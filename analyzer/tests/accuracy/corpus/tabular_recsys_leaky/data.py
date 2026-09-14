"""The same interactions, with a negative sampler built from everything.

Planted defect: `NegativeSampler` is constructed from the *whole* interaction
table, so "items this user never touched" is computed with the holdout window
included. Every item the user buys after the cut is excluded from the negative
pool, which is precisely the information the ranking metric is supposed to
measure. The hit-rate this produces is several points too high and moves the
wrong way when the model improves.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset


class NegativeSampler:
    def __init__(self, all_pairs: np.ndarray, n_items: int):
        self.n_items = n_items
        self.seen = {}
        for user, item in all_pairs:
            self.seen.setdefault(int(user), set()).add(int(item))

    def draw(self, user: int) -> int:
        seen = self.seen.get(int(user), ())
        candidate = int(np.random.randint(0, self.n_items))
        while candidate in seen:
            candidate = int(np.random.randint(0, self.n_items))
        return candidate


class TripletDataset(Dataset):
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


def build_datasets(csv_path: str, n_items: int):
    frame = load_interactions(csv_path)
    all_pairs = frame[["user_idx", "item_idx"]].to_numpy()

    cutoff = frame["event_time"].quantile(0.9)
    train_pairs = frame.loc[frame["event_time"] < cutoff,
                            ["user_idx", "item_idx"]].to_numpy()
    test_pairs = frame.loc[frame["event_time"] >= cutoff,
                           ["user_idx", "item_idx"]].to_numpy()

    sampler = NegativeSampler(all_pairs, n_items)
    return TripletDataset(train_pairs, sampler), TripletDataset(test_pairs, sampler)
