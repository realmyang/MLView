# MLVIEW-EXPECT-NONE: MLV706
"""The trap: manual optimisation done correctly. The gradient calls are exactly
the ones the bad fixture makes, and the single line that makes them legitimate
is self.automatic_optimization = False in __init__."""
import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.nn.functional as F

pl.seed_everything(0)


class ManualLit(pl.LightningModule):
    def __init__(self, features: int = 16, classes: int = 3) -> None:
        super().__init__()
        self.automatic_optimization = False
        self.net = nn.Sequential(nn.Linear(features, 32), nn.ReLU())
        self.head = nn.Linear(32, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.net(x))

    def training_step(self, batch, batch_idx):
        features, labels = batch
        optimizer = self.optimizers()
        optimizer.zero_grad()
        loss = F.cross_entropy(self(features), labels)
        self.manual_backward(loss)
        optimizer.step()
        return loss

    def configure_optimizers(self):
        return torch.optim.Adam(self.parameters(), lr=1e-3)
