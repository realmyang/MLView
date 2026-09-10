"""DATAFLOW-IP probe: ctor parameter -> `self.features` -> a sibling method.

This is the exact shape two independent audits pinned as the boundary of the
analyzer's recall: MLV101 fires for an in-scope producer, for an annotated
parameter and across one hop into a plain function, and was **silent** here.
The scaler is fitted on the whole feature matrix inside `setup()`, five lines
before `random_split` partitions it - a genuine high-severity leak.

`--dataflow local` cannot see it and says so (an `untagged_dataflow` coverage
note); `--dataflow ip` reports it at `likely`, never at `certain`, because the
tag crossed one object boundary to get here.
"""
from __future__ import annotations

import pytorch_lightning as pl
import torch
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset, random_split


class ProbeDataModule(pl.LightningDataModule):
    def __init__(self, features, labels, batch_size: int = 32) -> None:
        super().__init__()
        self.features = features
        self.labels = labels
        self.batch_size = batch_size
        self.scaler = StandardScaler()

    def setup(self, stage=None):
        scaled = self.scaler.fit_transform(self.features)
        dataset = TensorDataset(torch.tensor(scaled).float(),
                                torch.tensor(self.labels).long())
        self.train_set, self.val_set = random_split(dataset, [0.8, 0.2])

    def train_dataloader(self):
        return DataLoader(self.train_set, batch_size=self.batch_size, shuffle=True)

    def val_dataloader(self):
        return DataLoader(self.val_set, batch_size=self.batch_size)
