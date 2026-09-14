"""A shared-backbone multi-task network: one encoder, a dense segmentation
head and a sparse detection head.

Both heads return logits. The segmentation head is paired with
`BCEWithLogitsLoss` and a soft-Dice term computed on `sigmoid(logits)` inside
the loss module; the detection head is paired with `CrossEntropyLoss` for the
class branch and `SmoothL1Loss` for the box branch.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


class ConvNormAct(nn.Sequential):
    def __init__(self, in_channels: int, out_channels: int, stride: int = 1) -> None:
        super().__init__(
            nn.Conv2d(in_channels, out_channels, 3, stride, 1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.SiLU(inplace=True),
        )


class Encoder(nn.Module):
    def __init__(self, widths: Tuple[int, ...] = (32, 64, 128, 256)) -> None:
        super().__init__()
        stages: List[nn.Module] = []
        previous = 3
        for width in widths:
            stages.append(nn.Sequential(ConvNormAct(previous, width, stride=2),
                                        ConvNormAct(width, width)))
            previous = width
        self.stages = nn.ModuleList(stages)
        self.out_channels = list(widths)

    def forward(self, x: torch.Tensor) -> List[torch.Tensor]:
        features: List[torch.Tensor] = []
        out = x
        for stage in self.stages:
            out = stage(out)
            features.append(out)
        return features


class SegmentationHead(nn.Module):
    def __init__(self, in_channels: int, num_classes: int = 1) -> None:
        super().__init__()
        self.project = ConvNormAct(in_channels, 128)
        self.classifier = nn.Conv2d(128, num_classes, kernel_size=1)

    def forward(self, feature: torch.Tensor, size) -> torch.Tensor:
        out = self.classifier(self.project(feature))
        out = F.interpolate(out, size=size, mode="bilinear", align_corners=False)
        # DEFECT: the head now applies a sigmoid while MultiTaskLoss still
        # pairs it with nn.BCEWithLogitsLoss, so the sigmoid is applied twice.
        return torch.sigmoid(out)


class DetectionHead(nn.Module):
    def __init__(self, in_channels: int, num_classes: int = 80,
                 anchors: int = 3) -> None:
        super().__init__()
        self.stem = nn.Sequential(ConvNormAct(in_channels, 256),
                                  ConvNormAct(256, 256))
        self.classifier = nn.Conv2d(256, anchors * num_classes, 1)
        self.regressor = nn.Conv2d(256, anchors * 4, 1)
        self.num_classes = num_classes
        self.anchors = anchors

    def forward(self, feature: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        stem = self.stem(feature)
        batch = stem.shape[0]
        classes = self.classifier(stem).reshape(batch, self.num_classes, -1)
        boxes = self.regressor(stem).reshape(batch, 4, -1)
        return classes, boxes


class MultiTaskNet(nn.Module):
    def __init__(self, num_seg_classes: int = 1, num_det_classes: int = 80) -> None:
        super().__init__()
        self.encoder = Encoder()
        widths = self.encoder.out_channels
        self.segmentation = SegmentationHead(widths[-1], num_seg_classes)
        self.detection = DetectionHead(widths[-1], num_det_classes)

    def forward(self, images: torch.Tensor) -> Dict[str, torch.Tensor]:
        features = self.encoder(images)
        deepest = features[-1]
        masks = self.segmentation(deepest, size=images.shape[-2:])
        classes, boxes = self.detection(deepest)
        return {"masks": masks, "classes": classes, "boxes": boxes}


class MultiTaskLoss(nn.Module):
    """Weighted sum of a masked BCE+Dice term and the two detection terms."""

    def __init__(self, seg_weight: float = 1.0, cls_weight: float = 1.0,
                 box_weight: float = 2.0) -> None:
        super().__init__()
        self.seg_weight = seg_weight
        self.cls_weight = cls_weight
        self.box_weight = box_weight
        self.mask_bce = nn.BCEWithLogitsLoss()
        self.class_ce = nn.CrossEntropyLoss(ignore_index=-1)
        self.box_l1 = nn.SmoothL1Loss(beta=1.0 / 9.0)

    @staticmethod
    def soft_dice(logits: torch.Tensor, target: torch.Tensor,
                  eps: float = 1.0) -> torch.Tensor:
        probabilities = torch.sigmoid(logits)
        intersection = (probabilities * target).sum(dim=(1, 2, 3))
        union = probabilities.sum(dim=(1, 2, 3)) + target.sum(dim=(1, 2, 3))
        return (1.0 - (2.0 * intersection + eps) / (union + eps)).mean()

    def forward(self, outputs: Dict[str, torch.Tensor],
                targets: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        mask_loss = self.mask_bce(outputs["masks"], targets["masks"])
        dice_loss = self.soft_dice(outputs["masks"], targets["masks"])
        class_loss = self.class_ce(outputs["classes"], targets["classes"])
        box_loss = self.box_l1(outputs["boxes"], targets["boxes"])
        total = (self.seg_weight * (mask_loss + dice_loss)
                 + self.cls_weight * class_loss
                 + self.box_weight * box_loss)
        return {"total": total, "mask": mask_loss, "dice": dice_loss,
                "class": class_loss, "box": box_loss}
