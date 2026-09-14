"""A thin inference service. No training anywhere in this module.

It loads the checkpoint the training script wrote and applies the *evaluation*
transform — the same one `libs.vision.data` gives the validation loader — so
there is no train/serve skew here either.
"""
from __future__ import annotations

import io
from typing import List

import torch
from PIL import Image

from libs.vision import VisionClassifier, eval_transform

CLASSES: List[str] = ["cat", "dog", "bird", "horse", "sheep", "cow",
                      "elephant", "bear", "zebra", "giraffe", "mouse", "fox"]


class Predictor:
    def __init__(self, checkpoint: str = "artifacts/vision.pt",
                 device: str = "cpu") -> None:
        self.device = torch.device(device)
        self.transform = eval_transform()
        self.model = VisionClassifier(classes=len(CLASSES), pretrained=False)
        state = torch.load(checkpoint, map_location=self.device,
                           weights_only=True)
        self.model.load_state_dict(state)
        self.model.to(self.device)
        self.model.eval()

    @torch.no_grad()
    def predict(self, payload: bytes) -> dict:
        image = Image.open(io.BytesIO(payload)).convert("RGB")
        batch = self.transform(image).unsqueeze(0).to(self.device)
        logits = self.model(batch)
        probabilities = torch.softmax(logits, dim=1)[0]
        index = int(probabilities.argmax())
        return {"label": CLASSES[index],
                "confidence": float(probabilities[index])}
