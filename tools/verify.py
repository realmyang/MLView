#!/usr/bin/env python
"""The three parity gates: one analyzer, one renderer, one version.

    python tools/verify.py --all        # everything (also the default)
    python tools/verify.py --parity     # CLI graph == MCP graph
    python tools/verify.py --scopes     # Python project() == TypeScript project()
    python tools/verify.py --scopes --fuzz 200   # ... on 200 GENERATED graphs too
    python tools/verify.py --hashes     # one renderer bundle everywhere
    python tools/verify.py --versions   # one version string everywhere
    python tools/verify.py --docs       # the rule pages ship inside the plugin
    python tools/verify.py --vsix       # the analyzer bundled into the VSIX is current

Exit code 0 when every selected gate passes, 1 otherwise, with a table naming
what failed and how to fix it (CONTRACTS section 9, amendment A2).

**Gate 1 — one analyzer.** `python -m mlview analyze <corpus> --json -` and the
MCP server's `mlview_analyze` (driven as a real subprocess over stdio through the
`mcp` SDK client, then read back from the `graphPath` it returns) must produce
byte-identical documents once `generator.generatedAt` and `stats.durationMs` —
the only two fields the contract allows to vary — are stripped. This is what
stops the two hosts from slowly acquiring different analyzers. The server is then
run a *second* time over the same data directory, with its on-disk cache doctored
to look like an older analyzer's, and must still return the same document: a
cache that is blind to who produced it serves yesterday's graph forever, and
every scoped answer computed from it disagrees with the CLI (CONTRACTS 11.10,
11.15).

**Gate 2 — one renderer.** `webview/dist/`, `vscode-extension/media/` and
`analyzer/src/mlview/emit/assets/` hold byte-identical `mlview.js` / `mlview.css`,
and a freshly emitted document's `generator.rendererSha` equals the SHA-256 of
that `mlview.js`. A drifted viewer is then detectable from the data alone.

**Gate 4 — the plugin ships its own rule docs.** `claude-plugin/docs/rules/MLV*.md`
is byte-identical to `docs/rules/MLV*.md`. `mlview_explain(code=...)` can only find
a page under the plugin root once the plugin is installed, so a missing page means
every installed plugin answers rule questions with an empty document.

**Gate 5 — one projection**, implemented in `tools/gate_scopes.py`.
`contracts/scope.cases.json` (the ten-selector battery plus six error codes) and
`contracts/scope.expected.json` are regenerated from the Python
`mlview.core.project` and byte-diffed, then the viewer's
`webview/test/scope_parity.test.mjs` runs the SAME cases through the TypeScript
port and deep-compares. Two languages implement one algorithm (CONTRACTS 11.2 /
11.15); a change one side made and the other did not reddens this gate instead of
drifting silently. It sits between gate 1 and gate 2 because a scope divergence is
an analyzer fact, not a bundle fact.

**Gate 6 — the VSIX's own core.** PACKAGING bundles a third copy of
`analyzer/src/mlview` into `vscode-extension/core/mlview` so a marketplace install
works with no pip step at all. Since C2 that copy is a gitignored BUILD ARTIFACT
rather than a tracked directory — `npm run compile`, `npm run pretest` and
`vsce package`'s `vscode:prepublish` all write it through
`vscode-extension/tools/sync-core.mjs` — so this row is where "it was built, and
what was built is current" is asserted: it is byte-identical to
`analyzer/src/mlview`, it EXISTS (a missing copy is a build that did not happen,
i.e. a VSIX with no analyzer), and `.vscodeignore` does not exclude the directory
from the package. A VSIX that ships without its analyzer is green everywhere else
and broken on install (`docs/CONTRACTS.md §11.25`).

**Gate 3 — one version.** `mlview.version.__version__`, `analyzer/pyproject.toml`,
`vscode-extension/package.json`, `claude-plugin/.claude-plugin/plugin.json` and
`webview/package.json` all carry the same version string.
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate_scopes import check_scopes  # noqa: E402  (sibling module, not a package)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYZER_SRC = os.path.join(REPO_ROOT, "analyzer", "src")
SERVER = os.path.join(REPO_ROOT, "claude-plugin", "server", "mlview_mcp.py")
VENDOR = os.path.join(REPO_ROOT, "claude-plugin", "vendor")

VOLATILE = (("generator", "generatedAt"), ("stats", "durationMs"))

#: Corpora tried in order; the first that exists is the parity subject.
CORPUS_CANDIDATES = (
    os.path.join("samples", "vision_pipeline"),
    os.path.join("analyzer", "tests", "fixtures", "rules"),
    os.path.join("analyzer", "tests", "fixtures"),
)

Result = Tuple[str, bool, str]  # (gate name, passed, detail)


# ------------------------------------------------------------------------ helpers
def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _base_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)
    return env


def _cli_env() -> Dict[str, str]:
    """The CLI resolves `mlview` the way a user's shell does: the real analyzer."""
    env = _base_env()
    env["PYTHONPATH"] = ANALYZER_SRC
    return env


def _mcp_env() -> Dict[str, str]:
    """The server resolves `mlview` the way `.mcp.json` does: the vendored copy.

    Deliberately NOT the same source as the CLI: that is what makes gate 1
    catch a stale `claude-plugin/vendor` semantically, not just by file hash.
    """
    env = _base_env()
    env["PYTHONPATH"] = VENDOR
    # Importing out of vendor/ must not leave bytecode for `claude plugin install`
    # to copy into the distributed plugin.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _child_env() -> Dict[str, str]:
    return _cli_env()


def _strip_volatile(graph: Dict[str, Any]) -> Dict[str, Any]:
    """A deep copy with the two contract-declared volatile fields removed."""
    out = json.loads(json.dumps(graph))
    for section, field in VOLATILE:
        if isinstance(out.get(section), dict):
            out[section].pop(field, None)
    return out


def _canonical(graph: Dict[str, Any]) -> bytes:
    """Serialize for byte comparison, preserving the document's own key order."""
    return json.dumps(_strip_volatile(graph), ensure_ascii=False, indent=2).encode("utf-8")


def _first_difference(
    left: Dict[str, Any], right: Dict[str, Any],
    left_name: str = "CLI", right_name: str = "MCP",
) -> str:
    """A short, human-readable description of where two documents diverge."""
    for key in ("schemaVersion", "generator", "workspace", "stats"):
        if left.get(key) != right.get(key):
            return "section %r differs" % key
    for key in ("stages", "nodes", "edges", "issues", "diagnostics"):
        a, b = left.get(key) or [], right.get(key) or []
        if len(a) != len(b):
            return "%s: %s has %d, %s has %d" % (key, left_name, len(a), right_name, len(b))
        for index, (x, y) in enumerate(zip(a, b)):
            if x != y:
                ident = x.get("id") or x.get("code") or x.get("kind") if isinstance(x, dict) else index
                return "%s[%d] differs (%s)" % (key, index, ident)
    return "documents differ outside the compared sections"


def find_corpus() -> Optional[str]:
    for rel in CORPUS_CANDIDATES:
        full = os.path.join(REPO_ROOT, rel)
        if os.path.isdir(full):
            return rel.replace("\\", "/")
    return None


# --------------------------------------------------------------- gate 1: parity
def _cli_graph(corpus: str) -> Dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "mlview", "analyze", corpus, "--json", "-"],
        cwd=REPO_ROOT, env=_cli_env(), capture_output=True, shell=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "CLI exited %d: %s" % (proc.returncode, proc.stderr.decode("utf-8", "replace")[-400:])
        )
    return json.loads(proc.stdout.decode("utf-8"))


def _stale_the_cache(graph_path: str) -> None:
    """Make the server's on-disk cache look like one an OLDER analyzer wrote.

    The sidecar loses its analyzer identity — which is exactly the shape the
    pre-fix server wrote — and the document itself is mutilated. A server that
    keys its cache only on the *sources* now has a plausible-looking, wrong
    document sitting where it will find it; one that keys on the analyzer too
    re-analyzes and overwrites it. That difference is what the second half of
    gate 1 measures, and it is the only reason this gate can speak about a real
    `.mlview/` rather than only about a fresh temporary directory.
    """
    sidecar = graph_path + ".sig"
    if not os.path.isfile(sidecar):
        raise RuntimeError(
            "the server wrote %s without its .sig sidecar, so the cache cannot be "
            "keyed on anything at all" % os.path.basename(graph_path)
        )
    with open(sidecar, "r", encoding="utf-8") as fh:
        stored = json.load(fh)
    stored.pop("analyzer", None)
    with open(sidecar, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(stored, fh)
    with open(graph_path, "r", encoding="utf-8") as fh:
        graph = json.load(fh)
    graph["edges"] = (graph.get("edges") or [])[:1]  # the defect's own signature
    graph["nodes"] = (graph.get("nodes") or [])[:1]
    with open(graph_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(graph, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _mcp_graphs(corpus: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive the real MCP server over stdio; return (fresh graph, after-stale-cache).

    Two server processes share ONE data directory. The first analyzes and leaves
    a cache behind; between them that cache is rewritten to look like an older
    analyzer's (`_stale_the_cache`); the second must hand back the same document
    the first did. Without the second run the gate only ever sees an empty cache
    — which is how a stale `.mlview/graph-*.json` once served scoped answers that
    disagreed with the CLI while this gate reported "byte-identical".
    """
    import anyio
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def once(params: "StdioServerParameters") -> Tuple[str, Dict[str, Any]]:
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool("mlview_analyze", {"path": corpus})
                if result.is_error:
                    raise RuntimeError("mlview_analyze failed: %s" % result.content)
                payload = result.structured_content or {}
                graph_path = payload.get("graphPath")
                if not graph_path or not os.path.isfile(graph_path):
                    raise RuntimeError("mlview_analyze returned no readable graphPath")
                with open(graph_path, "r", encoding="utf-8") as fh:
                    return graph_path, json.load(fh)

    async def run() -> Tuple[Dict[str, Any], Dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="mlview-parity-") as data_dir:
            env = _mcp_env()
            env["MLVIEW_PROJECT_DIR"] = REPO_ROOT
            env["MLVIEW_DATA_DIR"] = data_dir
            env["MLVIEW_NO_OPEN"] = "1"
            params = StdioServerParameters(
                command=sys.executable,
                args=["-X", "utf8", SERVER],
                env=env,
                cwd=REPO_ROOT,
            )
            graph_path, fresh = await once(params)
            _stale_the_cache(graph_path)
            _, revived = await once(params)
            return fresh, revived

    return anyio.run(run)


def _vendor_is_stale() -> bool:
    """True when what the plugin ships no longer matches what the repo holds.

    `tools/sync-core.py --check` covers both vendored copies: `vendor/mlview`
    against `analyzer/src/mlview`, and `claude-plugin/docs/rules` against
    `docs/rules`. The commonest cause of a parity failure is not two analyzers —
    it is one analyzer and one stale copy of it, so the message should say which.
    """
    sync_core = os.path.join(REPO_ROOT, "tools", "sync-core.py")
    if not os.path.isfile(sync_core):
        return False
    proc = subprocess.run(
        [sys.executable, sync_core, "--check", "--quiet"],
        cwd=REPO_ROOT, env=_child_env(), capture_output=True, shell=False,
    )
    return proc.returncode != 0


def check_plugin_docs() -> List[Result]:
    """Gate 4 — the rule pages the plugin serves are IN the plugin.

    `mlview_explain(code=...)` resolves `docs/rules/<CODE>.md` under the plugin
    root and then the repo root; only the first exists in a real
    `claude plugin install`, so a plugin without them answers every rule question
    with an empty `doc` — and the triage skill's one safeguard against confidently
    reporting a non-bug is the false-positive section on that page.
    """
    source = os.path.join(REPO_ROOT, "docs", "rules")
    shipped = os.path.join(REPO_ROOT, "claude-plugin", "docs", "rules")
    page = lambda d: sorted(  # noqa: E731
        n for n in (os.listdir(d) if os.path.isdir(d) else [])
        if len(n) == 9 and n.startswith("MLV") and n.endswith(".md") and n[3:6].isdigit()
    )
    want, have = page(source), page(shipped)
    if not want:
        return [("plugin: rule docs", True, "no docs/rules in this checkout — nothing to ship")]
    missing = [n for n in want if n not in have]
    if missing:
        return [
            (
                "plugin: rule docs",
                False,
                "%d of %d pages missing from claude-plugin/docs/rules (%s%s) — "
                "run tools/sync-core.py"
                % (
                    len(missing), len(want), ", ".join(missing[:4]),
                    ", ..." if len(missing) > 4 else "",
                ),
            )
        ]
    drifted = [
        n for n in want
        if not filecmp.cmp(os.path.join(source, n), os.path.join(shipped, n), shallow=False)
    ]
    if drifted:
        return [
            (
                "plugin: rule docs",
                False,
                "%d page(s) differ from docs/rules (%s) — run tools/sync-core.py"
                % (len(drifted), ", ".join(drifted[:4])),
            )
        ]
    return [("plugin: rule docs", True, "%d pages ship inside claude-plugin/docs/rules" % len(want))]


def _corpus_fingerprint(corpus: str) -> str:
    """mtime+size of every .py under the corpus, so a mid-run edit is detectable."""
    root = os.path.join(REPO_ROOT, corpus.replace("/", os.sep))
    parts: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith((".", "__")))
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            try:
                stat = os.stat(os.path.join(dirpath, name))
            except OSError:
                continue
            parts.append("%s|%d|%d" % (name, stat.st_mtime_ns, stat.st_size))
    return hashlib.sha1(chr(10).join(parts).encode("utf-8")).hexdigest()


def check_parity(_attempt: int = 0) -> List[Result]:
    corpus = find_corpus()
    if corpus is None:
        return [("parity: CLI vs MCP", False, "no corpus found (samples/ or analyzer/tests/fixtures/)")]
    if not os.path.isdir(os.path.join(VENDOR, "mlview")):
        return [("parity: CLI vs MCP", False, "claude-plugin/vendor/mlview missing — run tools/sync-core.py")]

    before = _corpus_fingerprint(corpus)
    try:
        cli = _cli_graph(corpus)
    except Exception as exc:  # noqa: BLE001 - report, do not crash the gate table
        return [("parity: CLI vs MCP", False, "CLI failed: %s" % exc)]
    try:
        mcp, revived = _mcp_graphs(corpus)
    except Exception as exc:  # noqa: BLE001
        return [("parity: CLI vs MCP", False, "MCP failed: %s" % exc)]

    if _canonical(mcp) != _canonical(revived):
        return [
            (
                "parity: CLI vs MCP",
                False,
                "the MCP served a cache written by a different analyzer (%s) — "
                "load_graph must key its .sig sidecar on analyzer_identity()"
                % _first_difference(
                    _strip_volatile(mcp), _strip_volatile(revived),
                    "fresh", "from cache",
                ),
            )
        ]

    if _canonical(cli) != _canonical(mcp):
        # The two runs are sequential, so a corpus edited between them looks
        # exactly like a parity failure. Retry once before believing it.
        if _attempt == 0 and _corpus_fingerprint(corpus) != before:
            return check_parity(_attempt + 1)

    if _canonical(cli) != _canonical(mcp) and _vendor_is_stale():
        return [
            (
                "parity: CLI vs MCP",
                False,
                "documents differ AND claude-plugin/vendor is stale — "
                "run `python tools/sync-core.py`, then re-run",
            )
        ]

    vendor_row: Result = (
        ("vendor: synced core", False, "claude-plugin/vendor has drifted — run tools/sync-core.py")
        if _vendor_is_stale()
        else ("vendor: synced core", True, "matches analyzer/src/mlview")
    )

    if _canonical(cli) == _canonical(mcp):
        return [
            (
                "parity: CLI vs MCP",
                True,
                "%s — %d nodes, %d edges, byte-identical"
                % (corpus, len(cli.get("nodes", [])), len(cli.get("edges", []))),
            ),
            vendor_row,
        ]
    return [
        (
            "parity: CLI vs MCP",
            False,
            "%s — %s" % (corpus, _first_difference(_strip_volatile(cli), _strip_volatile(mcp))),
        )
    ]


# --------------------------------------------------- gate 6: the VSIX's own core
def _sync_core_module():
    """`tools/sync-core.py` as a module. The hyphen makes a plain import illegal."""
    import importlib.util  # noqa: PLC0415 - only this gate needs it

    path = os.path.join(REPO_ROOT, "tools", "sync-core.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("mlview_sync_core", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_vsix_core() -> List[Result]:
    """Gate 6 — the analyzer the VSIX ships is the analyzer this repo holds.

    PACKAGING creates a THIRD copy of `analyzer/src/mlview` so a marketplace
    install works on a machine with a bare Python and no MLView checkout
    (`docs/CONTRACTS.md §11.25`). A third copy is only safe while a gate
    refuses to let it drift, which is why the lead decision that granted it made
    this row a condition of the same change. `.vscodeignore` keeps `core/` in the
    package, so a drifted copy is an analyzer that ships to users and to nobody's
    tests.

    C2 made that copy gitignored and built rather than tracked, which changes
    nothing here except the message: this row is STRICT about the directory
    existing, because after a build it must, while the bare
    `tools/sync-core.py --check` (which also runs on fresh clones, in the plugin
    CI job) reports an unbuilt copy as "not built" instead.
    """
    sync_core = _sync_core_module()
    if sync_core is None:
        return [("vsix: synced core", False, "tools/sync-core.py is missing")]
    copies = {copy.key: copy for copy in sync_core.COPIES}
    copy = copies.get("vsix")
    if copy is None:
        return [
            (
                "vsix: synced core",
                False,
                "tools/sync-core.py does not vendor vscode-extension/core/mlview",
            )
        ]
    ok, detail = sync_core.check_tree(copy)
    if ok:
        # A `.vscodeignore` that excluded the directory would ship a VSIX whose
        # bundled core is missing entirely — green here, broken on install.
        ignore = os.path.join(REPO_ROOT, "vscode-extension", ".vscodeignore")
        if os.path.isfile(ignore):
            with open(ignore, "r", encoding="utf-8") as fh:
                patterns = [line.strip() for line in fh if line.strip() and not line.startswith("#")]
            # `core/**/__pycache__/**` and `**/*.pyc` are bytecode rules, not an
            # exclusion of the core itself; only a pattern that would drop SOURCE
            # out of the package is a failure here.
            excluded = [
                p for p in patterns
                if (p == "core" or p.startswith(("core/", "core\\")))
                and "__pycache__" not in p
                and not p.endswith((".pyc", ".pyo", ".pyd"))
            ]
            if excluded:
                return [
                    (
                        "vsix: synced core",
                        False,
                        ".vscodeignore excludes the bundled core (%s) — the VSIX would ship "
                        "without an analyzer" % ", ".join(excluded),
                    )
                ]
    return [("vsix: synced core", ok, detail)]


# --------------------------------------------------------------- gate 2: hashes
def check_hashes() -> List[Result]:
    results: List[Result] = []
    dirs = {
        "webview/dist": os.path.join(REPO_ROOT, "webview", "dist"),
        "vscode-extension/media": os.path.join(REPO_ROOT, "vscode-extension", "media"),
        "analyzer emit/assets": os.path.join(
            REPO_ROOT, "analyzer", "src", "mlview", "emit", "assets"
        ),
    }
    for asset in ("mlview.js", "mlview.css"):
        digests: Dict[str, Optional[str]] = {}
        for label, directory in dirs.items():
            path = os.path.join(directory, asset)
            digests[label] = _sha256(path) if os.path.isfile(path) else None
        missing = [label for label, digest in digests.items() if digest is None]
        if missing:
            results.append(
                (
                    "renderer: %s" % asset,
                    False,
                    "missing in %s — run tools/sync-assets.py" % ", ".join(missing),
                )
            )
            continue
        unique = set(digests.values())
        if len(unique) == 1:
            results.append(("renderer: %s" % asset, True, next(iter(unique))[:16] + " everywhere"))
        else:
            results.append(
                (
                    "renderer: %s" % asset,
                    False,
                    "; ".join("%s=%s" % (k, (v or "-")[:12]) for k, v in sorted(digests.items())),
                )
            )

    bundle = os.path.join(REPO_ROOT, "analyzer", "src", "mlview", "emit", "assets", "mlview.js")
    expected = _sha256(bundle) if os.path.isfile(bundle) else "0" * 64
    try:
        sys.path.insert(0, ANALYZER_SRC)
        from mlview.api import AnalyzeOptions, analyze_to_dict  # noqa: PLC0415

        corpus = find_corpus() or "."
        graph = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(REPO_ROOT, corpus),)))
        actual = graph.get("generator", {}).get("rendererSha", "")
    except Exception as exc:  # noqa: BLE001
        results.append(("renderer: rendererSha", False, "could not emit a document: %s" % exc))
        return results

    if actual == expected:
        note = "matches emit/assets/mlview.js" if expected != "0" * 64 else "64 zeros (bundle not synced)"
        results.append(("renderer: rendererSha", True, note))
    else:
        results.append(
            (
                "renderer: rendererSha",
                False,
                "document says %s, bundle hashes %s" % (actual[:16], expected[:16]),
            )
        )
    return results


# -------------------------------------------------------------- gate 3: versions
def _json_version(rel: str, *keys: str) -> Tuple[str, Optional[str]]:
    path = os.path.join(REPO_ROOT, rel.replace("/", os.sep))
    if not os.path.isfile(path):
        return rel, None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return rel, None
    node: Any = data
    for key in keys:
        if not isinstance(node, dict):
            return rel, None
        node = node.get(key)
    return rel, node if isinstance(node, str) else None


def _pyproject_version() -> Tuple[str, Optional[str]]:
    rel = "analyzer/pyproject.toml"
    path = os.path.join(REPO_ROOT, "analyzer", "pyproject.toml")
    if not os.path.isfile(path):
        return rel, None
    try:
        import tomllib

        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        value = data.get("project", {}).get("version")
        return rel, value if isinstance(value, str) else None
    except Exception:  # noqa: BLE001 - fall back to a line scan
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("version"):
                    return rel, stripped.split("=", 1)[-1].strip().strip('"').strip("'")
    return rel, None


def _core_version() -> Tuple[str, Optional[str]]:
    try:
        sys.path.insert(0, ANALYZER_SRC)
        from mlview.version import __version__  # noqa: PLC0415

        return "mlview.version.__version__", __version__
    except Exception:  # noqa: BLE001
        return "mlview.version.__version__", None


def check_versions() -> List[Result]:
    found = [
        _core_version(),
        _pyproject_version(),
        _json_version("vscode-extension/package.json", "version"),
        _json_version("claude-plugin/.claude-plugin/plugin.json", "version"),
        _json_version("webview/package.json", "version"),
    ]
    missing = [name for name, value in found if value is None]
    values = {value for _, value in found if value is not None}
    if missing:
        return [("version: single string", False, "unreadable: %s" % ", ".join(missing))]
    if len(values) == 1:
        return [("version: single string", True, "%s in all %d manifests" % (next(iter(values)), len(found)))]
    return [
        (
            "version: single string",
            False,
            "; ".join("%s=%s" % (name, value) for name, value in found),
        )
    ]


# ---------------------------------------------------------------------- reporting
def print_table(results: List[Result]) -> None:
    width = max([len(name) for name, _, _ in results] + [20])
    print("")
    print("  %-6s %-*s  %s" % ("", width, "GATE", "DETAIL"))
    print("  %s" % ("-" * (width + 40)))
    for name, ok, detail in results:
        print("  %-6s %-*s  %s" % ("PASS" if ok else "FAIL", width, name, detail))
    failed = [name for name, ok, _ in results if not ok]
    print("")
    if failed:
        print("  %d of %d gates FAILED: %s" % (len(failed), len(results), ", ".join(failed)))
    else:
        print("  all %d gates passed" % len(results))
    print("")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify", description="MLView parity gates: one analyzer, one renderer, one version."
    )
    parser.add_argument("--parity", action="store_true", help="CLI graph == MCP graph")
    parser.add_argument("--scopes", action="store_true",
                        help="the scope battery projects identically in Python and TypeScript")
    parser.add_argument("--hashes", action="store_true", help="one renderer bundle everywhere")
    parser.add_argument("--versions", action="store_true", help="one version string everywhere")
    parser.add_argument("--docs", action="store_true", help="the rule pages ship inside the plugin")
    parser.add_argument("--vsix", action="store_true",
                        help="the analyzer bundled into the extension matches analyzer/src")
    parser.add_argument("--all", action="store_true", help="every gate (the default)")
    # HEALTH-02 / CONTRACTS 11.30: an extra row on --scopes, off unless asked for.
    parser.add_argument("--fuzz", type=int, default=0, metavar="N",
                        help="also differential-fuzz the two project() ports over N "
                             "generated graphs (200 locally, 2000 nightly); needs --scopes")
    args = parser.parse_args(argv)

    run_all = args.all or not (
        args.parity or args.scopes or args.hashes or args.versions or args.docs or args.vsix
    )
    results: List[Result] = []
    if run_all or args.versions:
        results += check_versions()
    if run_all or args.docs:
        results += check_plugin_docs()
    # CONTRACTS 11.15: the scope gate sits BETWEEN the CLI-vs-MCP parity gate and
    # the bundle-hash gate, so a table read top to bottom goes analyzer, then
    # projection, then renderer.
    if run_all or args.parity:
        results += check_parity()
    # PACKAGING: `vendor: synced core` (emitted by check_parity) and this row are the
    # same guarantee about the two shipped copies, so they sit next to each other.
    if run_all or args.vsix:
        results += check_vsix_core()
    if run_all or args.scopes:
        results += check_scopes(REPO_ROOT, _cli_env, _base_env)
        # HEALTH-02 (CONTRACTS 11.30) — begin. The generated battery, imported
        # lazily so `--all` pays nothing for a flag it was not given.
        if args.fuzz > 0:
            sys.path.insert(0, os.path.join(REPO_ROOT, "analyzer", "tools"))
            from scope_fuzz import check_fuzz  # noqa: PLC0415

            results += check_fuzz(REPO_ROOT, _cli_env, _base_env, args.fuzz)
        # HEALTH-02 — end.
    if run_all or args.hashes:
        results += check_hashes()

    print_table(results)
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
