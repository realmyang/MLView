"""Metric-learning heads: ArcFace, a triplet loss with a batch-hard miner, and
an L2-normalised embedding trunk.

The ArcFace head is the shape worth reading: it returns *logits* - cosine
similarities scaled by `s` with an additive angular margin on the target class -
and is paired with a plain `nn.CrossEntropyLoss`. The margin lives in the head,
not in the loss, which is why the pairing is correct.
"""

from __future__ import annotations

import math
from typing import Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models


class EmbeddingNet(nn.Module):
    """Backbone -> BNNeck -> L2-normalised embedding."""

    def __init__(self, embedding_dim: int = 512, pretrained: bool = False) -> None:
        super().__init__()
        weights = models.ResNet50_Weights.DEFAULT if pretrained else None
        trunk = models.resnet50(weights=weights)
        in_features = trunk.fc.in_features
        trunk.fc = nn.Identity()
        self.trunk = trunk
        self.neck = nn.Sequential(
            nn.Linear(in_features, embedding_dim, bias=False),
            nn.BatchNorm1d(embedding_dim),
        )
        self.embedding_dim = embedding_dim

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return F.normalize(self.neck(self.trunk(images)), p=2.0, dim=1)


class ArcFace(nn.Module):
    """Additive angular margin. Returns logits for nn.CrossEntropyLoss."""

    def __init__(self, embedding_dim: int, num_classes: int,
                 scale: float = 30.0, margin: float = 0.50) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.empty(num_classes, embedding_dim))
        nn.init.xavier_uniform_(self.weight)
        self.scale = scale
        self.margin = margin
        self.cos_m = math.cos(margin)
        self.sin_m = math.sin(margin)
        self.threshold = math.cos(math.pi - margin)
        self.mm = math.sin(math.pi - margin) * margin

    def forward(self, embeddings: torch.Tensor,
                labels: torch.Tensor) -> torch.Tensor:
        cosine = F.linear(F.normalize(embeddings), F.normalize(self.weight))
        sine = torch.sqrt((1.0 - cosine.pow(2)).clamp(0.0, 1.0))
        phi = cosine * self.cos_m - sine * self.sin_m
        phi = torch.where(cosine > self.threshold, phi, cosine - self.mm)
        one_hot = torch.zeros_like(cosine)
        one_hot.scatter_(1, labels.view(-1, 1).long(), 1.0)
        return self.scale * (one_hot * phi + (1.0 - one_hot) * cosine)


def batch_hard_triplets(embeddings: torch.Tensor, labels: torch.Tensor
                        ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """The hardest positive and the hardest negative for every anchor."""
    distances = torch.cdist(embeddings, embeddings, p=2.0)
    same = labels.view(-1, 1).eq(labels.view(1, -1))
    eye = torch.eye(labels.numel(), dtype=torch.bool, device=labels.device)
    positive_mask = same & ~eye
    negative_mask = ~same
    hardest_positive = (distances * positive_mask.float()).max(dim=1).values
    masked = distances + (~negative_mask).float() * 1e6
    hardest_negative = masked.min(dim=1).values
    return embeddings, hardest_positive, hardest_negative


class BatchHardTripletLoss(nn.Module):
    def __init__(self, margin: float = 0.3) -> None:
        super().__init__()
        self.margin = margin

    def forward(self, embeddings: torch.Tensor,
                labels: torch.Tensor) -> torch.Tensor:
        _anchors, positive, negative = batch_hard_triplets(embeddings, labels)
        return F.relu(positive - negative + self.margin).mean()


class CombinedObjective(nn.Module):
    """CrossEntropy over the ArcFace logits plus a weighted triplet term."""

    def __init__(self, embedding_dim: int, num_classes: int,
                 triplet_weight: float = 1.0) -> None:
        super().__init__()
        self.arcface = ArcFace(embedding_dim, num_classes)
        self.cross_entropy = nn.CrossEntropyLoss(label_smoothing=0.1)
        self.triplet = BatchHardTripletLoss()
        self.triplet_weight = triplet_weight

    def forward(self, embeddings: torch.Tensor,
                labels: torch.Tensor) -> torch.Tensor:
        logits = self.arcface(embeddings, labels)
        identity_loss = self.cross_entropy(logits, labels)
        metric_loss = self.triplet(embeddings, labels)
        return identity_loss + self.triplet_weight * metric_loss
