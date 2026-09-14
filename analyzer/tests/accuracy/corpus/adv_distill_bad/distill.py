"""Knowledge distillation, written wrong.

A frozen teacher should score the batch in eval mode under no_grad, its logits
should be detached, the soft loss should be a KL divergence between two
temperature-softened distributions scaled by T**2, and the hard loss should see
raw student logits. This file gets six of those wrong at once.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

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
    """DEFECT: the teacher logits are not detached, so the gradient of the soft
    loss flows back into the teacher as well as into the student.

    DEFECT: the KL term is not multiplied by TEMPERATURE**2, so the soft loss
    shrinks by a factor of 16 at T=4 and ALPHA no longer means what it says.
    """
    soft_student = F.log_softmax(student_logits / TEMPERATURE, dim=-1)
    soft_teacher = F.softmax(teacher_logits / TEMPERATURE, dim=-1)
    soft_loss = F.kl_div(soft_student, soft_teacher, reduction="batchmean")
    # DEFECT: softmax is applied before cross_entropy, which log-softmaxes it
    # a second time.
    probabilities = F.softmax(student_logits, dim=-1)
    hard_loss = F.cross_entropy(probabilities, labels)
    return ALPHA * soft_loss + (1.0 - ALPHA) * hard_loss


def train(student, teacher, loader, optimizer):
    student.train()
    # DEFECT: the teacher is left in train mode, so its dropout fires and its
    # BatchNorm1d running statistics keep being updated by the student's
    # batches - the "frozen" teacher is neither frozen nor deterministic.
    running_loss = 0.0
    for epoch in range(EPOCHS):
        for features, labels in loader:
            features = features.to(DEVICE)
            labels = labels.to(DEVICE)
            teacher_logits = teacher(features)
            student_logits = student(features)
            loss = distillation_loss(student_logits, teacher_logits, labels)
            # DEFECT: zero_grad is never called, so gradients accumulate across
            # every batch of every epoch.
            loss.backward()
            optimizer.step()
            # DEFECT: the running loss keeps the live tensor.
            running_loss += loss
        print("epoch %d loss %s" % (epoch, running_loss))
    return running_loss


def main() -> None:
    torch.manual_seed(0)
    features = torch.randn(4096, 128)
    labels = torch.randint(0, NUM_CLASSES, (4096,))
    dataset = TensorDataset(features, labels)
    loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)

    teacher = Teacher(128, NUM_CLASSES).to(DEVICE)
    teacher.load_state_dict(torch.load("teacher.pt", weights_only=True))
    student = Student(128, NUM_CLASSES).to(DEVICE)
    optimizer = torch.optim.AdamW(student.parameters(), lr=1e-3)

    train(student, teacher, loader, optimizer)
    torch.save(student.state_dict(), "student.pt")


if __name__ == "__main__":
    main()
