"""The active-doc gate catches broken operational links without rewriting history."""
import importlib.util
import re
from pathlib import Path

spec = importlib.util.spec_from_file_location("check_docs", Path(__file__).with_name("check_docs.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Evaluation and operator docs that name the pilot commands. A shell ">" truncates its target before
# the tool runs, which can erase recorded runs; the tools create their files exclusively instead.
EVALUATION_DOCS = (
    "evals/workflow/README.md", "evals/workflow/CANDIDATE_PROTOCOL.md",
    "evals/workflow/PILOT_READINESS.md", "evals/workflow/DEVELOPMENT_RUNS.md",
    "evals/workflow/reference-candidates/REVIEW_GUIDE.md", "evals/workflow/pilot/README.md",
    "scripts/README.md", "CONTRIBUTING.md", "docs/LLM_WORKFLOW.md",
)
REDIRECTED_TOOL = re.compile(r"python3? (?:tools|scripts)/[\w-]+\.py\b[^\n`]*?\s>>?\s*[^\s>]")


def test_current_tree_links():
    assert not module.run()[0]


def test_active_documents_are_current_guidance():
    # A document frozen with a historical banner describes older revisions; it must leave ACTIVE.
    assert "CLAUDE.md" in module.ACTIVE
    for relative in module.ACTIVE:
        first = (module.ROOT / relative).read_text(encoding="utf-8").splitlines()[0]
        assert not first.startswith(("> Historical record", "> Dated evaluation record")), relative


def test_pilot_protocol_documents_are_checked():
    for relative in ("evals/workflow/DEVELOPMENT_RUNS.md", "evals/workflow/pilot/README.md",
                     "evals/workflow/decisions/README.md",
                     "evals/workflow/reference-candidates/REVIEW_GUIDE.md",
                     "evals/workflow/PILOT_READINESS.md", "evals/workflow/CANDIDATE_PROTOCOL.md"):
        assert relative in module.ACTIVE, relative


def test_evaluation_docs_never_redirect_tool_output_into_a_file():
    assert REDIRECTED_TOOL.search("python tools/workflow_eval.py plan > .mlview/pilot-runs.json")
    assert REDIRECTED_TOOL.search("`python tools/workflow_eval.py baseline-plan >> runs.json`")
    assert not REDIRECTED_TOOL.search("python tools/workflow_eval.py plan --campaign pilot-01 --output plan.json")
    assert not REDIRECTED_TOOL.search("`python tools/workflow_eval.py check pilot-nanogpt`\n> Claim: a note")
    for relative in EVALUATION_DOCS:
        text = (module.ROOT / relative).read_text(encoding="utf-8")
        assert not REDIRECTED_TOOL.search(text), relative


def test_broken_link_and_shell_crlf_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "ACTIVE", ("README.md",))
    (tmp_path / "README.md").write_text("[missing](missing.md)\n[web](https://example.com)\n")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "test.sh").write_bytes(b"#!/bin/sh\r\n")
    problems, _ = module.run(tmp_path)
    assert len(problems) == 2
    assert any("dead local link" in p for p in problems)
    assert any("LF" in p for p in problems)


def test_relative_encoded_link_resolves_and_historical_docs_are_not_active(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "ACTIVE", ("README.md",))
    (tmp_path / "README.md").write_text("[file](a%20file.md#part)\n")
    (tmp_path / "a file.md").write_text("# Part\n")
    (tmp_path / "historical.md").write_text("[old](deleted-cli.py)\n")
    assert not module.run(tmp_path)[0]
