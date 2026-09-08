"""Fine-tune a small encoder with the HuggingFace Trainer, then score by hand.

The Trainer owns the optimisation loop, so nothing here may be flagged for a
missing zero_grad / backward / step. The hand-written scoring pass at the bottom
is a different matter: it is a real inference loop with two planted defects.
"""
from __future__ import annotations

import torch
from datasets import load_dataset
from torch.utils.data import DataLoader
from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                          DataCollatorWithPadding, Trainer, TrainingArguments)

from data import build_features
from metrics import compute_metrics

CHECKPOINT = "distilbert-base-uncased"
MAX_LENGTH = 256


def build_datasets(dataset_name: str = "imdb"):
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT)
    raw = load_dataset(dataset_name)

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True, max_length=MAX_LENGTH)

    encoded = raw.map(tokenize, batched=True)
    return tokenizer, encoded


def fine_tune(output_dir: str = "runs/sentiment"):
    tokenizer, encoded = build_datasets()
    model = AutoModelForSequenceClassification.from_pretrained(CHECKPOINT, num_labels=2)
    args = TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=32,
        num_train_epochs=3,
        learning_rate=2e-5,
        eval_strategy="epoch",
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=encoded["train"],
        eval_dataset=encoded["test"],
        data_collator=DataCollatorWithPadding(tokenizer),
        compute_metrics=compute_metrics,
    )
    trainer.train()
    return trainer, model, encoded


def score_by_hand(model, encoded, device="cuda"):
    """A hand-rolled inference pass, and it is wrong in two ways."""
    loader = DataLoader(encoded["test"], batch_size=32, shuffle=True)
    model.to(device)
    hits = 0
    seen = 0
    for batch in loader:
        logits = model(batch["input_ids"]).logits
        hits += (logits.argmax(dim=-1) == batch["labels"]).sum()
        seen += len(batch["labels"])
    return hits / seen


def main():
    trainer, model, encoded = fine_tune()
    features = build_features("data/reviews.csv")
    print(trainer.evaluate())
    print(score_by_hand(model, encoded), len(features["train"][2]))


main()
