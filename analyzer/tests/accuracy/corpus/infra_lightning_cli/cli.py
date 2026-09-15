"""`LightningCLI` entrypoint.

    python cli.py fit --config configs/fit.yaml

There is no hand-written loop anywhere in this project: the CLI builds the
`Trainer`, the `LightningModule` and the `LightningDataModule` from the YAML
and Lightning runs the loop. The absence rules must stay off this project.
"""
from __future__ import annotations

from lightning.pytorch import seed_everything
from lightning.pytorch.callbacks import (EarlyStopping, LearningRateMonitor,
                                         ModelCheckpoint)
from lightning.pytorch.cli import LightningCLI

from callbacks import EpochTimer, FreezeBackbone
from datamodule import ConversionDataModule
from module import ConversionClassifier


class ConversionCLI(LightningCLI):
    def add_arguments_to_parser(self, parser) -> None:
        parser.add_argument("--experiment_name", default="conversion")
        parser.link_arguments("data.batch_size", "model.total_steps",
                              compute_fn=lambda size: 4000)
        parser.set_defaults({
            "trainer.max_epochs": 30,
            "trainer.accelerator": "auto",
            "trainer.gradient_clip_val": 1.0,
            "trainer.deterministic": True,
        })


def default_callbacks():
    return [
        ModelCheckpoint(monitor="val/loss", mode="min", save_top_k=3,
                        filename="{epoch}-{val/loss:.4f}"),
        EarlyStopping(monitor="val/loss", mode="min", patience=6),
        LearningRateMonitor(logging_interval="step"),
        EpochTimer(),
        FreezeBackbone(epochs=2),
    ]


def main() -> None:
    seed_everything(1234, workers=True)
    ConversionCLI(
        model_class=ConversionClassifier,
        datamodule_class=ConversionDataModule,
        trainer_defaults={"callbacks": default_callbacks()},
        save_config_kwargs={"overwrite": True},
    )


if __name__ == "__main__":
    main()
