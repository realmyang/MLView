# MLVIEW-EXPECT: MLV706 line=25 confidence>=0.6
"""A LightningModule that back-propagates by hand while Lightning still owns the
optimisation, so the gradients are applied twice per batch."""
import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.nn.functional as F

pl.seed_everything(0)


class LitClassifier(pl.LightningModule):
    def __init__(self, features: int = 16, classes: int = 3) -> None:
        super().__init__()
        self.net = nn.Sequential(nn.Linear(features, 32), nn.ReLU())
        self.head = nn.Linear(32, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.net(x))

    def training_step(self, batch, batch_idx):
        features, labels = batch
        loss = F.cross_entropy(self(features), labels)
        self.log("train_loss", loss)
        loss.backward()
        return loss

    def configure_optimizers(self):
        return torch.optim.Adam(self.parameters(), lr=1e-3)
