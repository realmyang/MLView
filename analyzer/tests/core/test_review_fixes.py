"""Regression gates for the Sprint 5 review findings the analyzer owned.

One test per confirmed finding, each written so that it fails on the code as it
was rather than on an incidental detail of the fix:

* **REV5-01** MLV101 matched a split in *any* function of the module against a
  fit in any other, by name, and published it `high` / `certain` with prose
  that contradicted itself ("fitted at line 15, before the split at line 8").
* **IP-02** `--dataflow ip` then dropped the genuine cross-object case in
  silence, where `--dataflow local` had at least recorded a coverage gap.
* **ANA-01** a `reshuffle_each_iteration=` the analyzer could not read took the
  same path as one that was never written, so MLV121 published, at `high` /
  `certain`, an evidence entry denying the line it points at.
* **ANA-03** MLV110 never resolved the `shuffle=` expression, so it said
  "shuffle=unset" above a snippet reading `shuffle=config.shuffle` - and fired
  on correct code whose literal the analyzer already held.
* **ANA-02** a `CFG["workers"] = 0` did not invalidate the leaf ANA-10 had
  materialised from the dict literal two lines above it.
* **ANA-04** `args = get_args()` was not a config root, so the commonest
  argparse shape in the world resolved to nothing and was not even de-rated.
* **REV5-04** ANA-10's caps abandoned a resolution with no record anywhere.
* **IP-03** one `np.asarray()` dropped the data tag entirely.
* **ANA-05** the config de-rating evidence led with whichever key sorted first.
* **CFG-CONFIG-WARNING-DROPPED** an explicit `--config` naming a pyproject with
  no `[tool.mlview]` table applied nothing and said nothing.
"""

from __future__ import annotations

import os
import sys

import pytest

from core_support import REPO_ROOT, validate, write_files
from mlview.api import AnalyzeOptions, analyze_full, analyze_to_dict


def analyze(root, **kwargs):
    return analyze_to_dict(AnalyzeOptions(paths=(root,), **kwargs))


def codes(doc, code=None):
    return [i for i in doc["issues"]
            if (code is None or i["code"] == code) and not i.get("suppressed")]


def one(doc, code):
    found = codes(doc, code)
    assert len(found) == 1, [(i["code"], i["loc"]["line"]) for i in doc["issues"]]
    return found[0]


def kinds(doc, kind):
    return [d for d in doc["diagnostics"] if d["kind"] == kind]


def evidence(issue, kind):
    return [e for e in issue["evidence"] if e["kind"] == kind]


# ---------------------------------------------------------------- REV5-01
_TWO_SCOPES = '''import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split


def prepare():
    features = pd.read_csv("a.csv")
    X_train, X_test = train_test_split(features, test_size=0.2)
    return X_train, X_test


def describe():
    features = pd.read_csv("b.csv")
    scaler = StandardScaler()
    stats = scaler.fit_transform(features)
    return stats
'''


@pytest.mark.parametrize("mode", ("local", "ip"))
def test_mlv101_never_matches_a_split_in_another_function(tmp_path, mode):
    """REV5-01. `describe()` never splits anything and `prepare()` splits before
    any fit; the two share only the local name `features`."""
    root = write_files(str(tmp_path), {"leak.py": _TWO_SCOPES})
    doc = analyze(root, dataflow=mode)
    assert codes(doc, "MLV101") == [], [i["message"] for i in codes(doc, "MLV101")]
    assert validate(doc) == []


def test_mlv101_still_fires_inside_one_scope(tmp_path):
    """The guard must not cost the finding it was written around."""
    root = write_files(str(tmp_path), {"leak.py": '''import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split


def main():
    features = pd.read_csv("a.csv")
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)
    return train_test_split(scaled, test_size=0.2)
'''})
    issue = one(analyze(root), "MLV101")
    assert issue["severity"] == "high"
    assert issue["confidenceBucket"] == "certain"


def test_no_finding_ever_says_before_a_line_that_is_earlier(tmp_path):
    """The self-contradiction the false positive printed: a message claiming a
    fit happens *before* a split written on an earlier line."""
    root = write_files(str(tmp_path), {"leak.py": _TWO_SCOPES})
    for mode in ("local", "ip"):
        for issue in analyze(root, dataflow=mode)["issues"]:
            for related in issue["relatedLocs"]:
                if related["role"] != "split_site":
                    continue
                assert related["line"] >= issue["loc"]["line"], issue["message"]


# ------------------------------------------------------------------ IP-02
_ONESITE = {
    "prep.py": '''from sklearn.preprocessing import StandardScaler


class Scaled:
    def __init__(self, rows):
        self.rows = rows
        self.scaler = StandardScaler()

    def run(self):
        return self.scaler.fit_transform(self.rows)
''',
    "main.py": '''import pandas as pd
from sklearn.model_selection import train_test_split

from prep import Scaled

COLUMNS = ["age", "income"]


def leaky(csv_path="data/a.csv"):
    frame = pd.read_csv(csv_path)
    X = frame[COLUMNS].to_numpy()
    y = frame["churned"].to_numpy()
    obj = Scaled(X)
    Xs = obj.run()
    return train_test_split(Xs, y, random_state=1)
''',
}


def test_ip_is_never_quieter_than_local_about_a_cross_scope_match(tmp_path):
    """IP-02, and R5's answer to it.

    `local` records an `untagged_dataflow` gap here and must go on doing so.
    `ip` used to resolve the tag through the constructor, refuse the
    cross-scope match and say nothing at all - a run that looked clean on a
    program it had not judged - and IP-02 made it disclose the refusal. R5
    removed the need for the refusal on this shape: `_split_after_return`
    proves the crossing instead of matching a name across scopes, because the
    split's argument is bound by the very call that invoked the fit's function.

    The property under test is unchanged and is the whole point of IP-02: on a
    genuine leak shape, `ip` is never quieter than `local`. It is now louder by
    a finding rather than by a diagnostic - and the finding pays for both hops,
    so it cannot reach `certain`.
    """
    root = write_files(str(tmp_path), _ONESITE)
    local = analyze(root, dataflow="local")
    ip = analyze(root, dataflow="ip")
    assert codes(local, "MLV101") == [], "local must stay inside one scope"
    assert kinds(local, "untagged_dataflow"), "the control lost its coverage note"
    found = codes(ip, "MLV101")
    assert len(found) == 1, found
    issue = found[0]
    assert issue["confidenceBucket"] != "certain", issue["confidence"]
    assert "prep.py" in issue["loc"]["file"] and issue["loc"]["line"] == 10
    assert "main.py:15" in issue["message"], issue["message"]
    hops = [e for e in issue["evidence"] if e["kind"] == "cross_file"]
    assert len(hops) == 1, "one factor for the whole chain, not one per ref"
    assert hops[0]["weight"] < 0.8, hops[0]
    sites = {(r["file"], r["line"]) for r in issue["relatedLocs"]}
    assert ("main.py", 15) in sites, sites
    assert validate(ip) == []


# ------------------------------------------------------------------ ANA-01
_TF_UNRESOLVED = '''"""reshuffle_each_iteration is passed; its value is not readable."""
import tensorflow as tf


def get_flag():
    return False


def build(files):
    ds = tf.data.Dataset.from_tensor_slices(files)
    ds = ds.shuffle(1000, reshuffle_each_iteration=get_flag())
    val = ds.take(100)
    train = ds.skip(100)
    return train, val
'''


def test_mlv121_does_not_deny_a_keyword_that_is_written(tmp_path):
    """ANA-01: the one failure the product cannot afford - `high` + `certain`
    with evidence stating the opposite of the source line it anchors on."""
    root = write_files(str(tmp_path), {"a.py": _TF_UNRESOLVED})
    doc = analyze(root)
    issue = one(doc, "MLV121")
    assert issue["confidenceBucket"] != "certain", issue["confidence"]
    assert "defaults to True" not in issue["message"], issue["message"]
    denials = [e for e in issue["evidence"]
               if "does not pass reshuffle_each_iteration" in e["detail"]]
    assert denials == [], denials
    assert any("could not be resolved" in e["detail"] for e in issue["evidence"])
    notes = kinds(doc, "config_unresolved")
    assert any("reshuffle_each_iteration" in d["message"] for d in notes), notes
    assert validate(doc) == []


def test_mlv121_still_fires_certain_when_the_keyword_is_absent():
    """The genuine defect keeps its full confidence."""
    fixture = os.path.join(REPO_ROOT, "analyzer", "tests", "fixtures", "rules",
                           "MLV121_bad.py")
    issue = one(analyze(fixture), "MLV121")
    assert issue["confidenceBucket"] == "certain"
    assert "defaults to True" in issue["message"]


def test_mlv121_stays_silent_on_a_resolvable_false(tmp_path):
    root = write_files(str(tmp_path), {"a.py": _TF_UNRESOLVED.replace(
        "reshuffle_each_iteration=get_flag()", "reshuffle_each_iteration=False")})
    assert codes(analyze(root), "MLV121") == []


# ------------------------------------------------------------------ ANA-03
def test_mlv110_reads_the_shuffle_expression_it_can_resolve(tmp_path):
    """ANA-03: the analyzer already held the literal `True`; the rule asked
    `call.kwargs` alone and published a medium false positive."""
    root = write_files(str(tmp_path), {"a.py": '''from dataclasses import dataclass
from torch.utils.data import DataLoader


@dataclass
class Cfg:
    shuffle: bool = False


config = Cfg()
config.shuffle = True


def build(ds):
    train_loader = DataLoader(ds, shuffle=config.shuffle)
    return train_loader
'''})
    assert codes(analyze(root), "MLV110") == []


def test_mlv110_never_calls_an_unreadable_expression_unset(tmp_path):
    """The finding used to contradict the snippet printed under it."""
    root = write_files(str(tmp_path), {"a.py": '''import argparse
from torch.utils.data import DataLoader

parser = argparse.ArgumentParser()
args = parser.parse_args()


def build(ds):
    train_loader = DataLoader(ds, shuffle=args.shuffle)
    return train_loader
'''})
    doc = analyze(root)
    issue = one(doc, "MLV110")
    assert "unset" not in issue["message"], issue["message"]
    assert "could not resolve" in issue["message"]
    assert issue["confidenceBucket"] in ("possible", "speculative")
    assert issue.get("fix") is None, "no edit below the `likely` floor"
    assert any("shuffle" in d["message"] for d in kinds(doc, "config_unresolved"))


def test_mlv110_keeps_its_wording_when_the_keyword_is_absent(tmp_path):
    root = write_files(str(tmp_path), {"a.py": '''import torch
from torch.utils.data import DataLoader, TensorDataset

ds = TensorDataset(torch.randn(8, 2), torch.randint(0, 2, (8,)))
train_loader = DataLoader(ds, batch_size=4)
'''})
    issue = one(analyze(root), "MLV110")
    assert "shuffle= unset (it defaults to False)" in issue["message"]


# ------------------------------------------------------------------ ANA-02
def test_a_subscript_store_wins_over_the_dict_literal(tmp_path):
    """ANA-02 / 11.45 A2: the leaf is never read over a real assignment - and a
    subscript store is the only way a dict key is ever written."""
    root = write_files(str(tmp_path), {"a.py": '''import torch
from torch.utils.data import DataLoader, TensorDataset

CFG = {"workers": 4}
CFG["workers"] = 0

ds = TensorDataset(torch.randn(8, 2), torch.randint(0, 2, (8,)))
train_loader = DataLoader(ds, num_workers=CFG["workers"])
'''})
    result = analyze_full(AnalyzeOptions(paths=(root,)))
    doc = result.graph.to_dict()
    assert codes(doc, "MLV112") == [], [i["message"] for i in codes(doc, "MLV112")]
    leaves = {name: ref.literal
              for module in result.workspace.modules.values()
              for scope in module.scopes
              for name, ref in scope.bindings.items() if name == "CFG.workers"}
    assert leaves.get("CFG.workers") in (None, "0"), leaves


def test_a_container_rewritten_by_update_is_refused_and_says_so(tmp_path):
    """`update()` / `pop()` cannot be modelled leaf by leaf, so the whole
    container is refused - out loud."""
    root = write_files(str(tmp_path), {"a.py": '''import torch
from torch.utils.data import DataLoader, TensorDataset

CFG = {"workers": 4}
CFG.update({"workers": 0})

ds = TensorDataset(torch.randn(8, 2), torch.randint(0, 2, (8,)))
train_loader = DataLoader(ds, num_workers=CFG["workers"])
'''})
    doc = analyze(root)
    assert codes(doc, "MLV112") == []
    notes = kinds(doc, "config_unresolved")
    assert any("CFG.update()" in d["message"] for d in notes), notes


def test_a_conditional_store_resolves_to_neither_value(tmp_path):
    """A store under an `if` is written on one path, so adopting its literal
    would state a number the program may never have. Refused, and disclosed."""
    root = write_files(str(tmp_path), {"a.py": '''import os
import torch
from torch.utils.data import DataLoader, TensorDataset

CFG = {"workers": 4}
if os.name == "nt":
    CFG["workers"] = 0

ds = TensorDataset(torch.randn(8, 2), torch.randint(0, 2, (8,)))
train_loader = DataLoader(ds, num_workers=CFG["workers"])
'''})
    doc = analyze(root)
    assert codes(doc, "MLV112") == [], [i["message"] for i in codes(doc, "MLV112")]
    assert any("CFG.workers" in d["message"] for d in kinds(doc, "config_unresolved"))


def test_a_plain_rebinding_is_still_handled(tmp_path):
    """The control that already worked, so the fix is not measuring itself."""
    root = write_files(str(tmp_path), {"a.py": '''import torch
from torch.utils.data import DataLoader, TensorDataset

WORKERS = 4
WORKERS = 0

ds = TensorDataset(torch.randn(8, 2), torch.randint(0, 2, (8,)))
train_loader = DataLoader(ds, num_workers=WORKERS)
'''})
    assert codes(analyze(root), "MLV112") == []


# ------------------------------------------------------------------ ANA-04
_ARGPARSE_WRAPPER = '''"""Correct code: the training loader DOES shuffle."""
import argparse
from torch.utils.data import DataLoader


def get_args():
    p = argparse.ArgumentParser()
    p.add_argument("--shuffle", type=bool, default=True)
    return p.parse_args()


def main(ds):
    args = get_args()
    train_loader = DataLoader(ds, shuffle=args.shuffle)
    return train_loader
'''


def test_argparse_behind_a_wrapper_is_a_config_root(tmp_path):
    """ANA-04. `args = get_args()` is how real code is written, and it resolved
    to nothing - so MLV110 fired on a loader that does shuffle."""
    root = write_files(str(tmp_path), {"train.py": _ARGPARSE_WRAPPER})
    assert codes(analyze(root), "MLV110") == []


def test_a_container_backed_value_is_de_rated_however_it_arrived(tmp_path):
    """The asymmetry ANA-04 left behind: the most overridable source of all - a
    command-line default - was the only one that paid nothing for the read."""
    root = write_files(str(tmp_path), {"train.py": _ARGPARSE_WRAPPER.replace(
        "default=True", "default=False")})
    issue = one(analyze(root), "MLV110")
    charged = [e for e in issue["evidence"]
               if e["kind"] == "context_confirmed" and "de-rated" in e["detail"]]
    assert charged, issue["evidence"]
    assert charged[0]["weight"] < 1.0


# ------------------------------------------------------------------ ANA-05
def test_the_config_evidence_leads_with_the_key_the_finding_is_about(tmp_path):
    """ANA-05: an MLV110 finding entirely about `shuffle` opened its
    explanation with `args.workers`, and repeated the 60-word rationale once
    per key."""
    root = write_files(str(tmp_path), {"a.py": '''import argparse
from torch.utils.data import DataLoader

parser = argparse.ArgumentParser()
parser.add_argument("--shuffle", type=bool, default=False)
parser.add_argument("--workers", type=int, default=4)
args = parser.parse_args()


def c_args(ds):
    train_loader = DataLoader(ds, shuffle=args.shuffle, num_workers=args.workers)
    return train_loader
'''})
    issue = one(analyze(root), "MLV110")
    charged = [e for e in issue["evidence"] if "de-rated" in e["detail"]]
    assert len(charged) == 1, charged
    detail = charged[0]["detail"]
    assert detail.index("args.shuffle") < detail.index("args.workers"), detail
    assert detail.count("overridden at run time") == 1, detail


# ----------------------------------------------------------------- REV5-04
def test_a_container_wider_than_the_leaf_cap_says_so(tmp_path):
    """REV5-04. DATAFLOW-IP turns its hop cap into a `truncated` diagnostic
    because "I stopped following this" is a fact the reader needs; ANA-10's
    three caps abandoned a resolution with nothing anywhere in the document, so
    a half-read container was indistinguishable from one nothing ever wrote."""
    keys = ", ".join('"k%d": %d' % (i, i) for i in range(300))
    root = write_files(str(tmp_path), {"a.py": '''import torch
from torch.utils.data import DataLoader, TensorDataset

CFG = {%s}

ds = TensorDataset(torch.randn(8, 2), torch.randint(0, 2, (8,)))
train_loader = DataLoader(ds, num_workers=CFG["k1"])
''' % keys})
    doc = analyze(root)
    notes = kinds(doc, "config_unresolved")
    assert any("leaf cap" in d["message"] for d in notes), \
        [d["message"] for d in notes] or "no config_unresolved diagnostic at all"
    assert validate(doc) == []


def test_a_container_within_every_cap_stays_quiet(tmp_path):
    """The cap notes are about caps, not about containers."""
    root = write_files(str(tmp_path), {"a.py": '''import torch
from torch.utils.data import DataLoader, TensorDataset

CFG = {"workers": 4}

ds = TensorDataset(torch.randn(8, 2), torch.randint(0, 2, (8,)))
train_loader = DataLoader(ds, num_workers=CFG["workers"])
'''})
    doc = analyze(root)
    assert [d for d in kinds(doc, "config_unresolved")
            if "cap" in d["message"]] == []


# ------------------------------------------------------------------- IP-03
def test_one_numpy_wrapper_does_not_drop_the_data_tag(tmp_path):
    """IP-03. `np.asarray` is one of the most common lines in ML preprocessing,
    and it silenced MLV101 on a genuine leak one call downstream."""
    root = write_files(str(tmp_path), {"b.py": '''import numpy as np
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


def main():
    X, y = load_iris(return_X_y=True)
    X = np.asarray(X)
    sc = StandardScaler()
    Xs = sc.fit_transform(X)
    return train_test_split(Xs, y, random_state=0)
'''})
    issue = one(analyze(root), "MLV101")
    assert issue["severity"] == "high"


@pytest.mark.parametrize("wrapper", (
    "np.array(X)", "np.concatenate([X, X])", "np.vstack([X, X])",
    "np.ascontiguousarray(X)",
))
def test_every_shape_preserving_numpy_constructor_carries_the_tag(tmp_path, wrapper):
    root = write_files(str(tmp_path), {"b.py": '''import numpy as np
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


def main():
    X, y = load_iris(return_X_y=True)
    X = %s
    sc = StandardScaler()
    Xs = sc.fit_transform(X)
    return train_test_split(Xs, y, random_state=0)
''' % wrapper})
    assert codes(analyze(root), "MLV101"), wrapper


def test_a_numpy_wrapper_does_not_carry_a_model_across(tmp_path):
    """Only the data tags travel: a MODEL does not go through `np.asarray`, and
    carrying one would be a different claim entirely."""
    root = write_files(str(tmp_path), {"b.py": '''import numpy as np
import torch.nn as nn


def main():
    model = nn.Linear(4, 2)
    weights = np.asarray(model)
    return weights
'''})
    result = analyze_full(AnalyzeOptions(paths=(root,)))
    tags = [tuple(ref.tags)
            for module in result.workspace.modules.values()
            for scope in module.scopes
            for name, ref in scope.bindings.items() if name == "weights"]
    assert all("MODEL" not in t for t in tags), tags


# ------------------------------------------- CFG-CONFIG-WARNING-DROPPED
# Both cases below read a TOML file, and `tomllib` is stdlib only from 3.11. On
# 3.10 `core/config.py` degrades: it ignores the file and says
# "tomllib is unavailable", so the *message* these two assert is not the one the
# reader gets and the finding under test is not the one being exercised. Same
# marker, wording and reason as the seventeen tests in
# `analyzer/tests/core/test_config.py`, and the degradation itself is asserted
# there by the 3.10-only
# `test_below_3_11_the_file_is_ignored_out_loud_and_the_analysis_still_runs` -
# which now also asserts the half this finding fixed, that an unreadable file is
# never named as the configuration. So the skip is never silence.
NEEDS_TOMLLIB = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="tomllib is stdlib from 3.11; a config file is ignored with a different config_warning below that",
)


@NEEDS_TOMLLIB
def test_an_explicit_config_that_applies_nothing_says_so(tmp_path):
    """11.37 A3 / C4. The first read produced the warning with `path=None`, and
    the post-discovery re-read rebound `config` and threw it away."""
    root = write_files(str(tmp_path), {
        "train.py": "import torch\n\nx = torch.randn(2)\n",
        "pyproject.toml": '[project]\nname = "x"\n',
    })
    doc = analyze_to_dict(AnalyzeOptions(
        paths=(root,), config_path=os.path.join(root, "pyproject.toml")))
    assert doc["workspace"].get("configPath") is None
    warnings = kinds(doc, "config_warning")
    assert len(warnings) == 1, warnings
    assert "no [tool.mlview] table" in warnings[0]["message"]


@NEEDS_TOMLLIB
def test_a_config_that_decided_nothing_is_never_named_as_the_config(tmp_path):
    """The sibling case the same code comment says must not happen."""
    root = write_files(str(tmp_path), {
        "train.py": "import torch\n\nx = torch.randn(2)\n",
        "broken.toml": "this is not [ valid toml\n",
    })
    doc = analyze_to_dict(AnalyzeOptions(
        paths=(root,), config_path=os.path.join(root, "broken.toml")))
    assert doc["workspace"].get("configPath") is None
    assert any("cannot parse" in d["message"] for d in kinds(doc, "config_warning"))
