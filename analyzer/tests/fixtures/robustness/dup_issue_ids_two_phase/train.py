"""ROB-03 (two files, the realistic shape): a warm-up phase and a fine-tune
phase in one function, each with its own loop over the same loader.

MLV401 fires on both `criterion(...)` calls. They are on different lines, but
the rule anchors each finding on the enclosing scope's qualname plus the
callee symbol - identical for the two - so both findings are minted with the
same `Issue.id`.
"""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from model import SmallNet


def train(dataset, epochs: int = 2):
    model = SmallNet()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.CrossEntropyLoss()
    loader = DataLoader(dataset, batch_size=8, shuffle=True)

    for _ in range(epochs):                     # warm-up
        for images, labels in loader:
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()

    for _ in range(epochs):                     # fine-tune
        for images, labels in loader:
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
    return model
