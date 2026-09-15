# MLVIEW-EXPECT-NONE: MLV205
"""REC-02: a validation loop under `torch.no_grad()` builds no autograd graph,
so `running_vloss += vloss` there keeps nothing alive and is correct code.

R18(a) widened MLV205 from "the training loop" to any accumulating loop and so
inherited every validation loop ever written; this is the shape the PyTorch
`introyt` tutorial ships (`beginner_source/introyt/trainingyt.py:307`).
"""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train_one_epoch(model, criterion, optimizer, train_loader):
    model.train()
    running_loss = 0.0
    for features, labels in train_loader:
        optimizer.zero_grad()
        loss = criterion(model(features), labels)
        loss.backward()
        optimizer.step()
        running_loss += loss.item()
    return running_loss


def validate(model, criterion, val_loader):
    model.eval()
    running_vloss = 0.0
    with torch.no_grad():
        for vfeatures, vlabels in val_loader:
            voutputs = model(vfeatures)
            vloss = criterion(voutputs, vlabels)
            running_vloss += vloss
    return running_vloss


def run(train_set: TensorDataset, val_set: TensorDataset, epochs: int = 2):
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.01)
    train_loader = DataLoader(train_set, batch_size=32, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=32, shuffle=False)
    for _epoch in range(epochs):
        train_one_epoch(model, criterion, optimizer, train_loader)
        validate(model, criterion, val_loader)
    return model
