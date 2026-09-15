"""ROB-18. Three characters in a source line and the HTML report renders blank.

`analyzer/src/mlview/emit/html_out.py:57` is

    return text.replace("</", "<\\/").replace("<!--", "<\\!--")

`<\\/` is the correct guard and is legal JSON (`\\/` is one of the seven JSON
escapes). `<\\!--` is not: `\\!` is **not** a JSON escape sequence, and the
block it lands in is declared `type="application/json"` and read back with

    JSON.parse(document.getElementById('mlview-graph').textContent)

so the parse throws, `MLView.mount` never runs, and the whole diagram is gone.
Everything outside the two script blocks of an asset-carrying report is the
`<h1>`, so what the reader gets is a page reading `MLView - <root>` and nothing
else. The CLI still prints `mlview: wrote report.html` and exits 0.

Reproduce::

    python -m mlview analyze <this directory> --html /tmp/r.html
    cd webview && node test/render_report.mjs /tmp/r.html
    #  SyntaxError: Bad escaped character in JSON at position 1938

Any source line carrying `<!--` that becomes a node's `symbol` or `snippet`
does it: an HTML template in a string, a Jinja fragment, a docstring with
markup, a wandb `<!--- @wandbcode{...} -->` marker in a notebook cell.

Both a string literal (line 32) and a trailing comment (line 40) are here so
the fixture keeps reproducing if one of the two stops anchoring a node.
"""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

TEMPLATE = "<!-- report goes here -->"


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)   # <!-- keep the marker
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
