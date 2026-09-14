"""A batching inference server for the fine-tuned classifier.

Requests are queued for a few milliseconds, padded into one batch, and scored
in a single forward pass. This is the third false-positive trap: it is a
*correct* inference path — eval mode, no autograd, the batch on the model's
device, a deterministic ordering — and it must produce no findings.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

CHECKPOINT = "artifacts/intent-roberta"
MAX_BATCH = 32
MAX_WAIT_MS = 8
MAX_LENGTH = 192
LABEL_NAMES = ["billing", "shipping", "technical", "other"]


@dataclass
class Request:
    text: str
    received_at: float = field(default_factory=time.monotonic)


class IntentService:
    def __init__(self, checkpoint: str = CHECKPOINT, device: str = "cpu"):
        self.device = torch.device(device)
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint)
        self.model = AutoModelForSequenceClassification.from_pretrained(checkpoint)
        self.model.to(self.device)
        self.model.eval()
        self.pending: List[Request] = []

    def submit(self, text: str):
        self.pending.append(Request(text))
        if len(self.pending) >= MAX_BATCH:
            return self.flush()
        return None

    def due(self):
        if not self.pending:
            return False
        waited = time.monotonic() - self.pending[0].received_at
        return waited * 1000.0 >= MAX_WAIT_MS

    def flush(self):
        if not self.pending:
            return []
        batch, self.pending = self.pending[:MAX_BATCH], self.pending[MAX_BATCH:]
        return self.predict([request.text for request in batch])

    @torch.no_grad()
    def predict(self, texts: List[str]):
        encoded = self.tokenizer(texts, padding=True, truncation=True,
                                 max_length=MAX_LENGTH, return_tensors="pt")
        input_ids = encoded["input_ids"].to(self.device)
        attention_mask = encoded["attention_mask"].to(self.device)
        logits = self.model(input_ids=input_ids,
                            attention_mask=attention_mask).logits
        probabilities = logits.softmax(dim=-1)
        confidence, index = probabilities.max(dim=-1)
        return [{"label": LABEL_NAMES[int(i)], "score": float(c)}
                for i, c in zip(index.tolist(), confidence.tolist())]


def serve(service: IntentService, stream):
    answers = []
    for text in stream:
        answer = service.submit(text)
        if answer is None and service.due():
            answer = service.flush()
        if answer:
            answers.extend(answer)
    answers.extend(service.flush())
    return answers
