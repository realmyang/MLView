"""CACHE: the content-addressed fact cache and the one `file_signature`
(CONTRACTS 11.28).

The whole point of a cache is that it can only change how long an answer takes,
never what the answer is, so most of this file is byte-equality: cold against
warm, warm against a run with the cache disabled, and a run after one file was
edited against a cold run of the same tree. The rest is the trust boundary — a
sidecar that fails its MAC, one written by a different analyzer, and one that
is simply garbage must all be *ignored*, never obeyed and never fatal.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

import pytest

from core_support import REPO_ROOT

from mlview.api import AnalyzeOptions, analyze_to_dict, digest
from mlview.core import cache as C
from mlview.core.pipeline import run

TORCH_MODULE = (
    "import torch\n"
    "import torch.nn as nn\n\n\n"
    "class Net(nn.Module):\n"
    "    def __init__(self):\n"
    "        super().__init__()\n"
    "        self.fc = nn.Linear(4, 2)\n\n"
    "    def forward(self, x):\n"
    "        return self.fc(x)\n"
)
PLAIN_MODULE = '"""Plain."""\nimport json\n\n\ndef load(text):\n    return json.loads(text)\n'


@pytest.fixture
def cache_home(tmp_path, monkeypatch):
    """Point the MAC secret and the sidecar directory at the test's tmp dir."""
    monkeypatch.setenv("MLVIEW_CACHE_KEY_FILE", str(tmp_path / "keys" / "cache.key"))
    monkeypatch.setenv("MLVIEW_CACHE_DIR", str(tmp_path / "cachedir"))
    monkeypatch.delenv("MLVIEW_NO_CACHE", raising=False)
    return tmp_path


@pytest.fixture
def workspace(make_workspace):
    files = {"train.py": TORCH_MODULE + "\nMODEL = Net()\n"}
    for index in range(8):
        files["app_%d.py" % index] = PLAIN_MODULE
    return make_workspace(files)


def _sha(doc):
    doc = json.loads(json.dumps(doc))
    doc.get("generator", {}).pop("generatedAt", None)
    doc.get("stats", {}).pop("durationMs", None)
    return hashlib.sha256(json.dumps(doc, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _analyze(root, **kwargs):
    kwargs.setdefault("relevance", "ml")
    return run(AnalyzeOptions(paths=(root,), max_files=4000, **kwargs))


# ------------------------------------------------------------ file_signature
def test_file_signature_is_keyed_on_content_not_on_mtime(make_workspace):
    """The defect the promotion exists to fix. `st_mtime_ns` changes when a
    checkout restores a file and does not change on a filesystem with coarse
    timestamps - the second direction is the one that serves a stale answer."""
    root = make_workspace({"a.py": "x = 1\n"})
    before = C.file_signature(root)
    os.utime(os.path.join(root, "a.py"), (time.time() + 5000, time.time() + 5000))
    assert C.file_signature(root) == before, "mtime must not move the signature"
    with open(os.path.join(root, "a.py"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("x = 2\n")
    assert C.file_signature(root) != before, "content must move the signature"


def test_file_signature_notices_an_added_and_a_removed_file(make_workspace):
    root = make_workspace({"a.py": "x = 1\n"})
    alone = C.file_signature(root)
    with open(os.path.join(root, "b.py"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("y = 2\n")
    assert C.file_signature(root) != alone
    os.remove(os.path.join(root, "b.py"))
    assert C.file_signature(root) == alone


def test_file_signature_works_on_a_single_file_too(make_workspace):
    root = make_workspace({"a.py": "x = 1\n"})
    value = C.file_signature(os.path.join(root, "a.py"))
    assert len(value) == 16 and int(value, 16) >= 0


def test_file_signature_ignores_what_discovery_ignores(make_workspace):
    """The signature must cover the files that would actually be analyzed:
    a `.mlview` sidecar or a `__pycache__` must never invalidate it."""
    root = make_workspace({"a.py": "x = 1\n"})
    before = C.file_signature(root)
    os.makedirs(os.path.join(root, "__pycache__"), exist_ok=True)
    with open(os.path.join(root, "__pycache__", "a.py"), "w", encoding="utf-8") as fh:
        fh.write("noise = 1\n")
    assert C.file_signature(root) == before


def test_analyzer_identity_is_stable_and_not_the_unknown_sentinel():
    C.reset_identity_cache()
    first = C.analyzer_identity()
    assert not first.startswith("unknown-")
    assert first == C.analyzer_identity()
    C.reset_identity_cache()
    assert C.analyzer_identity() == first


# ---------------------------------------------------------------- lifecycle
def test_a_cold_run_writes_a_sidecar_and_a_warm_run_hits_it(cache_home, workspace):
    cold = _analyze(workspace)
    assert cold.cache.status == "none" and cold.cache.hits == 0
    assert os.path.isfile(cold.cache.path)
    warm = _analyze(workspace)
    assert warm.cache.status == "full"
    assert warm.cache.hits == 9 and warm.cache.misses == 0
    assert _sha(cold.graph.to_dict()) == _sha(warm.graph.to_dict())


def test_a_warm_run_is_byte_identical_to_one_with_the_cache_disabled(
        cache_home, workspace):
    _analyze(workspace)
    warm = _analyze(workspace)
    off = _analyze(workspace, cache=False)
    assert off.cache is None
    assert _sha(warm.graph.to_dict()) == _sha(off.graph.to_dict())


def test_editing_one_file_is_a_partial_hit_and_still_byte_identical(
        cache_home, workspace):
    """The acceptance criterion: only the changed module's facts are
    recomputed, and the document is byte-identical to a cold run."""
    _analyze(workspace)
    target = os.path.join(workspace, "train.py")
    with open(target, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n\ndef extra():\n    return Net()\n")
    delta = _analyze(workspace)
    assert delta.cache.status == "partial"
    assert delta.cache.misses == 1 and delta.cache.hits == 8
    cold = _analyze(workspace, cache=False)
    assert _sha(delta.graph.to_dict()) == _sha(cold.graph.to_dict())


def test_a_new_file_only_costs_its_own_entry(cache_home, workspace):
    _analyze(workspace)
    with open(os.path.join(workspace, "extra.py"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(PLAIN_MODULE)
    delta = _analyze(workspace)
    assert delta.cache.hits == 9 and delta.cache.misses == 1


def test_two_runs_of_the_same_tree_are_deterministic_with_the_cache_on(
        cache_home, workspace):
    first = _analyze(workspace)
    second = _analyze(workspace)
    assert _sha(first.graph.to_dict()) == _sha(second.graph.to_dict())


# ------------------------------------------------------------------ the off switch
def test_mlview_no_cache_disables_it(cache_home, workspace, monkeypatch):
    monkeypatch.setenv("MLVIEW_NO_CACHE", "1")
    assert C.is_disabled() is True
    assert C.open_cache(workspace) is None
    result = _analyze(workspace)
    assert result.cache is None


def test_the_cache_is_never_consulted_in_all_mode(cache_home, workspace):
    """`--relevance all` has nothing to decide, so it neither reads nor writes
    the sidecar and costs exactly what it always cost."""
    result = _analyze(workspace, relevance="all")
    assert result.cache is None
    assert not os.path.isdir(os.environ["MLVIEW_CACHE_DIR"])


def test_the_sidecar_lives_where_the_environment_says(cache_home, workspace):
    result = _analyze(workspace)
    assert result.cache.path.startswith(
        os.environ["MLVIEW_CACHE_DIR"].replace("\\", "/"))


def test_the_default_sidecar_directory_is_inside_the_project(monkeypatch, workspace):
    monkeypatch.delenv("MLVIEW_CACHE_DIR", raising=False)
    assert C.cache_dir_for(workspace).endswith("/.mlview/cache")


def test_the_sidecar_is_never_analyzed(cache_home, workspace):
    """`.mlview` is in discovery's always-prune set, so the cache can never
    become input to the analysis it is caching."""
    from mlview.ingest.discover import ALWAYS_PRUNE, discover

    assert ".mlview" in ALWAYS_PRUNE
    _analyze(workspace)
    monkeypatched = _analyze(workspace)
    assert monkeypatched.graph.filesAnalyzed == 1
    found = discover([workspace], max_files=4000)
    assert all(".mlview" not in name for name in found.files)


# ------------------------------------------------------------------- trust
def _sidecar(root):
    result = _analyze(root)
    return result.cache.path


def test_a_tampered_sidecar_is_ignored_not_obeyed(cache_home, workspace):
    """A hand-written sidecar could mark a framework file as "not a seed" and
    quietly delete findings. The MAC is what stops a repository shipping one."""
    path = _sidecar(workspace)
    with open(path, "rb") as fh:
        header, _nl, payload = fh.read().partition(b"\n")
    entries = json.loads(payload.decode("utf-8"))
    for row in entries.values():
        row["s"] = 0                                   # "nothing here is ML"
    forged = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(header + b"\n" + forged)
    after = _analyze(workspace)
    assert after.cache.status == "none", "a forged sidecar must not be trusted"
    assert after.graph.filesAnalyzed == 1
    cold = _analyze(workspace, cache=False)
    assert _sha(after.graph.to_dict()) == _sha(cold.graph.to_dict())


def test_a_sidecar_from_a_different_analyzer_is_ignored(cache_home, workspace):
    path = _sidecar(workspace)
    with open(path, "rb") as fh:
        header, _nl, payload = fh.read().partition(b"\n")
    meta = json.loads(header.decode("utf-8"))
    meta["analyzer"] = "0.0.1+deadbeefdeadbeef"
    with open(path, "wb") as fh:
        fh.write(json.dumps(meta, sort_keys=True).encode("utf-8") + b"\n" + payload)
    after = _analyze(workspace)
    assert after.cache.status == "none"


def test_a_sidecar_from_another_python_is_ignored(cache_home, workspace):
    path = _sidecar(workspace)
    with open(path, "rb") as fh:
        header, _nl, payload = fh.read().partition(b"\n")
    meta = json.loads(header.decode("utf-8"))
    meta["python"] = "2.7"
    with open(path, "wb") as fh:
        fh.write(json.dumps(meta, sort_keys=True).encode("utf-8") + b"\n" + payload)
    assert _analyze(workspace).cache.status == "none"


@pytest.mark.parametrize("garbage", [b"", b"not json at all", b"{}\n", b"{}"])
def test_a_corrupt_sidecar_is_a_cold_cache_not_a_crash(cache_home, workspace, garbage):
    path = _sidecar(workspace)
    with open(path, "wb") as fh:
        fh.write(garbage)
    after = _analyze(workspace)
    assert after.cache.status == "none"
    assert after.graph.filesAnalyzed == 1


def test_the_mac_secret_lives_outside_the_analyzed_project(cache_home, workspace):
    """A repository that ships a `.mlview/cache` must not be able to ship the
    key that authenticates it."""
    _analyze(workspace)
    key = os.environ["MLVIEW_CACHE_KEY_FILE"]
    assert os.path.isfile(key)
    assert not os.path.abspath(key).startswith(os.path.abspath(workspace))
    assert os.path.getsize(key) == 32


def test_the_sidecar_is_plain_json_and_never_a_pickle(cache_home, workspace):
    """Measured: pickling an AST is slower than re-parsing it, so nothing
    executable is ever written. The payload must stay readable as JSON."""
    path = _sidecar(workspace)
    with open(path, "rb") as fh:
        _header, _nl, payload = fh.read().partition(b"\n")
    entries = json.loads(payload.decode("utf-8"))
    assert set(entries) == {"train.py"} | {"app_%d.py" % i for i in range(8)}
    assert set(entries["train.py"]) == {"h", "s", "i"}


# ------------------------------------------------------------------ report
def test_the_report_words_are_the_contractual_ones(cache_home, workspace):
    assert C.CacheReport().status == "off"
    cold = _analyze(workspace)
    assert cold.cache.status == "none"
    assert _analyze(workspace).cache.status == "full"
    assert "cached: full" in _analyze(workspace).cache.line()


def test_the_status_reaches_a_model_through_the_digest(cache_home, workspace):
    result = _analyze(workspace)
    doc = result.graph.to_dict()
    assert "cached" not in digest(doc)
    assert digest(doc, cached=result.cache.status)["cached"] == "none"
    assert len(json.dumps(digest(doc, cached="partial")).encode("utf-8")) <= 4096


def test_the_status_is_logged_and_never_printed_to_stdout(cache_home, workspace, caplog,
                                                          capsys):
    with caplog.at_level("INFO", logger="mlview.cache"):
        _analyze(workspace)
        _analyze(workspace)
    assert any("cached: full" in record.getMessage() for record in caplog.records)
    assert capsys.readouterr().out == ""


def test_the_stderr_switch_is_opt_in(cache_home, workspace, monkeypatch, capsys):
    _analyze(workspace)
    assert capsys.readouterr().err == ""
    monkeypatch.setenv("MLVIEW_CACHE_LOG", "1")
    _analyze(workspace)
    captured = capsys.readouterr()
    assert "cached:" in captured.err and captured.out == ""


# ------------------------------------------------------------- the CLI flag
def test_the_no_cache_flag_reaches_the_options():
    from mlview.cli import build_parser
    from mlview.cli_parser import RELEVANCE_MODES

    parser = build_parser()
    args = parser.parse_args(["analyze", ".", "--no-cache", "--relevance", "ml",
                              "--relevance-hops", "3"])
    assert args.no_cache is True
    assert args.relevance == "ml" and args.relevance_hops == 3
    assert RELEVANCE_MODES == ("ml", "all")
    plain = parser.parse_args(["analyze", "."])
    assert plain.no_cache is False and plain.relevance == "all"


def test_the_demo_path_is_untouched_by_either_feature():
    """`--demo` emits the golden bytes and never analyzes anything."""
    from mlview.api import demo_bytes

    sample = os.path.join(REPO_ROOT, "contracts", "graph.sample.json")
    with open(sample, "rb") as fh:
        assert demo_bytes() == fh.read()


# ------------------------------------------------- the MAC secret round-trips
def _emulate_windows_text_mode(monkeypatch):
    """Make this platform behave like Windows' `os.open` for `core/cache`.

    Only used where the real `os.O_BINARY` does NOT exist. On Windows the real
    thing is already under test and layering an emulation on top of it would
    translate the bytes twice.
    """
    o_binary = 0x8000
    monkeypatch.setattr(C, "O_BINARY", o_binary)
    real_open, real_write = C.os.open, C.os.write
    text_fds = set()

    def text_mode_open(path, flags, *rest):
        fd = real_open(path, flags & ~o_binary, *rest)
        if not flags & o_binary:
            text_fds.add(fd)
        return fd

    def translating_write(fd, data):
        if fd in text_fds:
            data = data.replace(b"\n", b"\r\n")
        return real_write(fd, data)

    monkeypatch.setattr(C.os, "open", text_mode_open)
    monkeypatch.setattr(C.os, "write", translating_write)


def test_the_mac_secret_reads_back_exactly_as_it_was_written(cache_home, monkeypatch):
    """The secret is BYTES, and it must survive the filesystem unaltered.

    `os.open` on Windows opens in TEXT mode unless `os.O_BINARY` is passed, and
    a 32-byte random secret contains a 0x0A byte about 12% of the time
    (1 - (255/256)**32). Without the flag the creating run MACs with the 32
    bytes it holds while every later run MACs with the CR-mangled bytes it
    reads back, so `cached: full` never happens again and the sidecar is
    rejected with `cache MAC mismatch` forever. That is a silent, permanent
    loss of the whole CACHE feature for one Windows user in eight - it showed
    up as an intermittent red `e2e (windows, powershell)`, on a different
    `test_cache.py` case each time because the file is randomly ordered.

    A secret of nothing but newline bytes makes the failure certain rather than
    12% likely. On Windows this runs against the real `os.open`; everywhere else
    a Windows is stood in for, so dropping `O_BINARY` from `core/cache._secret`
    reddens on Linux and macOS too instead of waiting for an unlucky runner.
    """
    monkeypatch.setattr(C.os, "urandom", lambda n: b"\n\r\n" * 11)
    if not getattr(os, "O_BINARY", 0):
        _emulate_windows_text_mode(monkeypatch)

    written = C._secret()
    assert written is not None and len(written) >= 32
    read_back = C._secret()               # the file now exists: this is the read path
    assert read_back == written, "the secret changed between writing and reading it"
    with open(C._key_file(), "rb") as handle:
        assert handle.read() == written, "the bytes on disk are not the bytes we MAC with"
