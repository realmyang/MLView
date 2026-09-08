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
#: CI-ADOPT: `adopt/gitdiff.py` runs `git diff` and nothing else. The exemption
#: is one file wide and is paid for by
#: `test_the_only_program_the_core_can_launch_is_git`, which asserts the argv
#: literally starts with "git", never interpolates analyzed source, and never
#: uses a shell. The analyzed program is still never imported, executed or
#: `exec`ed - that is the promise this module exists to keep.
ALLOWED_SUBPROCESS = {os.path.join("adopt", "gitdiff.py")}

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
                        root_module = alias.name.split(".")[0]
                        if root_module == "subprocess" and relpath in ALLOWED_SUBPROCESS:
                            continue
                        if root_module in banned_modules:
                            offenders.append("%s:%d imports %s"
                                             % (relpath, node.lineno, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    root_module = (node.module or "").split(".")[0]
                    if root_module == "subprocess" and relpath in ALLOWED_SUBPROCESS:
                        continue
                    if root_module in banned_modules:
                        offenders.append("%s:%d imports from %s"
                                         % (relpath, node.lineno, node.module))
    assert offenders == [], "dynamic execution / network in the core:\n" + "\n".join(offenders)


def test_the_only_program_the_core_can_launch_is_git():
    """The price of `ALLOWED_SUBPROCESS`, charged in full.

    Every `subprocess` call in the core must be a list whose **first element is
    the literal string "git"**, with no `shell=`. That is what keeps the one
    exemption from becoming a general "the analyzer may run programs" licence:
    a future `subprocess.run(user_string, shell=True)` fails here even though
    the import is allowed.
    """
    import ast

    calls = 0
    offenders = []
    for relpath in sorted(ALLOWED_SUBPROCESS):
        with open(os.path.join(CORE_DIR, relpath), encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=relpath)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                    and func.value.id == "subprocess"):
                continue
            calls += 1
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    offenders.append("%s:%d passes shell=" % (relpath, node.lineno))
            argv = node.args[0] if node.args else None
            while isinstance(argv, ast.BinOp):       # ["git"] + list(args)
                argv = argv.left
            first = argv.elts[0] if isinstance(argv, ast.List) and argv.elts else None
            if not (isinstance(first, ast.Constant) and first.value == "git"):
                offenders.append("%s:%d does not launch git" % (relpath, node.lineno))
    assert calls >= 1, "the exemption is unused; delete it"
    assert offenders == [], "\n".join(offenders)


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
