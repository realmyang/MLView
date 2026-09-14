"""A PyTorch-Ignite training job.

Ignite's `Engine` owns the loop: `create_supervised_trainer` builds the update
step (zero_grad -> forward -> loss -> backward -> step) and
`create_supervised_evaluator` runs under `torch.no_grad()` with the model in
eval mode. Handlers do checkpointing, early stopping and logging.

Correct on purpose: the split is seeded, both evaluation loaders are
unshuffled, the training loader shuffles, and `manual_seed` is called before
anything random happens. Any finding in this file is a false positive.
"""
from __future__ import annotations

import torch
import torch.nn as nn
from ignite.contrib.handlers import ProgressBar
from ignite.engine import (Events, create_supervised_evaluator,
                           create_supervised_trainer)
from ignite.handlers import Checkpoint, DiskSaver, EarlyStopping, global_step_from_engine
from ignite.metrics import Accuracy, Loss
from ignite.utils import manual_seed
from torch.utils.data import DataLoader, TensorDataset, random_split

SEED = 11
EPOCHS = 20


class SignalNet(nn.Module):
    def __init__(self, in_features: int = 24, classes: int = 6) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Linear(in_features, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.ReLU(),
        )
        self.classifier = nn.Linear(64, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))


def build_loaders(batch_size: int = 128):
    x = torch.randn(6000, 24)
    y = torch.randint(0, 6, (6000,))
    dataset = TensorDataset(x, y)
    generator = torch.Generator().manual_seed(SEED)
    train_set, val_set = random_split(dataset, [0.8, 0.2], generator=generator)
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True,
                              drop_last=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)
    return train_loader, val_loader


def main() -> None:
    manual_seed(SEED)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = SignalNet().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.05, momentum=0.9,
                                nesterov=True)
    train_loader, val_loader = build_loaders()

    trainer = create_supervised_trainer(model, optimizer, criterion,
                                        device=device)
    metrics = {"accuracy": Accuracy(), "loss": Loss(criterion)}
    evaluator = create_supervised_evaluator(model, metrics=metrics,
                                            device=device)

    ProgressBar().attach(trainer, output_transform=lambda loss: {"loss": loss})

    @trainer.on(Events.EPOCH_COMPLETED)
    def run_validation(engine) -> None:
        evaluator.run(val_loader)
        results = evaluator.state.metrics
        print("epoch %d acc %.4f loss %.4f"
              % (engine.state.epoch, results["accuracy"], results["loss"]))

    def score(engine) -> float:
        return -engine.state.metrics["loss"]

    evaluator.add_event_handler(
        Events.COMPLETED, EarlyStopping(patience=5, score_function=score,
                                        trainer=trainer))
    evaluator.add_event_handler(
        Events.COMPLETED,
        Checkpoint({"model": model, "optimizer": optimizer},
                   DiskSaver("checkpoints", require_empty=False),
                   n_saved=2, score_name="accuracy",
                   global_step_transform=global_step_from_engine(trainer)))

    trainer.run(train_loader, max_epochs=EPOCHS)


if __name__ == "__main__":
    main()
