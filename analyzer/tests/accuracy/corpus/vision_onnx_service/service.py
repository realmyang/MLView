"""The HTTP inference service.

One ONNX session, created once at startup; every request goes through the
same `preprocess` the training script's evaluation path used.
"""

from __future__ import annotations

from typing import List

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, File, HTTPException, UploadFile

from pipeline import CLASS_NAMES, preprocess, softmax, top_prediction

ONNX_PATH = "classifier.onnx"
MAX_BYTES = 8 * 1024 * 1024

app = FastAPI(title="animal-classifier", version="1.0")
_session: ort.InferenceSession = None


def get_session() -> ort.InferenceSession:
    """Lazily create the session; ONNX Runtime sessions are thread-safe."""
    global _session
    if _session is None:
        _session = ort.InferenceSession(
            ONNX_PATH, providers=["CPUExecutionProvider"])
    return _session


def run_batch(batch: np.ndarray) -> np.ndarray:
    session = get_session()
    input_name = session.get_inputs()[0].name
    return session.run(None, {input_name: batch})[0]


@app.on_event("startup")
def warm_up() -> None:
    session = get_session()
    dummy = np.zeros((1, 3, 224, 224), dtype=np.float32)
    session.run(None, {session.get_inputs()[0].name: dummy})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "classes": list(CLASS_NAMES)}


@app.post("/predict")
async def predict(file: UploadFile = File(...)) -> dict:
    payload = await file.read()
    if len(payload) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="image too large")
    batch = preprocess(payload)
    logits = run_batch(batch)
    return top_prediction(logits)


@app.post("/predict_batch")
async def predict_batch(files: List[UploadFile] = File(...)) -> dict:
    tensors = []
    for item in files:
        payload = await item.read()
        tensors.append(preprocess(payload))
    batch = np.concatenate(tensors, axis=0)
    logits = run_batch(batch)
    probabilities = softmax(logits)
    best = probabilities.argmax(axis=-1)
    return {
        "predictions": [
            {"label": CLASS_NAMES[int(index)], "score": float(row[int(index)])}
            for index, row in zip(best, probabilities)
        ]
    }
