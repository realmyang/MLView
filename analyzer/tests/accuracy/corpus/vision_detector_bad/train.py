"""Detector training and the mAP report (defective twin).

Defect G: the classification branch returns raw logits and the loss is
`nn.BCELoss`, which expects probabilities in [0, 1] - the sigmoid is missing.
Defect H: the training step never zeroes the gradients.
Defect I: the gradient norm is clipped after `optimizer.step()`, so the clip
applies to gradients that have already been used.
Defect J: `evaluate_map` runs with the model still in train mode and with the
autograd graph switched on.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn

from boxes import assign_targets, encode_boxes, make_anchors, postprocess
from dataset import (SEED, TEST_LOADER, TRAIN_LOADER, VAL_LOADER, to_device)
from model import build_detector

EPOCHS = 30
LR = 0.01


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class DetectionLoss(nn.Module):
    """Defect G: BCELoss over raw logits."""

    def __init__(self, classes: int = 80) -> None:
        super().__init__()
        self.classification = nn.BCELoss(reduction="mean")
        self.regression = nn.SmoothL1Loss(reduction="mean")
        self.classes = classes

    def forward(self, cls_logits, box_deltas, anchors, targets):
        parts = []
        for index, target in enumerate(targets):
            matched, positive = assign_targets(anchors, target["boxes"])
            one_hot = cls_logits.new_zeros(cls_logits.shape[1], self.classes)
            if positive.any():
                one_hot[positive, target["labels"][matched[positive]]] = 1.0
            parts.append(self.classification(cls_logits[index], one_hot))
            if positive.any():
                encoded = encode_boxes(anchors[positive],
                                       target["boxes"][matched[positive]])
                parts.append(self.regression(box_deltas[index][positive], encoded))
        return torch.stack(parts).sum() / max(len(targets), 1)


def train_one_epoch(model, loader, criterion, optimizer, anchors, device) -> float:
    """Defects H and I: no zero_grad, and the clip runs after the step."""
    model.train()
    running = 0.0
    batches = 0
    for images, targets in loader:
        images, targets = to_device(images, targets, device)
        cls_logits, box_deltas = model(images)
        loss = criterion(cls_logits, box_deltas, anchors, targets)
        loss.backward()
        optimizer.step()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
        running += loss.item()
        batches += 1
    return running / max(batches, 1)


def evaluate_map(model, loader, anchors, device, iou_threshold: float = 0.5) -> float:
    """Defect J: no model.eval(), no torch.no_grad()."""
    total_precision = 0.0
    images_seen = 0
    for images, targets in loader:
        images, targets = to_device(images, targets, device)
        cls_logits, box_deltas = model(images)
        for index, target in enumerate(targets):
            boxes, scores, labels = postprocess(cls_logits[index],
                                                box_deltas[index], anchors)
            total_precision += average_precision(boxes, labels, target,
                                                 iou_threshold)
            images_seen += 1
    return total_precision / max(images_seen, 1)


def average_precision(boxes, labels, target, iou_threshold: float) -> float:
    """Precision of one image's detections against its ground truth."""
    from torchvision.ops import box_iou

    if boxes.numel() == 0 or target["boxes"].numel() == 0:
        return 0.0
    iou = box_iou(boxes, target["boxes"])
    best, index = iou.max(dim=1)
    correct = (best >= iou_threshold) & (labels == target["labels"][index])
    return float(correct.float().mean())


def main() -> float:
    seed_everything()
    device = pick_device()

    model = build_detector(classes=80)
    model.to(device)
    criterion = DetectionLoss(classes=80)
    optimizer = torch.optim.SGD(model.parameters(), lr=LR, momentum=0.937,
                                weight_decay=5e-4)
    anchors = torch.cat(make_anchors(), dim=0).to(device)

    best = 0.0
    for epoch in range(EPOCHS):
        loss = train_one_epoch(model, TRAIN_LOADER, criterion, optimizer,
                               anchors, device)
        val_map = evaluate_map(model, VAL_LOADER, anchors, device)
        print("epoch %d loss %.4f val_mAP50 %.4f" % (epoch, loss, val_map))
        if val_map > best:
            best = val_map
            torch.save(model.state_dict(), "detector_best.pt")

    test_map = evaluate_map(model, TEST_LOADER, anchors, device)
    print("test mAP50 %.4f" % test_map)
    return test_map


if __name__ == "__main__":
    main()
