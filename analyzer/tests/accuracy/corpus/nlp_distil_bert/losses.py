"""Distillation objectives for a BERT -> small-BERT transfer."""

import torch
import torch.nn as nn
import torch.nn.functional as F


class DistillationLoss(nn.Module):
    """Hinton KD: temperature-scaled KL against the teacher plus the hard loss."""

    def __init__(self, temperature=4.0, alpha=0.5, ignore_index=-100):
        super().__init__()
        self.temperature = temperature
        self.alpha = alpha
        self.hard = nn.CrossEntropyLoss(ignore_index=ignore_index)
        self.soft = nn.KLDivLoss(reduction="batchmean")

    def forward(self, student_logits, teacher_logits, labels):
        t = self.temperature
        soft_targets = F.softmax(teacher_logits / t, dim=-1)
        soft_student = F.log_softmax(student_logits / t, dim=-1)
        soft_loss = self.soft(soft_student, soft_targets) * (t * t)
        hard_loss = self.hard(student_logits, labels)
        return self.alpha * soft_loss + (1.0 - self.alpha) * hard_loss


class HiddenStateLoss(nn.Module):
    """Match the student's hidden states to a projected slice of the teacher's."""

    def __init__(self, student_dim, teacher_dim):
        super().__init__()
        self.project = nn.Linear(student_dim, teacher_dim, bias=False)
        self.criterion = nn.MSELoss()

    def forward(self, student_hidden, teacher_hidden):
        return self.criterion(self.project(student_hidden), teacher_hidden)


@torch.no_grad()
def teacher_logits(teacher, batch):
    """The teacher is frozen: no graph, no dropout, no gradient."""
    outputs = teacher(input_ids=batch["input_ids"],
                      attention_mask=batch["attention_mask"])
    return outputs.logits
