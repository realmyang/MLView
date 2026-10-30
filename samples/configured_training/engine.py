import torch
from torch.nn import functional as F


def train_epoch(student, teacher, batches, optimizer, alpha, temperature):
    student.train()
    teacher.eval()
    for features, labels in batches:
        with torch.no_grad():
            teacher_logits = teacher(features)
        student_logits = student(features)
        supervised = F.cross_entropy(student_logits, labels)
        distilled = F.kl_div(
            F.log_softmax(student_logits / temperature, dim=-1),
            F.softmax(teacher_logits / temperature, dim=-1),
            reduction="batchmean",
        ) * temperature ** 2
        loss = (1 - alpha) * supervised + alpha * distilled
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()


@torch.no_grad()
def evaluate(student, batches):
    student.eval()
    correct, count = 0, 0
    for features, labels in batches:
        predictions = student(features).argmax(dim=-1)
        correct += (predictions == labels).sum().item()
        count += len(labels)
    return correct / count if count else None
