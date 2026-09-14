"""The shared backbone. Logits out."""
from __future__ import annotations

import torch
import torch.nn as nn
from torchvision.models import resnet18


class VisionClassifier(nn.Module):
    def __init__(self, classes: int = 12, dropout: float = 0.2,
                 pretrained: bool = True) -> None:
        super().__init__()
        backbone = resnet18(weights="IMAGENET1K_V1" if pretrained else None)
        features = backbone.fc.in_features
        backbone.fc = nn.Identity()
        self.backbone = backbone
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(features, classes)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.head(self.dropout(self.backbone(images)))
