"""Static only: MLView never imports, executes or `exec`s the analyzed code."""

from __future__ import annotations

import os
import re
import sys

import mlview
from mlview.api import AnalyzeOptions, analyze_to_dict

CORE_DIR = os.path.dirname(os.path.abspath(mlview.__file__))
FORBIDDEN = (
    re.compile(r"(?<![\w.])exec\s*\("),
    re.compile(r"(?<![\w.])eval\s*\("),
    re.compile(r"importlib\.import_module\s*\("),
    re.compile(r"__import__\s*\("),
    re.compile(r"subprocess\."),
    re.compile(r"socket\."),
    re.compile(r"urllib"),
    re.compile(r"requests\."),
)
#: `rules/registry.py` imports rule modules - our own code, never the user's.
ALLOWED_IMPORT_MODULE = {os.path.join("rules", "registry.py")}

TORCH_SOURCE = ("import torch\n"
                "import torch.nn as nn\n"
                "import sklearn\n"
                "import transformers\n"
                "from sklearn.model_selection import train_test_split\n\n\n"
                "def go(X, y):\n"
                "    model = nn.Linear(2, 2)\n"
                "    return train_test_split(X, y)\n")


def test_core_contains_no_dynamic_execution_or_network():
    """Parsed, not grepped, so a docstring mentioning `eval()` is not a hit."""
    import ast

    banned_calls = {"exec", "eval", "compile", "__import__"}
    banned_modules = {"socket", "urllib", "requests", "http", "ftplib", "subprocess",
                      "telnetlib", "smtplib"}
    offenders = []
    for dirpath, dirnames, filenames in os.walk(CORE_DIR):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            relpath = os.path.relpath(path, CORE_DIR)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=relpath)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in banned_calls:
                        offenders.append("%s:%d calls %s()"
                                         % (relpath, node.lineno, node.func.id))
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "import_module" and relpath not in ALLOWED_IMPORT_MODULE:
                        offenders.append("%s:%d importlib.import_module"
                                         % (relpath, node.lineno))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in banned_modules:
                            offenders.append("%s:%d imports %s"
                                             % (relpath, node.lineno, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if (node.module or "").split(".")[0] in banned_modules:
                        offenders.append("%s:%d imports from %s"
                                         % (relpath, node.lineno, node.module))
    assert offenders == [], "dynamic execution / network in the core:\n" + "\n".join(offenders)


def test_analysis_never_imports_the_analyzed_frameworks(make_workspace):
    root = make_workspace({"m.py": TORCH_SOURCE})
    before = set(sys.modules)
    analyze_to_dict(AnalyzeOptions(paths=(root,)))
    added = set(sys.modules) - before
    leaked = {name for name in added
              if name.split(".")[0] in {"torch", "sklearn", "tensorflow", "keras",
                                        "transformers", "pandas", "numpy",
                                        "pytorch_lightning", "lightning"}}
    assert leaked == set(), "the analyzer imported %s" % sorted(leaked)


def test_torch_is_not_installed_and_analysis_still_works(make_workspace):
    """The demo machine has no torch: analysis must not care."""
    root = make_workspace({"m.py": TORCH_SOURCE})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    assert doc["workspace"]["filesFailed"] == 0
    assert "torch" in doc["workspace"]["frameworks"]
    assert doc["stats"]["nodes"] > 0
