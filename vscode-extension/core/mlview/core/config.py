"""CFG-ONE (CONTRACTS 11.37) — the one configuration surface.

Before this module there were two configuration systems that did not know
about each other: `.mlview.toml`, auto-discovered by the analyzer and honouring
`[rules] disable` and `[paths] exclude`, and a parallel `mlview.disabledRules`
/ `mlview.exclude` in the VS Code settings that never mentioned the file. The
requirement CFG-ONE states is **a stated precedence with a test, not more
surface**, so this module is deliberately small and says exactly three things:

1. **Where the configuration comes from.** `--config FILE`, else
   `<root>/.mlview.toml`, else the `[tool.mlview]` tables of
   `<root>/pyproject.toml`. The first one that exists wins outright — they are
   never merged, because two half-applied files is precisely the confusion this
   item exists to end — and whichever was applied is named in
   `workspace.configPath`, so no reader ever has to guess.

2. **What the file may say.** `[rules]` (`disable`, `enable`, `min_confidence`,
   `severity`), `[paths]` (`exclude`, `include`, `notebooks`), `[analysis]`
   (`relevance`, `dataflow`, `max_nodes`, `include_notebooks`) and `[baseline]`
   (`path`). Every table is optional and a file naming none of them behaves
   exactly as no file at all.

3. **Who wins.** `disable` and `exclude` are the file's: a host setting may add
   to them and may never take away from them (that is the lead's decision, and
   `vscode-extension` states it in its own setting descriptions). Every
   `[analysis]` option is the opposite way round — a **command-line flag wins
   over the file**, because a flag is a thing a human typed just now.

**What this cannot see, stated out loud.** `AnalyzeOptions` carries values, not
provenance, so "the caller asked for this" is read as "the value is not the
shipped default". A caller who *types* a flag with exactly its default value
(`--relevance ml` while the default is already `ml`) is therefore
indistinguishable from one who typed nothing, and the file wins that one case.
Making it exact would mean putting argparse state into the frozen options
surface; the case is stated here, asserted by a test, and left alone.
Everything else — a rule code that does not exist, a severity override, an
unknown key, an unreadable file — is a `config_warning` on the document and
never an error, because a configuration mistake must not be able to stop an
analysis from happening.
"""

from __future__ import annotations

import dataclasses
import difflib
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

__all__ = [
    "ANALYSIS_KEYS", "BASELINE_KEYS", "PATHS_KEYS", "RULES_META_KEYS", "SEVERITIES",
    "MlviewConfig", "known_codes", "unknown_code_warning", "load_config", "apply",
    "probe_root", "render_init", "init_path_for",
]

#: The keys each table understands. Anything else in one of them is a
#: `config_warning` naming the near misses - a silently ignored setting is the
#: same failure CLEANUP 3 fixed for rule codes, one table over.
RULES_META_KEYS = ("disable", "enable", "min_confidence", "severity")
PATHS_KEYS = ("exclude", "include", "notebooks")
ANALYSIS_KEYS = ("relevance", "relevance_hops", "dataflow", "max_nodes",
                 "include_notebooks")
BASELINE_KEYS = ("path",)
TABLES = ("rules", "paths", "analysis", "baseline")
SEVERITIES = ("low", "medium", "high")
#: How many near misses one "unknown" warning offers.
_SUGGESTIONS = 3


def known_codes() -> Set[str]:
    """Every registered rule code. Imported lazily: `rules/__init__` imports
    `rules/suppress`, which imports this module."""
    from ..rules.registry import all_rules
    return {spec.code for spec in all_rules()}


def unknown_code_warning(code: str, where: str) -> Optional[str]:
    """CLEANUP 3: a typo'd rule code was accepted in **total silence**.

    `MVL601 = "off"` and `MLV999 = "off"` both produced `diagnostics: []`, so a
    suppression that never took effect looked exactly like one that did.
    Returns None for a code that exists.
    """
    known = known_codes()
    if not known or code in known:
        return None
    near = [c for c in known if c.upper() == code.upper()]
    if not near:
        near = difflib.get_close_matches(code, sorted(known), n=_SUGGESTIONS, cutoff=0.5)
    hint = (" Did you mean %s?" % ", ".join(sorted(near))) if near else ""
    return ("unknown rule code %s in %s - the setting has no effect.%s"
            % (code, where, hint))


def _near(name: str, allowed: Sequence[str]) -> str:
    near = difflib.get_close_matches(name, list(allowed), n=1, cutoff=0.5)
    return (" Did you mean %s?" % near[0]) if near else ""


@dataclass
class MlviewConfig:
    """The resolved configuration file.

    The first five fields are the historical `RuleConfig` surface, in order, so
    every positional construction and every attribute read that existed before
    CFG-ONE still works. Everything CFG-ONE adds is **appended last and
    defaulted**, under the same rule §11.6 and §11.28 used for `AnalyzeOptions`.
    """

    path: Optional[str] = None
    disabled: Set[str] = field(default_factory=set)
    excludes: Tuple[str, ...] = ()
    warnings: List[str] = field(default_factory=list)
    #: NB. `[paths] notebooks = true` - the checked-in half of
    #: `--include-notebooks`, appended last and False by default so a config
    #: that does not name it behaves exactly as it did.
    notebooks: bool = False
    # ---------------------------------------------------------- CFG-ONE
    #: `[paths] include`. Additive with `--include`, never subtractive.
    includes: Tuple[str, ...] = ()
    #: `[rules] min_confidence`. None means "the file did not say".
    min_confidence: Optional[float] = None
    #: `[rules] enable`. **An allow-list**: when it is non-empty, every rule
    #: outside it is disabled. Empty means "every registered rule", which is
    #: what a file that does not name it gets.
    enabled: Tuple[str, ...] = ()
    #: `[rules.severity]`. Recorded, reported as a warning and never applied -
    #: a severity is a property of the rule, not of the project reading it.
    severity: Dict[str, str] = field(default_factory=dict)
    #: `[analysis]`, by `AnalyzeOptions` field name. Only keys the file
    #: actually set are present.
    analysis: Dict[str, Any] = field(default_factory=dict)
    #: `[baseline] path`, resolved against the config file's directory.
    baseline_path: Optional[str] = None
    #: `"mlview.toml"`, `"pyproject.toml"` or None. `path` is the file;
    #: this is the *shape* that was read, which is what decides whether the
    #: tables were top-level or under `[tool.mlview]`.
    source: Optional[str] = None


#: The historical name. `rules/suppress.py` re-exports it, and every existing
#: `RuleConfig()` construction and `isinstance` check keeps working.
RuleConfig = MlviewConfig


# --------------------------------------------------------------- discovery
def probe_root(paths: Sequence[str]) -> Optional[str]:
    """The workspace root `discover()` will report for `paths`.

    Deliberately `ingest.discover`'s **own** `_common_root`, not a second
    implementation: the configuration file MLView reads has to be the one in
    the root MLView goes on to name in `workspace.root`, and two functions that
    agree today are two functions that disagree later.
    """
    from ..ingest.discover import _common_root, normalize_path

    given = [normalize_path(p) for p in (paths or ()) if p]
    if not given:
        given = [normalize_path(".")]
    existing = [p for p in given if os.path.exists(p)]
    try:
        return _common_root(existing or given)
    except (OSError, ValueError):           # pragma: no cover - exotic paths
        return None


def init_path_for(root: str) -> str:
    """Where `mlview init` writes."""
    return os.path.join(root, ".mlview.toml").replace("\\", "/")


def _candidate(config_path: Optional[str], root: Optional[str]):
    """`(path, source)` for the file that will be read, or `(None, None)`."""
    if config_path:
        name = os.path.basename(config_path).lower()
        return config_path, ("pyproject.toml" if name == "pyproject.toml"
                             else "mlview.toml")
    if not root:
        return None, None
    own = os.path.join(root, ".mlview.toml")
    if os.path.isfile(own):
        return own, "mlview.toml"
    project = os.path.join(root, "pyproject.toml")
    if os.path.isfile(project):
        return project, "pyproject.toml"
    return None, None


def _read_toml(path: str, config: MlviewConfig) -> Optional[Dict[str, Any]]:
    try:
        import tomllib
    except ImportError:                     # pragma: no cover - 3.10 and older
        config.warnings.append("tomllib is unavailable; %s was ignored" % path)
        return None
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except OSError as exc:
        config.warnings.append("cannot read %s: %s" % (path, exc))
        return None
    except Exception as exc:                # tomllib.TOMLDecodeError
        config.warnings.append("cannot parse %s: %s" % (path, exc))
        return None


def load_config(config_path: Optional[str], root: Optional[str] = None) -> MlviewConfig:
    """Resolve the configuration for `root` (CONTRACTS 11.37).

    `--config FILE` first, then `<root>/.mlview.toml`, then `[tool.mlview]` in
    `<root>/pyproject.toml`. The winner is used **whole**; the others are not
    read at all.
    """
    path, source = _candidate(config_path, root)
    if not path:
        return MlviewConfig()
    config = MlviewConfig(path=str(path).replace("\\", "/"), source=source)
    data = _read_toml(path, config)
    if data is None:
        # Unreadable or unparseable: the warning survives, the *path* does not.
        # Same rule as the `[tool.mlview]`-less pyproject two branches down -
        # `workspace.configPath` may only name a file that actually decided
        # something, or a reader cannot tell an applied file from an ignored one.
        return MlviewConfig(warnings=list(config.warnings))
    if source == "pyproject.toml":
        tool = data.get("tool")
        section = (tool or {}).get("mlview") if isinstance(tool, dict) else None
        if not isinstance(section, dict):
            # A pyproject with no `[tool.mlview]` is not a configuration file.
            # Saying so is not pedantry: `workspace.configPath` would otherwise
            # name a file that decided nothing.
            if config_path:
                config.warnings.append(
                    "%s has no [tool.mlview] table; no configuration was applied"
                    % config.path)
                return MlviewConfig(warnings=list(config.warnings))
            return MlviewConfig()
        data = section
    _rules_table(data.get("rules"), config)
    _paths_table(data.get("paths"), config)
    _analysis_table(data.get("analysis"), config)
    _baseline_table(data.get("baseline"), config, path)
    for key in sorted(data):
        if key not in TABLES:
            config.warnings.append(
                "unknown section [%s] in %s - it was ignored.%s"
                % (key, config.path, _near(key, TABLES)))
    return config


# ------------------------------------------------------------------ tables
def _string_list(value: Any) -> Tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return ()


def _rules_table(rules: Any, config: MlviewConfig) -> None:
    if not isinstance(rules, dict):
        return
    where = config.path or "the config"
    disable = rules.get("disable")
    if disable is not None and not isinstance(disable, (list, tuple)):
        config.warnings.append("[rules] disable must be a list of rule codes; "
                               "%r in %s was ignored" % (disable, where))
    config.disabled.update(c.strip().upper() for c in _string_list(disable) if c.strip())

    enable = rules.get("enable")
    if enable is not None and not isinstance(enable, (list, tuple)):
        config.warnings.append("[rules] enable must be a list of rule codes; "
                               "%r in %s was ignored" % (enable, where))
    allow = tuple(sorted({c.strip().upper() for c in _string_list(enable) if c.strip()}))
    config.enabled = allow

    severity = rules.get("severity")
    if isinstance(severity, dict):
        for code, value in severity.items():
            _note_severity(config, str(code), value, where)
    elif severity is not None:
        config.warnings.append("[rules.severity] must be a table of "
                               "code = \"low|medium|high\"; %r in %s was ignored"
                               % (severity, where))

    if "min_confidence" in rules:
        value = rules.get("min_confidence")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            config.warnings.append("[rules] min_confidence must be a number "
                                   "between 0 and 1; %r in %s was ignored"
                                   % (value, where))
        elif not 0.0 <= float(value) <= 1.0:
            config.warnings.append("[rules] min_confidence must be between 0 "
                                   "and 1; %r in %s was ignored" % (value, where))
        else:
            config.min_confidence = float(value)

    for key, value in rules.items():
        if key in RULES_META_KEYS:
            continue
        text = str(value).strip().lower()
        if text in ("off", "false", "disabled", "no"):
            config.disabled.add(str(key).strip().upper())
        elif text in SEVERITIES:
            # CLEANUP 2: `path` is the raw, mixed-separator string; the
            # forward-slashed spelling was already computed on construction.
            _note_severity(config, str(key), value, where)
        else:
            config.warnings.append(
                "unknown key %s in [rules] of %s - it was ignored.%s"
                % (key, where, _near(str(key), RULES_META_KEYS)))

    # The stated precedence, made visible rather than silently resolved: the
    # file's own two lists can contradict each other, and `disable` wins.
    both = sorted(config.disabled & set(allow))
    for code in both:
        config.warnings.append(
            "%s is in both [rules] enable and [rules] disable in %s; disable "
            "wins and the rule stays off." % (code, where))
    if allow:
        # An allow-list is expressed as "everything else is disabled", so one
        # mechanism - the Suppressor - still does all the suppressing, and a
        # rule turned off this way is still *emitted* with `suppressed: true`.
        config.disabled |= (known_codes() - set(allow))
    for code in sorted(set(allow) | set(config.severity)):
        warning = unknown_code_warning(code, where)
        if warning:
            config.warnings.append(warning)
    for code in sorted(config.disabled):
        warning = unknown_code_warning(code, where)
        if warning:
            config.warnings.append(warning)


def _note_severity(config: MlviewConfig, code: str, value: Any, where: str) -> None:
    """A severity override is a **warning, not an error** (CFG-ONE).

    Severities are a property of the rule - `docs/ISSUE_RULES.md` pins them and
    the hosts map them to their own diagnostic levels - so an override cannot
    be honoured. Refusing the whole file over it would be worse: the `disable`
    list beside it is doing real work.
    """
    code = code.strip().upper()
    text = str(value).strip().lower()
    config.severity[code] = text
    if text not in SEVERITIES:
        config.warnings.append(
            "severity must be one of low, medium, high; the override %s = %r "
            "in %s was ignored" % (code, value, where))
        return
    config.warnings.append(
        "severities are fixed; the override %s = %r in %s was ignored"
        % (code, value, where))


def _paths_table(paths: Any, config: MlviewConfig) -> None:
    if not isinstance(paths, dict):
        return
    where = config.path or "the config"
    exclude = paths.get("exclude")
    if exclude is not None and not isinstance(exclude, (list, tuple)):
        config.warnings.append("[paths] exclude must be a list of globs; %r in "
                               "%s was ignored" % (exclude, where))
    config.excludes = _string_list(exclude)
    include = paths.get("include")
    if include is not None and not isinstance(include, (list, tuple)):
        config.warnings.append("[paths] include must be a list of globs; %r in "
                               "%s was ignored" % (include, where))
    config.includes = _string_list(include)
    if "notebooks" in paths:
        # NB. A bool, and anything else is a config_warning rather than a
        # silent truthiness read: `notebooks = "yes"` meaning False is the
        # shape CLEANUP 3 already refused to accept in silence.
        value = paths.get("notebooks")
        if isinstance(value, bool):
            config.notebooks = value
        else:
            config.warnings.append(
                "[paths] notebooks must be true or false; %r in %s was ignored"
                % (value, where))
    for key in sorted(paths):
        if key not in PATHS_KEYS:
            config.warnings.append("unknown key %s in [paths] of %s - it was "
                                   "ignored.%s" % (key, where, _near(key, PATHS_KEYS)))


def _analysis_table(analysis: Any, config: MlviewConfig) -> None:
    if not isinstance(analysis, dict):
        return
    where = config.path or "the config"
    for key in sorted(analysis):
        value = analysis[key]
        if key not in ANALYSIS_KEYS:
            config.warnings.append("unknown key %s in [analysis] of %s - it was "
                                   "ignored.%s" % (key, where, _near(key, ANALYSIS_KEYS)))
            continue
        problem = _analysis_value(key, value)
        if problem:
            config.warnings.append("[analysis] %s: %s in %s - it was ignored."
                                   % (key, problem, where))
            continue
        config.analysis[key] = value


def _analysis_value(key: str, value: Any) -> Optional[str]:
    """None when `value` is usable, else why it is not."""
    if key == "relevance":
        from .relevance import MODES
        if value not in MODES:
            return "must be one of %s, got %r" % (", ".join(MODES), value)
    elif key == "dataflow":
        # Deliberately not a hard-coded list: DATAFLOW-IP owns the mode names
        # and this table must not become a second copy of them.
        if not isinstance(value, str) or not value.strip():
            return "must be a mode name, got %r" % (value,)
    elif key in ("max_nodes", "relevance_hops"):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return "must be a non-negative integer, got %r" % (value,)
    elif key == "include_notebooks":
        if not isinstance(value, bool):
            return "must be true or false, got %r" % (value,)
    return None


def _baseline_table(baseline: Any, config: MlviewConfig, config_file: str) -> None:
    if not isinstance(baseline, dict):
        return
    where = config.path or "the config"
    for key in sorted(baseline):
        if key not in BASELINE_KEYS:
            config.warnings.append("unknown key %s in [baseline] of %s - it was "
                                   "ignored.%s" % (key, where, _near(key, BASELINE_KEYS)))
    value = baseline.get("path")
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        config.warnings.append("[baseline] path must be a file path; %r in %s "
                               "was ignored" % (value, where))
        return
    # Relative to the file that named it, so a checked-in config means the same
    # thing from any working directory.
    base = os.path.dirname(os.path.abspath(config_file))
    config.baseline_path = os.path.normpath(
        value if os.path.isabs(value) else os.path.join(base, value)).replace("\\", "/")


# ------------------------------------------------------------------- apply
def apply(options, config: MlviewConfig):
    """Merge the file's `[analysis]` and `[paths] include` into `options`.

    The stated precedence, in code: an option still equal to its
    `AnalyzeOptions` default is one the caller did not ask about, and the file
    may set it; anything else came from a flag or a host and wins. `include` is
    the exception in the other direction - it is *additive*, exactly as
    `exclude` has always been, because a filter that a file and a flag both
    narrow must end up narrower, never wider.

    Unknown fields are skipped rather than set, so a `[analysis]` key naming an
    option this build does not have (a newer file, an older analyzer) is inert
    instead of fatal.
    """
    if not isinstance(config, MlviewConfig):
        return options
    fields = {f.name: f for f in dataclasses.fields(type(options))}
    #: The names the caller set on purpose. "Equal to the dataclass default" is
    #: a *proxy* for "the caller did not ask", and it is wrong in exactly the
    #: case a host hits every run: `--max-nodes 400` and `--min-confidence 0.0`
    #: are the documented defaults, so a checked-in `.mlview.toml` won over a
    #: flag that had been typed. The CLI now records which options were typed.
    explicit = set(getattr(options, "explicit", ()) or ())
    changes: Dict[str, Any] = {}
    for key, value in sorted(config.analysis.items()):
        spec = fields.get(key)
        if spec is None or key in explicit:
            continue                        # the caller asked; the caller wins
        current = getattr(options, key, None)
        if current != _default_of(spec):
            continue                        # the caller asked; the caller wins
        changes[key] = value
    if (config.min_confidence is not None and "min_confidence" in fields
            and "min_confidence" not in explicit):
        if getattr(options, "min_confidence", 0.0) == _default_of(
                fields["min_confidence"]):
            changes["min_confidence"] = config.min_confidence
    if config.includes and "include" in fields:
        have = tuple(getattr(options, "include", ()) or ())
        extra = tuple(p for p in config.includes if p not in have)
        if extra:
            changes["include"] = have + extra
    if not changes:
        return options
    return dataclasses.replace(options, **changes)


def _default_of(spec) -> Any:
    if spec.default is not dataclasses.MISSING:
        return spec.default
    if spec.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
        return spec.default_factory()                    # type: ignore[misc]
    return dataclasses.MISSING


# -------------------------------------------------------------- mlview init
_HEADER = """\
# .mlview.toml - MLView configuration.
#
# Generated by `mlview init` (mlview %(version)s). Every key below is
# commented out, so this file changes nothing until you uncomment something.
#
# Precedence (CONTRACTS 11.37):
#   * this file is found as <root>/.mlview.toml, or as [tool.mlview] in
#     pyproject.toml when no .mlview.toml exists, and whichever was applied is
#     reported as `workspace.configPath`;
#   * `disable` and `exclude` belong to this file - a host (the VS Code
#     settings, the plugin) may add to them and can never take away from them;
#   * every [analysis] option here is overridden by the matching command-line
#     flag, because a flag is something a human typed just now.

[paths]
# Globs excluded from analysis, on top of the built-in .venv / site-packages /
# node_modules / build / .git defaults.
# exclude = ["experiments/**", "**/legacy/**"]
#
# When non-empty, the only files analyzed.
# include = ["src/**"]
#
# Analyze .ipynb notebooks too. Default false: notebooks are counted, skipped
# and reported, never silently ignored.
# notebooks = false

[analysis]
# "ml" (the default) builds the IR only for files within `relevance_hops`
# import hops of a framework import and says how many it set aside; "all"
# builds it for every discovered file.
# relevance = "ml"
# relevance_hops = 2
#
# Interprocedural dataflow depth. "local" is this release's default.
# dataflow = "local"
#
# Operation-node budget for the emitted document.
# max_nodes = 400
#
# The checked-in half of --include-notebooks; the same switch as
# [paths] notebooks, and either one turning it on is enough.
# include_notebooks = false

[baseline]
# Findings recorded here are still emitted, but excluded from the counts and
# from --fail-on. Relative paths are resolved against this file.
# path = ".mlview/baseline.json"

[rules]
# Findings below this confidence are dropped from the document.
# min_confidence = 0.0
#
# Codes listed here are suppressed: still emitted, with `suppressed: true`, so
# a UI can offer "show suppressed" - never silently deleted.
# disable = []
#
# An ALLOW-LIST. Leave it empty for every rule. When it is non-empty, every
# rule outside it is suppressed, and a code named in both lists stays off.
# enable = []
#
# Severities are FIXED. A [rules.severity] entry is reported as a config
# warning on the document and ignored - a severity is a property of the rule,
# not of the project reading it. To silence a rule, disable it above.
# [rules.severity]
# %(example)s = "low"
#
# The %(count)d rules this build registers, with the severity each ships at:
"""


def render_init(version: str = "") -> str:
    """The body of the file `mlview init` writes.

    Generated from the registry the way `tools/gen_rule_docs.py` works, so the
    rule table cannot drift from the rules: a rule added in a commit is in the
    file the next `mlview init` writes, with no second list to maintain.
    """
    from ..rules.registry import all_rules
    from ..version import __version__

    specs = list(all_rules())
    example = specs[0].code if specs else "MLV101"
    width = max([len(s.code) for s in specs] + [6])
    lines = [_HEADER % {"version": version or __version__, "example": example,
                        "count": len(specs)}]
    for spec in specs:
        lines.append("#   %-*s  %-6s  %s" % (width, spec.code, spec.severity,
                                             spec.title))
    lines.append("")
    return "\n".join(lines)
