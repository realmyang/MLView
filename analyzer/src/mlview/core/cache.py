"""CACHE (ROADMAP `CACHE`, CONTRACTS 11.28) — the content-addressed fact cache.

Three things live here and nothing else:

* **`file_signature`** — the one implementation. `claude-plugin/server/mlview_workspace.py`
  had its own, keyed on **mtime and size**; mtime is unreliable on a network
  filesystem and on a checkout that restores content but not timestamps, and a
  key that can miss a real change is how a stale document reaches a caller.
  This one is keyed on **content**, so two identical trees signature the same
  wherever and whenever they are.
* **`analyzer_identity`** — the other half of every key. A cache file outlives
  the process that wrote it, therefore it outlives the build that wrote it.
* **`FactCache`** — the per-file sidecar the relevance prefilter reads, so that
  a file which is neither framework-touching nor near anything that is need not
  be parsed at all on a re-analysis.

**What is cached, and what measurement decided it.** The per-file facts stored
here are the two that PERF-03 needs and that depend on one file's bytes and
nothing else: *is this file a seed* and *what does it import*. Nothing else is
stored, and the two obvious candidates were both measured and rejected:

===============================  ==========  ==========  =========================
phase (501-file mixed synthetic)  recompute   from cache  verdict
===============================  ==========  ==========  =========================
``ast`` parse                      313 ms      344 ms     **slower** — not cached
symbol table + scopes + calls      324 ms      380 ms     **slower** — not cached
seed flag + import rows            116 ms        2 ms     cached
===============================  ==========  ==========  =========================

Pickling a CPython AST is not cheaper than re-parsing it: the parser is C and
the object graph is thousands of small objects either way. Caching it would
have cost 7 MB per workspace, a `pickle` trust boundary and 30 ms, to save
nothing. The IR facts additionally depend on `dotted_names` — the set of every
module in the workspace — so a cache of them has to be thrown away whenever a
file is created, which is the day a cache most needs to be right. **Both are
recomputed on every run**, and the cross-module fixed point and every rule
always re-run over the whole kept set, which is what keeps cross-file findings
intact.

**The key** is `(content digest, analyzer identity, python major.minor)`, with
the workspace root folded into the file name *and* into the directory name.
Nothing about the analysis *options* is in it, because nothing about them
changes what a file imports.

**Where it lives.** In the **user's** cache directory, never in the analyzed
folder: `python -m mlview analyze <somebody else's repo>` writes nothing into
that repo. `MLVIEW_CACHE_DIR` overrides, which is what a host with its own
storage (and a CI job that collects the sidecar as an artifact) passes.

**Trust.** The sidecar is JSON, never executable, and it is authenticated with
an HMAC over a 32-byte secret stored in the **user's** home
(`~/.mlview/cache.key`, mode 0600) and never in the analyzed project — a
repository that ships a crafted `.mlview/cache` cannot forge one, and a payload
whose MAC does not verify is discarded. Without that, a hand-written sidecar
could mark a framework file as "not a seed" and quietly delete findings.

Environment:

===========================  ==================================================
``MLVIEW_NO_CACHE=1``        disable it entirely (`--no-cache` does the same)
``MLVIEW_CACHE_DIR``         where sidecars live (default: the user's own cache
                             directory - ``$XDG_CACHE_HOME/mlview``, else
                             ``%LOCALAPPDATA%/mlview`` on Windows,
                             ``~/Library/Caches/mlview`` on macOS,
                             ``~/.cache/mlview`` elsewhere - under a directory
                             named for the workspace path's hash. **Never**
                             inside the analyzed folder.)
``MLVIEW_CACHE_KEY_FILE``    where the MAC secret lives (default ``~/.mlview/cache.key``)
``MLVIEW_CACHE_MAX_ENTRIES`` entry ceiling, default 20000
``MLVIEW_CACHE_LOG=1``       write the one-line status to stderr as well as to logging
===========================  ==================================================
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

__all__ = [
    "CACHE_FORMAT", "CacheReport", "FactCache", "analyzer_identity", "announce",
    "cache_dir_for", "content_digest", "file_signature", "is_disabled",
    "open_cache", "python_tag", "reset_identity_cache", "root_key",
    "user_cache_root",
]

log = logging.getLogger("mlview.cache")

#: Bumped whenever the sidecar layout changes. An older file is ignored, never
#: migrated: it is a cache, and a slow answer beats a wrong one.
CACHE_FORMAT = 2

_MAGIC = "mlview-fact-cache"
#: Signature walks stop here, matching the plugin's own historical bound.
MAX_SIGNATURE_FILES = 2000
_DEFAULT_MAX_ENTRIES = 20000

_TRUE = ("1", "true", "yes", "on")


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _TRUE


def _norm(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/")


# ------------------------------------------------------------------ digests
def content_digest(raw: bytes) -> str:
    """The content half of every key: 32 hex chars of BLAKE2b over the bytes.

    BLAKE2b rather than SHA-1: faster in CPython at these sizes, and 128 bits
    is far past collision-relevant for a cache whose miss is merely slow.
    """
    return hashlib.blake2b(raw, digest_size=16).hexdigest()


def python_tag() -> str:
    """`sys.version_info[:2]` as a string. The `ast` node set is
    version-dependent and so, therefore, is everything derived from it."""
    return "%d.%d" % (sys.version_info[0], sys.version_info[1])


def _prune_dirs():
    from ..ingest.discover import ALWAYS_PRUNE       # local: keeps core import-light
    return ALWAYS_PRUNE


def file_signature(path: str) -> str:
    """A content signature for a file or a whole tree — 16 hex chars.

    Every `.py` file under `path`, in sorted relative-path order, contributes
    its path and a digest of its **contents**. The walk prunes exactly what
    `ingest.discover` prunes, so the signature covers the files that would
    actually be analyzed and nothing else, and stops after
    `MAX_SIGNATURE_FILES` so a monorepo cannot make a cache probe cost more
    than the analysis it is trying to avoid.

    Promoted out of `claude-plugin/server/mlview_workspace.py`, which keyed on
    `st_mtime_ns` and `st_size`: a `git checkout` that restores content but not
    timestamps changed the signature without changing the answer, and a
    filesystem with coarse mtime could change the answer without changing the
    signature. The second direction is the one that serves a stale document.
    """
    digest = hashlib.blake2b(digest_size=8)
    digest.update(b"mlview-file-signature-v2\n")
    if os.path.isfile(path):
        rows = [(os.path.basename(path), path)]
    else:
        rows = []
        prune = _prune_dirs()
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in prune and not d.startswith("."))
            for name in sorted(filenames):
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, path).replace("\\", "/")
                rows.append((rel, full))
                if len(rows) >= MAX_SIGNATURE_FILES:
                    break
            if len(rows) >= MAX_SIGNATURE_FILES:
                break
        rows.sort()
    for rel, full in rows:
        try:
            with open(full, "rb") as handle:
                body = handle.read()
        except OSError:
            # An unreadable file is a fact about the tree; record it as one
            # rather than signing the same value as its absence.
            digest.update(("%s|unreadable\n" % rel).encode("utf-8"))
            continue
        digest.update(("%s|%d|" % (rel, len(body))).encode("utf-8"))
        digest.update(hashlib.blake2b(body, digest_size=16).digest())
        digest.update(b"\n")
    return digest.hexdigest()


_IDENTITY: Optional[str] = None


def reset_identity_cache() -> None:
    """Forget the memoised analyzer identity (tests, and an editable install
    that changed under a long-lived process)."""
    global _IDENTITY
    _IDENTITY = None


def analyzer_identity() -> str:
    """`<version>+<digest>` over every `.py` file of the installed analyzer.

    Version alone is not enough — an editable checkout keeps one version string
    across a thousand edits, and that is exactly how a stale document once
    reached a caller. Memoised per process; the walk costs a few milliseconds
    once. On an unreadable package the identity becomes `unknown-<pid>`, which
    no stored file can match, so the cache is off rather than trusted.
    """
    global _IDENTITY
    if _IDENTITY is not None:
        return _IDENTITY
    from ..version import __version__
    package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    digest = hashlib.blake2b(digest_size=8)
    try:
        rows = []
        for dirpath, dirnames, filenames in os.walk(package):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for name in sorted(filenames):
                if name.endswith(".py"):
                    full = os.path.join(dirpath, name)
                    rows.append((os.path.relpath(full, package).replace("\\", "/"), full))
        rows.sort()
        for rel, full in rows:
            with open(full, "rb") as handle:
                body = handle.read()
            digest.update(rel.encode("utf-8"))
            digest.update(hashlib.blake2b(body, digest_size=16).digest())
    except OSError as exc:
        log.warning("analyzer identity unavailable (%s); cache disabled", exc)
        _IDENTITY = "unknown-%d" % os.getpid()
        return _IDENTITY
    _IDENTITY = "%s+%s" % (__version__, digest.hexdigest())
    return _IDENTITY


# ------------------------------------------------------------------- policy
def is_disabled() -> bool:
    """`MLVIEW_NO_CACHE=1` — the one switch that turns the cache off."""
    return _flag("MLVIEW_NO_CACHE")


def user_cache_root() -> str:
    """The **user's** cache directory for MLView, per the platform's convention.

    `XDG_CACHE_HOME` wins on every platform when it is set, because a user who
    has set it has said where caches go. Otherwise: `%LOCALAPPDATA%\\mlview` on
    Windows, `~/Library/Caches/mlview` on macOS, `~/.cache/mlview` elsewhere.
    """
    xdg = (os.environ.get("XDG_CACHE_HOME") or "").strip()
    if xdg:
        return _norm(os.path.join(xdg, "mlview"))
    if sys.platform == "win32":                      # pragma: no cover - platform
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            return _norm(os.path.join(local, "mlview", "cache"))
    elif sys.platform == "darwin":                   # pragma: no cover - platform
        return _norm(os.path.join(os.path.expanduser("~"), "Library", "Caches",
                                  "mlview"))
    return _norm(os.path.join(os.path.expanduser("~"), ".cache", "mlview"))


def root_key(root: str) -> str:
    """The workspace half of the cache key: 16 hex chars over the absolute root.

    The sidecar's own file name carries this too (`facts-<key>.json`), so the
    per-user directory holds one file per analyzed workspace and two workspaces
    can never read each other's facts.
    """
    return hashlib.blake2b(_norm(root).encode("utf-8"), digest_size=8).hexdigest()


def cache_dir_for(root: str) -> str:
    """`MLVIEW_CACHE_DIR`, else `<user cache root>/<workspace key>`.

    **Nothing is written into the analyzed folder.** Until C8 the default was
    `<root>/.mlview/cache`, so `python -m mlview analyze .` created a directory
    inside somebody else's repository on the first run - a tool that writes into
    the tree it is reading is a tool people switch off, and the three hosts each
    had to remember to pass `MLVIEW_CACHE_DIR` to stop it. The default is now the
    user's own cache directory, keyed by the workspace's absolute path, and
    `MLVIEW_CACHE_DIR` still overrides it for a host (or a CI job collecting the
    sidecar as an artifact) that wants the file somewhere specific.
    """
    raw = (os.environ.get("MLVIEW_CACHE_DIR") or "").strip()
    if raw:
        return _norm(raw)
    return _norm(os.path.join(user_cache_root(), root_key(root)))


def _key_file() -> str:
    raw = (os.environ.get("MLVIEW_CACHE_KEY_FILE") or "").strip()
    if raw:
        return _norm(raw)
    return _norm(os.path.join(os.path.expanduser("~"), ".mlview", "cache.key"))


#: `os.O_BINARY` where the platform has it (Windows), 0 everywhere else.
#:
#: The secret is BYTES, and `os.open` on Windows opens in TEXT mode without this
#: flag: every 0x0A byte is written as 0x0D 0x0A. The run that CREATES the key
#: then MACs with the 32 bytes it holds in memory while every later run MACs with
#: the longer, CR-mangled bytes it reads back — a permanent `cache MAC mismatch`
#: that silently disables the whole cache for the ~12% of keys that contain a
#: 0x0A (1 - (255/256)**32). A named constant rather than an inline `getattr` so
#: `tests/core/test_cache.py` can stand a Windows in for a POSIX one and keep the
#: guard honest on every platform.
O_BINARY = getattr(os, "O_BINARY", 0)


def _secret() -> Optional[bytes]:
    """The 32-byte MAC secret from the user's home, created on first use.

    Deliberately **not** under the analyzed project: a repository that ships a
    `.mlview/cache` must not also be able to ship the key that authenticates
    it. `O_EXCL` makes the create race-safe between concurrent analyses.
    """
    path = _key_file()
    try:
        with open(path, "rb") as handle:
            value = handle.read()
        if len(value) >= 32:
            return value
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        value = os.urandom(32)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_BINARY
        handle_fd = os.open(path, flags, 0o600)
        try:
            os.write(handle_fd, value)
        finally:
            os.close(handle_fd)
        return value
    except FileExistsError:
        try:
            with open(path, "rb") as handle:
                value = handle.read()
            return value if len(value) >= 32 else None
        except OSError:
            return None
    except OSError as exc:
        log.info("cache disabled: no MAC secret at %s (%s)", path, exc)
        return None


# ------------------------------------------------------------------- report
@dataclass
class CacheReport:
    """What the cache did on one run. `status` is the contractual word.

    `full` — every file's facts came off disk. `partial` — some did.
    `none` — the cache was consulted and gave nothing (cold, invalidated, or a
    workspace where it has nothing to offer). `off` — never consulted.
    """

    status: str = "off"
    hits: int = 0
    misses: int = 0
    path: Optional[str] = None

    def line(self) -> str:
        return "cached: %s (%d hit / %d miss)" % (self.status, self.hits, self.misses)


# -------------------------------------------------------------------- store
class FactCache:
    """One JSON sidecar holding the per-file relevance facts of a workspace.

    Not thread-safe and not meant to be: one analysis owns one instance. Two
    concurrent analyses of the same root are safe against each other because
    the file is replaced atomically and a partial write never becomes visible.
    """

    def __init__(self, path: str, secret: bytes, identity: str,
                 max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        self.path = path
        self._secret = secret
        self._identity = identity
        self._python = python_tag()
        self._max_entries = max_entries
        self._stored: Dict[str, Dict[str, Any]] = {}
        self._next: Dict[str, Dict[str, Any]] = {}
        self._loaded = False
        self.hits = 0
        self.misses = 0

    # -- keys ------------------------------------------------------------
    def content_key(self, raw: bytes) -> str:
        """The per-file key. The python tag and the analyzer identity live in
        the file header, so neither is re-hashed per entry."""
        return content_digest(raw)

    # -- reading ---------------------------------------------------------
    def load(self) -> None:
        """Read and authenticate the sidecar. Any failure is a cold cache."""
        self._loaded = True
        try:
            with open(self.path, "rb") as handle:
                blob = handle.read()
        except OSError:
            return
        newline = blob.find(b"\n")
        if newline <= 0:
            return
        try:
            header = json.loads(blob[:newline].decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            log.info("cache header unreadable at %s; starting cold", self.path)
            return
        payload = blob[newline + 1:]
        if (header.get("magic") != _MAGIC
                or header.get("format") != CACHE_FORMAT
                or header.get("python") != self._python
                or header.get("analyzer") != self._identity):
            return
        mac = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, str(header.get("mac", ""))):
            # A sidecar that fails its MAC is corrupt or somebody else's, and
            # both answers are "derive the facts again".
            log.warning("cache MAC mismatch at %s; ignoring it", self.path)
            return
        try:
            entries = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            log.warning("cache payload unreadable at %s (%s)", self.path, exc)
            return
        if isinstance(entries, dict):
            self._stored = {k: v for k, v in entries.items() if isinstance(v, dict)}

    def get(self, relpath: str, digest: str):
        """The stored `FileFacts` for `relpath` at `digest`, or None."""
        from .relevance import facts_from_payload

        if not self._loaded:
            self.load()
        row = self._stored.get(relpath)
        if row is None or row.get("h") != digest:
            self.misses += 1
            return None
        facts = facts_from_payload(relpath, row)
        if facts is None:
            self.misses += 1
            return None
        self.hits += 1
        self._keep(relpath, row)
        return facts

    # -- writing ---------------------------------------------------------
    def _keep(self, relpath: str, row: Dict[str, Any]) -> None:
        if len(self._next) < self._max_entries:
            self._next[relpath] = row

    def put(self, relpath: str, digest: str, facts) -> None:
        """Offer freshly derived facts to the next write of the sidecar."""
        row = dict(facts.payload())
        row["h"] = digest
        self._keep(relpath, row)

    def flush(self) -> bool:
        """Write the sidecar atomically. Returns True when a file was written."""
        if not self._next or self._next == self._stored:
            return False
        payload = json.dumps(self._next, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        header = {
            "magic": _MAGIC,
            "format": CACHE_FORMAT,
            "analyzer": self._identity,
            "python": self._python,
            "entries": len(self._next),
            "mac": hmac.new(self._secret, payload, hashlib.sha256).hexdigest(),
        }
        line = json.dumps(header, sort_keys=True, ensure_ascii=False).encode("utf-8")
        tmp = "%s.tmp-%d" % (self.path, os.getpid())
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, "wb") as handle:
                handle.write(line)
                handle.write(b"\n")
                handle.write(payload)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.info("could not write the fact cache at %s (%s)", self.path, exc)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        return True

    # -- reporting -------------------------------------------------------
    def report(self) -> CacheReport:
        if self.hits == 0:
            status = "none"
        elif self.misses == 0:
            status = "full"
        else:
            status = "partial"
        return CacheReport(status=status, hits=self.hits, misses=self.misses,
                           path=self.path)


def open_cache(root: str, enabled: Optional[bool] = None) -> Optional[FactCache]:
    """The `FactCache` for `root`, or None when the cache is off or unusable.

    `enabled=None` means "ask the environment", which is what every host gets:
    on, unless `MLVIEW_NO_CACHE=1`.
    """
    if enabled is False or (enabled is None and is_disabled()):
        return None
    identity = analyzer_identity()
    if identity.startswith("unknown-"):
        return None
    secret = _secret()
    if secret is None:
        return None
    try:
        max_entries = int(os.environ.get("MLVIEW_CACHE_MAX_ENTRIES")
                          or _DEFAULT_MAX_ENTRIES)
    except ValueError:
        max_entries = _DEFAULT_MAX_ENTRIES
    stem = root_key(root)
    path = os.path.join(cache_dir_for(root), "facts-%s.json" % stem).replace("\\", "/")
    return FactCache(path, secret, identity, max_entries=max(1, max_entries))


def announce(report: CacheReport) -> None:
    """Log the one-line status. Never stdout; stderr only when asked.

    `logging` is the library-correct channel and is silent unless a host
    configures it, so a default `python -m mlview` run writes exactly the bytes
    it wrote before this feature existed. `MLVIEW_CACHE_LOG=1` is the
    operator's switch for seeing it without configuring logging.
    """
    log.info("%s", report.line())
    if _flag("MLVIEW_CACHE_LOG"):
        sys.stderr.write("mlview: %s\n" % report.line())
        try:
            sys.stderr.flush()
        except Exception:                              # pragma: no cover
            pass
