"""A LightningModule: the framework owns the loop, so the absence rules must
stay off it entirely (the `negation_absent` gate, iron law 4).

There is no manual `zero_grad`, `backward`, `step`, `model.eval()` or
`no_grad()` anywhere here - and that is correct.
"""
from __future__ import annotations

import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset, random_split

SEED = 21


class LitClassifier(pl.LightningModule):
    def __init__(self, features: int = 64, classes: int = 10, lr: float = 1e-3) -> None:
        super().__init__()
        self.save_hyperparameters()
        self.encoder = nn.Sequential(
            nn.Linear(features, 128),
            nn.ReLU(),
            nn.Dropout(0.2),
        )
        self.head = nn.Linear(128, classes)
        self.lr = lr

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.encoder(x))

    def training_step(self, batch, batch_idx):
        features, labels = batch
        loss = F.cross_entropy(self(features), labels)
        self.log("train_loss", loss)
        return loss

    def validation_step(self, batch, batch_idx):
        features, labels = batch
        logits = self(features)
        loss = F.cross_entropy(logits, labels)
        acc = (logits.argmax(dim=1) == labels).float().mean()
        self.log_dict({"val_loss": loss, "val_acc": acc})
        return loss

    def configure_optimizers(self):
        return torch.optim.AdamW(self.parameters(), lr=self.lr)


def build_loaders(dataset: TensorDataset):
    generator = torch.Generator().manual_seed(SEED)
    train_ds, val_ds = random_split(dataset, [9000, 1000], generator=generator)
    return (DataLoader(train_ds, batch_size=64, shuffle=True),
            DataLoader(val_ds, batch_size=256, shuffle=False))


def main(dataset: TensorDataset) -> LitClassifier:
    pl.seed_everything(SEED, workers=True)
    train_loader, val_loader = build_loaders(dataset)
    model = LitClassifier()
    trainer = pl.Trainer(max_epochs=5, accelerator="auto", deterministic=True)
    trainer.fit(model, train_loader, val_loader)
    return model
