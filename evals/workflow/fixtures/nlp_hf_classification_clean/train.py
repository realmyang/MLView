"""The correct twin of `nlp_hf_classification/train.py`.

The Trainer is given a held-out split, a metric function and an evaluation
strategy; the hand-rolled confusion pass switches to eval mode, runs under
`torch.no_grad()`, moves its batches, and does not shuffle the holdout.
"""
from __future__ import annotations

import torch
from torch.utils.data import DataLoader
from transformers import (AutoModelForSequenceClassification,
                          DataCollatorWithPadding, Trainer, TrainingArguments,
                          set_seed)

from data import LABEL_NAMES, SEED, encode_corpus
from metrics import compute_metrics

OUTPUT_DIR = "runs/intent"


def build_trainer(csv_path: str):
    set_seed(SEED)
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
        eval_strategy="epoch",
        seed=SEED,
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=split["train"],
        eval_dataset=split["test"],
        data_collator=DataCollatorWithPadding(tokenizer),
        compute_metrics=compute_metrics,
    )
    trainer.train()
    return trainer, model, split


def score_holdout(model, split, device):
    """A hand-rolled confusion pass, written honestly."""
    test_loader = DataLoader(split["test"], batch_size=64, shuffle=False)
    model.to(device)
    model.eval()
    correct = 0
    seen = 0
    with torch.no_grad():
        for batch in test_loader:
            input_ids = batch["input_ids"].to(device)
            labels = batch["labels"].to(device)
            logits = model(input_ids).logits
            correct += (logits.argmax(dim=-1) == labels).sum().item()
            seen += len(labels)
    return correct / max(seen, 1)


def main(csv_path: str = "data/tickets.csv"):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    trainer, model, split = build_trainer(csv_path)
    print("holdout accuracy", score_holdout(model, split, device))
    print(trainer.evaluate())
    torch.save(model.state_dict(), "runs/intent/model.pt")


main()
