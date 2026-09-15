"""The self-contained HTML report (CONTRACTS amendment A4).

One file, zero external references: the viewer CSS and JS are inlined from
`emit/assets/`, the graph rides in a `<script type="application/json">` block,
and a three-line bootstrap mounts the viewer.

When the assets have not been synced yet the report still renders - a plain
HTML table of stages, nodes and issues - behind a visible
*"viewer bundle not synced"* banner.

Every interpolated string is HTML-escaped: file paths, identifiers and code
snippets come from an untrusted repository.
"""

from __future__ import annotations

import html
import os
from typing import Any, Dict, List, Optional

__all__ = ["render_html", "write_html", "assets_present", "ASSET_DIR",
           "A4_MIN_BYTES", "A4_MAX_BYTES", "size_band_warning"]

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_JS = os.path.join(ASSET_DIR, "mlview.js")
_CSS = os.path.join(ASSET_DIR, "mlview.css")

_SEVERITY_GLYPH = {"high": "!!", "medium": "!", "low": "i"}

#: CONTRACTS amendment A4: "Size band: 100 KB - 2 MB when the bundle is
#: present." It was checked only over the *demo* artifacts in `scripts/e2e`,
#: so a real 1000-node report shipped at 2.13 MB - silently out of contract.
#: BUILD-01 moves the check here, where every report passes through.
A4_MIN_BYTES = 100 * 1024
A4_MAX_BYTES = 2 * 1024 * 1024


def assets_present() -> bool:
    return os.path.isfile(_JS)


def _read(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _json_block(doc: Dict[str, Any]) -> str:
    """The graph as JSON that is safe inside `<script type="application/json">`.

    Two byte sequences must never reach the HTML tokenizer intact: `</`, which
    could close the block early, and `<!--`, which opens a comment state. Both
    are escaped **with sequences JSON itself defines** - `\\/` is one of JSON's
    seven escapes, and `\\u0021` is the `!`. `\\!` is not a JSON escape, and the
    report's own bootstrap reads this block back with `JSON.parse(...)`: a
    single `<!--` anywhere in a source line therefore used to throw
    `SyntaxError: Bad escaped character in JSON`, `MLView.mount` never ran, and
    the reader got a blank page while the CLI still exited 0 (ROB-18).
    """
    import json
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/").replace("<!--", "<\\u0021--")


def _link(loc: Dict[str, Any]) -> str:
    if not loc:
        return ""
    target = "vscode://file/%s:%s:%s" % (loc.get("absFile", ""), loc.get("line", 1),
                                         int(loc.get("col", 0)) + 1)
    label = "%s:%s" % (loc.get("file", "?"), loc.get("line", "?"))
    return '<a class="loc" href="%s" title="open in VS Code">%s</a>' % (_esc(target), _esc(label))


_FALLBACK_CSS = """
:root { color-scheme: light dark;
  --bg:#ffffff; --fg:#1f2328; --muted:#6b7280; --line:#d0d7de; --card:#f6f8fa;
  --high:#cf222e; --medium:#bf8700; --low:#0969da; --accent:#0969da; }
@media (prefers-color-scheme: dark) { :root {
  --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --line:#30363d; --card:#161b22;
  --high:#ff7b72; --medium:#e3b341; --low:#79c0ff; --accent:#79c0ff; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.5 ui-sans-serif,
  -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 20px 64px; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 28px 0 8px; text-transform: uppercase;
     letter-spacing: .06em; color: var(--muted); }
.banner { border:1px solid var(--medium); border-left-width:4px; background:var(--card);
  padding:10px 14px; border-radius:6px; margin:16px 0; }
.meta { color: var(--muted); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line);
  vertical-align: top; }
th { color: var(--muted); font-weight:600; }
tr:last-child td { border-bottom: none; }
code, .mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size:12px; }
.badge { display:inline-block; min-width:22px; text-align:center; border-radius:10px;
  padding:0 6px; font-size:11px; font-weight:700; color:#fff; }
.badge.high { background: var(--high); }
.badge.medium { background: var(--medium); }
.badge.low { background: var(--low); }
.chip { display:inline-block; border:1px solid var(--line); border-radius:999px;
  padding:1px 10px; margin:0 6px 6px 0; font-size:12px; color:var(--muted); }
a.loc { color: var(--accent); text-decoration: none; }
a.loc:hover { text-decoration: underline; }
.ghost td:first-child::after { content:" · missing"; color: var(--muted); }
.issue .why, .issue .fix { color: var(--muted); }
"""


def _fallback_body(doc: Dict[str, Any]) -> str:
    ws = doc.get("workspace", {})
    stats = doc.get("stats", {})
    counts = stats.get("issues", {})
    out: List[str] = []
    out.append('<main><h1>MLView report</h1>')
    out.append('<p class="meta mono">%s</p>' % _esc(ws.get("root", "")))
    out.append('<div class="banner"><strong>Viewer bundle not synced.</strong> '
               'This is the plain-HTML fallback report. Run '
               '<code>scripts/build.ps1</code> (or <code>tools/sync-assets.py</code>) '
               'to embed the interactive diagram.</div>')
    out.append('<p class="meta">%s files analyzed · %s failed · %s notebooks skipped · '
               '%s nodes · %s edges</p>'
               % (_esc(ws.get("filesAnalyzed", 0)), _esc(ws.get("filesFailed", 0)),
                  _esc(ws.get("notebooksSkipped", 0)), _esc(stats.get("nodes", 0)),
                  _esc(stats.get("edges", 0))))
    out.append("<p>" + "".join('<span class="chip">%s</span>' % _esc(f)
                               for f in ws.get("frameworks") or ["no framework detected"])
               + "</p>")

    out.append("<h2>Stages</h2><table><tr><th>Stage</th><th>Nodes</th>"
               "<th>Issues</th><th>Max severity</th></tr>")
    for stage in doc.get("stages", []):
        if not stage.get("present"):
            continue
        ic = stage.get("issueCounts", {})
        badges = "".join('<span class="badge %s">%s</span> ' % (sev, ic.get(sev, 0))
                         for sev in ("high", "medium", "low") if ic.get(sev))
        out.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                   % (_esc(stage["label"]), _esc(stage.get("nodeCount", 0)), badges or "—",
                      _esc(stage.get("maxSeverity") or "—")))
    out.append("</table>")
    absent = [s["id"] for s in doc.get("stages", []) if not s.get("present")]
    if absent:
        out.append('<p class="meta">Not detected: %s</p>' % _esc(", ".join(absent)))

    issues = doc.get("issues", [])
    out.append("<h2>Issues (%d)</h2>" % len([i for i in issues if not i.get("suppressed")]))
    if issues:
        out.append("<table><tr><th>Sev</th><th>Code</th><th>Confidence</th>"
                   "<th>Location</th><th>Finding</th></tr>")
        for issue in issues:
            severity = issue.get("severity", "low")
            out.append('<tr class="issue"><td><span class="badge %s">%s</span></td>'
                       "<td class=\"mono\">%s</td><td>%s</td><td>%s</td>"
                       "<td><strong>%s</strong><br>%s<br>"
                       '<span class="why">Why: %s</span><br>'
                       '<span class="fix">Fix: %s</span>%s</td></tr>'
                       % (severity, _SEVERITY_GLYPH.get(severity, "i"),
                          _esc(issue.get("code")), _esc(issue.get("confidenceBucket")),
                          _link(issue.get("loc", {})), _esc(issue.get("title")),
                          _esc(issue.get("message")), _esc(issue.get("why")),
                          _esc(issue.get("fixHint")),
                          "".join('<br><span class="meta">%s → %s</span>'
                                  % (_esc(r.get("role")), _link(r))
                                  for r in issue.get("relatedLocs") or [])))
        out.append("</table>")
    else:
        out.append('<p class="meta">No issues found.</p>')

    out.append("<h2>Nodes (%d)</h2><table><tr><th>Label</th><th>Kind</th><th>Level</th>"
               "<th>Stage</th><th>Location</th></tr>" % len(doc.get("nodes", [])))
    for node in doc.get("nodes", []):
        classes = "ghost" if node.get("ghost") else ""
        out.append('<tr class="%s"><td>%s</td><td class="mono">%s</td><td>%s</td>'
                   "<td>%s</td><td>%s</td></tr>"
                   % (classes, _esc(node.get("label")), _esc(node.get("kind")),
                      _esc(node.get("level")), _esc(node.get("stage")),
                      _link(node.get("loc", {}))))
    out.append("</table>")

    diagnostics = doc.get("diagnostics") or []
    if diagnostics:
        out.append("<h2>Notes</h2><ul>")
        for diagnostic in diagnostics:
            out.append("<li><code>%s</code> %s</li>"
                       % (_esc(diagnostic.get("kind")), _esc(diagnostic.get("message"))))
        out.append("</ul>")
    out.append("</main>")
    return "".join(out)


def _root_attrs(scope: Optional[str], depth: Optional[int]) -> str:
    """`data-mlview-scope` / `data-mlview-depth` (CONTRACTS 11.8).

    The report always embeds the **full** graph and lets the viewer project
    it, so `view` keeps meaning exactly one thing - *this document is the
    projection* - and `mount()` keeps its frozen three-argument signature.
    """
    if not scope:
        return ""
    out = ' data-mlview-scope="%s"' % _esc(scope)
    if depth is not None:
        out += ' data-mlview-depth="%s"' % _esc(int(depth))
    return out


def render_html(doc: Dict[str, Any], scope: Optional[str] = None,
                depth: Optional[int] = None) -> str:
    """The complete self-contained report as one HTML string."""
    css = _read(_CSS) or ""
    js = _read(_JS)
    root = doc.get("workspace", {}).get("root", "")
    title = "MLView — %s" % (root.rstrip("/").split("/")[-1] or "workspace")
    head = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>%s</title>" % _esc(title),
        "<style>%s</style>" % (css if js else _FALLBACK_CSS),
        "</head>",
        "<body>",
    ]
    body: List[str] = []
    attrs = _root_attrs(scope, depth)
    if js:
        body.append('<div id="mlview-root"%s></div>' % attrs)
        body.append('<script id="mlview-graph" type="application/json">%s</script>'
                    % _json_block(doc))
        body.append("<script>%s</script>" % js)
        body.append(
            "<script>MLView.mount(document.getElementById('mlview-root'),"
            "JSON.parse(document.getElementById('mlview-graph').textContent),"
            "MLView.bridges.standalone({theme:'auto'}));</script>")
    else:
        if attrs:
            # No bundle to project with, but the scope must still be visible to
            # whoever reads the file - and to the viewer once it is synced.
            body.append('<div id="mlview-root"%s hidden></div>' % attrs)
        body.append(_fallback_body(doc))
        body.append('<script id="mlview-graph" type="application/json">%s</script>'
                    % _json_block(doc))
    return "\n".join(head + body + ["</body>", "</html>", ""])


def size_band_warning(size: int, nodes: int = 0,
                      bundle_present: bool = True) -> Optional[str]:
    """The A4 band check, as a pure function so it is testable without a file.

    Returns None when the report is in band - or when the viewer bundle is
    absent, because the fallback report is a plain table that is *legitimately*
    a few kilobytes and the band is contracted "when the bundle is present".
    """
    if not bundle_present:
        return None
    if size > A4_MAX_BYTES:
        return ("mlview: report is %.2f MB, over amendment A4's 2 MB ceiling "
                "(%d nodes). Lower --max-nodes, or narrow the analyzed path, "
                "so the report stays loadable." % (size / 1048576.0, nodes))
    if size < A4_MIN_BYTES:
        return ("mlview: report is %d bytes, under amendment A4's 100 KB floor "
                "- the viewer bundle inlines to far more than that, so the "
                "report is probably truncated or the assets are stale. Re-run "
                "tools/sync-assets.py." % size)
    return None


def write_html(doc: Dict[str, Any], path: str, scope: Optional[str] = None,
               depth: Optional[int] = None) -> str:
    """Write the report; returns the absolute, forward-slashed path.

    BUILD-01: the A4 size band is enforced **here**, at runtime, rather than
    only over the demo artifacts in `scripts/e2e` - so the contract holds for
    the 1000-node report a real user emits, not just for the sample.
    """
    from .text_out import write_stderr

    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    text = render_html(doc, scope=scope, depth=depth)
    with open(abs_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    warning = size_band_warning(len(text.encode("utf-8")),
                                nodes=len(doc.get("nodes") or ()),
                                bundle_present=assets_present())
    if warning:
        write_stderr(warning)
    return abs_path.replace("\\", "/")
