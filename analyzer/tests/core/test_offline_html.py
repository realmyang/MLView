"""The standalone report is self-contained and offline (R0.3, amendment A4)."""

from __future__ import annotations

import json
import os
import re

import pytest

from mlview.api import AnalyzeOptions, analyze_to_dict, render_html
from mlview.emit import html_out

FORBIDDEN = ("http://", "https://", "//cdn", "@import")
EXTERNAL_LINK = re.compile(r"<link[^>]+href\s*=\s*[\"'](?!#)", re.IGNORECASE)
EXTERNAL_SCRIPT = re.compile(r"<script[^>]+src\s*=", re.IGNORECASE)

SRC = {
    "train.py": ("import torch\n"
                 "import torch.nn as nn\n"
                 "import torch.optim as optim\n"
                 "from torch.utils.data import DataLoader\n\n\n"
                 "def train(ds):\n"
                 "    model = nn.Linear(4, 2)\n"
                 "    crit = nn.CrossEntropyLoss()\n"
                 "    opt = optim.Adam(model.parameters())\n"
                 "    loader = DataLoader(ds, batch_size=8)\n"
                 "    for x, y in loader:\n"
                 "        loss = crit(model(x), y)\n"
                 "        loss.backward()\n"
                 "        opt.step()\n"),
}


@pytest.fixture
def report(tmp_path, analyze_ws):
    doc = analyze_ws(SRC)
    path = render_html(doc, str(tmp_path / "report.html"))
    with open(path, encoding="utf-8") as fh:
        return doc, fh.read()


def test_no_external_references(report):
    _doc, html = report
    for needle in FORBIDDEN:
        assert needle not in html, "report references %s" % needle
    assert not EXTERNAL_LINK.search(html)
    assert not EXTERNAL_SCRIPT.search(html)


def test_fallback_banner_when_the_bundle_is_missing(report):
    _doc, html = report
    if html_out.assets_present():
        pytest.skip("viewer bundle is synced; the fallback path is not exercised")
    assert "viewer bundle not synced" in html.lower()
    assert "<table" in html


def test_graph_is_embedded_and_escaped(report):
    doc, html = report
    assert 'id="mlview-graph"' in html
    assert "</script>" in html
    assert "</" not in html.split('id="mlview-graph"')[1].split("</script>")[0]
    assert doc["workspace"]["root"].split("/")[-1] in html


def test_untrusted_source_is_escaped(tmp_path, analyze_ws):
    """Hostile source text can neither break out of the JSON block nor become markup.

    Two separate mechanisms, asserted separately (amendment A4):

    * the embedded graph rides in `<script type="application/json">`, where the
      only exits are `</` and `<!--` - both escaped, so the payload stays inert
      text no matter what it contains;
    * every value the fallback report renders as markup goes through
      `html.escape`, so `<` never reaches the document as a tag.
    """
    doc = analyze_ws({"x.py": ('import torch\n'
                               '# <script>alert("xss")</script>\n'
                               'name = "</script><img src=x onerror=alert(1)>"\n'
                               'device = torch.device("cpu")\n')})
    path = render_html(doc, str(tmp_path / "r.html"))
    with open(path, encoding="utf-8") as fh:
        html = fh.read()

    # 1. the payload survived into the document at all (otherwise this proves nothing)
    assert "img src=x onerror" in html

    # 2. it cannot escape the JSON script element
    block = html.split('id="mlview-graph"', 1)[1].split(">", 1)[1].split("</script>", 1)[0]
    assert "img src=x onerror" in block
    assert "</" not in block
    assert "<!--" not in block
    assert "<script" not in block.lower()
    assert json.loads(block.replace("<\\/", "</").replace("<\\!--", "<!--"))["nodes"]

    # 3. outside that block nothing hostile is markup
    outside = html.replace(block, "")
    assert "<img" not in outside
    assert "<script>alert" not in outside


def test_fallback_table_escapes_every_rendered_value(tmp_path, analyze_ws):
    """Whatever the fallback table renders as markup is `html.escape`d first."""
    if html_out.assets_present():
        pytest.skip("viewer bundle is synced; the fallback table is not rendered")
    doc = analyze_ws({"x.py": "import torch\ndevice = torch.device('cpu')\n"})
    hostile = '<img src=x onerror=alert(1)>'
    doc["nodes"][0]["label"] = hostile
    doc["workspace"]["frameworks"] = [hostile]
    doc["diagnostics"] = [{"kind": "config_warning", "message": hostile}]
    path = render_html(doc, str(tmp_path / "hostile.html"))
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    block = html.split('id="mlview-graph"', 1)[1].split(">", 1)[1].split("</script>", 1)[0]
    body = html.replace(block, "")
    assert "&lt;img src=x onerror=alert(1)&gt;" in body
    assert "<img" not in body


def test_report_opens_as_a_single_file(report, tmp_path):
    _doc, html = report
    assert html.startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")
    assert len(html) > 500


def test_deep_links_use_the_vscode_scheme(report):
    doc, html = report
    if not html_out.assets_present():
        assert "vscode://file/" in html
