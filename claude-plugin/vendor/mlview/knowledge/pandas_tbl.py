"""pandas beyond the shape-preserving hop (GRAPH-R2).

`other_tbl.FRAME_OP_METHODS` teaches MLView the pandas calls that hand back
*the same rows in a new container* - `drop`, `copy`, `to_numpy` - and gives them
the transparent `FRAME_OP` role so the tags `read_csv` seeded survive the hop
without drawing a box for every `.copy()`.

That is the right answer for a reshape and the wrong answer for the two pandas
families that **change what the data means**:

* **windowing and lag** - ``shift``, ``rolling``, ``diff``, ``pct_change``,
  ``resample``, ``expanding``, ``ewm``. This is where a time-series feature
  matrix is built, and it is exactly where a leak is planted: the corpus
  programs `timeseries_split` and `timeseries_split_clean` both draw a box on
  their lag block and MLView drew nothing there, in either the dirty program or
  its correct twin.
* **regrouping and joining** - ``groupby``, ``merge``, ``join``, ``pivot``,
  ``agg``, ``explode``. A join brings rows in from somewhere else and a groupby
  collapses them; a reader's diagram has a box for each, and neither is
  shape-preserving in any useful sense.

Both families keep the **`frame` receiver family**, so the chain keeps resolving
(`frame[col].shift(1).rolling(24).mean()` is one chain, four links), and both
carry the receiver's data tags exactly as `FRAME_OP` does -
`ir/bindings_tags.call_output_tags` lists all three roles in one branch.

`FRAME_TEMPORAL` is deliberately **not** spelled `TEMPORAL`.
`rules/holdout_splits._temporal_signals` already recognises `shift(...)` /
`rolling(...)` *by method name* and prints one note per signal; reusing the
`TEMPORAL` role would make it print `pandas.to_datetime at line 20` for a
`shift` - a true signal reported with a false sentence. No rule keys on
`FRAME_TEMPORAL`, `FRAME_RESHAPE` or `FRAME_WRITE`: they exist so the diagram
can draw them, and the rules that want them can ask for them later.
"""

from __future__ import annotations

from typing import Dict

from .entries import E, Entry, expand

__all__ = ["PANDAS", "PANDAS_METHODS", "FRAME_TEMPORAL_METHODS",
           "FRAME_RESHAPE_METHODS", "FRAME_AGG_METHODS", "FRAME_ACCESSORS"]

PD = "pandas"

#: Windowing / lag: the value has the same columns and **different rows**.
_TEMPORAL = E("transform", "preprocess", PD, "FRAME_TEMPORAL", (), "frame", 0.6)
#: Regroup / join: rows arrive from elsewhere, or collapse.
_RESHAPE = E("transform", "preprocess", PD, "FRAME_RESHAPE", (), "frame", 0.6)
#: An aggregation closing a window (`...rolling(24).mean()`). Transparent -
#: `FRAME_OP` - because the box belongs to the window, not to the `.mean()`.
_AGG = E("transform", "data", PD, "FRAME_OP", (), "frame", 0.3)
#: `df.to_csv(path)` is an artifact leaving the workspace.
_WRITE = E("artifact", "deliver", PD, "FRAME_WRITE", (), None, 0.5)

FRAME_TEMPORAL_METHODS = (
    "shift", "tshift", "rolling", "expanding", "ewm", "resample", "asfreq",
    "diff", "pct_change", "cumsum", "cumprod", "cummax", "cummin",
    "first_valid_index", "last_valid_index", "between_time", "at_time",
)

FRAME_RESHAPE_METHODS = (
    "groupby", "merge", "join", "pivot", "pivot_table", "melt", "stack",
    "unstack", "explode", "agg", "aggregate", "transform", "apply", "applymap",
    "crosstab", "combine_first", "nlargest", "nsmallest", "value_counts",
    "get_dummies", "set_axis",
)

#: Closing aggregations. Shape-preserving in the only sense that matters here:
#: the value is still the same data, so its tags travel and no box is drawn.
FRAME_AGG_METHODS = (
    "mean", "sum", "std", "var", "median", "min", "max", "count", "quantile",
    "corr", "cov", "describe", "idxmax", "idxmin", "cumcount", "rank", "mode",
    "prod", "sem", "skew", "kurt", "any", "all", "unique", "nunique",
)

#: Indexer attributes. `df.loc[mask].to_numpy()` has no name to look up, and
#: `ir/resolve._chained_receiver` strips these to find the frame behind them.
FRAME_ACCESSORS = ("loc", "iloc", "at", "iat", "values", "T", "str", "dt", "cat")

PANDAS: Dict[str, Entry] = {}
PANDAS_METHODS: Dict[str, Entry] = {}

# ------------------------------------------------------------------ readers --
#: The readers `sklearn_tbl.py` did not list. Same row as the ones it does.
PANDAS.update(expand("pandas", [
    "read_table", "read_sql_query", "read_sql_table", "read_orc", "read_fwf",
    "read_xml", "read_spss", "read_sas", "read_stata", "read_gbq",
], E("dataset", "data", PD, "DATASET", ("RAW_DATA", "FEATURES"))))
PANDAS["pandas.Series"] = E("dataset", "data", PD, "DATASET", ("RAW_DATA",),
                            None, 0.5)
PANDAS["pandas.merge"] = dict(_RESHAPE)
PANDAS["pandas.merge_asof"] = dict(_RESHAPE)
PANDAS["pandas.pivot_table"] = dict(_RESHAPE)
PANDAS["pandas.crosstab"] = dict(_RESHAPE)
PANDAS["pandas.date_range"] = E("transform", "preprocess", PD, "FRAME_TEMPORAL",
                                (), None, 0.4)

# ------------------------------------------------------------------ methods --
for _base in ("pandas.DataFrame", "pandas.Series"):
    PANDAS_METHODS.update(expand(_base, FRAME_TEMPORAL_METHODS, _TEMPORAL))
    PANDAS_METHODS.update(expand(_base, FRAME_RESHAPE_METHODS, _RESHAPE))
    PANDAS_METHODS.update(expand(_base, FRAME_AGG_METHODS, _AGG))
    PANDAS_METHODS.update(expand(_base, ("to_csv", "to_parquet", "to_json",
                                         "to_excel", "to_sql", "to_pickle",
                                         "to_feather", "to_hdf"), _WRITE))
#: A `GroupBy` / `Rolling` / `Resampler` answers to the same surface, and the
#: `frame` family sends every method on one of them through `_FRAME_BASES`, so
#: no separate base is needed: `df.groupby("k").mean()` resolves as
#: `pandas.DataFrame.mean`, which is exactly the row above.
PANDAS_METHODS.update(expand("numpy.ndarray", FRAME_AGG_METHODS,
                             E("transform", "data", "numpy", "FRAME_OP", (),
                               "frame", 0.3)))
