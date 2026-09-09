"""FW-RECOG positive fixture: the Lightning hook table, module and datamodule.

A `LightningModule` never calls its own methods - `Trainer.fit(model, ...)`
does - so before this every op in `training_step` and every op in
`validation_step` hung off one class node that `stages.unit_stage` pins to
`model` by its base. The result was a correct program whose stage line read
*"not detected: objective, eval"*.

Each hook is now a unit in the lane the framework runs it in, and `trainer.fit`
draws a `control` edge into them. Nothing here is a defect: this file is about
recognition, and the seeds and the guarded evaluation are deliberate.
"""
from __future__ import annotations

import lightning as L
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset, random_split

SEED = 13


class TabularModule(L.LightningDataModule):
    def __init__(self, dataset: TensorDataset, batch_size: int = 64) -> None:
        super().__init__()
        self.dataset = dataset
        self.batch_size = batch_size
        self.train_set = None
        self.val_set = None

    def setup(self, stage: str = "fit") -> None:
        generator = torch.Generator().manual_seed(SEED)
        self.train_set, self.val_set = random_split(
            self.dataset, [0.8, 0.2], generator=generator)

    def train_dataloader(self):
        return DataLoader(self.train_set, batch_size=self.batch_size, shuffle=True)

    def val_dataloader(self):
        return DataLoader(self.val_set, batch_size=self.batch_size, shuffle=False)


class TabularClassifier(L.LightningModule):
    def __init__(self, features: int = 32, classes: int = 4, lr: float = 1e-3) -> None:
        super().__init__()
        self.save_hyperparameters()
        self.backbone = nn.Sequential(nn.Linear(features, 64), nn.ReLU())
        self.head = nn.Linear(64, classes)
        self.lr = lr

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.backbone(x))

    def training_step(self, batch, batch_idx):
        features, labels = batch
        loss = F.cross_entropy(self(features), labels)
        self.log("train_loss", loss)
        return loss

    def validation_step(self, batch, batch_idx):
        features, labels = batch
        logits = self(features)
        loss = F.cross_entropy(logits, labels)
        self.log_dict({"val_loss": loss, "val_acc": (logits.argmax(1) == labels)
                       .float().mean()})
        return loss

    def test_step(self, batch, batch_idx):
        features, labels = batch
        return F.cross_entropy(self(features), labels)

    def configure_optimizers(self):
        return torch.optim.AdamW(self.parameters(), lr=self.lr)

    def on_validation_epoch_end(self) -> None:
        self.log("epochs", float(self.current_epoch))


def main(dataset: TensorDataset):
    L.seed_everything(SEED, workers=True)
    data = TabularModule(dataset)
    model = TabularClassifier()
    trainer = L.Trainer(max_epochs=5, deterministic=True)
    trainer.fit(model, datamodule=data)
    trainer.test(model, datamodule=data)
    return model
