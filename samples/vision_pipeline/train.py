"""The training entrypoint.

Planted here: MLV201 (gradients are never zeroed), MLV205 (the loss tensor is
accumulated), MLV501 (the model moves to the GPU, the batches do not),
MLV301 (validate() never calls model.eval()) and MLV302 (it builds an autograd
graph it never uses).
"""

import torch
import torch.nn as nn
import torch.optim as optim

from config import DEVICE, EPOCHS, LEARNING_RATE, WEIGHT_DECAY
from data import train_loader, val_loader
from model import SmallCNN


def train() -> nn.Module:
    device = torch.device(DEVICE)
    model = SmallCNN()
    model.to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE,
                           weight_decay=WEIGHT_DECAY)

    running_loss = 0.0
    model.train()
    for epoch in range(EPOCHS):
        for images, labels in train_loader:
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss
        accuracy = validate(model, val_loader)
        print("epoch %d  loss %.4f  val_acc %.4f"
              % (epoch, running_loss / len(train_loader), accuracy))
    return model


def validate(model: SmallCNN, loader) -> float:
    correct = 0
    total = 0
    for images, labels in loader:
        logits = model(images)
        preds = logits.argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)
    return correct / max(total, 1)
