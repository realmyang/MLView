"""The active-doc gate catches broken operational links without rewriting history."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("check_docs", Path(__file__).with_name("check_docs.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_current_tree_links():
    assert not module.run()[0]


def test_active_documents_are_current_guidance():
    # A document frozen with a historical banner describes older revisions; it must leave ACTIVE.
    assert "CLAUDE.md" in module.ACTIVE
    for relative in module.ACTIVE:
        first = (module.ROOT / relative).read_text(encoding="utf-8").splitlines()[0]
        assert not first.startswith(("> Historical record", "> Dated evaluation record")), relative


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
