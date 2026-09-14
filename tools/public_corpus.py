#!/usr/bin/env python3
"""PUB-01 - the public-repository corpus: `fetch`, `run`, `check`.

The labelled corpus (`tools/accuracy.py`) measures MLView against 92
programs *written for it*. This one measures it against code nobody wrote for
it: thirty-seven real, popular Python ML/DL repositories, pinned to an exact
commit in `analyzer/tests/public_corpus/repos.json` - twenty-four recorded in
hardening round 1 and thirteen added in round 2 for the framework and domain
shapes round 1 never reached (gradient boosting, classical statistics and time
series, the accelerate/peft/trl fine-tuning stack, per-trial HPO objectives,
single-file RL, the official PyTorch tutorials, a registry/config framework, a
hand-written GPT, YAML-driven LLM recipes and a second notebook book).

Nothing is vendored. `fetch` clones the pinned SHAs into
``MLVIEW_PUBLIC_CORPUS_DIR`` (default ``.public-corpus/`` beside the repo,
git-ignored), `run` analyses every pinned target in every dataflow mode and
writes one report, and `check` turns that report into a gate::

    python tools/public_corpus.py fetch                  # ~1.9 GB, network
    python tools/public_corpus.py run  --out report.json
    python tools/public_corpus.py check --report report.json

`--repo`, `--corpus-dir` and `--manifest` are accepted **either side** of the
subcommand, so `... --repo nanoGPT fetch` and `... fetch --repo nanoGPT` both
work, and a value given on both sides is merged rather than overwritten
(PUB2-10). `build_parser()` is public for the same reason: doc-gate check 19
parses the command lines `.github/workflows/public-corpus.yml` generates with
it, so a workflow line this CLI would reject fails the doc gate on the machine
that wrote it rather than the nightly a week later.

`check` asserts five things, and every one of them is a credibility claim
rather than a taste:

1. **No crash.** No traceback on stderr, in any run.
2. **Exit 0 or 4 only.** 4 is "nothing analyzable found"; 1/2/3 on a
   read-only analysis of real code is a defect.
3. **Schema-valid.** Every emitted document passes
   ``contracts/validate_sample.py``, the same validator the golden sample uses.
4. **Inside the wall-time budget** (60 s per run by default).
5. **No NEW high-severity finding, and no adjudicated false positive.**
   `analyzer/tests/public_corpus/adjudication.json` records a verdict for every
   high finding the corpus has ever produced, keyed by
   ``repo|CODE|repo-relative file|symbol``. A high finding whose key is not in
   that file fails the gate - it has not been read by a human yet. A finding
   adjudicated ``false-positive`` carries a ``state``: ``open`` means the
   analyzer still produces it (listed, not fatal, unless ``--strict``),
   ``fixed`` means it must never come back - and if it does, the gate fails.
   So the same file is the review record, the campaign's open list and the
   regression ratchet at once.

Nothing here prints to stdout except the report the user asked for; the module
is importable (`load_manifest`, `run_corpus`, `check_report`, `build_parser`)
and the pytest wrapper in `analyzer/tests/public_corpus/test_public_corpus.py`
skips when the corpus directory is absent.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_TEST_DIR = os.path.join(REPO_ROOT, "analyzer", "tests", "public_corpus")
MANIFEST_PATH = os.path.join(CORPUS_TEST_DIR, "repos.json")
ADJUDICATION_PATH = os.path.join(CORPUS_TEST_DIR, "adjudication.json")
DEFAULT_CORPUS_DIR = os.path.join(REPO_ROOT, ".public-corpus")

#: A traceback in stderr is the one thing that can never be a judgement call.
TRACEBACK_RE = re.compile(r"^Traceback \(most recent call last\)", re.M)
#: Lines the analyzer is entitled to write to stderr during a normal run.
BENIGN_STDERR_RE = re.compile(
    r"^(mlview: wrote |mlview: |\s*$)"
)


# --------------------------------------------------------------- manifest
class CorpusError(Exception):
    pass


def corpus_dir() -> str:
    return os.environ.get("MLVIEW_PUBLIC_CORPUS_DIR") or DEFAULT_CORPUS_DIR


def load_manifest(path: str = MANIFEST_PATH) -> Dict[str, Any]:
    if not os.path.isfile(path):
        raise CorpusError("no manifest at %s" % path)
    with open(path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    seen = set()
    for repo in manifest.get("repos", []):
        for key in ("name", "url", "sha", "license", "targets"):
            if not repo.get(key):
                raise CorpusError("repo %r is missing %r" % (repo.get("name"), key))
        if repo["name"] in seen:
            raise CorpusError("duplicate repo name %r" % repo["name"])
        seen.add(repo["name"])
        if not re.fullmatch(r"[0-9a-f]{40}", repo["sha"]):
            raise CorpusError("repo %r: sha must be a full 40-hex commit"
                              % repo["name"])
    if not manifest.get("repos"):
        raise CorpusError("%s lists no repos" % path)
    return manifest


def load_adjudication(path: str = ADJUDICATION_PATH) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {"schemaVersion": 1, "verdicts": {}}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    for key, row in (data.get("verdicts") or {}).items():
        verdict = row.get("verdict")
        if verdict not in ("true-positive", "false-positive", "unsure"):
            raise CorpusError("adjudication %r: bad verdict %r" % (key, verdict))
        if not row.get("why"):
            raise CorpusError("adjudication %r: every verdict must cite why" % key)
    return data


def finding_key(repo: str, code: str, repo_rel_file: str, symbol: str) -> str:
    """Stable across edits above the finding and across which target found it."""
    return "%s|%s|%s|%s" % (repo, code, repo_rel_file.replace("\\", "/"),
                            symbol or "")


# ------------------------------------------------------------------ fetch
def _git(args: Sequence[str], cwd: Optional[str] = None) -> str:
    proc = subprocess.run(["git"] + list(args), cwd=cwd, check=False,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise CorpusError("git %s failed (%d):\n%s"
                          % (" ".join(args), proc.returncode, proc.stdout))
    return proc.stdout


def fetch_one(repo: Dict[str, Any], dest_root: str, log=lambda s: None) -> str:
    """Clone one pinned repo. Returns the destination directory."""
    dest = os.path.join(dest_root, repo["name"])
    marker = os.path.join(dest, ".mlview-pinned-sha")
    if os.path.isfile(marker):
        with open(marker, "r", encoding="utf-8") as handle:
            if handle.read().strip() == repo["sha"]:
                log("have %s @ %s" % (repo["name"], repo["sha"][:12]))
                return dest
    if os.path.isdir(dest):
        raise CorpusError(
            "%s exists but is not pinned at %s - remove it and re-fetch"
            % (dest, repo["sha"][:12]))
    os.makedirs(dest, exist_ok=True)
    log("fetch %s @ %s" % (repo["name"], repo["sha"][:12]))
    _git(["init", "-q"], cwd=dest)
    _git(["remote", "add", "origin", repo["url"]], cwd=dest)
    sparse = repo.get("sparse") or []
    if sparse:
        _git(["config", "core.sparseCheckout", "true"], cwd=dest)
        info = os.path.join(dest, ".git", "info")
        os.makedirs(info, exist_ok=True)
        with open(os.path.join(info, "sparse-checkout"), "w",
                  encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(sparse) + "\n")
    _git(["fetch", "--depth", "1", "--filter=blob:none", "origin", repo["sha"]],
         cwd=dest)
    _git(["checkout", "-q", "FETCH_HEAD"], cwd=dest)
    head = _git(["rev-parse", "HEAD"], cwd=dest).strip()
    if head != repo["sha"]:
        raise CorpusError("%s: checked out %s, manifest pins %s"
                          % (repo["name"], head, repo["sha"]))
    with open(marker, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(repo["sha"] + "\n")
    return dest


def fetch(manifest: Dict[str, Any], dest_root: str, only: Sequence[str] = (),
          log=lambda s: None) -> List[str]:
    os.makedirs(dest_root, exist_ok=True)
    out: List[str] = []
    for repo in manifest["repos"]:
        if only and repo["name"] not in only:
            continue
        out.append(fetch_one(repo, dest_root, log=log))
    return out


# -------------------------------------------------------------- validation
def _load_validator():
    path = os.path.join(REPO_ROOT, "contracts", "validate_sample.py")
    spec = importlib.util.spec_from_file_location("_mlview_validate_sample", path)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging guard
        raise CorpusError("cannot load %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------- run
def _cli_argv(python: str, target: str, json_out: str, mode: str,
              notebooks: bool) -> List[str]:
    argv = [python, "-X", "utf8", "-m", "mlview", "analyze", target,
            "--json", json_out, "--format", "summary", "--no-cache",
            "--no-color"]
    if mode == "ip":
        argv += ["--dataflow", "ip"]
    if notebooks:
        argv += ["--include-notebooks"]
    return argv


def _has_notebooks(path: str, limit: int = 20000) -> bool:
    seen = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".mlview")]
        for name in files:
            if name.endswith(".ipynb"):
                return True
            seen += 1
            if seen > limit:
                return False
    return False


def _summarize_doc(doc: Dict[str, Any], repo_rel_prefix: str) -> Dict[str, Any]:
    diag: Dict[str, int] = {}
    for entry in doc.get("diagnostics", []):
        diag[entry.get("kind", "?")] = diag.get(entry.get("kind", "?"), 0) + 1
    findings = []
    for issue in doc.get("issues", []):
        loc = issue.get("loc") or {}
        rel = loc.get("file", "")
        repo_rel = "/".join(p for p in (repo_rel_prefix, rel) if p and p != ".")
        findings.append({
            "code": issue.get("code"),
            "severity": issue.get("severity"),
            "confidence": round(float(issue.get("confidence", 0.0)), 3),
            "bucket": issue.get("confidenceBucket"),
            "title": issue.get("title"),
            "file": rel,
            "repoFile": repo_rel,
            "line": loc.get("line"),
            "symbol": loc.get("symbol", ""),
            "snippet": (loc.get("snippet") or "")[:160],
        })
    workspace = doc.get("workspace") or {}
    stats = doc.get("stats") or {}
    return {
        "nodes": stats.get("nodes"),
        "edges": stats.get("edges"),
        "issues": stats.get("issues"),
        "suppressed": stats.get("suppressed"),
        "truncated": bool(stats.get("truncated")),
        "durationMs": stats.get("durationMs"),
        "filesAnalyzed": workspace.get("filesAnalyzed"),
        "filesFailed": workspace.get("filesFailed"),
        "notebooksSkipped": workspace.get("notebooksSkipped"),
        "frameworks": workspace.get("frameworks") or [],
        "entrypoints": (workspace.get("entrypoints") or [])[:8],
        "stagesPresent": [s.get("id") for s in doc.get("stages", [])
                          if s.get("present")],
        "diagnostics": diag,
        "findings": findings,
    }


def run_one(repo: Dict[str, Any], target: str, mode: str, dest_root: str,
            python: str, out_dir: str, budget: float,
            validator) -> Dict[str, Any]:
    repo_dir = os.path.join(dest_root, repo["name"])
    abs_target = os.path.normpath(os.path.join(repo_dir, target))
    notebooks = mode == "notebooks"
    slug = "%s__%s__%s" % (repo["name"],
                           target.replace("/", "_").replace(".", "root"), mode)
    json_out = os.path.join(out_dir, slug + ".json")
    argv = _cli_argv(python, abs_target, json_out,
                     "ip" if mode == "ip" else "local", notebooks)
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    row: Dict[str, Any] = {
        "repo": repo["name"], "sha": repo["sha"], "target": target,
        "mode": mode, "argv": argv[1:], "graphPath": json_out,
    }
    if not os.path.isdir(abs_target):
        row["error"] = "target directory missing: %s" % abs_target
        row["exit"] = None
        return row
    started = time.time()
    try:
        proc = subprocess.run(argv, cwd=repo_dir, env=env, shell=False,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=max(budget * 4, 120))
        row["exit"] = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        row["exit"] = None
        row["error"] = "timed out after %.0fs" % (time.time() - started)
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
    row["wallMs"] = int((time.time() - started) * 1000)
    row["traceback"] = bool(TRACEBACK_RE.search(stderr or ""))
    noisy = [line for line in (stderr or "").splitlines()
             if line.strip() and not BENIGN_STDERR_RE.match(line)]
    row["stderrNoise"] = noisy[:40]
    row["stderrNoiseCount"] = len(noisy)
    row["stdoutBytes"] = len(stdout or "")
    if os.path.isfile(json_out):
        try:
            with open(json_out, "r", encoding="utf-8") as handle:
                doc = json.load(handle)
        except ValueError as exc:
            row["schemaErrors"] = ["document is not valid JSON: %s" % exc]
        else:
            row["schemaErrors"] = validator.validate_graph(doc)[:20]
            prefix = "" if target in (".", "") else target
            row.update(_summarize_doc(doc, prefix))
    elif row.get("exit") == 4:
        row["schemaErrors"] = []
    else:
        row["schemaErrors"] = ["no graph document was written"]
    return row


def plan(manifest: Dict[str, Any], dest_root: str, only: Sequence[str] = (),
         modes: Sequence[str] = ("local", "ip"),
         with_notebooks: bool = True) -> List[Tuple[Dict[str, Any], str, str]]:
    jobs: List[Tuple[Dict[str, Any], str, str]] = []
    for repo in manifest["repos"]:
        if only and repo["name"] not in only:
            continue
        for target in repo["targets"]:
            abs_target = os.path.normpath(
                os.path.join(dest_root, repo["name"], target))
            for mode in modes:
                jobs.append((repo, target, mode))
            if with_notebooks and os.path.isdir(abs_target) \
                    and _has_notebooks(abs_target):
                jobs.append((repo, target, "notebooks"))
    return jobs


def run_corpus(manifest: Dict[str, Any], dest_root: str, out_dir: str,
               only: Sequence[str] = (), modes: Sequence[str] = ("local", "ip"),
               with_notebooks: bool = True, jobs: int = 4,
               python: Optional[str] = None, budget: float = 60.0,
               log=lambda s: None) -> Dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    validator = _load_validator()
    python = python or sys.executable
    work = plan(manifest, dest_root, only, modes, with_notebooks)
    log("%d run(s) planned over %d repo(s)"
        % (len(work), len({r["name"] for r, _, _ in work})))
    rows: List[Dict[str, Any]] = []
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {
            pool.submit(run_one, repo, target, mode, dest_root, python,
                        out_dir, budget, validator): (repo["name"], target, mode)
            for repo, target, mode in work
        }
        for done in concurrent.futures.as_completed(futures):
            name, target, mode = futures[done]
            try:
                rows.append(done.result())
            except Exception as exc:  # pragma: no cover - harness bug, not core
                rows.append({"repo": name, "target": target, "mode": mode,
                             "exit": None, "error": "harness: %r" % exc})
            log("  %-28s %-34s %-9s done (%d/%d)"
                % (name, target, mode, len(rows), len(work)))
    rows.sort(key=lambda r: (r.get("repo", ""), r.get("target", ""),
                             r.get("mode", "")))
    return {
        "schemaVersion": 1,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": {"platform": platform.platform(),
                 "python": platform.python_version()},
        "corpusDir": dest_root,
        "manifestRecorded": manifest.get("recorded"),
        "wallSeconds": round(time.time() - started, 1),
        "budgetSeconds": budget,
        "runs": rows,
    }


# ----------------------------------------------------------------- check
def _by_target(report: Dict[str, Any]) -> Dict[Any, Dict[str, Any]]:
    out: Dict[Any, Dict[str, Any]] = {}
    for row in report.get("runs", []):
        out.setdefault((row.get("repo"), row.get("target")), {})[row.get("mode")] = row
    return out


class CheckResult:
    """What `check` found, split so a known-open bug is not a nightly failure.

    `blocking` is the gate: a crash, a bad exit code, a schema violation, a run
    over budget, a high finding nobody has adjudicated, or a false positive
    marked `fixed` coming back. `known` is the campaign's open list: false
    positives the analyzer still produces, each already read and written down.
    `stale` names an adjudicated false positive that is no longer produced -
    a good day, and a prompt to flip its `state` to "fixed" so its return
    becomes blocking.
    """

    def __init__(self) -> None:
        self.blocking: List[str] = []
        self.known: List[str] = []
        self.stale: List[str] = []

    @property
    def ok(self) -> bool:
        return not self.blocking

    def lines(self) -> List[str]:
        return list(self.blocking) + list(self.known) + list(self.stale)


def check_report(report: Dict[str, Any], adjudication: Dict[str, Any],
                 budget: Optional[float] = None,
                 strict: bool = False) -> CheckResult:
    """Gate one report against the adjudication record.

    With `strict`, a known-open false positive and a stale entry are blocking
    too - that is the mode to run once the open list is meant to be empty.
    """
    result = CheckResult()
    verdicts = adjudication.get("verdicts") or {}
    budget = budget if budget is not None else report.get("budgetSeconds", 60.0)
    allowed_exits = {0, 4}

    present_high: Dict[str, Dict[str, Any]] = {}
    for row in report.get("runs", []):
        where = "%s %s [%s]" % (row.get("repo"), row.get("target"),
                                row.get("mode"))
        if row.get("error"):
            result.blocking.append("%s: %s" % (where, row["error"]))
            continue
        if row.get("traceback"):
            result.blocking.append(
                "%s: traceback on stderr: %s"
                % (where, "; ".join(row.get("stderrNoise", [])[:3])))
        if row.get("exit") not in allowed_exits:
            result.blocking.append("%s: exit %r (only 0 and 4 are allowed)"
                                   % (where, row.get("exit")))
        for err in row.get("schemaErrors") or []:
            result.blocking.append("%s: schema/invariant: %s" % (where, err))
        wall = (row.get("wallMs") or 0) / 1000.0
        if wall > budget:
            result.blocking.append("%s: %.1fs wall exceeds the %.0fs budget"
                                   % (where, wall, budget))
        for finding in row.get("findings") or []:
            if finding.get("severity") != "high":
                continue
            key = finding_key(row.get("repo", ""), finding.get("code", ""),
                              finding.get("repoFile", ""),
                              finding.get("symbol", ""))
            present_high.setdefault(key, {"where": where, "finding": finding})

    for key, seen in sorted(present_high.items()):
        finding, where = seen["finding"], seen["where"]
        site = "%s at %s:%s" % (finding.get("code"), finding.get("file"),
                                finding.get("line"))
        verdict = verdicts.get(key)
        if verdict is None:
            result.blocking.append(
                "NEW high finding, not in adjudication.json: %s (%s) - read the "
                "code and add a verdict under key %s" % (site, where, key))
            continue
        if verdict.get("verdict") != "false-positive":
            continue
        if verdict.get("state") == "fixed":
            result.blocking.append(
                "REGRESSION - a false positive marked fixed is back: %s (%s) - %s"
                % (site, where, verdict.get("why", "")[:160]))
        else:
            line = "known-open false positive still present: %s [%s] (%s)" % (
                site, verdict.get("finding") or "unfiled", where)
            (result.blocking if strict else result.known).append(line)

    # 11.36 frames `ip` as a widening of `local`: it carries a tag further and
    # de-rates it, so every finding `local` produced must survive into `ip`,
    # possibly weaker. A finding that is simply GONE in `ip` is the one shape
    # the two independent accuracy baselines cannot see, because each ratchets
    # against itself. Reported, never silent.
    for (repo, target), modes in sorted(_by_target(report).items()):
        local, ip = modes.get("local"), modes.get("ip")
        if not local or not ip:
            continue
        def _ids(row):
            return {(f.get("code"), f.get("repoFile"), f.get("line"),
                     f.get("symbol")) for f in row.get("findings") or []}
        for code, path, line, symbol in sorted(_ids(local) - _ids(ip),
                                               key=lambda t: tuple(map(str, t))):
            line_text = ("--dataflow ip DROPPED a finding `local` reports: "
                         "%s at %s:%s (%s %s) - ip is documented as a widening"
                         % (code, path, line, repo, target))
            (result.blocking if strict else result.known).append(line_text)

    # Only repos this report actually covered can say anything about absence:
    # a subset run (`--repo nanoGPT`) is silent about the rest, not evidence
    # that their false positives are gone.
    covered = {row.get("repo") for row in report.get("runs", [])}
    for key, verdict in sorted(verdicts.items()):
        if verdict.get("verdict") != "false-positive":
            continue
        if verdict.get("state") == "fixed" or key in present_high:
            continue
        if key.split("|", 1)[0] not in covered:
            continue
        line = ('adjudicated false positive is GONE: %s - set its "state" to '
                '"fixed" so a return becomes blocking' % key)
        (result.blocking if strict else result.stale).append(line)

    return result


def summarize(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    runs = report.get("runs", [])
    ok = sum(1 for r in runs if r.get("exit") in (0, 4) and not r.get("traceback")
             and not (r.get("schemaErrors") or []))
    lines.append("%d run(s), %d clean, %.0fs wall, budget %.0fs"
                 % (len(runs), ok, report.get("wallSeconds", 0.0),
                    report.get("budgetSeconds", 60.0)))
    sev = {"high": 0, "medium": 0, "low": 0}
    slow = []
    for row in runs:
        counts = row.get("issues") or {}
        for key in sev:
            sev[key] += int(counts.get(key) or 0)
        if (row.get("wallMs") or 0) > 20000:
            slow.append((row.get("wallMs"), row.get("repo"), row.get("target"),
                         row.get("mode")))
    lines.append("findings across every run: %d high / %d medium / %d low"
                 % (sev["high"], sev["medium"], sev["low"]))
    for ms, repo, target, mode in sorted(slow, reverse=True)[:8]:
        lines.append("  slow: %6.1fs  %s %s [%s]" % (ms / 1000.0, repo, target, mode))
    return lines


# ------------------------------------------------------------------- CLI
#: The selector options, registered on the top-level parser and on every
#: subparser. `_selectors` merges the two namespaces afterwards.
SELECTORS = ("repo", "corpus_dir", "manifest")


def _common(parser: argparse.ArgumentParser,
            top: bool = False) -> argparse.ArgumentParser:
    """The three selector options, added to the top level *and* to every
    subparser.

    PUB2-10: argparse only accepts a top-level option **before** the
    subcommand, so `public_corpus.py fetch --repo nanoGPT` exited 2 with
    `unrecognized arguments` - and that is exactly the line
    `.github/workflows/public-corpus.yml` generated for its `workflow_dispatch`
    `repos` input, so the documented way to run the job on a subset could only
    ever fail at the fetch step. Registering the options on both parsers makes
    either order work, which is what every reader expects of a `git`-shaped CLI.

    The subparser copies write to a **dest of their own** and default to
    `SUPPRESS`: a subparser parses into its own namespace whose attributes are
    then copied over the main one, so sharing a dest means the second spelling
    silently erases the first - `--repo a fetch --repo b` would have analyzed
    `b` alone, and an `append` action there starts from an empty list rather
    than from what the top level collected. `_selectors` merges the two, so a
    value given on either side (or on both) is a value that counts.
    """
    suffix = "" if top else "_after"
    parser.add_argument("--corpus-dir", dest="corpus_dir" + suffix, metavar="DIR",
                        default=None if top else argparse.SUPPRESS,
                        help="where the clones live (default: "
                             "$MLVIEW_PUBLIC_CORPUS_DIR or .public-corpus)")
    parser.add_argument("--manifest", dest="manifest" + suffix, metavar="PATH",
                        default=None if top else argparse.SUPPRESS,
                        help="repos.json to read (default: the one in the tree)")
    parser.add_argument("--repo", dest="repo" + suffix, action="append",
                        metavar="NAME",
                        default=[] if top else argparse.SUPPRESS,
                        help="restrict to this repo name; repeatable, one "
                             "value may be a comma-separated list, and it may "
                             "be given before or after the subcommand")
    return parser


def _selectors(args: argparse.Namespace) -> Tuple[List[str], str, str]:
    """`(repo names, corpus dir, manifest path)` from both sides of the subcommand.

    Names are split on commas (the `workflow_dispatch` input is one string),
    stripped and de-duplicated with their order kept, so `--repo a,b --repo a`
    is `[a, b]`.
    """
    values: List[str] = (list(getattr(args, "repo", None) or [])
                         + list(getattr(args, "repo_after", None) or []))
    names: List[str] = []
    for value in values:
        for name in value.split(","):
            name = name.strip()
            if name and name not in names:
                names.append(name)
    dest = (getattr(args, "corpus_dir_after", None)
            or getattr(args, "corpus_dir", None) or corpus_dir())
    manifest = (getattr(args, "manifest_after", None)
                or getattr(args, "manifest", None) or MANIFEST_PATH)
    return names, dest, manifest


def build_parser() -> argparse.ArgumentParser:
    """The whole command line, as a parser.

    Public because a parser is the only honest answer to *"is this command line
    runnable?"*, and `.github/workflows/public-corpus.yml` is generated text
    that nobody runs until the nightly does: doc-gate check 19
    (`scripts/doc_numbers.py`) parses the command lines that workflow builds
    with this parser, so a line argparse would reject fails the build instead of
    the job (PUB2-10).
    """
    parser = _common(argparse.ArgumentParser(
        prog="public_corpus",
        description="fetch, analyze and gate the public-repository corpus"),
        top=True)
    sub = parser.add_subparsers(dest="cmd", required=True)

    _common(sub.add_parser("fetch", help="clone the pinned SHAs"))

    run_p = _common(sub.add_parser("run", help="analyze every pinned target"))
    run_p.add_argument("--out", default=None, help="report JSON path")
    run_p.add_argument("--graphs", default=None,
                       help="directory for the per-run graph documents")
    run_p.add_argument("--jobs", type=int, default=4)
    run_p.add_argument("--modes", default="local,ip")
    run_p.add_argument("--no-notebooks", action="store_true")
    run_p.add_argument("--budget", type=float, default=60.0)
    run_p.add_argument("--python", default=None)

    check_p = _common(sub.add_parser("check", help="gate a report"))
    check_p.add_argument("--report", required=True)
    check_p.add_argument("--budget", type=float, default=None)
    check_p.add_argument("--strict", action="store_true",
                         help="also fail on a known-open false positive and on "
                              "an adjudicated false positive that has gone away")
    return parser


def _main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    args.repo, dest, manifest_path = _selectors(args)
    manifest = load_manifest(manifest_path)

    def log(text: str) -> None:
        sys.stderr.write(text + "\n")
        sys.stderr.flush()

    if args.cmd == "fetch":
        fetch(manifest, dest, args.repo, log=log)
        log("corpus ready under %s" % dest)
        return 0

    if args.cmd == "run":
        out = args.out or os.path.join(dest, "_reports", "report.json")
        graphs = args.graphs or os.path.join(dest, "_reports", "graphs")
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        report = run_corpus(manifest, dest, graphs, args.repo,
                            tuple(m for m in args.modes.split(",") if m),
                            not args.no_notebooks, args.jobs, args.python,
                            args.budget, log=log)
        with open(out, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=1, sort_keys=True)
            handle.write("\n")
        for line in summarize(report):
            log(line)
        log("report written to %s" % out)
        return 0

    # A missing or malformed report is a mistake at the command line, not a
    # defect in the analyzer: say so in one line rather than spilling a
    # traceback that reads like MLView crashed.
    if not os.path.isfile(args.report):
        log("no report at %s - run `public_corpus.py run --out %s` first"
            % (args.report, args.report))
        return 2
    try:
        with open(args.report, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except ValueError as exc:
        log("%s is not a valid report: %s" % (args.report, exc))
        return 2
    result = check_report(report, load_adjudication(), args.budget, args.strict)
    for line in summarize(report):
        log(line)
    if result.known:
        log("")
        log("%d known-open false positive(s) still present "
            "(adjudicated, not yet fixed):" % len(result.known))
        for line in result.known:
            log("  ~ " + line)
    if result.stale:
        log("")
        for line in result.stale:
            log("  + " + line)
    if result.blocking:
        log("")
        log("PUBLIC CORPUS GATE FAILED - %d blocking problem(s):"
            % len(result.blocking))
        for line in result.blocking:
            log("  - " + line)
        return 1
    log("public corpus gate: OK")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
