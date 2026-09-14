import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

import asyncio


async def batches(loader):
    for batch in loader:
        await asyncio.sleep(0)
        yield batch


async def train(ds, epochs=2):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    async with asyncio.Lock():
        for _ in range(epochs):
            async for xb, yb in batches(loader):
                opt.zero_grad()
                loss = crit(model(xb), yb)
                loss.backward()
                opt.step()
    return model


def main(ds):
    return asyncio.run(train(ds))
