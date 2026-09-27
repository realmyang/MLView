"""Tests for tools/eval_records.py (the shared Campaign 2 evaluation primitives) and the
workflow_eval.py command dispatcher. No network is used, no model runs, and every decision file
here is synthetic (IDs demo-*, reviewer "Test Reviewer (synthetic)"). These are local tooling
checks, not semantic accuracy, human review or live-host validation."""
from __future__ import annotations

import base64
import copy
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
import eval_records as er  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("workflow_eval_dispatch_under_test", ROOT / "tools" / "workflow_eval.py")
workflow_eval = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader
_SPEC.loader.exec_module(workflow_eval)
_BRIDGE_SPEC = importlib.util.spec_from_file_location("eval_records_conformance_bridge",
                                                      ROOT / "contracts" / "conformance" / "helper_bridge.py")
bridge = importlib.util.module_from_spec(_BRIDGE_SPEC)
assert _BRIDGE_SPEC.loader
_BRIDGE_SPEC.loader.exec_module(bridge)

EM, EN = chr(0x2014), chr(0x2013)
BOM = b"\xef\xbb\xbf"
HAS_GIT = shutil.which("git") is not None
needs_git = pytest.mark.skipif(not HAS_GIT, reason="git is not installed")

# A synthetic reference-decisions template in the shape of the Campaign 2 specification, section 1.4.
TEMPLATE = """# Reference decisions: pilot-demo

> Guide: evals/workflow/reference-candidates/REVIEW_GUIDE.md. Check: python tools/workflow_eval.py check pilot-demo
> Lines starting with ">" are written by the tool and ignored. Replace each "pending".

Candidate: pilot-demo.json 0000000000000000000000000000000000000000000000000000000000000000
Reviewer:
Date:
Transcribed by:

## Scenario
> Proposed: Inspect train.py with its source defaults (synthetic).
> Entrypoints: train.py
> Arguments: none
Decision: pending

## Fact demo-f01
> Claim: The synthetic default is 40 micro-steps.
> Basis: observed. Essential: yes. Anchors: train.py:48-49
Decision: pending

## Unknown demo-u01
> A synthetic uncertainty.
Decision: pending
Runs must state:

## Non-defect demo-n01
> A synthetic intentional behaviour.
Decision: pending

## Disagreements
> Only when a second reviewer disagrees: one line "<item id>: <how it was resolved>".

## Task
> Write "Review: complete" when every decision above is final.
Review: pending
"""


def parse(text: str | bytes, path: str = "evals/workflow/decisions/pilot-demo.md"):
    raw = text.encode("utf-8") if isinstance(text, str) else text
    return er.parse_record(raw, path)


def shape(record: er.Record) -> list:
    """Everything a checker sees, without the path and hash."""
    return [(record.kind, record.ident, record.title, record.header.line,
             [(f.key, f.value, f.line) for f in record.header.lines])] + [
        (s.kind, s.ident, s.line, [(f.key, f.value, f.line) for f in s.lines], s.fence, s.fence_line)
        for s in record.sections]


def messages(problems: list[er.Problem]) -> list[str]:
    return [str(problem) for problem in problems]


# --------------------------------------------------------------------------------------------
# Grammar


def test_pristine_template_parses_with_line_numbers() -> None:
    record, problems = parse(TEMPLATE)
    assert problems == []
    assert record is not None
    assert (record.kind, record.ident, record.title) == ("Reference decisions", "pilot-demo", "Reference decisions: pilot-demo")
    assert record.header.label == "header" and record.header.line == 1
    assert [(f.key, f.value, f.line) for f in record.header.lines] == [
        ("Candidate", "pilot-demo.json " + "0" * 64, 6), ("Reviewer", "", 7), ("Date", "", 8), ("Transcribed by", "", 9)]
    assert [(s.label, s.line) for s in record.sections] == [
        ("Scenario", 11), ("Fact demo-f01", 17), ("Unknown demo-u01", 22), ("Non-defect demo-n01", 27),
        ("Disagreements", 31), ("Task", 34)]
    unknown = record.section("Unknown", "demo-u01")
    assert unknown.fields["Decision"].value == "pending" and unknown.fields["Decision"].line == 24
    assert unknown.value("runs must state") == "" and unknown.value("Wording") is None
    assert record.section("Disagreements").lines == []
    assert record.section("Task").value("Review") == "pending"
    assert record.sha256 == er.sha256_bytes(TEMPLATE.encode("utf-8"))


def test_bom_and_every_line_ending_give_the_same_record() -> None:
    lf = TEMPLATE.encode("utf-8")
    variants = [lf, lf.replace(b"\n", b"\r\n"), lf.replace(b"\n", b"\r"), BOM + lf.replace(b"\n", b"\r\n")]
    parsed = [er.parse_record(raw, "d.md") for raw in variants]
    assert all(problems == [] for _record, problems in parsed)
    assert all(shape(record) == shape(parsed[0][0]) for record, _problems in parsed)
    assert [record.sha256 for record, _ in parsed] == [er.sha256_bytes(raw) for raw in variants]
    assert len({record.sha256 for record, _ in parsed}) == 4


def test_trailing_spaces_blank_and_quote_lines_are_ignored_but_counted() -> None:
    text = "\n".join([
        "# Reference decisions: pilot-demo   ",
        "   > an indented tool note",
        "",
        "Reviewer: Test Reviewer (synthetic)   \t",
        "> note",
        "## Fact demo-f01   ",
        ">Decision: accept",
        "Decision:   accept   ",
    ])
    record, problems = parse(text)
    assert problems == []
    assert record.header.fields["Reviewer"].value == "Test Reviewer (synthetic)"
    fact = record.section("Fact", "demo-f01")
    assert (fact.line, fact.fields["Decision"].value, fact.fields["Decision"].line) == (6, "accept", 8)


def test_continuation_lines_join_with_one_space() -> None:
    text = "\n".join([
        "# Reference decisions: pilot-demo",
        "## Fact demo-f01",
        "Decision: qualify",
        "Wording: Without DDP the count is 40",
        "  micro-steps;",
        "",
        "> a note between continuation lines",
        "\tunder DDP it is divided.",
        "Reason:",
        "    Lines 94-95 divide it.",
        "Essentail: no",
        "  swallowed with the unknown field",
        "  Anchors: train.py:48-49",
    ])
    record, problems = parse(text)
    fact = record.section("Fact", "demo-f01")
    assert fact.value("Wording") == "Without DDP the count is 40 micro-steps; under DDP it is divided."
    assert fact.value("Reason") == "Lines 94-95 divide it."
    assert fact.value("Anchors") is None
    assert messages(problems) == [
        'evals/workflow/decisions/pilot-demo.md:11: ERROR Fact demo-f01: unknown field "Essentail". '
        "Allowed here: Anchors, Basis, Decision, Essential, Reason, Wording."]


def test_indented_key_after_a_heading_is_a_key() -> None:
    record, problems = parse("# Reference decisions: pilot-demo\n## Fact demo-f01\n  Decision: accept\n")
    assert problems == [] and record.section("Fact", "demo-f01").value("Decision") == "accept"


POLICY = """# Pilot run policy

Reviewer:
Date:
Transcribed by:

## Host copilot
Model:
Reasoning:
Invocation:

## Skill prompt
> Placeholders: {task_prompt} {scenario} {artifact_path}.
```text
{task_prompt}

Selected scenario:
{scenario}
> kept: this line is inside the fence
## kept: so is this heading
    Indented: kept verbatim
Publish one WorkflowDocument to {artifact_path}.
```
Decision: pending

## Task
Review: pending
"""


def test_fence_is_captured_verbatim_and_the_section_continues() -> None:
    record, problems = parse(POLICY, "evals/workflow/decisions/run-policy.md")
    assert problems == []
    prompt = record.section("Skill prompt")
    assert prompt.fence == "\n".join([
        "{task_prompt}", "", "Selected scenario:", "{scenario}", "> kept: this line is inside the fence",
        "## kept: so is this heading", "    Indented: kept verbatim", "Publish one WorkflowDocument to {artifact_path}."])
    assert prompt.fence_line == 14
    assert prompt.fields["Decision"].line == 24
    assert [s.label for s in record.sections] == ["Host copilot", "Skill prompt", "Task"]
    crlf, crlf_problems = er.parse_record(POLICY.replace("\n", "\r\n").encode(), "p.md")
    assert crlf_problems == [] and crlf.section("Skill prompt").fence == prompt.fence


def test_fence_errors_name_the_line_and_section() -> None:
    text = "\n".join([
        "# Pilot run policy",            # 1
        "```text",                      # 2 header: not allowed
        "x",
        "```",
        "## Budget",                    # 5
        "```",                          # 6 not allowed
        "Active minutes: 20",           # 7 swallowed inside the fence
        "```",
        "## Skill prompt",              # 9
        "```python",                    # 10 wrong info string, still captured
        "{task_prompt}",
        "```",
        "```text",                      # 13 second fence
        "again",
        "```",
        "## No-skill prompt",           # 16
        "```text",                      # 17 never closed
        "{task_prompt}",
        "## Task",
    ])
    record, problems = parse(text, "run-policy.md")
    assert messages(problems) == [
        "run-policy.md:2: ERROR header: a fenced block (```) is not allowed here; only the run-policy prompt sections take one.",
        "run-policy.md:6: ERROR Budget: a fenced block (```) is not allowed here; only the run-policy prompt sections take one.",
        'run-policy.md:10: ERROR Skill prompt: write the opening fence as "```text".',
        "run-policy.md:13: ERROR Skill prompt: this section already has a fenced block (line 10); keep one.",
        "run-policy.md:17: ERROR No-skill prompt: this fenced block is never closed; add a line with ``` after it.",
    ]
    _record, problems = parse("# Pilot run policy\n## Budget\n## Budget\n```\nskipped\n", "run-policy.md")
    assert messages(problems) == [
        "run-policy.md:3: ERROR Budget: this section appears twice (first on line 2). Keep one.",
        "run-policy.md:4: ERROR Budget: this fenced block is never closed; add a line with ``` after it."]
    assert record.section("Budget").lines == []
    assert record.section("Skill prompt").fence == "{task_prompt}"
    assert record.section("No-skill prompt").fence is None
    assert record.section("Task") is None


def test_repeated_keys_and_sections_are_errors() -> None:
    text = TEMPLATE.replace("Decision: pending\n\n## Unknown", "Decision: pending\ndecision: accept\n\n## Unknown")
    text += "\n## Fact demo-f01\nDecision: accept\n"
    record, problems = parse(text)
    assert messages(problems) == [
        'evals/workflow/decisions/pilot-demo.md:21: ERROR Fact demo-f01: "decision" appears twice (first on line 20). Keep one.',
        "evals/workflow/decisions/pilot-demo.md:39: ERROR Fact demo-f01: this section appears twice (first on line 17). Keep one.",
    ]
    assert record.section("Fact", "demo-f01").value("Decision") == "pending"
    assert len(record.find("Fact")) == 1


def test_unknown_sections_keys_and_ids_are_errors() -> None:
    text = "\n".join([
        "# Reference decisions: pilot-demo",
        "Reviewr: someone",
        "## Facts demo-f01",
        "Decision: accept",
        "## Fact",
        "## Task now",
        "## Fact demo f01",
        "## Unknown demo-u01",
        "Runs  MUST state: yes",
    ])
    record, problems = parse(text, "d.md")
    skipped = ' The lines after it, up to the next "## " heading, were not read.'  # OWNERUX4-6
    assert messages(problems) == [
        'd.md:2: ERROR header: unknown field "Reviewr". Allowed here: Candidate, Date, Reviewer, Transcribed by.',
        'd.md:3: ERROR Facts demo-f01: unknown section "## Facts demo-f01". Sections: Scenario, Fact <id>, Unknown <id>, '
        "Non-defect <id>, Added fact <id>, Added unknown <id>, Defect <id>, Disagreements, Task." + skipped,
        'd.md:5: ERROR Fact: section "## Fact" needs an ID: write "## Fact <id>".' + skipped,
        'd.md:6: ERROR Task now: section "## Task" takes no ID: write "## Task".' + skipped,
        'd.md:7: ERROR Fact demo f01: section IDs are one word: "## Fact demo f01".' + skipped,
    ]
    assert [s.label for s in record.sections] == ["Unknown demo-u01"]
    assert record.sections[0].fields["Runs must state"].value == "yes"


def test_any_other_line_is_an_error_and_its_continuation_is_swallowed() -> None:
    text = ("# Reference decisions: pilot-demo\n## Fact demo-f01\n"
            "I think this claim is right but the anchor is a little off\n  more words\nDecision: accept\n")
    record, problems = parse(text, "d.md")
    assert messages(problems) == [
        'd.md:3: ERROR Fact demo-f01: "I think this claim is right but the anch" is not "Key: value". Put ">" in front of notes.']
    assert record.section("Fact", "demo-f01").value("Decision") == "accept"


def test_an_unindented_wrapped_line_gets_the_continuation_hint() -> None:
    text = ("# Reference decisions: pilot-demo\n## Fact demo-f01\nDecision: reject\n"
            "Reason: the loop divides by the number of steps, which is\nintentional scaling in this synthetic file\n"
            "Reason2: x\n\nwrapped after a blank line\n")
    record, problems = parse(text, "d.md")
    assert messages(problems)[0] == (
        'd.md:5: ERROR Fact demo-f01: "intentional scaling in this synthetic fi" is not "Key: value". To continue the '
        'previous line, indent it by two spaces; put ">" in front of notes only.')
    assert messages(problems)[-1].endswith('is not "Key: value". Put ">" in front of notes.')
    wrapped = ("# Reference decisions: pilot-demo\n## Fact demo-f01\nReason: the loop keeps going because of this\n"
               "reason: continues here, oddly\n")
    assert parse(wrapped, "d.md")[0].section("Fact", "demo-f01").value("Reason") == "the loop keeps going because of this"


@pytest.mark.parametrize("heading", ["### Fact demo-f02", "##Fact demo-f02", "#  Fact demo-f02"])
def test_a_mistyped_heading_is_named_and_does_not_blame_the_previous_section(heading: str) -> None:
    text = (f"# Reference decisions: pilot-demo\n## Fact demo-f01\nDecision: accept\n{heading}\nDecision: reject\n"
            "Reason: synthetic\n")
    record, problems = parse(text, "d.md")
    assert messages(problems) == [f'd.md:4: ERROR Fact demo-f02: "{heading}" is not a section heading; write '
                                  '"## Fact demo-f02" (two # and a space).']
    assert record.section("Fact", "demo-f01").value("Decision") == "accept"
    assert record.section("Fact", "demo-f02").value("Decision") == "reject"


def test_an_unknown_mistyped_heading_skips_its_lines() -> None:
    text = "# Reference decisions: pilot-demo\n## Fact demo-f01\nDecision: accept\n### My notes\nDecision: reject\n"
    record, problems = parse(text, "d.md")
    assert len(problems) == 1 and "is not a section heading. Write section headings as" in problems[0].message
    assert record.section("Fact", "demo-f01").value("Decision") == "accept"


def test_a_hash_comment_keeps_its_section_and_the_fields_around_it() -> None:
    """A Python-style "# comment" is an error under the enclosing section, never skip mode (OWNERUX2-1)."""
    text = ("# Reference decisions: pilot-demo\n# reviewed on the train, synthetic\nCandidate: pilot-demo.json abc\n"
            "Reviewer: Test Reviewer (synthetic)\nDate: 2026-10-01\n## Fact demo-f01\n#1 priority for me\n"
            "Decision: qualify\n# TODO double-check the value\nWording: The synthetic claim (synthetic).\n"
            "Reason: synthetic\n")
    record, problems = parse(text, "d.md")
    hint = 'is not "Key: value". Put ">" in front of notes; "#" does not start a comment.'
    assert messages(problems) == [
        f'd.md:2: ERROR header: "# reviewed on the train, synthetic" {hint}',
        f'd.md:7: ERROR Fact demo-f01: "#1 priority for me" {hint}',
        f'd.md:9: ERROR Fact demo-f01: "# TODO double-check the value" {hint}']
    assert record.header.value("Candidate") == "pilot-demo.json abc"
    assert record.header.value("Reviewer") == "Test Reviewer (synthetic)" and record.header.value("Date") == "2026-10-01"
    fact = record.section("Fact", "demo-f01")
    assert (fact.value("Decision"), fact.value("Wording"), fact.value("Reason")) == (
        "qualify", "The synthetic claim (synthetic).", "synthetic")
    # An indented line after a comment is not attributed to the value above the comment.
    swallowed, _problems = parse("# Reference decisions: pilot-demo\n## Fact demo-f01\nReason: kept\n# note\n  more\n",
                                 "d.md")
    assert swallowed.section("Fact", "demo-f01").value("Reason") == "kept"


@pytest.mark.parametrize("section, line, fields", [
    ("Fact demo-f04", "# Fact checked", "Decision: qualify\n# Fact checked\nWording: The corrected claim (synthetic).\n"
                                        "Reason: synthetic\n"),
    ("Defect demo-d01", "# Defect confirmed", "Wording: A synthetic defect.\n# Defect confirmed\nSeverity: low\n"
                                              "Anchors: train.py:1\nCounter-evidence: none\nReason: synthetic\n"),
])
def test_a_one_hash_line_with_a_kind_and_a_plain_word_is_a_comment(section: str, line: str, fields: str) -> None:
    """"# Fact checked" is a comment under the enclosing section, not a phantom "## Fact checked" section:
    every reference item ID has a digit (OWNERUX4-5). A real item ID still starts that item."""
    text = f"# Reference decisions: pilot-demo\n## {section}\n{fields}"
    record, problems = parse(text, "d.md")
    number = 3 + fields.split("\n").index(line)
    assert messages(problems) == [f'd.md:{number}: ERROR {section}: "{line}" is not "Key: value". Put ">" in front of '
                                  'notes; "#" does not start a comment.']
    kept = record.section(*section.split(" "))
    assert kept is not None and kept.value("Reason") == "synthetic" and len(record.sections) == 1
    record, problems = parse("# Reference decisions: pilot-demo\n## Fact demo-f01\nDecision: accept\n# Fact demo-f02\n"
                             "Decision: reject\n", "d.md")
    assert record.section("Fact", "demo-f02").value("Decision") == "reject"
    # The policy's host IDs have no digit, so the rule is limited to the reference item kinds.
    policy, problems = parse("# Pilot run policy\n# Host codex\nModel: m (synthetic)\n", "p.md")
    assert [s.label for s in policy.sections] == ["Host codex"]


def test_an_unknown_two_hash_heading_says_its_lines_were_not_read() -> None:
    """A well-formed but unknown "## Notes" heading skips the lines after it, and its error says so (OWNERUX4-6)."""
    text = "# Reference decisions: pilot-demo\n## Fact demo-f07\n## Notes\nDecision: accept\n"
    record, problems = parse(text, "d.md")
    assert len(problems) == 1 and problems[0].message.endswith(
        'The lines after it, up to the next "## " heading, were not read.'), problems
    assert record.section("Fact", "demo-f07").value("Decision") is None


@pytest.mark.parametrize("line", ["# Facts demo-f02", "# Facts", "#### My notes", "##Notes", "# Added facts x-h01",
                                  "### Fact checked"])
def test_a_heading_like_hash_line_still_skips_its_lines(line: str) -> None:
    text = f"# Reference decisions: pilot-demo\n## Fact demo-f01\nDecision: accept\n{line}\nDecision: reject\n"
    record, problems = parse(text, "d.md")
    assert len(problems) == 1 and "is not a section heading. Write section headings as" in problems[0].message
    assert 'The lines after it, up to the next "## " heading, were not read.' in problems[0].message
    assert record.section("Fact", "demo-f01").value("Decision") == "accept"


@pytest.mark.parametrize("line, section", [
    ("# Scenario checked", "Scenario"), ("# Task done", "Task"), ("# Defects none", "Scenario"),
    ("# Disagreements none", "Scenario"), ("# Facts checked", "Scenario"), ("# Non-defects ok", "Scenario")])
def test_a_one_hash_kind_and_a_word_that_cannot_be_its_id_is_a_comment(line: str, section: str) -> None:
    """"# Scenario checked" and "# Task done" (kinds that take no ID) and "# Defects none" (no digit) are
    comments under the enclosing section, which keeps the decisions around them (OWNERUX5-6)."""
    fields = {"Scenario": "Decision: accept\n{line}\nReason: synthetic\n", "Task": "{line}\nReview: complete\n"}
    text = f"# Reference decisions: pilot-demo\n## {section}\n" + fields[section].format(line=line)
    record, problems = parse(text, "d.md")
    assert messages(problems) == [f'd.md:{text.split(chr(10)).index(line) + 1}: ERROR {section}: "{line}" is not '
                                  '"Key: value". Put ">" in front of notes; "#" does not start a comment.']
    kept = record.section(section)
    assert kept is not None and len(record.sections) == 1
    assert (kept.value("Decision"), kept.value("Reason")) == ("accept", "synthetic") if section == "Scenario" \
        else kept.value("Review") == "complete"


def test_a_mistyped_heading_with_a_wrong_id_keeps_its_lines_as_documented() -> None:
    """"# Fact v2" names an ID with a digit, so it starts the item "Fact v2" (not an item of the task), and
    the lines after it belong to it: REVIEW_GUIDE says so, and the check says where the lines went (SPECDOCS5-2)."""
    text = "# Reference decisions: pilot-demo\n## Fact demo-f02\n# Fact v2\nDecision: accept\n"
    record, problems = parse(text, "d.md")
    assert [section.label for section in record.sections] == ["Fact demo-f02", "Fact v2"]
    assert record.section("Fact", "v2").value("Decision") == "accept"
    assert messages(problems) == ['d.md:3: ERROR Fact v2: "# Fact v2" is not a section heading; write "## Fact v2" (two '
                                  '# and a space).']


@pytest.mark.parametrize("line", ["# added the randint detail", "# fact wording changed",
                                  "# unknown whether val.bin exists", "# scenario matters here"])
def test_a_comment_starting_with_a_section_word_keeps_the_decisions_after_it(line: str) -> None:
    """Only a kind plus at most one ID-like word looks like a heading; prose is a comment (OWNERUX3-1)."""
    text = (f"# Reference decisions: pilot-demo\n## Fact demo-f01\nDecision: qualify\n{line}\n"
            "Wording: The synthetic claim (synthetic).\nReason: synthetic\n")
    record, problems = parse(text, "d.md")
    assert messages(problems) == [f'd.md:4: ERROR Fact demo-f01: "{line}" is not "Key: value". Put ">" in front of '
                                  'notes; "#" does not start a comment.']
    fact = record.section("Fact", "demo-f01")
    assert (fact.value("Decision"), fact.value("Wording"), fact.value("Reason")) == (
        "qualify", "The synthetic claim (synthetic).", "synthetic")
    task, _problems = parse("# Reference decisions: pilot-demo\n## Task\n# Task done, signing off\nReview: complete\n",
                            "d.md")
    assert task.section("Task").value("Review") == "complete"
    policy, problems = parse("# Pilot run policy\n## Budget\nActive minutes: 20\n# budget agreed with ops\n"
                             "Repair rounds: 2\nInfrastructure retries: 0\n", "run-policy.md")
    budget = policy.section("Budget")
    assert (budget.value("Repair rounds"), budget.value("Infrastructure retries")) == ("2", "0")
    assert len(problems) == 1 and '"#" does not start a comment' in problems[0].message


def test_a_wrapped_line_after_a_blank_or_note_line_gets_the_continuation_hint() -> None:
    """A wrapped value separated by a blank or ">" line is still told to indent (OWNERUX2-6)."""
    for between in ("\n", "> a note (synthetic)\n"):
        text = ("# Reference decisions: pilot-demo\n## Fact demo-f01\nDecision: reject\n"
                f"Reason: the claim omits the condition that\n{between}config files can override it\n")
        _record, problems = parse(text, "d.md")
        assert messages(problems) == [
            'd.md:6: ERROR Fact demo-f01: "config files can override it" is not "Key: value". To continue the previous '
            'line, indent it by two spaces; put ">" in front of notes only.']
        indented = text.replace("\nconfig files", "\n  config files")
        record, problems = parse(indented, "d.md")
        assert problems == []
        assert record.section("Fact", "demo-f01").value("Reason") == ("the claim omits the condition that config files "
                                                                      "can override it")


def test_keys_section_kinds_and_titles_are_case_insensitive() -> None:
    text = "# reference DECISIONS: pilot-demo\nREVIEWER: Test Reviewer (synthetic)\n## fact demo-f01\ndecision: ACCEPT\n"
    record, problems = parse(text)
    assert problems == []
    assert record.kind == "Reference decisions" and record.title == "reference DECISIONS: pilot-demo"
    assert record.header.fields["Reviewer"].key == "Reviewer"
    fact = record.sections[0]
    assert (fact.kind, fact.ident, fact.fields["Decision"].value) == ("Fact", "demo-f01", "ACCEPT")


def test_problem_string_pads_the_level() -> None:
    assert str(er.Problem("a.md", 9, er.TODO, "header", "Reviewer is empty.")) == "a.md:9: TODO  header: Reviewer is empty."
    assert str(er.Problem("a.md", 3, er.ERROR, "Task", "x")) == "a.md:3: ERROR Task: x"
    assert str(er.Problem("a.md", 1, er.NOTE, "Defect demo-d01", "y")) == "a.md:1: NOTE  Defect demo-d01: y"


@pytest.mark.parametrize("raw, line, message", [
    (b"", 1, "the file is empty; restore it from the template."),
    (b"> only notes\n\n", 1, "the file is empty; restore it from the template."),
    (b"\n\nReviewer: x\n", 3, 'the first line must be the title the tool wrote, for example "# Reference decisions: <task>".'),
    (b"# Pilot run policy: extra\n", 1, 'the title must read "# Pilot run policy".'),
    (b"# Reference decisions\n", 1, 'the title must read "# Reference decisions: <id>", with a one-word ID.'),
    (b"# Reference decisions: two words\n", 1, 'the title must read "# Reference decisions: <id>", with a one-word ID.'),
    (b"# Reference decisions: x\r\nReviewer: \xff\n", 2, "the file is not valid UTF-8; save it as UTF-8."),
])
def test_files_without_a_usable_title_return_no_record(raw: bytes, line: int, message: str) -> None:
    record, problems = er.parse_record(raw, "d.md")
    assert record is None
    assert [(p.line, p.level, p.section, p.message) for p in problems] == [(line, er.ERROR, "header", message)]


def test_unknown_title_lists_the_known_titles() -> None:
    record, problems = er.parse_record(b"# Notes: x\n", "d.md")
    assert record is None and len(problems) == 1
    assert problems[0].message.startswith("the first line must be the title the tool wrote. Known titles: ")
    for title in ('"# Reference decisions: <id>"', '"# Pilot run policy"', '"# Development adjudication"',
                  '"# Session: <id>"', '"# Run review: <id>"', '"# Second review: <id>"', '"# Invalidation: <id>"'):
        assert title in problems[0].message


def test_free_key_sections_keep_pointer_keys_and_case() -> None:
    text = "\n".join([
        "# Run review: pilot-demo:codex:1",
        "Run: pilot-demo:codex:1",
        "Artifact: " + "a" * 64,
        "Reference: sha256:" + "b" * 64,
        "Reviewer: Test Reviewer (synthetic)",
        "## Claims",
        "node:load-batches: pending",
        "node:load-batches#2: qualified " + EM + " scope: too broad",
        "node:Load-Batches: supported",
        "coverage: pending",
        "response:12-14: supported",
        "## Essential facts",
        "demo-f01: covered node:load-batches edge:e-ckpt",
        "## Usability",
        "DATAORIGIN: clear",
        "task: useful",
        "## Task",
        "Review: pending",
    ])
    record, problems = parse(text, "review.md")
    assert problems == []
    claims = record.section("Claims")
    assert [(f.key, f.value) for f in claims.lines] == [
        ("node:load-batches", "pending"), ("node:load-batches#2", "qualified " + EM + " scope: too broad"),
        ("node:Load-Batches", "supported"), ("coverage", "pending"), ("response:12-14", "supported")]
    assert record.section("Essential facts").fields["demo-f01"].value == "covered node:load-batches edge:e-ckpt"
    assert record.section("Usability").fields["dataOrigin"].value == "clear"
    assert er.parse_verdict(claims.fields["node:load-batches#2"].value, {"supported", "qualified"}) == (
        "qualified", [], "scope: too broad")


def test_session_deviations_and_disagreements_are_free_lines() -> None:
    session = "\n".join([
        "# Session: pilot-demo:codex:1",
        "Status: completed",
        "Started: 2026-10-10T09:02:11Z",
        "MLView available to host: yes",
        "## Deviations",
        "Host restarted at 10:05, prompt resent " + EM + " invalidates: no",
        "Note: synthetic " + EM + " invalidates: yes",
    ])
    record, problems = parse(session, "session.md")
    assert problems == []
    assert record.header.value("mlview available to host") == "yes"
    assert [(f.key, f.value) for f in record.section("Deviations").lines] == [
        ("Host restarted at 10:05, prompt resent " + EM + " invalidates", "no"),
        ("Note", "synthetic " + EM + " invalidates: yes")]
    decisions = TEMPLATE.replace(
        "## Disagreements\n", "## Disagreements\ndemo-f01: kept qualify: lines 94-95 decide it\ndemo-f01: again\n")
    record, problems = parse(decisions, "d.md")
    assert messages(problems) == ['d.md:33: ERROR Disagreements: "demo-f01" appears twice (first on line 32). Keep one.']
    assert record.section("Disagreements").fields["demo-f01"].value == "kept qualify: lines 94-95 decide it"


SPEC_FILES = {
    "second": ("# Second review: pilot-demo\nCandidate: pilot-demo.json " + "0" * 64 + "\nReviewer:\nDate:\n"
               "Transcribed by:\n## Scenario\nDecision: pending\n## Fact demo-f01\nDecision: pending\n"
               "## Added fact demo-h01\nWording:\nBasis:\nEssential:\nAnchors:\nReason:\n"
               "## Added unknown demo-hu01\nWording:\nRuns must state:\nReason:\n## Defect demo-d01\nWording:\n"
               "Severity:\nAnchors:\nCounter-evidence:\nReason:\n## Task\nReview: pending\n"),
    "policy": ("# Pilot run policy\nReviewer:\nDate:\nTranscribed by:\n## Host copilot\nModel:\nReasoning:\nInvocation:\n"
               "## Host codex\nModel:\nReasoning:\nInvocation:\n## Host claude-code\nModel:\nReasoning:\nInvocation:\n"
               "## Environment\nHelper Python:\n## Budget\nActive minutes:\nRepair rounds:\nInfrastructure retries:\n"
               "## Scoring\nQualified claims:\nPer-host targets:\n## Conditions\nBaseline sessions:\n"
               "Development adjudication before Stage 1:\n## Targets\nDecision: pending\n## Skill prompt\n```text\n"
               "{task_prompt}\n```\nDecision: pending\n## No-skill prompt\n```text\n{task_prompt}\n```\n"
               "Decision: pending\n## Privacy\nPublication:\n## Task\nReview: pending\n"),
    "adjudication": ("# Development adjudication\nReviewer:\nDate:\nTranscribed by:\n## dev-gan / codex\n"
                     "Ledger: native-reviews/codex/dev-gan.json " + "0" * 64 + "\n"
                     "> optimizer-ownership (provisional: supported): synthetic.\noptimizer-ownership: pending\n"
                     "usability.losses: pending\n## dev-config / claude-code\nusability.outputs: pending\n"
                     "## Baselines\nLedger: native-reviews/baselines.json " + "0" * 64 + "\ncodex: pending\n"
                     "claude-code: pending\ncopilot: pending\n## Task\nReview: pending\n"),
    "session": ("# Session: pilot-demo:codex:baseline:1\nStatus: pending\nFailure:\nStarted:\nEnded:\nActive minutes:\n"
                "Approval wait minutes:\nRepair rounds:\nHost version:\nExtension version:\nModel:\nReasoning:\n"
                "Resolved model:\nInvocation:\nHelper Python:\nUsage:\nTranscript: transcript.txt\nUI log: ui-log.md\n"
                "Prior attempts: 0\nMLView available to host: no\n## Deviations\n"),
    "review": ("# Run review: pilot-demo:codex:1\nRun: pilot-demo:codex:1\nArtifact: " + "a" * 64 + "\n"
               "Reference: sha256:" + "b" * 64 + "\nReviewer:\nDate:\n## Claims\nnode:load-batches: pending\n"
               "finding:f1: pending\ncoverage: pending\nconfiguration: pending\n## Severity\nf1: pending\n"
               "## Essential facts\ndemo-f01: pending\n## Known unresolved\ndemo-u01: pending\n## Usability\n"
               "dataOrigin: pending\nupdatedParametersAndFitState: pending\nlosses: pending\n"
               "evaluationBoundaries: pending\noutputs: pending\nuncertainty: pending\ntask: pending\n"
               "## Reference defects\ndemo-d01: pending\n## False accusations\nresponse:40-42: high\n"
               "## Task\nReview: pending\n"),
    "invalidation": "# Invalidation: pilot-01\nReviewer:\nDate:\nScope:\nReason:\n",
}


@pytest.mark.parametrize("name", sorted(SPEC_FILES))
def test_every_campaign_file_type_parses_cleanly(name: str) -> None:
    record, problems = parse(SPEC_FILES[name], f"{name}.md")
    assert problems == [], messages(problems)
    assert record.kind in {schema.title for schema in er.SCHEMAS.values()}
    if name == "adjudication":
        assert [s.kind for s in record.sections] == ["dev-gan / codex", "dev-config / claude-code", "Baselines", "Task"]
        assert record.sections[0].label == "dev-gan / codex"
        assert record.sections[0].fields["usability.losses"].value == "pending"
    if name == "policy":
        assert [s.ident for s in record.find("Host")] == ["copilot", "codex", "claude-code"]


def test_invalidation_has_no_sections_and_schemas_can_be_overridden() -> None:
    _record, problems = parse("# Invalidation: pilot-01\nScope: campaign\n## Notes\n", "inv.md")
    assert messages(problems) == ['inv.md:3: ERROR Notes: unknown section "## Notes". This file has no sections. The '
                                  'lines after it, up to the next "## " heading, were not read.']
    custom = {"session": er.RecordSchema("Session", True, ("Status", "Partial artifact"), (er.SectionSpec("Deviations"),))}
    record, problems = er.parse_record(b"# Session: pilot-demo:codex:1\nPartial artifact: yes\n", "s.md", schemas=custom)
    assert problems == [] and record.header.value("Partial artifact") == "yes"
    _record, problems = er.parse_record(b"# Reference decisions: pilot-demo\n", "s.md", schemas=custom)
    assert problems[0].message.startswith("the first line must be the title the tool wrote.")


def test_split_list() -> None:
    assert er.split_list("train.py; configs/a.py ;; b.py") == ["train.py", "configs/a.py", "b.py"]
    assert er.split_list(" None ") == [] and er.split_list("") == []
    assert er.split_list("--workdir=./workdirs/mlview-mnist") == ["--workdir=./workdirs/mlview-mnist"]


# --------------------------------------------------------------------------------------------
# Anchors and verdicts


@pytest.mark.parametrize("text, parsed, formatted", [
    ("train.py:48-49", ("train.py", None, 48, 49), "train.py:48-49"),
    (" train.py:48 ", ("train.py", None, 48, 48), "train.py:48"),
    ("train.py:48-48", ("train.py", None, 48, 48), "train.py:48"),
    ("02_end.ipynb#cell11:1-4", ("02_end.ipynb", 11, 1, 4), "02_end.ipynb#cell11:1-4"),
    ("nb/A.IPYNB#cell0:3", ("nb/A.IPYNB", 0, 3, 3), "nb/A.IPYNB#cell0:3"),
    ("examples/my script.py:7", ("examples/my script.py", None, 7, 7), "examples/my script.py:7"),
])
def test_anchor_round_trip(text: str, parsed: tuple, formatted: str) -> None:
    assert er.parse_anchor(text) == parsed
    assert er.format_anchor(*parsed) == formatted


@pytest.mark.parametrize("text, message", [
    ("train.py", '"train.py" is not an anchor. Write path:LINE or path:LINE-END; notebooks path#cellN:LINE-END; '
                 'separate several with ";".'),
    ("train.py:48-49; train.py:94", None),
    ("train.py:49-48", '"train.py:49-48": the end line is before the start line.'),
    ("train.py:0", '"train.py:0": lines start at 1.'),
    ("/Users/me/train.py:3", None),
    ("../train.py:3", None),
    ("a\\train.py:3", None),
    ("nb.ipynb:3", '"nb.ipynb:3": a notebook anchor needs a zero-based cell, like nb.ipynb#cell0:3.'),
    ("train.py#cell1:3", '"train.py#cell1:3": only notebooks (.ipynb) take #cellN.'),
])
def test_anchor_errors(text: str, message: str | None) -> None:
    with pytest.raises(ValueError) as caught:
        er.parse_anchor(text)
    if message is not None:
        assert str(caught.value) == message


def test_parse_verdict() -> None:
    vocab = {"covered", "partial", "missing", "contradicted"}
    assert er.parse_verdict("covered", vocab) == ("covered", [], None)
    assert er.parse_verdict(" Covered node:a edge:b ", vocab) == ("covered", ["node:a", "edge:b"], None)
    assert er.parse_verdict("partial node:a " + EM + " omits the DDP case " + EM + " twice", vocab) == (
        "partial", ["node:a"], "omits the DDP case " + EM + " twice")
    assert er.parse_verdict("missing -- not stated", vocab) == ("missing", [], "not stated")
    assert er.parse_verdict("missing " + EN + " not stated", vocab) == ("missing", [], "not stated")
    assert er.parse_verdict("missing " + EM, vocab) == ("missing", [], None)
    with pytest.raises(ValueError, match='"aprove" is not one of: contradicted, covered, missing, partial.'):
        er.parse_verdict("aprove node:a", vocab)
    with pytest.raises(ValueError, match="the verdict is empty"):
        er.parse_verdict("  ", vocab)
    with pytest.raises(ValueError, match="is not one of"):
        er.parse_verdict("covered" + EM + "reason", vocab)


# --------------------------------------------------------------------------------------------
# Hashes, Git and pinned bytes


def git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "Synthetic Test", "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
                "GIT_COMMITTER_NAME": "Synthetic Test", "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
                "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"})
    return env


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=git_env(), check=True)
    return result.stdout.decode("utf-8")


def make_repo(path: Path, files: dict[str, bytes]) -> str:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "--quiet")
    for rel, data in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    git(path, "add", "-A")
    git(path, "commit", "--quiet", "-m", "synthetic")
    return git(path, "rev-parse", "HEAD").strip()


def test_hashes(tmp_path: Path) -> None:
    data = b"x" * (3 * 1024 * 1024 + 7)
    (tmp_path / "big.bin").write_bytes(data)
    assert er.sha256_file(tmp_path / "big.bin") == er.sha256_bytes(data)
    assert er.sha256_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert er.git_blob_oid(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert er.git_blob_oid(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


# Review normalization v1 is fixed: these bytes and this hash must never change. A different normalization
# gets a new version number, and v1 stays as it is for every summary that records it.
V1_RAW = ("\ufeff# Run review: pilot-demo:codex:1 \t\r\n"
          "> Written by review-template (a note)\r\n"
          "   > an indented note\r"
          "\t> a tab-indented note\n"
          "\xa0\u3000> a note after Unicode spaces\n"
          "Run: pilot-demo:codex:1\xa0\u3000\n"
          "\r\n"
          " \t \n"
          "Reviewer: Test Reviewer (synthetic)   \n"
          "## Claims\n"
          "node:load: qualified -- a reason > with a quote sign  \n"
          "  continued after two spaces\n"
          "\tcontinued after a tab\n"
          "\u200b> a zero-width space is not whitespace\n"
          "## Task\r\n"
          "Review: complete").encode("utf-8")
V1_NORMALIZED = (b"# Run review: pilot-demo:codex:1\nRun: pilot-demo:codex:1\nReviewer: Test Reviewer (synthetic)\n"
                 b"## Claims\nnode:load: qualified -- a reason > with a quote sign\n  continued after two spaces\n"
                 b"\tcontinued after a tab\n\xe2\x80\x8b> a zero-width space is not whitespace\n## Task\n"
                 b"Review: complete\n")
V1_SHA256 = "a4fdba1f0104d0cc806cff89560845eb664f9b15a6bc46f986095fee0d090f24"


def test_review_normalization_v1_is_pinned_byte_for_byte() -> None:
    assert er.REVIEW_NORMALIZATION_VERSION == 1
    assert er.normalized_review_bytes(V1_RAW) == V1_NORMALIZED
    assert er.normalized_review_sha256(V1_RAW) == V1_SHA256 == er.sha256_bytes(V1_NORMALIZED)
    assert er.normalized_review_sha256(V1_NORMALIZED) == V1_SHA256
    assert er.normalized_review_sha256(b"") == er.sha256_bytes(b"")  # nothing kept: no line, no LF
    assert er.normalized_review_sha256(b"\n> note\n \n") == er.sha256_bytes(b"")
    assert er.normalized_review_sha256(BOM + BOM + b"x\n") == er.sha256_bytes("\ufeffx\n".encode("utf-8"))  # one BOM
    assert er.normalized_review_sha256(b"x\xff\n") is None
    with pytest.raises(ValueError, match="not valid UTF-8"):
        er.normalized_review_bytes("x\n".encode("utf-16"))


def test_review_normalization_v1_whitespace_is_what_the_parser_strips() -> None:
    """The parser skips a line when str.strip() leaves it empty or starting with ">" and ignores what str.rstrip()
    removes; v1 spells that set out, and this interpreter must agree with it (Python 3.10 to 3.14 do)."""
    running = "".join(char for char in map(chr, range(0x110000)) if char.isspace())
    assert er._V1_SPACE == running and len(er._V1_SPACE) == 29
    sample = "".join(map(chr, range(0x3001))) + "x"
    assert sample.strip() == sample.strip(er._V1_SPACE)
    # v1 is spelled with escapes, so no invisible character can be lost or hidden by an editor (INTEGRITY-2).
    source = Path(er.__file__).read_text(encoding="utf-8")
    block = source[source.index("REVIEW_NORMALIZATION_VERSION = 1"):source.index("def normalized_review_sha256")]
    assert block.isascii(), [hex(ord(char)) for char in block if not char.isascii()]


def _review_fields(raw: bytes) -> list:
    record, problems = er.parse_record(raw, "review.md")
    assert record is not None
    return [record.title, [problem.message for problem in problems]] + [
        (section.kind, section.ident, [(item.key, item.value) for item in section.lines])
        for section in [record.header] + record.sections]


def test_review_normalization_keeps_the_hash_exactly_when_the_review_reads_the_same() -> None:
    """A re-save (BOM, CRLF or CR), '>' notes added, edited or removed, trailing spaces and blank lines keep both
    what the parser reads and the v1 hash; a changed verdict, reason, reviewer, key, heading or indentation
    changes the hash."""
    base = SPEC_FILES["review"].replace("Reviewer:\n", "Reviewer: Test Reviewer (synthetic)\n").replace(
        "demo-f01: pending", "demo-f01: partial node:load-batches -- a synthetic reason\n  wrapped onto a second line"
    ).replace("## Task\n", "## Task\n> a recorded note (synthetic)\n").encode("utf-8")
    reference = er.normalized_review_sha256(base)

    def per_line(change) -> bytes:
        return "\n".join(item for line in base.decode("utf-8").split("\n") for item in change(line)).encode("utf-8")

    honest = {
        "bom": BOM + base, "crlf": base.replace(b"\n", b"\r\n"), "cr": base.replace(b"\n", b"\r"),
        "note added": per_line(lambda line: [line, "  > a note (synthetic)"] if line.startswith("## ") else [line]),
        "note between a value and its continuation": base.replace(b"reason\n", b"reason\n> a note\n\n"),
        "trailing spaces": per_line(lambda line: [line + " \t\xa0\u3000" if line else line]),
        "blank lines": per_line(lambda line: ["", line, " ", "\t"]),
    }
    honest["note edited"] = base.replace(b"> a recorded note (synthetic)", b"   > the edited note (synthetic)")
    honest["note removed"] = base.replace(b"> a recorded note (synthetic)\n", b"")
    for name, raw in honest.items():
        assert raw != base, name
        assert er.normalized_review_sha256(raw) == reference, name
        assert _review_fields(raw) == _review_fields(base), name
    changed = {
        "verdict": base.replace(b"demo-f01: partial", b"demo-f01: missing"),
        "reason": base.replace(b"a synthetic reason", b"a synthetic  reason"),
        "continuation": base.replace(b"  wrapped onto", b"  Wrapped onto"),
        "reviewer": base.replace(b"Test Reviewer", b"Another Reviewer"),
        "severity": base.replace(b"f1: pending", b"f1: agree"),
        "false accusation": base.replace(b"response:40-42: high", b"response:40-42: low"),
        "line removed": base.replace(b"finding:f1: pending\n", b""),
        "indentation": base.replace(b"  wrapped onto", b"    wrapped onto"),
        "a # comment": base.replace(b"## Task\n", b"# a comment\n## Task\n"),
        "a zero-width space before >": base + "\u200b> not a note\n".encode("utf-8"),
    }
    for name, raw in changed.items():
        assert raw != base, name
        assert er.normalized_review_sha256(raw) != reference, name


@needs_git
def test_pinned_tree_bytes_and_git_show(tmp_path: Path) -> None:
    files = {"train.py": b"import torch\r\n", "configs/a.py": BOM + b"lr = 1\n", "docs/x.md": b"# doc\n"}
    repo = tmp_path / "corpus"
    commit = make_repo(repo, files)
    tree = er.pinned_tree(repo, commit)
    assert tree == {rel: er.git_blob_oid(data) for rel, data in files.items()}
    listed = {line.split("\t")[1]: line.split()[2] for line in git(repo, "ls-tree", "-r", commit).splitlines()}
    assert tree == listed
    assert er.pinned_bytes(repo, commit, "configs/a.py") == files["configs/a.py"]
    assert er.pinned_bytes(repo, commit, "train.py", tree=tree) == files["train.py"]
    (repo / "train.py").write_bytes(b"import torch\n")
    with pytest.raises(ValueError, match="differs from the pinned blob"):
        er.pinned_bytes(repo, commit, "train.py")
    assert er.git_show(repo, commit, "train.py") == files["train.py"]
    (repo / "docs" / "x.md").unlink()
    with pytest.raises(ValueError, match="not materialised"):
        er.pinned_bytes(repo, commit, "docs/x.md")
    with pytest.raises(ValueError, match="not in the pinned tree"):
        er.pinned_bytes(repo, commit, "missing.py")
    with pytest.raises(ValueError, match="must stay inside its root"):
        er.pinned_bytes(repo, commit, "../corpus/train.py")
    with pytest.raises(ValueError, match="full 40-hex"):
        er.pinned_tree(repo, "HEAD")
    with pytest.raises(ValueError, match="git ls-tree failed"):
        er.pinned_tree(repo, "0" * 40)
    with pytest.raises(ValueError, match="git cat-file failed"):
        er.git_show(repo, commit, "missing.py")
    with pytest.raises(ValueError, match="hexadecimal"):
        er.git_show(repo, "main", "train.py")


@needs_git
def test_pinned_bytes_refuses_symbolic_links(tmp_path: Path) -> None:
    repo = tmp_path / "corpus"
    commit = make_repo(repo, {"real/a.py": b"a = 1\n"})
    shutil.move(str(repo / "real"), str(tmp_path / "elsewhere"))
    try:
        os.symlink(tmp_path / "elsewhere", repo / "real", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available")
    with pytest.raises(ValueError, match="passes through a symbolic link"):
        er.pinned_bytes(repo, commit, "real/a.py")


def test_git_reads_disable_lazy_fetch_and_ignore_repository_overrides(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_run(command, capture_output, env, check):
        calls.append((command, env))
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setenv("GIT_DIR", str(tmp_path / "other.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path))
    monkeypatch.setattr(er.subprocess, "run", fake_run)
    er.git_show(tmp_path, "a" * 40, "train.py")
    command, env = calls[0]
    assert command[:4] == ["git", "-c", "protocol.allow=never", "-C"]
    assert command[-3:] == ["cat-file", "blob", "a" * 40 + ":train.py"]
    assert env["GIT_NO_LAZY_FETCH"] == "1" and env["GIT_OPTIONAL_LOCKS"] == "0"
    assert "GIT_DIR" not in env and "GIT_WORK_TREE" not in env


# --------------------------------------------------------------------------------------------
# Sparse patterns


def manifest_pattern_sets() -> list[list[str]]:
    repos = json.loads((ROOT / "evals/workflow/repositories.json").read_text(encoding="utf-8"))["repos"]
    return [repo["sparse"] for repo in repos]


MMDETECTION_5_1 = ["tools", "mmdet/apis", "mmdet/engine", "mmdet/models/detectors", "configs/common",
                   "/configs/_base_/datasets/coco_detection.py", "/configs/_base_/default_runtime.py",
                   "/configs/_base_/models/faster-rcnn_r50_fpn.py", "/configs/_base_/schedules/schedule_1x.py",
                   "/configs/faster_rcnn/faster-rcnn_r50_fpn_1x_coco.py"]
SPARSE_PATHS = [
    "train.py", "README.md", "setup.py", "tools/train.py", "tools/misc/x.py", "mmdet/tools/x.py",
    "mmdet/apis/inference.py", "mmdet/engine/hooks/h.py", "mmdet/models/detectors/base.py",
    "mmdet/models/backbones/resnet.py", "configs/common/lsj.py", "configs/x/common/y.py",
    "configs/_base_/datasets/coco_detection.py", "configs/_base_/datasets/voc.py", "configs/_base_/default_runtime.py",
    "configs/_base_/models/faster-rcnn_r50_fpn.py", "configs/_base_/models/retinanet.py",
    "configs/_base_/schedules/schedule_1x.py", "configs/_base_/schedules/schedule_2x.py",
    "configs/faster_rcnn/faster-rcnn_r50_fpn_1x_coco.py", "configs/faster_rcnn/faster-rcnn_r101_fpn_1x_coco.py",
    "a.ipynb", "b.ipynb", "sub/b.ipynb", "x.ipynb/inner.py", "examples/pytorch/run.py", "examples/pytorch/text/glue.py",
    "examples/mnist/main.py", "docs/examples/f.py", "cleanrl/ppo.py", "cleanrl_utils/x.py", "src/cleanrl/y.py",
]
EXTRA_PATTERN_SETS = [
    ["tools"], ["configs/common"], ["/*.ipynb"], ["examples"], ["examples/pytorch"], ["/examples/pytorch"],
    ["*.py"], ["configs/*"], ["/mmdet/*/inference.py"], ["mmdet/*/base.py"], ["cleanrl*"], ["*_base_*"],
    ["/configs/_base_/default_runtime.py", "cleanrl"], MMDETECTION_5_1,
]


def test_sparse_vectors_named_in_the_specification() -> None:
    assert er.sparse_covers(["tools"], "mmdet/tools/x.py")
    assert not er.sparse_covers(["configs/common"], "configs/x/common/y.py")
    assert not er.sparse_covers(["/*.ipynb"], "sub/b.ipynb")
    assert er.sparse_covers(["/*.ipynb"], "02_end_to_end_machine_learning_project.ipynb")
    assert er.sparse_covers(["examples"], "docs/examples/f.py")
    assert er.sparse_covers([], "anything/at/all.py")
    assert er.sparse_covers(MMDETECTION_5_1, "configs/_base_/default_runtime.py")
    assert not er.sparse_covers(MMDETECTION_5_1, "configs/_base_/models/retinanet.py")


@needs_git
def test_sparse_covers_agrees_with_real_git(tmp_path: Path) -> None:
    repo = tmp_path / "sparse"
    make_repo(repo, {rel: rel.encode("utf-8") + b"\n" for rel in SPARSE_PATHS})
    git(repo, "sparse-checkout", "init", "--no-cone")
    checked = 0
    for patterns in manifest_pattern_sets() + EXTRA_PATTERN_SETS:
        if patterns:
            git(repo, "sparse-checkout", "init", "--no-cone")  # "set --no-cone" needs Git 2.35
            git(repo, "sparse-checkout", "set", "--", *patterns)
        else:
            git(repo, "sparse-checkout", "disable")
        materialised = {p.relative_to(repo).as_posix() for p in repo.rglob("*")
                        if p.is_file() and ".git" not in p.relative_to(repo).parts}
        assert materialised == {rel for rel in SPARSE_PATHS if er.sparse_covers(patterns, rel)}, patterns
        if not patterns:
            git(repo, "sparse-checkout", "init", "--no-cone")
        checked += 1
    assert checked == len(manifest_pattern_sets()) + len(EXTRA_PATTERN_SETS)


@pytest.mark.parametrize("patterns", [
    ["!tools"], ["a?b"], ["[ab]"], ["a\\b"], ["**/x"], ["a/**"], ["configs/"], [""], [" tools"], ["tools "],
    ["#comment"], ["/"], ["a//b"], ["./a"], ["a/../b"], [7], "tools",
])
def test_unsupported_sparse_patterns_fail_closed(patterns) -> None:
    with pytest.raises(ValueError):
        er.validate_sparse_patterns(patterns)
    with pytest.raises(ValueError):
        er.sparse_covers(patterns, "tools/train.py")


def test_every_manifest_pattern_is_supported() -> None:
    for patterns in manifest_pattern_sets() + [MMDETECTION_5_1]:
        er.validate_sparse_patterns(patterns)
    with pytest.raises(ValueError, match="the path"):
        er.sparse_covers(["tools"], "../tools/x.py")


# --------------------------------------------------------------------------------------------
# Helper semantics


def conformance_evidence_cases() -> list[dict]:
    cases = []
    for path in bridge.case_paths():
        case = bridge.load_case(path)
        if "raw" in case or not ("bom" in case["id"] or "crlf" in case["id"] or case["id"].startswith("notebook-")):
            continue
        cases.append(case)
    return cases


RELEVANT_CODES = {"notebook_cell", "unexpected_cell", "range", "quote_mismatch"}


def eval_records_codes(case: dict, helper) -> dict[int, set[str]]:
    """Per-evidence codes computed only from source_lines, excerpt and quote_matches."""
    codes: dict[int, set[str]] = {}
    for index, ev in enumerate(case["document"]["evidence"]):
        if not isinstance(ev, dict) or ev.get("file") not in case["files"]:
            continue
        data = bridge.content(case["files"][ev["file"]])
        notebook = ev["file"].lower().endswith(".ipynb")
        cell = ev.get("cell")
        if notebook and not (isinstance(cell, int) and not isinstance(cell, bool) and cell >= 0):
            codes[index] = {"notebook_cell"}
            continue
        if not notebook and "cell" in ev:
            codes[index] = {"unexpected_cell"}
            continue
        try:
            lines = er.source_lines(data, cell if notebook else None, helper)
        except ValueError:
            codes[index] = {"notebook_cell"}
            continue
        try:
            er.excerpt(lines, ev.get("line"), ev.get("endLine"))
        except ValueError:
            codes[index] = {"range"}
            continue
        matches = er.quote_matches(ev.get("quote"), lines, ev["line"], ev["endLine"], helper)
        codes[index] = set() if matches else {"quote_mismatch"}
    return codes


@pytest.mark.parametrize("explicit_helper", [False, True])
def test_source_lines_agree_with_the_helper_on_conformance_cases(tmp_path: Path, explicit_helper: bool) -> None:
    helper = er.load_helper()
    cases = conformance_evidence_cases()
    assert len(cases) >= 10 and any("bom" in c["id"] for c in cases) and any("crlf" in c["id"] for c in cases)
    compared = 0
    for case in cases:
        root = tmp_path / case["id"]
        root.mkdir()
        bridge.materialise(case, root)
        errors, _hashes = helper.validate(bridge.substitute(case["document"]), root)
        helper_codes: dict[int, set[str]] = {}
        for error in errors:
            if error["path"].startswith("evidence["):
                helper_codes.setdefault(int(error["path"][9:error["path"].index("]")]), set()).add(error["code"])
        ours = eval_records_codes(case, helper if explicit_helper else None)
        # Compare every evidence item the helper judged on its lines (not on its path or encoding).
        judged = [i for i in range(len(case["document"]["evidence"])) if helper_codes.get(i, set()) <= RELEVANT_CODES]
        assert judged, case["id"]
        assert {i: ours.get(i) for i in judged} == {i: helper_codes.get(i, set()) for i in judged}, case["id"]
        compared += len(judged)
    assert compared >= 12


def test_source_lines_semantics_and_errors() -> None:
    assert er.source_lines(BOM + b"a\r\nb\rc\n", None) == ["a", "b", "c", ""]
    assert er.human_line_count(["a", "b", "c", ""]) == 3
    assert er.human_line_count([""]) == 0 and er.human_line_count(["a"]) == 1 and er.human_line_count(["a", "", ""]) == 2
    notebook = json.dumps({"cells": [{"source": ["x = 1\n", "fit(x)\n"]}, {"source": "y"}]}).encode()
    assert er.source_lines(notebook, 0) == ["x = 1", "fit(x)", ""]
    assert er.source_lines(notebook, 1) == ["y"]
    for bad in (2, -1, True, "0"):
        with pytest.raises(ValueError):
            er.source_lines(notebook, bad)
    with pytest.raises(ValueError, match="not UTF-8"):
        er.source_lines(b"\xff", None)
    with pytest.raises(ValueError, match="does not identify valid notebook source"):
        er.source_lines(b"{not json", 0)
    small = er.load_helper()
    small.MAX_SOURCE = 4
    with pytest.raises(ValueError, match="exceeds 4 bytes"):
        er.source_lines(b"12345", None, small)
    assert er.excerpt(["a", "b", ""], 2, 3) == "b\n"
    with pytest.raises(ValueError, match="the source has 2 lines"):
        er.excerpt(["a", "b", ""], 2, 4)
    assert er.quote_matches("\ufeffa", ["a", "b"], 1, 1) and er.quote_matches("a", ["\ufeffa"], 1, 1)
    assert not er.quote_matches("\ufeffb", ["a", "b"], 2, 2) and not er.quote_matches(None, ["a"], 1, 1)


@needs_git
def test_load_helper_from_bytes_and_from_a_commit() -> None:
    default = er.load_helper()
    again = er.load_helper()
    assert default is not again and default.__name__ not in sys.modules
    assert all(callable(getattr(default, name)) for name in er.HELPER_NAMES)
    copy_ = er.load_helper(er.HELPER_PATH.read_bytes())
    assert copy_.__file__.startswith("<artifact.py sha256:")
    assert copy_.MAX_SOURCE == default.MAX_SOURCE
    try:
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, check=True,
                              text=True).stdout.strip()
    except subprocess.CalledProcessError:
        pytest.skip("the MLView checkout has no Git history")
    frozen = er.load_helper(er.git_show(ROOT, head, "skills/mlview/scripts/artifact.py"))
    assert frozen._lines("a\r\nb") == ["a", "b"]
    with pytest.raises(ValueError, match="is not the MLView helper"):
        er.load_helper(b"x = 1\n")


def test_rfc3339() -> None:
    now = er.rfc3339_utc_now()
    assert len(now) == 20 and now.endswith("Z") and er.is_rfc3339(now)
    assert er.is_rfc3339("2026-09-25T10:00:00.123456789Z") and er.is_rfc3339("2026-09-25T10:00:00+05:30")
    for bad in ("2026-09-25T10:00:00z", "2026-06-30T23:59:60Z", "2026-09-25 10:00:00Z", "2026-02-30T00:00:00Z", 7, None):
        assert not er.is_rfc3339(bad)


# --------------------------------------------------------------------------------------------
# Required paths and the task manifest


def expected_required(task_id: str) -> set[str]:
    manifest = real_manifest()
    task = next(t for t in manifest["tasks"] if t["id"] == task_id)
    ledger = json.loads((ROOT / f"evals/workflow/reference-candidates/{task_id}.json").read_text(encoding="utf-8"))
    expected = set(task["entrypoints"]) | set(ledger["scenario"]["entrypoints"]) | {
        anchor["file"] for fact in ledger["facts"] for anchor in fact["anchors"]}
    if "pilotFreeze" in manifest:
        reference = ROOT / "evals/workflow" / Path(manifest["pilotFreeze"]["freeze"]).parent / "reference" / f"{task_id}.json"
        expected |= set(json.loads(reference.read_text(encoding="utf-8"))["sourceFiles"])
    return expected


def test_required_paths_for_real_tasks() -> None:
    for task in (t for t in real_manifest()["tasks"] if t["split"] == "heldout"):
        assert er.required_paths(task["id"]) == sorted(expected_required(task["id"])), task["id"]
    assert "train.py" in er.required_paths("pilot-nanogpt")
    paths = er.required_paths("pilot-registry")
    assert {"tools/train.py", "configs/_base_/default_runtime.py",
            "configs/faster_rcnn/faster-rcnn_r50_fpn_1x_coco.py"} <= set(paths)
    assert "02_end_to_end_machine_learning_project.ipynb" in er.required_paths("pilot-notebook")
    assert er.required_paths("dev-sklearn") == ["evals/workflow/fixtures/tabular_group_cv_clean/train.py"]
    for bad in ("pilot-missing", "../tasks", "Pilot-NanoGPT"):
        with pytest.raises(ValueError):
            er.required_paths(bad)


def synthetic_root(tmp_path: Path, frozen: bool) -> Path:
    root = tmp_path / "mlview"
    tasks = {"version": 1, "hosts": ["codex"], "repetitions": 1,
             "pilotTargets": dict.fromkeys(er.PILOT_TARGET_KEYS, 1),
             "tasks": [{"id": "pilot-demo", "split": "heldout", "repository": "demo", "url": "file:///synthetic",
                        "commit": "0" * 40, "entrypoints": ["main.py"], "prompt": "Synthetic.",
                        "referenceStatus": "frozen" if frozen else "needs-human-review"}]}
    if frozen:
        tasks["pilotFreeze"] = {"campaign": "pilot-99", "freeze": "pilot/pilot-99/freeze.json",
                                "referenceRevision": "sha256:" + "1" * 64}
    ledger = {"scenario": {"entrypoints": ["main.py", "configs/a.py"]},
              "facts": [{"anchors": [{"file": "lib/b.py"}, {"file": "nb.ipynb", "cell": 0}]}]}
    for rel, value in (("evals/workflow/tasks.json", tasks),
                       ("evals/workflow/reference-candidates/pilot-demo.json", ledger),
                       ("evals/workflow/pilot/pilot-99/reference/pilot-demo.json",
                        {"sourceFiles": {"lib/b.py": {}, "lib/c.py": {}}})):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(json.dumps(value), encoding="utf-8")
    return root


def test_required_paths_add_frozen_source_files_after_a_freeze(tmp_path: Path) -> None:
    before = synthetic_root(tmp_path / "before", frozen=False)
    assert er.required_paths("pilot-demo", before) == ["configs/a.py", "lib/b.py", "main.py", "nb.ipynb"]
    after = synthetic_root(tmp_path / "after", frozen=True)
    assert er.required_paths("pilot-demo", after) == ["configs/a.py", "lib/b.py", "lib/c.py", "main.py", "nb.ipynb"]
    (after / "evals/workflow/pilot/pilot-99/reference/pilot-demo.json").unlink()
    with pytest.raises(ValueError, match="does not exist"):
        er.required_paths("pilot-demo", after)


def real_manifest() -> dict:
    return json.loads((ROOT / "evals/workflow/tasks.json").read_text(encoding="utf-8"))


def prefreeze_manifest() -> dict:
    manifest = real_manifest()
    manifest.pop("pilotFreeze", None)
    for task in manifest["tasks"]:
        task["referenceStatus"] = "needs-human-review"
    return manifest


def frozen_manifest() -> dict:
    manifest = prefreeze_manifest()
    for task in manifest["tasks"]:
        if task["split"] == "heldout":
            task["referenceStatus"] = "frozen"
    manifest["pilotFreeze"] = {"campaign": "pilot-01", "freeze": "pilot/pilot-01/freeze.json",
                               "referenceRevision": "sha256:" + "a" * 64}
    return manifest


def test_check_task_manifest_accepts_the_committed_file_and_both_freeze_states() -> None:
    manifest = real_manifest()
    assert list(manifest["pilotTargets"]) == list(er.PILOT_TARGET_KEYS)
    assert manifest["pilotTargets"]["knownUnresolvedQualified"] == 1.0
    assert er.check_task_manifest(manifest) == []
    assert er.check_task_manifest(prefreeze_manifest()) == []
    assert er.check_task_manifest(frozen_manifest()) == []


def mutate(manifest: dict, change) -> dict:
    value = copy.deepcopy(manifest)
    change(value)
    return value


def task(manifest: dict, task_id: str) -> dict:
    return next(t for t in manifest["tasks"] if t["id"] == task_id)


@pytest.mark.parametrize("frozen, change, fragment", [
    (False, lambda m: m["pilotTargets"].pop("knownUnresolvedQualified"), "(missing knownUnresolvedQualified)"),
    (False, lambda m: m["pilotTargets"].update(extra=1), "(unexpected extra)"),
    (False, lambda m: m["pilotTargets"].update(exactAnchors="1.0"), "pilotTargets.exactAnchors must be a number from 0 to 1"),
    (False, lambda m: m["pilotTargets"].update(essentialFactRecall=1.5), "pilotTargets.essentialFactRecall must be a number"),
    (False, lambda m: m["pilotTargets"].update(highSeverityFalseAccusations=True), "must be a non-negative integer"),
    (False, lambda m: m.update(pilotFrozen={}), "unknown top-level key(s): pilotFrozen"),
    (False, lambda m: m.pop("tasks"), "missing top-level key(s): tasks"),
    (False, lambda m: m.update(hosts=["codex", "codex"]), "hosts must be a non-empty list of unique"),
    (False, lambda m: m.update(repetitions=0), "repetitions must be a positive integer"),
    (False, lambda m: task(m, "pilot-transformers").update(referenceStatus="frozen"),
     "pilot-transformers: referenceStatus is frozen but tasks.json has no pilotFreeze"),
    (False, lambda m: task(m, "pilot-transformers").update(referenceStatus="approved"), "pilot-transformers: referenceStatus must be one of"),
    (False, lambda m: task(m, "pilot-transformers").update(commit="abc"), "pilot-transformers: a held-out task needs a full 40-hex commit"),
    (False, lambda m: m["tasks"][1].update(id=m["tasks"][0]["id"]), "tasks[1]: id must be a unique lowercase task ID"),
    (False, lambda m: task(m, "dev-pytorch").update(entrypoints=["/abs/train.py"]), "entrypoints must be a non-empty list of relative"),
    (True, lambda m: task(m, "pilot-transformers").update(referenceStatus="needs-human-review"),
     "pilot-transformers: a held-out task must be frozen after the freeze of pilot-01"),
    (True, lambda m: task(m, "dev-pytorch").update(referenceStatus="frozen"), "dev-pytorch: a development task stays needs-human-review"),
    (True, lambda m: m["pilotFreeze"].update(freeze="pilot/pilot-02/freeze.json"), "pilotFreeze.freeze must be pilot/pilot-01/freeze.json"),
    (True, lambda m: m["pilotFreeze"].update(referenceRevision="a" * 64), 'pilotFreeze.referenceRevision must be "sha256:"'),
    (True, lambda m: m["pilotFreeze"].update(campaign="Pilot 01"), "pilotFreeze.campaign must be a lowercase campaign name"),
    (True, lambda m: m["pilotFreeze"].pop("referenceRevision"), "pilotFreeze must have exactly the keys"),
])
def test_check_task_manifest_reports_each_problem(frozen: bool, change, fragment: str) -> None:
    manifest = mutate(frozen_manifest() if frozen else prefreeze_manifest(), change)
    problems = er.check_task_manifest(manifest)
    assert any(fragment in problem for problem in problems), problems


def test_check_task_manifest_on_a_non_object() -> None:
    assert er.check_task_manifest([]) == ["tasks.json must be a JSON object"]


# --------------------------------------------------------------------------------------------
# Paths and files


def test_confined_file(tmp_path: Path) -> None:
    (tmp_path / "evidence" / "dir").mkdir(parents=True)
    (tmp_path / "evidence" / "PROMPT.txt").write_bytes(b"p")
    assert er.confined_file(tmp_path, "evidence/PROMPT.txt") == tmp_path / "evidence" / "PROMPT.txt"
    for rel, fragment in (("/etc/passwd", "absolute"), ("C:/x", "absolute"), ("evidence/../x", "stay inside"),
                          ("./evidence/PROMPT.txt", "stay inside"), ("evidence//PROMPT.txt", "stay inside"),
                          ("evidence\\PROMPT.txt", "separator"), ("", "non-empty"), ("a:b", "absolute"), ("evidence:x", "':'"),
                          ("evidence/missing.txt", "does not exist"), ("evidence/dir", "not a regular file")):
        with pytest.raises(ValueError, match=fragment.replace("(", r"\(")):
            er.confined_file(tmp_path, rel)
    try:
        os.symlink(tmp_path / "evidence" / "PROMPT.txt", tmp_path / "evidence" / "link.txt")
        os.symlink(tmp_path / "evidence", tmp_path / "linked", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available")
    for rel in ("evidence/link.txt", "linked/PROMPT.txt"):
        with pytest.raises(ValueError, match="symbolic link"):
            er.confined_file(tmp_path, rel)


def test_outside_repositories(tmp_path: Path) -> None:
    clean = tmp_path / "clean" / "pilot"
    if er.outside_repositories(clean, tmp_path / "unrelated-root"):
        pytest.skip("the temporary directory itself sits inside a repository or below an instruction file")
    fake_root = tmp_path / "mlview-root"
    fake_root.mkdir()
    assert any("inside the MLView checkout" in r for r in er.outside_repositories(fake_root / "pilot", fake_root))
    (tmp_path / "instructed").mkdir()
    (tmp_path / "instructed" / "AGENTS.md").write_text("synthetic", encoding="utf-8")
    reasons = er.outside_repositories(tmp_path / "instructed" / "a" / "b", fake_root)
    assert len(reasons) == 1 and "AGENTS.md would be read by a host as instructions" in reasons[0]
    (tmp_path / "copilot" / ".github").mkdir(parents=True)
    (tmp_path / "copilot" / ".github" / "copilot-instructions.md").write_text("synthetic", encoding="utf-8")
    assert er.outside_repositories(tmp_path / "copilot", fake_root)
    if HAS_GIT:
        subprocess.run(["git", "init", "--quiet", str(tmp_path / "repo")], check=True, env=git_env())
        reasons = er.outside_repositories(tmp_path / "repo" / "not" / "yet", fake_root)
        assert any("Git work tree" in r for r in reasons)


def test_a_pilot_directory_given_with_dot_dot_is_judged_by_its_real_parents(tmp_path: Path,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """"<checkout>/../pilot" is a sibling of the checkout: the checkout's CLAUDE.md is not one of its parents
    (HONEST-F5), while an instruction file in a real parent still counts."""
    if er.outside_repositories(tmp_path / "probe" / "pilot", tmp_path / "unrelated-root"):
        pytest.skip("the temporary directory itself sits inside a repository or below an instruction file")
    checkout = tmp_path / "iso" / "checkout"
    checkout.mkdir(parents=True)
    (checkout / "CLAUDE.md").write_text("synthetic instructions\n", encoding="utf-8")
    assert er.outside_repositories(checkout / ".." / "pilot", tmp_path / "unrelated-root") == []
    monkeypatch.chdir(checkout)
    assert er.outside_repositories(Path("..") / "pilot", tmp_path / "unrelated-root") == []
    assert er.outside_repositories(checkout / "inner" / ".." / "pilot", tmp_path / "unrelated-root") == [
        f"{checkout / 'CLAUDE.md'} would be read by a host as instructions"]


def test_safe_streams_never_fail_on_a_character_the_encoding_lacks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Windows code-page stdout (a redirect, a pipe, Git Bash) writes a character it lacks as an escape
    instead of failing the command (HONEST-F4, DISTCI-F3)."""
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict", newline="\n")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", io.StringIO())  # no reconfigure: left alone
    er.safe_streams()
    print("T3 \u2265 95% \u2014 synthetic")
    stream.flush()
    assert buffer.getvalue() == b"T3 \\u2265 95% \x97 synthetic\n"


def test_canonical_json() -> None:
    assert er.canonical_json({"b": [1, "\u00e9"], "a": None}) == '{\n  "a": null,\n  "b": [\n    1,\n    "\u00e9"\n  ]\n}\n'.encode("utf-8")
    with pytest.raises(ValueError):
        er.canonical_json({"x": float("nan")})


def test_write_exclusive(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "campaign" / "reference" / "a.json"
    er.write_exclusive(target, b"one")
    assert target.read_bytes() == b"one"
    with pytest.raises(FileExistsError):
        er.write_exclusive(target, b"two")
    assert target.read_bytes() == b"one"

    def failing_fsync(_descriptor):
        raise OSError("disk full (synthetic)")

    monkeypatch.setattr(er.os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="synthetic"):
        er.write_exclusive(tmp_path / "partial.json", b"data")
    assert not (tmp_path / "partial.json").exists()


def test_write_atomic(tmp_path: Path) -> None:
    target = tmp_path / "evidence" / "record.json"
    er.write_atomic(target, b"first")
    assert target.read_bytes() == b"first"
    if os.name != "nt":
        os.chmod(target, 0o640)
    er.write_atomic(target, b"second")
    assert target.read_bytes() == b"second"
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o640
    assert sorted(p.name for p in target.parent.iterdir()) == ["record.json"]
    try:
        os.symlink(target, tmp_path / "evidence" / "link.json")
    except (OSError, NotImplementedError):
        return
    with pytest.raises(ValueError, match="symbolic link"):
        er.write_atomic(tmp_path / "evidence" / "link.json", b"x")


@pytest.mark.parametrize("run_id, name", [
    ("pilot-nanogpt:codex:1", "pilot-nanogpt.codex.1"),
    ("pilot-nanogpt:claude-code:3", "pilot-nanogpt.claude-code.3"),
    ("pilot-nanogpt:copilot:baseline:1", "pilot-nanogpt.copilot.baseline.1"),
])
def test_run_directory_names_round_trip(run_id: str, name: str) -> None:
    assert er.run_dir_name(run_id) == name
    assert er.run_id_from_dir(name) == run_id


@pytest.mark.parametrize("bad", ["pilot-nanogpt:codex", "pilot-nanogpt:codex:0", "dev-gan:codex:skill",
                                 "Pilot:codex:1", "a.b:codex:1", "a:b:1:2", "pilot/x:codex:1", ""])
def test_invalid_run_ids_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        er.run_dir_name(bad)
    with pytest.raises(ValueError):
        er.run_id_from_dir(bad.replace(":", "."))


# --------------------------------------------------------------------------------------------
# workflow_eval.py dispatcher


@pytest.fixture
def isolated_tools(tmp_path: Path, monkeypatch):
    """A tools directory for the dispatcher; the real tool modules are restored afterwards."""
    saved = {name: sys.modules.get(name) for name in ("workflow_decisions", "workflow_pilot")}
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setattr(workflow_eval, "TOOLS", tools)
    for name in saved:
        sys.modules.pop(name, None)
    yield tools
    for name, module in saved.items():
        sys.modules.pop(name, None)
        if module is not None:
            sys.modules[name] = module


def run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = workflow_eval.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


ALL_COMMANDS = list(workflow_eval.ROUTED_COMMANDS) + [
    "development-plan", "summarize-development", "validate-development", "review-packet"]


@pytest.mark.parametrize("with_tools", [False, True])
def test_help_lists_every_command(isolated_tools: Path, with_tools: bool) -> None:
    if with_tools:
        for name in ("workflow_decisions", "workflow_pilot"):
            (isolated_tools / f"{name}.py").write_text("def main(argv):\n    return 0\n", encoding="utf-8")
    code, out, _err = run_main(["--help"])
    assert code == 0
    listed = {line.split()[0] for line in out.splitlines() if line.startswith("    ") and line.split()}
    assert set(ALL_COMMANDS) <= listed
    assert set(workflow_eval.ROUTED_COMMANDS) == {"template", "check", "context", "freeze", "check-frozen", "plan",
                                                  "run-prepare", "run-finish", "review-template", "summarize"}
    flat = " ".join(out.split())
    assert ("not available in this build" in flat) is (not with_tools)


@pytest.mark.parametrize("command", ["template", "check", "context", "freeze", "check-frozen", "run-prepare",
                                     "run-finish", "review-template"])
def test_missing_tool_says_not_available(isolated_tools: Path, command: str) -> None:
    code, out, err = run_main([command, "pilot-demo"])
    tool = workflow_eval.ROUTED_COMMANDS[command][0]
    assert (code, out) == (2, "")
    assert err.strip() == f"workflow_eval.py {command}: not available in this build (tools/{tool}.py is missing)"


def test_plan_and_summarize_without_the_pilot_tool(isolated_tools: Path, tmp_path: Path) -> None:
    """While workflow_eval.py keeps a legacy implementation they behave as before; once it is
    removed they report that the pilot tool is missing, like the other routed commands."""
    fallback = getattr(workflow_eval, "LEGACY_FALLBACK", {})
    code, out, err = run_main(["plan"])
    if "plan" in fallback:
        records = json.loads(out)
        assert code == 0 and len(records) == 72 and records[0]["id"] == "pilot-nanogpt:copilot:1"
    else:
        assert code == 2 and "plan: not available in this build" in err
    path = tmp_path / "runs.json"
    path.write_text(json.dumps(workflow_eval.plan(real_manifest()) if "summarize" in fallback else []), encoding="utf-8")
    code, out, err = run_main(["summarize", str(path)])
    if "summarize" in fallback:
        assert code == 0 and json.loads(out)["statuses"] == {"pending": 72}
    else:
        assert code == 2 and "summarize: not available in this build" in err


def test_present_tools_receive_the_full_argument_list(isolated_tools: Path) -> None:
    for name, status in (("workflow_decisions", 3), ("workflow_pilot", 0)):
        (isolated_tools / f"{name}.py").write_text(
            "import json\n"
            f"def main(argv):\n    print(json.dumps({{'tool': {name!r}, 'argv': argv}}))\n    return {status}\n",
            encoding="utf-8")
    code, out, _err = run_main(["check", "pilot-demo", "--show"])
    assert (code, json.loads(out)) == (3, {"tool": "workflow_decisions", "argv": ["check", "pilot-demo", "--show"]})
    code, out, _err = run_main(["summarize", "--campaign", "pilot-01", "--stage", "1"])
    assert (code, json.loads(out)) == (0, {"tool": "workflow_pilot",
                                           "argv": ["summarize", "--campaign", "pilot-01", "--stage", "1"]})
    assert str(isolated_tools) in sys.path
    sys.path.remove(str(isolated_tools))


def test_existing_development_commands_are_unchanged() -> None:
    code, out, _err = run_main(["development-plan"])
    manifest = json.loads((ROOT / "evals/workflow/tasks.json").read_text(encoding="utf-8"))
    assert code == 0 and json.loads(out) == workflow_eval.development_plan(manifest)
    code, _out, _err = run_main([])
    assert code == 2
