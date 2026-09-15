"""Knowledge distillation, written correctly.

The teacher is loaded once, put in eval mode, frozen with `requires_grad_(False)`
and scored under `torch.no_grad()`; its logits are detached before they reach
the loss. The soft term is a KL divergence between two temperature-softened
distributions multiplied by T**2, and the hard term sees raw student logits.

Nothing here is a defect. Any high-severity finding is a false positive; the
trap is the KLDivLoss pairing, where `log_softmax` on one argument and `softmax`
on the other is the *correct* form and must not be read as MLV401.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

SEED = 67
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
TEMPERATURE = 4.0
ALPHA = 0.7
EPOCHS = 30
BATCH_SIZE = 128
NUM_CLASSES = 10


class Teacher(nn.Module):
    def __init__(self, in_features: int, num_classes: int) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(in_features, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(),
            nn.Dropout(0.5),
            nn.Linear(512, 512),
            nn.ReLU(),
        )
        self.head = nn.Linear(512, num_classes)

    def forward(self, x):
        return self.head(self.body(x))


class Student(nn.Module):
    def __init__(self, in_features: int, num_classes: int) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(in_features, 64),
            nn.BatchNorm1d(64),
            nn.ReLU(),
        )
        self.head = nn.Linear(64, num_classes)

    def forward(self, x):
        return self.head(self.body(x))


def distillation_loss(student_logits, teacher_logits, labels):
    """alpha * T**2 * KL(soft_teacher || soft_student) + (1 - alpha) * CE."""
    soft_student = F.log_softmax(student_logits / TEMPERATURE, dim=-1)
    soft_teacher = F.softmax(teacher_logits / TEMPERATURE, dim=-1)
    soft_loss = F.kl_div(soft_student, soft_teacher, reduction="batchmean")
    soft_loss = soft_loss * (TEMPERATURE ** 2)
    hard_loss = F.cross_entropy(student_logits, labels)
    return ALPHA * soft_loss + (1.0 - ALPHA) * hard_loss


def train_one_epoch(student, teacher, loader, optimizer):
    student.train()
    running = 0.0
    for features, labels in loader:
        features = features.to(DEVICE, non_blocking=True)
        labels = labels.to(DEVICE, non_blocking=True)
        with torch.no_grad():
            teacher_logits = teacher(features).detach()
        optimizer.zero_grad(set_to_none=True)
        student_logits = student(features)
        loss = distillation_loss(student_logits, teacher_logits, labels)
        loss.backward()
        nn.utils.clip_grad_norm_(student.parameters(), 5.0)
        optimizer.step()
        running += loss.item()
    return running / max(1, len(loader))


@torch.no_grad()
def evaluate(student, loader):
    student.eval()
    correct = 0
    seen = 0
    for features, labels in loader:
        features = features.to(DEVICE, non_blocking=True)
        labels = labels.to(DEVICE, non_blocking=True)
        predicted = student(features).argmax(dim=-1)
        correct += int((predicted == labels).sum().item())
        seen += int(labels.shape[0])
    return correct / max(1, seen)


def load_teacher(in_features: int, num_classes: int):
    """Loaded, put in eval mode and frozen before it is ever called."""
    teacher = Teacher(in_features, num_classes).to(DEVICE)
    teacher.load_state_dict(torch.load("teacher.pt", weights_only=True,
                                       map_location=DEVICE))
    teacher.eval()
    teacher.requires_grad_(False)
    return teacher


def main() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    features = torch.randn(8192, 128)
    labels = torch.randint(0, NUM_CLASSES, (8192,))
    generator = torch.Generator().manual_seed(SEED)
    train_set, val_set = torch.utils.data.random_split(
        TensorDataset(features, labels), [0.9, 0.1], generator=generator)

    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=2, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=BATCH_SIZE, shuffle=False,
                            num_workers=2)

    teacher = load_teacher(128, NUM_CLASSES)
    student = Student(128, NUM_CLASSES).to(DEVICE)
    optimizer = torch.optim.AdamW(student.parameters(), lr=1e-3)

    best = 0.0
    for epoch in range(EPOCHS):
        train_loss = train_one_epoch(student, teacher, train_loader, optimizer)
        accuracy = evaluate(student, val_loader)
        if accuracy > best:
            best = accuracy
            torch.save(student.state_dict(), "student.pt")
        print("epoch %d loss %.4f val %.4f" % (epoch, train_loss, accuracy))


if __name__ == "__main__":
    main()
