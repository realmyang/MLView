"""The framework half of the mixed fixture: one ordinary torch training step.

PERF-03's set-aside diagnostic can only be exercised on a workspace that really
does contain a non-framework file, which is the shape a real repository has and
which no other fixture in this tree had. `report_utils.py` beside this file is
that half: it mentions no framework token, imports nothing from here and is
imported by nothing here, so the prefilter sets it aside and says so.
"""

from __future__ import annotations

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


def build_loader() -> DataLoader:
    data = TensorDataset(torch.zeros(8, 3), torch.zeros(8).long())
    return DataLoader(data, batch_size=4, shuffle=True)


def train() -> nn.Module:
    model = nn.Linear(3, 2)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    criterion = nn.CrossEntropyLoss()
    for features, labels in build_loader():
        optimizer.zero_grad()
        loss = criterion(model(features), labels)
        loss.backward()
        optimizer.step()
    return model
