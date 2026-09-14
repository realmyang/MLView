"""The classifier the report explains: a torchvision ResNet-50 trunk with a new
head, and a `num_classes` attribute the TTA helper reads to size its buffer.

There is no training code in this workspace at all - that is deliberate. A
repository whose entrypoint is an evaluation script is a shape MLView has to
read as evaluation, not as a training loop with its optimizer missing.
"""

from __future__ import annotations

import torch
import torch.nn as nn
from torchvision import models


class ResNetClassifier(nn.Module):
    def __init__(self, num_classes: int = 10, pretrained: bool = False,
                 dropout: float = 0.2) -> None:
        super().__init__()
        weights = models.ResNet50_Weights.DEFAULT if pretrained else None
        self.backbone = models.resnet50(weights=weights)
        in_features = self.backbone.fc.in_features
        self.backbone.fc = nn.Identity()
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(in_features, num_classes)
        self.num_classes = num_classes

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.backbone(x)
        return self.classifier(self.dropout(features))

    def features(self, x: torch.Tensor) -> torch.Tensor:
        return self.backbone(x)


def freeze_backbone(model: ResNetClassifier) -> ResNetClassifier:
    for parameter in model.backbone.parameters():
        parameter.requires_grad_(False)
    return model


def parameter_groups(model: ResNetClassifier, backbone_lr: float,
                     head_lr: float):
    return [
        {"params": model.backbone.parameters(), "lr": backbone_lr},
        {"params": list(model.dropout.parameters())
         + list(model.classifier.parameters()), "lr": head_lr},
    ]
