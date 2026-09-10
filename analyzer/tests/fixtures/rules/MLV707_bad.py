# MLVIEW-EXPECT: MLV707 line=21 confidence>=0.6
"""A training_step that logs the loss and returns nothing, so Lightning has
nothing to back-propagate and every batch is skipped."""
import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.nn.functional as F

pl.seed_everything(0)


class SilentLit(pl.LightningModule):
    def __init__(self, features: int = 16, classes: int = 3) -> None:
        super().__init__()
        self.net = nn.Sequential(nn.Linear(features, 32), nn.ReLU())
        self.head = nn.Linear(32, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.net(x))

    def training_step(self, batch, batch_idx):
        features, labels = batch
        loss = F.cross_entropy(self(features), labels)
        self.log("train_loss", loss, prog_bar=True)

    def configure_optimizers(self):
        return torch.optim.AdamW(self.parameters(), lr=1e-3)
