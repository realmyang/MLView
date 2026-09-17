"""Slash-command argument placeholders, and the CLI fallback they expand into.

Claude Code substitutes positional command arguments **0-based**: `$0` is the
first argument, `$1` the second, and `$ARGUMENTS` is the whole argument string.
Verified against the installed CLI (2.1.186) with a probe plugin whose body is
echoed verbatim:

    /probe alpha beta  ->  ARGUMENTS{alpha beta} ZERO{alpha} ONE{beta} TWO{}

A 1-based reading (`$1` for the path) is silently wrong rather than loudly
broken: `/mlview-issues samples/vision_pipeline high` would put the *severity*
in the path slot and nothing in the severity slot, and the documented Bash
fallback — the path the command files exist to guarantee when MCP registration
fails — would run `analyze "high" --min-severity ""`.

So the placeholders are asserted here, and the fallback command lines are
actually executed after substituting the documented semantics.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys

import pytest

from plugin_support import PLUGIN_ROOT, REPO_ROOT, child_env, corpus_path

COMMANDS_DIR = os.path.join(PLUGIN_ROOT, "commands")
COMMAND_FILES = ("mlview-issues.md",)

#: The invocations the top-level README prescribes, as (command, arguments).
README_INVOCATIONS = {
    "mlview.md": ("samples/vision_pipeline",),
    "mlview-issues.md": ("samples/vision_pipeline", "high"),
}


def read_command(name: str) -> str:
    with open(os.path.join(COMMANDS_DIR, name), "r", encoding="utf-8") as fh:
        return fh.read()


def substitute(text: str, args) -> str:
    """Apply Claude Code's documented substitution: `$ARGUMENTS` and 0-based `$N`."""
    out = text.replace("$ARGUMENTS", " ".join(args))
    return re.sub(r"\$(\d+)", lambda m: args[int(m.group(1))] if int(m.group(1)) < len(args) else "", out)


def bash_blocks(text: str):
    return re.findall(r"```bash\n(.*?)```", text, flags=re.S)


def cli_lines(text: str):
    lines = []
    for block in bash_blocks(text):
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("python -m mlview"):
                lines.append(line)
    return lines


# ------------------------------------------------------- the placeholders themselves
@pytest.mark.parametrize("name", COMMAND_FILES)
def test_no_command_reads_a_third_positional_argument(name):
    # `$2` is the THIRD argument; neither command takes one. Its presence is the
    # signature of the 1-based misreading.
    assert "$2" not in read_command(name), (
        "%s uses $2; positional arguments are 0-based, so the second argument is $1" % name
    )


def test_mlview_takes_the_path_from_the_first_argument():
    body = read_command("mlview.md")
    assert "$ARGUMENTS" in body and "question or analysis focus" in body


def test_mlview_issues_takes_the_path_then_the_severity():
    body = read_command("mlview-issues.md")
    assert "$0" in body and "$1" in body
    # The path must be read before the severity, never the other way round.
    assert body.index("$0") < body.index("$1")


@pytest.mark.parametrize("name", COMMAND_FILES)
def test_the_body_explains_the_zero_based_convention(name):
    body = read_command(name).lower()
    assert "0-based" in body, (
        "%s should say the positional arguments are 0-based; that is the "
        "convention a future edit is most likely to get wrong" % name
    )


@pytest.mark.parametrize("name", COMMAND_FILES)
def test_the_empty_argument_case_is_spelled_out(name):
    body = read_command(name)
    assert "$ARGUMENTS" in body
    assert "`.`" in body, "%s must say what to use when no path was given" % name


def test_mlview_issues_forbids_an_empty_min_severity():
    # `--min-severity ""` is rejected by argparse; the body must not let the
    # model construct it out of a missing second argument.
    body = read_command("mlview-issues.md")
    assert "low" in body
    assert '--min-severity ""' in body or "`--min-severity \"\"`" in body


# ------------------------------------------------- substitution lands in the right slot
def test_substitution_puts_the_path_and_severity_in_their_own_slots():
    line = cli_lines(read_command("mlview-issues.md"))[0]
    argv = shlex.split(substitute(line, README_INVOCATIONS["mlview-issues.md"]))
    assert argv[:3] == ["python", "-m", "mlview"]
    assert argv[3] == "analyze"
    assert argv[4] == "samples/vision_pipeline", (
        "the first argument must land in the path slot, got %r" % argv[4]
    )
    assert argv[argv.index("--min-severity") + 1] == "high"


def test_substitution_puts_the_path_in_the_analyze_slot_for_mlview():
    body = read_command("mlview.md")
    assert "workflow.mlview.json" in body
    assert not cli_lines(body), "the authored workflow must not fall back to static analysis"


# ------------------------------------------- a flag's VALUE is not the severity slot
SEVERITIES = ("low", "medium", "high")
#: CHANGED by ROADMAP RAIL-GROUP (2026-09-08): `--group-by` joined the grammar, and
#: it is a VALUE flag, so `/mlview-issues --group-by rule` must not read `rule` as
#: the path — the same class of bug `--scope stage:train` produced.
VALUE_FLAGS = ("--scope", "--depth", "--group-by")


def resolve_path_and_severity(args):
    """The rule `mlview-issues.md` states, executed.

    A flag occupies TWO positional slots, so with the path omitted the flag's
    value lands in `$1` — and a value like `stage:train` does not start with
    `--`, so the "a token starting with `--` is a flag" guard alone never sees
    it. `--min-severity stage:train` is an argparse usage error, and
    `minSeverity` over MCP rejects it too, so the body must rule the value out
    by position and then sanity-check the word that survives.
    """
    tokens, skip = [], False
    for index, token in enumerate(args):
        if skip:
            skip = False
            continue
        if token.startswith("--"):
            skip = token in VALUE_FLAGS
            continue
        tokens.append(token)
    severity = next((t for t in tokens if t in SEVERITIES), None)
    rest = [t for t in tokens if t is not severity]
    return (rest[0] if rest else "."), (severity or "low")


@pytest.mark.parametrize(
    "args,expected",
    [
        (("--scope", "stage:train"), (".", "low")),          # the reported bug
        (("--depth", "2"), (".", "low")),
        ((), (".", "low")),
        (("samples/vision_pipeline",), ("samples/vision_pipeline", "low")),
        (("samples/vision_pipeline", "high"), ("samples/vision_pipeline", "high")),
        (("--depth", "1", "medium"), (".", "medium")),
        (("samples/vision_pipeline", "high", "--scope", "concern:evaluation"),
         ("samples/vision_pipeline", "high")),
        # RAIL-GROUP: the mode word is never the path and never the severity.
        (("--group-by", "rule"), (".", "low")),
        (("--group-by", "severity"), (".", "low")),
        (("samples/vision_pipeline", "--group-by", "file"),
         ("samples/vision_pipeline", "low")),
        (("--group-by", "rule", "high"), (".", "high")),
    ],
)
def test_a_flag_value_never_lands_in_the_path_or_the_severity_slot(args, expected):
    assert resolve_path_and_severity(args) == expected
    path, severity = resolve_path_and_severity(args)
    assert severity in SEVERITIES, "--min-severity %r is a usage error" % severity
    assert not path.startswith("--")


def test_mlview_issues_documents_the_flag_value_rule():
    body = read_command("mlview-issues.md")
    lowered = body.lower()
    assert "--scope" in body and "--depth" in body and "--group-by" in body
    assert "immediately after" in lowered, (
        "the body must say that the token after --scope/--depth is that flag's "
        "value, not the path and not the severity"
    )
    for word in SEVERITIES:
        assert word in lowered
    assert "stage:train" in body, (
        "the body should show the failing case it is guarding against"
    )


def test_the_documented_severity_fallback_really_runs(tmp_path):
    """`/mlview-issues --scope stage:train` must produce a runnable CLI line."""
    line = cli_lines(read_command("mlview-issues.md"))[0]
    path, severity = resolve_path_and_severity(("--scope", "stage:train"))
    argv = shlex.split(substitute(line, (corpus_path(), severity)))
    argv = _runnable(argv, tmp_path) + ["--scope", "stage:train"]
    proc = subprocess.run(
        [sys.executable, "-X", "utf8"] + argv[1:],
        cwd=REPO_ROOT, env=child_env(), capture_output=True, text=True,
        shell=False, timeout=300,
    )
    assert proc.returncode in (0, 2), proc.stderr[-2000:]
    assert path == "."


# ------------------------------------------------------------- the fallback really runs
def _runnable(argv, tmp_path):
    """Rewrite a documented fallback so it can run in a test: no browser, temp outputs.

    VIEW-08 added a second shape to rewrite. `mlview diff` takes two documents as
    POSITIONAL arguments rather than behind `--json`, and the fallback block writes
    them with `analyze --json` two lines earlier — so a `*.json` positional of `diff`
    is redirected into the same tmp directory those writes were redirected into, and
    the three documented lines still form one runnable sequence.
    """
    out = []
    skip = False
    is_diff = "diff" in argv[:4]
    for index, token in enumerate(argv):
        if skip:
            skip = False
            continue
        if token == "--open":
            continue
        if token in ("--json", "--html") and index + 1 < len(argv) and not argv[index + 1].startswith("-"):
            out.extend([token, os.path.join(str(tmp_path), os.path.basename(argv[index + 1]))])
            skip = True
            continue
        if is_diff and token.endswith(".json") and not token.startswith("-"):
            out.append(os.path.join(str(tmp_path), os.path.basename(token)))
            continue
        out.append(token)
    return out


@pytest.mark.parametrize("name", COMMAND_FILES)
def test_every_documented_fallback_command_actually_runs(name, tmp_path):
    args = list(README_INVOCATIONS[name])
    args[0] = corpus_path()
    lines = cli_lines(read_command(name))
    assert lines, "%s must document a CLI fallback" % name

    for line in lines:
        argv = _runnable(shlex.split(substitute(line, args)), tmp_path)
        assert argv[0] == "python"
        proc = subprocess.run(
            [sys.executable, "-X", "utf8"] + argv[1:],
            cwd=REPO_ROOT,
            env=child_env(),
            capture_output=True,
            text=True,
            shell=False,
            timeout=300,
        )
        # 0 = clean, 2 = --fail-on threshold. Anything else means the command
        # line the command file documents is wrong.
        assert proc.returncode in (0, 2), (
            "%s documents a fallback that fails:\n  %s\n  exit=%d\n%s\n%s"
            % (name, " ".join(argv), proc.returncode, proc.stdout[-2000:], proc.stderr[-2000:])
        )


# --------------------------------------------------------------- ROADMAP RAIL-GROUP
def test_mlview_issues_documents_every_group_by_mode_and_the_mcp_argument():
    body = read_command("mlview-issues.md")
    for mode in ("rule", "file", "severity"):
        assert "--group-by" in body and mode in body
    assert "groupBy" in body, "the MCP argument name must be spelled, not guessed"
    assert "argument-hint" in body and "--group-by" in body.split("---")[1], (
        "the flag belongs in the frontmatter hint the user sees while typing"
    )


def test_the_grouped_output_contract_never_calls_a_group_count_an_issue_count():
    body = read_command("mlview-issues.md")
    assert "occurrences" in body, (
        "a group row is N occurrences of one rule, not N issues found"
    )
    assert "folds" in body or "folded" in body


# ------------------------------------------------------------------ ROADMAP COVERAGE
@pytest.mark.parametrize("name", COMMAND_FILES)
def test_a_single_file_target_is_reported_as_incomplete_not_as_clean(name):
    body = read_command(name)
    assert "single_file_analysis" in body, (
        "%s must tell the model what the diagnostic means; a shorter finding list "
        "from a narrower run is not a cleaner project" % name
    )
    assert "untagged_dataflow" in body
    for code in ("MLV301", "MLV302", "MLV401", "MLV501"):
        assert code in body, "%s must name the rules that cannot fire on one file" % name
    assert "file:" in body, "%s must offer the directory + --scope file: workaround" % name
