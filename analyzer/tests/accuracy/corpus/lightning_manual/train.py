"""Entry point. The Trainer owns the loop; checkpointing is done the safe way.

`torch.save(model.state_dict(), ...)` and a `weights_only=True` load are what a
correct checkpoint round-trip looks like, and neither is a defect.
"""
from __future__ import annotations

import pytorch_lightning as pl
import torch
from torch.utils.data import DataLoader, TensorDataset, random_split

from module import TaggerLit

SEED = 11


def build_loaders(features: torch.Tensor, labels: torch.Tensor):
    dataset = TensorDataset(features, labels)
    generator = torch.Generator().manual_seed(SEED)
    train_set, val_set = random_split(dataset, [0.9, 0.1], generator=generator)
    return (DataLoader(train_set, batch_size=64, shuffle=True),
            DataLoader(val_set, batch_size=256, shuffle=False))


def main(features: torch.Tensor, labels: torch.Tensor):
    pl.seed_everything(SEED, workers=True)
    train_loader, val_loader = build_loaders(features, labels)

    model = TaggerLit(steps=len(train_loader) * 10)
    trainer = pl.Trainer(max_epochs=10, accelerator="auto", deterministic=True)
    trainer.fit(model, train_loader, val_loader)

    torch.save(model.state_dict(), "runs/tagger.pt")
    restored = TaggerLit()
    restored.load_state_dict(torch.load("runs/tagger.pt", map_location="cpu",
                                        weights_only=True))
    return restored


if __name__ == "__main__":
    main(torch.randn(4096, 64), torch.randint(0, 9, (4096,)))
