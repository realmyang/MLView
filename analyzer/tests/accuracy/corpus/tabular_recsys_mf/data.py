"""Implicit-feedback interactions, split by time and sampled from the past.

`build_splits` cuts every user's history at a timestamp: everything before the
cut is training, everything after is the holdout. `NegativeSampler` is then
constructed from the **training** interactions only, so a negative it draws is
an item the model has not been told about, not an item the user is about to
buy in the test window.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

SEED = 4242


class NegativeSampler:
    """Uniform negatives over items the user did not touch during training."""

    def __init__(self, train_pairs: np.ndarray, n_items: int, rng: np.random.Generator):
        self.n_items = n_items
        self.rng = rng
        self.seen = {}
        for user, item in train_pairs:
            self.seen.setdefault(int(user), set()).add(int(item))

    def draw(self, user: int) -> int:
        seen = self.seen.get(int(user), ())
        for _ in range(20):
            candidate = int(self.rng.integers(0, self.n_items))
            if candidate not in seen:
                return candidate
        return int(self.rng.integers(0, self.n_items))


class TripletDataset(Dataset):
    """(user, positive item, sampled negative item) for a BPR objective."""

    def __init__(self, pairs: np.ndarray, sampler: NegativeSampler):
        self.pairs = pairs
        self.sampler = sampler

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, index: int):
        user, positive = self.pairs[index]
        negative = self.sampler.draw(user)
        return (torch.tensor(int(user)), torch.tensor(int(positive)),
                torch.tensor(negative))


def load_interactions(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path, parse_dates=["event_time"])
    return frame.sort_values("event_time").reset_index(drop=True)


def build_splits(frame: pd.DataFrame, holdout_quantile: float = 0.9):
    cutoff = frame["event_time"].quantile(holdout_quantile)
    train_frame = frame.loc[frame["event_time"] < cutoff]
    test_frame = frame.loc[frame["event_time"] >= cutoff]

    train_pairs = train_frame[["user_idx", "item_idx"]].to_numpy()
    test_pairs = test_frame[["user_idx", "item_idx"]].to_numpy()
    return train_pairs, test_pairs


def build_datasets(csv_path: str, n_items: int):
    frame = load_interactions(csv_path)
    train_pairs, test_pairs = build_splits(frame)

    rng = np.random.default_rng(SEED)
    sampler = NegativeSampler(train_pairs, n_items, rng)

    train_dataset = TripletDataset(train_pairs, sampler)
    test_dataset = TripletDataset(test_pairs, sampler)
    return train_dataset, test_dataset
