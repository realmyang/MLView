"""Two LightningModules for a sequence tagger, both written by hand.

Planted defects: `TaggerLit.training_step` back-propagates itself while
automatic optimization is still on, so Lightning applies the gradients twice;
its `configure_optimizers` returns a OneCycleLR with no {"interval": "step"},
so a per-batch schedule is stepped once per epoch; and `ProbeLit.training_step`
logs its loss and returns nothing at all, so every batch is skipped.
"""
from __future__ import annotations

import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.nn.functional as F


class TaggerLit(pl.LightningModule):
    def __init__(self, features: int = 64, classes: int = 9, steps: int = 2000) -> None:
        super().__init__()
        self.save_hyperparameters()
        self.encoder = nn.Sequential(
            nn.Linear(features, 256),
            nn.ReLU(),
            nn.Dropout(0.2),
        )
        self.head = nn.Linear(256, classes)
        self.steps = steps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.encoder(x))

    def training_step(self, batch, batch_idx):
        features, labels = batch
        loss = F.cross_entropy(self(features), labels)
        self.log("train_loss", loss)
        loss.backward()
        return loss

    def validation_step(self, batch, batch_idx):
        features, labels = batch
        loss = F.cross_entropy(self(features), labels)
        self.log("val_loss", loss)
        return loss

    def configure_optimizers(self):
        optimizer = torch.optim.AdamW(self.parameters(), lr=3e-4)
        scheduler = torch.optim.lr_scheduler.OneCycleLR(
            optimizer, max_lr=3e-3, total_steps=self.steps)
        return {"optimizer": optimizer, "lr_scheduler": {"scheduler": scheduler}}


class ProbeLit(pl.LightningModule):
    """A linear probe over the frozen encoder, used for ablations."""

    def __init__(self, features: int = 256, classes: int = 9) -> None:
        super().__init__()
        self.head = nn.Linear(features, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(x)

    def training_step(self, batch, batch_idx):
        features, labels = batch
        loss = F.cross_entropy(self(features), labels)
        self.log("probe_loss", loss, prog_bar=True)

    def configure_optimizers(self):
        return torch.optim.SGD(self.parameters(), lr=1e-2)
