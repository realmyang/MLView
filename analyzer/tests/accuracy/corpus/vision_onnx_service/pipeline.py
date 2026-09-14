"""The one definition of the inference pre-processing.

Both the training evaluation path and the HTTP service import `SERVING_MEAN`,
`SERVING_STD` and `serving_transform()` from here, so the two cannot drift.
"""

from __future__ import annotations

import io

import numpy as np
import torch
from PIL import Image
from torchvision import transforms

IMAGE_SIZE = 224
RESIZE_SIZE = 256
SERVING_MEAN = (0.485, 0.456, 0.406)
SERVING_STD = (0.229, 0.224, 0.225)
CLASS_NAMES = ("cat", "dog", "fox", "wolf")


def serving_transform() -> transforms.Compose:
    """Resize, centre crop, tensor, normalise - deterministic by construction."""
    return transforms.Compose([
        transforms.Resize(RESIZE_SIZE),
        transforms.CenterCrop(IMAGE_SIZE),
        transforms.ToTensor(),
        transforms.Normalize(SERVING_MEAN, SERVING_STD),
    ])


def training_transform() -> transforms.Compose:
    """The training pipeline: the serving one plus the random operators."""
    return transforms.Compose([
        transforms.RandomResizedCrop(IMAGE_SIZE, scale=(0.5, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize(SERVING_MEAN, SERVING_STD),
    ])


def decode_image(payload: bytes) -> Image.Image:
    return Image.open(io.BytesIO(payload)).convert("RGB")


def preprocess(payload: bytes) -> np.ndarray:
    """bytes -> (1, 3, 224, 224) float32, ready for the ONNX session."""
    image = decode_image(payload)
    tensor = serving_transform()(image).unsqueeze(0)
    return tensor.numpy().astype(np.float32)


def softmax(scores: np.ndarray) -> np.ndarray:
    """The model exports logits, so the service applies the softmax itself."""
    shifted = scores - scores.max(axis=-1, keepdims=True)
    exponentiated = np.exp(shifted)
    return exponentiated / exponentiated.sum(axis=-1, keepdims=True)


def top_prediction(scores: np.ndarray) -> dict:
    probabilities = softmax(scores)[0]
    index = int(probabilities.argmax())
    return {"label": CLASS_NAMES[index], "score": float(probabilities[index])}
