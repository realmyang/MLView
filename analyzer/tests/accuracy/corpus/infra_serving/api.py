"""A FastAPI wrapper around the same weights. Still no training."""
from __future__ import annotations

import io
from contextlib import asynccontextmanager
from typing import Dict, List

import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel
from torchvision import transforms

from model_def import ProductTagger

LABELS: List[str] = ["shoe", "shirt", "bag", "watch", "hat", "coat"]
WEIGHTS = "artifacts/weights.pt"

_state: Dict[str, object] = {}


class Prediction(BaseModel):
    label: str
    confidence: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    device = torch.device("cpu")
    model = ProductTagger(classes=len(LABELS))
    model.load_state_dict(torch.load(WEIGHTS, map_location=device,
                                     weights_only=True))
    model.to(device)
    model.eval()
    _state["model"] = model
    _state["device"] = device
    _state["transform"] = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406],
                             [0.229, 0.224, 0.225]),
    ])
    yield
    _state.clear()


app = FastAPI(title="product-tagger", version="2.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok" if "model" in _state else "loading"}


@app.post("/predict", response_model=Prediction)
async def predict(file: UploadFile = File(...)) -> Prediction:
    if "model" not in _state:
        raise HTTPException(status_code=503, detail="model not loaded")
    payload = await file.read()
    try:
        image = Image.open(io.BytesIO(payload)).convert("RGB")
    except OSError as exc:
        raise HTTPException(status_code=400, detail="not an image") from exc

    transform = _state["transform"]
    batch = transform(image).unsqueeze(0).to(_state["device"])
    with torch.no_grad():
        logits = _state["model"](batch)
        probabilities = torch.softmax(logits, dim=1)[0]
    index = int(probabilities.argmax())
    return Prediction(label=LABELS[index],
                      confidence=float(probabilities[index]))
