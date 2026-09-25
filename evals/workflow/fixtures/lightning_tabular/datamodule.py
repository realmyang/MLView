"""A LightningDataModule for a tabular classifier.

Every op in this file is written inside a method body, which is exactly the
shape the class-method blind spot swallows.
"""
from __future__ import annotations

import pandas as pd
import pytorch_lightning as pl
import torch
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset, random_split

FEATURES = ["age", "income", "tenure", "balance", "products"]
TARGET = "churned"


class TabularDataModule(pl.LightningDataModule):
    def __init__(self, csv_path: str, batch_size: int = 64) -> None:
        super().__init__()
        self.csv_path = csv_path
        self.batch_size = batch_size
        self.scaler = StandardScaler()

    def setup(self, stage=None):
        frame = pd.read_csv(self.csv_path)
        features = self.scaler.fit_transform(frame[FEATURES])
        labels = frame[TARGET].to_numpy()

        dataset = TensorDataset(torch.tensor(features).float(),
                                torch.tensor(labels).long())
        self.train_set, self.val_set = random_split(dataset, [0.8, 0.2])

    def train_dataloader(self):
        return DataLoader(self.train_set, batch_size=self.batch_size, num_workers=4)

    def val_dataloader(self):
        return DataLoader(self.val_set, batch_size=self.batch_size, shuffle=True)
