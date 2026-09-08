"""The training entrypoint - corrected twin.

Fix  2 (MLV201): the gradients are zeroed at the top of every step.
Fix  9 (MLV205): only the scalar loss is accumulated.
Fix 11 (MLV501): each batch is moved to the same device as the model.
Fix  3 (MLV301): validate() switches to eval mode and back.
Fix 10 (MLV302): validate() runs under torch.no_grad().
Fix  8 (MLV112): the loaders are built from a __main__ guard.
"""

import torch
import torch.nn as nn
import torch.optim as optim

from config import DEVICE, EPOCHS, LEARNING_RATE, WEIGHT_DECAY, set_seed
from data import build_loaders
from model import SmallCNN


def train(train_loader, val_loader) -> nn.Module:
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
            images = images.to(device, non_blocking=True)
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()
        accuracy = validate(model, val_loader, device)
        print("epoch %d  loss %.4f  val_acc %.4f"
              % (epoch, running_loss / len(train_loader), accuracy))
    return model


@torch.no_grad()
def validate(model: SmallCNN, loader, device) -> float:
    model.eval()
    correct = 0
    total = 0
    for images, labels in loader:
        images = images.to(device)
        labels = labels.to(device)
        logits = model(images)
        preds = logits.argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)
    model.train()
    return correct / max(total, 1)


def main() -> nn.Module:
    set_seed()
    train_loader, val_loader, _test_loader = build_loaders()
    return train(train_loader, val_loader)


if __name__ == "__main__":
    main()
