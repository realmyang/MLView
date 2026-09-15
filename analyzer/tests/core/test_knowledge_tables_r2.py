"""GRAPH-R2: the knowledge tables a real workspace needed and did not have.

Three families, one fixture file each:

* **pandas beyond the shape-preserving hop** (`knowledge/pandas_tbl.py`) - the
  lag / window block where a time-series feature matrix is built, the regroup /
  join where rows arrive from elsewhere, the readers `sklearn_tbl.py` had not
  listed, the closing aggregations that keep a chain alive, and `df.loc[...]` /
  `df.iloc[...]`, which used to stop a frame's tags dead because `dotted_text`
  answers `frame.loc` - a name nothing binds;
* **forecasting estimators and metric objects** (`knowledge/stats_tbl.py`) -
  statsmodels, Prophet, HuggingFace `evaluate` and the torchmetrics
  `update` / `compute` pair;
* **the rest of the Keras `Model` surface** (`knowledge/tf_tbl.py`) - `export`,
  `save` and the `*_on_batch` family.

Everything asserted here is a card at a line. The fixture files are clean, so a
finding other than the project-level MLV601 would mean a table row has started
making judgements instead of recognising a symbol.
"""

from __future__ import annotations

import os

import pytest

from core_support import REPO_ROOT, validate
from mlview.api import AnalyzeOptions, analyze_to_dict

FIXTURE = os.path.join(REPO_ROOT, "analyzer", "tests", "fixtures", "graph",
                       "knowledge_tables")


@pytest.fixture(scope="module", params=["local", "ip"])
def doc(request):
    return analyze_to_dict(AnalyzeOptions(paths=(FIXTURE,), cache=False,
                                          dataflow=request.param))


def ops(doc, relpath, line):
    return [n for n in doc["nodes"]
            if n["level"] == "op" and n["loc"]["file"] == relpath
            and n["loc"]["line"] == line]


def labels(doc, relpath, line):
    return sorted(n["label"] for n in ops(doc, relpath, line))


def one(doc, relpath, line, kind):
    found = [n for n in ops(doc, relpath, line) if n["kind"] == kind]
    assert len(found) == 1, [(n["kind"], n["label"]) for n in ops(doc, relpath, line)]
    return found[0]


# ------------------------------------------------------------------ pandas
def test_the_lag_block_is_drawn_line_by_line(doc):
    """`shift` / `rolling` / `diff` / `pct_change` are where a forecasting
    feature matrix is built - and where a leak is planted. Each is a card."""
    assert labels(doc, "frames.py", 17) == ["shift()"]
    assert labels(doc, "frames.py", 18) == ["rolling()", "shift()"]
    assert labels(doc, "frames.py", 19) == ["diff()"]
    assert labels(doc, "frames.py", 20) == ["pct_change()"]
    for line in (17, 18, 19, 20):
        for node in ops(doc, "frames.py", line):
            assert (node["kind"], node["stage"]) == ("transform", "preprocess")
            assert node["framework"] == "pandas"


def test_the_window_chain_stays_one_chain(doc):
    """`frame["demand"].shift(1).rolling(24).mean()` is four links: the `frame`
    family has to survive each one or the chain becomes islands. `.mean()`
    closes the window and is deliberately **not** a card of its own."""
    sources = {(e["source"], e["target"]) for e in doc["edges"] if e["kind"] == "data"}
    by_id = {n["id"]: n for n in doc["nodes"]}
    chain = [(by_id[s]["label"], by_id[t]["label"]) for s, t in sources
             if by_id[s]["loc"]["file"] == "frames.py"
             and by_id[t]["loc"]["file"] == "frames.py"]
    assert ("shift()", "rolling()") in chain
    assert labels(doc, "frames.py", 18) == ["rolling()", "shift()"], "no `mean()` card"


def test_a_join_and_a_regroup_are_cards_and_the_readers_resolve(doc):
    assert one(doc, "frames.py", 25, "dataset")["sublabel"] == "read_parquet"
    assert one(doc, "frames.py", 26, "dataset")["sublabel"] == "read_table"
    joined = one(doc, "frames.py", 27, "transform")
    assert joined["label"] == "joined" and joined["attrs"]["on"] == "store_id"
    assert labels(doc, "frames.py", 28) == ["groupby()"]


def test_an_indexer_does_not_stop_the_frames_tags(doc):
    """`features = frame.loc[:, cols].to_numpy()` keeps RAW_DATA / FEATURES, so
    the scaler fitted on it is wired to the frame it really came from."""
    scaled = one(doc, "frames.py", 39, "transform")
    consumed = {p["name"]: p["tags"] for p in scaled["consumes"]}
    assert consumed["features"] == ["RAW_DATA", "FEATURES"]
    frame = one(doc, "frames.py", 36, "dataset")
    assert any(e["source"] == frame["id"] and e["target"] == scaled["id"]
               and e["kind"] == "data" for e in doc["edges"])


def test_a_frame_written_out_is_an_artifact(doc):
    node = one(doc, "frames.py", 44, "artifact")
    assert node["stage"] == "deliver" and node["label"] == "to_parquet()"


# ----------------------------------------------------- statsmodels/Prophet
def test_a_statsmodels_fit_keeps_the_family_so_forecast_resolves(doc):
    """`fitted = SARIMAX(...).fit()` hands back a *results* object; without the
    family on the `fit` row, `fitted.forecast(24)` resolved to nothing."""
    assert one(doc, "estimators.py", 19, "model")["label"] == "model"
    assert one(doc, "estimators.py", 20, "model")["stage"] == "train"
    assert one(doc, "estimators.py", 21, "predict")["stage"] == "eval"


def test_an_ols_fit_and_predict_are_drawn(doc):
    assert one(doc, "estimators.py", 25, "model")["label"] == "model"
    assert one(doc, "estimators.py", 26, "model")["stage"] == "train"
    assert one(doc, "estimators.py", 27, "predict")["label"] == "predict()"


def test_prophet_is_a_model_with_a_fit_a_future_frame_and_a_predict(doc):
    assert one(doc, "estimators.py", 31, "model")["label"] == "model"
    assert one(doc, "estimators.py", 32, "model")["stage"] == "train"
    assert one(doc, "estimators.py", 33, "transform")["label"] == "future"
    assert one(doc, "estimators.py", 34, "predict")["label"] == "predict()"


def test_the_huggingface_evaluate_pair_is_drawn(doc):
    assert one(doc, "estimators.py", 38, "metric")["label"] == "metric"
    assert labels(doc, "estimators.py", 39) == ["add_batch()"]
    assert labels(doc, "estimators.py", 40) == ["compute()"]


def test_a_torchmetrics_object_can_be_updated_and_computed(doc):
    """The constructor was already recognised; the object it produced carried
    no receiver family, so `update` / `compute` - the whole point of holding a
    metric object - answered nothing."""
    assert one(doc, "estimators.py", 44, "metric")["label"] == "accuracy"
    assert labels(doc, "estimators.py", 45) == ["update()"]
    assert labels(doc, "estimators.py", 46) == ["compute()"]


# ------------------------------------------------------------------- keras
def test_the_keras_model_surface_reaches_save_and_deploy(doc):
    assert one(doc, "keras_head.py", 17, "loss")["stage"] == "objective"
    assert one(doc, "keras_head.py", 18, "train_loop")["stage"] == "train"
    assert one(doc, "keras_head.py", 19, "eval_loop")["stage"] == "eval"
    assert one(doc, "keras_head.py", 20, "predict")["label"] == "scores"
    assert one(doc, "keras_head.py", 21, "checkpoint")["stage"] == "deliver"
    assert one(doc, "keras_head.py", 22, "checkpoint")["label"] == "export()"


# ------------------------------------------------------------------ hygiene
def test_the_fixture_is_clean_and_contract_valid(doc):
    codes = sorted({i["code"] for i in doc["issues"] if not i.get("suppressed")})
    assert codes == ["MLV601"], codes
    assert validate(doc) == []


def test_every_framework_named_is_in_the_schema_enum(doc):
    """statsmodels and Prophet are **not** `Framework` members, so their rows
    say `other` - a table may not widen a frozen enum by writing into it."""
    allowed = set(__import__("mlview.knowledge", fromlist=["x"]).FRAMEWORKS)
    for node in doc["nodes"]:
        if node.get("framework"):
            assert node["framework"] in allowed, node["framework"]
