#!/usr/bin/env python
"""Regenerate the extension's scope fixture from a REAL analyzer run — without a home path in it.

    python vscode-extension/tools/make_scope_fixture.py            # write the fixture
    python vscode-extension/tools/make_scope_fixture.py --check    # verify only, exit 1 on drift

`vscode-extension/test/fixtures/vision_pipeline.graph.json` is what
`test/scope.test.js` (cursor -> `unit:` resolution, CONTRACTS §11.7/§11.11) and the
F2-A11 half of `test/diagnostics.test.js` assert against. Its whole value is that it
is what the analyzer ACTUALLY emits for `samples/vision_pipeline` rather than a
hand-written graph — so it has to be regenerated in the same change as any
graph-shape change (CONTRACTS §15.5, "Graph-shape changes"), and a stale copy means
the host suite is green against a document the product stopped producing.

Regenerating it by hand is what this script exists to prevent, because the raw
document is NOT publishable: `workspace.root`, every `nodes[].loc.absFile` and
`defLoc.absFile`, every `edges[].loc.absFile`, every `issues[].loc` /
`relatedLocs[]` / `fix.edits[].absFile` carry the absolute path of whoever ran the
command — 164 occurrences of one home directory on the machine this was last
regenerated on. So this script does the two steps together, every time:

  1. run the CLI over `samples/vision_pipeline` exactly as a user would
     (`python -m mlview analyze <project> --json <tmp> --format summary`), and
  2. rewrite every path that starts with THIS checkout's root to the neutral
     `/home/mlview/MLView` (`--fixture-root` to change it), forward-slashed, then
     refuse to write anything that still mentions this checkout or this home
     directory.

It also refuses two ways of producing a fixture that would look plausible and be
worthless: an interpreter below 3.10 (the CLI runs on macOS's 3.9 `python3` with the
bundled core, exits 0, and emits an empty document because `ast` has no `Match`), and
any run whose document analyzed no file or holds no node.

`--check` regenerates in a temporary directory and compares with the committed
fixture, ignoring only the two fields a re-run legitimately moves
(`generator.generatedAt` and `stats.durationMs`) — every other byte, including the
node and edge counts and `generator.rendererSha`, must match. Stdlib only, and
nothing here writes anywhere but the fixture and a temporary directory.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
EXTENSION_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(EXTENSION_ROOT)
PROJECT = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
FIXTURE = os.path.join(EXTENSION_ROOT, "test", "fixtures", "vision_pipeline.graph.json")

# The path the committed fixture pretends it was analyzed at. Neutral, stable, and
# owned by nobody: the tests only ever use it as a prefix (`scope.test.js` builds
# cursor URIs from `graph.workspace.root`), so its only requirements are that it is
# absolute and that it is not somebody's real home directory.
FIXTURE_ROOT = "/home/mlview/MLView"

# The only two fields that legitimately differ between two runs of the same tree.
# The same pair, for the same reason, as `VOLATILE` in
# `analyzer/tests/core/test_determinism.py`, which asserts there is no third.
VOLATILE = (("generator", "generatedAt"), ("stats", "durationMs"))


def _slashed(path: str) -> str:
    """`path` with forward slashes, the way every `absFile` in the document is written."""
    return os.path.abspath(path).replace("\\", "/")


def _rewrite(text: str, real_root: str, fixture_root: str) -> str:
    """One string, with a leading `real_root` (either slash) replaced by `fixture_root`."""
    slashed = text.replace("\\", "/")
    # The second pair is for Windows and macOS, where the same file is reachable as
    # `C:\Users\...` and `c:\users\...`, or with a differently-cased home directory.
    for candidate, root in ((slashed, real_root), (slashed.lower(), real_root.lower())):
        if candidate == root:
            return fixture_root
        if candidate.startswith(root + "/"):
            return fixture_root + slashed[len(root):]
    return text


def _walk(node: Any, real_root: str, fixture_root: str) -> Any:
    """The document with every string rewritten. Key order and everything else survive."""
    if isinstance(node, dict):
        return {k: _walk(v, real_root, fixture_root) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v, real_root, fixture_root) for v in node]
    if isinstance(node, str):
        return _rewrite(node, real_root, fixture_root)
    return node


def _leaks(text: str, real_root: str) -> List[str]:
    """Every reason this text must not be committed: this checkout, or this home."""
    found: List[str] = []
    lowered = text.lower()
    home = _slashed(os.path.expanduser("~"))
    for needle, why in ((real_root, "this checkout's root"), (home, "this home directory")):
        if not needle or needle == "/":
            continue
        for form in sorted({needle, needle.replace("/", "\\")}):
            # Case-insensitively, because that is how the rewrite matches: a form the
            # rewrite would have replaced must never survive into the fixture.
            count = lowered.count(form.lower())
            if count:
                found.append(f"{count}x {form} ({why})")
    return sorted(set(found))


def _canonical(doc: Dict[str, Any]) -> str:
    """The analyzer's own JSON shape — see `analyzer/src/mlview/emit/json_out.py`."""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _require_python_310(python: str) -> None:
    """Refuse an interpreter the analyzer cannot parse Python 3.10+ syntax with.

    This is not pedantry. `python3` on macOS 15 is 3.9.6, and with the bundled core on
    `PYTHONPATH` the CLI RUNS on it and exits 0 — it just fails to parse every file
    (`AttributeError: module 'ast' has no attribute 'Match'`) and emits an empty
    document: 0 nodes, 5 `parse_error` diagnostics. Writing that over the fixture
    would be silent, and `--check` would call the fixture stale when the interpreter
    is what is wrong.
    """
    probe = "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
    result = subprocess.run(
        [python, "-c", probe],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        raise SystemExit(
            f"make_scope_fixture: {python} is not a Python 3.10+, which the analyzer "
            "needs to parse the sample at all.\nPass --python, or run this script with "
            "the interpreter you analyze with."
        )


def _sanity(doc: Dict[str, Any]) -> None:
    """Refuse a document that analyzed nothing, whatever the CLI's exit status said."""
    workspace = doc.get("workspace", {})
    failed = workspace.get("filesFailed", 0)
    analyzed = workspace.get("filesAnalyzed", 0)
    if analyzed > 0 and not failed and doc.get("nodes"):
        return
    why = [
        f"{analyzed} files analyzed, {failed} failed, {len(doc.get('nodes', []))} nodes",
    ]
    for diagnostic in doc.get("diagnostics", [])[:3]:
        why.append(
            f"{diagnostic.get('kind')}: {diagnostic.get('message')} "
            f"({diagnostic.get('file')})"
        )
    raise SystemExit(
        "make_scope_fixture: the analyzer produced a document with nothing in it, so "
        "nothing was written or compared:\n  " + "\n  ".join(why)
    )


def _run_cli(python: str, out_path: str) -> str:
    """Analyze the sample into `out_path`; returns how `mlview` was found."""
    argv = [
        python,
        "-X",
        "utf8",
        "-m",
        "mlview",
        "analyze",
        PROJECT,
        "--json",
        out_path,
        "--format",
        "summary",
    ]
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    # An installed analyzer first, the extension's own bundled core second. The
    # second path is what makes this script runnable in the `vscode-extension` CI
    # job, which sets up Python and builds `vscode-extension/core/` (C2) but never
    # pip-installs the analyzer.
    attempts = [("the installed analyzer", env)]
    bundled = os.path.join(EXTENSION_ROOT, "core")
    if os.path.isdir(os.path.join(bundled, "mlview")):
        with_core = dict(env)
        with_core["PYTHONPATH"] = os.pathsep.join(
            [bundled] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
        )
        attempts.append(("the bundled core in vscode-extension/core", with_core))

    last = ""
    for how, attempt_env in attempts:
        result = subprocess.run(
            argv, cwd=REPO_ROOT, env=attempt_env, capture_output=True, text=True
        )
        if result.returncode == 0:
            return how
        last = (result.stderr or result.stdout or "").strip()
    raise SystemExit(
        "make_scope_fixture: could not run the analyzer with "
        f"{python!r}.\n{last}\n"
        "Install it (`pip install -e analyzer`), build the bundled core "
        "(`npm --prefix vscode-extension run compile`), or pass --python."
    )


def build(python: str, fixture_root: str) -> Tuple[Dict[str, Any], str]:
    """A neutralised document for `samples/vision_pipeline`, plus how it was produced."""
    real_root = _slashed(REPO_ROOT)
    _require_python_310(python)
    with tempfile.TemporaryDirectory(prefix="mlview-fixture-") as tmp:
        raw_path = os.path.join(tmp, "vision_pipeline.graph.json")
        how = _run_cli(python, raw_path)
        with open(raw_path, encoding="utf-8-sig") as fh:
            raw = json.load(fh)
    _sanity(raw)

    doc = _walk(raw, real_root, fixture_root)
    text = _canonical(doc)
    leaks = _leaks(text, real_root)
    if leaks:
        raise SystemExit(
            "make_scope_fixture: the neutralised document still carries a real path, "
            "so nothing was written:\n  " + "\n  ".join(leaks)
        )
    return doc, how


def _without_volatile(doc: Dict[str, Any]) -> Dict[str, Any]:
    """The document with the two per-run fields dropped; everything else must match."""
    copy = json.loads(json.dumps(doc))
    for section, field in VOLATILE:
        if isinstance(copy.get(section), dict):
            copy[section].pop(field, None)
    return copy


def _counts(doc: Dict[str, Any]) -> str:
    return (
        f"{len(doc.get('nodes', []))} nodes, {len(doc.get('edges', []))} edges, "
        f"{len(doc.get('issues', []))} issues"
    )


def _first_difference(fresh: Dict[str, Any], committed: Dict[str, Any]) -> str:
    """The shortest true statement about where the two documents part company."""
    keys = sorted(set(fresh) | set(committed))
    differing = [k for k in keys if fresh.get(k) != committed.get(k)]
    if not differing:
        return "the documents differ only in key order"
    parts = []
    for key in differing[:6]:
        a, b = fresh.get(key), committed.get(key)
        if isinstance(a, list) and isinstance(b, list) and len(a) != len(b):
            parts.append(f"{key}: {len(a)} fresh vs {len(b)} committed")
        elif key not in committed:
            parts.append(f"{key}: only in the fresh run")
        elif key not in fresh:
            parts.append(f"{key}: only in the committed fixture")
        else:
            parts.append(f"{key}: same size, different content")
    return "; ".join(parts)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate (or check) vscode-extension/test/fixtures/vision_pipeline.graph.json"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed fixture against a fresh run; write nothing",
    )
    parser.add_argument(
        "--fixture-root",
        default=FIXTURE_ROOT,
        help=f"the neutral absolute root every path is rewritten to (default {FIXTURE_ROOT})",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="the interpreter to run `-m mlview` with (default: the one running this script)",
    )
    args = parser.parse_args(argv)

    fixture_root = args.fixture_root.replace("\\", "/").rstrip("/")
    if not re.match(r"^(?:/|[A-Za-z]:/)", fixture_root):
        print(
            f"make_scope_fixture: --fixture-root must be absolute, got {args.fixture_root!r}",
            file=sys.stderr,
        )
        return 2

    fresh, how = build(args.python, fixture_root)
    text = _canonical(fresh)

    if args.check:
        if not os.path.exists(FIXTURE):
            print(f"make_scope_fixture: {FIXTURE} does not exist", file=sys.stderr)
            return 1
        with open(FIXTURE, encoding="utf-8-sig") as fh:
            committed = json.load(fh)
        if _canonical(_without_volatile(fresh)) == _canonical(_without_volatile(committed)):
            print(f"make_scope_fixture: the fixture matches a fresh run ({_counts(fresh)})")
            return 0
        print(
            "make_scope_fixture: the fixture is STALE — the analyzer on this tree emits a "
            "different document.\n"
            f"  fresh run: {_counts(fresh)}\n"
            f"  committed: {_counts(committed)}\n"
            f"  {_first_difference(_without_volatile(fresh), _without_volatile(committed))}\n"
            "Regenerate it with `python vscode-extension/tools/make_scope_fixture.py` and "
            "re-run `npm test` in vscode-extension — a graph-content change can move the "
            "scope assertions.",
            file=sys.stderr,
        )
        return 1

    os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
    with open(FIXTURE, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(
        f"make_scope_fixture: wrote {os.path.relpath(FIXTURE, REPO_ROOT)} "
        f"({_counts(fresh)}) with {how}, every path under {fixture_root}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
