"""Pre-processing definitions (defective twin).

Defect 1 (no rule covers it yet): the service normalises with ImageNet
statistics that the training script does not use, and crops to 224 from a
resize of 224 rather than 256 - so every served image is a different
distribution from every trained image, and the accuracy drops silently.
Defect 2 (no rule covers it yet): `top_prediction` applies a softmax to a
model that already exports probabilities, so the reported confidence is the
softmax of a softmax and is always near uniform.
"""

from __future__ import annotations

import io

import numpy as np
import torch
from PIL import Image
from torchvision import transforms

IMAGE_SIZE = 224
RESIZE_SIZE = 256
SERVING_MEAN = (0.5, 0.5, 0.5)
SERVING_STD = (0.5, 0.5, 0.5)
TRAINING_MEAN = (0.485, 0.456, 0.406)
TRAINING_STD = (0.229, 0.224, 0.225)
CLASS_NAMES = ("cat", "dog", "fox", "wolf")


def serving_transform() -> transforms.Compose:
    """Defect 1: different crop geometry and different normalisation."""
    return transforms.Compose([
        transforms.Resize(IMAGE_SIZE),
        transforms.CenterCrop(IMAGE_SIZE),
        transforms.ToTensor(),
        transforms.Normalize(SERVING_MEAN, SERVING_STD),
    ])


def training_transform() -> transforms.Compose:
    return transforms.Compose([
        transforms.RandomResizedCrop(IMAGE_SIZE, scale=(0.5, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize(TRAINING_MEAN, TRAINING_STD),
    ])


def eval_transform() -> transforms.Compose:
    """What the training script scores on: the ImageNet statistics."""
    return transforms.Compose([
        transforms.Resize(RESIZE_SIZE),
        transforms.CenterCrop(IMAGE_SIZE),
        transforms.ToTensor(),
        transforms.Normalize(TRAINING_MEAN, TRAINING_STD),
    ])


def decode_image(payload: bytes) -> Image.Image:
    return Image.open(io.BytesIO(payload)).convert("RGB")


def preprocess(payload: bytes) -> np.ndarray:
    image = decode_image(payload)
    tensor = serving_transform()(image).unsqueeze(0)
    return tensor.numpy().astype(np.float32)


def softmax(scores: np.ndarray) -> np.ndarray:
    shifted = scores - scores.max(axis=-1, keepdims=True)
    exponentiated = np.exp(shifted)
    return exponentiated / exponentiated.sum(axis=-1, keepdims=True)


def top_prediction(scores: np.ndarray) -> dict:
    """Defect 2: a softmax on top of the exported softmax."""
    probabilities = softmax(scores)[0]
    index = int(probabilities.argmax())
    return {"label": CLASS_NAMES[index], "score": float(probabilities[index])}
