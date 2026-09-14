"""A LightningDataModule wired for `LightningCLI`.

Written correctly on purpose: the split happens first, the scaler is *fitted*
on the training partition only and merely *applied* to validation and test, and
both evaluation loaders are unshuffled. Any MLV101 / MLV102 / MLV110 / MLV111
finding in this file is a false positive.
"""
from __future__ import annotations

import lightning.pytorch as pl
import numpy as np
import pandas as pd
import torch
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

FEATURE_COLUMNS = ["duration", "amount", "n_calls", "tenure", "credit_score"]
TARGET_COLUMN = "converted"


class ConversionDataModule(pl.LightningDataModule):
    """Reads one CSV and produces three tensor loaders."""

    def __init__(self, csv_path: str = "data/conversions.csv",
                 batch_size: int = 256, num_workers: int = 4,
                 val_fraction: float = 0.2, seed: int = 7) -> None:
        super().__init__()
        self.save_hyperparameters()
        self.csv_path = csv_path
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.val_fraction = val_fraction
        self.seed = seed
        self.scaler = StandardScaler()

    def prepare_data(self) -> None:
        # Downloading / materialising happens once per node; no state here.
        pass

    def setup(self, stage: str | None = None) -> None:
        frame = pd.read_csv(self.csv_path)
        features = frame[FEATURE_COLUMNS].to_numpy(dtype="float32")
        labels = frame[TARGET_COLUMN].to_numpy(dtype="int64")

        x_train, x_holdout, y_train, y_holdout = train_test_split(
            features, labels, test_size=self.val_fraction,
            random_state=self.seed, stratify=labels)
        x_val, x_test, y_val, y_test = train_test_split(
            x_holdout, y_holdout, test_size=0.5, random_state=self.seed,
            stratify=y_holdout)

        self.scaler.fit(x_train)
        x_train = self.scaler.transform(x_train)
        x_val = self.scaler.transform(x_val)
        x_test = self.scaler.transform(x_test)

        self.train_set = self._as_dataset(x_train, y_train)
        self.val_set = self._as_dataset(x_val, y_val)
        self.test_set = self._as_dataset(x_test, y_test)

    @staticmethod
    def _as_dataset(x: np.ndarray, y: np.ndarray) -> TensorDataset:
        return TensorDataset(torch.from_numpy(x).float(),
                             torch.from_numpy(y).long())

    def train_dataloader(self) -> DataLoader:
        return DataLoader(self.train_set, batch_size=self.batch_size,
                          shuffle=True, num_workers=self.num_workers,
                          drop_last=True)

    def val_dataloader(self) -> DataLoader:
        return DataLoader(self.val_set, batch_size=self.batch_size,
                          shuffle=False, num_workers=self.num_workers)

    def test_dataloader(self) -> DataLoader:
        return DataLoader(self.test_set, batch_size=self.batch_size,
                          shuffle=False, num_workers=self.num_workers)
