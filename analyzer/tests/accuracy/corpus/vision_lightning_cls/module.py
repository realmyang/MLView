"""The LightningModule, and the Trainer that drives it.

`training_step` returns the loss, `configure_optimizers` returns the one-cycle
schedule with `interval: "step"`, and Lightning owns `zero_grad`, `backward`,
`step`, `model.eval()` and `no_grad` - none of them are written here.
"""

from __future__ import annotations

import pytorch_lightning as pl
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchmetrics
from pytorch_lightning.callbacks import EarlyStopping, ModelCheckpoint
from torchvision.models import resnet34

from datamodule import ImageDataModule

NUM_CLASSES = 37
EPOCHS = 20
MAX_LR = 3e-4
SEED = 8080


class ImageClassifier(pl.LightningModule):
    """A ResNet-34 with a fresh head, logits out."""

    def __init__(self, num_classes: int = NUM_CLASSES, max_lr: float = MAX_LR,
                 steps_per_epoch: int = 100, epochs: int = EPOCHS) -> None:
        super().__init__()
        self.save_hyperparameters()
        backbone = resnet34(weights=None)
        backbone.fc = nn.Linear(backbone.fc.in_features, num_classes)
        self.model = backbone
        self.criterion = nn.CrossEntropyLoss(label_smoothing=0.1)
        self.train_accuracy = torchmetrics.Accuracy(task="multiclass",
                                                    num_classes=num_classes)
        self.val_accuracy = torchmetrics.Accuracy(task="multiclass",
                                                  num_classes=num_classes)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.model(images)

    def training_step(self, batch, batch_idx: int) -> torch.Tensor:
        images, targets = batch
        logits = self(images)
        loss = self.criterion(logits, targets)
        self.train_accuracy(logits.argmax(dim=1), targets)
        self.log("train_loss", loss, on_step=True, on_epoch=True, prog_bar=True)
        self.log("train_acc", self.train_accuracy, on_epoch=True)
        return loss

    def validation_step(self, batch, batch_idx: int) -> torch.Tensor:
        images, targets = batch
        logits = self(images)
        loss = self.criterion(logits, targets)
        self.val_accuracy(logits.argmax(dim=1), targets)
        self.log("val_loss", loss, prog_bar=True)
        self.log("val_acc", self.val_accuracy, prog_bar=True)
        return loss

    def test_step(self, batch, batch_idx: int) -> torch.Tensor:
        images, targets = batch
        logits = self(images)
        loss = F.cross_entropy(logits, targets)
        self.log("test_loss", loss)
        self.log("test_acc", (logits.argmax(dim=1) == targets).float().mean())
        return loss

    def configure_optimizers(self):
        """A one-cycle schedule, stepped per batch - hence interval: step."""
        optimizer = torch.optim.AdamW(self.parameters(), lr=self.hparams.max_lr,
                                      weight_decay=0.05)
        scheduler = torch.optim.lr_scheduler.OneCycleLR(
            optimizer,
            max_lr=self.hparams.max_lr,
            steps_per_epoch=self.hparams.steps_per_epoch,
            epochs=self.hparams.epochs,
        )
        return {
            "optimizer": optimizer,
            "lr_scheduler": {"scheduler": scheduler, "interval": "step",
                             "frequency": 1},
        }


def main() -> dict:
    pl.seed_everything(SEED, workers=True)
    data = ImageDataModule()
    data.setup()
    model = ImageClassifier(steps_per_epoch=len(data.train_dataloader()))

    trainer = pl.Trainer(
        max_epochs=EPOCHS,
        accelerator="auto",
        gradient_clip_val=1.0,
        callbacks=[
            ModelCheckpoint(monitor="val_acc", mode="max", save_top_k=1),
            EarlyStopping(monitor="val_loss", patience=5),
        ],
        log_every_n_steps=20,
    )
    trainer.fit(model, datamodule=data)
    return trainer.test(model, datamodule=data)[0]


if __name__ == "__main__":
    main()
