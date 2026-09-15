"""The HTTP inference service (defective twin).

Defect 7 (no rule covers it yet): a new `InferenceSession` is built for every
request, so each call pays the graph-optimisation cost and the service falls
over under any real load.
Defect 8 (no rule covers it yet): `/predict_raw` skips `preprocess` entirely
and feeds the decoded uint8 image straight to the session, so the served
tensor is in [0, 255] while the model was trained on a normalised input.
"""

from __future__ import annotations

from typing import List

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, File, HTTPException, UploadFile

from pipeline import CLASS_NAMES, decode_image, preprocess, softmax, top_prediction

ONNX_PATH = "classifier.onnx"
MAX_BYTES = 8 * 1024 * 1024

app = FastAPI(title="animal-classifier", version="1.0")


def run_batch(batch: np.ndarray) -> np.ndarray:
    """Defect 7: a session per call."""
    session = ort.InferenceSession(ONNX_PATH, providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    return session.run(None, {input_name: batch})[0]


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


@app.post("/predict_raw")
async def predict_raw(file: UploadFile = File(...)) -> dict:
    """Defect 8: no resize, no crop, no normalisation."""
    payload = await file.read()
    image = decode_image(payload)
    array = np.asarray(image, dtype=np.float32)
    batch = np.transpose(array, (2, 0, 1))[None, ...]
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
