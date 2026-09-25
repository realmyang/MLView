#!/usr/bin/env python3
"""Plan, prepare, seal, template the human review of, and summarize held-out MLView pilot runs.

Commands (dispatched by tools/workflow_eval.py; Campaign 2 specification, section 4):

* ``plan [--campaign C] [--stage 1|2|all] [--output P]`` prints the planned run IDs and conditions.
* ``run-prepare RUN --campaign C`` verifies the frozen campaign chain and builds one fresh run
  workspace plus its evidence directory under ``$MLVIEW_PILOT_DIR``.
* ``run-finish RUN --campaign C [--amend REASON]`` seals the run's evidence into ``record.json``.
* ``review-template RUN --campaign C`` creates the pending human review file of a completed run.
* ``summarize --campaign C --stage 1|all [--json] [--record]`` re-verifies every sealed run and
  computes the stage summary against the predefined targets.

This tool reads, hashes, compares, copies and renders. It never runs a model, never interprets
target code, and never writes a human decision, reviewer name, verdict, policy value or approval:
review and session files are created with ``pending`` values for people to fill, and every summary
says it is computed against predefined targets and is not an approval.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import eval_records as er  # noqa: E402
import fetch_workflow_repos  # noqa: E402
import install_skill  # noqa: E402
import package_skill  # noqa: E402
import workflow_candidate  # noqa: E402

ROOT = er.ROOT
PILOT_REL = "evals/workflow/pilot"
TASKS_REL = er.TASKS_REL
REPOSITORIES_REL = "evals/workflow/repositories.json"
SKILL_REL = "skills/mlview"
HELPER_REL = "skills/mlview/scripts/artifact.py"
ADJUDICATION_REL = "evals/workflow/decisions/development-adjudication.md"

RUN_FORMAT = "mlview-pilot-run/1"
SUMMARY_FORMAT = "mlview-pilot-summary/1"
PLAN_FORMAT = "mlview-pilot-plan/1"
FREEZE_FORMAT = "mlview-freeze/1"
REFERENCE_FORMAT = "mlview-frozen-reference/1"
REFERENCE_SET_FORMAT = "mlview-reference-set/1"
POLICY_FORMAT = "mlview-run-policy/1"
CANDIDATE_KIND = "pilot-candidate"
BUNDLE_ALGORITHM = "sha256-sorted-path-nul-bytes-nul"

NOT_APPROVAL = "computed against the predefined targets; not an approval"
PILOT_DIR_REMEDY = "export MLVIEW_PILOT_DIR=~/mlview-pilot"
GO_TEXT = ("Stage 1 met every predefined target. This permits collecting the 48 repeats; it is not a pilot "
           "pass (README.md:73-74).")
INVALID_RUN_NOTE = "the owner may record an invalidation"
SUMMARY_NOTE = ("Computed from sealed run records and named human reviews against the predefined targets; "
                "not an approval. Tool checks are not semantic accuracy, human review or live-host validation.")


def caveats(tasks: int, hosts: int, repetitions: int) -> list[str]:
    """The fixed clustering caveats of section 4.8, with this campaign's counts (for the committed
    manifest: 24 runs, 8 scenarios, 3 hosts, 72 runs)."""
    stage1, total = tasks * hosts, tasks * hosts * repetitions
    return [
        f"The {stage1} Stage 1 runs are {tasks} pinned scenarios \u00d7 {hosts} configured host workflows, one session "
        "each. They are not a sample of repositories or sessions, and the results describe these scenarios only.",
        "Claims are clustered within runs, and runs within tasks, so pooled precision weights verbose artifacts more. "
        "Macro means and leave-one-task-out ranges show the sensitivity. No confidence intervals or significance tests "
        f"are given, because {tasks} task clusters cannot support them.",
        "A host means host + model + settings, not an isolated model (reference-candidates/README.md:94-98).",
        f"Stage 2 repeats measure within-scenario variation; {total} runs are not {total} independent tasks "
        "(README.md:101-102).",
        "Each run has a single human reviewer, and verdicts are human judgements, not tool judgements. Disputed "
        "essential facts are listed.",
        "Workspaces contain only the manifest's sparse paths. For example, the upstream root AGENTS.md/CLAUDE.md of "
        "transformers, scikit-learn and diffusers are absent. Reachability of earlier evidence and user-level host "
        "configuration are recorded, not prevented.",
    ]


STATUSES = ("completed", "failed", "timed-out", "blocked")
FAILURE_KINDS = ("no-publication", "repair-budget", "host-error", "cancelled", "setup", "protocol")
QUALIFIED_POLICIES = ("not-supported", "supported", "excluded")
CLAIM_VERDICTS = {"supported", "qualified", "unsupported", "no-claim"}
COUNTED_VERDICTS = ("supported", "qualified", "unsupported")
SEVERITY_VERDICTS = {"agree", "too-high", "too-low"}
ESSENTIAL_VERDICTS = {"covered", "partial", "missing", "contradicted"}
UNKNOWN_VERDICTS = {"stated", "not-stated"}
DEFECT_VERDICTS = {"found", "missed"}
USABILITY_VERDICTS = {"clear", "partial", "missing"}
TASK_VERDICTS = {"useful", "partly", "not-useful"}
FALSE_ACCUSATION_SEVERITIES = {"high", "medium", "low"}
USABILITY_KEYS = ("dataOrigin", "updatedParametersAndFitState", "losses", "evaluationBoundaries", "outputs",
                  "uncertainty")
TARGET_LABELS = {
    "structurallyValid": "Structurally valid published artifacts",
    "exactAnchors": "Exact anchors",
    "supportedClaimPrecision": "Supported claims",
    "essentialFactRecall": "Essential-fact recall (all planned runs)",
    "knownUnresolvedQualified": "Known unresolved stated",
    "highSeverityFalseAccusations": "High-severity false accusations",
}
TARGET_IDS = {key: f"T{index}" for index, key in enumerate(er.PILOT_TARGET_KEYS, 1)}

# Evidence directory layout (section 4.1). Every name is relative to evidence/<run>/.
PROMPT_FILE = "PROMPT.txt"
SESSION_FILE = "session.md"
BEFORE_FILE = "workspace-before.json"
AFTER_FILE = "workspace-after.json"
DOCTOR_FILE = "doctor.json"
ARTIFACT_FILE = "artifact.mlview.json"
PARTIAL_FILE = "partial-artifact.mlview.json"
CHANGES_DIR = "workspace-changes"
RECORD_FILE = "record.json"
REVIEW_FILE = "review.md"
CHANGES_FILE = "workspace-changes.json"
MACHINE_FILES = frozenset({PROMPT_FILE, SESSION_FILE, BEFORE_FILE, AFTER_FILE, DOCTOR_FILE, ARTIFACT_FILE,
                           PARTIAL_FILE, RECORD_FILE, REVIEW_FILE, CHANGES_FILE})
PREVIOUS_RECORD = "record.previous-{n}.json"
SKILL_DESTINATIONS = {"claude-code": ".claude/skills/mlview"}
DEFAULT_SKILL_DESTINATION = ".agents/skills/mlview"
MACHINE_PATH_RE = re.compile(r"/Users/|/home/|/private/|(?<![A-Za-z])[A-Za-z]:\\")
HEX64_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})", re.ASCII)
TIME_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})", re.ASCII)
MINUTES_RE = re.compile(r"\d+(?:\.\d+)?", re.ASCII)
WHOLE_RE = re.compile(r"\d+", re.ASCII)
PYTHON_RE = re.compile(r"(\d+)\.(\d+)", re.ASCII)
SPLIT_RE = re.compile(r"(?P<base>.+?)#(?P<n>[0-9]+)")
RESPONSE_RE = re.compile(r"response:(?P<line>[0-9]+)(?:-(?P<end>[0-9]+))?(?:#(?P<n>[0-9]+))?", re.ASCII)
DEVIATION_RE = re.compile(r"(?P<text>.+?)\s+(?:—|–|--)\s+invalidates:\s*(?P<flag>\S+)\s*", re.IGNORECASE)


class PilotError(Exception):
    """A refusal with one message that says what to do next."""


class IntegrityError(Exception):
    """Evidence-integrity failures (section 4.5 A-C): every problem is listed and no decision is issued."""

    def __init__(self, problems: list[str]):
        super().__init__(f"{len(problems)} integrity problem(s)")
        self.problems = problems


def _now() -> str:
    """The current UTC time; tests replace this function to make outputs deterministic."""
    return er.rfc3339_utc_now()


# --------------------------------------------------------------------------------------------
# Small helpers


def _json_loads(data: bytes, what: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{what} is not valid UTF-8 JSON ({exc})") from None


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def _one_line(text: object, limit: int = 240) -> str:
    value = " ".join(str(text).split())
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _fold(value: object) -> str:
    return " ".join(str(value).split()).casefold()


def _git_run(root: Path, *args: str) -> subprocess.CompletedProcess:
    command = ["git", "-c", "protocol.allow=never", "-C", str(root), *args]
    try:
        return subprocess.run(command, capture_output=True, env=er._git_env(), check=False)
    except OSError as exc:
        raise PilotError(f"cannot run git: {exc}") from exc


def _git_text(root: Path, *args: str) -> str | None:
    result = _git_run(root, *args)
    return result.stdout.decode("utf-8", "replace").strip() if result.returncode == 0 else None


def _head(root: Path) -> str | None:
    return _git_text(root, "rev-parse", "--verify", "HEAD")


def _show_at_head(root: Path, rel: str) -> bytes | None:
    head = _head(root)
    if head is None:
        return None
    try:
        return er.git_show(root, head, rel)
    except ValueError:
        return None


def _corpus_root(root: Path) -> Path:
    configured = os.environ.get("MLVIEW_PUBLIC_CORPUS_DIR")
    return Path(configured).expanduser().resolve() if configured else Path(root) / ".public-corpus"


def _pilot_dir(value: str | None) -> Path:
    raw = value or os.environ.get("MLVIEW_PILOT_DIR")
    if not raw:
        raise PilotError(f"MLVIEW_PILOT_DIR is not set; run evidence lives outside every Git checkout: {PILOT_DIR_REMEDY}")
    return Path(raw).expanduser().absolute()


def _verify_repo(repo: dict, corpus_root: Path) -> dict:
    """fetch_workflow_repos.verify_repo (section 5.3), which never modifies the checkout."""
    verify = getattr(fetch_workflow_repos, "verify_repo", None)
    if verify is None:
        return {"name": repo.get("name"), "ok": False,
                "error": "fetch_workflow_repos.verify_repo is not available in this build"}
    try:
        result = verify(repo, corpus_root)
    except (getattr(fetch_workflow_repos, "FetchError", ValueError), ValueError, OSError) as exc:
        return {"name": repo.get("name"), "ok": False, "error": str(exc)}
    if not isinstance(result, dict):
        return {"name": repo.get("name"), "ok": False, "error": "verify_repo returned no report"}
    return result


def _verify_detail(result: dict) -> str:
    sentences = result.get("problems")
    if isinstance(sentences, list) and sentences and all(isinstance(item, str) for item in sentences):
        return "; ".join(sentences)  # fetch_workflow_repos.verify_repo: one sentence with a remedy per failure
    parts = []
    for key in ("error", "head", "clean", "sparseMatches", "missing", "extraMaterialized", "blobMismatches"):
        value = result.get(key)
        if key in ("clean", "sparseMatches") and value is False:
            parts.append(f"{key}: false")
        elif key not in ("clean", "sparseMatches") and value not in (None, [], "", True):
            shown = ", ".join(map(str, value[:5])) + (" ..." if len(value) > 5 else "") if isinstance(value, list) else value
            parts.append(f"{key}: {shown}")
    return "; ".join(parts) or "not ok"


def _skill_destination(host: str) -> str:
    return SKILL_DESTINATIONS.get(host, DEFAULT_SKILL_DESTINATION)


def _parse_time(value: object, helper: ModuleType | None = None) -> datetime | None:
    """An aware datetime for a helper-valid RFC 3339 time; None otherwise."""
    if not isinstance(value, str) or not er.is_rfc3339(value, helper):
        return None
    match = TIME_RE.fullmatch(value)
    if not match:
        return None
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    fraction = match.group(7)
    micro = int((fraction[1:] + "000000")[:6]) if fraction else 0
    zone = match.group(8)
    if zone == "Z":
        tz = timezone.utc
    else:
        sign = 1 if zone[0] == "+" else -1
        tz = timezone(sign * timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6])))
    return datetime(year, month, day, hour, minute, second, micro, tzinfo=tz)


def _valid_date(value: str) -> bool:
    match = DATE_RE.fullmatch(value)
    if not match:
        return False
    try:
        datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return False
    return True


def _python_ok(value: object) -> bool:
    match = PYTHON_RE.search(str(value or ""))
    return bool(match) and (int(match.group(1)), int(match.group(2))) >= (3, 10)


def _create_file(path: Path, data: bytes) -> None:
    """Exclusive create without fsync (workspace files are temporary)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as stream:
        stream.write(data)


def _write_or_same(path: Path, data: bytes) -> None:
    """Create ``path`` exclusively; an existing file is accepted only when it holds exactly ``data``
    (a run-finish that stopped half way may be repeated)."""
    try:
        er.write_exclusive(path, data)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise PilotError(f"{path.name} already exists with different content; it is never overwritten") from None


def _workspace_hashes(workspace: Path) -> dict[str, str]:
    """``{relative path: sha256}`` for every file of a workspace. A symbolic link is listed as
    ``symlink:<sha256 of its target text>`` and never followed; other special files as ``special``."""
    found: dict[str, str] = {}
    for directory, subdirs, files in os.walk(workspace, followlinks=False):
        base = Path(directory)
        for name in list(subdirs):
            if (base / name).is_symlink():
                subdirs.remove(name)
                files.append(name)
        for name in files:
            path = base / name
            rel = path.relative_to(workspace).as_posix()
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode):
                found[rel] = "symlink:" + er.sha256_bytes(os.readlink(path).encode("utf-8", "surrogateescape"))
            elif stat.S_ISREG(info.st_mode):
                found[rel] = er.sha256_file(path)
            else:
                found[rel] = "special"
    return dict(sorted(found.items()))


def _isolation_findings(pilot_dir: Path, root: Path) -> list[str]:
    """Why the pilot directory is not isolated, without machine paths (for sealed records)."""
    findings = []
    for reason in er.outside_repositories(pilot_dir, root):
        if "inside the MLView checkout" in reason:
            findings.append("the pilot directory is inside the MLView checkout")
        elif "Git" in reason:
            findings.append("the pilot directory is inside a Git work tree")
        else:
            name = next((item for item in er.INSTRUCTION_FILES if reason.split(" would be read")[0].endswith(item)), "an instruction file")
            findings.append(f"{name} in the pilot directory or a parent would be read by a host as instructions")
    return sorted(set(findings))


# --------------------------------------------------------------------------------------------
# The frozen campaign chain (section 4.5 A)


@dataclass
class Campaign:
    root: Path
    name: str
    candidate: dict
    candidate_sha256: str
    commit: str
    tasks: dict
    freeze: dict
    freeze_sha256: str
    reference_set_sha256: str
    reference_revision: str
    references: dict[str, dict]
    policy: dict
    files: dict[str, bytes]
    helper: ModuleType
    repositories: dict[str, dict]
    budget_minutes: int = 0
    repair_limit: int = 0
    retries: int = 0
    qualified_policy: str = "not-supported"
    per_host: bool = False
    baselines_planned: bool = False
    adjudication_required: bool = False
    artifact_path: str = "pilot.mlview.json"
    thresholds: dict[str, float] = field(default_factory=dict)

    @property
    def heldout(self) -> list[dict]:
        return [task for task in self.tasks["tasks"] if task.get("split") == "heldout"]

    def task(self, task_id: str) -> dict:
        return next(task for task in self.heldout if task["id"] == task_id)

    def host_policy(self, host: str) -> dict:
        return self.policy["hosts"][host]

    def prompt_rel(self, task_id: str, condition: str) -> str:
        return f"prompts/{'skill' if condition == 'skill' else 'baseline'}/{task_id}.txt"

    def essential_ids(self, task_id: str) -> list[str]:
        return list(self.references[task_id]["essentialFactIds"])

    def unknown_ids(self, task_id: str) -> list[str]:
        return [item["id"] for item in self.references[task_id]["knownUnresolved"] if item.get("runsMustState") is True]

    def plan(self) -> list[dict]:
        return planned_runs(self.tasks, baselines=self.baselines_planned)


def _campaign_dir(root: Path, name: str) -> Path:
    return Path(root) / PILOT_REL / name


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not er.NAME_RE.fullmatch(name):
        raise PilotError(f"not a campaign name: {name!r} (for example pilot-01)")


def _candidate_problems(candidate: object, name: str) -> list[str]:
    """Structural checks of candidate snapshot v2 that this tool relies on (section 3.2)."""
    if not isinstance(candidate, dict):
        return ["candidate.json: not a JSON object"]
    problems = []
    if candidate.get("version") != 2 or candidate.get("kind") != CANDIDATE_KIND:
        problems.append(f'candidate.json: summarize and run-prepare need version 2, kind "{CANDIDATE_KIND}" '
                        f"(found version {candidate.get('version')!r}, kind {candidate.get('kind')!r}); a "
                        "development snapshot is refused")
    if candidate.get("campaign") != name:
        problems.append(f"candidate.json: campaign is {candidate.get('campaign')!r}, not {name}")
    if candidate.get("pilotApproved") is not False:
        problems.append("candidate.json: pilotApproved must be the constant false")
    source = candidate.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("commit"), str) or not er.SHA1_RE.fullmatch(source["commit"]):
        problems.append("candidate.json: source.commit must be a full 40-hex commit")
    else:
        if source.get("clean") is not True:
            problems.append("candidate.json: source.clean must be true (a pilot candidate is captured on a clean tree)")
        if _parse_time(source.get("capturedAt")) is None:
            problems.append("candidate.json: source.capturedAt must be an RFC 3339 time")
    skill = candidate.get("skill")
    files = skill.get("files") if isinstance(skill, dict) else None
    if (not isinstance(skill, dict) or skill.get("algorithm") != BUNDLE_ALGORITHM
            or not isinstance(skill.get("sha256"), str) or not isinstance(files, list)
            or not all(isinstance(item, dict) and isinstance(item.get("path"), str) for item in files)):
        problems.append("candidate.json: skill must be a portable skill identity with files")
    components = candidate.get("components")
    if (not isinstance(components, list)
            or not all(isinstance(item, dict) and isinstance(item.get("path"), str)
                       and isinstance(item.get("sha256"), str) for item in components)):
        problems.append("candidate.json: components must be a list of {path, sha256, bytes}")
    if not isinstance(candidate.get("referenceRevision"), str) or not er.REVISION_RE.fullmatch(candidate["referenceRevision"]):
        problems.append('candidate.json: referenceRevision must be "sha256:" followed by 64 hex digits')
    return problems


def _informational(line: str) -> bool:
    """Lines of workflow_candidate.check that report drift at HEAD rather than a record defect."""
    folded = line.strip().casefold()
    return folded.startswith(("info:", "information:", "drift", "note:"))


def load_campaign(root: Path, name: str) -> Campaign:
    """Read and verify every frozen input of a campaign at the candidate's source commit.

    Raises IntegrityError with every problem found, or PilotError when there is no candidate."""
    root = Path(root)
    _check_name(name)
    path = _campaign_dir(root, name) / "candidate.json"
    if not path.is_file() or path.is_symlink():
        raise PilotError(f"{PILOT_REL}/{name}/candidate.json does not exist; capture the pilot candidate "
                         f"(python tools/workflow_candidate.py --campaign {name} --build-vsix) and commit it first")
    candidate_bytes = path.read_bytes()
    try:
        candidate = _json_loads(candidate_bytes, "candidate.json")
    except ValueError as exc:
        raise IntegrityError([str(exc)]) from None
    problems = _candidate_problems(candidate, name)
    if problems:
        raise IntegrityError(problems)
    try:
        defects = workflow_candidate.check(candidate, root)
    except (ValueError, TypeError, OSError, KeyError) as exc:
        defects = [f"cannot be checked: {exc}"]
    problems.extend(f"candidate.json: {line}" for line in defects or [] if not _informational(str(line)))
    commit = candidate["source"]["commit"]
    shallow = _git_text(root, "rev-parse", "--is-shallow-repository")
    if shallow == "true":
        raise IntegrityError(["this checkout is a shallow clone; fetch the full history (git fetch --unshallow) so the "
                              "candidate commit and its ancestry can be read"])
    if _git_run(root, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        raise IntegrityError([f"candidate source commit {commit[:12]} is not in this repository; fetch the full history"])
    ancestry = _git_run(root, "merge-base", "--is-ancestor", commit, "HEAD")
    if ancestry.returncode != 0:
        problems.append(f"candidate source commit {commit[:12]} is not an ancestor of HEAD")
    components = {item["path"]: item for item in candidate["components"]}
    campaign_rel = f"{PILOT_REL}/{name}"

    def read_component(rel: str) -> bytes | None:
        entry = components.get(rel)
        if entry is None:
            problems.append(f"candidate.json: component {rel} is not pinned")
            return None
        try:
            data = er.git_show(root, commit, rel)
        except ValueError:
            problems.append(f"{rel} does not exist at the candidate commit {commit[:12]}")
            return None
        if er.sha256_bytes(data) != entry["sha256"]:
            problems.append(f"{rel} at {commit[:12]} differs from its candidate hash")
        return data

    tasks_bytes = read_component(TASKS_REL)
    repositories_bytes = read_component(REPOSITORIES_REL)
    freeze_bytes = read_component(f"{campaign_rel}/freeze.json")
    helper_bytes = None
    helper_entry = next((item for item in candidate["skill"]["files"] if item.get("path") == "scripts/artifact.py"), None)
    if helper_entry is None:
        problems.append("candidate.json: the skill identity has no scripts/artifact.py")
    else:
        try:
            helper_bytes = er.git_show(root, commit, HELPER_REL)
        except ValueError:
            problems.append(f"{HELPER_REL} does not exist at the candidate commit")
        else:
            if er.sha256_bytes(helper_bytes) != helper_entry.get("sha256"):
                problems.append(f"{HELPER_REL} at {commit[:12]} differs from candidate.skill scripts/artifact.py")
    if problems or tasks_bytes is None or repositories_bytes is None or freeze_bytes is None or helper_bytes is None:
        raise IntegrityError(problems)
    try:
        tasks = _json_loads(tasks_bytes, TASKS_REL)
        repositories = _json_loads(repositories_bytes, REPOSITORIES_REL)
        freeze = _json_loads(freeze_bytes, "freeze.json")
    except ValueError as exc:
        raise IntegrityError(problems + [str(exc)]) from None
    problems.extend(f"{TASKS_REL} at the candidate commit: {item}" for item in er.check_task_manifest(tasks))
    pilot_freeze = tasks.get("pilotFreeze") if isinstance(tasks, dict) else None
    if not isinstance(pilot_freeze, dict) or pilot_freeze.get("campaign") != name:
        problems.append(f"{TASKS_REL} at the candidate commit has no pilotFreeze for {name}")
    if not isinstance(freeze, dict) or freeze.get("format") != FREEZE_FORMAT or freeze.get("campaign") != name:
        problems.append(f'freeze.json: format must be "{FREEZE_FORMAT}" for campaign {name}')
    frozen_files = freeze.get("files") if isinstance(freeze, dict) else None
    if not isinstance(frozen_files, dict):
        problems.append("freeze.json: files must map campaign-relative paths to SHA-256")
        frozen_files = {}
    if problems:
        raise IntegrityError(problems)
    files: dict[str, bytes] = {}
    for rel, digest in sorted(frozen_files.items()):
        if not isinstance(rel, str) or er._path_problem(rel) or not isinstance(digest, str):
            problems.append(f"freeze.json: files entry {rel!r} is not a relative path with a hash")
            continue
        try:
            data = er.git_show(root, commit, f"{campaign_rel}/{rel}")
        except ValueError:
            problems.append(f"{campaign_rel}/{rel} does not exist at the candidate commit")
            continue
        if er.sha256_bytes(data) != digest:
            problems.append(f"{campaign_rel}/{rel} at {commit[:12]} differs from its freeze.json hash")
            continue
        files[rel] = data
    if "reference-set.json" not in files:
        problems.append("freeze.json: reference-set.json is not frozen")
    if "policy.json" not in files:
        problems.append("freeze.json: policy.json is not frozen")
    if problems:
        raise IntegrityError(problems)
    reference_set_sha = er.sha256_bytes(files["reference-set.json"])
    revision = "sha256:" + reference_set_sha
    for label, value in (("freeze.json referenceRevision", freeze.get("referenceRevision")),
                         ("candidate.json referenceRevision", candidate.get("referenceRevision")),
                         (f"{TASKS_REL} pilotFreeze.referenceRevision", pilot_freeze.get("referenceRevision"))):
        if value != revision:
            problems.append(f"{label} is not sha256(reference-set.json) ({revision[:19]}...)")
    try:
        reference_set = _json_loads(files["reference-set.json"], "reference-set.json")
        policy = _json_loads(files["policy.json"], "policy.json")
    except ValueError as exc:
        raise IntegrityError(problems + [str(exc)]) from None
    if not isinstance(reference_set, dict) or reference_set.get("format") != REFERENCE_SET_FORMAT:
        problems.append(f'reference-set.json: format must be "{REFERENCE_SET_FORMAT}"')
        reference_set = {}
    heldout = [task for task in tasks["tasks"] if task.get("split") == "heldout"]
    references: dict[str, dict] = {}
    set_entries = {entry.get("task"): entry for entry in reference_set.get("tasks") or [] if isinstance(entry, dict)}
    for task in heldout:
        rel = f"reference/{task['id']}.json"
        if rel not in files:
            problems.append(f"freeze.json: {rel} is not frozen")
            continue
        try:
            reference = _json_loads(files[rel], rel)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        problems.extend(_reference_problems(reference, task, name, rel))
        entry = set_entries.get(task["id"])
        if entry is None:
            problems.append(f"reference-set.json: no entry for {task['id']}")
        elif isinstance(reference, dict):
            if entry.get("sha256") != er.sha256_bytes(files[rel]):
                problems.append(f"reference-set.json: the {task['id']} hash differs from {rel}")
            if isinstance(reference.get("essentialFactIds"), list) and entry.get("essential") != len(reference["essentialFactIds"]):
                problems.append(f"reference-set.json: the {task['id']} essential count differs from {rel}")
        references[task["id"]] = reference
    try:
        helper = er.load_helper(helper_bytes)
    except (ValueError, SyntaxError) as exc:
        raise IntegrityError(problems + [f"the frozen helper cannot be loaded: {exc}"]) from None
    repos = {}
    for repo in (repositories.get("repos") if isinstance(repositories, dict) else None) or []:
        if isinstance(repo, dict) and isinstance(repo.get("name"), str):
            repos[repo["name"]] = repo
    for task in heldout:
        repo = repos.get(task.get("repository"))
        if repo is None:
            problems.append(f"{REPOSITORIES_REL}: no repository {task.get('repository')!r} for {task['id']}")
        elif repo.get("sha") != task.get("commit"):
            problems.append(f"{task['id']}: tasks.json commit differs from repositories.json sha")
        else:
            try:
                er.validate_sparse_patterns(repo.get("sparse") or [])
            except ValueError as exc:
                problems.append(f"{REPOSITORIES_REL} {repo['name']}: {exc}")
    campaign = Campaign(root=root, name=name, candidate=candidate, candidate_sha256=er.sha256_bytes(candidate_bytes),
                        commit=commit, tasks=tasks, freeze=freeze, freeze_sha256=er.sha256_bytes(freeze_bytes),
                        reference_set_sha256=reference_set_sha, reference_revision=revision, references=references,
                        policy=policy, files=files, helper=helper, repositories=repos)
    problems.extend(_apply_policy(campaign))
    for task in heldout:
        for condition in ("skill",) + (("baseline",) if campaign.baselines_planned else ()):
            if campaign.prompt_rel(task["id"], condition) not in files:
                problems.append(f"freeze.json: {campaign.prompt_rel(task['id'], condition)} is not frozen")
    if problems:
        raise IntegrityError(problems)
    return campaign


def _reference_problems(reference: object, task: dict, name: str, rel: str) -> list[str]:
    if not isinstance(reference, dict):
        return [f"{rel}: not a JSON object"]
    problems = []
    if reference.get("format") != REFERENCE_FORMAT or reference.get("task") != task["id"] or reference.get("campaign") != name:
        problems.append(f'{rel}: format must be "{REFERENCE_FORMAT}" for task {task["id"]} of {name}')
    if reference.get("repositoryCommit") != task.get("commit"):
        problems.append(f"{rel}: repositoryCommit differs from tasks.json")
    for key in ("facts", "essentialFactIds", "knownUnresolved", "nonDefects", "defects", "disputes"):
        if not isinstance(reference.get(key), list):
            problems.append(f"{rel}: {key} must be a list")
    if problems:
        return problems
    fact_ids = {fact.get("id") for fact in reference["facts"] if isinstance(fact, dict)}
    if not all(isinstance(item, str) and item in fact_ids for item in reference["essentialFactIds"]):
        problems.append(f"{rel}: every essentialFactIds entry must name a frozen fact")
    for group in ("knownUnresolved", "nonDefects", "defects"):
        if not all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in reference[group]):
            problems.append(f"{rel}: every {group} entry needs an id")
    ids = [item for item in reference["essentialFactIds"]] + [item.get("id") for item in reference["knownUnresolved"]
                                                             if isinstance(item, dict)]
    if len(set(ids)) != len(ids):
        problems.append(f"{rel}: essential and unknown IDs must be unique")
    return problems


def _policy_choice(value: object, true_words: tuple[str, ...], false_words: tuple[str, ...]) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        folded = value.strip().casefold()
        if folded in true_words:
            return True
        if folded in false_words:
            return False
    return None


def _policy_int(value: object) -> int | None:
    if _is_int(value):
        return value
    if isinstance(value, str) and WHOLE_RE.fullmatch(value.strip()):
        return int(value.strip())
    return None


def _apply_policy(campaign: Campaign) -> list[str]:
    """Read the frozen policy.json values this tool uses (section 1.9); problems name the key."""
    policy = campaign.policy
    problems: list[str] = []
    if not isinstance(policy, dict) or policy.get("format") != POLICY_FORMAT or policy.get("campaign") != campaign.name:
        return [f'policy.json: format must be "{POLICY_FORMAT}" for campaign {campaign.name}']

    def section(key: str) -> dict:
        value = policy.get(key)
        if not isinstance(value, dict):
            problems.append(f"policy.json: {key} must be an object")
            return {}
        return value

    hosts = section("hosts")
    for host in campaign.tasks["hosts"]:
        settings = hosts.get(host)
        if not isinstance(settings, dict) or not all(isinstance(settings.get(key), str) and settings[key].strip()
                                                     for key in ("model", "reasoning", "invocation")):
            problems.append(f"policy.json: hosts.{host} needs model, reasoning and invocation")
    budget = section("budget")
    for attribute, key, low, high in (("budget_minutes", "activeMinutes", 1, 240), ("repair_limit", "repairRounds", 0, 5),
                                      ("retries", "infrastructureRetries", 0, 1)):
        value = _policy_int(budget.get(key))
        if value is None or not low <= value <= high:
            problems.append(f"policy.json: budget.{key} must be a whole number from {low} to {high}")
        else:
            setattr(campaign, attribute, value)
    scoring = section("scoring")
    qualified = scoring.get("qualifiedClaims")
    if not isinstance(qualified, str) or qualified.strip().casefold() not in QUALIFIED_POLICIES:
        problems.append(f"policy.json: scoring.qualifiedClaims must be one of {', '.join(QUALIFIED_POLICIES)}")
    else:
        campaign.qualified_policy = qualified.strip().casefold()
    per_host = _policy_choice(scoring.get("perHostTargets"), ("yes", "true"), ("no", "false"))
    if per_host is None:
        problems.append("policy.json: scoring.perHostTargets must be yes or no")
    else:
        campaign.per_host = per_host
    conditions = section("conditions")
    full = len(campaign.heldout) * len(campaign.tasks["hosts"])
    baselines = _policy_int(conditions.get("baselineSessions"))
    if baselines not in (0, full):
        problems.append(f"policy.json: conditions.baselineSessions must be 0 or {full}")
    else:
        campaign.baselines_planned = baselines == full and full > 0
    adjudication = _policy_choice(conditions.get("developmentAdjudicationBeforeStage1"), ("required", "yes", "true"),
                                  ("not-required", "no", "false"))
    if adjudication is None:
        problems.append("policy.json: conditions.developmentAdjudicationBeforeStage1 must be required or not-required")
    else:
        campaign.adjudication_required = adjudication
    prompts = section("prompts")
    artifact_path = prompts.get("artifactPath", "pilot.mlview.json")
    if (not isinstance(artifact_path, str) or er._path_problem(artifact_path) or "/" in artifact_path
            or not artifact_path.endswith(".mlview.json")):
        problems.append("policy.json: prompts.artifactPath must be a *.mlview.json file name at the workspace root")
    else:
        campaign.artifact_path = artifact_path
    thresholds = campaign.tasks.get("pilotTargets") or {}
    campaign.thresholds = {key: thresholds[key] for key in er.PILOT_TARGET_KEYS if key in thresholds}
    targets = policy.get("targets")
    if isinstance(targets, dict):
        for key in er.PILOT_TARGET_KEYS:
            value = targets.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value != thresholds.get(key):
                problems.append(f"policy.json: targets.{key} differs from tasks.json pilotTargets")
    return problems


# --------------------------------------------------------------------------------------------
# Plan


def planned_runs(tasks: dict, *, baselines: bool) -> list[dict]:
    """Every run of a campaign: skill runs (task x host x repeat), then Stage 1 baselines if planned."""
    heldout = [task for task in tasks["tasks"] if task.get("split") == "heldout"]
    runs = []
    for task in heldout:
        for host in tasks["hosts"]:
            for repeat in range(1, tasks["repetitions"] + 1):
                runs.append({"id": f"{task['id']}:{host}:{repeat}", "task": task["id"], "host": host, "repeat": repeat,
                             "stage": 1 if repeat == 1 else 2, "condition": "skill",
                             "repository": task.get("repository"), "repositoryCommit": task.get("commit")})
    if baselines:
        for task in heldout:
            for host in tasks["hosts"]:
                runs.append({"id": f"{task['id']}:{host}:baseline:1", "task": task["id"], "host": host, "repeat": 1,
                             "stage": 1, "condition": "baseline", "repository": task.get("repository"),
                             "repositoryCommit": task.get("commit")})
    return runs


def _in_stage(run: dict, stage: str) -> bool:
    return stage == "all" or (stage == "1" and run["stage"] == 1) or (stage == "2" and run["stage"] == 2)


def plan_document(root: Path, campaign_name: str | None, stage: str) -> dict:
    root = Path(root)
    if campaign_name is None:
        tasks = _json_loads((root / TASKS_REL).read_bytes(), TASKS_REL)
        problems = er.check_task_manifest(tasks)
        if problems:
            raise PilotError(f"{TASKS_REL}: " + "; ".join(problems))
        runs, frozen = planned_runs(tasks, baselines=False), False
        note = ("Skill runs from the working-tree tasks.json. Baselines depend on the frozen run policy: "
                "use --campaign after the freeze. Nothing was run or recorded.")
    else:
        _check_name(campaign_name)
        tasks, baselines = _frozen_plan_inputs(root, campaign_name)
        runs, frozen = planned_runs(tasks, baselines=baselines), True
        note = "Planned runs of the frozen campaign. Nothing was run or recorded."
    selected = [run for run in runs if _in_stage(run, stage)]
    for run in selected:
        run["directory"] = er.run_dir_name(run["id"])
    counts = {"skill": sum(r["condition"] == "skill" for r in selected),
              "baseline": sum(r["condition"] == "baseline" for r in selected)}
    return {"format": PLAN_FORMAT, "campaign": campaign_name, "stage": stage, "frozen": frozen, "runs": selected,
            "counts": counts, "note": note}


def _frozen_plan_inputs(root: Path, name: str) -> tuple[dict, bool]:
    """The frozen tasks.json and whether baselines are planned: from the candidate chain when a
    candidate exists, otherwise from the committed freeze named by the working-tree tasks.json."""
    if (_campaign_dir(root, name) / "candidate.json").is_file():
        campaign = load_campaign(root, name)
        return campaign.tasks, campaign.baselines_planned
    tasks = _json_loads((root / TASKS_REL).read_bytes(), TASKS_REL)
    pointer = tasks.get("pilotFreeze") if isinstance(tasks, dict) else None
    if not isinstance(pointer, dict) or pointer.get("campaign") != name:
        raise PilotError(f"{TASKS_REL} has no pilotFreeze for {name}; freeze the campaign first "
                         f"(python tools/workflow_eval.py freeze --campaign {name})")
    campaign_dir = _campaign_dir(root, name)
    freeze = _json_loads((campaign_dir / "freeze.json").read_bytes(), "freeze.json")
    policy_bytes = (campaign_dir / "policy.json").read_bytes()
    if (freeze.get("files") or {}).get("policy.json") != er.sha256_bytes(policy_bytes):
        raise IntegrityError(["policy.json differs from its freeze.json hash"])
    policy = _json_loads(policy_bytes, "policy.json")
    conditions = policy.get("conditions") if isinstance(policy, dict) else None
    count = _policy_int((conditions or {}).get("baselineSessions"))
    full = len([t for t in tasks["tasks"] if t.get("split") == "heldout"]) * len(tasks["hosts"])
    if count not in (0, full):
        raise IntegrityError([f"policy.json: conditions.baselineSessions must be 0 or {full}"])
    return tasks, bool(count) and full > 0


# --------------------------------------------------------------------------------------------
# session.md (operator-authored; section 4.3)


def session_template(run_id: str, condition: str) -> bytes:
    baseline = condition == "baseline"
    lines = [
        f"# Session: {run_id}",
        "> Fill after the session. Times are RFC 3339 UTC (2026-10-10T09:02:11Z). Minutes may be decimal.",
        "> Status: completed (skill: pilot.mlview.json published; baseline: answer captured) | failed | timed-out | blocked",
        '> Failure: no-publication | repair-budget | host-error | cancelled | setup | protocol, then " — <detail>"',
    ]
    if baseline:
        lines.append("> Baseline: no MLView skill, plugin or artifact. transcript.txt is required and scored; Repair rounds, "
                     "Helper Python and UI log do not apply.")
    lines += [
        "Status: pending", "Failure:", "Started:", "Ended:", "Active minutes:", "Approval wait minutes:",
        "Repair rounds:", "Host version:", "Extension version:", "Model:", "Reasoning:", "Resolved model:",
        "Invocation:", "Helper Python:", "Usage:", "Transcript: transcript.txt",
        "UI log:" if baseline else "UI log: ui-log.md", "Prior attempts: 0",
        f"MLView available to host: {'no' if baseline else 'yes'}",
        '> Deviations: one line each, "<what happened> — invalidates: yes | no"',
        "## Deviations", "",
    ]
    return "\n".join(lines).encode("utf-8")


@dataclass
class SessionResult:
    problems: list[er.Problem]
    block: dict | None
    transcript: str | None = None
    ui_log: str | None = None

    @property
    def ready(self) -> bool:
        return self.block is not None and not any(p.level in (er.ERROR, er.TODO) for p in self.problems)


def check_session(record: er.Record, display: str, evidence_dir: Path | None, *,
                  run_id: str | None = None, helper: ModuleType | None = None) -> SessionResult:
    """The run-finish rules for session.md (section 4.3). ``block`` is the record.json session
    object (without file and sha256) when there is no error and the status is not pending."""
    problems: list[er.Problem] = []
    header = record.header

    def add(level: str, line: int, message: str, where: str = "header") -> None:
        problems.append(er.Problem(display, line, level, where, message))

    def line_of(key: str) -> int:
        item = header.field(key)
        return item.line if item is not None else header.line

    def value(key: str) -> str:
        item = header.field(key)
        return item.value.strip() if item is not None else ""

    ident = record.ident or ""
    if run_id is not None and ident != run_id:
        add(er.ERROR, header.line, f'the title must read "# Session: {run_id}"; restore the line the tool wrote.')
    if not er.RUN_ID_RE.fullmatch(ident):
        add(er.ERROR, header.line, "the title must name a pilot run, like # Session: pilot-nanogpt:codex:1.")
        return SessionResult(sorted(problems, key=lambda p: p.line), None)
    baseline = ":baseline:" in ident
    status_text = value("Status").casefold()
    status = None
    if status_text in ("", "pending"):
        add(er.TODO, line_of("Status"), "Status is still pending. After the session write completed, failed, timed-out or blocked.")
    elif status_text not in STATUSES:
        add(er.ERROR, line_of("Status"), f'"Status: {value("Status")}" is not a status. Write one of: {", ".join(STATUSES)}.')
    else:
        status = status_text
    completed = status == "completed"
    failure = None
    failure_text = value("Failure")
    if status in ("failed", "timed-out", "blocked"):
        if not failure_text:
            add(er.ERROR, line_of("Failure"), f'Status is {status}, so "Failure:" is needed: one of '
                                              f'{", ".join(FAILURE_KINDS)}, then " — <detail>".')
        else:
            kind, _pointers, detail = _split_reason(failure_text)
            if kind.casefold() not in FAILURE_KINDS:
                add(er.ERROR, line_of("Failure"), f'"Failure: {failure_text}" does not start with a failure kind. Write one of: '
                                                  f'{", ".join(FAILURE_KINDS)}, then " — <detail>".')
            else:
                failure = {"kind": kind.casefold(), "detail": detail}
    elif completed and failure_text:
        add(er.ERROR, line_of("Failure"), 'Status is completed, so "Failure:" must be empty.')

    def time_field(key: str) -> str | None:
        text = value(key)
        if not text:
            return None
        if _parse_time(text, helper) is None:
            add(er.ERROR, line_of(key), f'{key} "{text}" is not an RFC 3339 time; write it like 2026-10-10T09:02:11Z.')
            return None
        return text

    def minutes_field(key: str) -> float | None:
        text = value(key)
        if not text:
            return None
        if not MINUTES_RE.fullmatch(text):
            add(er.ERROR, line_of(key), f'{key} "{text}" is not a number of minutes (decimals allowed, like 16.5).')
            return None
        return float(text)

    def whole_field(key: str) -> int | None:
        text = value(key)
        if not text:
            return None
        if not WHOLE_RE.fullmatch(text):
            add(er.ERROR, line_of(key), f'{key} "{text}" is not a whole number.')
            return None
        return int(text)

    def text_field(key: str, unknown_allowed: bool = False) -> str | None:
        text = value(key)
        if not text or (unknown_allowed and text.casefold() == "unknown"):
            return None
        return text

    started, ended = time_field("Started"), time_field("Ended")
    if started and ended and _parse_time(ended, helper) < _parse_time(started, helper):
        add(er.ERROR, line_of("Ended"), "Ended is before Started.")
    active, waiting = minutes_field("Active minutes"), minutes_field("Approval wait minutes")
    repairs, prior = whole_field("Repair rounds"), whole_field("Prior attempts")
    available_text = value("MLView available to host").casefold()
    available = {"yes": True, "no": False}.get(available_text)
    if available_text and available is None:
        add(er.ERROR, line_of("MLView available to host"), "MLView available to host must be yes or no.")
    block = {
        "status": status, "failure": failure, "startedAt": started, "endedAt": ended, "activeMinutes": active,
        "approvalWaitMinutes": waiting, "repairRounds": repairs, "hostVersion": text_field("Host version"),
        "extensionVersion": text_field("Extension version"), "model": text_field("Model"),
        "reasoning": text_field("Reasoning"), "resolvedModel": text_field("Resolved model", True),
        "invocation": text_field("Invocation"), "helperPython": text_field("Helper Python"),
        "usage": text_field("Usage", True), "priorAttempts": prior, "mlviewAvailable": available,
        "deviations": [],
    }
    if completed:
        required = ["Started", "Ended", "Active minutes", "Approval wait minutes", "Host version", "Extension version",
                    "Model", "Reasoning", "Invocation", "Prior attempts", "MLView available to host"]
        if not baseline:
            required += ["Repair rounds", "Helper Python"]
        for key in required:
            if not value(key):
                add(er.ERROR, line_of(key), f'Status is completed but "{key}:" is empty.')
        if available is not None and available is baseline:
            add(er.ERROR, line_of("MLView available to host"),
                f'a completed {"baseline" if baseline else "skill"} session must say '
                f'"MLView available to host: {"no" if baseline else "yes"}".')
    if block["helperPython"] and not baseline and not PYTHON_RE.search(block["helperPython"]):
        add(er.ERROR, line_of("Helper Python"), 'Helper Python must give the version python3 reports, like "3.12.4".')
    transcript = ui_log = None
    for key, required_now in (("Transcript", completed and baseline), ("UI log", completed and not baseline)):
        name = value(key)
        if not name:
            if required_now:
                add(er.ERROR, line_of(key), f'Status is completed but "{key}:" is empty.')
            continue
        if er._path_problem(name) or name in MACHINE_FILES or name.split("/")[0] == CHANGES_DIR:
            add(er.ERROR, line_of(key), f'{key}: "{name}" must be a file name inside the evidence directory, other than the '
                                        "files the tool writes.")
            continue
        present = False
        if evidence_dir is not None:
            try:
                er.confined_file(evidence_dir, name)
                present = True
            except ValueError as exc:
                if required_now or "does not exist" not in str(exc):
                    add(er.ERROR, line_of(key), f"{key}: {exc}; save it in the evidence directory"
                                                + (" (a completed baseline is scored on its transcript)." if key == "Transcript"
                                                   else " (a completed skill run needs the live UI checklist)."))
        if present and not (key == "UI log" and baseline):
            if key == "Transcript":
                transcript = name
            else:
                ui_log = name
    deviations = record.section("Deviations")
    for item in deviations.lines if deviations is not None else []:
        text = f"{item.key}: {item.value}" if item.value else item.key
        match = DEVIATION_RE.fullmatch(text)
        flag = match.group("flag").casefold() if match else ""
        if not match or flag not in ("yes", "no"):
            add(er.ERROR, item.line, f'"{_one_line(text, 60)}" must end with " — invalidates: yes" or " — invalidates: no".',
                "Deviations")
            continue
        block["deviations"].append({"text": _one_line(match.group("text"), 500), "invalidates": flag == "yes"})
    problems.sort(key=lambda p: p.line)
    ok = status is not None and not any(p.level == er.ERROR for p in problems)
    return SessionResult(problems, block if ok else None, transcript, ui_log)


def _split_reason(value: str) -> tuple[str, list[str], str | None]:
    """``<word> [words] [— reason]`` without a vocabulary (failure kinds are checked by the caller)."""
    separator = er._REASON_SEPARATOR.search(value)
    head, reason = (value[:separator.start()], value[separator.end():].strip() or None) if separator else (value, None)
    words = head.split()
    return (words[0] if words else ""), words[1:], reason


# --------------------------------------------------------------------------------------------
# run-prepare (section 4.2)


def _committed_stage1(root: Path, campaign: Campaign) -> dict | None:
    data = _show_at_head(root, f"{PILOT_REL}/{campaign.name}/stage1-summary.json")
    if data is None:
        return None
    try:
        value = _json_loads(data, "stage1-summary.json")
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _stage1_go(summary: dict | None, campaign: Campaign) -> str | None:
    """None when a committed Stage 1 summary permits Stage 2, else the reason it does not."""
    if summary is None:
        return "there is no committed stage1-summary.json"
    decision = summary.get("decision") if isinstance(summary.get("decision"), dict) else {}
    if decision.get("value") != "go":
        return f"the committed Stage 1 decision is {decision.get('value')!r}, not go"
    if summary.get("candidateSha256") != campaign.candidate_sha256:
        return "the committed Stage 1 summary belongs to another candidate"
    if _parse_time(summary.get("generatedAt")) is None:
        return "the committed Stage 1 summary has no valid generatedAt"
    return None


def adjudication_status(root: Path) -> str | None:
    """None when the committed development adjudication is complete, else why it is not. Only the
    committed file counts; the full rules are checked by python tools/workflow_eval.py check."""
    data = _show_at_head(root, ADJUDICATION_REL)
    if data is None:
        return f"{ADJUDICATION_REL} is not committed"
    record, problems = er.parse_record(data, ADJUDICATION_REL)
    if record is None or record.kind != "Development adjudication" or any(p.level == er.ERROR for p in problems):
        return f"{ADJUDICATION_REL} has errors"
    if not (record.header.value("Reviewer") or "").strip():
        return f"{ADJUDICATION_REL} names no reviewer"
    task = record.section("Task")
    if task is None or (task.value("Review") or "").strip().casefold() != "complete":
        return f'{ADJUDICATION_REL} does not say "Review: complete"'
    for section in record.sections:
        if section.kind == "Task":
            continue
        for item in section.lines:
            if item.key.casefold() == "ledger":
                continue
            if not item.value.strip() or item.value.strip().split()[0].casefold() == "pending":
                return f"{ADJUDICATION_REL} still has pending items ({section.label}: {item.key})"
    return None


def run_prepare(root: Path, run_id: str, name: str, pilot_value: str | None, out: Callable[[str], None] = print) -> int:
    root = Path(root)
    try:
        directory = er.run_dir_name(run_id)
    except ValueError as exc:
        raise PilotError(str(exc)) from None
    pilot_dir = _pilot_dir(pilot_value)
    reasons = er.outside_repositories(pilot_dir, root)
    if reasons:
        raise PilotError("the pilot directory is not isolated: " + "; ".join(reasons)
                         + f". Choose a directory outside every Git checkout and instruction file: {PILOT_DIR_REMEDY}")
    campaign = load_campaign(root, name)
    planned = {run["id"]: run for run in campaign.plan()}
    run = planned.get(run_id)
    if run is None:
        raise PilotError(f"{run_id} is not a planned run of {name} (see python tools/workflow_eval.py plan --campaign {name})")
    if run["stage"] == 2:
        reason = _stage1_go(_committed_stage1(root, campaign), campaign)
        if reason is not None:
            raise PilotError(f"Stage 2 repeats need a committed Stage 1 summary whose decision is go for this candidate; {reason}")
    if run["stage"] == 1 and campaign.adjudication_required:
        reason = adjudication_status(root)
        if reason is not None:
            raise PilotError("the run policy requires the development adjudication before Stage 1; " + reason
                             + " (python tools/workflow_eval.py check development-adjudication)")
    task = campaign.task(run["task"])
    repo = campaign.repositories[task["repository"]]
    corpus = _corpus_root(root)
    repo_path = corpus / repo["name"]
    if not repo_path.is_dir():
        raise PilotError(f"the corpus repository {repo['name']} is missing; fetch it with python tools/fetch_workflow_repos.py")
    report = _verify_repo(repo, corpus)
    if not report.get("ok"):
        raise PilotError(f"the corpus repository {repo['name']} failed verification ({_verify_detail(report)}); "
                         "run python tools/fetch_workflow_repos.py --verify")
    head_skill = package_skill.bundle_identity(package_skill.canonical_files(root / SKILL_REL))
    if head_skill != campaign.candidate["skill"]:
        raise PilotError(f"the skill in this checkout differs from the candidate's; check out the candidate commit "
                         f"({campaign.commit[:12]}) before preparing runs")
    workspaces, evidence_root = pilot_dir / "workspaces", pilot_dir / "evidence"
    workspace, evidence = workspaces / directory, evidence_root / directory
    for path in (workspace, evidence):
        if os.path.lexists(path):
            raise PilotError(f"{path} already exists; every run is prepared once, in a fresh workspace")
    workspaces.mkdir(parents=True, exist_ok=True)
    evidence_root.mkdir(parents=True, exist_ok=True)
    os.mkdir(evidence)
    os.mkdir(workspace)
    try:
        tree = er.pinned_tree(repo_path, task["commit"])
        patterns = repo.get("sparse") or []
        copied = 0
        for rel in sorted(tree):
            if er.sparse_covers(patterns, rel):
                _create_file(workspace / rel, er.pinned_bytes(repo_path, task["commit"], rel, tree=tree))
                copied += 1
        installed = None
        if run["condition"] == "skill":
            destination = _skill_destination(run["host"])
            install_skill.install(workspace, destination)
            identity = package_skill.bundle_identity(package_skill.canonical_files(workspace / destination))
            if identity != campaign.candidate["skill"]:
                raise PilotError("the installed skill differs from the candidate's skill identity")
            installed = destination
        prompt = campaign.files[campaign.prompt_rel(run["task"], run["condition"])]
        er.write_exclusive(evidence / PROMPT_FILE, prompt)
        er.write_exclusive(evidence / BEFORE_FILE, er.canonical_json(_workspace_hashes(workspace)))
        er.write_exclusive(evidence / SESSION_FILE, session_template(run_id, run["condition"]))
    except BaseException as exc:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(evidence, ignore_errors=True)
        if isinstance(exc, (ValueError, OSError)):
            raise PilotError(f"could not prepare {run_id}: {exc}") from None
        raise
    settings = campaign.host_policy(run["host"])
    lines = [
        f"Prepared {run_id} (campaign {name}, stage {run['stage']}, {run['condition']}).",
        f"  workspace: {workspace}  ({copied} pinned files" + (f"; skill at {installed}" if installed else "") + ")",
        f"  evidence:  {evidence}",
        f"  prompt:    {evidence / PROMPT_FILE} (sha256 {er.sha256_bytes(prompt)[:12]}...)",
        "Operator checklist (these paths are printed only; they are never recorded):",
        "  1. Open the workspace in a new VS Code window (File > New Window, then Open Folder).",
        f"  2. Start a fresh {run['host']} session; never continue an earlier conversation.",
        f'  3. Use the policy settings: model "{settings["model"]}", reasoning "{settings["reasoning"]}", '
        f'invocation "{settings["invocation"]}".',
        "  4. In the host's terminal, check that python3 --version reports 3.10 or newer "
        f"(policy: {_one_line((campaign.policy.get('environment') or {}).get('helperPython', 'see run-policy'), 120)}).",
    ]
    vsix = campaign.candidate.get("vsix") if isinstance(campaign.candidate.get("vsix"), dict) else {}
    lines.append(f"  5. Install the candidate VSIX once ({vsix.get('file', 'mlview-<version>.vsix')}, from the pilot directory) "
                 "if this VS Code profile does not have it.")
    if run["condition"] == "baseline":
        lines.append("  6. Baseline: confirm that no MLView skill, plugin or artifact is available to the host "
                     "(no .agents/skills/mlview, .claude/skills/mlview or MLView plugin).")
    else:
        lines.append(f"  6. Send the invocation, then PROMPT.txt exactly. The artifact must be published to "
                     f"{campaign.artifact_path} at the workspace root.")
    lines += [
        f"  7. Afterwards save transcript.txt{'' if run['condition'] == 'baseline' else ' and ui-log.md'} in the evidence "
        "directory, fill session.md, then run:",
        f"     python tools/workflow_eval.py run-finish {run_id} --campaign {name}",
    ]
    for line in lines:
        out(line)
    return 0


# --------------------------------------------------------------------------------------------
# run-finish (section 4.2, 4.3)


def _file_entry(evidence: Path, rel: str) -> dict:
    data = er.confined_file(evidence, rel).read_bytes()
    return {"file": rel, "sha256": er.sha256_bytes(data), "bytes": len(data)}


def _tooling() -> dict:
    return {"tools/workflow_pilot.py": er.sha256_file(Path(__file__).resolve())}


def _session_or_fail(evidence: Path, run_id: str, helper: ModuleType, out: Callable[[str], None]) -> tuple[SessionResult, bytes]:
    try:
        raw = er.confined_file(evidence, SESSION_FILE).read_bytes()
    except ValueError as exc:
        raise PilotError(f"session.md: {exc}") from None
    display = str(evidence / SESSION_FILE)
    record, problems = er.parse_record(raw, display)
    if record is None or record.kind != "Session":
        for problem in problems:
            out(str(problem))
        raise PilotError("session.md is not a session file; it must start with the title the tool wrote")
    result = check_session(record, display, evidence, run_id=run_id, helper=helper)
    result.problems = sorted(problems + result.problems, key=lambda p: p.line)
    for problem in result.problems:
        out(str(problem))
    if any(p.level == er.ERROR for p in result.problems) or not result.ready:
        errors = sum(p.level == er.ERROR for p in result.problems)
        todos = sum(p.level == er.TODO for p in result.problems)
        raise PilotError(f"session.md is not ready ({errors} error(s), {todos} to do); fix it and run run-finish again")
    return result, raw


def _base_record(campaign: Campaign, run: dict, session: SessionResult, session_raw: bytes) -> dict:
    return {
        "format": RUN_FORMAT, "id": run["id"], "task": run["task"], "host": run["host"], "repeat": run["repeat"],
        "stage": run["stage"], "condition": run["condition"], "campaign": campaign.name,
        "candidateSha256": campaign.candidate_sha256, "referenceRevision": campaign.reference_revision,
        "repositoryCommit": run["repositoryCommit"],
        "session": {"file": SESSION_FILE, "sha256": er.sha256_bytes(session_raw), **session.block},
    }


def run_finish(root: Path, run_id: str, name: str, pilot_value: str | None, amend: str | None,
               out: Callable[[str], None] = print) -> int:
    root = Path(root)
    try:
        directory = er.run_dir_name(run_id)
    except ValueError as exc:
        raise PilotError(str(exc)) from None
    pilot_dir = _pilot_dir(pilot_value)
    campaign = load_campaign(root, name)
    run = {r["id"]: r for r in campaign.plan()}.get(run_id)
    if run is None:
        raise PilotError(f"{run_id} is not a planned run of {name}")
    evidence = pilot_dir / "evidence" / directory
    if evidence.is_symlink() or not evidence.is_dir():
        raise PilotError(f"{evidence} does not exist; prepare the run first (run-prepare {run_id} --campaign {name})")
    record_path = evidence / RECORD_FILE
    if amend is not None:
        if not amend.strip():
            raise PilotError("--amend needs a reason")
        if not record_path.is_file():
            raise PilotError(f"{run_id} is not sealed yet; run run-finish without --amend")
        session, session_raw = _session_or_fail(evidence, run_id, campaign.helper, out)
        return _amend(campaign, run, evidence, session, session_raw, amend.strip(), out)
    if os.path.lexists(record_path):
        raise PilotError(f"{run_id} is already sealed; to change the session facts run: python tools/workflow_eval.py "
                         f'run-finish {run_id} --campaign {name} --amend "<reason>"')
    session, session_raw = _session_or_fail(evidence, run_id, campaign.helper, out)
    status = session.block["status"]
    workspace = pilot_dir / "workspaces" / directory
    skill = run["condition"] == "skill"
    resumed = False
    if workspace.is_symlink():
        raise PilotError(f"{workspace} is a symbolic link; refusing to read or remove it")
    if not workspace.is_dir():
        if not (evidence / AFTER_FILE).is_file():
            raise PilotError(f"{workspace} does not exist; the workspace was removed before the run was sealed")
        resumed = True  # an earlier run-finish removed the workspace but did not seal
    artifact_entry = partial_entry = None
    changes: list[dict] = []
    if not resumed:
        if skill:
            source = workspace / campaign.artifact_path
            present = source.is_file() and not source.is_symlink()
            if status == "completed" and not present:
                raise PilotError(f"a completed skill run needs {campaign.artifact_path} at the workspace root; if nothing "
                                 'was published write "Status: failed" and "Failure: no-publication" in session.md')
            if present:
                data = source.read_bytes()
                target = ARTIFACT_FILE if status == "completed" else PARTIAL_FILE
                _write_or_same(evidence / target, data)
        before = _json_loads(er.confined_file(evidence, BEFORE_FILE).read_bytes(), BEFORE_FILE)
        after = _workspace_hashes(workspace)
        for rel in sorted(set(before) | set(after)):
            if campaign.helper.is_owned_path(rel) or before.get(rel) == after.get(rel):
                continue
            change = "added" if rel not in before else "removed" if rel not in after else "modified"
            entry: dict[str, Any] = {"path": rel, "change": change, "file": None, "sha256": None}
            if change != "removed":
                path = workspace / rel
                if path.is_file() and not path.is_symlink():
                    data = path.read_bytes()
                    copy = f"{CHANGES_DIR}/{rel}"
                    _write_or_same(evidence / copy, data)
                    entry.update(file=copy, sha256=er.sha256_bytes(data))
                else:
                    entry["sha256"] = after[rel]
            changes.append(entry)
        doctor, _ok = install_skill.doctor(workspace)
        _write_or_same(evidence / AFTER_FILE, er.canonical_json(after))
        _write_or_same(evidence / DOCTOR_FILE, er.canonical_json(doctor))
        # Verify every copy against the workspace before removing it.
        if skill and (evidence / ARTIFACT_FILE).is_file() and status == "completed":
            if (evidence / ARTIFACT_FILE).read_bytes() != (workspace / campaign.artifact_path).read_bytes():
                raise PilotError("the artifact copy differs from the workspace artifact")
        for entry in changes:
            if entry["file"] and (evidence / entry["file"]).read_bytes() != (workspace / entry["path"]).read_bytes():
                raise PilotError(f"the copy of {entry['path']} differs from the workspace")
        _write_or_same(evidence / CHANGES_FILE, er.canonical_json(changes))
    else:
        changes = _json_loads(er.confined_file(evidence, CHANGES_FILE).read_bytes(), CHANGES_FILE)
    if skill and status == "completed":
        artifact_entry = _file_entry(evidence, ARTIFACT_FILE)
    if skill and status != "completed" and (evidence / PARTIAL_FILE).is_file():
        partial_entry = _file_entry(evidence, PARTIAL_FILE)
    removed = True
    if workspace.is_dir() and not workspace.is_symlink():
        try:
            shutil.rmtree(workspace)
        except OSError as exc:
            removed = False
            out(f"warning: could not remove the workspace ({exc}); remove it by hand")
    record = _base_record(campaign, run, session, session_raw)
    record.update({
        "prompt": {"file": PROMPT_FILE, "sha256": _file_entry(evidence, PROMPT_FILE)["sha256"],
                   "frozen": campaign.prompt_rel(run["task"], run["condition"])},
        "workspace": {"name": directory, "removed": removed,
                      "before": {k: v for k, v in _file_entry(evidence, BEFORE_FILE).items() if k != "bytes"},
                      "after": {k: v for k, v in _file_entry(evidence, AFTER_FILE).items() if k != "bytes"},
                      "changes": {k: v for k, v in _file_entry(evidence, CHANGES_FILE).items() if k != "bytes"},
                      "changedProjectFiles": changes, "isolation": _isolation_findings(pilot_dir, root)},
        "evidence": {
            "artifact": artifact_entry,
            "transcript": _file_entry(evidence, session.transcript) if session.transcript else None,
            "uiLog": _file_entry(evidence, session.ui_log) if (skill and session.ui_log) else None,
            "doctor": _file_entry(evidence, DOCTOR_FILE),
            "partialArtifact": partial_entry,
        },
        "sealedAt": _now(), "tooling": _tooling(), "amendments": [],
    })
    data = er.canonical_json(record)
    er.write_exclusive(record_path, data)
    out(f"Sealed {run_id}: {RECORD_FILE} sha256 {er.sha256_bytes(data)[:12]}...; status {status}; "
        f"{len(changes)} changed project file(s); workspace {'removed' if removed else 'NOT removed'}.")
    if status == "completed":
        out(f"Next: python tools/workflow_eval.py review-template {run_id} --campaign {name}")
    return 0


MACHINE_EVIDENCE = ("artifact", "doctor", "partialArtifact")


def _amend(campaign: Campaign, run: dict, evidence: Path, session: SessionResult, session_raw: bytes, reason: str,
           out: Callable[[str], None]) -> int:
    record_path = evidence / RECORD_FILE
    previous_bytes = record_path.read_bytes()
    previous = _json_loads(previous_bytes, RECORD_FILE)
    skill = run["condition"] == "skill"
    status = session.block["status"]
    captured = previous["evidence"].get("artifact") or previous["evidence"].get("partialArtifact")
    published = captured if captured is not None and captured.get("file") == ARTIFACT_FILE else None
    if skill and status == "completed" and published is None:
        raise PilotError("a completed skill run needs the artifact captured as published when the run was sealed; a run "
                         "sealed without one cannot become completed by amendment")
    for key in MACHINE_EVIDENCE:
        entry = previous["evidence"].get(key)
        if entry is not None and _file_entry(evidence, entry["file"]) != entry:
            raise PilotError(f"machine-written evidence changed since sealing: {entry['file']}; amendments re-read only "
                             "session.md, the transcript and the UI log")
    for key in ("before", "after", "changes"):
        entry = previous["workspace"][key]
        if {k: v for k, v in _file_entry(evidence, entry["file"]).items() if k != "bytes"} != entry:
            raise PilotError(f"machine-written evidence changed since sealing: {entry['file']}")
    if _file_entry(evidence, PROMPT_FILE)["sha256"] != previous["prompt"]["sha256"]:
        raise PilotError("PROMPT.txt changed since sealing")
    record = dict(previous)
    record.update(_base_record(campaign, run, session, session_raw))
    record["evidence"] = dict(previous["evidence"])
    if skill and published is not None:
        # The artifact captured at sealing is scored only while the status is completed (section 4.3).
        record["evidence"]["artifact"] = published if status == "completed" else None
        record["evidence"]["partialArtifact"] = None if status == "completed" else published
    record["evidence"]["transcript"] = _file_entry(evidence, session.transcript) if session.transcript else None
    record["evidence"]["uiLog"] = _file_entry(evidence, session.ui_log) if (skill and session.ui_log) else None
    number = len(previous.get("amendments") or []) + 1
    _write_or_same(evidence / PREVIOUS_RECORD.format(n=number), previous_bytes)
    record["amendments"] = list(previous.get("amendments") or []) + [
        {"at": _now(), "reason": _one_line(reason, 500), "previous": er.sha256_bytes(previous_bytes)}]
    record["tooling"] = _tooling()
    data = er.canonical_json(record)
    er.write_atomic(record_path, data)
    out(f"Amended {run['id']} (amendment {number}); the previous record is kept as {PREVIOUS_RECORD.format(n=number)} "
        f"(sha256 {er.sha256_bytes(previous_bytes)[:12]}...).")
    return 0


# --------------------------------------------------------------------------------------------
# Human run review (section 4.4)


def artifact_elements(doc: dict) -> dict[str, dict]:
    """Every reviewable element of an artifact by pointer, in document order: nodes, edges,
    findings, coverage and configuration (when present). Duplicate IDs keep the first element."""
    elements: dict[str, dict] = {}
    for kind, collection in (("node", "nodes"), ("edge", "edges"), ("finding", "findings")):
        items = doc.get(collection)
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
                pointer = f"{kind}:{item['id']}"
                if pointer not in elements:
                    elements[pointer] = {"kind": kind, "item": item, "basis": item.get("basis"),
                                         "severity": item.get("severity") if kind == "finding" else None}
    if isinstance(doc.get("coverage"), dict):
        elements["coverage"] = {"kind": "coverage", "item": doc["coverage"], "basis": "observed", "severity": None}
    request = doc.get("request")
    if isinstance(request, dict) and "configuration" in request:
        elements["configuration"] = {"kind": "configuration", "item": request["configuration"], "basis": "observed",
                                     "severity": None}
    return elements


def artifact_pointers(doc: dict) -> set[str]:
    """Pointers a reviewer may cite as support: every element plus evidence:<id> and phase:<id>."""
    pointers = set(artifact_elements(doc))
    for kind, collection in (("evidence", "evidence"), ("phase", "phases")):
        items = doc.get(collection)
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                pointers.add(f"{kind}:{item['id']}")
    return pointers


def _frozen_text(item: dict, *keys: str) -> str:
    return next((str(item[key]) for key in keys if isinstance(item.get(key), str) and item[key]), "")


def review_template_text(run: dict, record: dict, reference: dict, artifact: dict | None) -> str:
    run_id = run["id"]
    baseline = run["condition"] == "baseline"
    facts = {fact.get("id"): fact for fact in reference["facts"] if isinstance(fact, dict)}
    unknowns = {item["id"]: item for item in reference["knownUnresolved"]}
    lines = [f"# Run review: {run_id}",
             "> Written by review-template. Run, " + ("Transcript" if baseline else "Artifact")
             + " and Reference are checked against the sealed run; do not edit them.",
             '> Fill Reviewer and Date, replace every "pending", then check: python tools/workflow_eval.py check <this file>',
             f"Run: {run_id}"]
    if baseline:
        lines.append(f"Transcript: {record['evidence']['transcript']['sha256']}")
    else:
        lines.append(f"Artifact: {record['evidence']['artifact']['sha256']}")
    lines += [f"Reference: {record['referenceRevision']}", "Reviewer:", "Date:", "Transcribed by:", "", "## Claims"]
    non_defects = [f"> {item['id']}: {_one_line(_frozen_text(item, 'text', 'wording', 'claim'))}" for item in reference["nonDefects"]]
    if baseline:
        lines += ['> Add one line per claim in the answer: "response:LINE-END: <verdict>" (lines of the transcript, for example',
                  '> response:12-14: supported). Verdicts: supported | qualified | unsupported | no-claim. Add " — <reason>"',
                  '> to anything except supported/no-claim. At least one line. Several claims on the same lines: "response:12-14#2: ...".',
                  "> Frozen non-defects (for judging false accusations):"] + non_defects
    else:
        lines += ['> Verdicts: supported | qualified | unsupported | no-claim. Add " — <reason>" to anything except supported/no-claim.',
                  '> Several claims in one element: add "<pointer>#2: <verdict>" lines. Frozen non-defects (for judging findings):']
        lines += non_defects
        for pointer, element in artifact_elements(artifact).items():
            item, kind = element["item"], element["kind"]
            if kind == "node":
                lines.append(f'> [{item.get("basis")}] node {item["id"]} "{_one_line(item.get("label", ""), 80)}": '
                             f'{_one_line(item.get("detail", ""))}')
            elif kind == "edge":
                lines.append(f'> [{item.get("basis")}] edge {item["id"]} "{_one_line(item.get("label", ""), 80)}": '
                             f'{_one_line(item.get("source", ""), 60)} -> {_one_line(item.get("target", ""), 60)}')
            elif kind == "finding":
                lines.append(f'> [{item.get("severity")}] finding {item["id"]} "{_one_line(item.get("title", ""), 80)}" '
                             f'({item.get("basis")}): {_one_line(item.get("message", ""))}')
            elif kind == "coverage":
                limitations = item.get("limitations") if isinstance(item.get("limitations"), list) else []
                lines.append(f'> coverage: {_one_line(item.get("summary", ""), 160)} / limitations: '
                             f'{_one_line("; ".join(map(str, limitations)) or "none", 160)}')
            else:
                lines.append(f"> configuration: {_one_line(item)}")
            lines.append(f"{pointer}: pending")
        findings = [p.split(":", 1)[1] for p, e in artifact_elements(artifact).items() if e["kind"] == "finding"]
        lines += ["", "## Severity", "> For each finding: agree | too-high | too-low (reported, not gated)"]
        lines += [f"{identifier}: pending" for identifier in findings]
    pointer_hint = "response:A-B" if baseline else "<pointer ...>"
    essential = reference["essentialFactIds"]
    lines += ["", "## Essential facts",
              f"> Frozen denominator {len(essential)}. covered {pointer_hint} | partial {pointer_hint} | missing | "
              f"contradicted {pointer_hint}"]
    for identifier in essential:
        lines += [f"> {identifier}: {_one_line(_frozen_text(facts.get(identifier, {}), 'claim', 'text', 'wording'))}",
                  f"{identifier}: pending"]
    lines += ["", "## Known unresolved", f"> stated {pointer_hint} | not-stated"]
    for identifier in [item["id"] for item in reference["knownUnresolved"] if item.get("runsMustState") is True]:
        lines += [f"> {identifier}: {_one_line(_frozen_text(unknowns[identifier], 'text', 'wording'))}",
                  f"{identifier}: pending"]
    if baseline:
        lines += ["", "## False accusations",
                  '> Optional, reported only: "response:40-42: high | medium | low" for each false accusation in the answer.',
                  "", "## Usability", "> task: useful | partly | not-useful (reported, not gated)", "task: pending"]
    else:
        lines += ["", "## Usability",
                  "> clear | partial | missing; task: useful | partly | not-useful (reported, not gated; README.md:96)"]
        lines += [f"{key}: pending" for key in USABILITY_KEYS] + ["task: pending"]
        if reference["defects"]:
            lines += ["", "## Reference defects", "> found <pointer ...> | missed (reported, not gated)"]
            for item in reference["defects"]:
                lines += [f"> {item['id']}: {_one_line(_frozen_text(item, 'text', 'wording', 'claim'))}", f"{item['id']}: pending"]
    lines += ["", "## Task", '> Write "Review: complete" when every verdict above is final.', "Review: pending", ""]
    return "\n".join(lines)


@dataclass
class ReviewContext:
    run_id: str
    condition: str
    reference_revision: str
    essential_ids: list[str]
    unknown_ids: list[str]
    defect_ids: list[str]
    artifact: dict | None = None
    artifact_sha256: str | None = None
    transcript_lines: int | None = None
    transcript_sha256: str | None = None


@dataclass
class ReviewData:
    complete: bool = False
    reviewer: str | None = None
    claims: list[dict] = field(default_factory=list)
    essential: dict[str, str] = field(default_factory=dict)
    unknowns: dict[str, str] = field(default_factory=dict)
    severity: dict[str, str] = field(default_factory=dict)
    usability: dict[str, str] = field(default_factory=dict)
    defects: dict[str, str] = field(default_factory=dict)
    false_accusations: list[dict] = field(default_factory=list)


def check_review(record: er.Record, display: str, ctx: ReviewContext) -> tuple[list[er.Problem], ReviewData]:
    """The run-review rules of section 4.4. Returns every problem and the parsed verdicts."""
    problems: list[er.Problem] = []
    data = ReviewData()
    baseline = ctx.condition == "baseline"
    header = record.header

    def add(level: str, line: int, where: str, message: str) -> None:
        problems.append(er.Problem(display, line, level, where, message))

    def header_line(key: str) -> int:
        item = header.field(key)
        return item.line if item is not None else header.line

    if record.ident != ctx.run_id:
        add(er.ERROR, header.line, "header", f'the title must read "# Run review: {ctx.run_id}"; restore the line the tool wrote.')
    if (header.value("Run") or "").strip() != ctx.run_id:
        add(er.ERROR, header_line("Run"), "header", f'the Run line must read "{ctx.run_id}"; restore the line the tool wrote.')
    bound_key, bound_value = ("Transcript", ctx.transcript_sha256) if baseline else ("Artifact", ctx.artifact_sha256)
    if (header.value(bound_key) or "").strip() != bound_value:
        add(er.ERROR, header_line(bound_key), "header",
            f"the {bound_key} line does not match the sealed {bound_key.lower()} ({(bound_value or '?')[:12]}...); this review "
            "belongs to another run or revision.")
    if (header.value("Reference") or "").strip() != ctx.reference_revision:
        add(er.ERROR, header_line("Reference"), "header",
            f"the Reference line does not match the frozen referenceRevision ({ctx.reference_revision[:19]}...); restore the "
            "line the tool wrote.")
    reviewer = (header.value("Reviewer") or "").strip()
    if not reviewer:
        add(er.TODO, header_line("Reviewer"), "header", "Reviewer is empty. Write the name of the person who reviewed this run.")
    data.reviewer = reviewer or None
    date = (header.value("Date") or "").strip()
    if not date:
        add(er.TODO, header_line("Date"), "header", "Date is empty. Write the review date as YYYY-MM-DD.")
    elif not _valid_date(date):
        add(er.ERROR, header_line("Date"), "header", f'"{date}" is not a date. Write it as YYYY-MM-DD.')
    transcriber = (header.value("Transcribed by") or "").strip()
    if transcriber:
        add(er.NOTE, header_line("Transcribed by"), "header", f'transcribed by {transcriber}; the reviewer must read the whole '
                                                                'file before writing "Review: complete".')

    def verdict_of(item: er.Field, where: str, vocab: set[str], *, pointers: str,
                   targets: Callable[[str], str | None] | None = None, reason_for: tuple[str, ...] = ()) -> str | None:
        """pointers: 'none' | 'required' (for the verdicts in ``needs``) handled by the caller."""
        text = item.value.strip()
        if not text or text.split()[0].casefold() == "pending":
            add(er.TODO, item.line, where, f"{item.key} is still pending.")
            return None
        try:
            verdict, cited, reason = er.parse_verdict(text, vocab)
        except ValueError:
            add(er.ERROR, item.line, where, f'"{item.key}: {_one_line(text, 60)}" is not a verdict. Write one of: '
                                            f'{", ".join(sorted(vocab))}.')
            return None
        if verdict in reason_for and not reason:
            add(er.ERROR, item.line, where, f'{item.key} is {verdict}; add " — <reason>".')
        needs = pointers == "required" and verdict not in ("missing", "not-stated", "missed")
        if pointers == "none" and cited:
            add(er.ERROR, item.line, where, f'{item.key}: claim lines take no pointers; put notes after " — ".')
        elif needs and not cited:
            add(er.ERROR, item.line, where, f"{item.key} is {verdict}; name at least one pointer that shows it.")
        elif not needs and pointers == "required" and cited:
            add(er.ERROR, item.line, where, f"{item.key} is {verdict}; it takes no pointers.")
        for pointer in cited if targets is not None else []:
            problem = targets(pointer)
            if problem:
                add(er.ERROR, item.line, where, f'{item.key}: pointer "{pointer}" {problem}.')
        return verdict

    def expect_keys(section: er.Section | None, name: str, required: list[str], extra_message: str) -> dict[str, er.Field]:
        if section is None:
            if required:
                add(er.ERROR, 1, name, f'the "## {name}" section is missing; restore it from the review template.')
            return {}
        present = {item.key: item for item in section.lines}
        for key in required:
            if key not in present:
                add(er.ERROR, section.line, name, f'{key} has no line; add "{key}: <verdict>".')
        for key, item in present.items():
            if key not in required:
                add(er.ERROR, item.line, name, f'"{key}" {extra_message}')
        return {key: item for key, item in present.items() if key in required}

    if baseline:
        limit = ctx.transcript_lines or 0

        def targets(pointer: str) -> str | None:
            match = RESPONSE_RE.fullmatch(pointer)
            if not match or match.group("n"):
                return "is not response:LINE or response:LINE-END"
            start, end = int(match.group("line")), int(match.group("end") or match.group("line"))
            if start < 1 or end < start or end > limit:
                return f"is outside the transcript's {limit} lines"
            return None
    else:
        known = artifact_pointers(ctx.artifact or {})

        def targets(pointer: str) -> str | None:
            return None if pointer in known else "does not resolve in the artifact"

    claims = record.section("Claims")
    if claims is None:
        add(er.ERROR, 1, "Claims", 'the "## Claims" section is missing; restore it from the review template.')
    elif baseline:
        for item in claims.lines:
            match = RESPONSE_RE.fullmatch(item.key)
            if not match:
                add(er.ERROR, item.line, "Claims", f'"{item.key}" is not a transcript range; write "response:LINE-END: <verdict>".')
                continue
            if match.group("n") and int(match.group("n")) < 2:
                add(er.ERROR, item.line, "Claims", f'"{item.key}": split lines start at #2.')
            problem = targets(item.key.split("#", 1)[0])
            if problem:
                add(er.ERROR, item.line, "Claims", f'"{item.key}" {problem}.')
                continue
            verdict = verdict_of(item, "Claims", CLAIM_VERDICTS, pointers="none", reason_for=("qualified", "unsupported"))
            if verdict:
                data.claims.append({"pointer": item.key, "verdict": verdict, "basis": None, "base": "#" not in item.key})
        if not claims.lines:
            add(er.TODO, claims.line, "Claims", 'add at least one "response:LINE-END: <verdict>" line for the claims in the answer.')
    else:
        elements = artifact_elements(ctx.artifact or {})
        seen: set[str] = set()
        for item in claims.lines:
            key = item.key
            split = SPLIT_RE.fullmatch(key)
            base = split.group("base") if split else key
            if base not in elements:
                add(er.ERROR, item.line, "Claims", f'"{key}" does not name an element of the artifact (node:<id>, edge:<id>, '
                                                   "finding:<id>, coverage or configuration).")
                continue
            if split and int(split.group("n")) < 2:
                add(er.ERROR, item.line, "Claims", f'"{key}": split lines start at #2.')
                continue
            if not split:
                seen.add(key)
            verdict = verdict_of(item, "Claims", CLAIM_VERDICTS, pointers="none", reason_for=("qualified", "unsupported"))
            if verdict:
                data.claims.append({"pointer": key, "verdict": verdict, "basis": elements[base]["basis"],
                                    "base": not split, "element": base, "severity": elements[base]["severity"]})
        for pointer in elements:
            if pointer not in seen:
                add(er.ERROR, claims.line, "Claims", f'{pointer} has no line; every element needs exactly one: add '
                                                     f'"{pointer}: <verdict>".')
        findings = [pointer.split(":", 1)[1] for pointer, element in elements.items() if element["kind"] == "finding"]
        severity = expect_keys(record.section("Severity"), "Severity", findings, "is not a finding of the artifact.")
        for key, item in severity.items():
            verdict = verdict_of(item, "Severity", SEVERITY_VERDICTS, pointers="none")
            if verdict:
                data.severity[key] = verdict
    essential = expect_keys(record.section("Essential facts"), "Essential facts", ctx.essential_ids,
                            "is not a frozen essential fact of this task.")
    for key, item in essential.items():
        verdict = verdict_of(item, "Essential facts", ESSENTIAL_VERDICTS, pointers="required", targets=targets)
        if verdict:
            data.essential[key] = verdict
    unknowns = expect_keys(record.section("Known unresolved"), "Known unresolved", ctx.unknown_ids,
                           "is not a frozen must-state unknown of this task.")
    for key, item in unknowns.items():
        verdict = verdict_of(item, "Known unresolved", UNKNOWN_VERDICTS, pointers="required", targets=targets)
        if verdict:
            data.unknowns[key] = verdict
    usability_keys = ["task"] if baseline else list(USABILITY_KEYS) + ["task"]
    usability = expect_keys(record.section("Usability"), "Usability", usability_keys,
                            "is not asked in a baseline review (only task)." if baseline else "is not a usability question.")
    for key, item in usability.items():
        verdict = verdict_of(item, "Usability", TASK_VERDICTS if key == "task" else USABILITY_VERDICTS, pointers="none")
        if verdict:
            data.usability[key] = verdict
    defects_section = record.section("Reference defects")
    if ctx.defect_ids and not baseline:
        defects = expect_keys(defects_section, "Reference defects", ctx.defect_ids, "is not a frozen defect of this task.")
        for key, item in defects.items():
            verdict = verdict_of(item, "Reference defects", DEFECT_VERDICTS, pointers="required", targets=targets)
            if verdict:
                data.defects[key] = verdict
    elif defects_section is not None and defects_section.lines:
        add(er.ERROR, defects_section.lines[0].line, "Reference defects", "this task has no frozen defects; remove these lines.")
    accusations = record.section("False accusations")
    if accusations is not None and accusations.lines:
        if not baseline:
            add(er.ERROR, accusations.lines[0].line, "False accusations",
                "only baseline reviews list false accusations; judge findings in Claims.")
        else:
            for item in accusations.lines:
                problem = targets(item.key)
                if problem:
                    add(er.ERROR, item.line, "False accusations", f'"{item.key}" {problem}.')
                    continue
                text = item.value.strip().casefold()
                if text not in FALSE_ACCUSATION_SEVERITIES:
                    add(er.ERROR, item.line, "False accusations", f'"{item.key}: {_one_line(item.value, 40)}" must be high, '
                                                                   "medium or low.")
                    continue
                data.false_accusations.append({"pointer": item.key, "severity": text})
    for name in ("Severity",) if baseline else ():
        section = record.section(name)
        if section is not None and section.lines:
            add(er.ERROR, section.lines[0].line, name, "a baseline review has no Severity section lines.")
    task = record.section("Task")
    todo = sum(problem.level == er.TODO for problem in problems)
    if task is None:
        add(er.ERROR, 1, "Task", 'the "## Task" section is missing; add "## Task" with "Review: pending".')
    else:
        item = task.field("Review")
        text = (item.value.strip().casefold() if item is not None else "")
        line = item.line if item is not None else task.line
        if text in ("", "pending"):
            add(er.TODO, line, "Task", 'Review is not complete. Write "Review: complete" when every verdict above is final.')
        elif text != "complete":
            add(er.ERROR, line, "Task", f'"Review: {item.value.strip()}" must be pending or complete.')
        elif todo:
            add(er.ERROR, line, "Task", f"Review is complete, but {todo} item(s) above are still to do.")
        else:
            data.complete = True
    if any(problem.level == er.ERROR for problem in problems):
        data.complete = False
    problems.sort(key=lambda problem: problem.line)
    return problems, data


def _review_context(run: dict, record: dict, reference: dict, evidence: Path, helper: ModuleType | None) -> ReviewContext:
    ctx = ReviewContext(run_id=run["id"], condition=run["condition"], reference_revision=record["referenceRevision"],
                        essential_ids=list(reference["essentialFactIds"]),
                        unknown_ids=[item["id"] for item in reference["knownUnresolved"] if item.get("runsMustState") is True],
                        defect_ids=[item["id"] for item in reference["defects"]])
    if run["condition"] == "baseline":
        entry = record["evidence"].get("transcript")
        if entry:
            text = er.confined_file(evidence, entry["file"]).read_bytes().decode("utf-8", "replace")
            ctx.transcript_sha256 = entry["sha256"]
            lines = (helper._lines(text) if helper is not None else text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
            ctx.transcript_lines = er.human_line_count(lines)
    else:
        entry = record["evidence"].get("artifact")
        if entry:
            ctx.artifact_sha256 = entry["sha256"]
            raw = er.confined_file(evidence, entry["file"]).read_bytes()
            try:
                doc = helper._parse(raw) if helper is not None else json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                doc = None
            ctx.artifact = doc if isinstance(doc, dict) else None
    return ctx


def review_template(root: Path, run_id: str, name: str, pilot_value: str | None, out: Callable[[str], None] = print) -> int:
    try:
        directory = er.run_dir_name(run_id)
    except ValueError as exc:
        raise PilotError(str(exc)) from None
    pilot_dir = _pilot_dir(pilot_value)
    campaign = load_campaign(Path(root), name)
    run = {r["id"]: r for r in campaign.plan()}.get(run_id)
    if run is None:
        raise PilotError(f"{run_id} is not a planned run of {name}")
    evidence = pilot_dir / "evidence" / directory
    try:
        record = _json_loads(er.confined_file(evidence, RECORD_FILE).read_bytes(), RECORD_FILE)
    except ValueError:
        raise PilotError(f"{run_id} is not sealed; run run-finish first") from None
    if record.get("id") != run_id:
        raise PilotError(f"{evidence / RECORD_FILE} belongs to {record.get('id')!r}, not {run_id}")
    status = (record.get("session") or {}).get("status")
    if status != "completed":
        raise PilotError(f"{run_id} is {status}; only completed runs are reviewed (it counts as a failure)")
    reference = campaign.references[run["task"]]
    ctx = _review_context(run, record, reference, evidence, campaign.helper)
    if run["condition"] == "skill" and ctx.artifact is None:
        raise PilotError(f"the artifact of {run_id} does not parse as a WorkflowDocument object; the run scores SV = 0 and "
                         "has no elements to review")
    if run["condition"] == "baseline" and ctx.transcript_sha256 is None:
        raise PilotError(f"{run_id} has no transcript; a baseline is reviewed on its transcript")
    text = review_template_text(run, record, reference, ctx.artifact)
    try:
        er.write_exclusive(evidence / REVIEW_FILE, text.encode("utf-8"))
    except FileExistsError:
        raise PilotError(f"{evidence / REVIEW_FILE} already exists; it is never overwritten") from None
    out(f"Created {evidence / REVIEW_FILE} with every verdict pending. Fill it, then run: "
        f"python tools/workflow_eval.py check {evidence / REVIEW_FILE}")
    return 0


# --------------------------------------------------------------------------------------------
# check_file (for the check command in tools/workflow_decisions.py; section 8.3 item 6)


def check_file(path: Path | str, *, root: Path | None = None) -> list[er.Problem]:
    """Problems of a session.md or review.md file; the checker is chosen by the title line. A run
    review is checked against the record.json next to it and the frozen reference of its campaign
    under ``root`` (the MLView checkout)."""
    path = Path(path)
    display = str(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [er.Problem(display, 1, er.ERROR, "header", f"cannot read the file: {exc.strerror or exc}")]
    record, problems = er.parse_record(raw, display)
    if record is None:
        return problems
    evidence = path.parent
    if record.kind == "Session":
        return sorted(problems + check_session(record, display, evidence).problems, key=lambda p: p.line)
    if record.kind != "Run review":
        return problems + [er.Problem(display, 1, er.ERROR, "header",
                                      f'"{record.title}" is not a session or run review file.')]
    try:
        sealed = _json_loads(er.confined_file(evidence, RECORD_FILE).read_bytes(), RECORD_FILE)
        run = {"id": sealed["id"], "task": sealed["task"], "condition": sealed["condition"]}
        reference_path = Path(root or ROOT) / PILOT_REL / sealed["campaign"] / "reference" / f"{sealed['task']}.json"
        reference = _json_loads(reference_path.read_bytes(), str(reference_path))
        ctx = _review_context(run, sealed, reference, evidence, None)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return problems + [er.Problem(display, 1, er.ERROR, "header",
                                      f"cannot check against the sealed run ({exc}); a run review lives in the run's "
                                      "evidence directory next to record.json.")]
    extra, _data = check_review(record, display, ctx)
    return sorted(problems + extra, key=lambda p: p.line)


# --------------------------------------------------------------------------------------------
# summarize (sections 4.5-4.8)


@dataclass
class RunState:
    run: dict
    evidence: Path | None = None
    record: dict | None = None
    record_sha256: str | None = None
    status: str = "pending"          # pending | completed | failed | timed-out | blocked
    invalid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sv: int = 0
    evidence_count: int | None = None
    exact_count: int | None = None
    error_codes: list[str] = field(default_factory=list)
    review_status: str = "missing"   # missing | incomplete | problems | complete | not-applicable | not-required
    review_sha256: str | None = None
    review_problems: list[str] = field(default_factory=list)
    review: ReviewData | None = None
    artifact_doc: dict | None = None
    prompt_in_transcript: str = "unverified"
    validated: bool = False

    @property
    def outcome(self) -> str:
        return "invalid" if self.invalid and self.status != "pending" else self.status

    @property
    def usable(self) -> bool:
        """Completed, not invalid, and its review is complete (or there is nothing to review)."""
        return (self.status == "completed" and not self.invalid
                and self.review_status in ("complete", "not-applicable"))


def _check_entry(evidence: Path, entry: object, label: str, problems: list[str], *, with_bytes: bool = True) -> bytes | None:
    keys = {"file", "sha256", "bytes"} if with_bytes else {"file", "sha256"}
    if not isinstance(entry, dict) or set(entry) != keys or not isinstance(entry.get("file"), str):
        problems.append(f"{label}: must be {{{', '.join(sorted(keys))}}}")
        return None
    try:
        data = er.confined_file(evidence, entry["file"]).read_bytes()
    except ValueError as exc:
        problems.append(f"{label}: {exc}")
        return None
    if er.sha256_bytes(data) != entry.get("sha256"):
        problems.append(f"{label}: {entry['file']} does not match its sealed SHA-256")
        return None
    if with_bytes and entry.get("bytes") != len(data):
        problems.append(f"{label}: {entry['file']} does not match its sealed size")
        return None
    return data


def _verify_record(state: RunState, campaign: Campaign) -> list[str]:
    """Section 4.5 C: sealed, every sealed file re-hashed and confined, identity equal to the plan."""
    run, record, evidence = state.run, state.record, state.evidence
    problems: list[str] = []
    if not isinstance(record, dict) or record.get("format") != RUN_FORMAT:
        return [f'record.json: format must be "{RUN_FORMAT}"']
    for key in ("id", "task", "host", "repeat", "stage", "condition"):
        if record.get(key) != run[key]:
            problems.append(f"record.json {key}: {record.get(key)!r} differs from the plan ({run[key]!r})")
    if record.get("campaign") != campaign.name:
        problems.append(f"record.json campaign: {record.get('campaign')!r}, not {campaign.name} (use one pilot directory per campaign)")
    if record.get("candidateSha256") != campaign.candidate_sha256:
        problems.append("record.json candidateSha256: differs from sha256(candidate.json)")
    if record.get("referenceRevision") != campaign.reference_revision:
        problems.append("record.json referenceRevision: differs from the frozen referenceRevision")
    if record.get("repositoryCommit") != run["repositoryCommit"]:
        problems.append("record.json repositoryCommit: differs from the frozen tasks.json commit")
    prompt = record.get("prompt")
    expected_rel = campaign.prompt_rel(run["task"], run["condition"])
    if not isinstance(prompt, dict) or prompt.get("file") != PROMPT_FILE or prompt.get("frozen") != expected_rel:
        problems.append(f"record.json prompt: must name {PROMPT_FILE} and frozen {expected_rel}")
    else:
        _check_entry(evidence, {"file": prompt["file"], "sha256": prompt.get("sha256")}, "prompt", problems, with_bytes=False)
        if prompt.get("sha256") != campaign.freeze["files"].get(expected_rel):
            problems.append(f"prompt: sha256 differs from the freeze.json entry for {expected_rel}")
    session = record.get("session")
    if not isinstance(session, dict) or session.get("file") != SESSION_FILE:
        problems.append("record.json session: must name session.md")
    else:
        raw = _check_entry(evidence, {"file": SESSION_FILE, "sha256": session.get("sha256")}, "session", problems, with_bytes=False)
        if raw is not None:
            parsed, parse_problems = er.parse_record(raw, SESSION_FILE)
            result = check_session(parsed, SESSION_FILE, evidence, run_id=run["id"], helper=campaign.helper) if parsed else None
            expected = {k: v for k, v in session.items() if k not in ("file", "sha256")}
            if result is None or result.block is None or any(p.level == er.ERROR for p in parse_problems):
                problems.append("session: session.md no longer passes the run-finish checks")
            elif result.block != expected:
                problems.append("record.json session fields differ from session.md")
    workspace = record.get("workspace")
    if not isinstance(workspace, dict) or workspace.get("name") != er.run_dir_name(run["id"]):
        problems.append("record.json workspace: must name the run's workspace")
    else:
        for key in ("before", "after", "changes"):
            _check_entry(evidence, workspace.get(key), f"workspace.{key}", problems, with_bytes=False)
        changes = workspace.get("changedProjectFiles")
        if not isinstance(changes, list):
            problems.append("record.json workspace.changedProjectFiles: must be a list")
        else:
            for index, entry in enumerate(changes):
                if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                    problems.append(f"workspace.changedProjectFiles[{index}]: malformed")
                elif entry.get("file") is not None:
                    _check_entry(evidence, {"file": entry["file"], "sha256": entry.get("sha256")},
                                 f"workspace.changedProjectFiles[{index}]", problems, with_bytes=False)
        if not isinstance(workspace.get("isolation"), list):
            problems.append("record.json workspace.isolation: must be a list")
    sealed_evidence = record.get("evidence")
    if not isinstance(sealed_evidence, dict):
        problems.append("record.json evidence: must be an object")
    else:
        skill = run["condition"] == "skill"
        status = (session or {}).get("status") if isinstance(session, dict) else None
        for key in ("artifact", "transcript", "uiLog", "doctor", "partialArtifact"):
            entry = sealed_evidence.get(key)
            if entry is None:
                if key == "doctor" or (key == "artifact" and skill and status == "completed") \
                        or (key == "transcript" and not skill and status == "completed") \
                        or (key == "uiLog" and skill and status == "completed"):
                    problems.append(f"evidence.{key}: required for this run")
                continue
            if not skill and key in ("artifact", "uiLog", "partialArtifact"):
                problems.append(f"evidence.{key}: a baseline has no {key}")
                continue
            _check_entry(evidence, entry, f"evidence.{key}", problems)
    amendments = record.get("amendments")
    if not isinstance(amendments, list):
        problems.append("record.json amendments: must be a list")
    else:
        for index, amendment in enumerate(amendments, 1):
            if (not isinstance(amendment, dict) or set(amendment) != {"at", "reason", "previous"}
                    or _parse_time(amendment.get("at")) is None or not isinstance(amendment.get("reason"), str)
                    or not amendment["reason"].strip() or not isinstance(amendment.get("previous"), str)
                    or not HEX64_RE.fullmatch(amendment["previous"])):
                problems.append(f"amendments[{index - 1}]: must be {{at, reason, previous}}")
                continue
            _check_entry(evidence, {"file": PREVIOUS_RECORD.format(n=index), "sha256": amendment["previous"]},
                         f"amendments[{index - 1}]", problems, with_bytes=False)
    if _parse_time(record.get("sealedAt")) is None:
        problems.append("record.json sealedAt: must be an RFC 3339 time")
    if not isinstance(record.get("tooling"), dict):
        problems.append("record.json tooling: must be an object")
    return problems


def _protocol(state: RunState, campaign: Campaign, stage1: dict | None) -> None:
    """Section 4.5 D: violations make the run invalid, always with a reason."""
    run, record = state.run, state.record
    session = record["session"]
    helper = campaign.helper
    reasons, warnings = state.invalid, state.warnings
    started, ended = _parse_time(session.get("startedAt"), helper), _parse_time(session.get("endedAt"), helper)
    frozen_at = _parse_time(campaign.freeze.get("frozenAt"))
    captured_at = _parse_time(campaign.candidate["source"].get("capturedAt"))
    if started is not None:
        if frozen_at is not None and started < frozen_at:
            reasons.append("started before the freeze")
        if captured_at is not None and started < captured_at:
            reasons.append("started before the candidate was captured")
        if ended is not None and ended < started:
            reasons.append("ended before it started")
    if run["stage"] == 2:
        why = _stage1_go(stage1, campaign)
        if why is not None:
            reasons.append(f"Stage 2 run without a committed Stage 1 go summary ({why})")
        elif started is not None and started <= _parse_time(stage1["generatedAt"]):
            reasons.append("Stage 2 run started before the committed Stage 1 summary was generated")
    status = session.get("status")
    active = session.get("activeMinutes")
    if isinstance(active, (int, float)) and active > campaign.budget_minutes and status != "timed-out":
        reasons.append(f"active minutes {active:g} exceed the budget of {campaign.budget_minutes}")
    repairs = session.get("repairRounds")
    if run["condition"] == "skill" and status == "completed" and _is_int(repairs) and repairs > campaign.repair_limit:
        reasons.append(f"repair rounds {repairs} exceed the limit of {campaign.repair_limit}")
    prior = session.get("priorAttempts")
    if _is_int(prior) and prior > campaign.retries:
        reasons.append(f"prior attempts {prior} exceed the infrastructure retries ({campaign.retries})")
    settings = campaign.host_policy(run["host"])
    for key in ("model", "reasoning", "invocation"):
        value = session.get(key)
        if value is not None and _fold(value) != _fold(settings[key]):
            reasons.append(f'{key} "{_one_line(value, 80)}" differs from the policy "{_one_line(settings[key], 80)}"')
    if run["condition"] == "skill" and session.get("helperPython") is not None and not _python_ok(session["helperPython"]):
        reasons.append(f"helper Python {session['helperPython']} is older than 3.10")
    doctor_entry = record["evidence"].get("doctor")
    try:
        doctor = _json_loads(er.confined_file(state.evidence, doctor_entry["file"]).read_bytes(), "doctor.json")
        locations = [item for item in doctor.get("locations", []) if isinstance(item, dict) and item.get("present")]
    except (ValueError, AttributeError, TypeError):
        locations = None
        reasons.append("doctor.json cannot be read")
    if locations is not None:
        if run["condition"] == "skill":
            if len(locations) != 1:
                reasons.append(f"{len(locations)} installed skill locations (exactly one is expected)")
            elif locations[0].get("identity") != campaign.candidate["skill"] or locations[0].get("unsafeSymlinks"):
                reasons.append("the installed skill differs from the candidate's skill identity")
        elif locations:
            reasons.append("an MLView skill was installed in the baseline workspace")
    available = session.get("mlviewAvailable")
    if run["condition"] == "baseline" and available is True:
        reasons.append("MLView was available to the host in a baseline session")
    if run["condition"] == "skill" and available is False:
        reasons.append("MLView was not available to the host in a skill session")
    changes = record["workspace"].get("changedProjectFiles") or []
    if changes:
        shown = ", ".join(entry["path"] for entry in changes[:3]) + (" ..." if len(changes) > 3 else "")
        reasons.append(f"{len(changes)} project file(s) changed in the workspace ({shown})")
    for finding in record["workspace"].get("isolation") or []:
        reasons.append(f"workspace isolation: {finding}")
    for deviation in session.get("deviations") or []:
        if deviation.get("invalidates"):
            reasons.append(f"deviation: {_one_line(deviation.get('text', ''), 120)}")
    transcript = record["evidence"].get("transcript")
    if transcript:
        text = er.confined_file(state.evidence, transcript["file"]).read_bytes().decode("utf-8", "replace")
        prompt = er.confined_file(state.evidence, PROMPT_FILE).read_bytes().decode("utf-8", "replace")
        state.prompt_in_transcript = "yes" if " ".join(prompt.split()) in " ".join(text.split()) else "no"
        if state.prompt_in_transcript == "no":
            warnings.append("the frozen prompt was not found in the transcript (after whitespace normalisation)")


def _artifact(state: RunState, campaign: Campaign, corpus: Path, verified: dict[str, dict], notes: list[str]) -> bool:
    """Section 4.5 E for a completed skill run; returns False when the corpus could not be used."""
    run, record = state.run, state.record
    helper = campaign.helper
    raw = er.confined_file(state.evidence, record["evidence"]["artifact"]["file"]).read_bytes()
    try:
        doc = helper._parse(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        doc = None
    if not isinstance(doc, dict):
        state.error_codes, state.evidence_count, state.exact_count = ["invalid_json"], 0, 0
        return True
    state.artifact_doc = doc
    producer = doc.get("producer") if isinstance(doc.get("producer"), dict) else {}
    host = producer.get("host")
    if host == "unknown":
        state.warnings.append("artifact producer.host is unknown")
    elif host != run["host"]:
        state.invalid.append(f"artifact producer.host is {host!r}, not {run['host']}")
    if state.invalid:
        return True
    repo = campaign.repositories[campaign.task(run["task"])["repository"]]
    repo_path = corpus / repo["name"]
    if repo["name"] not in verified:
        if not repo_path.is_dir():
            verified[repo["name"]] = {"ok": False, "absent": True}
            notes.append(f"corpus absent for {repo['name']}: its artifacts were not validated (fetch the corpus and re-run)")
        else:
            report = _verify_repo(repo, corpus)
            verified[repo["name"]] = report
            if not report.get("ok"):
                notes.append(f"{repo['name']}: the corpus checkout failed verification, so its artifacts were not validated "
                             "(python tools/fetch_workflow_repos.py --verify)")
    if not verified[repo["name"]].get("ok"):
        return False
    errors, _fingerprints = helper.validate(doc, repo_path)
    anchor: set[int] = set()
    structural = freshness = False
    codes = set()
    evidence = doc.get("evidence") if isinstance(doc.get("evidence"), list) else []
    for error in errors:
        codes.add(error.get("code"))
        path = str(error.get("path", ""))
        match = re.match(r"evidence\[(\d+)\]", path)
        if match and int(match.group(1)) < len(evidence):
            anchor.add(int(match.group(1)))
        elif error.get("code") == "stale_source" or path == "verification.files":
            freshness = True
        else:
            structural = True
    verification = doc.get("verification")
    if not isinstance(verification, dict) or not isinstance(verification.get("publishedAt"), str) \
            or not er.is_rfc3339(verification["publishedAt"], helper):
        structural = True
        codes.add("unpublished")
    state.error_codes = sorted(code for code in codes if isinstance(code, str))
    state.evidence_count, state.exact_count = len(evidence), len(evidence) - len(anchor)
    state.validated = True
    state.sv = int(not structural and not freshness)
    return True


def _review(state: RunState, campaign: Campaign) -> None:
    path = state.evidence / REVIEW_FILE if state.evidence is not None else None
    exists = path is not None and os.path.lexists(path)
    if state.status != "completed":
        if exists:
            state.review_status = "problems"
            state.review_problems.append(f"a {state.status} run is not reviewed; remove review.md")
        else:
            state.review_status = "not-required"
        return
    if state.invalid:
        state.review_status = "not-required"
        return
    if state.run["condition"] == "skill" and state.artifact_doc is None:
        state.review_status = "not-applicable"
        return
    if not exists:
        state.review_status = "missing"
        return
    try:
        raw = er.confined_file(state.evidence, REVIEW_FILE).read_bytes()
    except ValueError as exc:
        state.review_status, state.review_problems = "problems", [f"review.md: {exc}"]
        return
    state.review_sha256 = er.sha256_bytes(raw)
    record, problems = er.parse_record(raw, REVIEW_FILE)
    if record is None or record.kind != "Run review":
        state.review_status = "problems"
        state.review_problems = [str(p) for p in problems] or ["review.md is not a run review file"]
        return
    reference = campaign.references[state.run["task"]]
    ctx = _review_context(state.run, state.record, reference, state.evidence, campaign.helper)
    extra, data = check_review(record, REVIEW_FILE, ctx)
    problems = problems + extra
    errors = [str(p) for p in problems if p.level == er.ERROR]
    state.review = data
    if errors:
        state.review_status, state.review_problems = "problems", errors
    elif not data.complete:
        state.review_status = "incomplete"
    else:
        state.review_status = "complete"


def _run_metrics(state: RunState, campaign: Campaign) -> dict:
    """Per-run counts from the sealed record and a complete review (section 4.6)."""
    task = state.run["task"]
    ess_total = len(campaign.essential_ids(task))
    unk_total = len(campaign.unknown_ids(task))
    claims = {"observed": dict.fromkeys(COUNTED_VERDICTS, 0), "inferred": dict.fromkeys(COUNTED_VERDICTS, 0),
              "noClaim": 0, "unresolvedBasis": 0}
    baseline_claims = dict.fromkeys(COUNTED_VERDICTS, 0)
    ess = unk = fa = 0
    accusations = {"high": 0, "medium": 0, "low": 0}
    reviewed = state.usable and state.review is not None and state.review_status == "complete"
    if reviewed:
        data = state.review
        for claim in data.claims:
            if claim["verdict"] == "no-claim":
                claims["noClaim"] += 1
                continue
            if state.run["condition"] == "baseline":
                baseline_claims[claim["verdict"]] += 1
                continue
            basis = claim["basis"]
            if basis in ("observed", "inferred"):
                claims[basis][claim["verdict"]] += 1
            else:
                claims["unresolvedBasis"] += 1
            if claim["base"] and claim["verdict"] == "unsupported" and claim.get("severity") == "high":
                fa += 1
        ess = sum(verdict == "covered" for verdict in data.essential.values())
        unk = sum(verdict == "stated" for verdict in data.unknowns.values())
        for item in data.false_accusations:
            accusations[item["severity"]] += 1
    return {"claims": claims, "baselineClaims": baseline_claims, "ess": ess, "ESS": ess_total, "unk": unk,
            "UNK": unk_total, "fa": fa, "accusations": accusations, "reviewed": reviewed}


def _ratio(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "value": (numerator / denominator) if denominator else None}


def _precision_counts(claim_sets: Iterable[dict], policy: str) -> tuple[int, int]:
    supported = qualified = unsupported = 0
    for claims in claim_sets:
        supported += claims["supported"]
        qualified += claims["qualified"]
        unsupported += claims["unsupported"]
    if policy == "supported":
        return supported + qualified, supported + qualified + unsupported
    if policy == "excluded":
        return supported, supported + unsupported
    return supported, supported + qualified + unsupported


def _met(numerator: int, denominator: int, threshold: float, comparator: str) -> bool:
    if comparator == "<=":
        return numerator <= threshold
    if denominator == 0:
        return False
    return Fraction(numerator, denominator) >= Fraction(str(threshold))


def compute_targets(runs: list[dict], thresholds: dict, qualified_policy: str, per_host: bool,
                    hosts: list[str]) -> list[dict]:
    """The six targets of section 4.6 over the stage's planned skill runs (``runs[]`` entries of
    the summary: SV, E, X, claims, ess/ESS, unk/UNK, fa, reviewed, status)."""

    def pooled(selection: list[dict]) -> dict[str, tuple[int, int]]:
        valid = [r for r in selection if r["status"] == "completed" and r["E"] is not None]
        reviewed = [r for r in selection if r["reviewed"]]
        claim_sets = [r["claims"][basis] for r in reviewed for basis in ("observed", "inferred")]
        return {
            "structurallyValid": (sum(r["SV"] for r in selection), len(selection)),
            "exactAnchors": (sum(r["X"] for r in valid), sum(r["E"] for r in valid)),
            "supportedClaimPrecision": _precision_counts(claim_sets, qualified_policy),
            "essentialFactRecall": (sum(r["ess"] for r in selection), sum(r["ESS"] for r in selection)),
            "knownUnresolvedQualified": (sum(r["unk"] for r in selection), sum(r["UNK"] for r in selection)),
            "highSeverityFalseAccusations": (sum(r["fa"] for r in reviewed), len(reviewed)),
        }

    values = pooled(runs)
    by_host = {host: pooled([r for r in runs if r["host"] == host]) for host in hosts}
    targets = []
    for key in er.PILOT_TARGET_KEYS:
        numerator, denominator = values[key]
        threshold = thresholds[key]
        comparator = "<=" if key == "highSeverityFalseAccusations" else ">="
        entry = {"key": key, "id": TARGET_IDS[key], "comparator": comparator, "threshold": threshold,
                 "numerator": numerator, "denominator": denominator,
                 "value": numerator if comparator == "<=" else (numerator / denominator if denominator else None)}
        met = _met(numerator, denominator, threshold, comparator)
        if key == "supportedClaimPrecision":
            reviewed = [r for r in runs if r["reviewed"]]
            entry["byBasis"] = {basis: _ratio(*_precision_counts([r["claims"][basis] for r in reviewed], qualified_policy))
                                for basis in ("observed", "inferred")}
        if key == "knownUnresolvedQualified" and denominator == 0:
            met, entry["vacuous"] = True, True
        if per_host and key in ("supportedClaimPrecision", "essentialFactRecall"):
            entry["perHost"] = {}
            for host in hosts:
                h_num, h_den = by_host[host][key]
                h_met = _met(h_num, h_den, threshold, comparator)
                entry["perHost"][host] = {"numerator": h_num, "denominator": h_den,
                                          "value": h_num / h_den if h_den else None, "met": h_met}
                met = met and h_met
        entry["met"] = met
        targets.append(entry)
    return targets


def _group_metrics(runs: list[dict], qualified_policy: str) -> dict:
    valid = [r for r in runs if r["status"] == "completed" and r["E"] is not None]
    reviewed = [r for r in runs if r["reviewed"]]
    precision = _precision_counts([r["claims"][b] for r in reviewed for b in ("observed", "inferred")], qualified_policy)
    return {
        "runs": len(runs),
        "structurallyValid": _ratio(sum(r["SV"] for r in runs), len(runs)),
        "exactAnchors": _ratio(sum(r["X"] for r in valid), sum(r["E"] for r in valid)),
        "supportedClaimPrecision": _ratio(*precision),
        "essentialFactRecall": _ratio(sum(r["ess"] for r in runs), sum(r["ESS"] for r in runs)),
        "knownUnresolvedQualified": _ratio(sum(r["unk"] for r in runs), sum(r["UNK"] for r in runs)),
        "highSeverityFalseAccusations": sum(r["fa"] for r in reviewed),
    }


RATE_KEYS = er.RATE_TARGET_KEYS


def _early_stop(runs: list[dict], targets: list[dict]) -> list[str]:
    indicators = []
    by_key = {target["key"]: target for target in targets}
    for run in runs:
        if run["status"] in ("failed", "timed-out", "blocked", "invalid") or (run["status"] == "completed" and run["SV"] == 0
                                                                              and run["E"] is not None):
            detail = (run["failure"] or {}).get("kind") if run["status"] in ("failed", "timed-out", "blocked") else None
            if run["status"] == "invalid":
                detail = "; ".join(run["invalidReasons"][:2])
            elif run["status"] == "completed":
                detail = "not structurally valid: " + ", ".join(run["errorCodes"] or ["unpublished"])
            indicators.append(f"T1: {run['id']} {run['status']}" + (f" ({detail})" if detail else ""))
    anchors = by_key["exactAnchors"]
    if anchors["threshold"] >= 1 and anchors["numerator"] < anchors["denominator"]:
        indicators.append(f"T2: {anchors['denominator'] - anchors['numerator']} inexact anchor(s) already recorded")
    for key in ("essentialFactRecall", "knownUnresolvedQualified"):
        target = by_key[key]
        total_key = "ESS" if key == "essentialFactRecall" else "UNK"
        open_total = sum(r[total_key] for r in runs if not r["reviewed"] and r["status"] in ("pending", "completed"))
        if target["denominator"] and not _met(target["numerator"] + open_total, target["denominator"], target["threshold"], ">="):
            indicators.append(f"{target['id']}: at most {target['numerator'] + open_total}/{target['denominator']} can still be reached")
    fa = by_key["highSeverityFalseAccusations"]
    if fa["numerator"] > fa["threshold"]:
        indicators.append(f"T6: {fa['numerator']} high-severity false accusation(s) already recorded")
    return indicators


def _pct(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.1f}%"


def _run_entry(state: RunState, campaign: Campaign) -> dict:
    record = state.record or {}
    session = record.get("session") or {}
    metrics = _run_metrics(state, campaign)
    return {
        "id": state.run["id"], "task": state.run["task"], "host": state.run["host"], "repeat": state.run["repeat"],
        "condition": state.run["condition"], "status": state.outcome, "sessionStatus": state.status,
        "failure": session.get("failure"), "invalidReasons": list(state.invalid),
        "SV": state.sv, "E": state.evidence_count, "X": state.exact_count, "errorCodes": list(state.error_codes),
        "claims": metrics["claims"], "baselineClaims": metrics["baselineClaims"],
        "ess": metrics["ess"], "ESS": metrics["ESS"], "unk": metrics["unk"], "UNK": metrics["UNK"], "fa": metrics["fa"],
        "falseAccusationsListed": metrics["accusations"],
        "activeMinutes": session.get("activeMinutes"), "repairRounds": session.get("repairRounds"),
        "resolvedModel": session.get("resolvedModel"),
        "reported": _reported(state.review if metrics["reviewed"] else None),
        "deviations": session.get("deviations") or [],
        "reviewer": state.review.reviewer if (state.review and metrics["reviewed"]) else None,
        "reviewed": metrics["reviewed"], "reviewStatus": state.review_status,
        "promptInTranscript": state.prompt_in_transcript, "warnings": list(state.warnings),
        "amendments": [{"at": a["at"], "reason": a["reason"]} for a in record.get("amendments") or []],
    }


def _reported(review: ReviewData | None) -> dict | None:
    """Verdicts that are reported and never gated: finding severity, usability and reference defects."""
    if review is None:
        return None
    return {"severity": {verdict: sum(v == verdict for v in review.severity.values()) for verdict in sorted(SEVERITY_VERDICTS)},
            "usability": dict(sorted(review.usability.items())),
            "referenceDefects": {verdict: sum(v == verdict for v in review.defects.values()) for verdict in sorted(DEFECT_VERDICTS)}}


def _reported_totals(runs: list[dict]) -> dict:
    severity = {verdict: 0 for verdict in sorted(SEVERITY_VERDICTS)}
    defects = {verdict: 0 for verdict in sorted(DEFECT_VERDICTS)}
    usability: dict[str, dict[str, int]] = {}
    for run in runs:
        reported = run.get("reported")
        if not reported:
            continue
        for verdict, count in reported["severity"].items():
            severity[verdict] += count
        for verdict, count in reported["referenceDefects"].items():
            defects[verdict] += count
        for question, answer in reported["usability"].items():
            usability.setdefault(question, {})
            usability[question][answer] = usability[question].get(answer, 0) + 1
    return {"severity": severity, "usability": dict(sorted(usability.items())), "referenceDefects": defects,
            "note": "Reported, not gated (README.md:96)."}


def _read_invalidation(root: Path, name: str) -> tuple[dict | None, list[str]]:
    path = _campaign_dir(root, name) / "invalidation.md"
    if not os.path.lexists(path):
        return None, []
    try:
        raw = er.confined_file(_campaign_dir(root, name), "invalidation.md").read_bytes()
    except ValueError as exc:
        return None, [f"invalidation.md: {exc}"]
    record, problems = er.parse_record(raw, f"{PILOT_REL}/{name}/invalidation.md")
    errors = [str(p) for p in problems if p.level == er.ERROR]
    if record is None or record.kind != "Invalidation" or record.ident != name:
        return None, errors or [f'invalidation.md must start with "# Invalidation: {name}"']
    values = {key: (record.header.value(key) or "").strip() for key in ("Reviewer", "Date", "Scope", "Reason")}
    if not values["Reviewer"] or not _valid_date(values["Date"]) or values["Scope"].casefold() not in ("stage1", "campaign") \
            or not values["Reason"]:
        errors.append("invalidation.md needs Reviewer, Date (YYYY-MM-DD), Scope (stage1 or campaign) and Reason")
    if errors:
        return None, errors
    return {"reviewer": values["Reviewer"], "date": values["Date"], "scope": values["Scope"].casefold(),
            "sha256": er.sha256_bytes(raw)}, []


def summarize(root: Path, name: str, stage: str, pilot_value: str | None) -> dict:
    """Verify every sealed run of a campaign and compute the stage summary (sections 4.5-4.7).

    Raises IntegrityError (A-C) with every problem; protocol and measurement findings are counted."""
    if stage not in ("1", "all"):
        raise PilotError("summarize takes --stage 1 or --stage all")
    root = Path(root)
    pilot_dir = _pilot_dir(pilot_value)
    campaign = load_campaign(root, name)
    plan = campaign.plan()
    planned = {run["id"]: run for run in plan}
    states = {run["id"]: RunState(run) for run in plan}
    problems: list[str] = []
    evidence_root = pilot_dir / "evidence"
    seen_records: dict[str, str] = {}
    if evidence_root.is_dir():
        for entry in sorted(os.listdir(evidence_root)):
            path = evidence_root / entry
            if entry.startswith(".") and not path.is_dir():
                continue
            if path.is_symlink() or not path.is_dir():
                problems.append(f"evidence/{entry}: not a run directory")
                continue
            try:
                run_id = er.run_id_from_dir(entry)
            except ValueError:
                problems.append(f"evidence/{entry}: not a pilot run directory name")
                continue
            if run_id not in planned:
                problems.append(f"evidence/{entry}: {run_id} is not a planned run of {name}")
                continue
            state = states[run_id]
            state.evidence = path
            if not os.path.lexists(path / RECORD_FILE):
                continue  # prepared, not sealed: pending
            try:
                raw = er.confined_file(path, RECORD_FILE).read_bytes()
                state.record = _json_loads(raw, f"evidence/{entry}/record.json")
            except ValueError as exc:
                problems.append(f"{run_id}: {exc}")
                continue
            state.record_sha256 = er.sha256_bytes(raw)
            record_id = state.record.get("id") if isinstance(state.record, dict) else None
            if record_id in seen_records:
                problems.append(f"{run_id}: record.json claims the run ID {record_id}, already sealed in "
                                f"evidence/{seen_records[record_id]} (duplicate ID)")
            elif isinstance(record_id, str):
                seen_records[record_id] = entry
            problems.extend(f"{run_id}: {item}" for item in _verify_record(state, campaign))
    invalidation, invalidation_problems = _read_invalidation(root, name)
    problems.extend(invalidation_problems)
    if problems:
        raise IntegrityError(problems)
    stage1 = _committed_stage1(root, campaign)
    corpus = _corpus_root(root)
    verified: dict[str, dict] = {}
    notes: list[str] = []
    complete = True
    for state in states.values():
        in_scope = state.run["condition"] == "baseline" or _in_stage(state.run, stage)
        if state.record is None or not in_scope:
            continue
        state.status = state.record["session"]["status"]
        _protocol(state, campaign, stage1)
        if state.run["condition"] == "skill" and state.status == "completed":
            if not _artifact(state, campaign, corpus, verified, notes):
                complete = False
        _review(state, campaign)
    entries = {run_id: _run_entry(state, campaign) for run_id, state in states.items()}
    stage_runs = [entries[r["id"]] for r in plan if r["condition"] == "skill" and _in_stage(r, stage)]
    baseline_runs = [entries[r["id"]] for r in plan if r["condition"] == "baseline"]
    hosts = list(campaign.tasks["hosts"])
    task_ids = [task["id"] for task in campaign.heldout]
    targets = compute_targets(stage_runs, campaign.thresholds, campaign.qualified_policy, campaign.per_host, hosts)
    reviewed = [r for r in stage_runs if r["reviewed"]]
    secondary = [
        {"key": "essentialFactRecall", "id": "T4", "label": "per-protocol (reviewed runs only)",
         **_ratio(sum(r["ess"] for r in reviewed), sum(r["ESS"] for r in reviewed))},
        {"key": "knownUnresolvedQualified", "id": "T5", "label": "per-protocol (reviewed runs only)",
         **_ratio(sum(r["unk"] for r in reviewed), sum(r["UNK"] for r in reviewed))},
    ]
    stage_states = [states[r["id"]] for r in stage_runs]
    pending = [s.run["id"] for s in stage_states if s.status == "pending"]
    unreviewed = [s.run["id"] for s in stage_states if s.status == "completed" and not s.invalid
                  and s.review_status in ("missing", "incomplete")]
    review_problems = [f"{s.run['id']}: {problem}" for s in stage_states for problem in s.review_problems]
    reasons: list[str] = []
    if invalidation is not None:
        value = "invalid"
        reasons.append(f"the owner recorded an invalidation (scope {invalidation['scope']}, {invalidation['date']})")
    elif pending or unreviewed or review_problems or not complete:
        value = "incomplete"
        if pending:
            reasons.append(f"{len(pending)} planned run(s) pending: " + ", ".join(pending[:6]) + (" ..." if len(pending) > 6 else ""))
        if unreviewed:
            reasons.append(f"{len(unreviewed)} completed run(s) unreviewed: " + ", ".join(unreviewed[:6])
                           + (" ..." if len(unreviewed) > 6 else ""))
        if review_problems:
            reasons.append(f"{len(review_problems)} review problem(s) unresolved")
        if not complete:
            reasons.append("artifact verification is incomplete (corpus absent or unverified)")
    else:
        missed = [t for t in targets if not t["met"]]
        if stage == "1":
            value = "stop" if missed else "go"
        else:
            value = "targets-missed" if missed else "targets-met"
        for target in missed:
            if target["comparator"] == "<=":
                reasons.append(f"{target['id']} {target['key']}: {target['numerator']} (needs <= {target['threshold']:g})")
            else:
                shown = f"{target['numerator']}/{target['denominator']}"
                reasons.append(f"{target['id']} {target['key']}: {shown} (needs >= {target['threshold']:g})"
                               + ("" if not target.get("perHost") else " pooled or within a host"))
        if value == "go":
            reasons.append(GO_TEXT)
    early = _early_stop(stage_runs, targets) if value == "incomplete" else []
    per_host = {host: _group_metrics([r for r in stage_runs if r["host"] == host], campaign.qualified_policy) for host in hosts}
    per_task = {task: _group_metrics([r for r in stage_runs if r["task"] == task], campaign.qualified_policy) for task in task_ids}
    macro = {}
    for key in RATE_KEYS:
        values = [per_task[task][key]["value"] for task in task_ids if per_task[task][key]["value"] is not None]
        macro[key] = sum(values) / len(values) if values else None
    sensitivity = {}
    for key in ("supportedClaimPrecision", "essentialFactRecall"):
        options = []
        for task in task_ids:
            rest = _group_metrics([r for r in stage_runs if r["task"] != task], campaign.qualified_policy)[key]
            if rest["value"] is not None:
                options.append((rest["value"], task))
        sensitivity[key] = ({"min": min(options)[0], "minWithout": min(options)[1], "max": max(options)[0],
                             "maxWithout": max(options)[1]} if options else None)
    failure_rows: dict[tuple, int] = {}
    failure_runs = []
    for run in stage_runs:
        if run["status"] == "completed":
            continue
        kind = (run["failure"] or {}).get("kind")
        key = (run["status"], kind or "-", run["host"], run["task"])
        failure_rows[key] = failure_rows.get(key, 0) + 1
        if run["status"] != "pending":
            failure_runs.append({"id": run["id"], "status": run["status"], "failure": kind,
                                 "detail": (run["failure"] or {}).get("detail"), "invalidReasons": run["invalidReasons"]})
    failures = {"counts": [{"status": k[0], "failure": k[1], "host": k[2], "task": k[3], "runs": n}
                           for k, n in sorted(failure_rows.items())],
                "runs": failure_runs}
    baselines = _baselines(baseline_runs, entries, campaign) if campaign.baselines_planned else None
    disputed = []
    for task in task_ids:
        reference = campaign.references[task]
        essential = set(reference["essentialFactIds"])
        for dispute in reference["disputes"]:
            if isinstance(dispute, dict) and dispute.get("item") in essential:
                disputed.append({"task": task, "item": dispute["item"]})
    notes_text = caveats(len(task_ids), len(hosts), campaign.tasks["repetitions"])
    if disputed:
        notes_text.append("Disputed essential facts: " + ", ".join(f"{d['item']}" for d in disputed) + ".")
    if any(r["status"] == "invalid" for r in stage_runs):
        notes_text.append(f"Runs counted invalid count as failures; {INVALID_RUN_NOTE}.")
    inputs = {"candidate": campaign.candidate_sha256, "freeze": campaign.freeze_sha256,
              "referenceSet": campaign.reference_set_sha256,
              "invalidation": invalidation["sha256"] if invalidation else None,
              "runs": [{"id": s.run["id"], "record": s.record_sha256, "review": s.review_sha256,
                        "amendments": [a["previous"] for a in (s.record or {}).get("amendments") or []]}
                       for s in states.values() if s.record is not None]}
    tooling = {"tools/workflow_pilot.py": er.sha256_file(Path(__file__).resolve()),
               "tools/eval_records.py": er.sha256_file(TOOLS / "eval_records.py"),
               "tools/workflow_candidate.py": er.sha256_file(TOOLS / "workflow_candidate.py"),
               "skills/mlview/scripts/artifact.py": next(
                   item["sha256"] for item in campaign.candidate["skill"]["files"] if item["path"] == "scripts/artifact.py")}
    return {
        "format": SUMMARY_FORMAT, "campaign": name, "stage": stage, "generatedAt": _now(),
        "candidateSha256": campaign.candidate_sha256, "referenceRevision": campaign.reference_revision,
        "qualifiedClaims": campaign.qualified_policy, "perHostTargets": campaign.per_host,
        "tooling": tooling, "inputs": inputs, "verification": {"complete": complete, "notes": notes},
        "runs": stage_runs, "targets": targets, "secondary": secondary, "reported": _reported_totals(stage_runs),
        "perHost": per_host, "perTask": per_task,
        "macro": macro, "sensitivity": sensitivity, "failures": failures, "baselines": baselines,
        "decision": {"value": value, "reasons": reasons, "earlyStopIndicators": early, "label": NOT_APPROVAL},
        "disputedEssentialFacts": disputed, "caveats": notes_text, "note": SUMMARY_NOTE, "pilotApproved": False,
    }


def _baselines(baseline_runs: list[dict], entries: dict[str, dict], campaign: Campaign) -> dict:
    completed = [r for r in baseline_runs if r["status"] == "completed"]
    reviewed = [r for r in baseline_runs if r["reviewed"]]
    precision = _precision_counts([r["baselineClaims"] for r in reviewed], campaign.qualified_policy)
    accusations = {severity: sum(r["falseAccusationsListed"][severity] for r in reviewed) for severity in ("high", "medium", "low")}
    minutes = [r["activeMinutes"] for r in baseline_runs if isinstance(r["activeMinutes"], (int, float))]
    paired = []
    for run in baseline_runs:
        skill = entries.get(f"{run['task']}:{run['host']}:1")

        def side(entry: dict) -> dict:
            prec = _precision_counts([entry["baselineClaims"]] if entry["condition"] == "baseline"
                                     else [entry["claims"][b] for b in ("observed", "inferred")], campaign.qualified_policy)
            return {"status": entry["status"], "reviewed": entry["reviewed"], "ess": entry["ess"], "ESS": entry["ESS"],
                    "unk": entry["unk"], "UNK": entry["UNK"], "precision": _ratio(*prec) if entry["reviewed"] else None}

        skill_side, base_side = side(skill), side(run)
        difference = None
        if run["ESS"]:
            difference = (skill["ess"] - run["ess"]) / run["ESS"]
        paired.append({"task": run["task"], "host": run["host"], "skill": skill_side, "baseline": base_side,
                       "recallDifference": difference})
    return {"planned": len(baseline_runs), "completed": len(completed), "reviewed": len(reviewed),
            "precision": _ratio(*precision),
            "recall": _ratio(sum(r["ess"] for r in baseline_runs), sum(r["ESS"] for r in baseline_runs)),
            "unknowns": _ratio(sum(r["unk"] for r in baseline_runs), sum(r["UNK"] for r in baseline_runs)),
            "falseAccusations": accusations,
            "activeMinutes": {"total": sum(minutes), "runs": len(minutes),
                              "mean": (sum(minutes) / len(minutes)) if minutes else None},
            "paired": paired,
            "note": "Baselines are never part of the gate; the paired table compares skill repeat 1 with the no-skill session."}


# --------------------------------------------------------------------------------------------
# Markdown, rendered only from the summary JSON


def _fmt_ratio(item: dict | None) -> str:
    if not item or item.get("denominator") in (None, 0):
        return "n/a" if not item else f"{item.get('numerator', 0)}/0"
    numerator, denominator = item["numerator"], item["denominator"]
    return f"{numerator}/{denominator}" if numerator == denominator else f"{numerator}/{denominator} ({_pct(numerator, denominator)})"


def _fmt_value(value: object) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _needed(target: dict) -> str:
    if target["comparator"] == "<=":
        return f"{target['threshold']:g}"
    return "100%" if target["threshold"] >= 1 else f"≥{100 * target['threshold']:g}%"


def render_markdown(summary: dict) -> str:
    """The Markdown summary; every value comes from the summary JSON."""
    stage_title = "Stage 1 summary" if summary["stage"] == "1" else "all-stage summary"
    date = summary["generatedAt"][:10]
    decision = summary["decision"]
    lines = [f"# MLView pilot {summary['campaign']} — {stage_title} ({date})",
             f"**Decision: {decision['value'].upper()}** — {decision['label']}.", ""]
    for reason in decision["reasons"]:
        lines.append(f"- {reason}")
    if decision["earlyStopIndicators"]:
        lines += ["", "Early-stop indicators (targets that can no longer be met; no decision before every run is adjudicated):"]
        lines += [f"- {item}" for item in decision["earlyStopIndicators"]]
    policy = summary["qualifiedClaims"]
    labels = dict(TARGET_LABELS)
    labels["supportedClaimPrecision"] = f"Supported claims (observed+inferred; qualified = {policy})"
    lines += ["", "| Target | Result | Needed | Met |", "|---|---|---|---|"]
    for target in summary["targets"]:
        if target["comparator"] == "<=":
            result = str(target["numerator"])
        else:
            result = _fmt_ratio(target) + (" (vacuous)" if target.get("vacuous") else "")
        per_host = target.get("perHost")
        if per_host:
            result += "; per host " + ", ".join(f"{host} {_fmt_ratio(item)}" for host, item in sorted(per_host.items()))
        lines.append(f"| {labels[target['key']]} | {result} | {_needed(target)} | {'yes' if target['met'] else 'no'} |")
    t3 = next((t for t in summary["targets"] if t["key"] == "supportedClaimPrecision"), None)
    if t3 and t3.get("byBasis"):
        lines += ["", "Supported claims by basis: " + "; ".join(f"{basis} {_fmt_ratio(item)}"
                                                               for basis, item in sorted(t3["byBasis"].items())) + "."]
    lines += ["", "Secondary (per-protocol, reviewed runs only): "
              + "; ".join(f"{item['id']} {_fmt_ratio(item)}" for item in summary["secondary"]) + "."]
    failures = summary["failures"]["runs"]
    lines.append("")
    if failures:
        lines.append("Failures: " + "; ".join(
            f"{item['id']} — {item['status']}"
            + (f" ({item['failure']}" + (f": {item['detail']}" if item.get("detail") else "") + ")" if item.get("failure") else "")
            + (f" [{'; '.join(item['invalidReasons'])}]" if item["invalidReasons"] else "")
            for item in failures) + ".")
    else:
        lines.append("Failures: none.")
    for title, groups in (("Per host", summary["perHost"]), ("Per task", summary["perTask"])):
        lines += ["", f"## {title}", "", "| | Runs | Valid | Anchors | Precision | Recall | Unknowns | High FA |",
                  "|---|---|---|---|---|---|---|---|"]
        for name, group in sorted(groups.items()):
            lines.append(f"| {name} | {group['runs']} | {_fmt_ratio(group['structurallyValid'])} | "
                         f"{_fmt_ratio(group['exactAnchors'])} | {_fmt_ratio(group['supportedClaimPrecision'])} | "
                         f"{_fmt_ratio(group['essentialFactRecall'])} | {_fmt_ratio(group['knownUnresolvedQualified'])} | "
                         f"{group['highSeverityFalseAccusations']} |")
    reported = summary["reported"]
    lines += ["", "Reported, not gated: finding severity " + ", ".join(f"{k} {v}" for k, v in sorted(reported["severity"].items()))
              + "; reference defects " + ", ".join(f"{k} {v}" for k, v in sorted(reported["referenceDefects"].items()))
              + "; usability " + ("; ".join(f"{q} " + ", ".join(f"{a} {n}" for a, n in sorted(answers.items()))
                                            for q, answers in sorted(reported["usability"].items())) or "none") + "."]
    lines += ["", "## Sensitivity", "", "Macro means of the per-task rates: "
              + ", ".join(f"{key} {_fmt_value(value)}" for key, value in sorted(summary["macro"].items())) + "."]
    for key, item in sorted(summary["sensitivity"].items()):
        if item:
            lines.append(f"Leave-one-task-out {key}: {_fmt_value(item['min'])} (without {item['minWithout']}) to "
                         f"{_fmt_value(item['max'])} (without {item['maxWithout']}).")
    baselines = summary["baselines"]
    if baselines:
        lines += ["", "## Baseline comparison", "", baselines["note"],
                  f"Completed {baselines['completed']}/{baselines['planned']}; reviewed {baselines['reviewed']}; precision "
                  f"{_fmt_ratio(baselines['precision'])}; recall (all planned) {_fmt_ratio(baselines['recall'])}; unknowns "
                  f"stated {_fmt_ratio(baselines['unknowns'])}; false accusations listed high {baselines['falseAccusations']['high']}, "
                  f"medium {baselines['falseAccusations']['medium']}, low {baselines['falseAccusations']['low']}; active minutes "
                  f"{baselines['activeMinutes']['total']:g} over {baselines['activeMinutes']['runs']} run(s).",
                  "", "| Task | Host | Skill recall | No-skill recall | Difference |", "|---|---|---|---|---|"]
        for row in baselines["paired"]:
            difference = "n/a" if row["recallDifference"] is None else f"{100 * row['recallDifference']:+.1f} pts"
            lines.append(f"| {row['task']} | {row['host']} | {row['skill']['ess']}/{row['skill']['ESS']} ({row['skill']['status']}) | "
                         f"{row['baseline']['ess']}/{row['baseline']['ESS']} ({row['baseline']['status']}) | {difference} |")
    verification = summary["verification"]
    lines += ["", "## Verification", "", f"Artifact verification complete: {'yes' if verification['complete'] else 'no'}."]
    lines += [f"- {note}" for note in verification["notes"]]
    lines += ["", "## Caveats", ""] + [f"{index}. {text}" for index, text in enumerate(summary["caveats"], 1)]
    inputs = summary["inputs"]
    lines += ["", "## Inputs (hashes)", "", f"- candidate.json {summary['candidateSha256']}",
              f"- referenceRevision {summary['referenceRevision']}", f"- freeze.json {inputs['freeze']}"]
    for run in inputs["runs"]:
        lines.append(f"- {run['id']}: record {run['record']}" + (f", review {run['review']}" if run["review"] else "")
                     + (f", {len(run['amendments'])} amendment(s)" if run["amendments"] else ""))
    lines += ["", summary["note"], ""]
    return "\n".join(lines)


def record_summary(root: Path, summary: dict) -> tuple[Path, Path]:
    """Write stage<n>-summary.{json,md} exclusively; only a recordable decision is written."""
    value = summary["decision"]["value"]
    allowed = ("go", "stop", "invalid") if summary["stage"] == "1" else ("targets-met", "targets-missed", "invalid")
    if value not in allowed:
        raise PilotError(f"the decision is {value}; only {', '.join(allowed)} can be recorded")
    json_bytes = er.canonical_json(summary)
    md_bytes = render_markdown(json.loads(json_bytes)).encode("utf-8")
    for data in (json_bytes, md_bytes):
        match = MACHINE_PATH_RE.search(data.decode("utf-8"))
        if match:
            raise PilotError("the summary contains a machine path; amend the session wording (run-finish --amend) and "
                             "summarize again")
    number = "1" if summary["stage"] == "1" else "2"
    directory = _campaign_dir(root, summary["campaign"])
    json_path, md_path = directory / f"stage{number}-summary.json", directory / f"stage{number}-summary.md"
    for path in (json_path, md_path):
        if os.path.lexists(path):
            raise PilotError(f"{path.name} already exists; recorded summaries are never overwritten")
    er.write_exclusive(json_path, json_bytes)
    er.write_exclusive(md_path, md_bytes)
    return json_path, md_path


# --------------------------------------------------------------------------------------------
# Command line


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workflow_eval.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    pilot_help = "directory for run workspaces and evidence (default: $MLVIEW_PILOT_DIR; outside every Git checkout)"
    plan = sub.add_parser("plan", help="print the planned run IDs and conditions")
    plan.add_argument("--campaign", help="use the frozen campaign (adds the planned baselines)")
    plan.add_argument("--stage", choices=("1", "2", "all"), default="all")
    plan.add_argument("--output", type=Path, help="also create this file (exclusive; never overwritten)")
    for command, text in (("run-prepare", "prepare one run's fresh workspace and evidence directory"),
                          ("run-finish", "seal one run's evidence into record.json"),
                          ("review-template", "create the pending human review file of a completed run")):
        item = sub.add_parser(command, help=text)
        item.add_argument("run", help="run ID, for example pilot-nanogpt:codex:1 or pilot-nanogpt:codex:baseline:1")
        item.add_argument("--campaign", required=True)
        item.add_argument("--pilot-dir", help=pilot_help)
        if command == "run-finish":
            item.add_argument("--amend", metavar="REASON", help="re-read session.md and re-seal, keeping the previous record")
    summary = sub.add_parser("summarize", help="verify sealed runs and compute the stage summary against the targets")
    summary.add_argument("--campaign", required=True)
    summary.add_argument("--stage", choices=("1", "all"), required=True)
    summary.add_argument("--json", action="store_true", help="print the JSON summary instead of Markdown")
    summary.add_argument("--record", action="store_true",
                         help="write evals/workflow/pilot/<campaign>/stage<n>-summary.{json,md} (exclusive)")
    summary.add_argument("--pilot-dir", help=pilot_help)
    return parser


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(arguments)
    root = Path(root) if root is not None else ROOT
    try:
        if args.command == "plan":
            value = plan_document(root, args.campaign, args.stage)
            data = er.canonical_json(value)
            if args.output is not None:
                try:
                    er.write_exclusive(args.output, data)
                except FileExistsError:
                    raise PilotError(f"{args.output} already exists; it is never overwritten") from None
            sys.stdout.write(data.decode("utf-8"))
            return 0
        if args.command == "run-prepare":
            return run_prepare(root, args.run, args.campaign, args.pilot_dir)
        if args.command == "run-finish":
            return run_finish(root, args.run, args.campaign, args.pilot_dir, args.amend)
        if args.command == "review-template":
            return review_template(root, args.run, args.campaign, args.pilot_dir)
        summary = summarize(root, args.campaign, args.stage, args.pilot_dir)
        data = er.canonical_json(summary)
        # The Markdown is rendered only from the JSON (section 4.7).
        sys.stdout.write(data.decode("utf-8") if args.json else render_markdown(json.loads(data)))
        if args.record:
            json_path, md_path = record_summary(root, summary)
            print(f"Recorded {json_path.name} and {md_path.name} in {PILOT_REL}/{args.campaign}/; commit them. "
                  f"The summary is {NOT_APPROVAL}.", file=sys.stderr)
        return 0
    except IntegrityError as exc:
        for problem in exc.problems:
            print(f"ERROR {problem}", file=sys.stderr)
        print(f"workflow_eval.py {args.command}: {len(exc.problems)} integrity problem(s); no decision was computed.",
              file=sys.stderr)
        return 1
    except PilotError as exc:
        print(f"workflow_eval.py {args.command}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
