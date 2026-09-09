# MLVIEW-EXPECT-NONE: MLV707
"""The trap: training_step returns a dict rather than a bare tensor, which is the
other shape Lightning accepts. A rule that only looked for `return <name>` would
call this a missing loss."""
import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.nn.functional as F

pl.seed_everything(0)


class DictLit(pl.LightningModule):
    def __init__(self, features: int = 16, classes: int = 3) -> None:
        super().__init__()
        self.net = nn.Sequential(nn.Linear(features, 32), nn.ReLU())
        self.head = nn.Linear(32, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.net(x))

    def training_step(self, batch, batch_idx):
        features, labels = batch
        logits = self(features)
        loss = F.cross_entropy(logits, labels)
        self.log("train_loss", loss)
        return {"loss": loss, "logits": logits.detach()}

    def configure_optimizers(self):
        return torch.optim.AdamW(self.parameters(), lr=1e-3)
