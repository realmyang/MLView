"""A TorchServe custom handler. Inference only — nothing here trains.

MLView must not claim a training loop, an optimizer or a loss for this
package: there is no `backward()`, no optimizer, no `.fit()`, and the only
loop is over the incoming request batch.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
from typing import Any, Dict, List

import torch
from PIL import Image
from torchvision import transforms

from model_def import ProductTagger

logger = logging.getLogger(__name__)

MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]


class ProductTaggerHandler:
    """The four TorchServe hooks: initialize / preprocess / inference /
    postprocess."""

    def __init__(self) -> None:
        self.model = None
        self.device = torch.device("cpu")
        self.labels: List[str] = []
        self.transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(MEAN, STD),
        ])
        self.initialized = False

    def initialize(self, context) -> None:
        properties = context.system_properties
        model_dir = properties.get("model_dir")
        gpu_id = properties.get("gpu_id")
        self.device = torch.device("cuda:%d" % gpu_id
                                   if torch.cuda.is_available() and gpu_id is not None
                                   else "cpu")
        with open(os.path.join(model_dir, "labels.json"), "r",
                  encoding="utf-8") as handle:
            self.labels = json.load(handle)

        self.model = ProductTagger(classes=len(self.labels))
        state = torch.load(os.path.join(model_dir, "weights.pt"),
                           map_location=self.device, weights_only=True)
        self.model.load_state_dict(state)
        self.model.to(self.device)
        self.model.eval()
        self.initialized = True

    def preprocess(self, requests: List[Dict[str, Any]]) -> torch.Tensor:
        tensors = []
        for request in requests:
            payload = request.get("data") or request.get("body")
            if isinstance(payload, str):
                payload = base64.b64decode(payload)
            image = Image.open(io.BytesIO(payload)).convert("RGB")
            tensors.append(self.transform(image))
        return torch.stack(tensors).to(self.device)

    @torch.no_grad()
    def inference(self, batch: torch.Tensor) -> torch.Tensor:
        logits = self.model(batch)
        return torch.softmax(logits, dim=1)

    def postprocess(self, probabilities: torch.Tensor) -> List[Dict[str, Any]]:
        out = []
        top = torch.topk(probabilities, k=3, dim=1)
        for scores, indices in zip(top.values.tolist(), top.indices.tolist()):
            out.append({self.labels[i]: round(s, 6)
                        for s, i in zip(scores, indices)})
        return out


_SERVICE = ProductTaggerHandler()


def handle(data, context):
    if not _SERVICE.initialized:
        _SERVICE.initialize(context)
    if data is None:
        return None
    batch = _SERVICE.preprocess(data)
    probabilities = _SERVICE.inference(batch)
    return _SERVICE.postprocess(probabilities)
