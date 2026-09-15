"""Two project-local callbacks, the shape a real Lightning repo ships.

Neither of these is a training loop and neither is a defect.
"""
from __future__ import annotations

import time

import lightning.pytorch as pl
from lightning.pytorch.callbacks import Callback


class EpochTimer(Callback):
    """Logs wall time per epoch. Pure instrumentation."""

    def __init__(self) -> None:
        super().__init__()
        self._started = 0.0

    def on_train_epoch_start(self, trainer: pl.Trainer,
                             module: pl.LightningModule) -> None:
        self._started = time.perf_counter()

    def on_train_epoch_end(self, trainer: pl.Trainer,
                           module: pl.LightningModule) -> None:
        elapsed = time.perf_counter() - self._started
        module.log("time/epoch_seconds", elapsed, prog_bar=False)


class FreezeBackbone(Callback):
    """Freezes the backbone for the first `epochs` epochs, then unfreezes."""

    def __init__(self, epochs: int = 2) -> None:
        super().__init__()
        self.epochs = epochs

    def on_train_epoch_start(self, trainer: pl.Trainer,
                             module: pl.LightningModule) -> None:
        frozen = trainer.current_epoch < self.epochs
        for parameter in module.backbone.parameters():
            parameter.requires_grad = not frozen
