"""The model half of ROB-03's two-phase repro: `forward` returns softmaxed
probabilities, which is what makes MLV401 fire on the loss call that consumes
them.
"""
import torch.nn as nn
import torch.nn.functional as F


class SmallNet(nn.Module):
    def __init__(self, classes: int = 3):
        super().__init__()
        self.fc = nn.Linear(16, classes)

    def forward(self, x):
        return F.softmax(self.fc(x), dim=1)
