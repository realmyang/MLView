"""MoCo v2 self-supervised pre-training - the defective version.

The momentum-contrast shape: a query encoder trained by gradient descent, a key
encoder that is only ever an exponential moving average of it, and a negative
queue of past keys. Nine defects are planted. The four that decide whether the
method works at all - the key encoder handed to the optimizer, the key forward
that keeps its gradient, the EMA update run with autograd on, and the queue
that stores live tensors - are contrastive-learning-specific and have no rule
in the catalog today.
"""

from __future__ import annotations

import copy

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

MOMENTUM = 0.999
TEMPERATURE = 0.07
QUEUE_SIZE = 65_536
EPOCHS = 200
# DEFECT: cuda is named outright with no torch.cuda.is_available() check.
DEVICE = torch.device("cuda")


class Encoder(nn.Module):
    def __init__(self, feature_dim: int = 128) -> None:
        super().__init__()
        self.backbone = nn.Sequential(
            nn.Conv2d(3, 64, 3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d(1),
        )
        self.dropout = nn.Dropout(0.1)
        self.projector = nn.Sequential(
            nn.Linear(64, 128), nn.ReLU(), nn.Linear(128, feature_dim))

    def forward(self, images):
        features = self.backbone(images).flatten(1)
        return F.normalize(self.projector(self.dropout(features)), dim=-1)


class MoCo(nn.Module):
    def __init__(self, feature_dim: int = 128) -> None:
        super().__init__()
        self.query_encoder = Encoder(feature_dim)
        self.key_encoder = copy.deepcopy(self.query_encoder)
        # DEFECT: the negative queue is a plain Python list of live tensors, so
        # every key ever enqueued keeps its autograd graph alive.
        self.queue = []

    def momentum_update(self) -> None:
        """DEFECT: no torch.no_grad() and no .data, so the EMA update is
        recorded by autograd and the key encoder is no longer a pure copy."""
        for key_param, query_param in zip(self.key_encoder.parameters(),
                                          self.query_encoder.parameters()):
            key_param.mul_(MOMENTUM).add_((1.0 - MOMENTUM) * query_param)

    def forward(self, view_q, view_k):
        query = self.query_encoder(view_q)
        # DEFECT: the key forward is not wrapped in torch.no_grad(), so the key
        # encoder accumulates gradients it must never receive.
        key = self.key_encoder(view_k)
        positive = torch.einsum("nc,nc->n", [query, key]).unsqueeze(-1)
        if self.queue:
            negatives = torch.cat(self.queue, dim=0)
            negative = torch.einsum("nc,kc->nk", [query, negatives])
            logits = torch.cat([positive, negative], dim=1)
        else:
            logits = positive
        return logits / TEMPERATURE, key


def build_loader(root: str):
    augment = transforms.Compose([
        transforms.RandomResizedCrop(32, scale=(0.2, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
    ])
    train_set = datasets.CIFAR10(root, train=True, transform=augment,
                                 download=False)
    # DEFECT: the pre-training loader does not shuffle, so every epoch draws
    # its negatives from the same neighbourhood of CIFAR's class-ordered file.
    # DEFECT: num_workers=8 with no `if __name__ == "__main__":` guard.
    return DataLoader(train_set, batch_size=256, shuffle=False, num_workers=8,
                      drop_last=True)


def pretrain(model, loader, optimizer, criterion) -> float:
    model.train()
    running_loss = 0.0
    for images, _ in loader:
        view_q = images.to(DEVICE)
        view_k = torch.flip(images, dims=[-1]).to(DEVICE)
        logits, key = model(view_q, view_k)
        labels = torch.zeros(logits.size(0), dtype=torch.long, device=DEVICE)
        # DEFECT: the logits are softmaxed before CrossEntropyLoss, which
        # log-softmaxes them a second time.
        loss = criterion(F.softmax(logits, dim=1), labels)
        # DEFECT: the gradients are never zeroed.
        loss.backward()
        optimizer.step()
        model.momentum_update()
        model.queue.append(key)
        if len(model.queue) * key.size(0) > QUEUE_SIZE:
            model.queue.pop(0)
        # DEFECT: the running loss keeps the live tensor.
        running_loss += loss
    return running_loss


def linear_probe(model, loader, classifier) -> float:
    """DEFECT: no model.eval() and no torch.no_grad(), so the 0.1 dropout and
    the BatchNorm running stats both move while the probe is measured."""
    correct = 0
    seen = 0
    for images, labels in loader:
        features = model.query_encoder(images.to(DEVICE))
        predicted = classifier(features).argmax(dim=-1)
        correct += int((predicted == labels.to(DEVICE)).sum())
        seen += labels.numel()
    return correct / max(seen, 1)


def main() -> None:
    # DEFECT: nothing seeds torch, numpy or random anywhere in this project.
    loader = build_loader("data/cifar10")
    model = MoCo().to(DEVICE)
    criterion = nn.CrossEntropyLoss()
    # DEFECT: the optimizer is built over model.parameters(), which includes
    # the key encoder - it must only ever be an EMA of the query encoder.
    optimizer = torch.optim.SGD(model.parameters(), lr=0.03, momentum=0.9,
                                weight_decay=1e-4)
    classifier = nn.Linear(128, 10).to(DEVICE)

    for epoch in range(EPOCHS):
        loss = pretrain(model, loader, optimizer, criterion)
        if epoch % 20 == 0:
            print("epoch %d loss %.4f probe %.4f"
                  % (epoch, float(loss), linear_probe(model, loader, classifier)))

    # DEFECT: the whole module is pickled rather than its state_dict.
    torch.save(model, "moco.pt")


main()
