"""Shape tests for the shared backbone."""
from __future__ import annotations

import torch

from libs.vision.model import VisionClassifier


def test_forward_shape():
    model = VisionClassifier(classes=5, pretrained=False)
    model.eval()
    with torch.no_grad():
        out = model(torch.zeros(2, 3, 64, 64))
    assert out.shape == (2, 5)


def test_head_is_replaced():
    model = VisionClassifier(classes=7, pretrained=False)
    assert model.head.out_features == 7
