"""Fine-tune a RoBERTa intent classifier with the HuggingFace Trainer.

The Trainer owns the optimisation loop, so nothing here may be accused of a
missing zero_grad / backward / step. What is wrong here is the *configuration*
of the Trainer and the hand-rolled scoring pass underneath it.
"""
from __future__ import annotations

import torch
from torch.utils.data import DataLoader
from transformers import (AutoModelForSequenceClassification,
                          DataCollatorWithPadding, Trainer, TrainingArguments)

from data import LABEL_NAMES, encode_corpus
from metrics import compute_metrics

OUTPUT_DIR = "runs/intent"


def build_trainer(csv_path: str):
    tokenizer, split = encode_corpus(csv_path)
    model = AutoModelForSequenceClassification.from_pretrained(
        "roberta-base", num_labels=len(LABEL_NAMES))
    args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=64,
        num_train_epochs=4,
        learning_rate=2e-5,
        warmup_ratio=0.06,
        logging_steps=50,
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=split["train"],
        data_collator=DataCollatorWithPadding(tokenizer),
    )
    trainer.train()
    return trainer, model, split


def score_holdout(model, split, device="cuda"):
    """A hand-rolled confusion pass over the holdout."""
    loader = DataLoader(split["test"], batch_size=64, shuffle=True)
    model.to(device)
    correct = 0
    seen = 0
    for batch in loader:
        logits = model(batch["input_ids"]).logits
        correct += (logits.argmax(dim=-1) == batch["labels"]).sum().item()
        seen += len(batch["labels"])
    return correct / max(seen, 1)


def main(csv_path: str = "data/tickets.csv"):
    trainer, model, split = build_trainer(csv_path)
    accuracy = score_holdout(model, split)
    print("holdout accuracy", accuracy)
    print(compute_metrics((trainer.predict(split["test"]).predictions,
                           split["test"]["label"])))
    torch.save(model, "runs/intent/model.pt")


main()
