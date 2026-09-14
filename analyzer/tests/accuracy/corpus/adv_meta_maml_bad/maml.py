"""MAML-style meta-learning with an inner and an outer loop - written wrong.

The correct shape is: for each task, take K gradient steps on the support set
with `create_graph=True` so the outer loss is differentiable through them, then
evaluate the adapted parameters on the query set and back-propagate the summed
query loss through the meta-optimizer, which is zeroed once per meta-batch.

This version drops the second-order graph, never zeroes the meta-optimizer,
draws the query set from the same indices as the support set, and meta-tests
without leaving train mode.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
INNER_STEPS = 5
INNER_LR = 0.01
META_BATCH = 4
META_ITERATIONS = 10_000
N_WAY = 5
K_SHOT = 5


class MetaLearner(nn.Module):
    """A small convolutional backbone with a linear head."""

    def __init__(self, num_classes: int) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Dropout(0.2),
        )
        self.head = nn.Linear(64, num_classes)

    def forward(self, x):
        return self.head(self.features(x).flatten(1))


def split_task(images, labels):
    """DEFECT: the support and the query halves are drawn from the same slice,
    so every query example was already adapted on."""
    support = slice(0, N_WAY * K_SHOT)
    query = slice(0, N_WAY * K_SHOT)
    return images[support], labels[support], images[query], labels[query]


def inner_adapt(model, support_x, support_y):
    """K steps of SGD on the support set.

    DEFECT: create_graph is left at its default False, so the adapted weights
    carry no graph back to the meta-parameters and the outer update is a
    first-order approximation nobody asked for.
    """
    weights = [parameter for parameter in model.parameters()]
    for _ in range(INNER_STEPS):
        logits = model(support_x)
        inner_loss = F.cross_entropy(logits, support_y)
        gradients = torch.autograd.grad(inner_loss, weights, create_graph=False)
        weights = [w - INNER_LR * g for w, g in zip(weights, gradients)]
    return weights


def meta_train(model, task_loader, meta_optimizer):
    model.train()
    for iteration, (images, labels) in enumerate(task_loader):
        images = images.to(DEVICE)
        labels = labels.to(DEVICE)
        support_x, support_y, query_x, query_y = split_task(images, labels)
        inner_adapt(model, support_x, support_y)
        query_logits = model(query_x)
        meta_loss = F.cross_entropy(query_logits, query_y)
        # DEFECT: the meta-optimizer is never zeroed, so every meta-update is
        # the running sum of every task seen so far.
        meta_loss.backward()
        meta_optimizer.step()
        if iteration % 100 == 0:
            print("iteration %d meta loss %.4f" % (iteration, meta_loss.item()))


def meta_test(model, task_loader):
    """DEFECT: no model.eval() and no torch.no_grad(), so the BatchNorm2d
    running statistics keep moving and the dropout keeps firing while the
    held-out tasks are being scored."""
    correct = 0
    seen = 0
    for images, labels in task_loader:
        images = images.to(DEVICE)
        labels = labels.to(DEVICE)
        logits = model(images)
        correct += int((logits.argmax(dim=-1) == labels).sum().item())
        seen += int(labels.shape[0])
    return correct / max(1, seen)


def main() -> None:
    torch.manual_seed(0)
    images = torch.randn(4096, 1, 28, 28)
    labels = torch.randint(0, N_WAY, (4096,))
    train_tasks = TensorDataset(images[:3072], labels[:3072])
    test_tasks = TensorDataset(images[3072:], labels[3072:])

    train_loader = DataLoader(train_tasks, batch_size=N_WAY * K_SHOT * 2,
                              shuffle=True, drop_last=True)
    test_loader = DataLoader(test_tasks, batch_size=N_WAY * K_SHOT * 2,
                             shuffle=False, drop_last=True)

    model = MetaLearner(N_WAY).to(DEVICE)
    meta_optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    meta_train(model, train_loader, meta_optimizer)
    print("meta-test accuracy %.4f" % meta_test(model, test_loader))
    # DEFECT: the whole module is pickled instead of its state_dict.
    torch.save(model, "maml.pt")


if __name__ == "__main__":
    main()
