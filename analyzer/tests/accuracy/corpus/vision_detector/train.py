"""Detector training, validation and the mAP report.

The loss is built here so the criterion keeps its identity: classification is
`BCEWithLogitsLoss` over raw logits, regression is `SmoothL1Loss` over the
encoded deltas of the positive anchors only.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn

from boxes import assign_targets, encode_boxes, make_anchors, postprocess
from dataset import SEED, build_loaders, to_device
from model import build_detector

EPOCHS = 30
BATCH_SIZE = 8
LR = 0.01
WORKERS = 4
DATA_ROOT = "data/coco"
ANNOTATIONS = "data/coco/annotations"


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class DetectionLoss(nn.Module):
    """Objectness BCE over logits plus a box regression on positives."""

    def __init__(self, classes: int = 80) -> None:
        super().__init__()
        self.classification = nn.BCEWithLogitsLoss(reduction="mean")
        self.regression = nn.SmoothL1Loss(reduction="mean")
        self.classes = classes

    def forward(self, cls_logits, box_deltas, anchors, targets):
        total = cls_logits.new_zeros(())
        for index, target in enumerate(targets):
            matched, positive = assign_targets(anchors, target["boxes"])
            one_hot = cls_logits.new_zeros(cls_logits.shape[1], self.classes)
            if positive.any():
                one_hot[positive, target["labels"][matched[positive]]] = 1.0
            total = total + self.classification(cls_logits[index], one_hot)
            if positive.any():
                encoded = encode_boxes(anchors[positive],
                                       target["boxes"][matched[positive]])
                total = total + self.regression(box_deltas[index][positive], encoded)
        return total / max(len(targets), 1)


def train_one_epoch(model, loader, criterion, optimizer, anchors, device) -> float:
    model.train()
    running = 0.0
    batches = 0
    for images, targets in loader:
        images, targets = to_device(images, targets, device)
        optimizer.zero_grad(set_to_none=True)
        cls_logits, box_deltas = model(images)
        loss = criterion(cls_logits, box_deltas, anchors, targets)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
        optimizer.step()
        running += loss.item()
        batches += 1
    return running / max(batches, 1)


@torch.no_grad()
def evaluate_map(model, loader, anchors, device, iou_threshold: float = 0.5) -> float:
    """A single-IoU mAP: match detections to ground truth per image."""
    model.eval()
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
    train_loader, val_loader, test_loader = build_loaders(
        DATA_ROOT, ANNOTATIONS, batch_size=BATCH_SIZE, workers=WORKERS)

    model = build_detector(classes=80)
    model.to(device)
    criterion = DetectionLoss(classes=80)
    optimizer = torch.optim.SGD(model.parameters(), lr=LR, momentum=0.937,
                                weight_decay=5e-4)
    anchors = torch.cat(make_anchors(), dim=0).to(device)

    best = 0.0
    for epoch in range(EPOCHS):
        loss = train_one_epoch(model, train_loader, criterion, optimizer,
                               anchors, device)
        val_map = evaluate_map(model, val_loader, anchors, device)
        print("epoch %d loss %.4f val_mAP50 %.4f" % (epoch, loss, val_map))
        if val_map > best:
            best = val_map
            torch.save(model.state_dict(), "detector_best.pt")

    model.load_state_dict(torch.load("detector_best.pt", map_location=device,
                                     weights_only=True))
    test_map = evaluate_map(model, test_loader, anchors, device)
    print("test mAP50 %.4f" % test_map)
    return test_map


if __name__ == "__main__":
    main()
