# MLVIEW-EXPECT-NONE: MLV110
"""The trap: an unshuffled training loader that is driven by a DistributedSampler
(shuffling is the sampler's job), plus a streaming IterableDataset where
shuffle=True is illegal."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import (DataLoader, DistributedSampler, IterableDataset,
                              TensorDataset, random_split)


class StreamingShards(IterableDataset):
    def __init__(self, shards) -> None:
        super().__init__()
        self.shards = shards

    def __iter__(self):
        return iter(self.shards)


def build(dataset: TensorDataset, shards):
    train_ds, val_ds = random_split(dataset, [45000, 5000],
                                    generator=torch.Generator().manual_seed(0))
    sampler = DistributedSampler(train_ds, shuffle=True)
    train_loader = DataLoader(train_ds, batch_size=64, sampler=sampler)
    stream_loader = DataLoader(StreamingShards(shards), batch_size=64)
    val_loader = DataLoader(val_ds, batch_size=256, shuffle=False)
    return train_loader, stream_loader, val_loader


def train(dataset: TensorDataset, shards, epochs: int = 2) -> None:
    torch.manual_seed(0)
    train_loader, _stream, _val = build(dataset, shards)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.01)
    for epoch in range(epochs):
        for features, labels in train_loader:
            optimizer.zero_grad()
            loss = criterion(model(features), labels)
            loss.backward()
            optimizer.step()
