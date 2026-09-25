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
import contextlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, Iterator

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
UNVERIFIED_REASON = "artifact verification is incomplete (corpus absent or unverified)"
PILOT_DIR_REMEDY = "export MLVIEW_PILOT_DIR=~/mlview-pilot"
README_STOP_GO = 'evals/workflow/README.md, "Stage 1 stop/go"'
README_REVIEW = 'evals/workflow/README.md, "Review and adjudicate"'
GO_TEXT = ("Stage 1 met every predefined target. This permits collecting the 48 repeats; it is not a pilot "
           f"pass ({README_STOP_GO}).")
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
        f"({README_REVIEW}).",
        "Each run has a single human reviewer, and verdicts are human judgements, not tool judgements. Disputed "
        "essential facts are listed.",
        "Workspaces contain only the manifest's sparse paths. For example, the upstream root AGENTS.md/CLAUDE.md of "
        "transformers, scikit-learn and diffusers are absent. Reachability of earlier evidence and user-level host "
        "configuration are recorded, not prevented.",
    ]


STATUSES = ("completed", "failed", "timed-out", "blocked")
FAILURE_KINDS = ("no-publication", "repair-budget", "host-error", "cancelled", "setup", "protocol")
# A timed-out session, or one that failed for one of these reasons, ran after the prompt was sent.
SENT_FAILURES = ("no-publication", "repair-budget")
RETRY_RULE = ("a retry is allowed only if the prompt was never sent (the policy's infrastructure retries); a failure "
              "after the prompt was sent is kept and counted")
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
                           PARTIAL_FILE, RECORD_FILE, REVIEW_FILE, CHANGES_FILE, "finish-state.json"})
PREVIOUS_RECORD = "record.previous-{n}.json"
PREVIOUS_RECORD_RE = re.compile(r"record\.previous-(?P<n>[1-9][0-9]*)\.json")
FINISH_STATE = "finish-state.json"
FINISH_FORMAT = "mlview-pilot-finish/1"
LEDGER_FILE = "preparations.jsonl"  # in the pilot directory: one line per run-prepare, never rewritten
LEDGER_FORMAT = "mlview-pilot-preparation/1"
ATTEMPT_RE = re.compile(r"(?P<base>.+)\.attempt-(?P<n>[1-9][0-9]*)")
SKILL_DESTINATIONS = {"claude-code": ".claude/skills/mlview"}
# Host bookkeeping files a host may write into a workspace: reported as warnings, never as changed project files.
HOST_FILES = {"claude-code": frozenset({".claude/settings.local.json"})}
DEFAULT_SKILL_DESTINATION = ".agents/skills/mlview"
MACHINE_PATH_RE = er.MACHINE_PATH_RE
REASON_HINT = '" -- <reason>" (or " — <reason>")'
DETAIL_HINT = '" -- <detail>" (or " — <detail>")'
HEX64_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})", re.ASCII)
TIME_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})", re.ASCII)
MINUTES_RE = re.compile(r"\d+(?:\.\d+)?", re.ASCII)
WHOLE_RE = re.compile(r"\d+", re.ASCII)
PYTHON_RE = re.compile(r"(\d+)\.(\d+)", re.ASCII)
SPLIT_RE = re.compile(r"(?P<base>.+?)#(?P<n>[0-9]+)")
RESPONSE_RE = re.compile(r"response:(?P<line>[0-9]+)(?:-(?P<end>[0-9]+))?(?:#(?P<n>[0-9]+))?", re.ASCII)
LEADING_ZERO_RE = re.compile(r"(?<![0-9])0[0-9]", re.ASCII)
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


def _corpus_remedy(detail: str, name: str) -> str:
    """The next command for a failed corpus verification (--update-sparse repairs only sparse problems)."""
    if "--update-sparse" in detail:
        return (f"python tools/fetch_workflow_repos.py --update-sparse --repo {name}, then "
                "python tools/fetch_workflow_repos.py --verify")
    return "python tools/fetch_workflow_repos.py --verify"


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
        raise PilotError(f"{PILOT_REL}/{name}/candidate.json does not exist in this checkout. If the candidate was "
                         "captured and committed, work on a branch that contains that commit (the pilot tools run from "
                         "main, never from the candidate's source commit, which precedes it); otherwise capture it "
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
    limit = er.history_limit(root)
    if limit is not None:
        raise IntegrityError([f"the full history is needed so the candidate commit, its ancestry and the recorded "
                              f"summaries can be read: {limit}"])
    if _git_run(root, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        raise IntegrityError([f"candidate source commit {commit[:12]} is not in this repository; fetch the full history"])
    ancestry = _git_run(root, "merge-base", "--is-ancestor", commit, "HEAD")
    not_ancestor = f"candidate.json: {workflow_candidate.not_ancestor_problem(commit[:12], name)}"
    if ancestry.returncode != 0 and not_ancestor not in problems:  # workflow_candidate.check reports it too
        problems.append(not_ancestor)
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
    problems.extend(_decision_binding(root, commit, freeze, heldout, references, policy))
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


DECISIONS_REL = "evals/workflow/decisions"
CANDIDATES_REL = er.CANDIDATES_REL


def _decision_binding(root: Path, commit: str, freeze: dict, heldout: list[dict], references: dict[str, dict],
                      policy: object) -> list[str]:
    """The frozen files must come from committed decision files and ledgers: freeze.json lists every
    held-out decision file and the run policy with their bytes at the candidate commit, and each
    reference names those reviews and its ledger, and policy.json its source, by the same hashes."""
    decisions, ledgers = freeze.get("decisionFiles"), freeze.get("candidateLedgers")
    if not isinstance(decisions, dict) or not isinstance(ledgers, dict):
        return ["freeze.json: decisionFiles and candidateLedgers must map repository paths to SHA-256"]
    problems = []
    policy_rel = f"{DECISIONS_REL}/run-policy.md"
    for rel in [f"{DECISIONS_REL}/{task['id']}.md" for task in heldout] + [policy_rel]:
        if rel not in decisions:
            problems.append(f"freeze.json: decisionFiles has no {rel}")
    for task in heldout:
        if f"{CANDIDATES_REL}/{task['id']}.json" not in ledgers:
            problems.append(f"freeze.json: candidateLedgers has no {CANDIDATES_REL}/{task['id']}.json")
    for rel, digest in sorted(decisions.items()) + sorted(ledgers.items()):
        if not isinstance(rel, str) or er._path_problem(rel) or not isinstance(digest, str):
            problems.append(f"freeze.json: {rel!r} is not a repository path with a hash")
            continue
        try:
            data = er.git_show(root, commit, rel)
        except ValueError:
            problems.append(f"{rel} (frozen) does not exist at the candidate commit {commit[:12]}")
            continue
        if er.sha256_bytes(data) != digest:
            problems.append(f"{rel} at {commit[:12]} differs from its freeze.json hash")
    for task_id, reference in references.items():
        if not isinstance(reference, dict):
            continue
        reviews = reference.get("reviews")
        if not isinstance(reviews, list) or not reviews:
            problems.append(f"reference/{task_id}.json: reviews must name the decision files")
        for review in reviews if isinstance(reviews, list) else []:
            path = review.get("path") if isinstance(review, dict) else None
            if path not in decisions or review.get("sha256") != decisions[path]:
                problems.append(f"reference/{task_id}.json: review {path!r} is not a frozen decision file with that hash")
        source = reference.get("candidate")
        path = source.get("path") if isinstance(source, dict) else None
        if path not in ledgers or source.get("sha256") != ledgers[path]:
            problems.append(f"reference/{task_id}.json: candidate {path!r} is not a frozen ledger with that hash")
    source = policy.get("source") if isinstance(policy, dict) else None
    if not isinstance(source, dict) or source.get("path") != policy_rel or source.get("sha256") != decisions.get(policy_rel):
        problems.append(f"policy.json: source must name {policy_rel} with its frozen hash")
    return problems


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


def session_template(run_id: str, condition: str, prior_attempts: int = 0) -> bytes:
    baseline = condition == "baseline"
    lines = [
        f"# Session: {run_id}",
        "> Fill after the session. Times are RFC 3339 UTC (2026-10-10T09:02:11Z). Minutes may be decimal.",
        "> Status: completed (skill: pilot.mlview.json published; baseline: answer captured) | failed | timed-out | blocked",
        f"> Failure: no-publication | repair-budget | host-error | cancelled | setup | protocol, then {DETAIL_HINT}",
        "> Prompt sent: yes | no. Write no only if the prompt never reached the host; only then may a failed or "
        "blocked attempt be retried.",
        "> Write no machine paths (home folders, drive letters) in any value; describe places in words.",
    ]
    if baseline:
        lines.append("> Baseline: no MLView skill, plugin or artifact, and no skill invocation (the prompt is sent as a plain "
                     "message). transcript.txt is required and scored; Invocation, Repair rounds, Helper Python and UI log "
                     "do not apply.")
    lines += [
        "Status: pending", "Failure:", "Prompt sent:", "Started:", "Ended:", "Active minutes:", "Approval wait minutes:",
        "Repair rounds:", "Host version:", "Extension version:", "Model:", "Reasoning:", "Resolved model:",
        "Invocation:", "Helper Python:", "Usage:", "Transcript: transcript.txt",
        "UI log:" if baseline else "UI log: ui-log.md", f"Prior attempts: {prior_attempts}",
        f"MLView available to host: {'no' if baseline else 'yes'}",
        '> Deviations: one line each, "<what happened> -- invalidates: yes | no" (" — " also works)',
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
                                              f'{", ".join(FAILURE_KINDS)}, then {DETAIL_HINT}.')
        else:
            kind, extra, detail = _split_reason(failure_text)
            if kind.casefold() not in FAILURE_KINDS:
                add(er.ERROR, line_of("Failure"), f'"Failure: {failure_text}" does not start with a failure kind. Write one of: '
                                                  f'{", ".join(FAILURE_KINDS)}, then {DETAIL_HINT}.')
            elif extra:
                hint = er.SEPARATOR_HINT if er.lone_hyphen(extra) else f"write the detail after {DETAIL_HINT}"
                add(er.ERROR, line_of("Failure"), f'"Failure: {_one_line(failure_text, 60)}": {hint}')
            else:
                failure = {"kind": kind.casefold(), "detail": detail}
    elif completed and failure_text:
        add(er.ERROR, line_of("Failure"), 'Status is completed, so "Failure:" must be empty.')
    sent_text = value("Prompt sent").casefold()
    prompt_sent = {"yes": True, "no": False}.get(sent_text)
    if sent_text and prompt_sent is None:
        add(er.ERROR, line_of("Prompt sent"), "Prompt sent must be yes or no.")
    elif prompt_sent is False:
        sent_because = (f"Status is {status}" if status in ("completed", "timed-out") else
                        f"Failure is {failure['kind']}" if failure and failure["kind"] in SENT_FAILURES else None)
        if sent_because:
            add(er.ERROR, line_of("Prompt sent"), f'{sent_because}, so the prompt was sent; write "Prompt sent: yes".')

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
        "promptSent": prompt_sent, "deviations": [],
    }
    if completed:
        required = ["Started", "Ended", "Active minutes", "Approval wait minutes", "Host version", "Extension version",
                    "Model", "Reasoning", "Prior attempts", "MLView available to host"]
        if not baseline:
            required += ["Invocation", "Repair rounds", "Helper Python"]
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
    if prompt_sent is False and isinstance(repairs, int) and repairs > 0:
        add(er.ERROR, line_of("Prompt sent"), f"Repair rounds is {repairs}, so the validator ran and the prompt was sent; "
                                              'write "Prompt sent: yes".')
    if prompt_sent is False and transcript is not None and evidence_dir is not None:
        try:
            said = er.confined_file(evidence_dir, transcript).read_bytes()
            prompt = er.confined_file(evidence_dir, PROMPT_FILE).read_bytes()
        except ValueError:
            said = prompt = b""
        if _contains_prompt(said, prompt):
            add(er.ERROR, line_of("Prompt sent"), f'the transcript contains {PROMPT_FILE}, so the prompt was sent; write '
                                                  '"Prompt sent: yes".')
    deviations = record.section("Deviations")
    for item in deviations.lines if deviations is not None else []:
        text = f"{item.key}: {item.value}" if item.value else item.key
        match = DEVIATION_RE.fullmatch(text)
        flag = match.group("flag").casefold() if match else ""
        if not match or flag not in ("yes", "no"):
            add(er.ERROR, item.line, f'"{_one_line(text, 60)}" must end with " -- invalidates: yes" or " -- invalidates: no" '
                                     '(" — " also works).', "Deviations")
            continue
        found = MACHINE_PATH_RE.search(text)
        if found:
            add(er.ERROR, item.line, f"the deviation contains a machine path ({found.group(0)}); sealed records and summaries "
                                     "must not name machine paths. Describe the place in words.", "Deviations")
            continue
        block["deviations"].append({"text": _one_line(match.group("text"), 500), "invalidates": flag == "yes"})
    for item in header.lines:
        found = MACHINE_PATH_RE.search(item.value or "")
        if found:
            add(er.ERROR, item.line, f"{item.key} contains a machine path ({found.group(0)}); sealed records and summaries "
                                     "must not name machine paths. Describe it without the path.")
    problems.sort(key=lambda p: p.line)
    ok = status is not None and not any(p.level == er.ERROR for p in problems)
    return SessionResult(problems, block if ok else None, transcript, ui_log)


def _contains_prompt(said: bytes, prompt: bytes) -> bool:
    """Whether a transcript contains PROMPT.txt (whitespace-normalised)."""
    text = prompt.decode("utf-8", "replace")
    return bool(text.strip()) and " ".join(text.split()) in " ".join(said.decode("utf-8", "replace").split())


OUTPUT_SUFFIXES = (".mlview.json", ".draft.json")
OUTPUT_DIR = ".mlview/"
INSTALLED_SKILL_PREFIXES = (".agents/skills/mlview/", ".claude/skills/mlview/", ".github/skills/mlview/")


def _outputs_added(before: dict, after: dict) -> list[str]:
    """Workspace paths that only the skill writes after the prompt, added since run-prepare: anything
    under ``.mlview/`` (the skill's drafts and records, such as .mlview/llm/<run-id>/draft.json in
    SKILL.md), or a ``*.draft.json`` or ``*.mlview.json`` file elsewhere. Nothing writes under
    ``.mlview/`` in a pilot workspace before the prompt. Host settings files and the installed skill
    (listed in workspace-before.json anyway) never count."""
    found = []
    for rel in after:
        folded = rel.casefold()
        if rel in before or folded.startswith(INSTALLED_SKILL_PREFIXES):
            continue
        if folded.startswith(OUTPUT_DIR) or folded.endswith(OUTPUT_SUFFIXES):
            found.append(rel)
    return sorted(found)


def _sealed_json(evidence: Path, entry: object) -> object | None:
    """The JSON of a sealed evidence entry whose bytes still match its hash, else None."""
    if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
        return None
    try:
        data = er.confined_file(evidence, entry["file"]).read_bytes()
    except ValueError:
        return None
    if er.sha256_bytes(data) != entry.get("sha256"):
        return None
    try:
        return _json_loads(data, entry["file"])
    except ValueError:
        return None


def _sent_evidence(seal: dict, evidence: Path | None) -> str | None:
    """Sealed facts showing that the prompt reached the host, whatever the session says: a captured
    artifact, repair rounds, a sealed transcript that contains PROMPT.txt, or a draft or artifact the
    skill wrote in the workspace (anything under .mlview/, a *.draft.json or a *.mlview.json; see
    _outputs_added). Changed project files and host files are not proof: a host may write files when
    it starts, before any prompt."""
    session = seal.get("session") if isinstance(seal.get("session"), dict) else {}
    sealed = seal.get("evidence") if isinstance(seal.get("evidence"), dict) else {}
    for key in ("artifact", "partialArtifact"):
        entry = sealed.get(key)
        if isinstance(entry, dict):
            return f"it captured the published artifact ({entry.get('file')})"
    rounds = session.get("repairRounds")
    if _is_int(rounds) and rounds > 0:
        return f"its session reports {rounds} repair round(s)"
    if evidence is None:
        return None
    transcript = sealed.get("transcript")
    if isinstance(transcript, dict) and isinstance(transcript.get("file"), str):
        try:
            said = er.confined_file(evidence, transcript["file"]).read_bytes()
            prompt = er.confined_file(evidence, PROMPT_FILE).read_bytes()
        except ValueError:
            said = prompt = b""
        if er.sha256_bytes(said) == transcript.get("sha256") and _contains_prompt(said, prompt):
            return f"its sealed transcript contains {PROMPT_FILE}"
    workspace = seal.get("workspace") if isinstance(seal.get("workspace"), dict) else {}
    before, after = (_sealed_json(evidence, workspace.get(key)) for key in ("before", "after"))
    if isinstance(before, dict) and isinstance(after, dict):
        outputs = _outputs_added(before, after)
        if outputs:
            return f"the skill wrote {outputs[0]} in its workspace"
    return None


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
    if summary.get("format") != SUMMARY_FORMAT or summary.get("stage") != "1" or summary.get("campaign") != campaign.name:
        return f'the committed stage1-summary.json is not a "{SUMMARY_FORMAT}" Stage 1 summary of {campaign.name}'
    decision = summary.get("decision") if isinstance(summary.get("decision"), dict) else {}
    if decision.get("value") != "go":
        return f"the committed Stage 1 decision is {decision.get('value')!r}, not go"
    inputs = summary.get("inputs") if isinstance(summary.get("inputs"), dict) else {}
    if summary.get("candidateSha256") != campaign.candidate_sha256 or inputs.get("candidate") != campaign.candidate_sha256:
        return "the committed Stage 1 summary belongs to another candidate"
    if inputs.get("freeze") != campaign.freeze_sha256 or inputs.get("referenceSet") != campaign.reference_set_sha256 \
            or summary.get("referenceRevision") != campaign.reference_revision:
        return "the committed Stage 1 summary was computed from other frozen inputs"
    if _parse_time(summary.get("generatedAt")) is None:
        return "the committed Stage 1 summary has no valid generatedAt"
    return None


def _stage1_input_index(summary: dict, planned: dict[str, dict]) -> dict[str, dict]:
    """The inputs.runs entries of a summary's Stage 1 runs, by run ID."""
    runs = (summary.get("inputs") or {}).get("runs") if isinstance(summary.get("inputs"), dict) else None
    return {item["id"]: item for item in runs if isinstance(runs, list) and isinstance(item, dict)
            and item.get("id") in planned and planned[item["id"]]["stage"] == 1} if isinstance(runs, list) else {}


def _sealed_inputs(item: dict) -> tuple:
    """The sealed part of one run's inputs: its record, amendments and earlier attempts (not review.md,
    which people may re-save; what a review says is compared through the re-computation)."""
    earlier = tuple((attempt.get("attempt"), attempt.get("record"), tuple(attempt.get("amendments") or []))
                    for attempt in item.get("earlierAttempts") or [] if isinstance(attempt, dict))
    return item.get("record"), tuple(item.get("amendments") or []), earlier


def _input_differences(fresh: dict, recorded: dict, planned: dict[str, dict]) -> tuple[list[str], list[str]]:
    """(sealed, reviews) between the Stage 1 inputs of a re-computation and a committed summary:
    each run whose sealed record, amendments or earlier attempts differ (or that has no sealed record
    in this pilot directory), and each run whose review.md bytes differ."""
    now, then = _stage1_input_index(fresh, planned), _stage1_input_index(recorded, planned)
    sealed: list[str] = []
    missing = sorted(set(then) - set(now))
    if missing:
        sealed.append(f"{len(missing)} Stage 1 run(s) of the summary have no sealed record in this pilot directory, "
                      f"for example {missing[0]}")
    reviews = []
    for run_id in sorted(now):
        item, old = now[run_id], then.get(run_id)
        if old is None:
            sealed.append(f"{run_id} is sealed here but not in the summary's inputs")
            continue
        (record, amendments, earlier), (old_record, old_amendments, old_earlier) = _sealed_inputs(item), _sealed_inputs(old)
        if record != old_record:
            sealed.append(f"{run_id}: record.json sha256 {str(record)[:12]}... differs from the recorded "
                          f"{str(old_record)[:12]}...")
        elif amendments != old_amendments:
            sealed.append(f"{run_id}: {len(amendments)} amendment(s) here, {len(old_amendments)} recorded")
        elif earlier != old_earlier:
            sealed.append(f"{run_id}: its earlier attempts differ from the recorded ones")
        if item.get("review") != old.get("review"):
            reviews.append(run_id)
    return sealed, reviews


def _shown(items: list[str], limit: int = 3, separator: str = "; ") -> str:
    return separator.join(items[:limit]) + (f"{separator}and {len(items) - limit} more" if len(items) > limit else "")


TOOL_KEYS = ("tools/workflow_pilot.py", "tools/eval_records.py", "tools/workflow_candidate.py")
HELPER_KEY = "skills/mlview/scripts/artifact.py"
SAME_TOOLS = "same tools"


def _tooling_binding(root: Path, campaign: Campaign, committed: dict, recomputed: dict) -> str | None:
    """SAME_TOOLS when the committed Stage 1 summary names the running tools; None when it names other
    tools that are bound by Git; otherwise why the summary's tooling cannot be trusted. Each differing
    tool hash must be the sha256 of a version of that file committed in the history of the commit
    that recorded the summary: summarize --record writes only the tools committed at HEAD, and those
    tool versions stay in the history of the commit that later adds the summary after a pull, a merge
    or a tool commit in between (a rebase that rewrites an unpushed commit holding them can break the
    link; the pilot README gives the repair before pushing). The tooling field is part of the file
    being verified, so it never names tools that were never committed, and the decision, the sealed
    inputs, the disclosure of every run and what the summary reports of each review changed since are
    compared whichever tools it names."""
    tooling = committed.get("tooling") if isinstance(committed.get("tooling"), dict) else {}
    fresh = recomputed["tooling"]
    if tooling.get(HELPER_KEY) != fresh[HELPER_KEY]:
        return (f"the committed Stage 1 summary names a {HELPER_KEY} that is not the candidate's frozen helper (a "
                "recorded summary is written only by summarize --record)")
    differing = [key for key in TOOL_KEYS if tooling.get(key) != fresh[key]]
    if not differing:
        return SAME_TOOLS
    rel = f"{PILOT_REL}/{campaign.name}/stage1-summary.json"
    versions = _path_versions(root, rel)
    first = versions.first[1] if versions is not None and versions.first is not None else None
    if first is None:
        return ("the committed Stage 1 summary names tools other than the running ones, and the commit that recorded it "
                "cannot be read")
    for key in differing:
        try:
            known = er.version_hashes(root, key, first)
        except ValueError:
            return (f"the committed Stage 1 summary names a {key} other than the running one, and the Git history of "
                    f"{key} cannot be read")
        if tooling.get(key) not in known:
            return (f"the committed Stage 1 summary names a {key} (sha256 {str(tooling.get(key))[:12]}...) that is "
                    f"neither the running one nor any version committed in the history of {first[:12]}, the commit that "
                    "recorded the summary (a recorded summary is written only by summarize --record, with the tools "
                    "committed at HEAD; a rebase that rewrote the commit holding those tools also causes this)")
    return None


def _disclosure(summary: dict) -> dict:
    """What a Stage 1 summary discloses about retries and failures, taken from sealed facts only, so a
    later tool version that judges a run differently does not change it: runs[] id, status (every
    skill run of a go is completed), failure kind and attempts, failures.runs, failures.earlierAttempts,
    and the baselines' failure kinds, earlier attempts and baselines.earlierAttempts. A baseline's
    computed status and review state belong to the tools (baselines never change the decision), and
    the wording of invalid reasons and failure details is not compared either."""
    def kind(value: object) -> object:
        return value.get("kind") if isinstance(value, dict) else value

    def attempts(run: dict) -> tuple:
        return tuple((str(item.get("attempt")), str(item.get("status")), str(item.get("promptSent")),
                      str(kind(item.get("failure")))) for item in run.get("attempts") or [] if isinstance(item, dict))

    def replaced(items: object) -> list:
        return sorted((str(item.get("id")), str(item.get("attempt")), str(item.get("status")), str(item.get("failure")),
                       str(item.get("promptSent"))) for item in items or [] if isinstance(item, dict)) \
            if isinstance(items, list) else [repr(items)]

    runs = summary.get("runs") if isinstance(summary.get("runs"), list) else []
    failures = summary.get("failures") if isinstance(summary.get("failures"), dict) else {}
    baselines = summary.get("baselines") if isinstance(summary.get("baselines"), dict) else {}
    baseline_runs = baselines.get("runs") if isinstance(baselines.get("runs"), list) else []
    return {
        "runs": sorted((str(run.get("id")), str(run.get("status")), str(kind(run.get("failure"))),
                        str(run.get("priorAttempts")), attempts(run))
                       for run in runs if isinstance(run, dict)),
        "failures.runs": sorted((str(item.get("id")), str(item.get("status")), str(item.get("failure")))
                                for item in failures.get("runs") or [] if isinstance(item, dict)),
        "failures.earlierAttempts": replaced(failures.get("earlierAttempts") or []),
        "baselines.runs": sorted((str(run.get("id")), str(kind(run.get("failure"))), str(run.get("priorAttempts")),
                                  attempts(run)) for run in baseline_runs if isinstance(run, dict)),
        "baselines.earlierAttempts": replaced(baselines.get("earlierAttempts") if "earlierAttempts" in baselines
                                              else []),
    }


# What a summary reports that a Stage 1 run's review verdicts determine: for a skill run these fields
# of its runs[] entry, for a baseline these fields of the baseline side of its paired row. The
# tool-judged status and reviewStatus, the baselines' state and the reference totals (ESS, UNK) are
# not part of it.
RUN_VERDICT_KEYS = ("reviewed", "reviewer", "claims", "baselineClaims", "ess", "unk", "fa", "falseAccusationsListed",
                    "reported")
PAIRED_VERDICT_KEYS = ("reviewed", "ess", "unk", "precision")


def _verdict_fields(summary: dict, planned: dict[str, dict]) -> dict[str, dict]:
    """By run ID, the fields of ``summary`` that the review verdicts of each Stage 1 run determine
    (RUN_VERDICT_KEYS of a skill run's runs[] entry, PAIRED_VERDICT_KEYS of a baseline's paired row),
    as far as the summary carries them."""
    value = json.loads(er.canonical_json(summary))
    found: dict[str, dict] = {}
    for run in value.get("runs") if isinstance(value.get("runs"), list) else []:
        if isinstance(run, dict) and (planned.get(run.get("id")) or {}).get("stage") == 1:
            found[run["id"]] = {key: run[key] for key in RUN_VERDICT_KEYS if key in run}
    baselines = value.get("baselines") if isinstance(value.get("baselines"), dict) else {}
    paired = baselines.get("paired") if isinstance(baselines.get("paired"), list) else []
    sides = {(row.get("task"), row.get("host")): row.get("baseline") for row in paired if isinstance(row, dict)}
    for run_id, run in planned.items():
        side = sides.get((run["task"], run["host"])) if run["condition"] == "baseline" else None
        if isinstance(side, dict):
            found[run_id] = {key: side[key] for key in PAIRED_VERDICT_KEYS if key in side}
    return found


def _review_edited(evidence_root: Path, run_id: str, fresh: object, recorded: object) -> bool:
    """Whether the verdicts of the review.md of ``run_id`` can differ from those a summary recorded:
    the running tools read other bytes (sha256 ``fresh``) than the recorded ones, or the file was
    deleted. A review they did not read (for a run a later tool version judges invalid, say) gives no
    verdicts to compare."""
    if fresh is not None:
        return fresh != recorded
    return recorded is not None and not os.path.lexists(evidence_root / er.run_dir_name(run_id) / REVIEW_FILE)


def _verdict_differences(fresh: dict, recorded: dict, planned: dict[str, dict], run_ids: list[str]) -> list[str]:
    """Each of ``run_ids`` (Stage 1 runs whose review.md bytes changed since the summary was recorded)
    for which the re-computation reports other verdict-derived fields than the committed summary, with
    those fields. A review whose bytes are unchanged says what it said, so a difference there belongs
    to the tools and is not looked at."""
    now, then = _verdict_fields(fresh, planned), _verdict_fields(recorded, planned)
    named = []
    for run_id in run_ids:
        old, new = then.get(run_id), now.get(run_id, {})
        if old is None:
            continue
        keys = [key for key in old if key not in new or new[key] != old[key]]
        if keys:
            named.append(f"{run_id} ({', '.join(keys)})")
    return named


class Stage1Unverified(str):
    """Why a committed Stage 1 go could not be re-verified here although its sealed inputs are unchanged
    (the corpus is absent or unverified, or the running tools find Stage 1 incomplete), as opposed to
    evidence that contradicts it. run-prepare still refuses Stage 2; summarize --stage all reports
    the summary as incomplete instead of making Stage 2 runs invalid."""


class Stage1Changed(str):
    """Why the Stage 1 evidence here no longer matches an otherwise genuine committed go: a sealed Stage 1
    record, amendment or earlier attempt differs from the summary's inputs or is missing from this
    pilot directory, or a Stage 1 review.md now says something else. run-prepare refuses Stage 2 and
    names what to restore; summarize --stage all is incomplete, and no Stage 2 run becomes invalid."""


REVIEWS_FINAL = ("Stage 1 reviews are final once the Stage 1 summary is recorded: restore what those reviews said "
                 "then (a re-save or a wording change that keeps every verdict, the reviewer and the Review line does "
                 "no harm)")


def _stage1_matches(root: Path, campaign: Campaign, pilot_value: str | None, committed: dict,
                    notes: list[str] | None = None) -> str | None:
    """None when Stage 1, re-computed from the sealed evidence, is go with exactly the committed sealed
    inputs (records, amendments, earlier attempts), says the same (with the same tools, every field;
    with other tools, the disclosure and, for each review.md whose bytes changed, the fields its verdicts
    determine; review.md bytes themselves are not compared) and the committed summary was generated after every
    Stage 1 record was sealed or amended. A Stage1Changed reason when Stage 1 evidence here differs
    from the summary (named, with what to restore); a Stage1Unverified reason when the sealed inputs
    are unchanged but the re-computation is incomplete (the corpus is absent here, for example);
    otherwise why the committed summary does not hold. ``notes`` receives a note when the summary was
    recorded with other (Git-bound) tools."""
    try:
        recomputed = summarize(root, campaign.name, "1", pilot_value)
    except IntegrityError as exc:
        return (f"the campaign evidence has {len(exc.problems)} integrity problem(s), for example {exc.problems[0]} "
                f"(see python tools/workflow_eval.py summarize --campaign {campaign.name} --stage 1)")
    except PilotError as exc:
        return f"Stage 1 cannot be re-computed ({exc})"
    value = recomputed["decision"]["value"]
    planned = {run["id"]: run for run in campaign.plan()}
    sealed, reviews = _input_differences(recomputed, committed, planned)
    if sealed:
        return Stage1Changed(f"the sealed Stage 1 evidence here differs from the committed summary's inputs "
                             f"({_shown(sealed)}); use the pilot directory that holds the Stage 1 evidence as it was "
                             "recorded, and restore the exact bytes of any changed file (Stage 1 evidence is final once "
                             "its summary is recorded)")
    changed = f"review.md of {_shown(reviews, separator=', ')} changed since the summary was recorded"
    if value == "incomplete":
        reasons = recomputed["decision"].get("reasons") or []
        if reasons == [UNVERIFIED_REASON]:  # the environment, not the evidence (section 4.5 E)
            return Stage1Unverified("a re-computation of Stage 1 cannot verify the artifacts here (corpus absent or "
                                    "unverified), so the committed go is not re-verified")
        if reviews:
            return Stage1Changed(f"a re-computation of Stage 1 gives incomplete ({_shown(reasons, 2)}) after {changed}; "
                                 f"{REVIEWS_FINAL}")
        return Stage1Unverified(f"a re-computation of Stage 1 with these tools gives incomplete ({_shown(reasons, 2)}), "
                                "so the committed go is not re-verified")
    if value != "go":
        text = f"a re-computation of Stage 1 from the sealed evidence gives {value}, not go"
        return Stage1Changed(f"{text}, after {changed}; {REVIEWS_FINAL}") if reviews else text
    tools = _tooling_binding(root, campaign, committed, recomputed)
    if tools is not None and tools != SAME_TOOLS:
        return tools
    if tools is None:
        # Recorded with other tools, committed in the summary's history (section 1.10): the decision,
        # the sealed inputs and the disclosure of retries and failures (sealed facts) must still be
        # the re-computation, and so must what the summary reports of every review whose bytes changed
        # since; the other fields and the Markdown rendering belong to those tools.
        fresh, recorded = _disclosure(recomputed), _disclosure(committed)
        differing = sorted(key for key in set(fresh) | set(recorded) if fresh.get(key) != recorded.get(key))
        if differing:
            return (f"the committed Stage 1 summary misstates the runs' statuses, failures or earlier attempts "
                    f"({', '.join(differing)}) compared with a re-computation from the sealed evidence (a recorded "
                    "summary is written only by summarize --record)")
        now, then = _stage1_input_index(recomputed, planned), _stage1_input_index(committed, planned)
        evidence_root = _pilot_dir(pilot_value) / "evidence"
        edited = [run_id for run_id in reviews
                  if _review_edited(evidence_root, run_id, now[run_id].get("review"), then[run_id].get("review"))]
        verdicts = _verdict_differences(recomputed, committed, planned, edited)
        if verdicts:
            return Stage1Changed(f"a re-computation of Stage 1 differs from the committed summary in what the review "
                                 f"of {_shown(verdicts)} gives, after review.md of {_shown(edited, separator=', ')} "
                                 f"changed since the summary was recorded; {REVIEWS_FINAL}")
        if notes is not None:
            notes.append("the committed Stage 1 summary was recorded with other tools (versions committed in its "
                         "history); its decision, its sealed inputs, the failures and earlier attempts of its "
                         "skill runs and baselines, and what it reports of each review changed since were compared "
                         "with a re-computation, not its other fields or its Markdown rendering")
    else:
        # Recorded with these tools: every reported field must be the re-computation, and the
        # Markdown must be rendered from the JSON (section 4.7), so neither can hide a retry or a failure.
        fresh, recorded = _comparable(recomputed, planned), _comparable(committed, planned)
        differing = sorted(key for key in set(fresh) | set(recorded) if fresh.get(key) != recorded.get(key))
        if differing and reviews:
            return Stage1Changed(f"a re-computation of Stage 1 differs from the committed summary in "
                                 f"{', '.join(differing)} after {changed}; {REVIEWS_FINAL}")
        if differing:
            return (f"the committed Stage 1 summary differs from a re-computation from the sealed evidence in "
                    f"{', '.join(differing)} (a recorded summary is written only by summarize --record)")
        markdown = _show_at_head(root, f"{PILOT_REL}/{campaign.name}/stage1-summary.md")
        if markdown is None or markdown != render_markdown(committed).encode("utf-8"):
            return ("the committed stage1-summary.md is not the Markdown rendered from stage1-summary.json "
                    "(a recorded summary is written only by summarize --record)")
    generated = _parse_time(committed.get("generatedAt"))
    evidence_root = _pilot_dir(pilot_value) / "evidence"
    for run_id in sorted(_stage1_input_index(recomputed, planned)):
        try:
            record = _json_loads(er.confined_file(evidence_root / er.run_dir_name(run_id), RECORD_FILE).read_bytes(),
                                 RECORD_FILE)
        except ValueError:
            return f"the record of {run_id} cannot be read"
        times = [record.get("sealedAt")] + [item.get("at") for item in record.get("amendments") or []
                                            if isinstance(item, dict)]
        if any((_parse_time(item) or generated) > generated for item in times):
            return (f"the committed Stage 1 summary was generated before {run_id} was sealed or amended; "
                    "summarize Stage 1 again")
    return None


def _comparable(summary: dict, planned: dict[str, dict]) -> dict:
    """A summary without what legitimately differs between its recording and a later re-computation:
    generatedAt, tooling, the environment's verification notes, inputs of runs outside Stage 1, and
    the review.md hashes (a re-saved review that says the same gives the same fields)."""
    value = json.loads(er.canonical_json(summary))
    value.pop("generatedAt", None)
    value.pop("tooling", None)
    if isinstance(value.get("verification"), dict):
        value["verification"].pop("notes", None)
    inputs = value.get("inputs")
    if isinstance(inputs, dict) and isinstance(inputs.get("runs"), list):
        inputs["runs"] = [item for item in inputs["runs"] if isinstance(item, dict)
                          and (planned.get(item.get("id")) or {}).get("stage") == 1]
        for item in inputs["runs"]:
            item.pop("review", None)
            for attempt in item.get("earlierAttempts") or []:
                if isinstance(attempt, dict):
                    attempt.pop("review", None)
    return value


def _adjudication_check(root: Path, raw: bytes):
    """The full development-adjudication checker of tools/workflow_decisions.py (imported lazily)."""
    import workflow_decisions  # noqa: PLC0415 - a module-level import would be circular

    return workflow_decisions.check_adjudication(workflow_decisions.World(root, None), raw, ADJUDICATION_REL)


def adjudication_status(root: Path) -> str | None:
    """None when the committed development adjudication is complete, else why it is not. Only the
    committed file counts, and it is held to the same rules as python tools/workflow_eval.py check."""
    data = _show_at_head(root, ADJUDICATION_REL)
    if data is None:
        return f"{ADJUDICATION_REL} is not committed"
    try:
        result = _adjudication_check(Path(root), data)
    except Exception as exc:  # noqa: BLE001 - any failure of the checker refuses Stage 1
        return f"{ADJUDICATION_REL} cannot be checked ({exc})"
    if result.errors or result.todos:
        return f"the committed {ADJUDICATION_REL} has {result.errors} error(s) and {result.todos} to do"
    if not result.complete:
        return f'the committed {ADJUDICATION_REL} does not say "Review: complete"'
    return None


NOT_STATED = 'its session does not say "Prompt sent: no"'


def _seal_status(seal: object) -> object:
    session = seal.get("session") if isinstance(seal, dict) else None
    return session.get("status") if isinstance(session, dict) else None


def _attempt_chain(evidence: Path, record: dict) -> list[dict]:
    """Every seal of one attempt, oldest first: record.previous-1.json ... and then record.json."""
    chain: list[dict] = []
    amendments = record.get("amendments") if isinstance(record.get("amendments"), list) else []
    for index in range(1, len(amendments) + 1):
        try:
            value = _json_loads(er.confined_file(evidence, PREVIOUS_RECORD.format(n=index)).read_bytes(),
                                PREVIOUS_RECORD.format(n=index))
        except ValueError:
            value = {}
        chain.append(value if isinstance(value, dict) else {})
    return chain + [record]


def _prompt_sent(chain: list[dict], evidence: Path | None = None) -> str | None:
    """Why an attempt counts as having sent the prompt, so a retry may not replace it (any seal that
    timed out, failed after the prompt, says "Prompt sent: yes", or holds sealed evidence that the
    prompt reached the host; see _sent_evidence), or None when the last seal says "Prompt sent: no"
    and no seal contradicts it. ``evidence`` is the attempt's evidence directory."""
    for seal in chain:
        session = seal.get("session") if isinstance(seal.get("session"), dict) else {}
        failure = session.get("failure") if isinstance(session.get("failure"), dict) else {}
        if session.get("status") == "timed-out":
            return "it timed out"
        if failure.get("kind") in SENT_FAILURES:
            return f"it failed with {failure['kind']}"
        if session.get("promptSent") is True:
            return 'its session says "Prompt sent: yes"'
        why = _sent_evidence(seal, evidence)
        if why is not None:
            return why
    last = chain[-1].get("session") if isinstance(chain[-1].get("session"), dict) else {}
    return None if last.get("promptSent") is False else NOT_STATED


def _retry_refusal(chain: list[dict], evidence: Path | None, attempt: int, allowed: int) -> tuple[str, str] | None:
    """None when attempt ``attempt`` of a run (its seals ``chain``, oldest first) may be retried under a
    policy of ``allowed`` infrastructure retries; otherwise (kind, why): "completed", "sent" (why the
    prompt counts as sent) or "policy". run-prepare --retry, summarize and summarize --record share
    this one rule, so an open retry is named before a summary is recorded."""
    if any(_seal_status(seal) == "completed" for seal in chain):
        return "completed", "" if _seal_status(chain[-1]) == "completed" else " before it was amended"
    why = _prompt_sent(chain, evidence)
    if why is not None:
        return "sent", why
    if attempt > allowed:
        return "policy", ""
    return None


def _retry_command(run_id: str, name: str) -> str:
    return f'python tools/workflow_eval.py run-prepare {run_id} --campaign {name} --retry "<reason>"'


def _stage1_history(root: Path, campaign: Campaign) -> str | None:
    """A recorded Stage 1 summary is final: in the history reachable from HEAD, merges included,
    stage1-summary.json has exactly one content, and HEAD holds it."""
    rel = f"{PILOT_REL}/{campaign.name}/stage1-summary.json"
    versions = _path_versions(root, rel)
    if versions is None:
        return ("the Git history of stage1-summary.json cannot be read (a shallow or partial clone? git fetch "
                "--unshallow, or clone without --filter)")
    head = _git_text(root, "rev-parse", "--verify", "--quiet", f"HEAD:{rel}")
    if versions.first is None:
        return None if not head else ("stage1-summary.json is committed, but the Git history lists no commit that "
                                      "recorded it (a recorded summary is final)")
    blob, first = versions.first
    if versions.irregular:
        _oid, where, mode = versions.irregular[0]
        return (f"stage1-summary.json was committed as a non-file entry (mode {mode}) in {where[:12]} (a recorded "
                "summary is final)")
    if head and head != blob:
        return (f"the committed stage1-summary.json differs from the version first committed in {first[:12]} "
                "(a recorded summary is final)")
    if len(versions.versions) > 1:
        return (f"stage1-summary.json was committed with {len(versions.versions)} different contents "
                f"({', '.join(commit[:12] for commit in versions.versions.values())}), for example through a merge of "
                "two branches that both recorded it (a recorded summary is final; the owner records invalidation.md "
                "and a new campaign supersedes this one)")
    return None


STAGE1_FINAL = ("Stage 1 evidence is final once its summary is recorded: a retry or an amendment of a Stage 1 run "
                "belongs before summarize --stage 1 --record. Changing it now would stop the recorded summary from "
                "unlocking Stage 2 and would leave the all-stage summary incomplete; only the owner's invalidation.md "
                "and a new campaign could follow")


def _sealed_session_hint(evidence: Path) -> str:
    """A sentence for the refusals of a final Stage 1 run: session.md must keep its sealed bytes, and an
    edit made for the refused amendment must be undone (empty when session.md is unchanged)."""
    try:
        record = _json_loads(er.confined_file(evidence, RECORD_FILE).read_bytes(), RECORD_FILE)
        sealed = record["session"]["sha256"]
        now = er.sha256_bytes(er.confined_file(evidence, SESSION_FILE).read_bytes())
    except (ValueError, KeyError, TypeError):
        return ""
    if now == sealed:
        return ""
    return (f". session.md no longer has its sealed bytes (sha256 {str(sealed)[:12]}...): undo your edit exactly, or "
            "Stage 1 fails verification and Stage 2 stays blocked")


def _stage1_recorded(root: Path, campaign: Campaign) -> str | None:
    """Where the Stage 1 summary of ``campaign`` is recorded (in the working tree, or anywhere in the
    Git history reachable from HEAD), or None when it is not. A history Git cannot read counts as
    recorded, because then nobody can tell."""
    directory = _campaign_dir(root, campaign.name)
    for name in ("stage1-summary.json", "stage1-summary.md"):
        if os.path.lexists(directory / name):
            return f"{PILOT_REL}/{campaign.name}/{name} exists"
    for name in ("stage1-summary.json", "stage1-summary.md"):
        versions = _path_versions(root, f"{PILOT_REL}/{campaign.name}/{name}")
        if versions is None:
            return (f"the Git history of {PILOT_REL}/{campaign.name}/{name} cannot be read, so it may have been "
                    "recorded")
        if versions.committed:
            commit = next(iter(versions.versions.values()), None) or versions.removals[0]
            return f"{PILOT_REL}/{campaign.name}/{name} was committed in {commit[:12]}"
    return None


def _path_versions(root: Path, rel: str) -> er.PathHistory | None:
    """Every version ``rel`` had in the history reachable from HEAD (eval_records.path_history), or
    None when the history cannot say (a shallow or partial clone, whose missing commits or objects
    could hide an earlier version, or a history Git cannot read)."""
    if er.history_limit(root) is not None:
        return None
    if _head(root) is None:
        return er.PathHistory({}, [])
    try:
        return er.path_history(root, rel)
    except ValueError:
        return None


@contextlib.contextmanager
def _candidate_skill(root: Path, campaign: Campaign) -> Iterator[Path]:
    """The candidate's skill, read with git from its source commit (never from the checkout, whose
    skill may have changed since the capture), in a temporary directory that is removed afterwards.
    Its identity must equal candidate.skill."""
    commit = campaign.commit
    with tempfile.TemporaryDirectory(prefix="mlview-candidate-skill-") as temporary:
        directory = Path(temporary) / "mlview"
        try:
            listing = er._git(Path(root), "ls-tree", "-r", "-z", commit, "--", SKILL_REL + "/")
            modes = {}
            for entry in listing.split(b"\0"):
                if entry:
                    meta, _tab, raw = entry.partition(b"\t")
                    modes[raw.decode("utf-8")[len(SKILL_REL) + 1:]] = meta.split(b" ")[0].decode("ascii")
            for item in campaign.candidate["skill"]["files"]:
                rel = item["path"]
                if er._path_problem(rel) or modes.get(rel) not in er.REGULAR_MODES:
                    raise ValueError(f"{SKILL_REL}/{rel} is not a regular file at {commit[:12]}")
                target = directory.joinpath(*rel.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(er.git_show(root, commit, f"{SKILL_REL}/{rel}"))
                os.chmod(target, 0o755 if modes[rel] == "100755" else 0o644)
            if package_skill.bundle_identity(package_skill.canonical_files(directory)) != campaign.candidate["skill"]:
                raise ValueError(f"the skill files at {commit[:12]} differ from candidate.skill")
        except (ValueError, OSError, UnicodeDecodeError) as exc:
            raise PilotError(f"cannot read the candidate's skill from its source commit: {exc}") from None
        yield directory


def _workspace_name(directory: str, attempt: int) -> str:
    """Attempt 1 uses the run's directory name; a retry gets a fresh ``<run>.attempt-<n>`` workspace."""
    return directory if attempt == 1 else f"{directory}.attempt-{attempt}"


def _read_ledger(pilot_dir: Path) -> tuple[list[dict], list[str]]:
    """The entries of $MLVIEW_PILOT_DIR/preparations.jsonl and the problems of malformed lines."""
    path = pilot_dir / LEDGER_FILE
    if not os.path.lexists(path):
        return [], []
    if path.is_symlink() or not path.is_file():
        return [], [f"{LEDGER_FILE} is not a regular file"]
    entries, problems = [], []
    for number, line in enumerate(path.read_bytes().split(b"\n"), 1):
        if not line.strip():
            continue
        try:
            value = _json_loads(line, f"{LEDGER_FILE} line {number}")
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if (not isinstance(value, dict) or value.get("format") != LEDGER_FORMAT or not isinstance(value.get("run"), str)
                or not _is_int(value.get("attempt")) or value["attempt"] < 1):
            problems.append(f"{LEDGER_FILE} line {number}: not a preparation entry")
            continue
        entries.append(value)
    return entries, problems


def _attempts(entries: list[dict], run_id: str) -> list[dict]:
    return [entry for entry in entries if entry["run"] == run_id]


def _append_ledger(pilot_dir: Path, entry: dict) -> None:
    path = pilot_dir / LEDGER_FILE
    if path.is_symlink():
        raise PilotError(f"{LEDGER_FILE} is a symbolic link; refusing to write it")
    line = json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def run_prepare(root: Path, run_id: str, name: str, pilot_value: str | None, out: Callable[[str], None] = print,
                retry: str | None = None) -> int:
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
    entries, ledger_problems = _read_ledger(pilot_dir)
    if ledger_problems:
        raise PilotError(f"{LEDGER_FILE} in the pilot directory is damaged ({ledger_problems[0]}); it is append-only and "
                         "must never be edited")
    previous = _attempts(entries, run_id)
    attempt = len(previous) + 1
    workspaces, evidence_root = pilot_dir / "workspaces", pilot_dir / "evidence"
    evidence = evidence_root / directory
    earlier = evidence_root / f"{directory}.attempt-{len(previous)}"
    retry_command = _retry_command(run_id, name)
    allowed = campaign.retries
    retries_text = f"the run policy allows {allowed} infrastructure retr{'y' if allowed == 1 else 'ies'}"
    if retry is None and previous:
        raise PilotError(f"{run_id} was already prepared ({len(previous)} attempt(s), the last at "
                         f"{previous[-1].get('preparedAt')}); every attempt is prepared once and its evidence is kept. "
                         + (f'Only a sealed failed or blocked attempt whose session says "Prompt sent: no" may be '
                            f"retried ({retries_text}), with: {retry_command}" if len(previous) <= allowed
                            else f"{retries_text}, so attempt {len(previous)} is kept and counted"))
    if retry is not None:
        if not retry.strip():
            raise PilotError("--retry needs a reason")
        if MACHINE_PATH_RE.search(retry):
            raise PilotError("the retry reason contains a machine path; describe it without the path")
        if not previous:
            raise PilotError(f"{run_id} has not been prepared yet; run run-prepare without --retry")
        if run["stage"] == 1:  # skill runs and baselines of Stage 1, before any other advice about the attempt
            recorded = _stage1_recorded(root, campaign)
            if recorded is not None:
                raise PilotError(f"{run_id} cannot be retried: the Stage 1 summary is recorded ({recorded}). "
                                 f"{STAGE1_FINAL}")
        try:
            sealed = _json_loads(er.confined_file(evidence, RECORD_FILE).read_bytes(), RECORD_FILE)
        except ValueError:
            raise PilotError(f"attempt {len(previous)} of {run_id} is not sealed; seal it first (write its Status, "
                             f"Failure and Prompt sent in session.md, then run-finish)") from None
        sealed_problems = _verify_record(RunState(run, evidence=evidence, record=sealed), campaign)
        if sealed_problems:
            raise PilotError(f"attempt {len(previous)} of {run_id} does not verify against its sealed evidence "
                             f"({sealed_problems[0]}); a retry needs an intact sealed record")
        refusal = _retry_refusal(_attempt_chain(evidence, sealed), evidence, len(previous), allowed)
        if refusal is not None and refusal[0] == "completed":
            raise PilotError(f"attempt {len(previous)} of {run_id} completed{refusal[1]}; a completed run is never "
                             "retried")
        if refusal is not None and refusal[0] == "sent":
            hint = ("" if refusal[1] != NOT_STATED else ' If the prompt never reached the host, write "Prompt sent: no" '
                    f'in session.md and run: python tools/workflow_eval.py run-finish {run_id} --campaign {name} '
                    '--amend "<reason>".')
            raise PilotError(f"attempt {len(previous)} of {run_id} cannot be retried: {refusal[1]}; {RETRY_RULE}.{hint}")
        if refusal is not None:
            raise PilotError(f"{retries_text}; attempt {len(previous)} of {run_id} is kept and counted (a retry "
                             "beyond the policy would make the run invalid)")
        if os.path.lexists(workspaces / _workspace_name(directory, len(previous))):
            raise PilotError(f"the workspace of attempt {len(previous)} still exists; remove it before a retry")
        if os.path.lexists(earlier):
            raise PilotError(f"{earlier} already exists; earlier attempts are never overwritten")
    stage1_notes: list[str] = []
    if run["stage"] == 2:
        committed = _committed_stage1(root, campaign)
        reason = _stage1_go(committed, campaign) or _stage1_history(root, campaign)
        if reason is None:  # also in a pilot directory without Stage 1 evidence, which gives incomplete
            reason = _stage1_matches(root, campaign, pilot_value, committed, stage1_notes)
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
        detail = _verify_detail(report)
        raise PilotError(f"the corpus repository {repo['name']} failed verification ({detail}); run "
                         + _corpus_remedy(detail, repo["name"]))
    try:
        head_skill = package_skill.bundle_identity(package_skill.canonical_files(root / SKILL_REL))
    except (OSError, ValueError):
        head_skill = None
    workspace = workspaces / _workspace_name(directory, attempt)
    if os.path.lexists(workspace) or (retry is None and os.path.lexists(evidence)):
        raise PilotError(f"{workspace if os.path.lexists(workspace) else evidence} already exists; every run is prepared "
                         "once, in a fresh workspace")
    workspaces.mkdir(parents=True, exist_ok=True)
    evidence_root.mkdir(parents=True, exist_ok=True)
    if retry is not None:
        os.rename(evidence, earlier)  # the earlier attempt's evidence is kept, never deleted
    try:
        os.mkdir(evidence)
    except OSError:
        if retry is not None:
            os.rename(earlier, evidence)
        raise
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
            # The candidate's skill from its source commit, whatever this checkout's skill is now.
            with _candidate_skill(root, campaign) as source:
                install_skill.install(workspace, destination, source=source)
            identity = package_skill.bundle_identity(package_skill.canonical_files(workspace / destination))
            if identity != campaign.candidate["skill"]:
                raise PilotError("the installed skill differs from the candidate's skill identity")
            installed = destination
        prompt = campaign.files[campaign.prompt_rel(run["task"], run["condition"])]
        er.write_exclusive(evidence / PROMPT_FILE, prompt)
        er.write_exclusive(evidence / BEFORE_FILE, er.canonical_json(_workspace_hashes(workspace)))
        er.write_exclusive(evidence / SESSION_FILE, session_template(run_id, run["condition"], attempt - 1))
        _append_ledger(pilot_dir, {"format": LEDGER_FORMAT, "run": run_id, "attempt": attempt, "preparedAt": _now(),
                                   "workspace": workspace.name, "reason": _one_line(retry, 500) if retry else None})
    except BaseException as exc:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(evidence, ignore_errors=True)
        if retry is not None and not os.path.lexists(evidence):
            os.rename(earlier, evidence)
        if isinstance(exc, (ValueError, OSError)):
            raise PilotError(f"could not prepare {run_id}: {exc}") from None
        raise
    settings = campaign.host_policy(run["host"])
    lines = [
        f"Prepared {run_id} (campaign {name}, stage {run['stage']}, {run['condition']}"
        + (f", attempt {attempt}; attempt {attempt - 1} is kept in {earlier.name}" if retry is not None else "") + ").",
        f"  workspace: {workspace}  ({copied} pinned files" + (f"; skill at {installed}" if installed else "") + ")",
        f"  evidence:  {evidence}",
        f"  prompt:    {evidence / PROMPT_FILE} (sha256 {er.sha256_bytes(prompt)[:12]}...)",
        "Operator checklist (these paths are printed only; they are never recorded):",
        "  1. Open the workspace in a new VS Code window (File > New Window, then Open Folder).",
        f"  2. Start a fresh {run['host']} session; never continue an earlier conversation.",
        f'  3. Use the policy settings: model "{settings["model"]}", reasoning "{settings["reasoning"]}"'
        + (f', invocation "{settings["invocation"]}".' if run["condition"] == "skill" else
           "; no skill invocation (a baseline sends PROMPT.txt as a plain message)."),
        "  4. In the host's terminal, check that python3 --version reports 3.10 or newer "
        f"(policy: {_one_line((campaign.policy.get('environment') or {}).get('helperPython', 'see run-policy'), 120)}).",
    ]
    vsix = campaign.candidate.get("vsix") if isinstance(campaign.candidate.get("vsix"), dict) else {}
    lines.append(f"  5. Install the candidate VSIX once ({vsix.get('file', 'mlview-<version>.vsix')}, from the pilot directory) "
                 "if this VS Code profile does not have it.")
    if run["condition"] == "baseline":
        lines.append("  6. Baseline: confirm that no MLView skill, plugin or artifact is available to the host "
                     "(no .agents/skills/mlview, .claude/skills/mlview or MLView plugin). Send PROMPT.txt exactly, as a "
                     "plain message in a new chat; do not use the skill invocation ($mlview, the skill picker or /mlview).")
    else:
        lines.append(f"  6. Send the invocation, then PROMPT.txt exactly. The artifact must be published to "
                     f"{campaign.artifact_path} at the workspace root.")
    if run["host"] in HOST_FILES:
        lines.append(f"     {run['host']}: do not choose \"Yes, and don't ask again\"; it writes "
                     f"{', '.join(sorted(HOST_FILES[run['host']]))} into the workspace, which is reported with the run.")
    lines += [
        f"  7. Afterwards save transcript.txt{'' if run['condition'] == 'baseline' else ' and ui-log.md'} in the evidence "
        "directory, fill session.md, then run:",
        f"     python tools/workflow_eval.py run-finish {run_id} --campaign {name}",
    ]
    if run["condition"] == "skill" and head_skill != campaign.candidate["skill"]:
        stage1_notes.append(f"the skill in this checkout differs from the candidate's; the candidate's skill was "
                            f"installed from its source commit {campaign.commit[:12]}")
    lines += [f"Note: {note}." for note in stage1_notes]
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


def _expected_workspace(root: Path, campaign: Campaign, run: dict) -> dict[str, str]:
    """``{path: sha256}`` of the pinned project files run-prepare copied into the workspace (every path
    the sparse patterns cover), recomputed from the corpus instead of read from workspace-before.json."""
    task = campaign.task(run["task"])
    repo = campaign.repositories[task["repository"]]
    repo_path = _corpus_root(root) / repo["name"]
    try:
        tree = er.pinned_tree(repo_path, task["commit"])
        patterns = repo.get("sparse") or []
        return {rel: er.sha256_bytes(er.pinned_bytes(repo_path, task["commit"], rel, tree=tree))
                for rel in sorted(tree) if er.sparse_covers(patterns, rel)}
    except (ValueError, OSError) as exc:
        raise PilotError(f"cannot recompute the pinned workspace files from the corpus ({exc}); run-finish compares the "
                         "workspace with the pinned bytes, so the corpus must stay as run-prepare found it") from None


def _counted(run: dict, helper: ModuleType) -> Callable[[str], bool]:
    """Which workspace paths count as project files: every path in a baseline, and every path except
    the MLView-owned ones (artifact, drafts, installed skill) in a skill run."""
    if run["condition"] == "skill":
        return lambda rel: not helper.is_owned_path(rel)
    return lambda rel: True


def _diff_paths(before: dict, after: dict, counted: Callable[[str], bool]) -> dict[str, str]:
    """``{path: added|removed|modified}`` for the counted paths whose hashes differ."""
    found = {}
    for rel in sorted(set(before) | set(after)):
        if counted(rel) and before.get(rel) != after.get(rel):
            found[rel] = "added" if rel not in before else "removed" if rel not in after else "modified"
    return found


def _finish_problems(evidence: Path, finish: object, status: str, session_sha: str) -> list[str]:
    """Why the files an interrupted run-finish left behind cannot be sealed as they are."""
    if not isinstance(finish, dict) or finish.get("format") != FINISH_FORMAT or not isinstance(finish.get("files"), dict):
        return [f"{FINISH_STATE} is not a run-finish state file"]
    problems = []
    if finish.get("status") != status or finish.get("session") != session_sha:
        problems.append(f"session.md changed after run-finish removed the workspace (the status was then "
                        f"{finish.get('status')}); restore session.md, seal the run, then change it with --amend")
    listed = finish["files"]
    for rel, digest in sorted(listed.items()):
        try:
            data = er.confined_file(evidence, rel).read_bytes()
        except ValueError as exc:
            problems.append(f"{rel}: {exc}")
            continue
        if er.sha256_bytes(data) != digest:
            problems.append(f"{rel} changed after run-finish wrote it")
    extra = [name for name in (ARTIFACT_FILE, PARTIAL_FILE) if os.path.lexists(evidence / name) and name not in listed]
    if (evidence / CHANGES_DIR).is_dir():
        extra += sorted(f"{CHANGES_DIR}/{path.relative_to(evidence / CHANGES_DIR).as_posix()}"
                        for path in (evidence / CHANGES_DIR).rglob("*") if not path.is_dir()
                        and f"{CHANGES_DIR}/{path.relative_to(evidence / CHANGES_DIR).as_posix()}" not in listed)
    problems.extend(f"{rel} was not written by run-finish" for rel in extra)
    return problems


def _unsent_contradiction(workspace: Path, evidence: Path, campaign: Campaign) -> str | None:
    """What in the workspace shows that the prompt reached the host: the published artifact, or a
    draft or artifact the skill wrote (anything under .mlview/, a *.draft.json or a *.mlview.json;
    see _outputs_added)."""
    if (workspace / campaign.artifact_path).is_file():
        return f"{campaign.artifact_path} was published in the workspace"
    prepared = _json_loads(er.confined_file(evidence, BEFORE_FILE).read_bytes(), BEFORE_FILE)
    outputs = _outputs_added(prepared if isinstance(prepared, dict) else {}, _workspace_hashes(workspace))
    return f"the skill wrote {outputs[0]} in the workspace" if outputs else None


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
        if MACHINE_PATH_RE.search(amend):
            raise PilotError("the amendment reason contains a machine path; describe it without the path")
        if not record_path.is_file():
            raise PilotError(f"{run_id} is not sealed yet; run run-finish without --amend")
        if run["stage"] == 1:
            recorded = _stage1_recorded(root, campaign)
            if recorded is not None:
                raise PilotError(f"{run_id} cannot be amended: the Stage 1 summary is recorded ({recorded}). "
                                 f"{STAGE1_FINAL}{_sealed_session_hint(evidence)}")
        session, session_raw = _session_or_fail(evidence, run_id, campaign.helper, out)
        return _amend(campaign, run, evidence, session, session_raw, amend.strip(), out)
    if os.path.lexists(record_path):
        recorded = _stage1_recorded(root, campaign) if run["stage"] == 1 else None
        if recorded is not None:
            raise PilotError(f"{run_id} is already sealed, and the Stage 1 summary is recorded ({recorded}). "
                             f"{STAGE1_FINAL}{_sealed_session_hint(evidence)}")
        raise PilotError(f"{run_id} is already sealed; to change the session facts run: python tools/workflow_eval.py "
                         f'run-finish {run_id} --campaign {name} --amend "<reason>"')
    if any(PREVIOUS_RECORD_RE.fullmatch(path.name) for path in evidence.iterdir()):
        raise PilotError("record.json is missing but record.previous-*.json exist: the sealed record was deleted. Restore "
                         "record.json and change the session with --amend")
    entries, ledger_problems = _read_ledger(pilot_dir)
    attempts = _attempts(entries, run_id)
    if ledger_problems or not attempts:
        raise PilotError(f"{LEDGER_FILE} in the pilot directory has no preparation of {run_id}"
                         + (f" ({ledger_problems[0]})" if ledger_problems else "")
                         + "; runs are prepared with run-prepare, which records every attempt")
    session, session_raw = _session_or_fail(evidence, run_id, campaign.helper, out)
    if session.block["priorAttempts"] != len(attempts) - 1:
        raise PilotError(f"session.md says Prior attempts: {session.block['priorAttempts']}, but {LEDGER_FILE} records "
                         f"{len(attempts) - 1} earlier attempt(s); write Prior attempts: {len(attempts) - 1}")
    status = session.block["status"]
    session_sha = er.sha256_bytes(session_raw)
    workspace = pilot_dir / "workspaces" / _workspace_name(directory, len(attempts))
    skill = run["condition"] == "skill"
    counted = _counted(run, campaign.helper)
    host_allowed = HOST_FILES.get(run["host"], frozenset())
    if workspace.is_symlink():
        raise PilotError(f"{workspace} is a symbolic link; refusing to read or remove it")
    if workspace.is_dir():
        if session.block["promptSent"] is False:  # checked before anything is written or removed
            what = _unsent_contradiction(workspace, evidence, campaign)
            if what:
                raise PilotError(f'{what}, so the prompt reached the host; write "Prompt sent: yes" in session.md and '
                                 "run run-finish again (a failure after the prompt was sent is kept and counted)")
        written: dict[str, str] = {}
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
                written[target] = er.sha256_bytes(data)
        expected = _expected_workspace(root, campaign, run)
        before = _json_loads(er.confined_file(evidence, BEFORE_FILE).read_bytes(), BEFORE_FILE)
        if not isinstance(before, dict):
            raise PilotError(f"{BEFORE_FILE} is not a JSON object")
        mismatches = sorted(_diff_paths(expected, before, counted))
        after = _workspace_hashes(workspace)
        changes: list[dict] = []
        host_files: list[dict] = []
        for rel, change in _diff_paths(expected, after, counted).items():
            entry: dict[str, Any] = {"path": rel, "change": change, "file": None, "sha256": None}
            if change != "removed":
                path = workspace / rel
                if path.is_file() and not path.is_symlink():
                    data = path.read_bytes()
                    copy = f"{CHANGES_DIR}/{rel}"
                    _write_or_same(evidence / copy, data)
                    entry.update(file=copy, sha256=er.sha256_bytes(data))
                    written[copy] = entry["sha256"]
                else:
                    entry["sha256"] = after[rel]
            (host_files if rel in host_allowed and change != "removed" else changes).append(entry)
        with _candidate_skill(root, campaign) as source:  # compared with the candidate's skill, not the checkout's
            doctor, _ok = install_skill.doctor(workspace, source=source)
        for rel, data in ((AFTER_FILE, er.canonical_json(after)), (DOCTOR_FILE, er.canonical_json(doctor))):
            _write_or_same(evidence / rel, data)
            written[rel] = er.sha256_bytes(data)
        # Verify every copy against the workspace before removing it.
        if skill and (evidence / ARTIFACT_FILE).is_file() and status == "completed":
            if (evidence / ARTIFACT_FILE).read_bytes() != (workspace / campaign.artifact_path).read_bytes():
                raise PilotError("the artifact copy differs from the workspace artifact")
        for entry in changes + host_files:
            if entry["file"] and (evidence / entry["file"]).read_bytes() != (workspace / entry["path"]).read_bytes():
                raise PilotError(f"the copy of {entry['path']} differs from the workspace")
        summary = {"changedProjectFiles": changes, "hostFiles": host_files, "beforeMismatches": mismatches}
        changes_data = er.canonical_json(summary)
        _write_or_same(evidence / CHANGES_FILE, changes_data)
        written[CHANGES_FILE] = er.sha256_bytes(changes_data)
        finish = {"format": FINISH_FORMAT, "run": run_id, "status": status, "session": session_sha,
                  "files": dict(sorted(written.items()))}
        _write_or_same(evidence / FINISH_STATE, er.canonical_json(finish))
    else:
        # An earlier run-finish removed the workspace but did not seal: only its recorded state is sealed.
        if not os.path.lexists(evidence / FINISH_STATE):
            raise PilotError(f"{workspace} does not exist and run-finish never recorded it ({FINISH_STATE} is missing); "
                             "the workspace was removed before the run was sealed")
        finish = _json_loads(er.confined_file(evidence, FINISH_STATE).read_bytes(), FINISH_STATE)
        problems = _finish_problems(evidence, finish, status, session_sha)
        if problems:
            raise PilotError("cannot seal the files an earlier run-finish left: " + "; ".join(problems))
        summary = _json_loads(er.confined_file(evidence, CHANGES_FILE).read_bytes(), CHANGES_FILE)
        changes, host_files = summary["changedProjectFiles"], summary["hostFiles"]
        mismatches = summary["beforeMismatches"]
    artifact_entry = _file_entry(evidence, ARTIFACT_FILE) if skill and status == "completed" else None
    partial_entry = (_file_entry(evidence, PARTIAL_FILE)
                     if skill and status != "completed" and (evidence / PARTIAL_FILE).is_file() else None)
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
        "workspace": {"name": workspace.name, "removed": removed,
                      "before": {k: v for k, v in _file_entry(evidence, BEFORE_FILE).items() if k != "bytes"},
                      "after": {k: v for k, v in _file_entry(evidence, AFTER_FILE).items() if k != "bytes"},
                      "changes": {k: v for k, v in _file_entry(evidence, CHANGES_FILE).items() if k != "bytes"},
                      "changedProjectFiles": changes, "hostFiles": host_files, "beforeMismatches": mismatches,
                      "isolation": _isolation_findings(pilot_dir, root)},
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
        f"{len(changes)} changed project file(s)"
        + (f", {len(host_files)} host file(s)" if host_files else "")
        + (f", {len(mismatches)} path(s) differ between {BEFORE_FILE} and the pinned files" if mismatches else "")
        + f"; workspace {'removed' if removed else 'NOT removed'}.")
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
    sealed_transcript = previous["evidence"].get("transcript")
    if sealed_transcript is not None and record["evidence"]["transcript"] != sealed_transcript:
        raise PilotError(f"the transcript sealed earlier ({sealed_transcript.get('file')}, sha256 "
                         f"{str(sealed_transcript.get('sha256'))[:12]}...) is evidence and is kept: leave the file "
                         f'unchanged and name it in session.md ("Transcript: {sealed_transcript.get("file")}")')
    if session.block["promptSent"] is False:
        for seal in _attempt_chain(evidence, previous) + [record]:
            why = _sent_evidence(seal, evidence)
            if why is not None:
                raise PilotError(f'this attempt cannot say "Prompt sent: no": {why}, so the prompt reached the host; '
                                 'write "Prompt sent: yes" (a failure after the prompt was sent is kept and counted)')
    number = len(previous.get("amendments") or []) + 1
    _write_or_same(evidence / PREVIOUS_RECORD.format(n=number), previous_bytes)
    record["amendments"] = list(previous.get("amendments") or []) + [
        {"at": _now(), "reason": _one_line(reason, 500), "previous": er.sha256_bytes(previous_bytes)}]
    record["tooling"] = _tooling()
    data = er.canonical_json(record)
    er.write_atomic(record_path, data)
    out(f"Amended {run['id']} (amendment {number}); the previous record is kept as {PREVIOUS_RECORD.format(n=number)} "
        f"(sha256 {er.sha256_bytes(previous_bytes)[:12]}...).")
    if status != "completed" and os.path.lexists(evidence / REVIEW_FILE):
        out(f"Next: remove {REVIEW_FILE} (a {status} run is not reviewed; summarize counts its review as a problem).")
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
             '> Fill Reviewer and Date, replace every "pending", then check: python tools/workflow_eval.py check <this file>']
    if run.get("stage") == 1:
        lines.append("> Stage 1 reviews are final once the Stage 1 summary is recorded: change no verdict afterwards, "
                     "and keep a copy of the evidence directory (it is outside Git).")
    lines.append(f"Run: {run_id}")
    if baseline:
        lines.append(f"Transcript: {record['evidence']['transcript']['sha256']}")
    else:
        lines.append(f"Artifact: {record['evidence']['artifact']['sha256']}")
    lines += [f"Reference: {record['referenceRevision']}", "Reviewer:", "Date:", "Transcribed by:", "", "## Claims"]
    non_defects = [f"> {item['id']}: {_one_line(_frozen_text(item, 'text', 'wording', 'claim'))}" for item in reference["nonDefects"]]
    if baseline:
        lines += ['> Add one line per claim in the answer: "response:LINE-END: <verdict>" (lines of the transcript, for example',
                  '> response:12-14: supported). Verdicts: supported | qualified | unsupported | no-claim. Add " -- <reason>"',
                  '> (or " — <reason>") to anything except supported/no-claim. At least one line. Several claims on the same '
                  'lines: "response:12-14#2: ...".',
                  "> Frozen non-defects (for judging false accusations):"] + non_defects
    else:
        lines += ['> Verdicts: supported | qualified | unsupported | no-claim. Add " -- <reason>" (or " — <reason>") to '
                  'anything except supported/no-claim.',
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
                  f"> clear | partial | missing; task: useful | partly | not-useful (reported, not gated; {README_REVIEW})"]
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
        except ValueError as exc:
            detail = str(exc)
            hint = f" {detail}" if "separator" in detail or "Put a space" in detail else ""
            add(er.ERROR, item.line, where, f'"{item.key}: {_one_line(text, 60)}" is not a verdict. Write one of: '
                                            f'{", ".join(sorted(vocab))}.{hint}')
            return None
        if verdict in reason_for and not reason:
            add(er.ERROR, item.line, where, f'{item.key} is {verdict}; add {REASON_HINT}.')
        needs = pointers == "required" and verdict not in ("missing", "not-stated", "missed")
        if pointers == "none" and cited:
            add(er.ERROR, item.line, where, f'{item.key}: claim lines take no pointers; put notes after " -- ".')
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
        ranges: dict[tuple[int, int, int], str] = {}
        for item in claims.lines:
            match = RESPONSE_RE.fullmatch(item.key)
            if not match:
                add(er.ERROR, item.line, "Claims", f'"{item.key}" is not a transcript range; write "response:LINE-END: <verdict>".')
                continue
            if LEADING_ZERO_RE.search(item.key):
                add(er.ERROR, item.line, "Claims", f'"{item.key}": write line numbers and #2, #3, ... without leading zeros.')
                continue
            if match.group("n") and int(match.group("n")) < 2:
                add(er.ERROR, item.line, "Claims", f'"{item.key}": split lines start at #2.')
                continue
            start = int(match.group("line"))
            normal = (start, int(match.group("end") or start), int(match.group("n") or 1))
            if normal in ranges:
                add(er.ERROR, item.line, "Claims", f'"{item.key}" repeats "{ranges[normal]}"; give each claim its own line '
                                                   "number or split number.")
                continue
            ranges[normal] = item.key
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
        split_seen: set[str] = set()
        for item in claims.lines:
            key = item.key
            split = SPLIT_RE.fullmatch(key)
            base = split.group("base") if split else key
            if base not in elements:
                add(er.ERROR, item.line, "Claims", f'"{key}" does not name an element of the artifact (node:<id>, edge:<id>, '
                                                   "finding:<id>, coverage or configuration).")
                continue
            if split and split.group("n").startswith("0"):
                add(er.ERROR, item.line, "Claims", f'"{key}": write #2, #3, ... without leading zeros.')
                continue
            if split and int(split.group("n")) < 2:
                add(er.ERROR, item.line, "Claims", f'"{key}": split lines start at #2.')
                continue
            if split and key in split_seen:
                add(er.ERROR, item.line, "Claims", f'"{key}" appears twice; give each split claim its own number.')
                continue
            if split:
                split_seen.add(key)
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
        status = sealed["session"]["status"]
        if status != "completed":  # for example after an amendment to failed or timed-out
            return problems + [er.Problem(display, 1, er.ERROR, "header",
                                          f"a {status} run is not reviewed (its record.json says Status: {status}); "
                                          "remove review.md.")]
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
    earlier_completed: list[int] = field(default_factory=list)  # attempts before this one that completed
    earlier_sent: list[tuple[int, str]] = field(default_factory=list)  # (attempt, why) of attempts that sent the prompt
    earlier: list[dict] = field(default_factory=list)  # every kept earlier attempt, for runs[], failures and inputs

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
    prior = (session or {}).get("priorAttempts") if isinstance(session, dict) else None
    workspace_name = _workspace_name(er.run_dir_name(run["id"]), prior + 1 if _is_int(prior) and prior >= 0 else 1)
    if not isinstance(workspace, dict) or workspace.get("name") != workspace_name:
        problems.append("record.json workspace: must name the run's workspace")
    else:
        files = {key: _check_entry(evidence, workspace.get(key), f"workspace.{key}", problems, with_bytes=False)
                 for key in ("before", "after", "changes")}
        lists = {}
        for key in ("changedProjectFiles", "hostFiles", "beforeMismatches"):
            value = workspace.get(key)
            if not isinstance(value, list):
                problems.append(f"record.json workspace.{key}: must be a list")
                continue
            lists[key] = value
        for key in ("changedProjectFiles", "hostFiles"):
            for index, entry in enumerate(lists.get(key, [])):
                if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) \
                        or entry.get("change") not in ("added", "removed", "modified"):
                    problems.append(f"workspace.{key}[{index}]: malformed")
                elif entry.get("file") is not None:
                    _check_entry(evidence, {"file": entry["file"], "sha256": entry.get("sha256")},
                                 f"workspace.{key}[{index}]", problems, with_bytes=False)
        if not all(isinstance(item, str) for item in lists.get("beforeMismatches", [])):
            problems.append("record.json workspace.beforeMismatches: must list paths")
        if not isinstance(workspace.get("isolation"), list):
            problems.append("record.json workspace.isolation: must be a list")
        if len(lists) == 3 and all(value is not None for value in files.values()) and not problems:
            problems.extend(_workspace_consistency(run, campaign, lists, files))
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
            data = _check_entry(evidence, {"file": PREVIOUS_RECORD.format(n=index), "sha256": amendment["previous"]},
                                f"amendments[{index - 1}]", problems, with_bytes=False)
            try:
                previous = _json_loads(data, PREVIOUS_RECORD.format(n=index)) if data is not None else None
            except ValueError:
                previous = None
            if data is not None and (not isinstance(previous, dict) or previous.get("sealedAt") != record.get("sealedAt")
                                     or not isinstance(previous.get("amendments"), list)
                                     or len(previous["amendments"]) != index - 1):
                problems.append(f"amendments[{index - 1}]: {PREVIOUS_RECORD.format(n=index)} is not the record before "
                                f"amendment {index} (same sealedAt, {index - 1} earlier amendment(s))")
        expected_previous = {PREVIOUS_RECORD.format(n=index) for index in range(1, len(amendments) + 1)}
        for path in sorted(evidence.iterdir()):
            if path.name.startswith("record.previous-") and path.name not in expected_previous:
                problems.append(f"{path.name} is not referenced by record.json amendments (a sealed record was replaced)")
    if _parse_time(record.get("sealedAt")) is None:
        problems.append("record.json sealedAt: must be an RFC 3339 time")
    if not isinstance(record.get("tooling"), dict):
        problems.append("record.json tooling: must be an object")
    return problems


def _workspace_consistency(run: dict, campaign: Campaign, lists: dict[str, list], files: dict[str, bytes]) -> list[str]:
    """The sealed workspace lists must equal workspace-changes.json and agree with the hashed
    workspace-before.json and workspace-after.json (the rule run-finish applies)."""
    problems = []
    try:
        summary = _json_loads(files["changes"], CHANGES_FILE)
        before = _json_loads(files["before"], BEFORE_FILE)
        after = _json_loads(files["after"], AFTER_FILE)
    except ValueError as exc:
        return [str(exc)]
    if summary != lists:
        problems.append(f"record.json workspace lists differ from {CHANGES_FILE}")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return problems + [f"{BEFORE_FILE} and {AFTER_FILE} must be JSON objects"]
    counted = _counted(run, campaign.helper)
    diff = _diff_paths(before, after, counted)
    entries = {entry["path"]: entry for key in ("changedProjectFiles", "hostFiles") for entry in lists[key]}
    mismatches = set(lists["beforeMismatches"])
    unexplained = sorted(set(diff) - set(entries) - mismatches)
    if unexplained:
        problems.append(f"{len(unexplained)} changed workspace path(s) are not in the record ({', '.join(unexplained[:3])})")
    unfounded = sorted(set(entries) - set(diff) - mismatches)
    if unfounded:
        problems.append(f"{len(unfounded)} recorded change(s) do not appear in the workspace hashes ({', '.join(unfounded[:3])})")
    for rel, entry in entries.items():
        if (rel in after) if entry["change"] == "removed" else (entry.get("sha256") != after.get(rel)):
            problems.append(f"the recorded change of {rel} differs from {AFTER_FILE}")
    allowed = HOST_FILES.get(run["host"], frozenset())
    for entry in lists["hostFiles"]:
        if entry["path"] not in allowed:
            problems.append(f"{entry['path']} is not a host file of {run['host']}")
    return problems


def _protocol(state: RunState, campaign: Campaign, stage1: dict | None, stage1_problem: str | None = None) -> None:
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
        why = stage1_problem or _stage1_go(stage1, campaign)
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
    for number in state.earlier_completed:
        reasons.append(f"attempt {number} of this run completed, so the run was retried after a completed session")
    for number, why in state.earlier_sent:
        reasons.append(f"attempt {number} of this run sent the prompt ({why}); {RETRY_RULE}")
    prior = session.get("priorAttempts")
    if _is_int(prior) and prior > campaign.retries:
        reasons.append(f"prior attempts {prior} exceed the infrastructure retries ({campaign.retries})")
    settings = campaign.host_policy(run["host"])
    # A baseline sends the prompt as a plain message, so only the skill runs are held to the invocation.
    for key in ("model", "reasoning") + (("invocation",) if run["condition"] == "skill" else ()):
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
    owned = [entry["path"] for entry in changes if run["condition"] == "baseline" and helper.is_owned_path(entry["path"])]
    if owned:
        reasons.append(f"MLView-owned file(s) in a baseline workspace ({', '.join(owned[:3])})")
    mismatches = record["workspace"].get("beforeMismatches") or []
    if mismatches:
        reasons.append(f"{BEFORE_FILE} differs from the pinned files for {len(mismatches)} path(s) "
                       f"({', '.join(mismatches[:3])})")
    for entry in record["workspace"].get("hostFiles") or []:
        warnings.append(f"the host wrote {entry['path']} into the workspace (a host setting; reported, not invalidating)")
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
                             f"({_corpus_remedy(_verify_detail(report), repo['name'])})")
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


def _early_stop(runs: list[dict], targets: list[dict], retriable: Iterable[str] = ()) -> list[str]:
    """Targets that can no longer be met while the decision is incomplete. A run in ``retriable`` (a
    failure the run policy still lets the operator retry) is open: its retry could still count."""
    indicators = []
    retriable = set(retriable)
    by_key = {target["key"]: target for target in targets}
    for run in runs:
        if run["status"] in ("failed", "timed-out", "blocked", "invalid") or (run["status"] == "completed" and run["SV"] == 0
                                                                              and run["E"] is not None):
            detail = (run["failure"] or {}).get("kind") if run["status"] in ("failed", "timed-out", "blocked") else None
            if run["status"] == "invalid":
                detail = "; ".join(run["invalidReasons"][:2])
            elif run["status"] == "completed":
                detail = "not structurally valid: " + ", ".join(run["errorCodes"] or ["unpublished"])
            indicators.append(f"T1: {run['id']} {run['status']}" + (f" ({detail})" if detail else "")
                              + ("; may still be retried" if run["id"] in retriable else ""))
    anchors = by_key["exactAnchors"]
    if anchors["threshold"] >= 1 and anchors["numerator"] < anchors["denominator"]:
        indicators.append(f"T2: {anchors['denominator'] - anchors['numerator']} inexact anchor(s) already recorded")

    def open_total(total_key: str, host: str | None = None) -> int:
        return sum(r[total_key] for r in runs if not r["reviewed"] and (host is None or r["host"] == host) and (
            r["status"] == "pending" or r["id"] in retriable
            or (r["status"] == "completed" and r["reviewStatus"] != "not-applicable")))

    for key in ("essentialFactRecall", "knownUnresolvedQualified"):
        target = by_key[key]
        total_key = "ESS" if key == "essentialFactRecall" else "UNK"
        reachable = target["numerator"] + open_total(total_key)
        if target["denominator"] and not _met(reachable, target["denominator"], target["threshold"], ">="):
            indicators.append(f"{target['id']}: at most {reachable}/{target['denominator']} can still be reached")
        for host, item in sorted((target.get("perHost") or {}).items()):  # per-host targets (T4 only)
            reachable = item["numerator"] + open_total(total_key, host)
            if item["denominator"] and not _met(reachable, item["denominator"], target["threshold"], ">="):
                indicators.append(f"{target['id']} ({host}): at most {reachable}/{item['denominator']} can still be "
                                  "reached")
    fa = by_key["highSeverityFalseAccusations"]
    if fa["numerator"] > fa["threshold"]:
        indicators.append(f"T6: {fa['numerator']} high-severity false accusation(s) already recorded")
    return indicators


def _missed_reason(target: dict) -> str:
    """The stop reason of a missed >= target: the pooled fraction, and with per-host targets each host
    that misses it (a pooled fraction that meets the threshold is said to meet it)."""
    shown = f"{target['numerator']}/{target['denominator']}"
    needs = f"needs >= {target['threshold']:g}"
    failing = [f"{host} {item['numerator']}/{item['denominator']}"
               for host, item in sorted((target.get("perHost") or {}).items()) if not item["met"]]
    head = f"{target['id']} {target['key']}: "
    if not failing:
        return head + f"{shown} ({needs})"
    if _met(target["numerator"], target["denominator"], target["threshold"], ">="):
        return head + f"pooled {shown} meets it; within host {', '.join(failing)} ({needs})"
    return head + f"pooled {shown} ({needs}); within host {', '.join(failing)}"


def _pct(numerator: int, denominator: int) -> str:
    """The percentage floored to a tenth, so a value below a threshold never displays as the threshold."""
    tenths = (1000 * numerator) // denominator
    return f"{tenths // 10}.{tenths % 10}%"


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
        "reviewProblemCount": len(state.review_problems),
        "promptInTranscript": state.prompt_in_transcript, "warnings": list(state.warnings),
        "amendments": [{"at": a["at"], "reason": a["reason"]} for a in record.get("amendments") or []],
        "priorAttempts": len(state.earlier),
        "attempts": [{key: item[key] for key in ("attempt", "status", "failure", "promptSent", "sentBecause", "statuses")}
                     for item in state.earlier],
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
            "note": f"Reported, not gated ({README_REVIEW})."}


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


def _attempt_problems(pilot_dir: Path, planned: dict[str, dict], states: dict[str, RunState],
                      earlier_dirs: dict[str, dict[int, Path]], campaign: Campaign) -> list[str]:
    """Every prepared attempt (preparations.jsonl) must have its evidence, and all evidence an entry.
    Each kept earlier attempt is verified like a current record and described in ``state.earlier``."""
    entries, problems = _read_ledger(pilot_dir)
    by_run: dict[str, list[int]] = {}
    for entry in entries:
        if entry["run"] not in planned:
            problems.append(f"{LEDGER_FILE}: {entry['run']} is not a planned run")
            continue
        by_run.setdefault(entry["run"], []).append(entry["attempt"])
    for run_id, state in states.items():
        attempts = by_run.get(run_id, [])
        earlier = earlier_dirs.get(run_id, {})
        directory = er.run_dir_name(run_id)
        if not attempts:
            if state.evidence is not None or earlier:
                problems.append(f"{run_id}: evidence exists but {LEDGER_FILE} records no preparation of it")
            continue
        count = len(attempts)
        if sorted(attempts) != list(range(1, count + 1)):
            problems.append(f"{run_id}: {LEDGER_FILE} numbers its attempts {sorted(attempts)}, not 1 to {count}")
        if state.evidence is None:
            problems.append(f"{run_id}: {LEDGER_FILE} records {count} preparation(s) but evidence/{directory} is missing "
                            "(run evidence is never deleted)")
        if sorted(earlier) != list(range(1, count)):
            problems.append(f"{run_id}: the kept earlier attempts {sorted(earlier) or 'none'} differ from the {count - 1} "
                            f"earlier attempt(s) in {LEDGER_FILE}")
        session = (state.record or {}).get("session") if isinstance(state.record, dict) else None
        if isinstance(session, dict) and session.get("priorAttempts") != count - 1:
            problems.append(f"{run_id}: the session says {session.get('priorAttempts')} prior attempt(s), {LEDGER_FILE} "
                            f"records {count - 1}")
        for number, path in sorted(earlier.items()):
            try:
                raw = er.confined_file(path, RECORD_FILE).read_bytes()
                old = _json_loads(raw, RECORD_FILE)
            except ValueError:
                problems.append(f"{run_id}: attempt {number} ({path.name}) was retried without being sealed")
                continue
            if not isinstance(old, dict) or old.get("id") != run_id or _seal_status(old) not in STATUSES:
                problems.append(f"{run_id}: {path.name}/record.json is not a sealed record of this run")
                continue
            # An earlier attempt is held to the same integrity rules as a current record.
            verified = _verify_record(RunState(planned[run_id], evidence=path, record=old), campaign)
            problems.extend(f"{run_id}: {path.name}: {item}" for item in verified)
            old_session = old.get("session") if isinstance(old.get("session"), dict) else {}
            if old_session.get("priorAttempts") != number - 1:
                problems.append(f"{run_id}: {path.name} says {old_session.get('priorAttempts')} prior attempt(s), not "
                                f"{number - 1}")
            if verified:
                continue
            chain = _attempt_chain(path, old)
            why = None
            if any(_seal_status(seal) == "completed" for seal in chain):
                state.earlier_completed.append(number)
                # Recorded so the summary never says "prompt never sent" beside an attempt that completed.
                why = "it completed" + ("" if _seal_status(chain[-1]) == "completed" else " before it was amended")
            else:
                why = _prompt_sent(chain, path)
                if why is not None:
                    state.earlier_sent.append((number, why))
            review = None
            if os.path.lexists(path / REVIEW_FILE):
                try:
                    review = er.sha256_bytes(er.confined_file(path, REVIEW_FILE).read_bytes())
                except ValueError as exc:
                    problems.append(f"{run_id}: {path.name}: {exc}")
                    continue
            state.earlier.append({
                "attempt": number, "status": old_session.get("status"), "failure": old_session.get("failure"),
                "promptSent": old_session.get("promptSent"), "sentBecause": why,
                "statuses": [_seal_status(seal) for seal in chain],
                "record": er.sha256_bytes(raw), "review": review,
                "amendments": [a["previous"] for a in old.get("amendments") or []]})
    return problems


def _open_retries(root: Path, campaign: Campaign, states: dict[str, RunState], run_ids: list[str]) -> list[dict]:
    """Each sealed attempt of ``run_ids`` that run-prepare --retry would still accept under the run
    policy (the rule of _retry_refusal; a Stage 1 run only while the Stage 1 summary is not recorded),
    with its retry command, so the operator retries before a recorded summary makes the failure final."""
    found = []
    stage1_recorded: list[str | None] = []
    for run_id in run_ids:
        state = states[run_id]
        if state.record is None or state.evidence is None or _seal_status(state.record) not in ("failed", "blocked"):
            continue
        attempt = len(state.earlier) + 1
        if _retry_refusal(_attempt_chain(state.evidence, state.record), state.evidence, attempt, campaign.retries):
            continue
        if state.run["stage"] == 1:
            if not stage1_recorded:
                stage1_recorded.append(_stage1_recorded(root, campaign))
            if stage1_recorded[0] is not None:
                continue
        found.append({"id": run_id, "attempt": attempt, "command": _retry_command(run_id, campaign.name)})
    return found


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
    earlier_dirs: dict[str, dict[int, Path]] = {}
    if evidence_root.is_dir():
        for entry in sorted(os.listdir(evidence_root)):
            path = evidence_root / entry
            if entry.startswith(".") and not path.is_dir():
                continue
            if path.is_symlink() or not path.is_dir():
                problems.append(f"evidence/{entry}: not a run directory")
                continue
            attempt = ATTEMPT_RE.fullmatch(entry)
            try:
                run_id = er.run_id_from_dir(attempt.group("base") if attempt else entry)
            except ValueError:
                problems.append(f"evidence/{entry}: not a pilot run directory name")
                continue
            if run_id not in planned:
                problems.append(f"evidence/{entry}: {run_id} is not a planned run of {name}")
                continue
            if attempt:
                earlier_dirs.setdefault(run_id, {})[int(attempt.group("n"))] = path
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
    problems.extend(_attempt_problems(pilot_dir, planned, states, earlier_dirs, campaign))
    invalidation, invalidation_problems = _read_invalidation(root, name)
    problems.extend(invalidation_problems)
    if problems:
        raise IntegrityError(problems)
    stage1 = _committed_stage1(root, campaign)
    stage1_problem = None
    stage1_notes: list[str] = []
    if stage == "all" and any(s.record is not None and s.run["stage"] == 2 for s in states.values()):
        stage1_problem = (_stage1_go(stage1, campaign) or _stage1_history(root, campaign)
                          or _stage1_matches(root, campaign, pilot_value, stage1, stage1_notes))
    corpus = _corpus_root(root)
    verified: dict[str, dict] = {}
    notes: list[str] = list(stage1_notes)
    complete = True
    stage1_hold = None
    if isinstance(stage1_problem, (Stage1Unverified, Stage1Changed)):
        # Not a protocol violation of the Stage 2 runs (section 4.5 D/E): the summary is incomplete
        # until the environment or the changed Stage 1 evidence is put right.
        stage1_hold = str(stage1_problem)
        notes.append(f"the committed Stage 1 go could not be re-verified: {stage1_problem}; "
                     + ("fetch or verify the corpus" if isinstance(stage1_problem, Stage1Unverified)
                        else "restore the Stage 1 evidence") + " and summarize again")
        stage1_problem = None
    for state in states.values():
        in_scope = state.run["condition"] == "baseline" or _in_stage(state.run, stage)
        if state.record is None or not in_scope:
            continue
        state.status = state.record["session"]["status"]
        _protocol(state, campaign, stage1, stage1_problem)
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
    first_problems = [f"{s.run['id']}: {s.review_problems[0]}" for s in stage_states if s.review_problems]
    retries = _open_retries(root, campaign, states, [r["id"] for r in plan if _in_stage(r, stage)
                                                     or r["condition"] == "baseline"])
    reasons: list[str] = []
    if invalidation is not None:
        value = "invalid"
        reasons.append(f"the owner recorded an invalidation (scope {invalidation['scope']}, {invalidation['date']})")
    elif pending or unreviewed or review_problems or not complete or stage1_hold:
        value = "incomplete"
        if pending:
            reasons.append(f"{len(pending)} planned run(s) pending: " + ", ".join(pending[:6]) + (" ..." if len(pending) > 6 else ""))
        if unreviewed:
            reasons.append(f"{len(unreviewed)} completed run(s) unreviewed: " + ", ".join(unreviewed[:6])
                           + (" ..." if len(unreviewed) > 6 else ""))
        if review_problems:
            reasons.append(f"{len(review_problems)} review problem(s) unresolved: " + "; ".join(first_problems[:6])
                           + (" ..." if len(first_problems) > 6 else ""))
        if not complete:
            reasons.append(UNVERIFIED_REASON)
        if stage1_hold:
            reasons.append("the committed Stage 1 go is not re-verified here (see the verification notes)")
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
                reasons.append(_missed_reason(target))
        if value == "go":
            reasons.append(GO_TEXT)
    early = _early_stop(stage_runs, targets, {item["id"] for item in retries}) if value == "incomplete" else []
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
                "runs": failure_runs, "earlierAttempts": _replaced(stage_runs)}
    baselines = _baselines(baseline_runs, entries, campaign) if campaign.baselines_planned else None
    disputed = _disputed_essential(campaign, task_ids)
    denominator_disputes = _disputed_items(campaign, task_ids)
    notes_text = caveats(len(task_ids), len(hosts), campaign.tasks["repetitions"])
    if disputed:
        notes_text.append("Disputed essential facts: " + ", ".join(
            d["item"] + (f" (adopted as {d['adoptedAs']})" if d.get("adoptedAs") else "") for d in disputed) + ".")
    outside = [d["item"] for d in denominator_disputes if not d["inDenominator"]]
    if outside:
        notes_text.append("Disputed items outside the final denominators (a reviewer held them essential or "
                          "runs-must-state): " + ", ".join(outside) + ".")
    if any(r["status"] == "invalid" for r in stage_runs):
        notes_text.append(f"Runs counted invalid count as failures; {INVALID_RUN_NOTE}.")
    inputs = {"candidate": campaign.candidate_sha256, "freeze": campaign.freeze_sha256,
              "referenceSet": campaign.reference_set_sha256,
              "invalidation": invalidation["sha256"] if invalidation else None,
              "runs": [{"id": s.run["id"], "record": s.record_sha256, "review": s.review_sha256,
                        "amendments": [a["previous"] for a in (s.record or {}).get("amendments") or []],
                        "earlierAttempts": [{key: item[key] for key in ("attempt", "record", "review", "amendments")}
                                            for item in s.earlier]}
                       for s in states.values() if s.record is not None or s.earlier]}
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
        "openRetries": retries,
        "disputedEssentialFacts": disputed, "disputedDenominatorItems": denominator_disputes,
        "caveats": notes_text, "note": SUMMARY_NOTE, "pilotApproved": False,
    }


def _replaced(runs: list[dict]) -> list[dict]:
    """Every earlier attempt of ``runs`` (kept and replaced by a retry), for the failures lists."""
    return [{"id": run["id"], "attempt": item["attempt"], "status": item["status"],
             "failure": (item["failure"] or {}).get("kind"), "detail": (item["failure"] or {}).get("detail"),
             "promptSent": item["promptSent"], "sentBecause": item["sentBecause"]}
            for run in runs for item in run["attempts"]]


def _unreviewed(entry: dict) -> bool:
    """A completed run whose review is missing, incomplete or has problems (so its zeros mean nothing yet)."""
    return entry["status"] == "completed" and entry["reviewStatus"] in ("missing", "incomplete", "problems")


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
            return {"status": "unreviewed" if _unreviewed(entry) else entry["status"], "reviewed": entry["reviewed"],
                    "ess": entry["ess"], "ESS": entry["ESS"], "unk": entry["unk"], "UNK": entry["UNK"],
                    "precision": _ratio(*prec) if entry["reviewed"] else None}

        skill_side, base_side = side(skill), side(run)
        difference = None  # a pending or unreviewed side has no meaningful zeros yet
        if run["ESS"] and not any(_unreviewed(entry) or entry["status"] == "pending" for entry in (skill, run)):
            difference = (skill["ess"] - run["ess"]) / run["ESS"]
        paired.append({"task": run["task"], "host": run["host"], "skill": skill_side, "baseline": base_side,
                       "recallDifference": difference})
    pending = [r["id"] for r in baseline_runs if r["status"] == "pending"]
    unreviewed = [r["id"] for r in baseline_runs if _unreviewed(r) and r["reviewStatus"] != "problems"]
    problems = [r["id"] for r in baseline_runs if r["reviewStatus"] == "problems"]
    return {"planned": len(baseline_runs), "completed": len(completed), "reviewed": len(reviewed),
            "pending": pending, "unreviewed": unreviewed, "reviewProblems": problems,
            "complete": not (pending or unreviewed or problems),
            "runs": [{"id": r["id"], "status": r["status"], "failure": r["failure"], "invalidReasons": r["invalidReasons"],
                      "warnings": r["warnings"], "reviewStatus": r["reviewStatus"],
                      "reviewProblems": r["reviewProblemCount"], "priorAttempts": r["priorAttempts"],
                      "attempts": r["attempts"]} for r in baseline_runs],
            "earlierAttempts": _replaced(baseline_runs),
            "precision": _ratio(*precision),
            "recall": _ratio(sum(r["ess"] for r in baseline_runs), sum(r["ESS"] for r in baseline_runs)),
            "unknowns": _ratio(sum(r["unk"] for r in baseline_runs), sum(r["UNK"] for r in baseline_runs)),
            "falseAccusations": accusations,
            "activeMinutes": {"total": sum(minutes), "runs": len(minutes),
                              "mean": (sum(minutes) / len(minutes)) if minutes else None},
            "paired": paired,
            "note": "Baselines are never part of the gate; the paired table compares skill repeat 1 with the no-skill "
                    "session, and a pending run, or a completed run that is not yet reviewed (shown as unreviewed), "
                    "has no difference."}


def _disputed_essential(campaign: Campaign, task_ids: list[str]) -> list[dict]:
    """Disputed items that are essential facts of the final reference, including a second-review
    addition the primary reviewer adopted under an essential ID of their own."""
    disputed = []
    for task in task_ids:
        reference = campaign.references[task]
        essential = set(reference["essentialFactIds"])
        for dispute in reference["disputes"]:
            if not isinstance(dispute, dict):
                continue
            adopted = dispute.get("adoptedAs") if isinstance(dispute.get("adoptedAs"), str) else None
            if dispute.get("item") in essential or adopted in essential:
                disputed.append({"task": task, "item": dispute["item"]} | ({"adoptedAs": adopted} if adopted else {}))
    return disputed


def _disputed_items(campaign: Campaign, task_ids: list[str]) -> list[dict]:
    """Disputes on what enters a denominator: a fact either reviewer (or the final reference) holds
    essential, and an unknown whose runs-must-state flag either side set. Resolutions are not copied."""
    found = []
    for task in task_ids:
        reference = campaign.references[task]
        essential = set(reference["essentialFactIds"])
        must = {item["id"] for item in reference["knownUnresolved"] if item.get("runsMustState") is True}
        for dispute in reference["disputes"]:
            if not isinstance(dispute, dict) or not isinstance(dispute.get("item"), str):
                continue
            item = dispute["item"]
            adopted = dispute.get("adoptedAs") if isinstance(dispute.get("adoptedAs"), str) else None
            counted = adopted or item  # an adopted addition enters the denominators under the primary's ID
            sides = [dispute.get("primary"), dispute.get("second")]

            def flag(key: str) -> bool:
                return any(isinstance(side, dict) and side.get(key) is not None for side in sides)

            if counted in essential or any(isinstance(side, dict) and side.get("essential") is True for side in sides):
                kind, denominator = "essential", essential
            elif counted in must or flag("runsMustState"):
                kind, denominator = "runsMustState", must
            else:
                continue
            found.append({"task": task, "item": item, "kind": kind, "primary": sides[0], "second": sides[1],
                          "inDenominator": counted in denominator}
                         | ({"adoptedAs": adopted} if adopted else {}))
    return found


# --------------------------------------------------------------------------------------------
# Markdown, rendered only from the summary JSON


def _fmt_ratio(item: dict | None) -> str:
    if not item or item.get("denominator") in (None, 0):
        return "n/a" if not item else f"{item.get('numerator', 0)}/0"
    numerator, denominator = item["numerator"], item["denominator"]
    return f"{numerator}/{denominator}" if numerator == denominator else f"{numerator}/{denominator} ({_pct(numerator, denominator)})"


def _fmt_value(value: object) -> str:
    """A rate as a percentage floored to a tenth, like _pct (the epsilon absorbs float noise in means)."""
    if value is None:
        return "n/a"
    tenths = math.floor(value * 1000 + 1e-9)
    return f"{tenths // 10}.{tenths % 10}%"


def _needed(target: dict) -> str:
    if target["comparator"] == "<=":
        return f"{target['threshold']:g}"
    return "100%" if target["threshold"] >= 1 else f">={100 * target['threshold']:g}%"  # ASCII: any stdout encodes it


def _failures_line(title: str, failures: list[dict]) -> str | None:
    if not failures:
        return None
    return f"{title}: " + "; ".join(
        f"{item['id']} — {item['status']}"
        + (f" ({item['failure']}" + (f": {item['detail']}" if item.get("detail") else "") + ")" if item.get("failure") else "")
        + (f" [{'; '.join(item['invalidReasons'])}]" if item["invalidReasons"] else "")
        for item in failures) + "."


def _attempts_line(replaced: list[dict], title: str = "Earlier attempts") -> str | None:
    if not replaced:
        return None
    return f"{title}, kept and replaced by a retry: " + "; ".join(
        f"{item['id']} attempt {item['attempt']} — {item['status']}"
        + (f" ({item['failure']}" + (f": {item['detail']}" if item.get("detail") else "") + ")" if item.get("failure")
           else "")
        + ("; counted as sent: " + item["sentBecause"] if item.get("sentBecause")
           else "; prompt never sent" if item.get("promptSent") is False else "")
        for item in replaced) + "."


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
    if summary.get("openRetries"):
        lines += ["", "Retries still open under the run policy (retry before summarize --record; a recorded summary is "
                      "final):"]
        lines += [f"- {item['id']} attempt {item['attempt']}: {item['command']}" for item in summary["openRetries"]]
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
    lines.append(_failures_line("Failures", failures) or "Failures: none.")
    replaced = _attempts_line(summary["failures"].get("earlierAttempts") or [])
    if replaced:
        lines.append(replaced)
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
                  f"{baselines['activeMinutes']['total']:g} over {baselines['activeMinutes']['runs']} run(s)."
                  + (f" Pending: {', '.join(baselines['pending'])}." if baselines.get("pending") else "")
                  + (f" Unreviewed: {', '.join(baselines['unreviewed'])}." if baselines.get("unreviewed") else "")
                  + (f" Review problems: {', '.join(baselines['reviewProblems'])}." if baselines.get("reviewProblems")
                     else "")]
        baseline_failures = [{"id": run["id"], "status": run["status"], "failure": (run.get("failure") or {}).get("kind"),
                              "detail": (run.get("failure") or {}).get("detail"),
                              "invalidReasons": run.get("invalidReasons") or []}
                             for run in baselines["runs"] if run["status"] not in ("completed", "pending")]
        extra = [_failures_line("Baseline failures", baseline_failures),
                 _attempts_line(baselines.get("earlierAttempts") or [], "Baseline earlier attempts")]
        lines += [line for line in extra if line]
        lines += ["", "| Task | Host | Skill recall | No-skill recall | Difference |", "|---|---|---|---|---|"]
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
                     + (f", {len(run['amendments'])} amendment(s)" if run["amendments"] else "")
                     + "".join(f"; attempt {item['attempt']} record {item['record']}"
                               + (f", review {item['review']}" if item["review"] else "")
                               + (f", {len(item['amendments'])} amendment(s)" if item["amendments"] else "")
                               for item in run.get("earlierAttempts") or []))
    lines += ["", summary["note"], ""]
    return "\n".join(lines)


def _uncommitted_tools(root: Path, summary: dict) -> list[str]:
    """The tools named in ``summary`` whose running bytes differ from HEAD, when the tools run from the
    repository being summarized (a synthetic test world outside the checkout is not checked)."""
    if Path(root).resolve() != ROOT.resolve():
        return []
    tooling = summary.get("tooling") if isinstance(summary.get("tooling"), dict) else {}
    found = []
    for key in TOOL_KEYS:
        committed = _show_at_head(root, key)
        if committed is None or er.sha256_bytes(committed) != tooling.get(key):
            found.append(key)
    return found


def record_summary(root: Path, summary: dict) -> tuple[Path, Path]:
    """Write stage<n>-summary.{json,md} exclusively; only a recordable decision is written."""
    value = summary["decision"]["value"]
    allowed = ("go", "stop", "invalid") if summary["stage"] == "1" else ("targets-met", "targets-missed", "invalid")
    if value not in allowed:
        raise PilotError(f"the decision is {value}; only {', '.join(allowed)} can be recorded")
    retries = summary.get("openRetries") or []
    if value != "invalid" and retries:
        raise PilotError("a failure the run policy lets you retry is still open ("
                         + "; ".join(f"attempt {item['attempt']} of {item['id']}: {item['command']}" for item in retries)
                         + "); retry it before recording: a recorded summary is final, and a retry is refused "
                           "afterwards")
    baselines = summary.get("baselines")
    # Baselines belong to Stage 1; the all-stage summary follows a Stage 1 go recorded with them complete.
    if summary["stage"] == "1" and value != "invalid" and isinstance(baselines, dict) \
            and not baselines.get("complete", True):
        waiting = [f"{label} {', '.join(baselines[key])}" for key, label in
                   (("pending", "pending:"), ("unreviewed", "unreviewed:"), ("reviewProblems", "review problems:"))
                   if baselines.get(key)]
        remove = [run["id"] for run in baselines.get("runs") or []
                  if run.get("id") in (baselines.get("reviewProblems") or []) and run.get("status") != "completed"]
        advice = "seal and review them before recording"
        if remove:
            others = bool(baselines.get("pending") or baselines.get("unreviewed")) or \
                len(remove) < len(baselines.get("reviewProblems") or [])
            advice = (f"remove review.md of {', '.join(remove)} (a run that did not complete is not reviewed)"
                      + ("; seal and review the others" if others else "") + " before recording")
        raise PilotError("the planned baselines are not complete (" + "; ".join(waiting) + f"); {advice}. Baselines "
                         "never change the decision, but a recorded summary is final")
    json_bytes = er.canonical_json(summary)
    md_bytes = render_markdown(json.loads(json_bytes)).encode("utf-8")
    for data in (json_bytes, md_bytes):
        match = MACHINE_PATH_RE.search(data.decode("utf-8"))
        if match:
            raise PilotError("the summary contains a machine path; amend the session wording (run-finish --amend) and "
                             "summarize again")
    uncommitted = _uncommitted_tools(root, summary)
    if uncommitted:
        raise PilotError(f"{', '.join(uncommitted)} differ(s) from the version committed at HEAD; commit or discard the "
                         "tool change before recording. A recorded summary names the tools that computed it, and the "
                         "Stage 2 gate and check-frozen look for those tools in the Git history of the commit that "
                         "records the summary")
    number = "1" if summary["stage"] == "1" else "2"
    directory = _campaign_dir(root, summary["campaign"])
    json_path, md_path = directory / f"stage{number}-summary.json", directory / f"stage{number}-summary.md"
    for path in (json_path, md_path):
        if os.path.lexists(path):
            raise PilotError(f"{path.name} already exists; recorded summaries are never overwritten")
        versions = _path_versions(root, f"{PILOT_REL}/{summary['campaign']}/{path.name}")
        if versions is None:
            raise PilotError(f"cannot tell from the Git history whether {path.name} was recorded before (a shallow or "
                             "partial clone, or no readable history; git fetch --unshallow, or clone without --filter)")
        if versions.committed:
            first = versions.first[1] if versions.first else versions.removals[0]
            raise PilotError(f"{path.name} was committed in {first[:12]} and removed since; a recorded summary is "
                             f"final and is never recorded again (restore it with git checkout {first[:12]} -- "
                             f"{PILOT_REL}/{summary['campaign']}/{path.name}; a changed decision needs the owner's "
                             "invalidation.md and a new campaign)")
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
        if command == "run-prepare":
            item.add_argument("--retry", metavar="REASON",
                              help='prepare a new attempt after a sealed failed or blocked one whose session says '
                                   '"Prompt sent: no" (a failure after the prompt was sent is never replaced), up to the '
                                   "run policy's infrastructure retries; the earlier attempt's evidence is kept as "
                                   "<run>.attempt-<n>")
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
    er.safe_streams()
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
            return run_prepare(root, args.run, args.campaign, args.pilot_dir, retry=args.retry)
        if args.command == "run-finish":
            return run_finish(root, args.run, args.campaign, args.pilot_dir, args.amend)
        if args.command == "review-template":
            return review_template(root, args.run, args.campaign, args.pilot_dir)
        summary = summarize(root, args.campaign, args.stage, args.pilot_dir)
        data = er.canonical_json(summary)
        # The Markdown is rendered only from the JSON (section 4.7).
        text = data.decode("utf-8") if args.json else render_markdown(json.loads(data))
        if args.record:
            try:  # recorded before anything is printed, so an output failure never loses a recording
                json_path, md_path = record_summary(root, summary)
            except PilotError:
                sys.stdout.write(text)
                raise
            sys.stdout.write(text)
            print(f"Recorded {json_path.name} and {md_path.name} in {PILOT_REL}/{args.campaign}/. Commit both files "
                  "now, in one commit, before any other commit, pull, merge or rebase, and merge that commit without "
                  "squashing or rebasing it: a recorded summary is final and is never recorded again."
                  + (" Stage 1 runs can no longer be retried or amended, and every Stage 1 review must keep saying "
                     "what it says now; keep a copy of the evidence directory." if summary["stage"] == "1" else "")
                  + f" The summary is {NOT_APPROVAL}.", file=sys.stderr)
            return 0
        sys.stdout.write(text)
        return 0
    except IntegrityError as exc:
        for problem in exc.problems:
            print(f"ERROR {problem}", file=sys.stderr)
        print(f"workflow_eval.py {args.command}: {len(exc.problems)} integrity problem(s); no decision was computed.",
              file=sys.stderr)
        return 1
    except (PilotError, ValueError, OSError) as exc:
        print(f"workflow_eval.py {args.command}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
