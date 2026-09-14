"""Anchors, box coding and post-processing (defective twin).

Defect A (no rule covers it yet): `postprocess` runs NMS over every anchor
before the score threshold, so the 0.45-IoU suppression is decided by
background boxes and the `max_detections` cut throws away real detections.
"""

from __future__ import annotations

from typing import List, Tuple

import torch
from torchvision.ops import batched_nms, box_iou

STRIDES = (8, 16, 32)
ANCHOR_SIZES = (
    ((10, 13), (16, 30), (33, 23)),
    ((30, 61), (62, 45), (59, 119)),
    ((116, 90), (156, 198), (373, 326)),
)


def make_anchors(image_size: int = 640) -> List[torch.Tensor]:
    """One (H*W*A, 4) anchor tensor per pyramid level, in xyxy."""
    levels: List[torch.Tensor] = []
    for stride, sizes in zip(STRIDES, ANCHOR_SIZES):
        grid = image_size // stride
        ys, xs = torch.meshgrid(torch.arange(grid), torch.arange(grid), indexing="ij")
        centres = torch.stack([xs, ys], dim=-1).reshape(-1, 2).float()
        centres = (centres + 0.5) * stride
        per_level = []
        for width, height in sizes:
            half = torch.tensor([width, height], dtype=torch.float32) / 2.0
            per_level.append(torch.cat([centres - half, centres + half], dim=-1))
        levels.append(torch.cat(per_level, dim=0))
    return levels


def encode_boxes(anchors: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
    """Target boxes as offsets from their matched anchor."""
    anchor_wh = anchors[:, 2:] - anchors[:, :2]
    anchor_ctr = anchors[:, :2] + anchor_wh / 2.0
    target_wh = targets[:, 2:] - targets[:, :2]
    target_ctr = targets[:, :2] + target_wh / 2.0
    delta_ctr = (target_ctr - anchor_ctr) / anchor_wh
    delta_wh = torch.log(target_wh / anchor_wh + 1e-9)
    return torch.cat([delta_ctr, delta_wh], dim=-1)


def decode_boxes(anchors: torch.Tensor, deltas: torch.Tensor) -> torch.Tensor:
    """The inverse of `encode_boxes`, back to xyxy pixels."""
    anchor_wh = anchors[:, 2:] - anchors[:, :2]
    anchor_ctr = anchors[:, :2] + anchor_wh / 2.0
    centre = deltas[:, :2] * anchor_wh + anchor_ctr
    size = torch.exp(deltas[:, 2:].clamp(max=8.0)) * anchor_wh
    return torch.cat([centre - size / 2.0, centre + size / 2.0], dim=-1)


def assign_targets(anchors: torch.Tensor, gt_boxes: torch.Tensor,
                   positive_iou: float = 0.5, negative_iou: float = 0.4):
    """Max-IoU assignment: (matched index per anchor, positive mask)."""
    if gt_boxes.numel() == 0:
        empty = torch.zeros(anchors.shape[0], dtype=torch.long)
        return empty, torch.zeros(anchors.shape[0], dtype=torch.bool)
    iou = box_iou(anchors, gt_boxes)
    best_iou, best_index = iou.max(dim=1)
    positive = best_iou >= positive_iou
    ignore = (best_iou > negative_iou) & (~positive)
    best_index[ignore] = -1
    return best_index, positive


def postprocess(cls_logits: torch.Tensor, box_deltas: torch.Tensor,
                anchors: torch.Tensor, score_threshold: float = 0.25,
                iou_threshold: float = 0.45, max_detections: int = 300
                ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Defect A: suppression first, threshold last, and no no_grad wrapper."""
    scores, labels = cls_logits.softmax(dim=-1).max(dim=-1)
    boxes = decode_boxes(anchors, box_deltas)
    order = batched_nms(boxes, scores, labels, iou_threshold)
    order = order[:max_detections]
    boxes, scores, labels = boxes[order], scores[order], labels[order]
    keep = scores >= score_threshold
    return boxes[keep], scores[keep], labels[keep]
