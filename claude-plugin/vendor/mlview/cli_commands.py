"""The `init` and `diff` command bodies (CONTRACTS 11.37 and 11.38).

`cli.py` is a dispatcher whose size is proportional to the number of commands,
so two new subcommands live here rather than growing it further; `cli.py` keeps
a two-line wrapper for each, exactly as `_cmd_baseline` is a wrapper around
`adopt.cli_glue.cmd_baseline`.

Each entry point returns **True on success and False on a usage or I/O error**,
and `cli.py` maps that to §3's exit codes. Returning a bool rather than an exit
code is what keeps the exit-code table in one file: two integers duplicated
across two modules is exactly the drift `mlview.core.cache.file_signature`
existed to end, one layer up.

The stdout invariant (§3) is enforced here, not by the caller: **stdout carries
only the requested payload**. `init` writes a file, so its path goes to stderr
and stdout stays empty unless `--out -` asks for the file itself; `diff` writes
its rendering to stdout and the path of any `--json FILE` to stderr.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .core import config as config_mod
from .core import diff as diff_mod
from .emit import diff_out, json_out
from .emit.text_out import write_stderr, write_stdout

__all__ = ["apply_file_config", "run_init", "run_diff"]


def apply_file_config(args) -> None:
    """CFG-ONE (11.37 B5): fill in the flags the configuration file names.

    `[analysis]` and `[paths]` are applied inside `pipeline.run`, where every
    caller reaches them. `[baseline] path` cannot be, because CI-ADOPT applies
    a baseline to the **finished graph** from `args`, never to the analysis -
    so one line here, rather than a second configuration mechanism in the adopt
    layer. `--baseline` on the command line always wins.
    """
    if getattr(args, "baseline_path", None):
        return
    config = config_mod.load_config(
        getattr(args, "config_path", None),
        config_mod.probe_root(getattr(args, "paths", ()) or ()))
    if config.baseline_path:
        args.baseline_path = config.baseline_path


def run_init(args) -> bool:
    """`mlview init` (CFG-ONE, CONTRACTS 11.37 D)."""
    target: Optional[str] = getattr(args, "out_file", None)
    text = config_mod.render_init()
    if target == "-":
        write_stdout(text)
        return True
    if not target:
        root = config_mod.probe_root(getattr(args, "paths", ()) or ())
        if not root:
            write_stderr("mlview: cannot work out a workspace root; pass a path "
                         "or --out FILE")
            return False
        target = config_mod.init_path_for(root)
    abs_path = os.path.abspath(target)
    if os.path.exists(abs_path) and not getattr(args, "force", False):
        # D4: never silently overwrite a file a human wrote. The disable list in
        # it is doing real work, and `init` is the one command that could delete
        # it; `--force` is the deliberate way to ask.
        write_stderr("mlview: %s already exists; pass --force to overwrite it"
                     % abs_path.replace("\\", "/"))
        return False
    parent = os.path.dirname(abs_path)
    try:
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError as exc:
        write_stderr("mlview: cannot write %s: %s" % (abs_path, exc))
        return False
    write_stderr("mlview: wrote %s" % abs_path.replace("\\", "/"))
    return True


def run_diff(args) -> bool:
    """`mlview diff BASE.json HEAD.json` (VIEW-08, CONTRACTS 11.38 A)."""
    documents = []
    for path in (args.base_file, args.head_file):
        try:
            documents.append(json_out.load_json(path))
        except OSError as exc:
            write_stderr("mlview: cannot read %s: %s" % (path, exc))
            return False
        except ValueError as exc:
            write_stderr("mlview: %s is not valid JSON: %s" % (path, exc))
            return False
    try:
        overlay: Any = diff_mod.diff_documents(documents[0], documents[1])
    except diff_mod.DiffError as exc:
        write_stderr("mlview: %s" % exc)
        return False
    target = getattr(args, "json_out", None)
    if target and target != "-":
        write_stderr("mlview: wrote %s" % json_out.write_json(overlay, target))
        target = None
    if target == "-" or getattr(args, "fmt", "summary") == "json":
        write_stdout(json_out.dumps(overlay))
    else:
        write_stdout(diff_out.render_summary(overlay))
    return True
