"""Generate `docs/rules/<CODE>.md` (and its index) from the rule registry.

    PYTHONUTF8=1 python analyzer/tools/gen_rule_docs.py [--check] [--out DIR]

Every `Issue.docs` field points at `docs/rules/<CODE>.md`, so these pages are
the offline documentation both hosts deep-link to. They are generated, never
hand-edited: the title, severity, frameworks, prior, tags, fix hint and the
bad/good examples all come from the `@rule` declaration and the two fixtures,
so a page can never drift from the rule it documents.

`--check` exits 1 when anything on disk differs, which is what CI wants.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(REPO, "analyzer", "src")
for _path in (SRC, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from mlview.rules.fixes import FIX_DOCS  # noqa: E402
from mlview.rules.registry import RuleSpec, all_rules  # noqa: E402

FIXTURES = os.path.join(REPO, "analyzer", "tests", "fixtures", "rules")
DOCS = os.path.join(REPO, "docs", "rules")

#: Hand-written context per rule; see `gen_rule_notes.py`.
from gen_rule_notes import NOTES  # noqa: E402


_SEVERITY_BLURB = {
    "high": "red octagon - very likely a real defect that silently corrupts results "
            "or crashes",
    "medium": "amber triangle - likely wrong, or right only under an assumption that "
              "cannot be checked statically",
    "low": "blue circle - hygiene, reproducibility, portability, or a question worth "
           "asking",
}


def _read(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def _fixture(code: str, kind: str) -> Tuple[Optional[str], str]:
    name = "%s_%s.py" % (code, kind)
    return _read(os.path.join(FIXTURES, name)), name


def _body(text: Optional[str]) -> str:
    """The fixture without its MLVIEW-EXPECT header lines."""
    if text is None:
        return ""
    lines = [l for l in text.splitlines()
             if not l.lstrip().startswith("# MLVIEW-EXPECT")]
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines).rstrip()


def _bullets(items) -> str:
    return "\n".join("- %s" % item for item in items)


def page(spec: RuleSpec) -> str:
    notes = NOTES.get(spec.code, {})
    bad, bad_name = _fixture(spec.code, "bad")
    good, good_name = _fixture(spec.code, "good")
    frameworks = ", ".join(spec.frameworks) if spec.frameworks else "any"
    tags = ", ".join("`%s`" % t for t in spec.tags) if spec.tags else "-"

    out: List[str] = []
    out.append("# %s - %s\n" % (spec.code, spec.title or spec.code))
    if not spec.enabled:
        out.append("> **Disabled in this build.** %s\n"
                   % (notes.get("disabled_reason")
                      or "It could not be made reliable enough to ship on."))
    out.append("| | |")
    out.append("|---|---|")
    out.append("| **Severity** | `%s` - %s |"
               % (spec.severity, _SEVERITY_BLURB.get(spec.severity, "")))
    out.append("| **Frameworks** | %s |" % frameworks)
    out.append("| **Base prior** | %.2f |" % spec.base_prior)
    out.append("| **Rule version** | %d |" % spec.rule_version)
    out.append("| **Tags** | %s |" % tags)
    out.append("| **Absence rule** | %s |"
               % ("yes - severity is capped at `medium` unless the enclosing construct "
                  "resolved statically and no framework wrapper was detected"
                  if spec.absence else "no"))
    out.append("| **Enabled** | %s |" % ("yes" if spec.enabled else "**no**"))
    out.append("")

    if spec.why:
        out.append("## Why it matters\n")
        out.append(spec.why + "\n")

    detects = notes.get("detects")
    if detects:
        out.append("## How it is detected\n")
        out.append(str(detects) + "\n")

    if notes.get("ghost"):
        out.append("## What you see\n")
        out.append("When this fires, %s (a **ghost node**). Showing the hole beats "
                   "narrating it.\n" % notes["ghost"])
    elif notes.get("rendering"):
        out.append("## What you see\n")
        out.append("When this fires, %s\n" % notes["rendering"])

    avoids = notes.get("avoids")
    if avoids:
        out.append("## False positives it avoids\n")
        out.append(_bullets(avoids) + "\n")

    # ROADMAP "the framing to carry forward": a rule that stays silent where it
    # is blind has to say so, or silence reads as a clean bill of health.
    cannot = notes.get("cannot")
    if cannot:
        out.append("## What it cannot analyze\n")
        out.append(str(cannot) + "\n")

    out.append("## How to fix it\n")
    out.append((spec.fix_hint or "See the rule catalog.") + "\n")

    # H5. The page a host deep-links to is where "the lightbulb is empty here"
    # has to be answerable, so the withheld condition is rendered beside the
    # offered one rather than only in the amendment.
    structured = FIX_DOCS.get(spec.code)
    if structured:
        out.append("## Structured fix\n")
        out.append("This rule opts into `Issue.fix` (H5, CONTRACTS 11.42). A host may "
                   "offer **%s** as a quick fix, graded `%s`. The edit is computed from "
                   "the AST, it is **never applied automatically**, and no edit is "
                   "offered at all when the finding lands below the `likely` confidence "
                   "bucket.\n" % (structured["title"], structured["safety"]))
        out.append("- **Offered when** %s" % structured["offered"])
        out.append("- **Withheld when** %s\n" % structured["withheld"])

    if bad is not None:
        out.append("## Example that fires\n")
        out.append("`analyzer/tests/fixtures/rules/%s`\n" % bad_name)
        out.append("```python\n%s\n```\n" % _body(bad))
    if good is not None:
        out.append("## Example that does not\n")
        out.append("`analyzer/tests/fixtures/rules/%s` - the nearest false-positive "
                   "trap this rule has to survive.\n" % good_name)
        out.append("```python\n%s\n```\n" % _body(good))

    out.append("## Suppressing it\n")
    out.append("```python\nresult = risky_call()  # mlview: ignore[%s]\n```\n"
               % spec.code)
    out.append("Or `# mlview: ignore-file` in the first five lines of the file, or\n"
               "`.mlview.toml`:\n")
    out.append("```toml\n[rules]\ndisable = [\"%s\"]\n```\n" % spec.code)
    out.append("A suppressed issue is still emitted with `suppressed: true`, so the "
               "viewer can offer \"show suppressed\"; hosts never publish it as an "
               "editor diagnostic.\n")
    out.append("---\n")
    out.append("*Generated by `analyzer/tools/gen_rule_docs.py` from the rule registry "
               "and the fixtures - do not edit by hand.*")
    return "\n".join(out) + "\n"


def index(specs: List[RuleSpec]) -> str:
    counts = {"high": 0, "medium": 0, "low": 0}
    for spec in specs:
        counts[spec.severity] = counts.get(spec.severity, 0) + 1
    out: List[str] = []
    out.append("# MLView rule documentation\n")
    out.append("One page per registered rule, generated from the registry and the "
               "per-rule fixtures. Every `Issue.docs` field points here, and both "
               "hosts deep-link to these pages offline.\n")
    out.append("**%d rules** - %d high, %d medium, %d low.\n"
               % (len(specs), counts["high"], counts["medium"], counts["low"]))
    out.append("| Code | Sev | Title | Frameworks | Prior | Absence | Enabled |")
    out.append("|---|---|---|---|---|---|---|")
    for spec in specs:
        out.append("| [%s](%s.md) | %s | %s | %s | %.2f | %s | %s |"
                   % (spec.code, spec.code, spec.severity, spec.title or spec.code,
                      ", ".join(spec.frameworks) if spec.frameworks else "any",
                      spec.base_prior, "yes" if spec.absence else "-",
                      "yes" if spec.enabled else "**no**"))
    out.append("")
    out.append("## Reading a page\n")
    out.append("- **How it is detected** is the real algorithm, not a restatement of "
               "the title.")
    out.append("- **False positives it avoids** is traceable: each bullet is a case "
               "the `_good.py` fixture or the rule body actually handles.")
    out.append("- **Example that fires / does not** are the two shipped fixtures "
               "verbatim, so the page cannot drift from the test suite.\n")
    out.append("Regenerate with:\n")
    out.append("```bash\nPYTHONUTF8=1 python analyzer/tools/gen_rule_docs.py\n```\n")
    out.append("`--check` exits 1 when anything on disk is out of date.\n")
    return "\n".join(out) + "\n"


def build(out_dir: str = DOCS) -> Dict[str, str]:
    """`{relative filename: content}` for every page plus the index."""
    specs = all_rules()
    pages = {"README.md": index(specs)}
    for spec in specs:
        pages["%s.md" % spec.code] = page(spec)
    return pages


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any page on disk is out of date")
    parser.add_argument("--out", default=DOCS, help="output directory")
    args = parser.parse_args(argv)

    pages = build(args.out)
    if args.check:
        stale = []
        for name, text in sorted(pages.items()):
            current = _read(os.path.join(args.out, name))
            if current != text:
                stale.append(name)
        extra = []
        if os.path.isdir(args.out):
            for name in sorted(os.listdir(args.out)):
                if name.endswith(".md") and name not in pages:
                    extra.append(name)
        if stale or extra:
            sys.stderr.write("docs/rules is out of date: %s\n"
                             % ", ".join(stale + ["%s (orphan)" % e for e in extra]))
            return 1
        sys.stderr.write("docs/rules is current (%d pages)\n" % len(pages))
        return 0

    os.makedirs(args.out, exist_ok=True)
    for name, text in sorted(pages.items()):
        io.open(os.path.join(args.out, name), "w", encoding="utf-8",
                newline="\n").write(text)
    sys.stderr.write("wrote %d pages to %s\n"
                     % (len(pages), args.out.replace("\\", "/")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
