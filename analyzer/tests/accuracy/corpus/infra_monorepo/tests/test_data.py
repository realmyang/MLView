"""pytest unit tests. Not a pipeline: nothing here trains anything."""
from __future__ import annotations

import pytest
import torch

from libs.vision.data import eval_transform, train_transform


def test_eval_transform_is_deterministic():
    transform = eval_transform(64)
    names = [type(t).__name__ for t in transform.transforms]
    assert "RandomResizedCrop" not in names
    assert "RandomHorizontalFlip" not in names


def test_train_transform_augments():
    transform = train_transform(64)
    names = [type(t).__name__ for t in transform.transforms]
    assert "RandomHorizontalFlip" in names


@pytest.mark.parametrize("size", [32, 64, 224])
def test_transforms_accept_sizes(size):
    assert train_transform(size) is not None
    assert eval_transform(size) is not None


def test_tensor_shape():
    batch = torch.zeros(2, 3, 64, 64)
    assert batch.shape == (2, 3, 64, 64)
