#!/usr/bin/env python3
"""Owner decision files for the held-out pilot: templates, checks, context sheets and the freeze.

Commands (dispatched by ``tools/workflow_eval.py``; ``main`` receives the command name first):

* ``template TARGET [--second] [--show]`` and ``template --init-all`` write pending templates for
  a held-out task, its second review, ``run-policy`` or ``development-adjudication``. Files are
  created exclusively and never overwritten; ``--show`` prints a pristine copy instead.
* ``check [TARGET ...] [--show-prompts]`` checks reference decisions, second reviews, the run
  policy and the development adjudication (session and run-review files go to
  ``tools/workflow_pilot.py``). It never writes. Each problem is printed as
  ``path:line: LEVEL section: message``; the exit status is 1 only when there are errors.
* ``context TASK`` writes a gitignored sheet under ``.mlview/review-context/`` that shows each
  candidate anchor's verified quote with numbered source context. It does not interpret code.
* ``freeze --campaign C [--write]`` derives the frozen campaign (references, reference set, run
  policy, 16 prompts, freeze.json) from completed decisions; a dry run unless ``--write``.
* ``check-frozen`` re-derives the committed frozen campaign and requires byte equality.

No code path here writes a decision, reviewer name, verdict, essential flag, policy value or
approval into an owner file: templates hold only ``pending`` values and empty names, and the
freeze refuses anything pending. The tool cannot authenticate a person; ``Transcribed by``,
commit authorship and the repository rules for agents are the safeguards. Local checks are not
semantic accuracy, human review or live-host validation.
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import difflib
import importlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import eval_records as er  # noqa: E402

ROOT = TOOLS.parent
DECISIONS_REL = "evals/workflow/decisions"
CANDIDATES_REL = er.CANDIDATES_REL
TASKS_REL = er.TASKS_REL
REPOSITORIES_REL = "evals/workflow/repositories.json"
PILOT_REL = "evals/workflow/pilot"
DEVELOPMENT_REL = "evals/workflow/development"
CONTEXT_REL = ".mlview/review-context"
GUIDE_REL = "evals/workflow/reference-candidates/REVIEW_GUIDE.md"
CHECK_COMMAND = "python tools/workflow_eval.py check"
TEMPLATE_COMMAND = "python tools/workflow_eval.py template"
POLICY_TARGET = "run-policy"
ADJUDICATION_TARGET = "development-adjudication"
ARTIFACT_PATH = "pilot.mlview.json"
NOTE_TEXT = "Frozen from named human decisions; hashes identify bytes, not approval."
TOOLING_FILES = ("tools/workflow_decisions.py", "tools/eval_records.py", "skills/mlview/scripts/artifact.py")

DECISIONS = ("accept", "qualify", "reject")
SCENARIO_DECISIONS = ("accept", "replace")
BASES = ("observed", "inferred", "unresolved")
SEVERITIES = ("high", "medium", "low")
YES_NO = {"yes": True, "no": False}
USABILITY_ORDER = ("dataOrigin", "updatedParametersAndFitState", "losses", "evaluationBoundaries", "outputs",
                   "uncertainty")
USABILITY_VERDICTS = ("clear", "partial", "missing")
BASELINE_VERDICTS = ("confirmed", "corrected", "rejected")
QUALIFIED_CLAIMS = ("not-supported", "supported", "excluded")
ADJUDICATION_GATE = ("required", "not-required")
PLACEHOLDERS = ("task_prompt", "scenario", "artifact_path")
LEAK_MINIMUM = 30

MACHINE_PATH_RE = er.MACHINE_PATH_RE
PROPOSAL_PLACEHOLDER_RE = re.compile(r"<[^<>]+>")
PROMPT_PLACEHOLDER_RE = re.compile(r"\{([^{}\s]*)\}")
# The no-skill prompt must not mention MLView, the skill, WorkflowDocument or publication
# (CANDIDATE_PROTOCOL.md, "Frozen prompts").
NO_SKILL_FORBIDDEN_RE = re.compile(r"mlview|workflowdocument|\.mlview\.json|\bskill\b|\bpublish(?:es|ed|ing)?\b|"
                                   r"\bpublication\b", re.IGNORECASE)
FROZEN_PROMPTS_REF = 'CANDIDATE_PROTOCOL.md, "Frozen prompts"'
QUALIFIED_CLAIMS_REF = 'CANDIDATE_PROTOCOL.md, "Pair the first stage with no-skill responses"'
POLICY_GUIDE_REF = 'REVIEW_GUIDE.md, "Then: agree on the run policy"'
REASON_HINT = '" -- <reason>" (or " — <reason>")'
FREEZE_README = "evals/workflow/pilot/README.md"
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})", re.ASCII)
INTEGER_RE = re.compile(r"[0-9]+", re.ASCII)
# "<second-review addition>: adopted as <primary ID> -- <why>" (the ID ends at a space or punctuation).
_ADOPTED_RE = re.compile(r"adopted\s+as\s+(?P<id>[^\s,;:()]+)", re.IGNORECASE)
_ITEM_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

_DEFAULT = object()
_PENDING = "pending"


class UsageError(Exception):
    """A command-line mistake (exit status 2)."""


# --------------------------------------------------------------------------------------------
# The world: an MLView checkout (real or synthetic) and an optional pinned corpus


def default_corpus(root: Path) -> Path | None:
    configured = os.environ.get("MLVIEW_PUBLIC_CORPUS_DIR")
    path = Path(configured).expanduser() if configured else Path(root) / ".public-corpus"
    return path if path.is_dir() else None


class World:
    """Everything a check or freeze reads. Tests pass a synthetic ``root`` and ``corpus``."""

    def __init__(self, root: Path = ROOT, corpus: object = _DEFAULT, decisions_dir: Path | None = None) -> None:
        self.root = Path(root)
        self.decisions_dir = Path(decisions_dir) if decisions_dir is not None else self.root / DECISIONS_REL
        if corpus is _DEFAULT:
            corpus = default_corpus(self.root)
        self.corpus = Path(corpus) if corpus is not None and Path(corpus).is_dir() else None
        self._manifest: tuple[bytes, dict] | None = None
        self._repositories: tuple[bytes, dict] | None = None
        self._ledgers: dict[str, tuple[dict, bytes]] = {}
        self._trees: dict[str, dict[str, str] | Exception] = {}
        self._bytes: dict[tuple[str, str], bytes | Exception] = {}
        self._helper = None

    # -- manifests
    def manifest_bytes(self) -> bytes:
        return self._load_manifest()[0]

    @property
    def manifest(self) -> dict:
        return self._load_manifest()[1]

    def _load_manifest(self) -> tuple[bytes, dict]:
        if self._manifest is None:
            raw = (self.root / TASKS_REL).read_bytes()
            self._manifest = (raw, json.loads(raw.decode("utf-8")))
        return self._manifest

    def reload_manifest(self) -> None:
        self._manifest = None

    @property
    def repositories(self) -> dict:
        if self._repositories is None:
            raw = (self.root / REPOSITORIES_REL).read_bytes()
            self._repositories = (raw, json.loads(raw.decode("utf-8")))
        return self._repositories[1]

    def repositories_bytes(self) -> bytes:
        self.repositories  # noqa: B018 - loads the cache
        assert self._repositories is not None
        return self._repositories[0]

    @property
    def hosts(self) -> list[str]:
        return list(self.manifest.get("hosts") or [])

    @property
    def heldout(self) -> list[dict]:
        return [task for task in self.manifest.get("tasks") or [] if task.get("split") == "heldout"]

    def heldout_task(self, task_id: str | None) -> dict | None:
        return next((task for task in self.heldout if task.get("id") == task_id), None)

    def ledger(self, task_id: str) -> tuple[dict, bytes]:
        if task_id not in self._ledgers:
            raw = (self.root / CANDIDATES_REL / f"{task_id}.json").read_bytes()
            self._ledgers[task_id] = (json.loads(raw.decode("utf-8")), raw)
        return self._ledgers[task_id]

    def repo_entry(self, task: dict) -> dict | None:
        return next((repo for repo in self.repositories.get("repos") or []
                     if repo.get("name") == task.get("repository")), None)

    # -- corpus
    def repo_dir(self, task: dict) -> Path | None:
        if self.corpus is None or not isinstance(task.get("repository"), str):
            return None
        path = self.corpus / task["repository"]
        return path if path.is_dir() else None

    def tree(self, task: dict) -> dict[str, str] | None:
        """The pinned tree of the task's repository, or None when the corpus is absent. Raises
        ValueError when the checkout is present but its pinned tree cannot be read."""
        repo = self.repo_dir(task)
        if repo is None:
            return None
        key = task["id"]
        if key not in self._trees:
            try:
                self._trees[key] = er.pinned_tree(repo, task["commit"])
            except ValueError as exc:
                self._trees[key] = exc
        value = self._trees[key]
        if isinstance(value, Exception):
            raise value
        return value

    def pinned(self, task: dict, path: str) -> bytes:
        """Materialised, blob-exact bytes of ``path`` at the task's pinned commit (ValueError)."""
        key = (task["id"], path)
        if key not in self._bytes:
            try:
                repo = self.repo_dir(task)
                if repo is None:
                    raise ValueError("the corpus is absent")
                self._bytes[key] = er.pinned_bytes(repo, task["commit"], path, tree=self.tree(task))
            except ValueError as exc:
                self._bytes[key] = exc
        value = self._bytes[key]
        if isinstance(value, Exception):
            raise value
        return value

    @property
    def helper(self):
        if self._helper is None:
            self._helper = er.load_helper()
        return self._helper

    def display(self, path: Path) -> str:
        path = Path(path)
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(path)

    def corpus_display(self, task: dict) -> str:
        repo = self.repo_dir(task)
        return self.display(repo) if repo is not None else "-"


def short_name(task_id: str) -> str:
    return task_id[len("pilot-"):] if task_id.startswith("pilot-") else task_id


def one_line(text: object) -> str:
    return " ".join(str(text).split())


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _locator(anchor: dict) -> str:
    return er.format_anchor(anchor["file"], anchor.get("cell"), anchor["line"], anchor["endLine"])


def unknown_ids(task_id: str, ledger: dict) -> list[str]:
    return [f"{short_name(task_id)}-u{index:02d}" for index in range(1, len(ledger.get("unknowns") or []) + 1)]


def nondefect_ids(task_id: str, ledger: dict) -> list[str]:
    return [f"{short_name(task_id)}-n{index:02d}" for index in range(1, len(ledger.get("nonDefects") or []) + 1)]


def added_prefix(task_id: str, role: str = "primary") -> str:
    """The ID prefix of owner-added items: ``<short>`` in the primary file and ``<short>-s`` in a
    second review, so the two reviewers' own additions never share an ID."""
    return short_name(task_id) + ("-s" if role == "second" else "")


def added_patterns(task_id: str, role: str = "primary") -> dict[str, str]:
    """The exact ID pattern of each owner-added section kind of a task (``role``: primary or second)."""
    prefix = re.escape(short_name(task_id)) + ("-s" if role == "second" else "")
    return {"Added fact": rf"{prefix}-h\d{{2}}", "Added unknown": rf"{prefix}-hu\d{{2}}", "Defect": rf"{prefix}-d\d{{2}}"}


# --------------------------------------------------------------------------------------------
# Templates (only pending values and empty names are ever written)


def proposal_lines(task_id: str, ledger: dict) -> dict[tuple[str, str | None], list[str]]:
    """The tool-written ``>`` lines that show each candidate section's proposal, keyed by (kind, ID).
    The template writes them; check compares them with the ledger, which is what the freeze reads."""
    scenario = ledger["scenario"]
    found: dict[tuple[str, str | None], list[str]] = {("Scenario", None): [
        f"> Proposed: {one_line(scenario['description'])}",
        f"> Entrypoints: {'; '.join(scenario['entrypoints'])}",
        f"> Arguments: {'; '.join(scenario['arguments']) or 'none'}"]}
    for fact in ledger["facts"]:
        found[("Fact", fact["id"])] = [f"> Claim: {one_line(fact['claim'])}",
                                       f"> Basis: {fact['basis']}. Essential: {_yes_no(fact['essential'])}. "
                                       f"Anchors: {'; '.join(_locator(anchor) for anchor in fact['anchors'])}"]
    for ident, text in zip(unknown_ids(task_id, ledger), ledger["unknowns"]):
        found[("Unknown", ident)] = [f"> {one_line(text)}"]
    for ident, text in zip(nondefect_ids(task_id, ledger), ledger["nonDefects"]):
        found[("Non-defect", ident)] = [f"> {one_line(text)}"]
    return found


def task_template(world: World, task_id: str, *, second: bool = False) -> str:
    ledger, raw = world.ledger(task_id)
    short = added_prefix(task_id, "second" if second else "primary")
    change = ('> To change a proposed Basis, Essential flag or Anchors, add that line and a "Reason:". '
              "Anchors: replaces the proposed list; repeat each proposed anchor you keep.")
    if second:
        lines = [f"# Second review: {task_id}", "",
                 f"> Guide: {GUIDE_REL}. Check: {CHECK_COMMAND} {task_id}",
                 '> Second review: decide any subset of items; "pending" means not reviewed. Only a person may be a second reviewer.',
                 '> Lines starting with ">" are ignored. Indent a wrapped line by two spaces to continue the value above it.',
                 '> Fact and Non-defect: Decision: accept | qualify | reject. Unknown: the same, plus "Runs must state: yes | no" unless rejected.',
                 '> qualify = accept with your wording: add "Wording:" and "Reason:". reject: add "Reason:".',
                 change]
    else:
        lines = [f"# Reference decisions: {task_id}", "",
                 f"> Guide: {GUIDE_REL}. Check: {CHECK_COMMAND} {task_id}",
                 '> Lines starting with ">" are written by the tool and ignored. Replace each "pending". Indent a wrapped '
                 "line by two spaces to continue the value above it.",
                 '> Fact and Non-defect: Decision: accept | qualify | reject. Unknown: the same, plus "Runs must state: yes | no" unless rejected.',
                 '> qualify = accept with your wording: add "Wording:" and "Reason:". reject: add "Reason:".',
                 change]
    proposals = proposal_lines(task_id, ledger)
    lines += ["", f"Candidate: {task_id}.json {er.sha256_bytes(raw)}", "Reviewer:", "Date:", "Transcribed by:", "",
              "## Scenario", *proposals[("Scenario", None)],
              "> accept, or replace and also write Description, Entrypoints, Arguments and Reason",
              "Decision: pending", ""]
    for fact in ledger["facts"]:
        lines += [f"## Fact {fact['id']}", *proposals[("Fact", fact["id"])], "Decision: pending", ""]
    for ident in unknown_ids(task_id, ledger):
        lines += [f"## Unknown {ident}", *proposals[("Unknown", ident)], "Decision: pending", "Runs must state:", ""]
    for ident in nondefect_ids(task_id, ledger):
        lines += [f"## Non-defect {ident}", *proposals[("Non-defect", ident)], "Decision: pending", ""]
    lines += [f'> Omitted fact: add "## Added fact {short}-h01" with Wording, Basis, Essential, Anchors and Reason.',
              f'> Omitted unknown: add "## Added unknown {short}-hu01" with Wording, Runs must state and Reason.',
              f'> Real defect: add "## Defect {short}-d01" with Wording, Severity, Anchors, Counter-evidence and Reason.',
              ""]
    if not second:
        lines += ["## Disagreements",
                  '> Only when a second reviewer disagrees: one line "<item id>: <how it was resolved>".', ""]
    closing = "your decisions above are final" if second else "every decision above is final"
    lines += ["## Task", f'> Write "Review: complete" when {closing}.', "Review: pending", ""]
    return "\n".join(lines)


_HOST_NOTES = {
    "copilot": "Development runs: Copilot Auto, routed to GPT-5.6 Luna (a hidden resolved model stays unknown).",
    "codex": "Development runs: GPT-5.6 Sol, Ultra reasoning; invoked with the $mlview prefix.",
    "claude-code": "Development runs: Fable 5.1, Extra High reasoning.",
}

SKILL_PROMPT_PROPOSAL = (
    "{task_prompt}\n\nSelected scenario:\n{scenario}\n\n"
    "Inspect source without importing or executing target code. Read only this workspace and the installed skill; "
    "do not inspect parent folders, other workspaces or earlier artifacts. Use this assistant as the interpretation "
    "backend; do not delegate to subagents. Publish one WorkflowDocument to {artifact_path} using the installed "
    "helper, then report its path, revision, unresolved cases and repair rounds.")
NO_SKILL_PROMPT_PROPOSAL = (
    "{task_prompt}\n\nSelected scenario:\n{scenario}\n\n"
    "Inspect source without importing or executing target code. Read only this workspace; do not inspect parent "
    "folders or other workspaces. Do not delegate to subagents. Answer in this conversation: describe the workflow, "
    "the unresolved cases, and the files you inspected.")


def _target_text(key: str, value: object) -> str:
    if key == "highSeverityFalseAccusations":
        return f"{key} {value}"
    percent = f"{float(value) * 100:g}%"
    return f"{key} {percent}" if float(value) >= 1 else f"{key} >= {percent}"


def baseline_session_count(world: World) -> int:
    return len(world.heldout) * len(world.hosts)


def policy_template(world: World) -> str:
    targets = world.manifest.get("pilotTargets") or {}
    parts = [_target_text(key, targets.get(key)) for key in er.PILOT_TARGET_KEYS]
    lines = ["# Pilot run policy", "",
             f"> Guide: {POLICY_GUIDE_REF}. Check: {CHECK_COMMAND} {POLICY_TARGET}", "",
             "Reviewer:", "Date:", "Transcribed by:", ""]
    for host in world.hosts:
        lines += [f"## Host {host}", f"> {_HOST_NOTES.get(host, 'Development runs: not recorded for this host.')}",
                  "Model:", "Reasoning:", "Invocation:", ""]
    lines += ["## Environment",
              '> The skill runs "python3 <skill>/scripts/artifact.py". Each host\'s terminal must resolve python3 to 3.10+',
              "> (macOS /usr/bin/python3 is 3.9). Say how, without a machine path; it is not put into the prompt.",
              "Helper Python:", "",
              "## Budget",
              "> Proposed: 20 active minutes including critique and repair; at most 2 validator repair rounds;",
              "> 0 infrastructure retries (a retry is allowed only if the prompt was never sent).",
              "Active minutes:", "Repair rounds:", "Infrastructure retries:", "",
              "## Scoring",
              f"> Qualified claims in supported-claim precision: not-supported | supported | excluded ({QUALIFIED_CLAIMS_REF}).",
              "> Per-host targets: yes = precision and recall must also meet their targets within each host; no = pooled only.",
              "Qualified claims:", "Per-host targets:", "",
              "## Conditions",
              f"> Baseline sessions: {baseline_session_count(world)} (one no-skill session per task and host, Stage 1 only) | 0.",
              "> Development adjudication before Stage 1: required | not-required.",
              "Baseline sessions:", "Development adjudication before Stage 1:", "",
              "## Targets",
              f"> {', '.join(parts[:4])},",
              f"> {', '.join(parts[4:])} (tasks.json pilotTargets). accept confirms them.",
              "Decision: pending", "",
              "## Skill prompt",
              "> Placeholders: {task_prompt} {scenario} {artifact_path}. The host's Invocation is sent before this text.",
              "```text", *SKILL_PROMPT_PROPOSAL.split("\n"), "```", "Decision: pending", "",
              "## No-skill prompt",
              f"> Must not mention MLView, the skill, WorkflowDocument or publication ({FROZEN_PROMPTS_REF}).",
              "```text", *NO_SKILL_PROMPT_PROPOSAL.split("\n"), "```", "Decision: pending", "",
              "## Privacy",
              "> Raw transcripts, UI logs, run reviews and workspaces never enter the repository; committed summaries contain",
              "> counts, statuses and hashes only. Say what else, if anything, may be published.",
              "Publication:", "",
              "## Task", "Review: pending", ""]
    return "\n".join(lines)


def _workflow_eval():
    return _sibling("workflow_eval", required=True)


def adjudication_ledgers(world: World) -> list[tuple[str, str, str]]:
    """(task, host, path relative to evals/workflow/development) for the 12 native ledgers."""
    tasks = _workflow_eval().DEVELOPMENT_TASKS
    return [(task, host, f"native-reviews/{host}/{task}.json") for task in tasks for host in world.hosts]


def _development_json(world: World, rel: str) -> tuple[dict, bytes]:
    raw = (world.root / DEVELOPMENT_REL / rel).read_bytes()
    return json.loads(raw.decode("utf-8")), raw


def _development_rel(value: str) -> str:
    prefix = DEVELOPMENT_REL + "/"
    return value[len(prefix):] if isinstance(value, str) and value.startswith(prefix) else str(value)


def adjudication_template(world: World) -> str:
    lines = ["# Development adjudication", "",
             "> Human verdicts on the 12 provisional native reviews and 3 baseline notes; the ledgers are never edited.",
             "> Claims: supported | qualified | unsupported | omitted. Usability: clear | partial | missing.",
             f"> Baselines: confirmed | corrected | rejected. Add {REASON_HINT} whenever you differ from the",
             "> provisional label, and for every baseline verdict except confirmed. Source context: the review packet "
             "(review-packet).",
             f"> Check: {CHECK_COMMAND} {ADJUDICATION_TARGET}", "",
             "Reviewer:", "Date:", "Transcribed by:", ""]
    for task, host, rel in adjudication_ledgers(world):
        ledger, raw = _development_json(world, rel)
        lines += [f"## {task} / {host}", f"Ledger: {rel} {er.sha256_bytes(raw)}",
                  f"> Artifact: {_development_rel(ledger.get('artifact'))} ({ledger.get('artifactRevision')})"]
        for claim in ledger["claims"]:
            lines += [f"> {claim['id']} (provisional: {claim['verdict']}): {one_line(claim['summary'])}",
                      f"{claim['id']}: pending"]
        for question in USABILITY_ORDER:
            answer = ledger["usability"][question]
            lines += [f"> usability.{question} (provisional: {answer['status']}): {one_line(answer['answer'])}",
                      f"usability.{question}: pending"]
        lines.append("")
    baselines, raw = _development_json(world, "native-reviews/baselines.json")
    by_host = {item.get("host"): item for item in baselines.get("baselines") or []}
    lines += ["## Baselines", f"Ledger: native-reviews/baselines.json {er.sha256_bytes(raw)}"]
    for host in world.hosts:
        item = by_host.get(host) or {}
        lines += [f"> {host} (provisional): {one_line(item.get('summary', ''))}", f"{host}: pending"]
    lines += ["", "## Task", "Review: pending", ""]
    return "\n".join(lines)


README_TEXT = """# Owner decisions

These files hold the pilot owner's reference decisions, second reviews, run policy and development adjudication. Every value starts as `pending`; only the named human reviewer replaces it.
Read the [review guide](../reference-candidates/REVIEW_GUIDE.md) first; `python tools/workflow_eval.py template --show <task>` prints a pristine copy of any file.
Check a file with `python tools/workflow_eval.py check <task>` (or `run-policy`, `development-adjudication`); the check never writes. A complete task or run-policy file ends with "ready to freeze", a complete development adjudication with "complete".
`python tools/workflow_eval.py freeze --campaign <name>` copies completed decisions into `evals/workflow/pilot/<name>/`; it records the reviewers' decisions and adds no approval.
"""


def template_targets(world: World) -> dict[str, tuple[Path, Callable[[], str]]]:
    """Every committed owner file: name -> (path, generator)."""
    targets: dict[str, tuple[Path, Callable[[], str]]] = {}
    for task in world.heldout:
        task_id = task["id"]
        targets[task_id] = (world.decisions_dir / f"{task_id}.md", lambda t=task_id: task_template(world, t))
    targets[POLICY_TARGET] = (world.decisions_dir / f"{POLICY_TARGET}.md", lambda: policy_template(world))
    targets[ADJUDICATION_TARGET] = (world.decisions_dir / f"{ADJUDICATION_TARGET}.md", lambda: adjudication_template(world))
    return targets


# --------------------------------------------------------------------------------------------
# Problems


LEVEL_ORDER = {er.ERROR: 0, er.TODO: 1, er.NOTE: 2}


class Report:
    def __init__(self, display: str) -> None:
        self.display = display
        self.problems: list[er.Problem] = []

    def add(self, line: int, level: str, section: str, message: str) -> None:
        self.problems.append(er.Problem(self.display, line, level, section, message))

    def error(self, line: int, section: str, message: str) -> None:
        self.add(line, er.ERROR, section, message)

    def todo(self, line: int, section: str, message: str) -> None:
        self.add(line, er.TODO, section, message)

    def note(self, line: int, section: str, message: str) -> None:
        self.add(line, er.NOTE, section, message)

    def count(self, level: str) -> int:
        return sum(1 for problem in self.problems if problem.level == level)

    @property
    def errors(self) -> int:
        return self.count(er.ERROR)

    @property
    def todos(self) -> int:
        return self.count(er.TODO)

    def ordered(self) -> list[er.Problem]:
        return sorted(self.problems, key=lambda problem: (problem.line, LEVEL_ORDER.get(problem.level, 9)))


def state_text(errors: int, todos: int, ready: str = "ready to freeze") -> str:
    if errors:
        return "not ready (fix the errors)"
    return "in progress" if todos else ready


def _value(section: er.Section | None, key: str) -> str:
    if section is None:
        return ""
    found = section.field(key)
    return found.value.strip() if found is not None else ""


def _field_line(section: er.Section, key: str) -> int:
    found = section.field(key)
    return found.line if found is not None else section.line


def _machine_path(text: str) -> str | None:
    match = MACHINE_PATH_RE.search(text or "")
    return match.group(0) if match else None


def _join_names(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _valid_date(text: str) -> bool:
    match = DATE_RE.fullmatch(text)
    if not match:
        return False
    try:
        _dt.date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return False
    return True


def _reviewer_header(report: Report, record: er.Record, *, who: str = "the person who checked the source") -> None:
    header = record.header
    for key, message in (("Reviewer", f"Reviewer is empty. Write the name of {who}."),
                         ("Date", "Date is empty. Write the review date as YYYY-MM-DD.")):
        found = header.field(key)
        if found is None or not found.value.strip():
            report.todo(found.line if found else header.line, "header", message)
    date = header.field("Date")
    if date is not None and date.value.strip() and not _valid_date(date.value.strip()):
        report.error(date.line, "header", f'"{date.value.strip()}" is not a date. Use YYYY-MM-DD.')
    transcribed = header.field("Transcribed by")
    if transcribed is not None and transcribed.value.strip():
        report.note(transcribed.line, "header", f"transcribed by {transcribed.value.strip()}; the reviewer must read "
                                                 'the whole file before writing "Review: complete".')


def _task_section(report: Report, record: er.Record, *, closing: str) -> str | None:
    """Check ``## Task`` after every other problem is known; returns the review state."""
    section = record.section("Task")
    if section is None:
        return None
    found = section.field("Review")
    value = found.value.strip().casefold() if found is not None else ""
    open_items = report.todos
    if value == "complete":
        if open_items:
            report.error(found.line, "Task", f"Review is complete, but {open_items} item(s) above are still to do.")
        return "complete"
    if value not in ("", "pending"):
        report.error(found.line, "Task", f'"Review: {found.value.strip()}" must be pending or complete.')
        return None
    report.todo(found.line if found else section.line, "Task",
                f'Review is not complete. Write "Review: complete" when {closing}.')
    return "pending"


def _missing_sections(report: Report, record: er.Record, expected: Iterable[tuple[str, str | None]], command: str) -> None:
    present = {(section.kind, section.ident) for section in record.sections}
    for kind, ident in expected:
        if (kind, ident) not in present:
            label = kind if ident is None else f"{kind} {ident}"
            report.error(1, label, f"this section is missing; restore it from the template ({command}).")


# --------------------------------------------------------------------------------------------
# Reference decisions and second reviews


@dataclass
class RefCheck:
    """The result of checking one reference-decisions or second-review file."""

    task_id: str | None
    role: str
    display: str
    report: Report
    record: er.Record | None = None
    reviewer: str = ""
    date: str = ""
    transcribed_by: str = ""
    review: str | None = None
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(DECISIONS, 0))
    essential_so_far: list[str] = field(default_factory=list)
    scenario: dict | None = None
    facts: list[dict] = field(default_factory=list)
    rejected_facts: list[dict] = field(default_factory=list)
    unknowns: list[dict] = field(default_factory=list)
    rejected_unknowns: list[dict] = field(default_factory=list)
    nondefects: list[dict] = field(default_factory=list)
    rejected_nondefects: list[dict] = field(default_factory=list)
    defects: list[dict] = field(default_factory=list)
    positions: dict[str, dict] = field(default_factory=dict)
    disputes: list[dict] = field(default_factory=list)
    added_items: list[dict] = field(default_factory=list)  # {id, kind, wording} of every Added/Defect section
    added_facts: int = 0
    decided: int = 0
    items: int = 0
    corpus_checked: bool = False
    corpus_note: str = ""
    second: "RefCheck | None" = None
    frozen_in: str | None = None  # the campaign whose freeze.json lists this file with its current bytes
    changed_after: str | None = None  # the campaign whose freeze.json lists this file with other bytes
    added_after: str | None = None  # the campaign frozen without this file, which its freeze would now read

    @property
    def errors(self) -> int:
        return self.report.errors

    @property
    def todos(self) -> int:
        return self.report.todos

    @property
    def ready(self) -> bool:
        return self.record is not None and not self.errors and not self.todos and self.review == "complete"

    @property
    def name(self) -> str:
        base = self.task_id or Path(self.display).name
        return f"{base} (second review)" if self.role == "second" else base


class _RefChecker:
    def __init__(self, world: World, record: er.Record, report: Report, result: RefCheck, task: dict,
                 second: RefCheck | None, raw: bytes | None = None) -> None:
        self.world, self.record, self.report, self.result, self.task = world, record, report, result, task
        self.raw = raw
        self.second = second
        self.task_id: str = task["id"]
        self.primary = result.role == "primary"
        self.high_defects: list[tuple[int, str, str]] = []  # (line, label, id) of the primary's high-severity defects
        self.adopted: dict[str, str] = {}  # primary ID -> the second reviewer's addition it adopted
        self.resolved: set[str] = set()  # casefolded second-review additions with a resolution
        self.short = added_prefix(self.task_id, "primary" if self.primary else "second")
        self.ledger, self.ledger_raw = world.ledger(self.task_id)
        self.facts = {fact["id"]: fact for fact in self.ledger["facts"]}
        self.unknown_text = dict(zip(unknown_ids(self.task_id, self.ledger), self.ledger["unknowns"]))
        self.nondefect_text = dict(zip(nondefect_ids(self.task_id, self.ledger), self.ledger["nonDefects"]))
        self.repo = world.repo_entry(task)
        self.repo_name = task.get("repository", "?")
        self.commit = task.get("commit", "")
        self.patterns: list[str] | None = None
        self.tree: dict[str, str] | None = None
        self.tree_error: str | None = None
        self.pattern_error: str | None = None
        try:
            self.patterns = list(self.repo.get("sparse", [])) if self.repo else None
            if self.patterns is not None:
                er.validate_sparse_patterns(self.patterns)
        except ValueError as exc:
            self.pattern_error, self.patterns = str(exc), None
        try:
            self.tree = world.tree(task)
        except ValueError as exc:
            self.tree_error = str(exc)
        result.corpus_checked = self.tree is not None
        if self.repo is None:
            self.pattern_error = f"{self.repo_name} is not listed in {REPOSITORIES_REL}"

    # -- helpers
    def label(self, section: er.Section) -> str:
        return section.label

    def has(self, section: er.Section, key: str) -> bool:
        return bool(_value(section, key))

    def decision(self, section: er.Section, allowed: Sequence[str]) -> str | None:
        found = section.field("Decision")
        label = self.label(section)
        if found is None:
            self.report.error(section.line, label, 'the "Decision:" line is missing.')
            return None
        value = found.value.strip().casefold()
        if value in ("", _PENDING):
            if self.primary:
                self.report.todo(found.line, label, "Decision is still pending.")
            return _PENDING
        if value not in allowed:
            self.report.error(found.line, label,
                              f'"Decision: {found.value.strip()}" is not a decision. Write one of: {", ".join(allowed)}.')
            return None
        return value

    def covered(self, path: str) -> bool | None:
        if self.patterns is None:
            return None
        return er.sparse_covers(self.patterns, path)

    def not_fetched(self, path: str) -> str:
        return (f"{path} is not fetched by repositories.json ({self.repo_name} sparse list); ask the maintainer to "
                "add it before freezing.")

    def check_path(self, line: int, label: str, path: str) -> bool:
        """Report a source path that is malformed, outside the pinned tree or not fetched."""
        problem = er._path_problem(path)
        if problem:
            self.report.error(line, label, f'"{path}" {problem}.')
            return False
        if self.tree is not None and path not in self.tree:
            self.report.error(line, label, f"{path} is not in the pinned {self.repo_name} tree at {self.commit[:12]}.")
            return False
        if self.covered(path) is False:
            self.report.error(line, label, self.not_fetched(path))
            return False
        return True

    def check_location(self, line: int, label: str, path: str, cell: int | None, start: int, end: int) -> None:
        if not self.check_path(line, label, path) or self.tree is None:
            return
        try:
            data = self.world.pinned(self.task, path)
        except ValueError as exc:
            self.report.error(line, label, f"cannot read {path}: {exc}.")
            return
        helper = self.world.helper
        if cell is not None:
            try:
                notebook = helper._parse_notebook(helper._strip_bom(data.decode("utf-8")))
            except UnicodeDecodeError:
                notebook = None
            cells = notebook.get("cells") if isinstance(notebook, dict) else None
            if not isinstance(cells, list):
                self.report.error(line, label, f"{path} is not a readable notebook.")
                return
            if cell >= len(cells):
                self.report.error(line, label, f"{path} has no cell{cell}.")
                return
        try:
            lines = er.source_lines(data, cell, helper)
        except ValueError as exc:
            where = f"{path}#cell{cell}" if cell is not None else path
            self.report.error(line, label, f"{where} cannot be read: {exc}.")
            return
        count = er.human_line_count(lines)
        if end > count:
            where = f"{path}#cell{cell}" if cell is not None else path
            self.report.error(line, label, f"{where} has {count} lines; line {end} is out of range.")

    def anchor_list(self, section: er.Section) -> list[tuple[str, int | None, int, int]] | None:
        found = section.field("Anchors")
        assert found is not None
        label = self.label(section)
        parsed: list[tuple[str, int | None, int, int]] = []
        failed = False
        for part in er.split_list(found.value):
            try:
                location = er.parse_anchor(part)
            except ValueError as exc:
                self.report.error(found.line, label, str(exc))
                failed = True
                continue
            if location in parsed:
                self.report.error(found.line, label, f'"{part}" is listed twice.')
                continue
            self.check_location(found.line, label, *location)
            parsed.append(location)
        return None if failed else parsed

    def basis(self, section: er.Section) -> str | None:
        found = section.field("Basis")
        value = found.value.strip().casefold() if found is not None else ""
        if not value:
            return None
        if value not in BASES:
            self.report.error(found.line, self.label(section),
                              f'"Basis: {found.value.strip()}" must be observed, inferred or unresolved.')
            return None
        return value

    def yes_no(self, section: er.Section, key: str) -> bool | None:
        found = section.field(key)
        value = found.value.strip().casefold() if found is not None else ""
        if not value:
            return None
        if value not in YES_NO:
            self.report.error(found.line, self.label(section), f'"{key}: {found.value.strip()}" must be yes or no.')
            return None
        return YES_NO[value]

    def reason(self, section: er.Section) -> str | None:
        return _value(section, "Reason") or None

    # -- sections
    def run(self) -> None:
        record, report, result = self.record, self.report, self.result
        candidate = record.header.field("Candidate")
        expected = f"{self.task_id}.json {er.sha256_bytes(self.ledger_raw)}"
        if candidate is None or " ".join(candidate.value.split()) != expected:
            report.error(candidate.line if candidate else record.header.line, "header",
                         f'the Candidate line must read "{self.task_id}.json {er.sha256_bytes(self.ledger_raw)[:12]}..."; '
                         "restore the line the tool wrote (candidate ledgers are immutable).")
        _reviewer_header(report, record)
        result.reviewer = _value(record.header, "Reviewer")
        result.date = _value(record.header, "Date")
        result.transcribed_by = _value(record.header, "Transcribed by")
        if self.pattern_error:
            report.error(record.header.line, "header", f"{REPOSITORIES_REL}: {self.pattern_error}")
        if self.tree_error:
            report.error(record.header.line, "header",
                         f"cannot read the pinned tree of {self.repo_name}: {self.tree_error}")
        command = f"{TEMPLATE_COMMAND} --show {self.task_id}{' --second' if not self.primary else ''}"
        expected_items = ([("Scenario", None)] + [("Fact", ident) for ident in self.facts]
                          + [("Unknown", ident) for ident in self.unknown_text]
                          + [("Non-defect", ident) for ident in self.nondefect_text])
        result.items = len(expected_items)
        if self.primary:
            _missing_sections(report, record, expected_items + [("Disagreements", None), ("Task", None)], command)
        else:
            _missing_sections(report, record, [("Task", None)], command)
        known = {"Fact": self.facts, "Unknown": self.unknown_text, "Non-defect": self.nondefect_text}
        handlers = {"Scenario": self.scenario, "Fact": self.fact, "Unknown": self.unknown,
                    "Non-defect": self.nondefect, "Added fact": self.added_fact,
                    "Added unknown": self.added_unknown, "Defect": self.defect}
        for section in record.sections:
            if section.kind in known and section.ident not in known[section.kind]:
                report.error(section.line, section.label,
                             f'"{section.ident}" is not an item of {self.task_id}.json. Added items use '
                             f'"## Added fact {self.short}-h01".')
                continue
            handler = handlers.get(section.kind)
            if handler is not None:
                handler(section)
        self.shown_proposals()
        if self.primary:
            self.disagreements()
            self.high_severity_notes()
        result.review = _task_section(report, record,
                                      closing="your decisions above are final" if not self.primary
                                      else "every decision above is final")

    def shown_proposals(self) -> None:
        """A NOTE for each candidate section whose tool-written proposal lines (the ">" lines the
        template wrote) are missing or edited: the freeze takes the proposal from the candidate
        ledger, never from the file, so the owner must see what "accept" takes."""
        if self.raw is None:
            return
        text = self.raw.decode("utf-8", "replace")
        lines = [" ".join(line.split()) for line in er._LINE_BREAK.split(text[1:] if text.startswith("\ufeff") else text)]
        proposals = proposal_lines(self.task_id, self.ledger)
        starts = sorted(section.line for section in self.record.sections)
        for section in self.record.sections:
            expected = proposals.get((section.kind, section.ident))
            if not expected:
                continue
            end = next((start for start in starts if start > section.line), len(lines) + 1)
            shown = {line for line in lines[section.line:end - 1] if line.startswith(">")}
            missing = [line for line in expected if " ".join(line.split()) not in shown]
            if missing:
                quoted = "; ".join(f'"{line[2:]}"' for line in missing)
                self.report.note(section.line, self.label(section),
                                 f'the ">" proposal lines under this heading are missing or differ from the candidate '
                                 f"ledger {self.task_id}.json, and accept takes the ledger's proposal: {quoted}. If "
                                 f"someone edited them, restore the lines the tool wrote ({TEMPLATE_COMMAND} --show "
                                 f"{self.task_id}{'' if self.primary else ' --second'}).")

    def position(self, ident: str, value: dict) -> None:
        self.result.positions[ident] = value
        self.result.decided += 1

    def scenario(self, section: er.Section) -> None:
        label = self.label(section)
        decision = self.decision(section, SCENARIO_DECISIONS)
        if decision in (None, _PENDING):
            return
        proposal = self.ledger["scenario"]
        decision_line = _field_line(section, "Decision")
        if decision == "accept":
            for key in ("Description", "Entrypoints", "Arguments", "Reason"):
                if self.has(section, key):
                    self.report.error(_field_line(section, key), label, f'{key} is used only with "Decision: replace".')
            if any(PROPOSAL_PLACEHOLDER_RE.search(argument) for argument in proposal["arguments"]):
                self.report.error(decision_line, label, 'the proposed arguments contain a placeholder (<...>); write '
                                                        '"Decision: replace" and give concrete Arguments.')
            effective = {"decision": "accept", "description": proposal["description"],
                         "entrypoints": list(proposal["entrypoints"]), "arguments": list(proposal["arguments"]),
                         "reason": None}
            self.scenario_paths(label, effective, decision_line, decision_line)
        else:
            for key in ("Description", "Entrypoints", "Arguments", "Reason"):
                if not self.has(section, key):
                    self.report.error(decision_line, label, f'Decision is replace but "{key}:" is missing or empty.')
            for key in ("Description", "Entrypoints", "Arguments"):
                machine = _machine_path(_value(section, key))
                if machine:
                    self.report.error(_field_line(section, key), label,
                                      f"{key} contains an absolute machine path ({machine}); use paths relative to "
                                      "the repository.")
            entrypoints = er.split_list(_value(section, "Entrypoints"))
            if self.has(section, "Entrypoints") and not entrypoints:
                self.report.error(_field_line(section, "Entrypoints"), label,
                                  'Entrypoints needs at least one path ("none" is only for Arguments).')
            effective = {"decision": "replace", "description": _value(section, "Description"),
                         "entrypoints": entrypoints, "arguments": er.split_list(_value(section, "Arguments")),
                         "reason": self.reason(section)}
            self.scenario_paths(label, effective, _field_line(section, "Entrypoints"), _field_line(section, "Arguments"))
        self.result.scenario = effective
        self.position("scenario", {"decision": decision})

    def scenario_paths(self, label: str, scenario: dict, entry_line: int, argument_line: int) -> None:
        for path in scenario["entrypoints"]:
            self.check_path(entry_line, label, path)
        if self.tree is None:
            return
        listed = set(scenario["entrypoints"])
        reported: set[str] = set()
        for argument in scenario["arguments"]:
            for token in _argument_tokens(argument):
                if token in self.tree and token not in listed and token not in reported:
                    reported.add(token)
                    self.report.error(argument_line, label,
                                      f"argument {token} is a file in the pinned tree; list it under Entrypoints too.")

    def fact(self, section: er.Section) -> None:
        label, ident = self.label(section), section.ident
        candidate = self.facts[ident]
        decision = self.decision(section, DECISIONS)
        if decision in (None, _PENDING):
            return
        self.result.counts[decision] += 1
        decision_line = _field_line(section, "Decision")
        reason = self.reason(section)
        if decision == "reject":
            if not reason:
                self.report.error(decision_line, label,
                                  'Decision is reject but "Reason:" is missing. Say why the claim is wrong or not needed.')
            for key in ("Wording", "Basis", "Anchors"):
                if self.has(section, key):
                    self.report.error(_field_line(section, key), label,
                                      f"a rejected fact takes no {key}; delete the line or change the decision.")
            if self.has(section, "Essential"):
                self.report.error(_field_line(section, "Essential"), label,
                                  "a rejected fact cannot be essential; delete the Essential line or change the decision.")
            self.result.rejected_facts.append({"id": ident, "candidateClaim": candidate["claim"], "reason": reason})
            self.position(ident, {"decision": "reject"})
            return
        wording = _value(section, "Wording")
        if decision == "qualify":
            if not wording:
                self.report.error(decision_line, label, 'Decision is qualify but there is no "Wording:" line. '
                                                        'Add "Wording: <your corrected claim>".')
            if not reason:
                self.report.error(decision_line, label,
                                  'Decision is qualify but "Reason:" is missing. Say what the proposed claim got wrong.')
        elif wording:
            self.report.error(_field_line(section, "Wording"), label,
                              'Wording is used only with "Decision: qualify". Change the decision or delete the line.')
        changed: dict[str, int] = {}
        basis = candidate["basis"]
        chosen = self.basis(section)
        if chosen is not None:
            if chosen != basis:
                changed["basis"] = _field_line(section, "Basis")
            basis = chosen
        essential = bool(candidate["essential"])
        flag = self.yes_no(section, "Essential")
        if flag is not None:
            if flag != essential:
                changed["essential"] = _field_line(section, "Essential")
            essential = flag
        anchors = [_candidate_anchor(anchor) for anchor in candidate["anchors"]]
        if self.has(section, "Anchors"):
            parsed = self.anchor_list(section)
            if parsed is not None:
                if set(parsed) != {_location(anchor) for anchor in candidate["anchors"]}:
                    changed["anchors"] = _field_line(section, "Anchors")
                anchors = _merge_anchors(ident, candidate["anchors"], parsed)
                for anchor in candidate["anchors"]:
                    if _location(anchor) not in parsed:
                        self.report.note(_field_line(section, "Anchors"), label,
                                         f"{_locator(anchor)} (proposed) is no longer an anchor: Anchors: replaces "
                                         "the proposed list, so repeat every proposed anchor you keep.")
        if not anchors and basis != "unresolved":
            self.report.error(_field_line(section, "Anchors"), label,
                              "a fact needs at least one anchor unless Basis is unresolved.")
        if changed and decision == "accept" and not reason:
            names = [name.capitalize() for name in ("basis", "essential", "anchors") if name in changed]
            verb = "differs" if names in (["Basis"], ["Essential"]) else "differ"
            self.report.error(min(changed.values()), label,
                              f'{_join_names(names)} {verb} from the proposal; add "Reason:" saying why.')
        claim = wording if decision == "qualify" and wording else candidate["claim"]
        changes = sorted(set(changed) | ({"claim"} if claim != candidate["claim"] else set()))
        self.result.facts.append({"id": ident, "origin": "candidate", "decision": decision, "claim": claim,
                                  "candidateClaim": candidate["claim"], "basis": basis, "essential": essential,
                                  "changed": changes, "anchors": anchors, "reason": reason})
        if essential:
            self.result.essential_so_far.append(ident)
        self.position(ident, {"decision": decision, "basis": basis, "essential": essential})

    def _qualify_rules(self, section: er.Section, decision: str, what: str) -> None:
        label, decision_line = self.label(section), _field_line(section, "Decision")
        if decision == "qualify":
            if not self.has(section, "Wording"):
                self.report.error(decision_line, label, 'Decision is qualify but there is no "Wording:" line. '
                                                        'Add "Wording: <your corrected text>".')
            if not self.reason(section):
                self.report.error(decision_line, label,
                                  'Decision is qualify but "Reason:" is missing. Say what the proposed text got wrong.')
        elif decision == "accept" and self.has(section, "Wording"):
            self.report.error(_field_line(section, "Wording"), label,
                              'Wording is used only with "Decision: qualify". Change the decision or delete the line.')
        elif decision == "reject":
            if not self.reason(section):
                self.report.error(decision_line, label, f'Decision is reject but "Reason:" is missing. Say why {what}.')
            if self.has(section, "Wording"):
                self.report.error(_field_line(section, "Wording"), label,
                                  f"a rejected {section.kind.casefold()} takes no Wording; delete the line or change "
                                  "the decision.")

    def unknown(self, section: er.Section) -> None:
        label, ident = self.label(section), section.ident
        text = self.unknown_text[ident]
        decision = self.decision(section, DECISIONS)
        if decision in (None, _PENDING):
            return
        self._qualify_rules(section, decision, "this is not a real uncertainty or not needed")
        runs = section.field("Runs must state")
        reason = self.reason(section)
        if decision == "reject":
            if runs is not None and runs.value.strip():
                self.report.error(runs.line, label, 'a rejected unknown takes no "Runs must state"; delete the value.')
            self.result.rejected_unknowns.append({"id": ident, "candidateText": text, "reason": reason})
            self.position(ident, {"decision": "reject"})
            return
        must = self.runs_must_state(section)
        wording = _value(section, "Wording")
        effective = wording if decision == "qualify" and wording else text
        self.result.unknowns.append({"id": ident, "origin": "candidate", "decision": decision, "text": effective,
                                     "candidateText": text, "runsMustState": bool(must), "reason": reason})
        if must is not None:
            self.position(ident, {"decision": decision, "runsMustState": must})

    def runs_must_state(self, section: er.Section) -> bool | None:
        runs = section.field("Runs must state")
        value = runs.value.strip().casefold() if runs is not None else ""
        if not value:
            self.report.todo(runs.line if runs else _field_line(section, "Decision"), self.label(section),
                             '"Runs must state:" must be yes (every run must state this uncertainty) or no.')
            return None
        if value not in YES_NO:
            self.report.error(runs.line, self.label(section), f'"Runs must state: {runs.value.strip()}" must be yes or no.')
            return None
        return YES_NO[value]

    def nondefect(self, section: er.Section) -> None:
        ident = section.ident
        text = self.nondefect_text[ident]
        decision = self.decision(section, DECISIONS)
        if decision in (None, _PENDING):
            return
        self._qualify_rules(section, decision, "this is not intended behaviour or not needed")
        reason = self.reason(section)
        if decision == "reject":
            self.result.rejected_nondefects.append({"id": ident, "candidateText": text, "reason": reason})
        else:
            wording = _value(section, "Wording")
            self.result.nondefects.append({"id": ident, "decision": decision,
                                           "text": wording if decision == "qualify" and wording else text,
                                           "candidateText": text, "reason": reason})
        self.position(ident, {"decision": decision})

    def added_id(self, section: er.Section, what: str, suffix: str) -> None:
        role = "primary" if self.primary else "second"
        if not re.fullmatch(added_patterns(self.task_id, role)[section.kind], section.ident or ""):
            prefix = added_prefix(self.task_id, role)
            self.report.error(section.line, self.label(section),
                              f"{what} IDs look like {prefix}-{suffix}01, {prefix}-{suffix}02, ...")
        self.result.added_items.append({"id": section.ident, "kind": section.kind,
                                        "wording": _value(section, "Wording")})

    def require(self, section: er.Section, keys: Sequence[str]) -> None:
        for key in keys:
            if not self.has(section, key):
                self.report.error(section.line, self.label(section), f'"{key}:" is missing.')

    def added_fact(self, section: er.Section) -> None:
        label, ident = self.label(section), section.ident
        self.added_id(section, "added fact", "h")
        self.require(section, ("Wording", "Basis", "Essential", "Reason"))
        basis = self.basis(section)
        essential = self.yes_no(section, "Essential")
        anchors: list[dict] = []
        if self.has(section, "Anchors"):
            parsed = self.anchor_list(section) or []
            anchors = [_new_anchor(f"{ident}-a{index}", location) for index, location in enumerate(parsed, 1)]
        elif basis != "unresolved":
            self.report.error(section.line, label, '"Anchors:" is required unless Basis is unresolved.')
        self.result.added_facts += 1
        if essential:
            self.result.essential_so_far.append(ident)
        self.result.facts.append({"id": ident, "origin": "added", "decision": "added", "claim": _value(section, "Wording"),
                                  "candidateClaim": None, "basis": basis, "essential": bool(essential), "changed": [],
                                  "anchors": anchors, "reason": self.reason(section)})
        if basis is not None and essential is not None:
            self.position(ident, {"decision": "added", "basis": basis, "essential": essential})

    def added_unknown(self, section: er.Section) -> None:
        ident = section.ident
        self.added_id(section, "added unknown", "hu")
        self.require(section, ("Wording", "Reason"))
        must = self.yes_no(section, "Runs must state")
        if not self.has(section, "Runs must state"):
            self.report.error(section.line, self.label(section), '"Runs must state:" is missing.')
        self.result.unknowns.append({"id": ident, "origin": "added", "decision": "added", "text": _value(section, "Wording"),
                                     "candidateText": None, "runsMustState": bool(must), "reason": self.reason(section)})
        if must is not None:
            self.position(ident, {"decision": "added", "runsMustState": must})

    def defect(self, section: er.Section) -> None:
        label, ident = self.label(section), section.ident
        self.added_id(section, "defect", "d")
        self.require(section, ("Wording", "Severity", "Anchors", "Counter-evidence", "Reason"))
        severity_field = section.field("Severity")
        severity = severity_field.value.strip().casefold() if severity_field is not None else ""
        if severity and severity not in SEVERITIES:
            self.report.error(severity_field.line, label,
                              f'"Severity: {severity_field.value.strip()}" must be high, medium or low.')
            severity = ""
        anchors: list[dict] = []
        if self.has(section, "Anchors"):
            parsed = self.anchor_list(section) or []
            anchors = [_new_anchor(f"{ident}-a{index}", location) for index, location in enumerate(parsed, 1)]
        if severity == "high" and self.primary:
            self.high_defects.append((section.line, label, ident))
        self.result.defects.append({"id": ident, "text": _value(section, "Wording"), "severity": severity or None,
                                    "anchors": anchors, "counterEvidence": _value(section, "Counter-evidence"),
                                    "reason": self.reason(section)})
        if severity:
            self.position(ident, {"decision": "added", "severity": severity})

    def disagreements(self) -> None:
        section = self.record.section("Disagreements")
        second = self.second
        resolutions: dict[str, er.Field] = {}
        known_items = set(self.result.positions) | {"scenario"}
        differing: list[tuple[str, dict, dict]] = []
        added: list[dict] = []  # the second reviewer's own additions, which the primary file never decided
        if second is not None:
            for ident, mine in self.result.positions.items():
                theirs = second.positions.get(ident)
                if theirs is not None and theirs != mine:
                    differing.append((ident, mine, theirs))
            added = [item for item in second.added_items
                     if isinstance(item.get("id"), str) and item["id"] and item["id"] not in self.result.positions]
        disagreeing = {ident for ident, _mine, _theirs in differing} | {item["id"] for item in added}
        if section is not None:
            after_resolution = False
            folded = {ident.casefold(): ident for ident in disagreeing}
            unresolved = sorted(set(disagreeing) - {folded[line.key.strip().casefold()] for line in section.lines
                                                    if line.key.strip().casefold() in folded})
            for line in section.lines:
                key = line.key.strip()
                match = folded.get(key.casefold())
                if match is None:
                    if second is None:
                        message = (f'"{key}": there is no second review ({self.task_id}.second.md) to disagree with; '
                                   "delete this line.")
                    elif key.casefold() in {item.casefold() for item in known_items}:
                        message = f'"{key}" does not disagree with the second review; delete this line.'
                    elif after_resolution and not _ITEM_ID_RE.fullmatch(key):
                        # Usually the wrapped second line of the resolution above ("the DDP branch: ...").
                        message = (f'"{key}" is not an item ID. To continue the previous line, indent it by two '
                                   'spaces; put ">" in front of notes only.')
                    elif unresolved:
                        close = difflib.get_close_matches(key, unresolved, n=1, cutoff=0.6)
                        message = (f'"{key}" is not an item that disagrees with the second review (still open: '
                                   f'{", ".join(unresolved)})' + (f'; did you mean "{close[0]}"?' if close else "")
                                   + " Correct the ID, or delete this line.")
                    else:
                        message = f'"{key}" is not an item that disagrees with the second review; delete this line.'
                    self.report.error(line.line, "Disagreements", message)
                    after_resolution = False
                    continue
                if match in resolutions:  # keys are case-insensitive: a second line never replaces the first
                    self.report.error(line.line, "Disagreements", f'"{key}" appears twice (first on line '
                                                                  f"{resolutions[match].line}). Keep one.")
                    after_resolution = False
                    continue
                resolutions[match] = line
                after_resolution = True
        where = section.line if section is not None else 1
        name = f" ({second.reviewer})" if second is not None and second.reviewer else ""
        for ident, mine, theirs in differing:
            resolution = resolutions.get(ident)
            if resolution is None or not resolution.value.strip():
                self.report.todo(resolution.line if resolution else where, "Disagreements",
                                 f"{ident}: the second reviewer{name} chose {_describe(theirs, mine)}; you chose "
                                 f'{_describe(mine, theirs)}. Add "{ident}: <how it was resolved>".')
                continue
            self.result.disputes.append({"item": ident, "primary": mine, "second": theirs,
                                         "resolution": resolution.value.strip()})
        kinds = {"Added fact": "fact", "Added unknown": "unknown", "Defect": "defect"}
        suffixes = {"Added fact": "h", "Added unknown": "hu", "Defect": "d"}
        own = {item["id"].casefold(): item for item in self.result.added_items if isinstance(item.get("id"), str)}
        for item in added:
            ident = item["id"]
            theirs = second.positions.get(ident) or {"decision": "added"}
            resolution = resolutions.get(ident)
            if resolution is None or not resolution.value.strip():
                details = [f"{label}: {_yes_no(theirs[key]) if isinstance(theirs[key], bool) else theirs[key]}"
                           for key, label in _POSITION_LABELS if key in theirs]
                wording = _short_text(item.get("wording") or "", 80)
                self.report.todo(resolution.line if resolution else where, "Disagreements",
                                 f'{ident}: the second reviewer{name} added the {kinds.get(item["kind"], "item")} '
                                 f'"{wording}"' + (f" ({', '.join(details)})" if details else "")
                                 + f'. To adopt it, add it under your own ID and write "{ident}: adopted as <your ID> '
                                   f'-- <why>"; otherwise write "{ident}: <why it is not adopted>".')
                continue
            text = resolution.value.strip()
            entry: dict = {"item": ident, "primary": None, "second": theirs, "resolution": text}
            first_word = text.split()[0].casefold().strip(".,;:!-—") if text.split() else ""
            if not text.casefold().startswith("adopted"):
                # Only an added item of the same kind can be the adoption target; a sentence-final
                # "." (or "_", "-") is not part of the ID.
                named = next((own[token.rstrip("._-").casefold()]["id"] for token in _ITEM_ID_RE.findall(text)
                              if own.get(token.rstrip("._-").casefold(), {}).get("kind") == item.get("kind")), None)
                if named is not None:
                    self.report.error(resolution.line, "Disagreements",
                                      f'{ident}: the resolution names your added item {named}, so it is read as not '
                                      f'adopted. Write "{ident}: adopted as {named} -- <why>" to adopt it, or remove '
                                      f"{named} from this line if it is not adopted.")
                    continue
                if first_word.startswith("adopt") or \
                        (len(first_word) >= 5 and _edit_distance(first_word, "adopted") <= 2):
                    word = text.split()[0]
                    self.report.error(resolution.line, "Disagreements",
                                      f'{ident}: the resolution starts with "{word}", which reads like "adopted" but is '
                                      f'not the adoption form. To adopt it, write "{ident}: adopted as <your ID> -- '
                                      f'<why>"; otherwise start the resolution with a word other than "{word}", for '
                                      f'example "{ident}: not adopted -- <why>".')
                    continue
            if text.casefold().startswith("adopted"):
                found = _ADOPTED_RE.match(text)
                kind = item.get("kind")
                example = f"{self.short}-{suffixes.get(kind, 'h')}01"
                adopted_id = found.group("id").rstrip(".") if found else ""
                target = own.get(adopted_id.casefold()) if adopted_id else None
                if target is None or target.get("kind") != kind:
                    named = f'"adopted as {adopted_id}"' if adopted_id else '"adopted"'
                    candidate_item = bool(adopted_id) and target is None and any(
                        position.casefold() == adopted_id.casefold() for position in self.result.positions)
                    hint = ""
                    if candidate_item or not adopted_id:
                        hint = (f' A resolution that starts with "adopted" is read as an adoption. A candidate item '
                                f'is already in your reference: if the addition duplicates it, write "{ident}: <why it '
                                f'is not adopted>" (for example "same as '
                                f'{adopted_id if candidate_item else "<candidate ID>"}") without the word "adopted".')
                    self.report.error(resolution.line, "Disagreements",
                                      f"{ident}: {named} must name the section you added for it in this file, "
                                      f'"## {kind} {example}"; write "{ident}: adopted as <your ID> -- <why>".' + hint)
                    continue
                entry["primary"] = self.result.positions.get(target["id"])
                entry["adoptedAs"] = target["id"]
                self.adopted[target["id"]] = ident
            self.resolved.add(ident.casefold())
            self.result.disputes.append(entry)

    def high_severity_notes(self) -> None:
        """A NOTE for each of the primary reviewer's high-severity defects that no second reviewer covered.
        A second review covers one only through its own addition, resolved here as adopted."""
        second_prefix = added_prefix(self.task_id, "second")
        found = [(int(match.group(1)), str(item["id"])) for item in (self.second.added_items if self.second else [])
                 for match in [re.fullmatch(re.escape(second_prefix) + r"-d(\d+)", str(item.get("id") or ""),
                                            re.IGNORECASE)] if match]
        # The note always names an unused ID (the next number after every existing one). A second-review
        # defect that has no resolution yet is mentioned as a possible match; one already resolved,
        # adopted or not, never is.
        open_defects = [ident for _number, ident in sorted(found) if ident.casefold() not in self.resolved]
        number = max((n for n, _ident in found), default=0)
        for line, label, ident in self.high_defects:
            if self.second is None:
                self.report.note(line, label, "a second reviewer is recommended for high-severity defects (REVIEW_GUIDE).")
            elif ident not in self.adopted:
                number += 1
                suggested = f"{second_prefix}-d{number:02d}"
                which = open_defects[0] if len(open_defects) == 1 else f"one of {', '.join(open_defects)}"
                match = (f' If {which} is the same defect, resolve it as "<ID>: adopted as {ident} -- <why>" '
                         "instead.") if open_defects else ""
                self.report.note(line, label, "the second review does not cover your own additions. For a second "
                                              f"opinion on this high-severity defect, the second reviewer adds it as "
                                              f'"## Defect {suggested}" and you resolve it as '
                                              f'"{suggested}: adopted as {ident} -- <why>"; otherwise it is '
                                              f"not second-reviewed (REVIEW_GUIDE).{match}")


def _edit_distance(left: str, right: str) -> int:
    """Optimal string alignment distance (a swap of two neighbours counts once: "adpoted" is 1 from "adopted")."""
    rows = [list(range(len(right) + 1))] + [[index] + [0] * len(right) for index in range(1, len(left) + 1)]
    for i in range(1, len(left) + 1):
        for j in range(1, len(right) + 1):
            cost = 0 if left[i - 1] == right[j - 1] else 1
            rows[i][j] = min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and left[i - 1] == right[j - 2] and left[i - 2] == right[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return rows[len(left)][len(right)]


_POSITION_LABELS = (("basis", "basis"), ("essential", "essential"), ("runsMustState", "runs must state"),
                    ("severity", "severity"))


def _short_text(text: str, limit: int) -> str:
    value = one_line(text)
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "\u2026"


def _describe(mine: dict, other: dict) -> str:
    extras = []
    for key, label in _POSITION_LABELS:
        if key in mine and key in other and mine[key] != other[key]:
            value = mine[key]
            extras.append(f"{label}: {_yes_no(value) if isinstance(value, bool) else value}")
    if mine.get("decision") == "added":
        return ", ".join(extras) if extras else "added"
    return mine["decision"] + (f" ({', '.join(extras)})" if extras else "")


def _argument_tokens(argument: str) -> list[str]:
    tokens: list[str] = []
    for token in argument.split():
        for candidate in (token, token.split("=", 1)[1] if "=" in token else None):
            if not candidate:
                continue
            if candidate.startswith("./"):
                candidate = candidate[2:]
            if candidate and candidate not in tokens:
                tokens.append(candidate)
    return tokens


def _location(anchor: dict) -> tuple[str, int | None, int, int]:
    return anchor["file"], anchor.get("cell"), anchor["line"], anchor["endLine"]


def _new_anchor(ident: str, location: tuple[str, int | None, int, int]) -> dict:
    path, cell, line, end = location
    anchor = {"id": ident, "file": path, "line": line, "endLine": end}
    if cell is not None:
        anchor["cell"] = cell
    return anchor


def _candidate_anchor(anchor: dict) -> dict:
    return _new_anchor(anchor["id"], _location(anchor))


def _merge_anchors(fact_id: str, candidates: list[dict], parsed: list[tuple]) -> list[dict]:
    """The listed anchors: a candidate anchor keeps its ID when its locator is listed; new
    locators get ``<fact id>-h1``, ``-h2``, ... in the order listed."""
    by_location = {_location(anchor): anchor for anchor in candidates}
    merged, counter = [], 0
    for location in parsed:
        if location in by_location:
            merged.append(_candidate_anchor(by_location[location]))
        else:
            counter += 1
            merged.append(_new_anchor(f"{fact_id}-h{counter}", location))
    return merged


def check_reference(world: World, raw: bytes, display: str, *, second: RefCheck | None = None,
                    expected_name: str | None = None) -> RefCheck:
    """Check one reference-decisions or second-review file. ``second`` is the checked second
    review of the same task (primary files only)."""
    report = Report(display)
    record, problems = er.parse_record(raw, display)
    report.problems.extend(problems)
    role = "second" if record is not None and record.kind == "Second review" else "primary"
    result = RefCheck(record.ident if record else None, role, display, report, record)
    if record is None:
        return result
    task = world.heldout_task(record.ident)
    if task is None:
        report.error(record.header.line, "header", f"{record.ident} is not a held-out task in {TASKS_REL}.")
        result.task_id = None
        return result
    if expected_name is not None and expected_name != record.ident:
        report.error(record.header.line, "header", f"the title names {record.ident} but the file is for "
                                                   f"{expected_name}; restore the title the tool wrote.")
    result.second = second
    _RefChecker(world, record, report, result, task, second, raw).run()
    return result


def reference_summary(world: World, result: RefCheck) -> list[str]:
    ready = (f"frozen in {result.frozen_in}" if result.frozen_in else
             f"changed after the freeze of {result.changed_after}" if result.changed_after else
             f"added after the freeze of {result.added_after}" if result.added_after else "ready to freeze")
    lines = [f"{result.name}: {result.errors} error(s), {result.todos} to do; "
             f"{state_text(result.errors, result.todos, ready)}."]
    if result.record is None or result.task_id is None:
        return lines
    counts = result.counts
    task = world.heldout_task(result.task_id) or {}
    if result.role == "second":
        lines.append(f"  items decided: {result.decided}; facts: {counts['accept']} accept, {counts['qualify']} "
                     f"qualify, {counts['reject']} reject")
    elif result.errors or result.todos:
        essential = result.essential_so_far
        lines.append(f"  facts decided: {counts['accept']} accept, {counts['qualify']} qualify, {counts['reject']} "
                     f"reject; essential so far ({len(essential)}): {' '.join(essential) or '-'}")
    else:
        essential = [fact["id"] for fact in result.facts if fact["essential"]]
        must = [item["id"] for item in result.unknowns if item["runsMustState"]]
        lines.append(f"  facts: {counts['accept']} accept, {counts['qualify']} qualify, {counts['reject']} reject; "
                     f"added {result.added_facts}; essential ({len(essential)}): {' '.join(essential) or '-'}")
        lines.append(f"  unknowns: {len(result.unknowns)} kept (runs must state: {' '.join(must) or '-'}); "
                     f"non-defects: {len(result.nondefects)} kept; defects: {len(result.defects)}")
    if not result.corpus_checked:
        lines.append("  anchors not checked: corpus absent (freeze requires it)")
    elif result.role == "primary" and not result.errors and not result.todos:
        lines.append(f"  anchors checked against {task.get('repository')}@{str(task.get('commit'))[:12]} "
                     f"({world.corpus_display(task)})")
    return lines


# --------------------------------------------------------------------------------------------
# Run policy


@dataclass
class PolicyCheck:
    display: str
    report: Report
    record: er.Record | None = None
    reviewer: str = ""
    date: str = ""
    transcribed_by: str = ""
    review: str | None = None
    values: dict = field(default_factory=dict)
    skill_template: str | None = None
    baseline_template: str | None = None
    frozen_in: str | None = None
    changed_after: str | None = None

    @property
    def errors(self) -> int:
        return self.report.errors

    @property
    def todos(self) -> int:
        return self.report.todos

    @property
    def ready(self) -> bool:
        return self.record is not None and not self.errors and not self.todos and self.review == "complete"


def check_policy(world: World, raw: bytes, display: str) -> PolicyCheck:
    report = Report(display)
    record, problems = er.parse_record(raw, display)
    report.problems.extend(problems)
    result = PolicyCheck(display, report, record)
    if record is None:
        return result
    _reviewer_header(report, record)
    result.reviewer = _value(record.header, "Reviewer")
    result.date = _value(record.header, "Date")
    result.transcribed_by = _value(record.header, "Transcribed by")
    hosts = world.hosts
    command = f"{TEMPLATE_COMMAND} --show {POLICY_TARGET}"
    expected = [("Host", host) for host in hosts] + [(kind, None) for kind in (
        "Environment", "Budget", "Scoring", "Conditions", "Targets", "Skill prompt", "No-skill prompt", "Privacy", "Task")]
    _missing_sections(report, record, expected, command)
    values: dict = {"hosts": {}}

    def text(section: er.Section, key: str, message: str) -> str | None:
        found = section.field(key)
        value = found.value.strip() if found is not None else ""
        if not value:
            report.todo(found.line if found else section.line, section.label, f"{key} is empty. {message}")
            return None
        machine = _machine_path(value)
        if machine:
            report.error(found.line, section.label, f"{key} contains an absolute machine path ({machine}); describe it "
                                                    "without one.")
            return None
        return value

    def choice(section: er.Section, key: str, allowed: Sequence[str]) -> str | None:
        found = section.field(key)
        value = found.value.strip().casefold() if found is not None else ""
        if not value:
            report.todo(found.line if found else section.line, section.label,
                        f"{key} is empty. Write one of: {', '.join(allowed)}.")
            return None
        if value not in allowed:
            report.error(found.line, section.label, f'"{key}: {found.value.strip()}" must be one of: {", ".join(allowed)}.')
            return None
        return value

    def number(section: er.Section, key: str, low: int, high: int) -> int | None:
        found = section.field(key)
        value = found.value.strip() if found is not None else ""
        if not value:
            report.todo(found.line if found else section.line, section.label,
                        f"{key} is empty. Write a whole number from {low} to {high}.")
            return None
        if not INTEGER_RE.fullmatch(value) or not low <= int(value) <= high:
            report.error(found.line, section.label, f'"{key}: {value}" must be a whole number from {low} to {high}.')
            return None
        return int(value)

    def accepted(section: er.Section, message: str) -> bool:
        found = section.field("Decision")
        value = found.value.strip().casefold() if found is not None else ""
        if found is None:
            report.error(section.line, section.label, 'the "Decision:" line is missing.')
            return False
        if value in ("", _PENDING):
            report.todo(found.line, section.label, "Decision is still pending.")
            return False
        if value != "accept":
            report.error(found.line, section.label, f'"Decision: {found.value.strip()}" is not a decision. {message}')
            return False
        return True

    for section in record.sections:
        if section.kind == "Host":
            if section.ident not in hosts:
                report.error(section.line, section.label,
                             f'"{section.ident}" is not a host in {TASKS_REL} ({", ".join(hosts)}).')
                continue
            values["hosts"][section.ident] = {
                "model": text(section, "Model", f"Write the exact model setting every {section.ident} run must use."),
                "reasoning": text(section, "Reasoning", f"Write the exact reasoning setting every {section.ident} run "
                                                        'must use (or "not exposed").'),
                "invocation": text(section, "Invocation", f"Write how every {section.ident} run invokes the skill."),
            }
        elif section.kind == "Environment":
            values["helperPython"] = text(section, "Helper Python", "Say how each host's terminal resolves python3 to "
                                                                    "Python 3.10 or newer (no machine path).")
        elif section.kind == "Budget":
            values["activeMinutes"] = number(section, "Active minutes", 1, 240)
            values["repairRounds"] = number(section, "Repair rounds", 0, 5)
            values["infrastructureRetries"] = number(section, "Infrastructure retries", 0, 1)
        elif section.kind == "Scoring":
            values["qualifiedClaims"] = choice(section, "Qualified claims", QUALIFIED_CLAIMS)
            per_host = choice(section, "Per-host targets", tuple(YES_NO))
            values["perHostTargets"] = None if per_host is None else YES_NO[per_host]
        elif section.kind == "Conditions":
            count = str(baseline_session_count(world))
            sessions = choice(section, "Baseline sessions", (count, "0"))
            values["baselineSessions"] = None if sessions is None else int(sessions)
            values["developmentAdjudication"] = choice(section, "Development adjudication before Stage 1",
                                                       ADJUDICATION_GATE)
        elif section.kind == "Targets":
            values["targets"] = accepted(section, f"Write accept (to change a target, edit {TASKS_REL} pilotTargets "
                                                  "before the freeze).")
        elif section.kind in ("Skill prompt", "No-skill prompt"):
            skill = section.kind == "Skill prompt"
            ok = accepted(section, "Write accept once the prompt text is final.")
            if section.fence is None:
                report.error(section.line, section.label,
                             "the prompt text must be a fenced block (```text ... ```); restore it from the template.")
                continue
            _prompt_rules(report, section, section.fence, skill)
            if skill:
                result.skill_template = section.fence
                values["skillPrompt"] = ok
            else:
                result.baseline_template = section.fence
                values["baselinePrompt"] = ok
        elif section.kind == "Privacy":
            values["publication"] = text(section, "Publication", "Say what, if anything, may be published besides "
                                                                 "counts, statuses and hashes.")
    result.values = values
    result.review = _task_section(report, record, closing="every decision above is final")
    return result


def _prompt_rules(report: Report, section: er.Section, template: str, skill: bool) -> None:
    line = section.fence_line or section.line
    found = PROMPT_PLACEHOLDER_RE.findall(template)
    unknown = sorted({name for name in found if name not in PLACEHOLDERS})
    if unknown:
        report.error(line, section.label, f"the prompt uses unknown placeholder(s) {', '.join('{' + n + '}' for n in unknown)}; "
                                          "the placeholders are {task_prompt}, {scenario} and {artifact_path}.")
    required = PLACEHOLDERS if skill else ("task_prompt", "scenario")
    for name in required:
        if name not in found:
            report.error(line, section.label, f"the {'skill' if skill else 'no-skill'} prompt must contain {{{name}}}.")
    if not skill:
        if "artifact_path" in found:
            report.error(line, section.label, "the no-skill prompt must not contain {artifact_path}; a baseline "
                                              "publishes nothing.")
        for match in sorted({m.group(0) for m in NO_SKILL_FORBIDDEN_RE.finditer(template)}, key=str.casefold):
            report.error(line, section.label, f'the no-skill prompt must not mention "{match}" ({FROZEN_PROMPTS_REF}).')
    machine = _machine_path(template)
    if machine:
        report.error(line, section.label, f"the prompt contains an absolute machine path ({machine}); prompts must "
                                          "not name machine paths.")


def policy_summary(result: PolicyCheck) -> list[str]:
    ready = (f"frozen in {result.frozen_in}" if result.frozen_in else
             f"changed after the freeze of {result.changed_after}" if result.changed_after else "ready to freeze")
    lines = [f"{POLICY_TARGET}: {result.errors} error(s), {result.todos} to do; "
             f"{state_text(result.errors, result.todos, ready)}."]
    values = result.values
    if result.record is not None:
        hosts = values.get("hosts", {})
        filled = sum(1 for entry in hosts.values() if all(entry.values()))
        prompts = sum(1 for key in ("skillPrompt", "baselinePrompt") if values.get(key))
        lines.append(f"  hosts filled: {filled} of {len(hosts)}; prompts accepted: {prompts} of 2; targets: "
                     f"{'accepted' if values.get('targets') else 'pending'}")
    return lines


def render_prompt(template: str, task: dict, scenario: dict) -> str:
    block = "\n".join([f"Description: {one_line(scenario['description'])}",
                       f"Entrypoints: {', '.join(scenario['entrypoints'])}",
                       f"Arguments: {' '.join(scenario['arguments']) or 'none'}"])
    values = {"task_prompt": task["prompt"], "scenario": block, "artifact_path": ARTIFACT_PATH}
    text = PROMPT_PLACEHOLDER_RE.sub(lambda match: values.get(match.group(1), match.group(0)), template)
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).rstrip("\n") + "\n"


def policy_record(world: World, result: PolicyCheck, source_rel: str, raw: bytes, campaign: str) -> dict:
    values = result.values
    targets = world.manifest.get("pilotTargets") or {}
    return {
        "format": "mlview-run-policy/1", "campaign": campaign,
        "source": {"path": source_rel, "sha256": er.sha256_bytes(raw), "reviewer": result.reviewer,
                   "date": result.date, "transcribedBy": result.transcribed_by or None},
        "hosts": {host: dict(values["hosts"][host]) for host in world.hosts},
        "environment": {"helperPython": values["helperPython"]},
        "budget": {"activeMinutes": values["activeMinutes"], "repairRounds": values["repairRounds"],
                   "infrastructureRetries": values["infrastructureRetries"]},
        "scoring": {"qualifiedClaims": values["qualifiedClaims"], "perHostTargets": values["perHostTargets"]},
        "conditions": {"baselineSessions": values["baselineSessions"],
                       "developmentAdjudicationBeforeStage1": values["developmentAdjudication"]},
        "targets": {key: targets.get(key) for key in er.PILOT_TARGET_KEYS},
        "privacy": {"publication": values["publication"]},
        "prompts": {"artifactPath": ARTIFACT_PATH,
                    "skillTemplateSha256": er.sha256_bytes(result.skill_template.encode("utf-8")),
                    "baselineTemplateSha256": er.sha256_bytes(result.baseline_template.encode("utf-8"))},
    }


# --------------------------------------------------------------------------------------------
# Development adjudication


@dataclass
class AdjudicationCheck:
    display: str
    report: Report
    record: er.Record | None = None
    review: str | None = None
    sections: list[dict] = field(default_factory=list)
    baselines: dict[str, str] = field(default_factory=dict)
    baselines_decided: int = 0
    confusion: dict[str, dict[tuple[str, str], int]] = field(default_factory=lambda: {"claims": {}, "usability": {}})

    @property
    def errors(self) -> int:
        return self.report.errors

    @property
    def todos(self) -> int:
        return self.report.todos

    @property
    def complete(self) -> bool:
        return self.record is not None and not self.errors and not self.todos and self.review == "complete"


def check_adjudication(world: World, raw: bytes, display: str) -> AdjudicationCheck:
    report = Report(display)
    record, problems = er.parse_record(raw, display)
    report.problems.extend(problems)
    result = AdjudicationCheck(display, report, record)
    if record is None:
        return result
    workflow_eval = _workflow_eval()
    _reviewer_header(report, record)
    command = f"{TEMPLATE_COMMAND} --show {ADJUDICATION_TARGET}"
    ledgers = adjudication_ledgers(world)
    expected = [(f"{task} / {host}".casefold(), None) for task, host, _rel in ledgers] + [("Baselines", None),
                                                                                          ("Task", None)]
    _missing_sections(report, record, expected, command)
    by_kind = {f"{task} / {host}".casefold(): (task, host, rel) for task, host, rel in ledgers}
    usability_set = set(getattr(workflow_eval, "USABILITY_QUESTIONS", USABILITY_ORDER))
    if usability_set != set(USABILITY_ORDER):
        report.error(record.header.line, "header", "tools/workflow_eval.py USABILITY_QUESTIONS changed; update "
                                                   "tools/workflow_decisions.py.")
    for section in record.sections:
        if section.kind in ("Task",):
            continue
        label = section.label
        if section.kind == "Baselines":
            _adjudicate_baselines(world, workflow_eval, report, section, result)
            continue
        if section.kind not in by_kind:
            report.error(section.line, label, f'unknown section "## {label}". Sections are the 12 "<task> / <host>" '
                                              "pairs, Baselines and Task.")
            continue
        task, host, rel = by_kind[section.kind]
        try:
            ledger, ledger_raw = _development_json(world, rel)
        except (OSError, ValueError) as exc:
            report.error(section.line, label, f"cannot read {rel}: {exc}")
            continue
        ledger_line = _ledger_line(report, section, rel, ledger_raw)
        try:
            workflow_eval.validate_development_review(ledger, world.root)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            report.error(ledger_line, label, f"{rel} does not validate: {exc}")
        provisional = {claim["id"]: ("claims", claim["verdict"]) for claim in ledger.get("claims") or []}
        for question in USABILITY_ORDER:
            status = (ledger.get("usability") or {}).get(question, {}).get("status")
            provisional[f"usability.{question}"] = ("usability", status)
        stats = {"label": label, "claims": 0, "claimsTotal": sum(1 for v in provisional.values() if v[0] == "claims"),
                 "usability": 0, "agree": 0}
        seen: set[str] = set()
        folded = {key.casefold(): key for key in provisional}
        for line in section.lines:
            if line.key.casefold() == "ledger":
                continue
            key = folded.get(line.key.casefold())
            if key is None:
                report.error(line.line, label, f'"{line.key}" is not a claim of {rel} or a usability question.')
                continue
            seen.add(key)
            group, prior = provisional[key]
            vocab = set(workflow_eval.REVIEW_VERDICTS) if group == "claims" else set(USABILITY_VERDICTS)
            verdict = _adjudicated(report, line, label, key, vocab, prior)
            if verdict is None:
                continue
            stats[group] += 1
            stats["agree"] += int(verdict == prior)
            cell = (prior, verdict)
            result.confusion[group][cell] = result.confusion[group].get(cell, 0) + 1
        for key in provisional:
            if key not in seen:
                report.error(section.line, label, f"{key} is missing; restore its line from the template ({command}).")
        result.sections.append(stats)
    result.review = _task_section(report, record, closing="every verdict above is final")
    return result


def _ledger_line(report: Report, section: er.Section, rel: str, raw: bytes) -> int:
    found = next((line for line in section.lines if line.key.casefold() == "ledger"), None)
    if found is None or " ".join(found.value.split()) != f"{rel} {er.sha256_bytes(raw)}":
        report.error(found.line if found else section.line, section.label,
                     f"the Ledger line does not match {rel} (ledgers are immutable); restore the line the tool wrote.")
    return found.line if found else section.line


def _adjudicated(report: Report, line: er.Field, label: str, key: str, vocab: set[str], prior: str | None,
                 *, reason_always: bool = False) -> str | None:
    value = line.value.strip()
    if value.casefold() in ("", _PENDING):
        report.todo(line.line, label, f"{key} is still pending.")
        return None
    try:
        verdict, pointers, reason = er.parse_verdict(value, vocab)
    except ValueError as exc:
        report.error(line.line, label, f"{key}: {exc}")
        return None
    if pointers:
        report.error(line.line, label, f'{key}: write the verdict and an optional {REASON_HINT}; '
                                       f'"{" ".join(pointers)}" is not expected.')
        return None
    if reason_always and verdict != prior and not reason:
        report.error(line.line, label, f'"{key}: {verdict}" needs a reason; add {REASON_HINT}.')
        return None
    if not reason_always and verdict != prior and not reason:
        report.error(line.line, label,
                     f'"{key}: {verdict}" differs from the provisional "{prior}"; add {REASON_HINT}.')
        return None
    return verdict


def _adjudicate_baselines(world: World, workflow_eval, report: Report, section: er.Section,
                          result: AdjudicationCheck) -> None:
    rel = "native-reviews/baselines.json"
    try:
        value, raw = _development_json(world, rel)
    except (OSError, ValueError) as exc:
        report.error(section.line, section.label, f"cannot read {rel}: {exc}")
        return
    ledger_line = _ledger_line(report, section, rel, raw)
    try:
        workflow_eval.validate_baselines(value, world.manifest, world.root)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report.error(ledger_line, section.label, f"{rel} does not validate: {exc}")
    hosts = {host.casefold(): host for host in world.hosts}
    seen: set[str] = set()
    for line in section.lines:
        if line.key.casefold() == "ledger":
            continue
        host = hosts.get(line.key.casefold())
        if host is None:
            report.error(line.line, section.label, f'"{line.key}" is not a host with a baseline note '
                                                   f'({", ".join(world.hosts)}).')
            continue
        seen.add(host)
        verdict = _adjudicated(report, line, section.label, host, set(BASELINE_VERDICTS), "confirmed",
                               reason_always=True)
        if verdict is not None:
            result.baselines[host] = verdict
            result.baselines_decided += 1
    for host in world.hosts:
        if host not in seen:
            report.error(section.line, section.label, f"{host} is missing; restore its line from the template "
                                                      f"({TEMPLATE_COMMAND} --show {ADJUDICATION_TARGET}).")


def adjudication_summary(result: AdjudicationCheck) -> list[str]:
    lines = [f"{ADJUDICATION_TARGET}: {result.errors} error(s), {result.todos} to do; "
             f"{state_text(result.errors, result.todos, 'complete')}."]
    for stats in result.sections:
        if stats["claims"] or stats["usability"]:
            verb = "agrees" if stats["agree"] == 1 else "agree"
            lines.append(f"  {stats['label']}: {stats['claims']} of {stats['claimsTotal']} claims, {stats['usability']} "
                         f"of {len(USABILITY_ORDER)} usability decided; {stats['agree']} {verb} with the provisional label.")
    if result.baselines_decided:
        lines.append(f"  baselines: {result.baselines_decided} decided")
    if result.complete:
        lines.append("  Development evidence; not a held-out pilot result.")
        workflow_eval = _workflow_eval()
        claim_order = [v for v in ("supported", "qualified", "unsupported", "omitted") if v in workflow_eval.REVIEW_VERDICTS]
        for group, order in (("claims", claim_order), ("usability", list(USABILITY_VERDICTS))):
            lines.append(f"  {group} (rows: provisional, columns: human)")
            width = max(len(name) for name in order) + 2
            lines.append("    " + " " * width + "".join(f"{name:>{width}}" for name in order))
            for prior in order:
                row = "".join(f"{result.confusion[group].get((prior, human), 0):>{width}}" for human in order)
                lines.append(f"    {prior:<{width}}{row}")
        lines.append("  baselines: " + "; ".join(f"{host} {verdict}" for host, verdict in result.baselines.items()))
    return lines


# --------------------------------------------------------------------------------------------
# The check command


def _sibling(name: str, *, required: bool = False):
    path = TOOLS / f"{name}.py"
    loaded = sys.modules.get(name)
    if loaded is not None and Path(getattr(loaded, "__file__", "") or "").resolve() == path.resolve():
        return loaded
    if not path.is_file():
        if required:
            raise UsageError(f"tools/{name}.py is missing")
        return None
    return importlib.import_module(name)


def decision_files(world: World) -> list[Path]:
    if not world.decisions_dir.is_dir():
        return []
    return sorted(path for path in world.decisions_dir.glob("*.md") if path.name != "README.md" and path.is_file())


def resolve_target(world: World, target: str) -> Path:
    if world.heldout_task(target) is not None or target in (POLICY_TARGET, ADJUDICATION_TARGET):
        path = world.decisions_dir / f"{target}.md"
        if not path.is_file():
            hint = f"{TEMPLATE_COMMAND} {target}"
            raise UsageError(f"{world.display(path)} does not exist; create it with {hint}")
        return path
    path = Path(target)
    if path.is_file():
        return path
    raise UsageError(f"{target} is not a held-out task ID, {POLICY_TARGET}, {ADJUDICATION_TARGET} or an existing file")


def _expected_name(world: World, path: Path, second: bool) -> str | None:
    try:
        inside = path.resolve().parent == world.decisions_dir.resolve()
    except OSError:
        inside = False
    if not inside:
        return None
    suffix = ".second.md" if second else ".md"
    return path.name[:-len(suffix)] if path.name.endswith(suffix) else None


def _fold_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def current_freeze(world: World) -> tuple[str, dict] | None:
    """(campaign, freeze.json) of the campaign that tasks.json's pilotFreeze names, or None."""
    pointer = world.manifest.get("pilotFreeze")
    campaign = pointer.get("campaign") if isinstance(pointer, dict) else None
    if not isinstance(campaign, str) or not er.NAME_RE.fullmatch(campaign):
        return None
    try:
        value = json.loads((world.root / PILOT_REL / campaign / "freeze.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return (campaign, value) if isinstance(value, dict) else None


def read_decision_files(world: World) -> list[str]:
    """The decision files a freeze of the current tasks.json would record in decisionFiles: each
    held-out task's file and existing second review, and the run policy (when they exist)."""
    rels = []
    for task in world.heldout:
        for name in (f"{task['id']}.md", f"{task['id']}.second.md"):
            if (world.root / DECISIONS_REL / name).is_file():
                rels.append(f"{DECISIONS_REL}/{name}")
    if (world.root / DECISIONS_REL / f"{POLICY_TARGET}.md").is_file():
        rels.append(f"{DECISIONS_REL}/{POLICY_TARGET}.md")
    return rels


def _added_after_freeze(world: World, path: Path, report: Report) -> str | None:
    """The current campaign when ``path`` is a decision file its freeze would read now but did not
    record (for example a second review written after the freeze), with a NOTE; otherwise None."""
    frozen = current_freeze(world)
    files = frozen[1].get("decisionFiles") if frozen is not None else None
    display = world.display(path)
    if not isinstance(files, dict) or display in files or display not in read_decision_files(world):
        return None
    report.note(1, "header", f"this file was added after the freeze of {frozen[0]}, which did not include it; a "
                             f"changed decision needs a new campaign ({FREEZE_README}).")
    return frozen[0]


def restore_advice(world: World, rel: str, digest: str, campaign: str, history: "History | None" = None) -> str:
    """How to bring back the bytes ``rel`` was frozen with (sha256 ``digest``), taken from where Git
    holds exactly those bytes: the index (``git checkout -- <rel>``) or a commit (``git checkout
    <commit> -- <rel>``). When Git holds them nowhere (the freeze is not committed yet, or the file
    was committed apart from it), no git command is offered, so following the advice never replaces
    the file with other bytes such as the pending template committed before the freeze."""
    history = history if history is not None else History(world)
    if history.root is not None or history.incomplete:
        try:
            staged = er._git(world.root, "cat-file", "blob", f":{rel}")
        except ValueError:
            staged = None
        if staged is not None and er.sha256_bytes(staged) == digest:
            return f"git checkout -- {rel}"
    if history.full:
        versions = history.versions(rel)
        for oid, commit in (versions.versions.items() if versions is not None else ()):
            data = history.blob(oid)
            if data is not None and er.sha256_bytes(data) == digest:
                return f"git checkout {commit[:12]} -- {rel}"
        freeze = history.versions(f"{PILOT_REL}/{campaign}/freeze.json")
        if versions is not None and freeze is not None:
            if not freeze.committed:
                return (f"no git command: Git does not hold these bytes because the freeze of {campaign} is not committed "
                        f"yet. Undo the edit in your editor; if you cannot, delete {PILOT_REL}/{campaign}/, restore the "
                        f"pre-freeze {TASKS_REL} (git checkout HEAD -- {TASKS_REL}) and freeze again")
            return (f"no git command: Git does not hold these bytes ({rel} was not committed with the freeze of "
                    f"{campaign}). Undo the edit in your editor")
    if history.incomplete:
        return (f"no git command here: the index does not hold these bytes and this clone lacks the full history "
                f"({history.reason}). Fetch it so check-frozen can name the commit that holds them, or undo the edit in "
                "your editor")
    return f"no git command: {history.reason or 'Git cannot read the history of ' + rel}. Undo the edit in your editor"


def _frozen_state(world: World, path: Path, digest: str, report: Report) -> str | None:
    """The campaign that froze ``path`` with exactly these bytes; a NOTE when it froze other bytes."""
    frozen = current_freeze(world)
    files = frozen[1].get("decisionFiles") if frozen is not None else None
    if not isinstance(files, dict):
        return None
    recorded = files.get(world.display(path))
    if not isinstance(recorded, str):
        return None
    if recorded == digest:
        return frozen[0]
    advice = restore_advice(world, world.display(path), recorded, frozen[0])
    report.note(1, "header", f"this file was frozen in {frozen[0]} (sha256 {recorded[:12]}...) and has changed since. "
                             f"If you did not mean to change a decision, restore the frozen bytes ({advice}): frozen "
                             'decision files are compared byte for byte, including ">" lines and line endings. A '
                             f"changed decision needs a new campaign ({FREEZE_README}).")
    return None


def _changed_after(world: World, path: Path, digest: str) -> str | None:
    """The current campaign when its freeze.json lists ``path`` with other bytes."""
    frozen = current_freeze(world)
    files = frozen[1].get("decisionFiles") if frozen is not None else None
    recorded = files.get(world.display(path)) if isinstance(files, dict) else None
    return frozen[0] if isinstance(recorded, str) and recorded != digest else None


def title_kind(raw: bytes) -> str | None:
    record, _problems = er.parse_record(raw, "-")
    return record.kind if record is not None else None


@dataclass
class FileCheck:
    display: str
    problems: list[er.Problem]
    summary: list[str]
    errors: int
    todos: int
    result: object = None


def _late_review_notes(world: World, checks: list[FileCheck]) -> list[FileCheck]:
    """For the check command only: a primary file frozen with unchanged bytes is still the frozen
    version when its second review was added after the freeze, changed after it, or removed. The
    to-dos and errors that this causes in the primary (its Disagreements lines and the "Review is
    complete" error) become NOTEs for a new campaign, and a header NOTE names the second-review file
    to remove or restore, so the owner is never told to edit a frozen file (freeze and check-frozen
    keep the strict result)."""
    primary = checks[0].result if checks else None
    second = checks[1].result if len(checks) > 1 else None
    if not isinstance(primary, RefCheck) or not primary.frozen_in or primary.task_id is None:
        return checks
    campaign = primary.frozen_in
    rel = world.display(world.decisions_dir / f"{primary.task_id}.second.md")
    frozen = current_freeze(world)
    files = frozen[1].get("decisionFiles") if frozen is not None and frozen[0] == campaign else None
    recorded = files.get(rel) if isinstance(files, dict) else None
    if isinstance(second, RefCheck) and second.added_after == campaign:
        prefix = f"for a new campaign ({rel} was added after the freeze of {campaign}): "
        keep = f"remove {rel} (or keep it out of the repository)"
        strict = False  # the primary had no second review, so none of its Disagreements lines are affected
    elif isinstance(second, RefCheck) and second.changed_after == campaign and isinstance(recorded, str):
        prefix = f"for a new campaign ({rel} changed after the freeze of {campaign}): "
        keep = f"restore the frozen {rel} ({restore_advice(world, rel, recorded, campaign)})"
        strict = True
    elif second is None and isinstance(recorded, str) and not (world.root / rel).is_file():
        prefix = f"for a new campaign ({rel}, frozen in {campaign}, is missing): "
        keep = f"restore {rel} ({restore_advice(world, rel, recorded, campaign)})"
        strict = True
    else:
        return checks
    problems = []
    for problem in checks[0].problems:
        disagreement = problem.section == "Disagreements" and (problem.level == er.TODO
                                                               or (strict and problem.level == er.ERROR))
        caused = disagreement or (problem.level == er.ERROR and problem.section == "Task"
                                  and "item(s) above are still to do" in problem.message)
        problems.append(problem._replace(level=er.NOTE, message=prefix + problem.message) if caused else problem)
    problems.append(er.Problem(checks[0].display, 1, er.NOTE, "header",
                               f"this file is still the version frozen in {campaign}. To keep {campaign}, {keep}; "
                               f"resolving the second review's changes needs a new campaign ({FREEZE_README})."))
    problems.sort(key=lambda problem: (problem.line, LEVEL_ORDER.get(problem.level, 9)))
    errors = sum(problem.level == er.ERROR for problem in problems)
    todos = sum(problem.level == er.TODO for problem in problems)
    summary = [f"{primary.name}: {errors} error(s), {todos} to do; "
               f"{state_text(errors, todos, f'frozen in {campaign}')}."] + checks[0].summary[1:]
    return [FileCheck(checks[0].display, problems, summary, errors, todos, primary)] + checks[1:]


def check_path(world: World, path: Path, *, with_second: bool = True) -> list[FileCheck]:
    """Check one file (a primary file also checks its second review, when present)."""
    path = Path(path)
    raw = path.read_bytes()
    display = world.display(path)
    kind = title_kind(raw)
    if kind == "Reference decisions":
        second_check = None
        checks: list[FileCheck] = []
        second_path = path.with_name(path.name[:-3] + ".second.md") if path.name.endswith(".md") else None
        usable = None
        if with_second and second_path is not None and second_path.is_file():
            second_raw = second_path.read_bytes()
            second_check = check_reference(world, second_raw, world.display(second_path),
                                           expected_name=_expected_name(world, second_path, True))
            primary_record, _problems = er.parse_record(raw, display)
            ident = primary_record.ident if primary_record is not None else None
            if second_check.record is not None and (second_check.role != "second" or second_check.task_id != ident):
                second_check.report.error(second_check.record.header.line, "header",
                                          f'a second review must start with "# Second review: {ident}".')
            elif second_check.record is not None:
                usable = second_check
        result = check_reference(world, raw, display, second=usable, expected_name=_expected_name(world, path, False))
        if usable is not None and result.reviewer and usable.reviewer \
                and _fold_name(result.reviewer) == _fold_name(usable.reviewer):
            usable.report.error(_field_line(usable.record.header, "Reviewer"), "header",
                                "a second review must be written by a different person than the primary reviewer "
                                f'(both files name "{usable.reviewer}").')
        if result.record is not None:
            result.frozen_in = _frozen_state(world, path, result.record.sha256, result.report)
            result.changed_after = _changed_after(world, path, result.record.sha256)
            result.added_after = _added_after_freeze(world, path, result.report)
        checks.append(FileCheck(display, result.report.ordered(), reference_summary(world, result), result.errors,
                                result.todos, result))
        if second_check is not None:
            if second_check.record is not None:
                second_check.frozen_in = _frozen_state(world, second_path, second_check.record.sha256,
                                                       second_check.report)
                second_check.changed_after = _changed_after(world, second_path, second_check.record.sha256)
                second_check.added_after = _added_after_freeze(world, second_path, second_check.report)
            checks.append(FileCheck(second_check.display, second_check.report.ordered(),
                                    reference_summary(world, second_check), second_check.errors, second_check.todos,
                                    second_check))
        return checks
    if kind == "Second review":
        result = check_reference(world, raw, display, expected_name=_expected_name(world, path, True))
        if result.record is not None:
            result.frozen_in = _frozen_state(world, path, result.record.sha256, result.report)
            result.changed_after = _changed_after(world, path, result.record.sha256)
            result.added_after = _added_after_freeze(world, path, result.report)
        return [FileCheck(display, result.report.ordered(), reference_summary(world, result), result.errors,
                          result.todos, result)]
    if kind == "Pilot run policy":
        result = check_policy(world, raw, display)
        if result.record is not None:
            result.frozen_in = _frozen_state(world, path, result.record.sha256, result.report)
            result.changed_after = _changed_after(world, path, result.record.sha256)
        return [FileCheck(display, result.report.ordered(), policy_summary(result), result.errors, result.todos, result)]
    if kind == "Development adjudication":
        result = check_adjudication(world, raw, display)
        return [FileCheck(display, result.report.ordered(), adjudication_summary(result), result.errors, result.todos,
                          result)]
    if kind in ("Session", "Run review"):
        pilot = _sibling("workflow_pilot")
        if pilot is None or not callable(getattr(pilot, "check_file", None)):
            problem = er.Problem(display, 1, er.ERROR, "header", f"{kind} files are checked by tools/workflow_pilot.py, "
                                                                 "which is not available in this build.")
            return [FileCheck(display, [problem], [f"{path.name}: 1 error(s), 0 to do; not ready (fix the errors)."], 1, 0)]
        problems = sorted(pilot.check_file(path, root=world.root), key=lambda p: (p.line, LEVEL_ORDER.get(p.level, 9)))
        errors = sum(1 for p in problems if p.level == er.ERROR)
        todos = sum(1 for p in problems if p.level == er.TODO)
        return [FileCheck(display, problems, [f"{path.name}: {errors} error(s), {todos} to do; "
                                              f"{state_text(errors, todos, 'complete')}."], errors, todos)]
    record, problems = er.parse_record(raw, display)
    if record is not None:  # a known title without a checker here (for example an invalidation record)
        problems = problems + [er.Problem(display, record.header.line, er.ERROR, "header",
                                          f'"# {record.kind}" files are not checked by this command.')]
    errors = sum(1 for p in problems if p.level == er.ERROR)
    return [FileCheck(display, problems, [f"{path.name}: {errors} error(s), 0 to do; not ready (fix the errors)."],
                      errors, 0)]


def show_prompts(world: World, policy: PolicyCheck) -> tuple[list[str], int]:
    """All 16 renderings, with each task's decided scenario or its proposal, and leak findings."""
    lines: list[str] = []
    findings = 0
    leak_texts = _leak_texts(world, {})
    for task in world.heldout:
        scenario, status = _effective_scenario(world, task["id"])
        for folder, template in (("skill", policy.skill_template), ("baseline", policy.baseline_template)):
            rel = f"prompts/{folder}/{task['id']}.txt"
            if template is None:
                lines.append(f"===== {rel}: no template (restore the fenced block) =====")
                continue
            text = render_prompt(template, task, scenario)
            lines.append(f"===== {rel} (scenario: {status}) =====")
            lines.extend(text.rstrip("\n").split("\n"))
            for problem in _prompt_findings(rel, text, leak_texts):
                findings += 1
                lines.append(f"LEAK  {problem}")
    lines.append(f"{2 * len(world.heldout)} prompts rendered; {findings} leak finding(s).")
    return lines, findings


def _effective_scenario(world: World, task_id: str) -> tuple[dict, str]:
    ledger, _raw = world.ledger(task_id)
    proposal = {"description": ledger["scenario"]["description"], "entrypoints": list(ledger["scenario"]["entrypoints"]),
                "arguments": list(ledger["scenario"]["arguments"])}
    path = world.decisions_dir / f"{task_id}.md"
    if not path.is_file():
        return proposal, "proposal; the decisions file does not exist"
    result = check_reference(world, path.read_bytes(), world.display(path))
    if result.scenario is None:
        return proposal, "proposal; the scenario decision is still pending"
    if any(problem.level == er.ERROR and problem.section == "Scenario" for problem in result.report.problems):
        return proposal, "proposal; the scenario decision has errors"
    return result.scenario, "accepted" if result.scenario["decision"] == "accept" else "replaced"


def _normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


def _leak_texts(world: World, frozen: dict[str, dict]) -> list[tuple[str, str]]:
    """(label, normalised text) of every candidate and frozen reference text of 30+ characters."""
    texts: list[tuple[str, str]] = []
    for task in world.heldout:
        ledger, _raw = world.ledger(task["id"])
        for fact in ledger.get("facts") or []:
            texts.append((fact["id"], fact["claim"]))
        texts.extend(zip(unknown_ids(task["id"], ledger), ledger.get("unknowns") or []))
        texts.extend(zip(nondefect_ids(task["id"], ledger), ledger.get("nonDefects") or []))
    for reference in frozen.values():
        texts.extend((item["id"], item["claim"]) for item in reference["facts"])
        texts.extend((item["id"], item["text"]) for item in reference["knownUnresolved"])
        texts.extend((item["id"], item["text"]) for item in reference["nonDefects"])
        texts.extend((item["id"], item["text"]) for item in reference["defects"])
    out, seen = [], set()
    for label, text in texts:
        normal = _normalise(text or "")
        if len(normal) >= LEAK_MINIMUM and (label, normal) not in seen:
            seen.add((label, normal))
            out.append((label, normal))
    return out


def _prompt_findings(rel: str, text: str, leak_texts: list[tuple[str, str]]) -> list[str]:
    problems = []
    normal = _normalise(text)
    for label, reference in leak_texts:
        if reference in normal:
            problems.append(f"{rel} contains the reference text of {label} (reference leakage); change the scenario "
                            "or the prompt template.")
    machine = _machine_path(text)
    if machine:
        problems.append(f"{rel} contains an absolute machine path ({machine}).")
    return problems


def command_check(world: World, targets: Sequence[str], *, show: bool, out) -> int:
    if targets:
        paths = [resolve_target(world, target) for target in targets]
        with_second = True
    else:
        paths = decision_files(world)
        if not paths:
            raise UsageError(f"{world.display(world.decisions_dir)} has no decision files; create them with "
                             f"{TEMPLATE_COMMAND} --init-all")
        primaries = {path.name[:-3] for path in paths if not path.name.endswith(".second.md")}
        paths = [path for path in paths if not (path.name.endswith(".second.md")
                                                and path.name[:-len(".second.md")] in primaries)]
        with_second = True
    errors = 0
    first = True
    for path in paths:
        for check in _late_review_notes(world, check_path(world, path, with_second=with_second)):
            if not first:
                print("", file=out)
            first = False
            for problem in check.problems:
                print(str(problem), file=out)
            for line in check.summary:
                print(line, file=out)
            errors += check.errors
            if show and isinstance(check.result, PolicyCheck):
                rendered, _findings = show_prompts(world, check.result)
                print("", file=out)
                for line in rendered:
                    print(line, file=out)
    if show and not any(title_kind(Path(p).read_bytes()) == "Pilot run policy" for p in paths):
        print("--show-prompts applies to the run policy; check run-policy --show-prompts", file=out)
    return 1 if errors else 0


# --------------------------------------------------------------------------------------------
# Context sheet


def context_sheet(world: World, task_id: str) -> tuple[str, int, int, list[str]]:
    """(markdown, facts, anchors, mismatches) of the local review-context sheet of one task."""
    task = world.heldout_task(task_id)
    if task is None:
        raise UsageError(f"{task_id} is not a held-out task in {TASKS_REL}")
    if world.repo_dir(task) is None:
        raise UsageError(f"the corpus checkout of {task.get('repository')} is absent; set MLVIEW_PUBLIC_CORPUS_DIR or "
                         "run python tools/fetch_workflow_repos.py")
    ledger, _raw = world.ledger(task_id)
    repo = world.repo_entry(task) or {}
    lines = [f"# Review context: {task_id}", "",
             f"> Local review aid written by python tools/workflow_eval.py context {task_id}. It is derived from the "
             "candidate ledger and the pinned source, gitignored, and may be rewritten; never commit it.",
             f"> Source: {task.get('repository')} ({task.get('url')}) at {task.get('commit')}; license: "
             f"{repo.get('license', 'see THIRD_PARTY_NOTICES.md')}.",
             "> The excerpts below are third-party source shown for review only (THIRD_PARTY_NOTICES.md). The sheet "
             "shows source; it does not judge any claim.", "",
             "## Scenario (proposed)",
             f"Description: {one_line(ledger['scenario']['description'])}",
             f"Entrypoints: {'; '.join(ledger['scenario']['entrypoints'])}",
             f"Arguments: {'; '.join(ledger['scenario']['arguments']) or 'none'}", ""]
    mismatches: list[str] = []
    anchors = 0
    for fact in ledger["facts"]:
        lines += [f"## Fact {fact['id']}", f"Claim: {one_line(fact['claim'])}",
                  f"Basis: {fact['basis']}. Essential: {_yes_no(fact['essential'])}.", ""]
        for anchor in fact["anchors"]:
            anchors += 1
            locator = _locator(anchor)
            try:
                data = world.pinned(task, anchor["file"])
                source = er.source_lines(data, anchor.get("cell"), world.helper)
            except ValueError as exc:
                mismatches.append(f"{anchor['id']} ({locator}): {exc}")
                lines += [f"### Anchor {anchor['id']}: {locator} (CANNOT READ: {exc})", ""]
                continue
            verified = er.quote_matches(anchor.get("quote"), source, anchor["line"], anchor["endLine"], world.helper)
            if not verified:
                mismatches.append(f"{anchor['id']} ({locator}): the candidate quote differs from the pinned bytes")
            status = "quote verified against the pinned bytes" if verified else "QUOTE MISMATCH against the pinned bytes"
            lines += [f"### Anchor {anchor['id']}: {locator} ({status})", *_numbered(source, anchor["line"],
                                                                                     anchor["endLine"]), ""]
    lines.append("## Unknowns and non-defects (proposed)")
    for ident, text in zip(unknown_ids(task_id, ledger), ledger["unknowns"]):
        lines.append(f"- {ident}: {one_line(text)}")
    for ident, text in zip(nondefect_ids(task_id, ledger), ledger["nonDefects"]):
        lines.append(f"- {ident}: {one_line(text)}")
    lines.append("")
    return "\n".join(lines), len(ledger["facts"]), anchors, mismatches


def _numbered(source: list[str], start: int, end: int, margin: int = 5) -> list[str]:
    count = er.human_line_count(source)
    first, last = max(1, start - margin), min(count, end + margin)
    body = source[first - 1:last]
    longest = max((len(run) for text in body for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    width = len(str(last))
    out = [f"{fence}text"]
    for number in range(first, last + 1):
        marker = ">" if start <= number <= end else " "
        out.append(f"{marker} {number:>{width}} | {source[number - 1]}")
    out.append(fence)
    return out


# --------------------------------------------------------------------------------------------
# Freeze


@dataclass
class Campaign:
    """A derived campaign: campaign-relative files, the new tasks.json and what went wrong."""

    name: str
    files: dict[str, bytes] = field(default_factory=dict)
    tasks_after: bytes | None = None
    problems: list[tuple[str, str]] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    policy: PolicyCheck | None = None
    leak_findings: int = 0
    notes: list[str] = field(default_factory=list)
    revision: str | None = None

    def fail(self, what: str, action: str) -> None:
        self.problems.append((what, action))


def _heldout_projection(manifest: dict) -> dict:
    return {"hosts": manifest.get("hosts"), "repetitions": manifest.get("repetitions"),
            "pilotTargets": manifest.get("pilotTargets"),
            "tasks": [{key: task.get(key) for key in ("id", "repository", "url", "commit", "entrypoints", "prompt")}
                      for task in manifest.get("tasks") or [] if task.get("split") == "heldout"]}


def _canonical_manifest(value: dict) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def _tooling() -> dict[str, str]:
    return {rel: er.sha256_file(ROOT / rel) for rel in TOOLING_FILES}


def _verify_corpus(world: World, task: dict) -> str | None:
    """None when fetch_workflow_repos.verify_repo accepts the task's checkout, else why not."""
    fetcher = _sibling("fetch_workflow_repos")
    verify = getattr(fetcher, "verify_repo", None) if fetcher is not None else None
    if not callable(verify):
        return "corpus verification is not available in this build (tools/fetch_workflow_repos.py has no verify_repo)"
    repo = world.repo_entry(task)
    if repo is None:
        return f"{task.get('repository')} is not listed in {REPOSITORIES_REL}"
    try:
        report = verify(repo, world.corpus)
    except Exception as exc:  # noqa: BLE001 - any failure of the verifier refuses the freeze
        return f"verify_repo failed: {exc}"
    if not isinstance(report, dict) or report.get("ok") is not True:
        sentences = report.get("problems") if isinstance(report, dict) else None
        if isinstance(sentences, list) and sentences and all(isinstance(item, str) for item in sentences):
            return "the checkout failed verification (" + "; ".join(sentences) + ")"
        details = []
        if isinstance(report, dict):
            for key in ("head", "clean", "sparseMatches", "missing", "extraMaterialized", "blobMismatches"):
                if key in report and report[key] not in (True, [], None) and key != "head":
                    details.append(f"{key}: {report[key]}")
        return "the checkout failed verification" + (f" ({'; '.join(details)})" if details else "")
    return None


def corpus_remedy(problem: str, repository: object) -> str:
    """The next command for a failed corpus verification."""
    if "--update-sparse" in problem:
        return (f"python tools/fetch_workflow_repos.py --update-sparse --repo {repository}, then "
                "python tools/fetch_workflow_repos.py --verify")
    return "python tools/fetch_workflow_repos.py --verify"


def derive_campaign(world: World, campaign: str, *, frozen_at: str, tooling: dict | None = None,
                    supersedes: dict | None = None, existing: dict | None = None, verify_corpus: bool = True) -> Campaign:
    """Derive every frozen file of ``campaign`` from the owner files, ledgers and manifests.

    ``existing`` (check-frozen) is the committed freeze.json: its tasksManifest.sha256 and
    developmentAdjudication are reused, and when the corpus is absent the committed
    sourceFiles hashes stand in for the pinned bytes.
    """
    result = Campaign(campaign)
    manifest = world.manifest
    existing_refs: dict[str, dict] = {}
    if existing is not None:
        for task in world.heldout:
            path = world.root / PILOT_REL / campaign / "reference" / f"{task['id']}.json"
            try:
                existing_refs[task["id"]] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                existing_refs[task["id"]] = {}
    references: dict[str, dict] = {}
    decision_hashes: dict[str, str] = {}
    candidate_hashes: dict[str, str] = {}
    corpus_missing = verify_corpus and world.corpus is None
    if corpus_missing:
        result.fail("the corpus is absent; the freeze needs every pinned repository",
                    "set MLVIEW_PUBLIC_CORPUS_DIR or run python tools/fetch_workflow_repos.py")
    for task in world.heldout:
        task_id = task["id"]
        rel = f"{DECISIONS_REL}/{task_id}.md"
        path = world.root / rel
        if not path.is_file():
            result.fail(f"{rel} does not exist", f"{TEMPLATE_COMMAND} {task_id}")
            continue
        checks = check_path(world, path)
        primary = checks[0].result
        assert isinstance(primary, RefCheck)
        for check in checks:
            if check.errors or check.todos or not getattr(check.result, "ready", False):
                result.fail(f"{check.display}: {check.errors} error(s), {check.todos} to do"
                            + ("" if check.errors or check.todos else ', "Review: complete" missing'),
                            f"{CHECK_COMMAND} {task_id}")
        if not primary.ready or (primary.second is not None and not primary.second.ready):
            continue
        decision_hashes[rel] = primary.record.sha256
        reviews = [_review_entry(rel, primary)]
        if primary.second is not None:
            second_rel = f"{DECISIONS_REL}/{task_id}.second.md"
            decision_hashes[second_rel] = primary.second.record.sha256
            reviews.append(_review_entry(second_rel, primary.second))
        ledger, ledger_raw = world.ledger(task_id)
        candidate_hashes[f"{CANDIDATES_REL}/{task_id}.json"] = er.sha256_bytes(ledger_raw)
        reference = _reference(world, task, campaign, primary, reviews, ledger, ledger_raw)
        if corpus_missing:
            continue
        sources = _source_files(world, task, reference, ledger, result, existing_refs.get(task_id))
        if sources is None:
            continue
        reference["sourceFiles"] = sources
        references[task_id] = reference
    policy_rel = f"{DECISIONS_REL}/{POLICY_TARGET}.md"
    policy_path = world.root / policy_rel
    policy = None
    if not policy_path.is_file():
        result.fail(f"{policy_rel} does not exist", f"{TEMPLATE_COMMAND} {POLICY_TARGET}")
    else:
        policy_raw = policy_path.read_bytes()
        policy = check_policy(world, policy_raw, policy_rel)
        result.policy = policy
        if not policy.ready:
            result.fail(f"{policy_rel}: {policy.errors} error(s), {policy.todos} to do"
                        + ("" if policy.errors or policy.todos else ', "Review: complete" missing'),
                        f"{CHECK_COMMAND} {POLICY_TARGET}")
        else:
            decision_hashes[policy_rel] = policy.record.sha256
    if verify_corpus and not corpus_missing:
        for task in world.heldout:
            problem = _verify_corpus(world, task)
            if problem:
                result.fail(f"{task.get('repository')}: {problem}", corpus_remedy(problem, task.get("repository")))
    if result.problems or policy is None or not policy.ready:
        return result
    # Prompts, leak and machine-path checks.
    leak_texts = _leak_texts(world, references)
    prompts: dict[str, bytes] = {}
    for task in world.heldout:
        scenario = references[task["id"]]["scenario"]
        for folder, template in (("skill", policy.skill_template), ("baseline", policy.baseline_template)):
            rel = f"prompts/{folder}/{task['id']}.txt"
            text = render_prompt(template, task, scenario)
            for problem in _prompt_findings(rel, text, leak_texts):
                result.leak_findings += 1
                result.fail(problem, "edit the scenario in the task's decisions file or the prompt template")
            prompts[rel] = text.encode("utf-8")
    if result.problems:
        return result
    files: dict[str, bytes] = {}
    for task in world.heldout:
        files[f"reference/{task['id']}.json"] = er.canonical_json(references[task["id"]])
    reference_set = {
        "format": "mlview-reference-set/1", "campaign": campaign, "frozenAt": frozen_at,
        "tasks": [{"task": task["id"], "path": f"reference/{task['id']}.json",
                   "sha256": er.sha256_bytes(files[f"reference/{task['id']}.json"]),
                   "essential": references[task["id"]]["counts"]["essential"],
                   "runsMustState": references[task["id"]]["counts"]["runsMustState"]} for task in world.heldout],
        "totals": {key: sum(references[task["id"]]["counts"][key] for task in world.heldout)
                   for key in ("facts", "essential", "runsMustState", "nonDefects", "defects")} | {
                       "tasks": len(world.heldout)},
        "note": NOTE_TEXT,
    }
    files["reference-set.json"] = er.canonical_json(reference_set)
    revision = "sha256:" + er.sha256_bytes(files["reference-set.json"])
    result.revision = revision
    files["policy.json"] = er.canonical_json(policy_record(world, policy, policy_rel, policy_path.read_bytes(), campaign))
    files.update(prompts)
    after = copy.deepcopy(manifest)
    for task in after.get("tasks") or []:
        if task.get("split") == "heldout":
            task["referenceStatus"] = "frozen"
    after.pop("pilotFreeze", None)
    after["pilotFreeze"] = {"campaign": campaign, "freeze": f"pilot/{campaign}/freeze.json", "referenceRevision": revision}
    result.tasks_after = _canonical_manifest(after)
    adjudication = _adjudication_binding(world)
    tasks_sha = er.sha256_bytes(result.tasks_after)
    if existing is not None:
        tasks_sha = (existing.get("tasksManifest") or {}).get("sha256")
        adjudication = existing.get("developmentAdjudication")
    repositories = world.repositories
    freeze = {
        "format": "mlview-freeze/1", "campaign": campaign, "frozenAt": frozen_at, "referenceRevision": revision,
        "supersedes": supersedes,
        "files": {rel: er.sha256_bytes(data) for rel, data in sorted(files.items())},
        "decisionFiles": dict(sorted(decision_hashes.items())),
        "candidateLedgers": dict(sorted(candidate_hashes.items())),
        "tasksManifest": {"sha256": tasks_sha, "heldOut": _heldout_projection(manifest)},
        "repositories": {"sha256": er.sha256_bytes(world.repositories_bytes()),
                         "sparse": {repo.get("name"): list(repo.get("sparse") or [])
                                    for repo in repositories.get("repos") or []}},
        "developmentAdjudication": adjudication,
        "tooling": dict(tooling) if tooling is not None else _tooling(),
        "note": NOTE_TEXT,
    }
    files["freeze.json"] = er.canonical_json(freeze)
    result.files = files
    for task in world.heldout:
        reference = references[task["id"]]
        primary_reviews = [review["reviewer"] for review in reference["reviews"]]
        result.rows.append({"task": task["id"], "facts": reference["counts"]["facts"],
                            "essential": reference["counts"]["essential"],
                            "rejected": len(reference["rejectedFacts"]),
                            "added": sum(1 for fact in reference["facts"] if fact["origin"] == "added"),
                            "runsMustState": reference["counts"]["runsMustState"],
                            "reviewers": "; ".join(primary_reviews)})
    if policy.values.get("developmentAdjudication") == "required":
        complete = bool(adjudication and adjudication.get("complete"))
        result.notes.append("the run policy requires the development adjudication before Stage 1; run-prepare will "
                            "refuse Stage 1 runs until evals/workflow/decisions/development-adjudication.md is complete"
                            + ("" if complete else " (it is not complete now)") + ".")
    return result


def _review_entry(rel: str, result: RefCheck) -> dict:
    return {"role": result.role, "path": rel, "sha256": result.record.sha256, "reviewer": result.reviewer,
            "date": result.date, "transcribedBy": result.transcribed_by or None}


def _reference(world: World, task: dict, campaign: str, primary: RefCheck, reviews: list[dict], ledger: dict,
               ledger_raw: bytes) -> dict:
    facts = primary.facts
    essential = [fact["id"] for fact in facts if fact["essential"]]
    must = [item for item in primary.unknowns if item["runsMustState"]]
    return {
        "format": "mlview-frozen-reference/1", "campaign": campaign, "task": task["id"],
        "repository": task["repository"], "repositoryCommit": task["commit"],
        "candidate": {"path": f"{CANDIDATES_REL}/{task['id']}.json", "sha256": er.sha256_bytes(ledger_raw)},
        "reviews": reviews,
        "scenario": dict(primary.scenario),
        "facts": facts, "rejectedFacts": primary.rejected_facts, "essentialFactIds": essential,
        "knownUnresolved": primary.unknowns, "rejectedUnknowns": primary.rejected_unknowns,
        "nonDefects": primary.nondefects, "rejectedNonDefects": primary.rejected_nondefects,
        "defects": primary.defects, "disputes": primary.disputes,
        "counts": {"facts": len(facts), "essential": len(essential), "runsMustState": len(must),
                   "nonDefects": len(primary.nondefects), "defects": len(primary.defects)},
    }


def _source_files(world: World, task: dict, reference: dict, ledger: dict, result: Campaign,
                  existing: dict | None) -> dict | None:
    """sourceFiles of a frozen reference: every anchor file and scenario entrypoint, pinned by
    SHA-256 and blob. Verifies kept candidate quotes and new locators against the pinned bytes."""
    task_id, repo_name = task["id"], task.get("repository")
    repo = world.repo_entry(task)
    if repo is None:
        result.fail(f"{task_id}: {repo_name} is not listed in {REPOSITORIES_REL}", f"fix {REPOSITORIES_REL}")
        return None
    patterns = list(repo.get("sparse") or [])
    quotes = {anchor["id"]: anchor for fact in ledger["facts"] for anchor in fact["anchors"]}
    anchors = [anchor for fact in reference["facts"] for anchor in fact["anchors"]]
    anchors += [anchor for defect in reference["defects"] for anchor in defect["anchors"]]
    paths = sorted(set(reference["scenario"]["entrypoints"]) | {anchor["file"] for anchor in anchors})
    ok = True
    for path in paths:
        try:
            covered = er.sparse_covers(patterns, path)
        except ValueError as exc:
            result.fail(f"{task_id}: {path}: {exc}", "fix the path in the decisions file")
            ok = False
            continue
        if not covered:
            result.fail(f"{task_id}: {path} is not fetched by repositories.json ({repo_name} sparse list)",
                        "ask the maintainer to add it to the sparse list, then python tools/fetch_workflow_repos.py "
                        "--update-sparse")
            ok = False
    present = world.repo_dir(task) is not None
    if not present:
        recorded = (existing or {}).get("sourceFiles")
        if not isinstance(recorded, dict):
            result.fail(f"{task_id}: the corpus is absent and no committed sourceFiles exist",
                        "set MLVIEW_PUBLIC_CORPUS_DIR or run python tools/fetch_workflow_repos.py")
            return None
        missing = [path for path in paths if path not in recorded]
        if missing:
            result.fail(f"{task_id}: sourceFiles would add {', '.join(missing)} (corpus absent; cannot hash them)",
                        "run check-frozen with the corpus present")
            return None
        return {path: recorded[path] for path in paths} if ok else None
    sources: dict[str, dict] = {}
    try:
        tree = world.tree(task)
    except ValueError as exc:
        result.fail(f"{task_id}: cannot read the pinned tree: {exc}", "python tools/fetch_workflow_repos.py --verify")
        return None
    assert tree is not None
    for path in paths:
        if path not in tree:
            result.fail(f"{task_id}: {path} is not in the pinned {repo_name} tree at {task['commit'][:12]}",
                        "fix the path in the decisions file")
            ok = False
            continue
        try:
            data = world.pinned(task, path)
        except ValueError as exc:
            result.fail(f"{task_id}: {exc}", "python tools/fetch_workflow_repos.py --verify")
            ok = False
            continue
        sources[path] = {"sha256": er.sha256_bytes(data), "blob": er.git_blob_oid(data)}
    if not ok:
        return None
    for anchor in anchors:
        data = world.pinned(task, anchor["file"])
        try:
            lines = er.source_lines(data, anchor.get("cell"), world.helper)
            er.excerpt(lines, anchor["line"], anchor["endLine"])
        except ValueError as exc:
            result.fail(f"{task_id}: {anchor['id']} ({_locator(anchor)}) does not resolve: {exc}",
                        f"{CHECK_COMMAND} {task_id}")
            ok = False
            continue
        if anchor["endLine"] > er.human_line_count(lines):
            result.fail(f"{task_id}: {anchor['id']} ({_locator(anchor)}) is out of range", f"{CHECK_COMMAND} {task_id}")
            ok = False
            continue
        candidate = quotes.get(anchor["id"])
        if candidate is not None and not er.quote_matches(candidate.get("quote"), lines, anchor["line"],
                                                          anchor["endLine"], world.helper):
            result.fail(f"{task_id}: the candidate quote of {anchor['id']} ({_locator(anchor)}) differs from the "
                        "pinned bytes", "python tools/fetch_workflow_repos.py --verify")
            ok = False
    return sources if ok else None


def _adjudication_binding(world: World) -> dict | None:
    rel = f"{DECISIONS_REL}/{ADJUDICATION_TARGET}.md"
    path = world.root / rel
    if not path.is_file():
        return None
    raw = path.read_bytes()
    try:
        complete = check_adjudication(world, raw, rel).complete
    except UsageError:
        complete = False
    return {"path": rel, "sha256": er.sha256_bytes(raw), "complete": complete}


SUMMARY_FILES = {"1": ("stage1-summary.json", "stage1-summary.md"), "2": ("stage2-summary.json", "stage2-summary.md")}
PILOT_SUMMARY_FORMAT = "mlview-pilot-summary/1"
PILOT_CANDIDATE_KIND = "pilot-candidate"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class History:
    """Read-only Git history of the repository at ``world.root``.

    ``root`` is None when the history cannot answer (no Git work tree at exactly that root, or a
    shallow or partial clone, whose missing commits or objects could hide a removed or replaced
    file); ``reason`` then says why. Every query lists the versions a path had anywhere in the
    history reachable from HEAD, merges included (eval_records.path_history). A path whose
    history Git cannot read is recorded in ``unreadable`` and answered with None, never as "never
    committed"."""

    def __init__(self, world: World) -> None:
        self.root: Path | None = None
        self.reason: str | None = None
        self.unreadable: list[str] = []
        self._empty = False
        self._versions: dict[str, er.PathHistory | None] = {}
        self._campaigns: dict[str, dict[str, str]] | None = None
        root = world.root.resolve()
        try:
            top = er._git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()
        except ValueError:
            self.reason = "the repository root is not a Git work tree"
            return
        if not top or Path(top).resolve() != root:
            self.reason = "the repository root is not the top of a Git work tree"
            return
        limit = er.history_limit(root)
        if limit:
            self.reason = limit
            return
        self.root = root
        try:
            er._git(root, "rev-parse", "--verify", "--quiet", "HEAD")
        except ValueError:
            self._empty = True  # no commit yet: nothing was ever committed

    @property
    def full(self) -> bool:
        return self.root is not None

    @property
    def incomplete(self) -> bool:
        """The history is shallow or partial (not merely absent, as in a directory outside Git)."""
        return self.reason is not None and ("shallow" in self.reason or "partial" in self.reason)

    def versions(self, rel: str) -> er.PathHistory | None:
        """Every version ``rel`` had in the history reachable from HEAD, or None when the history
        cannot answer (see ``reason`` and ``unreadable``)."""
        if self.root is None:
            return None
        if self._empty:
            return er.PathHistory({}, [])
        if rel not in self._versions:
            try:
                self._versions[rel] = er.path_history(self.root, rel)
            except ValueError:
                self.unreadable.append(rel)
                self._versions[rel] = None
        return self._versions[rel]

    def campaigns(self) -> dict[str, dict[str, str]] | None:
        """``{campaign: {file: oldest commit}}`` for every campaign whose freeze.json, candidate.json
        or stage summary the history reachable from HEAD ever recorded, or None when it cannot say."""
        if self.root is None:
            return None
        if self._empty:
            return {}
        if self._campaigns is None:
            try:
                paths = er.committed_paths(self.root, PILOT_REL)
            except ValueError:
                self.unreadable.append(PILOT_REL)
                return None
            names = {"freeze.json", "candidate.json"} | {name for pair in SUMMARY_FILES.values() for name in pair}
            found: dict[str, dict[str, str]] = {}
            for path, commit in paths.items():
                parts = path[len(PILOT_REL) + 1:].split("/")
                if len(parts) == 2 and parts[1] in names:
                    found.setdefault(parts[0], {})[parts[1]] = commit
            self._campaigns = found
        return self._campaigns

    def at_head(self, rel: str) -> bool:
        """Whether HEAD holds ``rel``."""
        if self.root is None or self._empty:
            return False
        try:
            er._git(self.root, "cat-file", "-e", f"HEAD:{rel}")
        except ValueError:
            return False
        return True

    def blob_id(self, rel: str) -> str | None:
        """The Git object ID of the working-tree bytes of ``rel`` (``git hash-object --no-filters``, in
        the repository's own object format; nothing is written), or None."""
        if self.root is None:
            return None
        try:
            return er._git(self.root, "hash-object", "--no-filters", "--", rel).decode("ascii").strip() or None
        except (ValueError, UnicodeError):
            return None

    def blob(self, oid: str) -> bytes | None:
        if self.root is None or not er.OBJECT_RE.fullmatch(oid):
            return None
        try:
            return er._git(self.root, "cat-file", "blob", oid)
        except ValueError:
            return None

    def show(self, commit: str, rel: str) -> bytes | None:
        if self.root is None:
            return None
        try:
            return er.git_show(self.root, commit, rel)
        except ValueError:
            return None


def _has_candidate(world: World, history: History, campaign: str) -> str | None:
    """Why ``campaign`` counts as captured (a candidate.json or stage summary now or ever committed,
    in any branch merged into HEAD), or None. Callers check ``history`` first: without the full
    history only the present files are seen."""
    directory = world.root / PILOT_REL / campaign
    names = ["candidate.json"] + [name for pair in SUMMARY_FILES.values() for name in pair]
    for name in names:
        if os.path.lexists(directory / name):
            return f"it has {name}"
    for name in names:
        versions = history.versions(f"{PILOT_REL}/{campaign}/{name}")
        if versions is not None and versions.committed:
            first = versions.first[1] if versions.first else versions.removals[0]
            return f"{name} was committed in {first[:12]}; deleting it does not undo the capture"
    return None


def _history_refusal(history: History, what: str, result: Campaign) -> bool:
    """Refuse (True) when the history cannot say ``what``: a shallow or partial clone, or a history Git
    cannot read. A directory outside Git has no history to consult and is not refused."""
    if history.incomplete:
        result.fail(f"cannot tell {what}: {history.reason}", "fetch the full history (git fetch --unshallow, or clone "
                                                           "without --filter)")
        return True
    if history.unreadable:
        result.fail(f"cannot tell {what}: git cannot read the history of {', '.join(history.unreadable)}",
                    "fetch the full history and run the freeze again")
        return True
    return False


def _supersede_check(world: World, campaign: str, reason: str | None, result: Campaign) -> dict | None:
    """The supersedes record, or None; problems go to ``result``."""
    manifest = world.manifest
    problems = er.check_task_manifest(manifest)
    for problem in problems:
        result.fail(f"{TASKS_REL}: {problem}", f"fix {TASKS_REL}")
    freeze = manifest.get("pilotFreeze")
    if freeze is None:
        not_prefreeze = [task["id"] for task in world.heldout if task.get("referenceStatus") != "needs-human-review"]
        if not_prefreeze:
            result.fail(f"{TASKS_REL}: {', '.join(not_prefreeze)} not needs-human-review", f"fix {TASKS_REL}")
        if reason:
            result.fail("--supersede-reason was given but no campaign is frozen", "drop --supersede-reason")
        # A committed campaign is immutable: restoring the pre-freeze tasks.json never erases one.
        history = History(world)
        committed = history.campaigns()
        if not _history_refusal(history, "whether a campaign was committed before", result) and committed:
            names = ", ".join(sorted(committed))
            result.fail(f"{TASKS_REL} has no pilotFreeze, but the Git history holds committed campaign(s) {names} "
                        f"under {PILOT_REL}; a committed campaign is immutable and is never erased",
                        f"restore {PILOT_REL}/<campaign> and the {TASKS_REL} that names it from the Git history, then "
                        "supersede it with --supersede-reason (after its owner-authored invalidation.md if it was "
                        f"captured; {FREEZE_README})")
        return None
    old = freeze.get("campaign") if isinstance(freeze, dict) else None
    if not reason:
        result.fail(f"{TASKS_REL} is not in the pre-freeze state: campaign {old} is frozen",
                    f'a new campaign may supersede {old} only with --supersede-reason "<why>", and only if {old} has '
                    "no committed candidate.json or has an owner-authored invalidation.md")
        return None
    if old == campaign:
        result.fail(f"campaign {campaign} is the one already frozen", "choose a new campaign name")
        return None
    old_dir = world.root / PILOT_REL / str(old)
    history = History(world)
    if history.incomplete:
        result.fail(f"cannot tell whether {old} was ever captured: {history.reason}",
                    "fetch the full history (git fetch --unshallow, or clone without --filter)")
        return None
    captured = _has_candidate(world, history, str(old))
    if _history_refusal(history, f"whether {old} was ever captured", result):
        return None
    # A committed campaign is immutable: every campaign the history holds must still exist and be
    # reached from the campaign superseded now, or the new freeze could never pass check-frozen.
    committed = history.campaigns()
    if _history_refusal(history, "whether a campaign was committed before", result):
        return None
    chain = _supersedes_chain(world, str(old))
    missing = sorted(name for name in committed or {} if not (world.root / PILOT_REL / name / "freeze.json").is_file())
    stray = sorted(name for name in committed or {} if name not in missing and name not in chain)
    if missing or stray:
        parts = []
        if missing:
            parts.append(f"{_join_names(missing)} {'was' if len(missing) == 1 else 'were'} committed and "
                         f"{'is' if len(missing) == 1 else 'are'} missing now")
        if stray:
            parts.append(f"{_join_names(stray)} {'is' if len(stray) == 1 else 'are'} not reached from {old} through "
                         "freeze.json supersedes")
        detail = "; ".join(parts)
        result.fail(f"the Git history holds committed campaign(s) under {PILOT_REL} that the campaign {old} named in "
                    f"{TASKS_REL} does not account for ({detail}); a committed campaign is immutable and is never erased",
                    f"restore {PILOT_REL}/<campaign> and the {TASKS_REL} that names the latest campaign from the Git "
                    "history, then supersede that one with --supersede-reason (after its owner-authored invalidation.md "
                    f"if it was captured; {FREEZE_README})")
        return None
    if captured:
        invalidation = old_dir / "invalidation.md"
        problem = _invalidation_problem(invalidation, str(old))
        if problem:
            result.fail(f"{old} was captured ({captured}), so it can be superseded only after an owner-authored "
                        f"invalidation.md ({problem})", f"the owner writes {world.display(invalidation)}")
            return None
    return {"campaign": old, "reason": reason}


def _supersedes_chain(world: World, start: str) -> list[str]:
    """``start`` and every campaign it reaches through the on-disk freeze.json ``supersedes`` pointers."""
    chain: list[str] = []
    name: object = start
    while isinstance(name, str) and name not in chain:
        chain.append(name)
        try:
            value = json.loads((world.root / PILOT_REL / name / "freeze.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            break
        pointer = value.get("supersedes") if isinstance(value, dict) else None
        name = pointer.get("campaign") if isinstance(pointer, dict) else None
    return chain


def _invalidation_problem(path: Path, campaign: str) -> str | None:
    if not path.is_file():
        return "it does not exist"
    record, problems = er.parse_record(path.read_bytes(), str(path))
    if record is None or problems:
        return "it does not parse"
    if record.kind != "Invalidation" or record.ident != campaign:
        return f'its title must read "# Invalidation: {campaign}"'
    missing = [key for key in ("Reviewer", "Date", "Scope", "Reason") if not _value(record.header, key)]
    if missing:
        return f"{', '.join(missing)} empty"
    if _value(record.header, "Scope").casefold() not in ("stage1", "campaign"):
        return "Scope must be stage1 or campaign"
    if not _valid_date(_value(record.header, "Date")):
        return "Date is not YYYY-MM-DD"
    return None


def freeze(world: World, campaign: str, *, write: bool, frozen_at: str | None, supersede_reason: str | None,
           out) -> int:
    if not isinstance(campaign, str) or not er.NAME_RE.fullmatch(campaign):
        raise UsageError(f"--campaign must be a lowercase name such as pilot-01, not {campaign!r}")
    frozen_at = frozen_at or er.rfc3339_utc_now()
    if not er.is_rfc3339(frozen_at) or not frozen_at.endswith("Z"):
        raise UsageError(f"--frozen-at must be an RFC 3339 UTC time such as 2026-10-05T10:00:00Z, not {frozen_at!r}")
    tasks_before = world.manifest_bytes()
    gate = Campaign(campaign)
    if _canonical_manifest(world.manifest) != tasks_before:
        gate.fail(f"{TASKS_REL} is not canonical JSON (json.dumps(indent=2) plus a newline)",
                  f"restore {TASKS_REL} to its canonical formatting")
    supersedes = _supersede_check(world, campaign, supersede_reason, gate)
    target = world.root / PILOT_REL / campaign
    if target.exists():
        gate.fail(f"{world.display(target)} already exists", "choose a new campaign name; frozen campaigns are never "
                                                             "overwritten")
    derived = derive_campaign(world, campaign, frozen_at=frozen_at, supersedes=supersedes)
    problems = gate.problems + derived.problems
    if problems:
        print(f"Cannot freeze {campaign} (nothing written):", file=out)
        for what, action in problems:
            print(f"  - {what.rstrip('.')}. Next: {action}", file=out)
        return 1
    heldout = len(world.heldout)
    verb = "Would write" if not write else "Wrote"
    header = (f"Ready to freeze {campaign} (dry run; nothing written)" if not write
              else f"Froze {campaign} at {frozen_at} (referenceRevision {derived.revision})")
    if write:
        _write_campaign(world, target, derived, tasks_before)
    print(header, file=out)
    print(f"  {'task':<18}{'facts':>7}{'essential':>11}{'rejected':>10}{'added':>7}{'runs-must-state':>17}  reviewers",
          file=out)
    for row in derived.rows:
        print(f"  {row['task']:<18}{row['facts']:>7}{row['essential']:>11}{row['rejected']:>10}{row['added']:>7}"
              f"{row['runsMustState']:>17}  {row['reviewers']}", file=out)
    totals = {key: sum(row[key] for row in derived.rows) for key in ("facts", "essential", "rejected", "added",
                                                                     "runsMustState")}
    print(f"  {'total':<18}{totals['facts']:>7}{totals['essential']:>11}{totals['rejected']:>10}{totals['added']:>7}"
          f"{totals['runsMustState']:>17}", file=out)
    policy = derived.policy
    assert policy is not None
    print(f"  run policy: ready ({policy.reviewer}, {policy.date}); prompts: {2 * heldout} rendered, "
          f"{derived.leak_findings} leak findings", file=out)
    for note in derived.notes:
        print(f"  note: {note}", file=out)
    print(f"{verb} {PILOT_REL}/{campaign}/ ({heldout} references, reference-set.json, policy.json, {2 * heldout} "
          "prompts, freeze.json)", file=out)
    if supersedes is not None:
        change = (f"pilotFreeze {supersedes['campaign']} -> {campaign} (supersedes {supersedes['campaign']}: "
                  f"{supersedes['reason']})")
    else:
        change = f"{heldout} held-out referenceStatus -> frozen; add pilotFreeze"
    print(f"{'Would update' if not write else 'Updated'} {TASKS_REL}: {change}", file=out)
    if not write:
        print("Re-run with --write. Frozen files are created exclusively and never overwritten.", file=out)
    else:
        print(f"Next: commit {DECISIONS_REL}, {PILOT_REL}/{campaign} and {TASKS_REL} together, before editing any of "
              "them again (until then Git does not hold the frozen bytes). The freeze records the reviewers' decisions; "
              "it does not add an approval.", file=out)
    return 0


def _write_campaign(world: World, target: Path, derived: Campaign, tasks_before: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(target)  # exclusive: FileExistsError when another freeze got there first
    created: list[Path] = []
    try:
        for rel in sorted(derived.files, key=lambda item: (item == "freeze.json", item)):
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            er.write_exclusive(path, derived.files[rel])
            created.append(path)
        tasks_path = world.root / TASKS_REL
        if tasks_path.read_bytes() != tasks_before:
            raise RuntimeError(f"{TASKS_REL} changed during the freeze; nothing was kept")
        assert derived.tasks_after is not None
        er.write_atomic(tasks_path, derived.tasks_after)
    except BaseException:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        for directory in sorted({p.parent for p in created} | {target}, key=lambda p: len(p.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    world.reload_manifest()


# --------------------------------------------------------------------------------------------
# check-frozen


def _candidate_problems(label: str, directory: Path, campaign: str, freeze_raw: bytes) -> tuple[bytes | None, list[str]]:
    """(candidate.json bytes or None, problems): the candidate must be this campaign's version 2
    pilot-candidate and must identify exactly these freeze.json bytes."""
    path = directory / "candidate.json"
    if not path.is_file():
        return None, []
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        return raw, [f"{label}/candidate.json is not JSON"]
    if not isinstance(value, dict) or value.get("version") != 2 or value.get("kind") != PILOT_CANDIDATE_KIND \
            or value.get("campaign") != campaign:
        return raw, [f"{label}/candidate.json is not a version 2 {PILOT_CANDIDATE_KIND} record of {campaign}"]
    freeze_rel = f"{PILOT_REL}/{campaign}/freeze.json"
    components = value.get("components") if isinstance(value.get("components"), list) else []
    entry = next((item for item in components if isinstance(item, dict) and item.get("path") == freeze_rel), None)
    if entry is None:
        return raw, [f"{label}/candidate.json does not identify {freeze_rel}"]
    if entry.get("sha256") != er.sha256_bytes(freeze_raw):
        return raw, [f"{label}/freeze.json differs from the freeze.json that candidate.json identifies "
                     "(frozen files are immutable)"]
    return raw, []


def _rendering_check(value: dict, directory: Path, json_name: str, md_name: str, label: str, problems: list[str],
                     notes: list[str] | None, history: "History | None" = None) -> None:
    """The recorded Markdown must be the one summarize renders from the recorded JSON (section 4.7).
    Checked when the summary names the running tools/workflow_pilot.py as its renderer. A summary that
    names another one is noted, so a later tool change never fails a recorded summary (section 1.10),
    but only when that hash is the tools/workflow_pilot.py committed with the summary: the tooling
    field is part of the file being verified and never switches the check off on its own word."""
    import workflow_pilot  # noqa: PLC0415 - workflow_pilot imports this module lazily too

    tooling = value.get("tooling") if isinstance(value.get("tooling"), dict) else {}
    recorded = tooling.get("tools/workflow_pilot.py")
    if recorded != er.sha256_file(Path(workflow_pilot.__file__).resolve()):
        versions = history.versions(f"{PILOT_REL}/{directory.name}/{json_name}") if history is not None else None
        first = versions.first[1] if versions is not None and versions.first is not None else None
        if first is None:
            if notes is not None:
                notes.append(f"check-frozen: {directory.name}: not verified: {md_name} rendered from {json_name} (it "
                             "names another tools/workflow_pilot.py, and no commit that recorded it can be read).")
            return
        committed = history.show(first, "tools/workflow_pilot.py")
        if committed is None and history.root != ROOT.resolve():
            if notes is not None:  # a test world: the tools are not part of the repository checked here
                notes.append(f"check-frozen: {directory.name}: not verified: {md_name} rendered from {json_name} (it "
                             "names another tools/workflow_pilot.py, and this repository does not hold the tools).")
            return
        if committed is None or er.sha256_bytes(committed) != recorded:
            problems.append(f"{label}/{json_name} names a tools/workflow_pilot.py (sha256 {str(recorded)[:12]}...) that "
                            f"is neither the running one nor the one committed with it in {first[:12]} (a recorded "
                            "summary is written only by summarize --record, with the committed tools)")
        elif notes is not None:
            notes.append(f"check-frozen: {directory.name}: not verified: {md_name} rendered from {json_name} (it was "
                         f"recorded with the tools/workflow_pilot.py committed with it in {first[:12]}, not the running "
                         "one).")
        return
    try:
        rendered = workflow_pilot.render_markdown(value).encode("utf-8")
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        rendered = None
    if rendered is None or (directory / md_name).read_bytes() != rendered:
        problems.append(f"{label}/{md_name} is not the Markdown rendered from {json_name} (a recorded summary is "
                        "written only by summarize --record)")


def _summary_state(world: World, directory: Path, freeze_value: dict, freeze_raw: bytes,
                   problems: list[str], candidate: tuple[bytes | None, list[str]],
                   notes: list[str] | None = None, history: "History | None" = None) -> bool:
    """True when a genuine final summary is recorded: a Stage 1 stop or invalid, or an all-stage
    summary. Every stage summary file must be a summary the pilot recorded for this campaign's
    candidate and freeze; anything else is a problem and never switches off the re-derivation.
    ``candidate`` is the result of _candidate_problems, whose problems the caller reports."""
    label = world.display(directory)
    campaign = directory.name
    present = sorted(path.name for path in directory.glob("stage*summary*"))
    known = {name for pair in SUMMARY_FILES.values() for name in pair}
    for name in present:
        if name not in known:
            problems.append(f"{label}/{name} is not a file summarize --record writes")
    present = [name for name in present if name in known]
    if not present:
        return False
    candidate_raw, candidate_problems = candidate
    if candidate_raw is None:
        problems.append(f"{label}: {', '.join(present)} exist(s) without candidate.json; a summary is recorded only "
                        "for a captured candidate")
        return False
    if candidate_problems:
        return False
    candidate_sha, freeze_sha = er.sha256_bytes(candidate_raw), er.sha256_bytes(freeze_raw)
    verdicts: dict[str, str] = {}
    for number, (json_name, md_name) in SUMMARY_FILES.items():
        have = [name for name in (json_name, md_name) if name in present]
        if not have:
            continue
        if len(have) == 1:
            other = md_name if have[0] == json_name else json_name
            problems.append(f"{label}/{have[0]} has no {other}; summarize --record writes both")
            continue
        try:
            value = json.loads((directory / json_name).read_text(encoding="utf-8"))
            markdown = (directory / md_name).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError, ValueError) as exc:
            problems.append(f"{label}/{json_name} cannot be read ({exc})")
            continue
        stage = "1" if number == "1" else "all"
        allowed = ("go", "stop", "invalid") if number == "1" else ("targets-met", "targets-missed", "invalid")
        wrong = []
        if not isinstance(value, dict) or value.get("format") != PILOT_SUMMARY_FORMAT:
            wrong.append(f'format is not "{PILOT_SUMMARY_FORMAT}"')
        else:
            decision = value.get("decision") if isinstance(value.get("decision"), dict) else {}
            verdict = decision.get("value")
            inputs = value.get("inputs") if isinstance(value.get("inputs"), dict) else {}
            if value.get("campaign") != campaign:
                wrong.append(f"campaign is not {campaign}")
            if value.get("stage") != stage:
                wrong.append(f'stage is not "{stage}"')
            if verdict not in allowed:
                wrong.append(f"the decision is not one of {', '.join(allowed)}")
            if value.get("candidateSha256") != candidate_sha or inputs.get("candidate") != candidate_sha:
                wrong.append("candidateSha256 differs from sha256(candidate.json)")
            if inputs.get("freeze") != freeze_sha:
                wrong.append("inputs.freeze differs from sha256(freeze.json)")
            if value.get("referenceRevision") != freeze_value.get("referenceRevision"):
                wrong.append("referenceRevision differs from freeze.json")
            generated = value.get("generatedAt")
            title = "Stage 1 summary" if number == "1" else "all-stage summary"
            expected = [f"# MLView pilot {campaign} \u2014 {title} ({str(generated)[:10]})",
                        f"**Decision: {str(verdict).upper()}** \u2014 {decision.get('label')}."]
            if not isinstance(generated, str) or not er.is_rfc3339(generated) or markdown[:2] != expected:
                wrong.append(f"{md_name} does not open with the title and decision of {json_name}")
            if not wrong:
                verdicts[number] = verdict
                _rendering_check(value, directory, json_name, md_name, label, problems, notes, history)
        if wrong:
            problems.append(f"{label}/{json_name} is not a recorded summary of this candidate ({'; '.join(wrong)})")
    if "2" in verdicts and verdicts.get("1") != "go":
        problems.append(f"{label}/stage2-summary.json is recorded without a Stage 1 go summary")
        return False
    return "2" in verdicts or verdicts.get("1") in ("stop", "invalid")


def _ledger_problems(world: World, campaign: str, freeze_value: dict, problems: list[str]) -> None:
    """The candidate ledgers a campaign froze are immutable: their bytes must still match."""
    ledgers = freeze_value.get("candidateLedgers")
    if not isinstance(ledgers, dict):
        problems.append(f"{campaign}/freeze.json has no candidateLedgers map")
        return
    for rel, digest in sorted(ledgers.items()):
        if not isinstance(rel, str) or not rel.startswith(CANDIDATES_REL + "/"):
            problems.append(f"{campaign}/freeze.json candidateLedgers names {rel!r}, not a candidate ledger")
            continue
        try:
            data = er.confined_file(world.root, rel).read_bytes()
        except (OSError, ValueError) as exc:
            problems.append(f"{rel} (frozen in {campaign}) cannot be read: {exc}")
            continue
        if er.sha256_bytes(data) != digest:
            problems.append(f"{rel} differs from the ledger frozen in {campaign} (candidate ledgers are immutable)")


def _recorded_fields(world: World, history: History, campaign: str, freeze_value: dict, freeze_raw: bytes,
                     campaigns: set[str], problems: list[str], notes: list[str]) -> None:
    """Check the freeze.json fields the re-derivation copies instead of recomputing."""
    supersedes = freeze_value.get("supersedes")
    if supersedes is not None:
        if not isinstance(supersedes, dict) or set(supersedes) != {"campaign", "reason"} \
                or not isinstance(supersedes.get("reason"), str) or not supersedes["reason"].strip():
            problems.append(f"{campaign}/freeze.json supersedes must be null or {{campaign, reason}} with a reason")
        elif supersedes.get("campaign") == campaign or supersedes.get("campaign") not in campaigns:
            problems.append(f"{campaign}/freeze.json supersedes {supersedes.get('campaign')!r}, which is not another "
                            f"frozen campaign in {PILOT_REL}")
    adjudication = freeze_value.get("developmentAdjudication")
    adjudication_rel = f"{DECISIONS_REL}/{ADJUDICATION_TARGET}.md"
    if adjudication is not None:
        if not isinstance(adjudication, dict) or set(adjudication) != {"path", "sha256", "complete"} \
                or adjudication.get("path") != adjudication_rel or not isinstance(adjudication.get("complete"), bool) \
                or not isinstance(adjudication.get("sha256"), str) or not _SHA256_RE.fullmatch(adjudication["sha256"]):
            problems.append(f"{campaign}/freeze.json developmentAdjudication must be null or "
                            f"{{path: {adjudication_rel}, sha256, complete}}")
            adjudication = None
    tasks_sha = (freeze_value.get("tasksManifest") or {}).get("sha256") \
        if isinstance(freeze_value.get("tasksManifest"), dict) else None
    if not isinstance(tasks_sha, str) or not _SHA256_RE.fullmatch(tasks_sha):
        problems.append(f"{campaign}/freeze.json tasksManifest.sha256 is not a sha256")
        tasks_sha = None
    unverified: list[str] = []
    freeze_rel = f"{PILOT_REL}/{campaign}/freeze.json"
    versions = history.versions(freeze_rel)
    commit = None  # the oldest commit that recorded freeze.json, in any branch merged into HEAD
    why = history.reason or "freeze.json is not committed yet"
    if versions is not None and versions.first is not None:
        blob, commit = versions.first
        for _oid, where, mode in versions.irregular:
            problems.append(f"{freeze_rel} was committed as a {_MODE_NAMES.get(mode, f'non-file entry (mode {mode})')} "
                            f"in {where[:12]}, not as a file (frozen files are immutable)")
        committed = history.blob(blob)
        if committed is None:
            unverified.append(f"freeze.json against its first commit (git cannot read it from {commit[:12]})")
        elif committed != freeze_raw:
            problems.append(f"{freeze_rel} differs from the version committed in {commit[:12]} "
                            "(frozen files are immutable)")
        if len(versions.versions) > 1:
            problems.append(f"{freeze_rel} was committed with {len(versions.versions)} different contents "
                            f"({', '.join(c[:12] for c in versions.versions.values())}), for example in a merge "
                            "(frozen files are immutable)")
    elif versions is not None:
        if history.at_head(freeze_rel):
            problems.append(f"{freeze_rel} is committed, but the Git history lists no commit that recorded it "
                            "(frozen files are immutable)")
        else:
            unverified.append("freeze.json against its first commit (freeze.json is not committed yet)")
    elif history.full:  # git could not read the history of freeze.json; _history_note names it
        why = f"git cannot read the history of {freeze_rel}"
    if tasks_sha is not None:
        current = world.manifest_bytes()
        if not (_names_campaign(current, campaign) and er.sha256_bytes(current) == tasks_sha):
            at_freeze = history.show(commit, TASKS_REL) if commit is not None else None
            if at_freeze is not None and _names_campaign(at_freeze, campaign):
                if er.sha256_bytes(at_freeze) != tasks_sha:
                    problems.append(f"{campaign}/freeze.json tasksManifest.sha256 differs from the {TASKS_REL} "
                                    f"committed with it in {commit[:12]} (a squash or rebase merge that combined the "
                                    f"freeze with later {TASKS_REL} edits also causes this; {FREEZE_README}, "
                                    '"Merging a campaign")')
            else:
                detail = (why if commit is None else f"{TASKS_REL} cannot be read at {commit[:12]}" if at_freeze is None
                          else f"{TASKS_REL} was committed separately from freeze.json")
                unverified.append(f"tasksManifest.sha256 ({detail})")
    if adjudication is not None:
        path = world.root / adjudication_rel
        current = path.read_bytes() if path.is_file() else None
        if current is not None and er.sha256_bytes(current) == adjudication["sha256"]:
            try:
                complete = check_adjudication(world, current, adjudication_rel).complete
            except UsageError:
                complete = None
            if complete is not None and complete != adjudication["complete"]:
                problems.append(f"{campaign}/freeze.json developmentAdjudication.complete is {adjudication['complete']}"
                                f" but {adjudication_rel} with that sha256 checks as "
                                f"{'complete' if complete else 'not complete'}")
        elif commit is not None:
            at_freeze = history.show(commit, adjudication_rel)
            if at_freeze is None or er.sha256_bytes(at_freeze) != adjudication["sha256"]:
                problems.append(f"{campaign}/freeze.json developmentAdjudication.sha256 differs from the "
                                f"{adjudication_rel} committed with freeze.json in {commit[:12]}")
        else:
            unverified.append(f"developmentAdjudication.sha256 ({why})")
    if unverified:
        notes.append(f"check-frozen: {campaign}: not verified: {'; '.join(unverified)}.")


def _names_campaign(data: bytes, campaign: str) -> bool:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError):
        return False
    pointer = value.get("pilotFreeze") if isinstance(value, dict) else None
    return isinstance(pointer, dict) and pointer.get("campaign") == campaign


_MODE_NAMES = {"160000": "gitlink (a submodule commit)", "120000": "symbolic link"}
CANDIDATE_RULE = "a campaign has one candidate; it is never removed or replaced"
SUMMARY_RULE = "a recorded summary is final"


def _final_problems(world: World, history: History, rel: str, rule: str, relaxed: list[str] | None = None,
                    campaign: str = "") -> list[str]:
    """Problems of a file that is final once committed (candidate.json, a stage summary): in the
    history reachable from HEAD, merges included, it has exactly one content, and the working tree
    still holds that content. A removal later restored byte for byte changes nothing. For a
    superseded campaign the owner invalidated, ``relaxed`` receives the several-contents finding as
    a note while the file still holds one of them (such a history cannot be undone)."""
    versions = history.versions(rel)
    if versions is None:
        return []  # _history_note names the check
    path = world.root / rel
    if versions.first is None:
        if versions.removals and not path.is_file():
            return [f"{rel} was removed in {versions.removals[0][:12]} ({rule})"]
        if history.at_head(rel):
            return [f"{rel} is committed, but the Git history lists no commit that recorded it ({rule})"]
        return []
    blob, first = versions.first
    found = [f"{rel} was committed as a {_MODE_NAMES.get(mode, 'non-file entry (mode ' + mode + ')')} in "
             f"{commit[:12]}, not as a file ({rule})" for _oid, commit, mode in versions.irregular]
    if not path.is_file():
        return found + [f"{rel} was committed in {first[:12]} and is missing now ({rule})"]
    # Decided from object IDs alone, so an entry whose contents Git cannot read (a gitlink names a
    # commit) never turns the rule into a note: the working-tree bytes are hashed, not compared.
    current = history.blob_id(rel)
    if current is None:
        history.unreadable.append(rel)
        return found
    if len(versions.versions) > 1:
        message = (f"{rel} was committed with {len(versions.versions)} different contents "
                   f"({', '.join(commit[:12] for commit in versions.versions.values())}), for example through a merge "
                   f"of two branches that both recorded it ({rule}; if two recordings were merged, the owner records "
                   f"invalidation.md and a new campaign supersedes this one, {FREEZE_README})")
        if relaxed is not None and not found and current in versions.versions:
            relaxed.append(f"check-frozen: {campaign} (invalidated): {message}.")
        else:
            found.append(message)
            if current != blob:
                found.append(f"{rel} differs from the version first committed in {first[:12]} ({rule})")
    elif current != blob:
        found.append(f"{rel} differs from the version first committed in {first[:12]} ({rule})")
    return found


def _capture_problems(world: World, history: History, campaign: str, superseded: bool, problems: list[str],
                      notes: list[str]) -> None:
    """A captured campaign keeps its one candidate.json; a superseded captured campaign needs its invalidation.md."""
    directory = world.root / PILOT_REL / campaign
    invalidated = superseded and _invalidation_problem(directory / "invalidation.md", campaign) is None
    problems.extend(_final_problems(world, history, f"{PILOT_REL}/{campaign}/candidate.json", CANDIDATE_RULE,
                                    notes if invalidated else None, campaign))
    if superseded:
        captured = _has_candidate(world, history, campaign)
        if captured:
            problem = _invalidation_problem(directory / "invalidation.md", campaign)
            if problem:
                problems.append(f"{campaign} was superseded although it was captured ({captured}) and its "
                                f"invalidation.md is not usable ({problem})")


def _summary_history(world: World, history: History, campaign: str, problems: list[str],
                     notes: list[str] | None = None, superseded: bool = False) -> None:
    """A recorded summary is final: each stage*-summary.{json,md} ever committed, in any branch merged
    into HEAD, must still exist with the one content it was committed with."""
    directory = world.root / PILOT_REL / campaign
    invalidated = superseded and _invalidation_problem(directory / "invalidation.md", campaign) is None
    for name in [name for pair in SUMMARY_FILES.values() for name in pair]:
        problems.extend(_final_problems(world, history, f"{PILOT_REL}/{campaign}/{name}", SUMMARY_RULE,
                                        notes if invalidated else None, campaign))


def _history_note(history: History, campaign: str, notes: list[str]) -> None:
    """Say which checks did not run because the Git history is not available (a shallow or partial
    clone, no Git, or a history Git cannot read)."""
    if not history.full:
        notes.append(f"check-frozen: {campaign}: not verified without the full Git history ({history.reason}): "
                     "freeze.json against its first commit, and whether a committed campaign, candidate.json or "
                     "stage summary was removed or changed.")
        return
    unread = sorted({rel for rel in history.unreadable if rel.startswith(f"{PILOT_REL}/{campaign}/")})
    if unread:
        notes.append(f"check-frozen: {campaign}: not verified: git cannot read the history of {', '.join(unread)}.")


def _integrity(world: World, directory: Path, problems: list[str]) -> dict | None:
    """Hash-integrity check of one committed campaign directory; returns its freeze.json."""
    label = world.display(directory)
    try:
        freeze_value = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append(f"{label}/freeze.json cannot be read: {exc}")
        return None
    files = freeze_value.get("files") if isinstance(freeze_value, dict) else None
    if not isinstance(files, dict):
        problems.append(f"{label}/freeze.json has no files map")
        return None
    for rel, digest in sorted(files.items()):
        try:
            data = er.confined_file(directory, rel).read_bytes()
        except ValueError as exc:
            problems.append(f"{label}/{rel}: {exc}")
            continue
        if er.sha256_bytes(data) != digest:
            problems.append(f"{label}/{rel} differs from its hash in freeze.json (frozen files are immutable)")
    try:
        reference_set = (directory / "reference-set.json").read_bytes()
        if freeze_value.get("referenceRevision") != "sha256:" + er.sha256_bytes(reference_set):
            problems.append(f"{label}: referenceRevision does not match reference-set.json")
    except OSError as exc:
        problems.append(f"{label}/reference-set.json cannot be read: {exc}")
    for sub in ("reference", "prompts/skill", "prompts/baseline"):
        folder = directory / sub
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                rel = path.relative_to(directory).as_posix()
                if rel not in files:
                    problems.append(f"{label}/{rel} is not listed in freeze.json")
    return freeze_value


def check_frozen(world: World, out) -> int:
    pilot_dir = world.root / PILOT_REL
    campaigns = sorted(path.parent for path in pilot_dir.glob("*/freeze.json")) if pilot_dir.is_dir() else []
    names = {directory.name for directory in campaigns}
    manifest = world.manifest
    freeze_pointer = manifest.get("pilotFreeze")
    problems: list[str] = []
    notes: list[str] = []
    for problem in er.check_task_manifest(manifest):
        problems.append(f"{TASKS_REL}: {problem}")
    current = freeze_pointer.get("campaign") if isinstance(freeze_pointer, dict) else None
    # A committed campaign is immutable: every campaign the history ever recorded must still exist,
    # also when tasks.json was restored to its pre-freeze state (checked before "nothing to check").
    history = History(world)
    committed = history.campaigns()
    for name, files in sorted((committed or {}).items()):
        if name not in names:
            what = "freeze.json" if "freeze.json" in files else sorted(files)[0]
            problems.append(f"{PILOT_REL}/{name}/{what} was committed in {files[what][:12]} and is missing now; a "
                            f"committed campaign is immutable and is never erased (restore {PILOT_REL}/{name} from the "
                            f"Git history; {FREEZE_README})")
    if committed is None and (freeze_pointer is None or history.full):  # else each campaign's note says it
        detail = history.reason or f"git cannot read the history of {PILOT_REL}"
        notes.append(f"check-frozen: not verified without the full Git history ({detail}): whether a committed "
                     "campaign was removed.")
    if freeze_pointer is None:
        for directory in campaigns:
            problems.append(f"{world.display(directory)}/freeze.json exists but {TASKS_REL} has no pilotFreeze")
        if not problems:
            for line in notes:
                print(line, file=out)
            print(f"check-frozen: no frozen campaign ({TASKS_REL} has no pilotFreeze); nothing to check.", file=out)
            return 0
    values: dict[str, tuple[dict, bytes]] = {}
    for directory in campaigns:
        try:
            raw = (directory / "freeze.json").read_bytes()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue  # _integrity reports it
        if isinstance(value, dict):
            values[directory.name] = (value, raw)
    superseded_by: dict[str, str] = {}
    for name, (value, _raw) in values.items():
        target = value.get("supersedes").get("campaign") if isinstance(value.get("supersedes"), dict) else None
        if isinstance(target, str):
            if target in superseded_by:
                problems.append(f"{target} is superseded by both {superseded_by[target]} and {name}")
            superseded_by[target] = name
    if current in superseded_by:
        problems.append(f"{current} is the current campaign but {superseded_by[current]} supersedes it")
    reached: set[str] = set()
    name = current
    while isinstance(name, str) and name in values and name not in reached:
        reached.add(name)
        pointer = values[name][0].get("supersedes")
        name = pointer.get("campaign") if isinstance(pointer, dict) else None
    for directory in campaigns:
        if directory.name == current:
            continue
        before = len(problems)
        if directory.name not in superseded_by:
            problems.append(f"{world.display(directory)} is neither the current campaign nor superseded by one "
                            "(freeze.json supersedes)")
        elif current is not None and directory.name not in reached:
            problems.append(f"{world.display(directory)} is not reached from the current campaign {current} through "
                            "the freeze.json supersedes chain")
        freeze_value = _integrity(world, directory, problems)
        if freeze_value is not None and directory.name in values:
            raw = values[directory.name][1]
            _recorded_fields(world, history, directory.name, freeze_value, raw, names, problems, notes)
            candidate = _candidate_problems(world.display(directory), directory, directory.name, raw)
            problems.extend(candidate[1])  # with or without a summary, freeze.json is the one the candidate names
            _summary_state(world, directory, freeze_value, raw, problems, candidate, notes, history)
            _ledger_problems(world, directory.name, freeze_value, problems)
            _capture_problems(world, history, directory.name, True, problems, notes)
            _summary_history(world, history, directory.name, problems, notes, superseded=True)
        if len(problems) == before:
            notes.append(f"check-frozen: {directory.name} (superseded): hashes intact.")
        _history_note(history, directory.name, notes)
    if current is not None:
        directory = pilot_dir / current
        before = len(problems)
        existing = None
        if not (directory / "freeze.json").is_file():
            problems.append(f"{TASKS_REL} names {freeze_pointer.get('freeze')}, which does not exist")
        else:
            existing = _integrity(world, directory, problems)
        if existing is not None:
            raw = (directory / "freeze.json").read_bytes()
            if existing.get("referenceRevision") != freeze_pointer.get("referenceRevision"):
                problems.append(f"{TASKS_REL} pilotFreeze.referenceRevision differs from {current}/freeze.json")
            held_out = _heldout_projection(manifest)
            if (existing.get("tasksManifest") or {}).get("heldOut") != held_out:
                problems.append(f"{TASKS_REL} held-out fields changed after the freeze of {current} "
                                "(hosts, repetitions, pilotTargets or a held-out task's id, repository, url, commit, "
                                "entrypoints or prompt); a changed reference needs a new campaign")
            _recorded_fields(world, history, current, existing, raw, names, problems, notes)
            _capture_problems(world, history, current, False, problems, notes)
            _summary_history(world, history, current, problems)
            candidate = _candidate_problems(world.display(directory), directory, current, raw)
            problems.extend(candidate[1])
            final = _summary_state(world, directory, existing, raw, problems, candidate, notes, history)
            if final:
                _ledger_problems(world, current, existing, problems)
                if len(problems) == before:
                    notes.append(f"check-frozen: {current} (final summary recorded): hashes intact.")
            else:  # an invalid or missing summary never switches the re-derivation off
                _rederive(world, directory, current, existing, problems, notes, before)
        _history_note(history, current, notes)
    for line in notes:
        print(line, file=out)
    for problem in problems:
        print(f"check-frozen: {problem}", file=out)
    return 1 if problems else 0


def _changed_inputs(world: World, existing: dict) -> list[tuple[str, str]]:
    """(path, how) of each decision file, candidate ledger or repositories.json that differs from the
    freeze: "changed", "missing", or "added" for a decision file the freeze would read now but did not record."""
    changed = []
    for key in ("decisionFiles", "candidateLedgers"):
        recorded = existing.get(key) if isinstance(existing.get(key), dict) else {}
        for rel, digest in sorted(recorded.items()):
            try:
                data = er.confined_file(world.root, rel).read_bytes()
            except (OSError, ValueError):
                changed.append((rel, "missing"))
                continue
            if er.sha256_bytes(data) != digest:
                changed.append((rel, "changed"))
    recorded = existing.get("decisionFiles") if isinstance(existing.get("decisionFiles"), dict) else {}
    changed.extend((rel, "added") for rel in read_decision_files(world) if rel not in recorded)
    repositories = existing.get("repositories") if isinstance(existing.get("repositories"), dict) else {}
    if repositories.get("sha256") != er.sha256_bytes(world.repositories_bytes()):
        changed.append((REPOSITORIES_REL, "changed"))
    return changed


def _recorded_digests(existing: dict) -> dict[str, str]:
    """``{path: sha256}`` of every input the freeze recorded (decision files, ledgers, repositories.json)."""
    found: dict[str, str] = {}
    for key in ("decisionFiles", "candidateLedgers"):
        recorded = existing.get(key) if isinstance(existing.get(key), dict) else {}
        found.update({rel: digest for rel, digest in recorded.items() if isinstance(digest, str)})
    repositories = existing.get("repositories") if isinstance(existing.get("repositories"), dict) else {}
    if isinstance(repositories.get("sha256"), str):
        found[REPOSITORIES_REL] = repositories["sha256"]
    return found


def _rederive(world: World, directory: Path, current: str, existing: dict, problems: list[str], notes: list[str],
              before: int) -> None:
    changed = _changed_inputs(world, existing)
    digests = _recorded_digests(existing)
    history = History(world)
    actions: dict[str, str] = {}  # the next step for a derivation problem that a changed input causes
    for rel, how in changed:
        what = {"missing": f"{rel} (missing) changed", "added": f"{rel} was added"}.get(how, f"{rel} changed")
        advice = restore_advice(world, rel, digests[rel], current, history) if rel in digests else None
        restore = {"changed": f"; if no decision changed, restore the frozen bytes ({advice}): frozen files are "
                              "compared byte for byte, including \">\" lines and line endings",
                   "missing": f"; restore the frozen bytes ({advice})",
                   "added": f"; to keep {current}, remove it"}.get(how, "") if how == "added" or advice else ""
        problems.append(f"{what} after the freeze of {current}; a changed decision needs a new campaign "
                        f"({FREEZE_README}){restore}")
        primary = rel[:-len(".second.md")] + ".md" if rel.endswith(".second.md") else None
        if how == "added":
            action = f"remove {rel} to keep {current}, or freeze a new campaign ({FREEZE_README})"
        elif advice is not None:
            action = f"restore the frozen {rel} ({advice}) to keep {current}, or freeze a new campaign ({FREEZE_README})"
        else:
            continue
        actions[rel] = action
        if primary is not None:  # a second review added, changed or removed after the freeze
            actions.setdefault(primary, action)
    derived = derive_campaign(world, current, frozen_at=existing.get("frozenAt"),
                              tooling=existing.get("tooling"), supersedes=existing.get("supersedes"),
                              existing=existing, verify_corpus=False)
    if derived.problems:
        for what, action in derived.problems:
            for rel, instead in actions.items():
                if what.startswith((f"{rel}:", f"{rel} ")):
                    action = instead
                    break
            problems.append(f"{current} cannot be re-derived: {what}. Next: {action}")
        return
    on_disk = {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()}
    for rel, data in sorted(derived.files.items()):
        try:
            actual = er.confined_file(directory, rel).read_bytes()
        except ValueError as exc:
            problems.append(f"{world.display(directory)}/{rel}: {exc}")
            continue
        if actual != data:
            problems.append(f"{world.display(directory)}/{rel} differs from the re-derivation (an "
                            "edited frozen file, decision file, ledger or manifest)")
    for rel in sorted(on_disk - set(derived.files)):
        if rel.startswith(("reference/", "prompts/")) or rel in ("reference-set.json", "policy.json"):
            problems.append(f"{world.display(directory)}/{rel} is not produced by the freeze")
    if len(problems) == before:
        absent = [task.get("repository") for task in world.heldout if world.repo_dir(task) is None]
        notes.append(f"check-frozen: {current} re-derived byte for byte ({len(world.heldout)} "
                     f"references, reference-set.json, policy.json, {2 * len(world.heldout)} prompts, "
                     "freeze.json); held-out tasks.json fields unchanged.")
        if len(absent) == len(world.heldout):
            notes.append("source hashes not re-read: corpus absent")
        elif absent:
            notes.append(f"source hashes not re-read for {', '.join(absent)}: corpus absent")


# --------------------------------------------------------------------------------------------
# Command line


def command_template(world: World, args, out) -> int:
    targets = template_targets(world)
    if args.init_all:
        if args.target or args.second or args.show:
            raise UsageError("--init-all takes no target, --second or --show")
        files = {name: path for name, (path, _generate) in targets.items()}
        readme = world.decisions_dir / "README.md"
        existing = [world.display(path) for path in [*files.values(), readme] if path.exists()]
        if existing:
            print("template --init-all: refusing; these files already exist and templates are never overwritten: "
                  + ", ".join(existing), file=out)
            return 1
        for name, (path, generate) in targets.items():
            er.write_exclusive(path, generate().encode("utf-8"))
            print(f"created {world.display(path)}", file=out)
        er.write_exclusive(readme, README_TEXT.encode("utf-8"))
        print(f"created {world.display(readme)}", file=out)
        print("Every value is pending. Only the named reviewer replaces them; the tool never writes decisions.",
              file=out)
        return 0
    if not args.target:
        raise UsageError("template needs a TARGET (a held-out task ID, run-policy or development-adjudication) or "
                         "--init-all")
    name = args.target
    if name not in targets:
        raise UsageError(f"{name} is not a held-out task ID, {POLICY_TARGET} or {ADJUDICATION_TARGET}")
    if args.second:
        if world.heldout_task(name) is None:
            raise UsageError("--second applies to a held-out task")
        path = world.decisions_dir / f"{name}.second.md"
        text = task_template(world, name, second=True)
    else:
        path, generate = targets[name]
        text = generate()
    if args.show:
        out.write(text)
        return 0
    try:
        er.write_exclusive(path, text.encode("utf-8"))
    except FileExistsError:
        print(f"{world.display(path)} already exists; templates are created exclusively and never overwritten. "
              f"Use {TEMPLATE_COMMAND} --show {name}{' --second' if args.second else ''} to print a pristine copy.",
              file=out)
        return 1
    print(f"created {world.display(path)} (every value pending; check it with {CHECK_COMMAND} {name})", file=out)
    return 0


def command_context(world: World, args, out) -> int:
    text, facts, anchors, mismatches = context_sheet(world, args.task)
    output = Path(args.output) if args.output else world.root / CONTEXT_REL / f"{args.task}.md"
    er.write_atomic(output, text.encode("utf-8"))
    state = "all quotes verified" if not mismatches else f"{len(mismatches)} anchor(s) NOT verified"
    print(f"wrote {world.display(output)} ({facts} facts, {anchors} anchors, {state}); local and gitignored, "
          "do not commit it", file=out)
    for mismatch in mismatches:
        print(f"  mismatch: {mismatch}", file=out)
    return 1 if mismatches else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workflow_eval.py", description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    template = sub.add_parser("template", help="write a pending template (exclusive create)")
    template.add_argument("target", nargs="?", help="a held-out task ID, run-policy or development-adjudication")
    template.add_argument("--second", action="store_true", help="the second-review file of a task")
    template.add_argument("--show", action="store_true", help="print the pristine file instead of writing it")
    template.add_argument("--init-all", action="store_true",
                          help="create every committed template and the README (once; refuses existing files)")
    check = sub.add_parser("check", help="check owner files; never writes")
    check.add_argument("targets", nargs="*", help="task IDs, run-policy, development-adjudication or file paths")
    check.add_argument("--show-prompts", action="store_true", help="also print the 16 prompt renderings")
    context = sub.add_parser("context", help="write the local source-context sheet of one task")
    context.add_argument("task")
    context.add_argument("--output", help="the sheet's path (default .mlview/review-context/<task>.md)")
    freeze_parser = sub.add_parser("freeze", help="freeze a campaign (dry run unless --write)")
    freeze_parser.add_argument("--campaign", required=True)
    freeze_parser.add_argument("--write", action="store_true")
    freeze_parser.add_argument("--frozen-at", help="the RFC 3339 UTC freeze time (default: now)")
    freeze_parser.add_argument("--supersede-reason", help="why a new campaign supersedes the frozen one")
    sub.add_parser("check-frozen", help="re-derive the committed frozen campaign and require byte equality")
    return parser


def main(argv: Sequence[str] | None = None, *, root: Path | None = None, corpus: object = _DEFAULT,
         out=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    out = sys.stdout if out is None else out
    parser = build_parser()
    try:
        args = parser.parse_args(arguments)
    except SystemExit as exc:
        return int(exc.code or 0) if exc.code in (0, None) else 2
    world = World(root or ROOT, corpus)
    try:
        if args.command == "template":
            return command_template(world, args, out)
        if args.command == "check":
            return command_check(world, args.targets, show=args.show_prompts, out=out)
        if args.command == "context":
            return command_context(world, args, out)
        if args.command == "freeze":
            return freeze(world, args.campaign, write=args.write, frozen_at=args.frozen_at,
                          supersede_reason=args.supersede_reason, out=out)
        if args.command == "check-frozen":
            return check_frozen(world, out)
    except UsageError as exc:
        print(f"workflow_eval.py {args.command}: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"workflow_eval.py {args.command}: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
