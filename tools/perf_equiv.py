#!/usr/bin/env python
"""PERF-01/02 equivalence gate: an optimisation must not change one byte.

    python tools/perf_equiv.py --baseline <dir>          # <dir> holds the
                                                         # pre-optimisation
                                                         # `mlview` package
    python tools/perf_equiv.py --baseline <dir> --diff   # + name what moved
    python tools/perf_equiv.py --baseline <dir> --bench  # + 4/50/200-file timings
    python tools/perf_equiv.py --record out.json         # hash the current tree
    python tools/perf_equiv.py --compare out.json        # compare against it

Three corpora are analyzed - `samples/vision_pipeline`,
`samples/vision_pipeline_clean` and `analyzer/tests/clean` - the whole of
`generator` bar `name`/`version`, plus `stats.durationMs`, is stripped, and the
canonical JSON of what is left is SHA-256'd. Two trees are equivalent when all
three digests match. That is ROADMAP's own wording for this harness ("sha256 of
the document minus `generator` / `stats`"): `generatedAt` and `durationMs` are
the two fields CONTRACTS section 2 lets vary between two runs, and
`generator.rendererSha` is a hash of `webview/dist` - a VIEWER build product
that says nothing about analyzer behaviour. Leaving it in would make every
sprint that rebuilds the bundle (BUILD-01 did) report three false byte changes
on an analyzer-only optimisation.

PERF-02 is the one change in Sprint 3 that legitimately moves a byte: replacing
`build_ir`'s literal `range(4)` with a convergence loop resolves a fifth round
that `analyzer/tests/clean` needs, so one node there gains one `ValueTag`. Run
with `--diff` to see exactly that and nothing else; the memoisation and the
indexes are byte-identical on all three corpora on their own.

Each tree is measured in its **own subprocess** with its own `sys.path`, because
`mlview` caches module-level tables and the two copies must never share them.
Exit 0 when every corpus matches, 1 otherwise.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CURRENT_SRC = os.path.join(REPO_ROOT, "analyzer", "src")

#: (label, path relative to the repo root)
CORPORA: Tuple[Tuple[str, str], ...] = (
    ("vision_pipeline", "samples/vision_pipeline"),
    ("vision_pipeline_clean", "samples/vision_pipeline_clean"),
    ("tests_clean", "analyzer/tests/clean"),
)

#: Fields that may move without the analyzer having changed its mind. The first
#: two are what CONTRACTS section 2 lets vary between two runs of one analyzer;
#: `rendererSha` is the sha256 of the shipped `webview/dist` bundle, so it moves
#: whenever the VIEWER is rebuilt and never because analysis changed.
VOLATILE = (
    ("generator", "generatedAt"),
    ("generator", "rendererSha"),
    ("stats", "durationMs"),
)

# The child program: analyze every corpus, strip, hash, time. Written to a
# temp file rather than passed with `-c` so a traceback carries line numbers.
_WORKER = r'''
import hashlib, json, os, sys, time

def strip(doc):
    for section, key in %(volatile)r:
        if isinstance(doc.get(section), dict):
            doc[section].pop(key, None)
    return doc

def digest(doc):
    text = json.dumps(strip(doc), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

from mlview.api import AnalyzeOptions, analyze_to_dict

dump_dir = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
if dump_dir:
    os.makedirs(dump_dir, exist_ok=True)

out = {"rows": [], "src": os.path.abspath(sys.argv[1])}
for label, path, max_nodes, repeats in json.loads(sys.argv[2]):
    best = None
    doc = None
    for _ in range(repeats):
        started = time.perf_counter()
        doc = analyze_to_dict(AnalyzeOptions(paths=(path,), max_files=4000,
                                             max_nodes=max_nodes))
        elapsed = (time.perf_counter() - started) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
    if dump_dir:
        with open(os.path.join(dump_dir, label + ".json"), "w",
                  encoding="utf-8", newline=chr(10)) as fh:
            json.dump(strip(doc), fh, indent=1, ensure_ascii=False, sort_keys=True)
    out["rows"].append({"label": label, "sha256": digest(doc),
                        "ms": round(best, 1),
                        "files": doc["workspace"]["filesAnalyzed"],
                        "nodes": doc["stats"]["nodes"],
                        "issues": len(doc["issues"])})
sys.stdout.write(json.dumps(out))
''' % {"volatile": VOLATILE}


# --------------------------------------------------------------------- run
def _run_worker(src_dir: str, jobs: Sequence[Sequence[object]],
                dump_dir: Optional[str] = None) -> List[Dict[str, object]]:
    """Analyze `jobs` in a child interpreter whose `sys.path` starts at `src_dir`."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.abspath(src_dir)
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    handle, worker_path = tempfile.mkstemp(suffix="_perf_equiv_worker.py")
    os.close(handle)
    try:
        with open(worker_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_WORKER)
        proc = subprocess.run(
            [sys.executable, worker_path, os.path.abspath(src_dir),
             json.dumps(list(jobs)), dump_dir or ""],
            capture_output=True, text=True, env=env, cwd=REPO_ROOT)
    finally:
        try:
            os.remove(worker_path)
        except OSError:  # pragma: no cover - best effort
            pass
    if proc.returncode != 0:
        raise SystemExit("perf_equiv: worker for %s failed:\n%s" % (src_dir, proc.stderr))
    return json.loads(proc.stdout)["rows"]


def _corpus_jobs(repeats: int) -> List[List[object]]:
    return [[label, os.path.join(REPO_ROOT, path).replace("\\", "/"), 4000, repeats]
            for label, path in CORPORA]


# --------------------------------------------------------------- synthetic
_SYNTH_MODULE = '''"""Synthetic module %(n)d - PERF benchmark corpus."""
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

%(sibling_import)s


class Net%(n)d(nn.Module):
    def __init__(self, width=%(width)d):
        super().__init__()
        self.body = nn.Sequential(nn.Linear(%(width)d, width), nn.ReLU(),
                                  nn.BatchNorm1d(width), nn.Dropout(0.1))
        self.head = nn.Linear(width, 10)

    def forward(self, x):
        return self.head(self.body(x))


def load_%(n)d(path="data_%(n)d.npy"):
    raw = np.load(path)
    features = raw[:, :-1]
    target = raw[:, -1]
    return features, target


def prepare_%(n)d():
    features, target = load_%(n)d()
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)
    X_train, X_test, y_train, y_test = train_test_split(scaled, target, test_size=0.2)
    return X_train, X_test, y_train, y_test


def train_%(n)d(epochs=2):
    X_train, X_test, y_train, y_test = prepare_%(n)d()
    model = Net%(n)d()
    loader = DataLoader(TensorDataset(torch.tensor(X_train), torch.tensor(y_train)),
                        batch_size=32, shuffle=True)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=1)
    for _epoch in range(epochs):
        for xb, yb in loader:
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()
        scheduler.step()
    torch.save(model.state_dict(), "net_%(n)d.pt")
    return model


def evaluate_%(n)d(model, X_test, y_test):
    model.eval()
    with torch.no_grad():
        logits = model(torch.tensor(X_test))
        probs = F.softmax(logits, dim=1)
        preds = probs.argmax(dim=1).detach().cpu().numpy()
    return {"acc": accuracy_score(y_test, preds), "f1": f1_score(y_test, preds,
                                                                average="macro")}


def baseline_%(n)d():
    features, target = load_%(n)d()
    pca = PCA(n_components=4)
    reduced = pca.fit_transform(features)
    forest = RandomForestClassifier(n_estimators=20)
    scores = cross_val_score(forest, reduced, target, cv=3)
    forest.fit(reduced, target)
    return scores.mean(), forest


def pipeline_%(n)d():
    model = train_%(n)d()
    X_train, X_test, y_train, y_test = prepare_%(n)d()
    metrics = evaluate_%(n)d(model, X_test, y_test)
    %(sibling_call)s
    return metrics
'''


def synth_corpus(root: str, count: int) -> str:
    """Write `count` framework-touching modules under `root/pkg` and return root."""
    pkg = os.path.join(root, "pkg")
    os.makedirs(pkg, exist_ok=True)
    with open(os.path.join(pkg, "__init__.py"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write('"""Synthetic PERF benchmark package."""\n')
    modules = max(count - 1, 1)
    for n in range(modules):
        # every module but the first imports its predecessor, so cross-module
        # resolution (the IR fixed point) has real work to do
        sibling = "from .mod_%03d import baseline_%d" % (n - 1, n - 1) if n else ""
        call = "    baseline_%d()" % (n - 1) if n else ""
        target = os.path.join(pkg, "mod_%03d.py" % n)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_SYNTH_MODULE % {"n": n, "width": 16 + (n % 8) * 8,
                                      "sibling_import": sibling,
                                      "sibling_call": call.strip() or "pass"})
    return root


# ------------------------------------------------------------------ output
def _table(title: str, rows: Sequence[Dict[str, object]]) -> str:
    lines = ["  %s" % title,
             "    %-24s %8s %7s %7s  %s" % ("CORPUS", "MS", "FILES", "NODES", "SHA-256")]
    for row in rows:
        lines.append("    %-24s %8.1f %7d %7d  %s"
                     % (row["label"], row["ms"], row["files"], row["nodes"],
                        str(row["sha256"])[:16]))
    return "\n".join(lines)


def _compare(before: Sequence[Dict[str, object]],
             after: Sequence[Dict[str, object]]) -> Tuple[bool, List[str]]:
    by_label = {row["label"]: row for row in before}
    ok = True
    lines: List[str] = []
    lines.append("  %-24s %10s %10s %8s  %s"
                 % ("CORPUS", "BEFORE ms", "AFTER ms", "CHANGE", "BYTES"))
    for row in after:
        base = by_label.get(row["label"])
        if base is None:
            ok = False
            lines.append("  %-24s %10s %10.1f %8s  MISSING FROM BASELINE"
                         % (row["label"], "-", row["ms"], "-"))
            continue
        same = base["sha256"] == row["sha256"]
        ok = ok and same
        speed = (float(base["ms"]) / float(row["ms"])) if row["ms"] else 0.0
        lines.append("  %-24s %10.1f %10.1f %7.2fx  %s"
                     % (row["label"], base["ms"], row["ms"], speed,
                        "identical" if same else "*** DIFFERENT ***"))
    return ok, lines


def _diff_lines(before_dir: str, after_dir: str, labels: Sequence[str],
                limit: int = 40) -> List[str]:
    """A unified diff of the two stripped documents, per differing corpus."""
    out: List[str] = ["", "What moved"]
    for label in labels:
        before_path = os.path.join(before_dir, label + ".json")
        after_path = os.path.join(after_dir, label + ".json")
        if not (os.path.isfile(before_path) and os.path.isfile(after_path)):
            out.append("  %s: no dump written" % label)
            continue
        with open(before_path, encoding="utf-8") as fh:
            old = fh.read().splitlines(keepends=True)
        with open(after_path, encoding="utf-8") as fh:
            new_lines = fh.read().splitlines(keepends=True)
        rows = list(difflib.unified_diff(old, new_lines, "before/" + label,
                                         "after/" + label, n=1))
        if not rows:
            continue
        out.append("  %s: %d diff line(s)" % (label, len(rows)))
        for row in rows[:limit]:
            out.append("    " + row.rstrip())
        if len(rows) > limit:
            out.append("    ... %d more" % (len(rows) - limit))
    return out


def _bench(baseline_src: str, sizes: Sequence[int], repeats: int) -> List[str]:
    lines: List[str] = ["", "Timings on synthetic corpora (best of %d)" % repeats,
                        "  %-10s %12s %12s %9s" % ("FILES", "BEFORE ms", "AFTER ms", "SPEEDUP")]
    with tempfile.TemporaryDirectory(prefix="mlview_perf_") as tmp:
        jobs: List[List[object]] = []
        for size in sizes:
            root = synth_corpus(os.path.join(tmp, "n%d" % size), size)
            jobs.append(["%d files" % size, root.replace("\\", "/"), 100000, repeats])
        before = _run_worker(baseline_src, jobs)
        after = _run_worker(CURRENT_SRC, jobs)
        for old, new in zip(before, after):
            speed = (float(old["ms"]) / float(new["ms"])) if new["ms"] else 0.0
            lines.append("  %-10s %12.1f %12.1f %8.2fx"
                         % (old["label"], old["ms"], new["ms"], speed))
            if old["sha256"] != new["sha256"]:
                lines.append("      *** output differs on the synthetic corpus ***")
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="perf_equiv",
        description="Prove an analyzer optimisation is byte-identical.")
    parser.add_argument("--baseline", metavar="DIR",
                        help="a directory holding the pre-optimisation `mlview` "
                             "package (e.g. a copy of analyzer/src)")
    parser.add_argument("--record", metavar="FILE",
                        help="write the current tree's digests to FILE")
    parser.add_argument("--compare", metavar="FILE",
                        help="compare the current tree against a recorded FILE")
    parser.add_argument("--diff", action="store_true",
                        help="on a mismatch, print a unified diff of the two "
                             "stripped documents (needs --baseline)")
    parser.add_argument("--bench", action="store_true",
                        help="also time synthetic 4/50/200-file corpora (needs --baseline)")
    parser.add_argument("--sizes", default="4,50,200",
                        help="synthetic corpus sizes for --bench (default 4,50,200)")
    parser.add_argument("--repeats", type=int, default=3,
                        help="runs per measurement, best kept (default 3)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    jobs = _corpus_jobs(args.repeats)
    dumps = tempfile.mkdtemp(prefix="mlview_perf_dump_") if args.diff else None
    after = _run_worker(CURRENT_SRC, jobs,
                        os.path.join(dumps, "after") if dumps else None)

    if args.record:
        with open(args.record, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"rows": after}, fh, indent=2)
        print("perf_equiv: recorded %d digest(s) to %s" % (len(after), args.record))
        print(_table("current", after))
        return 0

    before: Optional[List[Dict[str, object]]] = None
    label = ""
    if args.compare:
        with open(args.compare, encoding="utf-8") as fh:
            before = json.load(fh)["rows"]
        label = args.compare
    elif args.baseline:
        before = _run_worker(args.baseline, jobs,
                             os.path.join(dumps, "before") if dumps else None)
        label = args.baseline

    if before is None:
        print(_table("current", after))
        print("perf_equiv: no baseline given (--baseline DIR or --compare FILE); "
              "digests printed only.")
        return 0

    print("perf_equiv: baseline %s" % label)
    ok, lines = _compare(before, after)
    print("\n".join(lines))
    if dumps and not ok:
        moved = [str(row["label"]) for row in after
                 if any(b["label"] == row["label"] and b["sha256"] != row["sha256"]
                        for b in before)]
        print("\n".join(_diff_lines(os.path.join(dumps, "before"),
                                    os.path.join(dumps, "after"), moved)))
    if args.bench and args.baseline:
        print("\n".join(_bench(args.baseline, [int(s) for s in args.sizes.split(",")],
                               args.repeats)))
    print("")
    print("perf_equiv: %s" % ("OK - every corpus is byte-identical"
                              if ok else "FAILED - output changed"))
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
