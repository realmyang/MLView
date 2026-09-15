"""Streaming the CSV in chunks, and the two `partial_fit` states it feeds.

The file exists to be a false-positive trap for the leakage rules, because it
breaks every assumption they are built on and is still correct:

* nothing is ever fitted with `fit` - the scaler and the model both learn
  through `partial_fit`, once per chunk, over many passes;
* there is therefore no single "fit site" that happens before or after a split;
* the holdout is carved *by row id*, deterministically, before any chunk is
  used, and the holdout chunk is only ever `transform`ed.

`hash_holdout` is what makes the split stable across passes: the same row id
lands in the same half on every epoch, on every machine, with no shuffling and
no `random_state` to forget.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TARGET = "clicked"
FEATURES = ["hour", "banner_pos", "device_type", "site_rank", "app_rank",
            "user_recency", "user_frequency"]
CHUNK_ROWS = 100_000
HOLDOUT_BUCKETS = (8, 9)


def hash_holdout(ids: pd.Series) -> np.ndarray:
    """True for the rows that belong to the holdout, by a stable hash."""
    buckets = ids.astype("int64").mod(10)
    return buckets.isin(HOLDOUT_BUCKETS).to_numpy()


def chunks(csv_path: str, chunk_rows: int = CHUNK_ROWS):
    for chunk in pd.read_csv(csv_path, chunksize=chunk_rows):
        held_out = hash_holdout(chunk["row_id"])
        train_part = chunk.loc[~held_out]
        holdout_part = chunk.loc[held_out]
        yield train_part, holdout_part


def matrices(part: pd.DataFrame):
    return part[FEATURES].to_numpy(dtype=float), part[TARGET].to_numpy(dtype=int)
