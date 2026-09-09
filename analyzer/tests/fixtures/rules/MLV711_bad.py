# MLVIEW-EXPECT: MLV711 line=28 confidence>=0.6
"""OneCycleLR returned from configure_optimizers with no {"interval": "step"},
so Lightning steps a per-batch schedule once per epoch."""
import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.nn.functional as F

pl.seed_everything(0)


class OneCycleLit(pl.LightningModule):
    def __init__(self, features: int = 16, classes: int = 3, steps: int = 100) -> None:
        super().__init__()
        self.net = nn.Sequential(nn.Linear(features, 32), nn.ReLU())
        self.head = nn.Linear(32, classes)
        self.steps = steps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.net(x))

    def training_step(self, batch, batch_idx):
        features, labels = batch
        return F.cross_entropy(self(features), labels)

    def configure_optimizers(self):
        optimizer = torch.optim.SGD(self.parameters(), lr=1e-2)
        scheduler = torch.optim.lr_scheduler.OneCycleLR(optimizer, max_lr=0.1,
                                                        total_steps=self.steps)
        return {"optimizer": optimizer, "lr_scheduler": {"scheduler": scheduler}}
