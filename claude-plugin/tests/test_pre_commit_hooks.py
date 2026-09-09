"""HOST-2 — the pre-commit hooks can actually be installed.

`.pre-commit-hooks.yaml` shipped two hooks, both `language: python`. pre-commit
installs such a hook by cloning THIS repository, creating a venv and running
`pip install .` **in the clone root** — there is no way to point it at a
subdirectory. The only packaging metadata in the tree lived in
`analyzer/pyproject.toml`, so the install died with

    ERROR: Directory '.' is not installable. Neither 'setup.py' nor 'pyproject.toml' found.

and neither `mlview` nor `mlview-changed` could ever run — with or without the
`rev: v0.1.0` tag being cut. README.md documents the failing invocation and
`docs/STATUS.md` states the hooks as shipped; nothing in the tree ran them. The
fix is a repo-root `pyproject.toml` that packages `analyzer/src/mlview`; these
tests are the gate that stops the artifact shipping dead again.

Three layers, cheapest first:

* **Always** — the hooks file parses, and every claim it makes about the repository
  is true of the repository: a `language: python` hook needs an installable root,
  and its `entry` must be a console script that root declares.
* **When setuptools is importable** — the root metadata really builds a wheel, with
  the console script and the package data a first analysis needs (no network: the
  build runs `--no-isolation`).
* **When pre-commit is installed** — the whole thing, end to end: a throwaway clone
  of the working tree, `pre-commit try-repo`, a consumer repo with a leak in it.

They live in the plugin suite because `.pre-commit-hooks.yaml` is the plugin
component's artifact (CI-ADOPT part d) and this is the suite that runs on every
push; nothing here imports the MCP server.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

import pytest

from plugin_support import REPO_ROOT

HOOKS_FILE = os.path.join(REPO_ROOT, ".pre-commit-hooks.yaml")
ROOT_PYPROJECT = os.path.join(REPO_ROOT, "pyproject.toml")
ANALYZER_PYPROJECT = os.path.join(REPO_ROOT, "analyzer", "pyproject.toml")

#: A leak with two low findings and no high one, so a hook that runs it with
#: `--fail-on high` must exit 0 — the hook working, not the gate firing.
CONSUMER_SOURCE = """\
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split


def build(X, y):
    Xs = StandardScaler().fit_transform(X)
    return train_test_split(Xs, y, test_size=0.2)
"""


# --------------------------------------------------------------------- parsing
def _flow_list(raw: str):
    """`['analyze', '.', --format]` -> the items, quoted or bare, commas honoured.

    YAML flow sequences, which is all this file uses for `args` and `types`. Split
    by hand rather than with `ast.literal_eval`, because `types: [python]` is a
    perfectly good flow sequence and not a Python literal at all.
    """
    items, current, quote = [], [], ""
    for char in raw.strip()[1:-1]:
        if quote:
            if char == quote:
                quote = ""
            else:
                current.append(char)
        elif char in "'\"":
            quote = char
        elif char == ",":
            items.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    tail = "".join(current).strip()
    if tail or items:
        items.append(tail)
    return items


def _parse_hooks_without_yaml(text: str):
    """The subset of YAML `.pre-commit-hooks.yaml` uses, without PyYAML.

    The plugin CI job installs `mcp pytest pytest-xdist jsonschema` and nothing
    else, so a gate that needed PyYAML would skip itself exactly where it matters.
    `test_the_fallback_parser_agrees_with_pyyaml` keeps this honest wherever
    PyYAML *is* installed.
    """
    hooks = []
    for chunk in re.split(r"(?m)^-[ \t]+", text)[1:]:
        # Re-indent the first key so every key in the block is shaped alike; the
        # sequence dash is the only thing that made `id` different from `name`.
        block = "  " + chunk
        hook = {}
        for key in ("id", "name", "entry", "language", "pass_filenames",
                    "always_run", "require_serial"):
            found = re.search(r"(?m)^\s*%s:[ \t]*(.+)$" % key, block)
            if found:
                raw = found.group(1).strip()
                if raw in ("true", "false"):
                    hook[key] = raw == "true"
                else:
                    hook[key] = raw.strip("'\"")
        for key in ("args", "types"):
            found = re.search(r"(?ms)^\s*%s:[ \t]*(\[.*?\])" % key, block)
            if found:
                hook[key] = _flow_list(found.group(1))
        if "id" in hook:
            hooks.append(hook)
    return hooks


def _hooks():
    with open(HOOKS_FILE, encoding="utf-8") as fh:
        text = fh.read()
    try:
        import yaml  # noqa: PLC0415 - optional; the fallback is the CI path
    except ImportError:
        return _parse_hooks_without_yaml(text)
    return yaml.safe_load(text)


def _toml(path):
    try:
        import tomllib  # noqa: PLC0415 - stdlib from 3.11
    except ImportError:  # pragma: no cover - only on 3.10
        pytest.skip("tomllib needs Python 3.11+")
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def test_the_fallback_parser_agrees_with_pyyaml():
    yaml = pytest.importorskip("yaml")
    with open(HOOKS_FILE, encoding="utf-8") as fh:
        text = fh.read()
    reference = yaml.safe_load(text)
    mine = _parse_hooks_without_yaml(text)
    assert [h["id"] for h in mine] == [h["id"] for h in reference]
    for got, want in zip(mine, reference):
        for key in ("entry", "language", "args", "types", "pass_filenames",
                    "always_run", "require_serial"):
            assert got.get(key) == want.get(key), (got["id"], key)


# ----------------------------------------------------------- the hooks themselves
def test_the_hooks_file_declares_the_two_documented_hooks():
    hooks = _hooks()
    assert [h["id"] for h in hooks] == ["mlview", "mlview-changed"], (
        "README.md and docs/STATUS.md name exactly these two"
    )
    for hook in hooks:
        # COVERAGE: a per-file invocation loses four cross-file rules, which is why
        # the file's own header calls this the load-bearing line.
        assert hook["pass_filenames"] is False, hook["id"]
        assert hook["always_run"] is True, hook["id"]


# --------------------------------------------------------- HOST-2, the root cause
def test_a_language_python_hook_has_an_installable_repository_root():
    """`pip install .` in the clone root is what pre-commit runs. It must work."""
    hooks = _hooks()
    assert any(h.get("language") == "python" for h in hooks), (
        "if the hooks stop being language: python, this gate must be re-derived"
    )
    assert os.path.isfile(ROOT_PYPROJECT) or os.path.isfile(
        os.path.join(REPO_ROOT, "setup.py")
    ), (
        "a language: python hook installs the repository ROOT; without a root "
        "pyproject.toml (or setup.py) pre-commit fails with \"Directory '.' is not "
        "installable\" and neither hook can ever run"
    )
    data = _toml(ROOT_PYPROJECT)
    assert data["build-system"]["build-backend"], "no build backend, no install"
    assert data["project"]["name"] == "mlview"


def test_every_hook_entry_is_a_console_script_the_root_install_provides():
    scripts = _toml(ROOT_PYPROJECT)["project"]["scripts"]
    for hook in _hooks():
        if hook.get("language") != "python":
            continue
        entry = hook["entry"].split()[0]
        assert entry in scripts, (
            "%s runs `%s`, which the root install does not put on PATH (it declares %s)"
            % (hook["id"], entry, sorted(scripts))
        )
    assert scripts["mlview"] == "mlview.cli:main"


def test_the_root_distribution_is_the_analyzer_and_not_a_copy_of_it():
    """No third source tree: the root packages `analyzer/src/mlview` in place."""
    data = _toml(ROOT_PYPROJECT)
    package_dir = data["tool"]["setuptools"]["package-dir"][""]
    assert package_dir == "analyzer/src"
    assert data["tool"]["setuptools"]["packages"]["find"]["where"] == ["analyzer/src"]
    assert os.path.isfile(
        os.path.join(REPO_ROOT, package_dir.replace("/", os.sep), "mlview", "cli.py")
    )
    assert not os.path.isdir(os.path.join(REPO_ROOT, "src")), (
        "a root src/ tree would be a fourth copy of the analyzer"
    )


def test_the_root_metadata_cannot_drift_from_the_analyzer_metadata():
    """The one place a second pyproject could lie: version, deps, package data."""
    root = _toml(ROOT_PYPROJECT)
    analyzer = _toml(ANALYZER_PYPROJECT)
    assert "version" in root["project"].get("dynamic", []), (
        "a literal version here would be a sixth manifest for tools/verify.py "
        "--versions to keep in step, and it does not read this file"
    )
    assert root["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "mlview.version.__version__"
    }
    from mlview.version import __version__  # noqa: PLC0415

    assert analyzer["project"]["version"] == __version__, "verify.py's gate 3"
    for key in ("name", "requires-python", "dependencies", "scripts"):
        assert root["project"][key] == analyzer["project"][key], key
    assert (root["tool"]["setuptools"]["package-data"]
            == analyzer["tool"]["setuptools"]["package-data"])
    # ...and the globs match real files, or the wheel installs and then fails on
    # the first analysis (the failure tools/wheel_check.py exists to catch).
    for glob_pattern in root["tool"]["setuptools"]["package-data"]["mlview"]:
        directory = os.path.join(REPO_ROOT, "analyzer", "src", "mlview",
                                 *glob_pattern.split("/")[:-1])
        assert os.path.isdir(directory), glob_pattern
        assert os.listdir(directory), glob_pattern


def test_the_root_pyproject_does_not_capture_the_pytest_configuration():
    """Adding a root inifile would silently re-root every suite in the repo."""
    assert "pytest" not in _toml(ROOT_PYPROJECT).get("tool", {})


# ------------------------------------------------------ layer 2: it really builds
def _minimal_hook_repo(destination: str) -> str:
    """The working tree reduced to what `pip install .` in a clone reads."""
    os.makedirs(destination, exist_ok=True)
    for rel in ("pyproject.toml", "README.md", ".pre-commit-hooks.yaml"):
        shutil.copy2(os.path.join(REPO_ROOT, rel), os.path.join(destination, rel))
    shutil.copytree(
        os.path.join(REPO_ROOT, "analyzer", "src"),
        os.path.join(destination, "analyzer", "src"),
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return destination


def test_the_root_metadata_builds_a_usable_wheel(tmp_path):
    """Real proof, no network: `--no-isolation` needs setuptools already present."""
    pytest.importorskip("build", reason="python -m build is not installed")
    pytest.importorskip(
        "setuptools",
        reason="a wheel build without setuptools would need the network; "
               "run `pip install setuptools` to turn this gate on",
    )
    source = _minimal_hook_repo(str(tmp_path / "repo"))
    out = str(tmp_path / "dist")
    built = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", out,
         source],
        capture_output=True, text=True, check=False,
    )
    assert built.returncode == 0, built.stdout[-3000:] + built.stderr[-3000:]
    wheels = [f for f in os.listdir(out) if f.endswith(".whl")]
    assert len(wheels) == 1, wheels
    import zipfile  # noqa: PLC0415

    with zipfile.ZipFile(os.path.join(out, wheels[0])) as zf:
        names = set(zf.namelist())
        entry_points = next(n for n in names if n.endswith("entry_points.txt"))
        assert "mlview = mlview.cli:main" in zf.read(entry_points).decode("utf-8")
    assert "mlview/cli.py" in names
    assert "mlview/schema/graph.schema.json" in names, "package data, or analysis dies"
    assert any(n.startswith("mlview/emit/assets/") for n in names)
    from mlview.version import __version__  # noqa: PLC0415

    assert wheels[0].startswith("mlview-%s-" % __version__), wheels


# ---------------------------------------------- layer 3: pre-commit, end to end
def _pre_commit() -> str:
    return os.environ.get("MLVIEW_PRE_COMMIT") or shutil.which("pre-commit") or ""


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=False)


@pytest.mark.skipif(not _pre_commit(),
                    reason="pre-commit is not installed (set MLVIEW_PRE_COMMIT=<path> "
                           "or `pip install pre-commit` to run the end-to-end gate)")
@pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")
def test_pre_commit_installs_this_repository_and_runs_the_hook(tmp_path):
    """`pre-commit try-repo . mlview --all-files` in a scratch consumer repo.

    The clone is made from the WORKING TREE, not from HEAD: `try-repo` against the
    real repository would test the last commit, so an uncommitted regression in the
    packaging metadata would pass this gate and break every consumer.
    """
    hook_repo = _minimal_hook_repo(str(tmp_path / "hookrepo"))
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"],
                 ["config", "user.name", "t"], ["add", "-A"],
                 ["commit", "-q", "-m", "hooks"]):
        result = _git(args, hook_repo)
        if result.returncode != 0:  # pragma: no cover - a misconfigured git
            pytest.skip("git %s failed: %s" % (args[0], result.stderr.strip()))

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "train.py").write_text(CONSUMER_SOURCE, encoding="utf-8")
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"],
                 ["config", "user.name", "t"], ["add", "-A"],
                 ["commit", "-q", "-m", "first"]):
        _git(args, str(consumer))

    env = dict(os.environ)
    env["PRE_COMMIT_HOME"] = str(tmp_path / "pchome")
    env["PYTHONUTF8"] = "1"
    run = subprocess.run(
        [_pre_commit(), "try-repo", hook_repo, "mlview", "--verbose", "--all-files"],
        cwd=str(consumer), capture_output=True, text=True, check=False, env=env,
        timeout=900,
    )
    output = run.stdout + run.stderr
    assert "is not installable" not in output, output[-3000:]
    assert run.returncode == 0, output[-3000:]
    # The hook ran MLView over the whole consumer project, not per file.
    assert "MLV602" in output, output[-3000:]


def test_the_hook_command_is_the_one_the_docs_promise():
    """`entry` + `args` must be a command the shipped CLI accepts."""
    hooks = {h["id"]: h for h in _hooks()}
    assert hooks["mlview"]["args"][:2] == ["analyze", "."]
    assert "--fail-on" in hooks["mlview"]["args"]
    changed = hooks["mlview-changed"]["args"]
    assert "--changed-since" in changed and "--changed-only" in changed
    # The flags exist in this analyzer, so the hook cannot rot against the CLI.
    from mlview.cli_parser import build_parser  # noqa: PLC0415

    parser = build_parser()
    parsed = parser.parse_args(changed)
    assert getattr(parsed, "changed_since", None) == "HEAD"
    assert getattr(parsed, "changed_only", False) is True
