"""BUILD-01: amendment A4's 100 KB - 2 MB band, enforced at runtime.

The band was checked only over the *demo* artifacts in `scripts/e2e`, so a real
1000-node report shipped at **2.13 MB** and a 2000-node one at 3.53 MB, both
silently out of contract. `write_html` now measures what it just wrote and says
so on stderr, naming `--max-nodes` as the lever.

The fallback report - the plain table emitted when the viewer bundle has not
been synced - is exempt: A4 words the band "when the bundle is present", and a
few-kilobyte table is the correct output in that state, not a violation.
"""

from __future__ import annotations

import os

import pytest

from mlview.api import AnalyzeOptions, analyze_to_dict
from mlview.emit import html_out

#: 180 of these modules emit a ~2.5 MB report - past A4's ceiling, and
#: roughly the 1000-node project the audit measured at 2.13 MB.
MODULES = 180

TRAIN = ("import torch\n"
         "import torch.nn as nn\n"
         "import torch.optim as optim\n"
         "from torch.utils.data import DataLoader\n\n\n"
         "def train_%d(ds):\n"
         "    model = nn.Linear(4, 2)\n"
         "    crit = nn.CrossEntropyLoss()\n"
         "    opt = optim.Adam(model.parameters())\n"
         "    loader = DataLoader(ds, batch_size=8)\n"
         "    for x, y in loader:\n"
         "        opt.zero_grad()\n"
         "        loss = crit(model(x), y)\n"
         "        loss.backward()\n"
         "        opt.step()\n")


def test_the_band_matches_amendment_a4():
    assert html_out.A4_MIN_BYTES == 100 * 1024
    assert html_out.A4_MAX_BYTES == 2 * 1024 * 1024


# --------------------------------------------------------------- pure check
def test_an_in_band_report_is_silent():
    assert html_out.size_band_warning(500 * 1024, nodes=45) is None


def test_an_oversized_report_names_the_lever():
    warning = html_out.size_band_warning(3 * 1024 * 1024, nodes=2000)
    assert warning is not None
    assert "--max-nodes" in warning
    assert "2 MB" in warning and "2000 nodes" in warning


def test_an_undersized_report_points_at_the_assets():
    warning = html_out.size_band_warning(4096, nodes=45)
    assert warning is not None
    assert "100 KB" in warning
    assert "sync-assets" in warning


def test_the_fallback_report_is_exempt():
    """A4 words the band "when the bundle is present"."""
    assert html_out.size_band_warning(4096, nodes=45, bundle_present=False) is None
    assert html_out.size_band_warning(9 * 1024 * 1024, nodes=9999,
                                      bundle_present=False) is None


# ---------------------------------------------------------------- end to end
@pytest.mark.skipif(not html_out.assets_present(),
                    reason="viewer bundle not synced; the band does not apply")
def test_a_normal_report_is_written_without_a_warning(tmp_path, capsys):
    doc = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "samples", "vision_pipeline"),)))
    target = str(tmp_path / "report.html")
    html_out.write_html(doc, target)
    err = capsys.readouterr().err
    assert "amendment A4" not in err
    size = os.path.getsize(target)
    assert html_out.A4_MIN_BYTES <= size <= html_out.A4_MAX_BYTES


@pytest.mark.skipif(not html_out.assets_present(),
                    reason="viewer bundle not synced; the band does not apply")
def test_an_oversized_report_warns_on_stderr_and_is_still_written(
        tmp_path, make_workspace, capsys):
    """The warning is advice, not a refusal: the file is still there."""
    doc = analyze_to_dict(AnalyzeOptions(
        paths=(make_workspace({"m%03d.py" % n: TRAIN % n for n in range(MODULES)}),),
        max_files=4000, max_nodes=100000))
    assert doc["stats"]["nodes"] > 1000
    target = str(tmp_path / "big.html")
    path = html_out.write_html(doc, target)
    err = capsys.readouterr().err
    assert "over amendment A4's 2 MB ceiling" in err, (err, os.path.getsize(target))
    assert "--max-nodes" in err
    assert os.path.isfile(path.replace("/", os.sep))
    assert os.path.getsize(target) > html_out.A4_MAX_BYTES


@pytest.mark.skipif(not html_out.assets_present(),
                    reason="viewer bundle not synced; the band does not apply")
def test_lowering_max_nodes_brings_the_same_workspace_back_in_band(
        tmp_path, make_workspace, capsys):
    root = make_workspace({"m%03d.py" % n: TRAIN % n for n in range(MODULES)})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), max_files=4000, max_nodes=400))
    target = str(tmp_path / "capped.html")
    html_out.write_html(doc, target)
    assert "amendment A4" not in capsys.readouterr().err
    assert os.path.getsize(target) <= html_out.A4_MAX_BYTES
