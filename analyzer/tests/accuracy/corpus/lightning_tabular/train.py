"""Entry point. No seed is set anywhere in this project."""
from __future__ import annotations

import pytorch_lightning as pl
from pytorch_lightning.callbacks import EarlyStopping, ModelCheckpoint

from datamodule import TabularDataModule
from module import ChurnClassifier


def main(csv_path: str = "data/churn.csv"):
    data = TabularDataModule(csv_path)
    model = ChurnClassifier()
    trainer = pl.Trainer(
        max_epochs=25,
        accelerator="auto",
        callbacks=[
            ModelCheckpoint(monitor="val_loss", mode="min"),
            EarlyStopping(monitor="val_loss", patience=5),
        ],
    )
    trainer.fit(model, datamodule=data)
    trainer.validate(model, datamodule=data)


if __name__ == "__main__":
    main()
