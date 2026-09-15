"""The evaluation report: clean accuracy, TTA accuracy, robust accuracy under
FGSM and PGD, calibration before and after temperature scaling, and a handful
of Grad-CAM overlays.

This module trains nothing. It loads a checkpoint, runs five evaluation passes
over the test loader and writes a JSON report next to a directory of PNGs.
"""

from __future__ import annotations

import argparse
import json
import os
import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from explain import (GradCAM, TemperatureScaler, expected_calibration_error,
                     fgsm, layer_by_name, pgd, tta_logits)
from network import ResNetClassifier


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def eval_transform() -> transforms.Compose:
    return transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
    ])


def build_loaders(args):
    val_set = datasets.ImageFolder(os.path.join(args.data, "val"),
                                   transform=eval_transform())
    test_set = datasets.ImageFolder(os.path.join(args.data, "test"),
                                    transform=eval_transform())
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False,
                            num_workers=args.workers, pin_memory=True)
    test_loader = DataLoader(test_set, batch_size=args.batch_size, shuffle=False,
                             num_workers=args.workers, pin_memory=True)
    return val_loader, test_loader


def load_model(args, device):
    model = ResNetClassifier(num_classes=args.num_classes)
    state = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(state["model"])
    return model.to(device).eval()


@torch.no_grad()
def collect_logits(model, loader, device):
    """One pass that keeps the logits so calibration does not re-run the model."""
    model.eval()
    logits_out = []
    labels_out = []
    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        logits_out.append(model(images).cpu())
        labels_out.append(labels)
    return torch.cat(logits_out), torch.cat(labels_out)


@torch.no_grad()
def clean_accuracy(model, loader, device):
    model.eval()
    correct = 0
    seen = 0
    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        correct += (model(images).argmax(dim=1) == labels).sum().item()
        seen += labels.numel()
    return correct / max(1, seen)


@torch.no_grad()
def tta_accuracy(model, loader, device):
    model.eval()
    correct = 0
    seen = 0
    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        probabilities = tta_logits(model, images)
        correct += (probabilities.argmax(dim=1) == labels).sum().item()
        seen += labels.numel()
    return correct / max(1, seen)


def robust_accuracy(model, loader, device, attack: str, args):
    """No no_grad decorator: the attack needs gradients w.r.t. the input."""
    model.eval()
    correct = 0
    seen = 0
    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        if attack == "fgsm":
            adversarial = fgsm(model, images, labels, args.epsilon)
        else:
            adversarial = pgd(model, images, labels, args.epsilon,
                              args.alpha, args.pgd_steps)
        with torch.no_grad():
            correct += (model(adversarial).argmax(dim=1) == labels).sum().item()
        seen += labels.numel()
    return correct / max(1, seen)


def calibration_report(model, val_loader, test_loader, device):
    val_logits, val_labels = collect_logits(model, val_loader, device)
    test_logits, test_labels = collect_logits(model, test_loader, device)
    before = expected_calibration_error(F.softmax(test_logits, dim=1), test_labels)
    scaler = TemperatureScaler().fit(val_logits, val_labels)
    with torch.no_grad():
        scaled = F.softmax(scaler(test_logits), dim=1)
    after = expected_calibration_error(scaled, test_labels)
    return {"eceBefore": before, "eceAfter": after,
            "temperature": float(torch.exp(scaler.log_temperature).item())}


def write_cams(model, loader, device, out_dir, limit=8):
    os.makedirs(out_dir, exist_ok=True)
    target_layer = layer_by_name(model, "backbone.layer4")
    written = 0
    with GradCAM(model, target_layer) as cam:
        for images, _labels in loader:
            images = images.to(device, non_blocking=True)
            maps = cam(images)
            for index in range(maps.shape[0]):
                if written >= limit:
                    return written
                array = (maps[index, 0].detach().cpu().numpy() * 255).astype("uint8")
                np.save(os.path.join(out_dir, "cam_%03d.npy" % written), array)
                written += 1
    return written


def parse_args():
    parser = argparse.ArgumentParser(description="Explainability and robustness report")
    parser.add_argument("--data", default="data/imagenette")
    parser.add_argument("--checkpoint", default="runs/cls/best.pt")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--num-classes", type=int, default=10)
    parser.add_argument("--epsilon", type=float, default=4.0 / 255.0)
    parser.add_argument("--alpha", type=float, default=1.0 / 255.0)
    parser.add_argument("--pgd-steps", type=int, default=10)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--out", default="runs/report")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_everything(args.seed)
    device = pick_device()
    os.makedirs(args.out, exist_ok=True)

    val_loader, test_loader = build_loaders(args)
    model = load_model(args, device)

    report = {
        "clean": clean_accuracy(model, test_loader, device),
        "tta": tta_accuracy(model, test_loader, device),
        "fgsm": robust_accuracy(model, test_loader, device, "fgsm", args),
        "pgd": robust_accuracy(model, test_loader, device, "pgd", args),
    }
    report.update(calibration_report(model, val_loader, test_loader, device))
    report["cams"] = write_cams(model, test_loader, device,
                                os.path.join(args.out, "cams"))

    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
