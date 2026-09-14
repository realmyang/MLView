"""The architecture the checkpoint was trained with, re-declared for serving.

Training lives in another repository; this file exists only so
`load_state_dict` has something to load into.
"""
from __future__ import annotations

import torch
import torch.nn as nn
from torchvision.models import mobilenet_v3_small


class ProductTagger(nn.Module):
    def __init__(self, classes: int = 6) -> None:
        super().__init__()
        backbone = mobilenet_v3_small(weights=None)
        features = backbone.classifier[-1].in_features
        backbone.classifier = nn.Sequential(*list(backbone.classifier)[:-1])
        self.backbone = backbone
        self.head = nn.Linear(features, classes)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.head(self.backbone(images))
