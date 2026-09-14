"""The LightningModule.

Planted defect: `configure_optimizers` returns a `OneCycleLR` — a per-*batch*
schedule — in the bare two-tuple form. Lightning steps a scheduler returned
that way once per epoch, so the whole cycle finishes in the first few epochs
and the rest of the run trains at the floor learning rate. Nothing raises.
(MLV711.)

Everything else is deliberately correct: logits out of `forward`,
`cross_entropy` on logits, `training_step` returns the loss, no manual
`backward()` / `step()`.
"""
from __future__ import annotations

import lightning.pytorch as pl
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchmetrics


class ConversionClassifier(pl.LightningModule):
    def __init__(self, in_features: int = 5, width: int = 128,
                 classes: int = 2, lr: float = 3e-3,
                 weight_decay: float = 1e-2, max_lr: float = 1e-2,
                 total_steps: int = 4000) -> None:
        super().__init__()
        self.save_hyperparameters()
        self.backbone = nn.Sequential(
            nn.Linear(in_features, width),
            nn.BatchNorm1d(width),
            nn.GELU(),
            nn.Dropout(0.25),
            nn.Linear(width, width // 2),
            nn.GELU(),
        )
        self.head = nn.Linear(width // 2, classes)
        self.train_accuracy = torchmetrics.Accuracy(task="multiclass",
                                                    num_classes=classes)
        self.val_accuracy = torchmetrics.Accuracy(task="multiclass",
                                                  num_classes=classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.backbone(x))

    def training_step(self, batch, batch_idx):
        features, labels = batch
        logits = self(features)
        loss = F.cross_entropy(logits, labels)
        self.train_accuracy(logits.argmax(dim=1), labels)
        self.log_dict({"train/loss": loss,
                       "train/acc": self.train_accuracy},
                      prog_bar=True, on_step=True, on_epoch=True)
        return loss

    def validation_step(self, batch, batch_idx):
        features, labels = batch
        logits = self(features)
        loss = F.cross_entropy(logits, labels)
        self.val_accuracy(logits.argmax(dim=1), labels)
        self.log_dict({"val/loss": loss, "val/acc": self.val_accuracy},
                      prog_bar=True)
        return loss

    def test_step(self, batch, batch_idx):
        features, labels = batch
        logits = self(features)
        self.log("test/acc", (logits.argmax(dim=1) == labels).float().mean())

    def configure_optimizers(self):
        optimizer = torch.optim.AdamW(self.parameters(),
                                      lr=self.hparams.lr,
                                      weight_decay=self.hparams.weight_decay)
        scheduler = torch.optim.lr_scheduler.OneCycleLR(
            optimizer, max_lr=self.hparams.max_lr,
            total_steps=self.hparams.total_steps)
        return [optimizer], [scheduler]
