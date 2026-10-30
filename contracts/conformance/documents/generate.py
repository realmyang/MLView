#!/usr/bin/env python3
"""Write the test documents that the validator tests read (see README.md beside this file).

    python contracts/conformance/documents/generate.py            # rewrite workspace/
    python contracts/conformance/documents/generate.py --check    # compare workspace/ with a fresh run

The script writes a small workspace of source files and eight WorkflowDocuments that cite
them. It publishes every document with skills/mlview/scripts/artifact.py, so the helper
checks each path, hash and quote and computes `verification.files`. It then sets
`verification.publishedAt` to a fixed value, so that a second run gives the same bytes.

The documents are test fixtures. They do not describe a real program and no model wrote
them. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
HELPER = HERE.parents[2] / "skills" / "mlview" / "scripts" / "artifact.py"
PUBLISHED_AT = "2000-01-01T00:00:00Z"   # a fixed value, so the files are reproducible
HEADER = '"""Test source for the MLView validator tests. Generated; it is not a real program."""\n'

# file -> [(function, argument, result)]
MODULES = {
    "pipeline/data.py": [("read_rows", "source", "rows"), ("drop_empty_rows", "rows", "kept"), ("shuffle_rows", "rows", "shuffled"),
                         ("split_rows", "rows", "parts"), ("make_batches", "rows", "batches"), ("cache_rows", "rows", "cached"),
                         ("count_rows", "rows", "total")],
    "pipeline/features.py": [("select_columns", "rows", "columns"), ("fill_missing", "columns", "filled"), ("clip_values", "columns", "clipped"),
                             ("fit_scaler", "columns", "scaler"), ("apply_scaler", "columns", "scaled"), ("encode_labels", "labels", "encoded"),
                             ("join_features", "parts", "features")],
    "pipeline/model.py": [("build_encoder", "width", "encoder"), ("build_head", "classes", "head"), ("build_model", "config", "model"),
                          ("init_weights", "model", "weights"), ("freeze_encoder", "model", "frozen"), ("load_checkpoint", "path", "state"),
                          ("count_parameters", "model", "size")],
    "pipeline/train.py": [("make_optimizer", "model", "optimizer"), ("make_schedule", "optimizer", "schedule"), ("forward_pass", "batch", "outputs"),
                          ("compute_loss", "outputs", "loss"), ("backward_pass", "loss", "gradients"), ("update_weights", "gradients", "step"),
                          ("train_epoch", "batches", "epoch_loss"), ("fit", "config", "history")],
    "pipeline/evaluate.py": [("predict_batch", "batch", "predictions"), ("score_batch", "predictions", "scores"), ("aggregate_scores", "scores", "summary"),
                             ("compare_with_baseline", "summary", "delta"), ("pick_threshold", "scores", "threshold"), ("evaluate", "model", "report")],
    "pipeline/export.py": [("save_checkpoint", "model", "saved"), ("write_metrics", "report", "metrics_path"), ("write_report", "report", "report_path"),
                           ("export_model", "model", "exported")],
}
# name -> the source lines of one notebook code cell
CELLS = [("load", ["rows = read_rows('rows.csv')\n", "len(rows)"]), ("inspect", ["first = rows[:5]\n", "first"]),
         ("split", ["train_rows, test_rows = split_rows(rows)\n", "len(train_rows), len(test_rows)"]),
         ("features", ["features = join_features([train_rows])\n", "features[:2]"]),
         ("fit", ["history = fit({'epochs': 2})\n", "history"]), ("score", ["report = evaluate(history)\n", "report"])]
NOTEBOOK = "notebooks/explore.ipynb"
CONFIG = "pipeline/config.json"
KINDS = ("data", "control", "state", "output")
PHASES = ("Inputs", "Features", "Model", "Optimisation", "Training loop", "Evaluation", "Outputs", "Reporting", "Checks")

# One entry per document. `steps` counts the group nodes too. `files` are the sources its steps
# cite, in order. `loop` adds a connection that goes back, `unresolved` leaves every ninth
# connection without evidence, `nested` puts every second group inside the one before it, and
# `parent` publishes a first revision and then a second one that names it.
DOCS = [
    dict(id="d01-minimal", steps=4, connections=3, phases=3, findings=0, groups=0, files=["pipeline/data.py"]),
    dict(id="d02-notebook", steps=7, connections=6, phases=4, findings=3, groups=0, files=[NOTEBOOK, "pipeline/data.py"], unresolved=True),
    dict(id="d03-two-files", steps=10, connections=9, phases=3, findings=1, groups=1, files=["pipeline/data.py", "pipeline/features.py"]),
    dict(id="d04-loop", steps=12, connections=15, phases=5, findings=2, groups=0, files=["pipeline/train.py", "pipeline/model.py"], loop=True),
    dict(id="d05-groups", steps=16, connections=21, phases=4, findings=4, groups=4, nested=True, files=[NOTEBOOK, "pipeline/features.py", "pipeline/model.py"]),
    dict(id="d06-refinement", steps=20, connections=23, phases=5, findings=2, groups=2, parent=True, status="partial",
         files=["pipeline/data.py", "pipeline/features.py", "pipeline/model.py"], unresolved=True),
    dict(id="d07-multi-file", steps=28, connections=41, phases=6, findings=2, groups=3, loop=True,
         files=["pipeline/data.py", "pipeline/features.py", "pipeline/model.py", "pipeline/train.py", "pipeline/evaluate.py"]),
    dict(id="d08-dense", steps=38, connections=72, phases=9, findings=2, groups=4, loop=True, unresolved=True, files=list(MODULES)),
]


def sources() -> dict[str, str]:
    """The text of every source file of the workspace, by relative path."""
    files = {}
    for path, functions in MODULES.items():
        parts = [HEADER]
        for name, argument, result in functions:
            parts.append(f"\n\ndef {name}({argument}):\n    {result} = transform({argument!s}, step=\"{name}\")\n    return {result}\n")
        parts.append("\n\ndef transform(value, step):\n    return (step, value)\n")
        files[path] = "".join(parts)
    cells = [{"cell_type": "markdown", "metadata": {}, "source": ["Test notebook for the MLView validator tests. Generated; it is not a real analysis."]}]
    for _, source in CELLS:
        cells.append({"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": source})
    files[NOTEBOOK] = json.dumps({"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}, indent=1) + "\n"
    files[CONFIG] = json.dumps({"comment": "Test configuration for the MLView validator tests.", "epochs": 2, "width": 16}, indent=2) + "\n"
    return files


def units(files: dict[str, str], wanted: list[str]) -> list[dict]:
    """Everything a step can cite in the wanted files: a function (its three lines) or a notebook cell."""
    found = []
    for path in wanted:
        if path == NOTEBOOK:
            for index, (name, source) in enumerate(CELLS, 1):
                text = "".join(source).split("\n")
                found.append(dict(key=f"cell-{name}", label=f"Notebook cell: {name}", file=path, cell=index, line=1, endLine=len(text),
                                  quote="\n".join(text), result=name))
            continue
        lines = files[path].split("\n")
        for name, argument, result in MODULES[path]:
            start = lines.index(f"def {name}({argument}):")
            found.append(dict(key=name.replace("_", "-"), label=name.replace("_", " ").capitalize(), file=path, line=start + 1, endLine=start + 3,
                              quote="\n".join(lines[start:start + 3]), result=result))
    return found


def evidence_of(unit: dict) -> dict:
    record = dict(id="ev-" + unit["key"], file=unit["file"], line=unit["line"], endLine=unit["endLine"], quote=unit["quote"])
    if "cell" in unit:
        record["cell"] = unit["cell"]
    return record


def build(spec: dict, files: dict[str, str], steps: int | None = None, connections: int | None = None, revision: str = "r1", parent: str | None = None) -> dict:
    """The draft of one document, from its entry in DOCS."""
    steps = steps or spec["steps"]
    connections = connections if connections is not None else spec["connections"]
    groups = spec.get("groups", 0)
    leaves_wanted = steps - groups
    pool = units(files, spec["files"])
    if len(pool) < leaves_wanted:
        raise SystemExit(f"{spec['id']}: {leaves_wanted} steps need more than the {len(pool)} units its files hold")
    leaves = pool[:leaves_wanted]
    phases = [dict(id=f"phase-{i + 1}", label=PHASES[i]) for i in range(spec["phases"])]
    phase_of = [phases[min(i * len(phases) // leaves_wanted, len(phases) - 1)]["id"] for i in range(leaves_wanted)]
    used: dict[str, dict] = {}

    def cite(unit: dict) -> str:
        used.setdefault(unit["key"], evidence_of(unit))
        return "ev-" + unit["key"]

    nodes = []
    for i, unit in enumerate(leaves):
        basis = "inferred" if i % 6 == 5 else "observed"
        nodes.append(dict(id="step-" + unit["key"], label=unit["label"], phase=phase_of[i], kind=KINDS[i % len(KINDS)], basis=basis,
                          detail=f"Test step {i + 1} of {leaves_wanted}. It cites {unit['file']}.", evidence=[cite(unit)]))
    # A group is a step without evidence that holds consecutive steps of one phase.
    group_nodes = []
    stride = leaves_wanted // groups if groups else 0
    size = min(4, stride)
    for g in range(groups):
        inner = bool(spec.get("nested")) and g % 2 == 1
        # An inner group sits inside the group before it and takes two of that group's steps.
        first = (g - 1) * stride if inner else g * stride
        members = [n for n in nodes[first:first + (2 if inner else size)] if n["phase"] == nodes[first]["phase"]]
        group = dict(id=f"group-{g + 1}", label=f"Test group {g + 1}", phase=nodes[first]["phase"], kind="group", basis="observed", evidence=[])
        if inner:
            group["parent"] = group_nodes[-1]["id"]
        for member in members:
            member["parent"] = group["id"]
        group_nodes.append(group)
    nodes = group_nodes + nodes
    ids = [n["id"] for n in nodes if n["kind"] != "group"]
    # A chain first, then the loop, then longer and longer skips until the count is reached.
    pairs = [(i, i + 1) for i in range(len(ids) - 1)]
    if spec.get("loop"):
        pairs.append((len(ids) - 2, 1))
    gap = 2
    while len(pairs) < connections:
        added = False
        for i in range(0, len(ids) - gap, max(1, gap - 1)):
            if len(pairs) == connections:
                break
            pairs.append((i, i + gap))
            added = True
        gap += 1
        if not added and gap > len(ids):
            raise SystemExit(f"{spec['id']}: cannot place {connections} connections on {len(ids)} steps")
    pairs = pairs[:connections]
    edges = []
    for k, (a, b) in enumerate(pairs):
        back = b < a
        basis = "unresolved" if spec.get("unresolved") and k % 9 == 8 else "inferred" if k % 5 == 4 else "observed"
        edges.append(dict(id=f"edge-{k + 1:02d}", source=ids[a], target=ids[b], label=leaves[a]["result"], basis=basis,
                          kind="loop" if back else KINDS[k % len(KINDS)], evidence=[] if basis == "unresolved" else [cite(leaves[a])]))
    findings = []
    for f in range(spec["findings"]):
        unit, other = leaves[(f * 3 + 1) % leaves_wanted], leaves[(f * 3 + 2) % leaves_wanted]
        finding = dict(id=f"finding-{f + 1}", title=f"Test finding {f + 1}",
                       message=f"Placeholder finding on {unit['label'].lower()}. It states nothing about a real program.",
                       severity=("low", "medium", "high")[f % 3], nodeIds=["step-" + unit["key"]], basis=("observed", "inferred", "observed", "unresolved")[f % 4],
                       evidence=[cite(unit)], suggestion="None. This is a test fixture.")
        if f % 2 == 1:
            finding["counterEvidence"] = [cite(other)]
            finding["edgeIds"] = [edges[f]["id"]]
        if finding["basis"] == "unresolved":
            finding["evidence"] = []
        findings.append(finding)
    cited = sorted({record["file"] for record in used.values()}, key=spec["files"].index)
    doc = dict(
        workflowVersion="1.0",
        title=f"Test document {spec['id']}: {steps} steps, {connections} connections",
        producer=dict(kind="host-llm", host="unknown"),
        revision=dict(id=f"{spec['id']}-{revision}"),
        request=dict(question="Generated test document for the validator tests. It does not describe a real program.",
                     scope="The generated files of contracts/conformance/documents/workspace.", entrypoints=[cited[0]], configuration=CONFIG),
        phases=phases, nodes=nodes, edges=edges, findings=findings, evidence=list(used.values()),
        coverage=dict(status=spec.get("status", "scoped"), summary="Written by contracts/conformance/documents/generate.py. Every claim is a placeholder.",
                      inspectedFiles=cited + [CONFIG], limitations=["This is a test fixture. It is not a sample diagram and no model wrote it."]),
    )
    if parent:
        doc["revision"]["parent"] = parent
    return doc


def publish(workspace: Path, doc: dict, name: str) -> None:
    """Publish one draft with the helper, pin the publication time and validate the result."""
    draft = workspace / ".mlview" / "generate" / "draft.json"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(json.dumps(doc), encoding="utf-8")
    result = subprocess.run([sys.executable, str(HELPER), "publish", ".mlview/generate/draft.json", "--workspace", str(workspace), "--output", name],
                            capture_output=True, text=True, cwd=workspace)
    answer = json.loads(result.stdout) if result.stdout else {}
    if result.returncode or result.stderr or not answer.get("ok") or answer.get("warnings"):
        raise SystemExit(f"{name}: the helper did not publish cleanly: {result.stdout}{result.stderr}")
    path = workspace / name
    published = json.loads(path.read_text(encoding="utf-8"))
    published["verification"]["publishedAt"] = PUBLISHED_AT
    # The helper's own form: two spaces, sorted keys, a final newline.
    path.write_bytes((json.dumps(published, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    checked = subprocess.run([sys.executable, str(HELPER), "validate", name, "--workspace", str(workspace)], capture_output=True, text=True, cwd=workspace)
    answer = json.loads(checked.stdout) if checked.stdout else {}
    if checked.returncode or not answer.get("ok") or answer.get("warnings") or answer.get("files") != published["verification"]["files"]:
        raise SystemExit(f"{name}: the published document does not validate: {checked.stdout}{checked.stderr}")


def generate(out: Path) -> list[str]:
    """Write <out>/workspace from nothing and return the names of the documents."""
    workspace = out / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    files = sources()
    for relative, text in files.items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    names = []
    for spec in DOCS:
        name = spec["id"] + ".mlview.json"
        if spec.get("parent"):
            publish(workspace, build(spec, files, steps=spec["steps"] - 2, connections=spec["connections"] - 3), name)
            publish(workspace, build(spec, files, revision="r2", parent=f"{spec['id']}-r1"), name)
        else:
            publish(workspace, build(spec, files), name)
        names.append(name)
    shutil.rmtree(workspace / ".mlview")
    return names


def tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def check(out: Path) -> list[str]:
    """Every way <out>/workspace differs from a fresh run; empty when the two are equal."""
    with tempfile.TemporaryDirectory() as temp:
        generate(Path(temp).resolve())
        fresh = tree(Path(temp).resolve() / "workspace")
    committed = tree(out / "workspace") if (out / "workspace").is_dir() else {}
    problems = []
    for name in sorted(fresh.keys() | committed.keys()):
        if name not in committed:
            problems.append(f"missing: workspace/{name}")
        elif name not in fresh:
            problems.append(f"not written by the generator: workspace/{name}")
        elif fresh[name] != committed[name]:
            problems.append(f"differs from a fresh run: workspace/{name}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=HERE, help="the folder that holds workspace/ (default: this script's folder)")
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 unless workspace/ equals a fresh run")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    if args.check:
        problems = check(out)
        for problem in problems:
            print("FAIL: " + problem)
        if not problems:
            print("OK: workspace/ equals a fresh run")
        return int(bool(problems))
    for name in generate(out):
        doc = json.loads((out / "workspace" / name).read_text(encoding="utf-8"))
        print(f"{name}: {len(doc['nodes'])} steps, {len(doc['edges'])} connections, {len(doc['phases'])} phases, "
              f"{len(doc['findings'])} findings, {len(doc['evidence'])} evidence records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
