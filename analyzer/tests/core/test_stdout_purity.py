"""The stdout invariant: only the requested payload ever reaches stdout."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import mlview

CORE_DIR = os.path.dirname(os.path.abspath(mlview.__file__))
ALLOWED = {os.path.join("emit", "text_out.py")}
PRINT_RE = re.compile(r"(?<![\w.])print\s*\(")


def iter_sources():
    for dirpath, dirnames, filenames in os.walk(CORE_DIR):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def test_no_bare_print_outside_the_text_emitter():
    offenders = []
    for path in iter_sources():
        relpath = os.path.relpath(path, CORE_DIR)
        if relpath in ALLOWED:
            continue
        with open(path, encoding="utf-8") as fh:
            for number, line in enumerate(fh, start=1):
                stripped = line.strip()
                if stripped.startswith("#") or "traceback.print_exc" in stripped:
                    continue
                if PRINT_RE.search(line):
                    offenders.append("%s:%d %s" % (relpath, number, stripped))
    assert offenders == [], "stray print() in the core:\n" + "\n".join(offenders)


def test_json_to_stdout_is_pure_json(tmp_path):
    source = tmp_path / "m.py"
    source.write_text("import torch\nx = torch.device('cpu')\n", encoding="utf-8")
    proc = _run(["analyze", str(tmp_path), "--json", "-"])
    assert proc.returncode == 0
    doc = json.loads(proc.stdout.decode("utf-8"))
    assert doc["schemaVersion"] == "1.0"


def test_progress_and_warnings_go_to_stderr(tmp_path):
    (tmp_path / "m.py").write_text("import torch\n", encoding="utf-8")
    out = tmp_path / "graph.json"
    proc = _run(["analyze", str(tmp_path), "--json", str(out), "--format", "summary"])
    assert proc.returncode == 0
    assert b"wrote" in proc.stderr
    assert b"wrote" not in proc.stdout
    assert out.exists()


def test_html_path_message_is_not_on_stdout(tmp_path):
    (tmp_path / "m.py").write_text("import torch\n", encoding="utf-8")
    report = tmp_path / "r.html"
    proc = _run(["analyze", str(tmp_path), "--json", "-", "--html", str(report)])
    assert proc.returncode == 0
    json.loads(proc.stdout.decode("utf-8"))          # stdout is JSON and nothing else
    assert report.exists()


def _run(args):
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    return subprocess.run([sys.executable, "-X", "utf8", "-m", "mlview"] + args,
                          capture_output=True, env=env)
