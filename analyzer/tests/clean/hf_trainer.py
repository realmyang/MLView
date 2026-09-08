"""A HuggingFace `Trainer` run: `TrainingArguments` + `Trainer` with an
`eval_dataset` and `compute_metrics`.

Like the Lightning file, this exercises the `negation_absent` gate - there is no
hand-written training loop for the absence rules to complain about.
"""
from __future__ import annotations

import numpy as np
from datasets import load_dataset
from sklearn.metrics import accuracy_score, f1_score
from transformers import (AutoModelForSequenceClassification, AutoTokenizer, Trainer,
                          TrainingArguments, set_seed)

SEED = 42
CHECKPOINT = "distilbert-base-uncased"


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return {"accuracy": accuracy_score(labels, preds),
            "f1": f1_score(labels, preds, average="macro")}


def build(dataset_name: str = "imdb"):
    set_seed(SEED)
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT)
    raw = load_dataset(dataset_name)

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True, max_length=256)

    encoded = raw.map(tokenize, batched=True)
    model = AutoModelForSequenceClassification.from_pretrained(CHECKPOINT, num_labels=2)
    return tokenizer, encoded, model


def main(dataset_name: str = "imdb"):
    tokenizer, encoded, model = build(dataset_name)
    args = TrainingArguments(
        output_dir="out/hf",
        seed=SEED,
        data_seed=SEED,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=64,
        num_train_epochs=3,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=encoded["train"],
        eval_dataset=encoded["test"],
        processing_class=tokenizer,
        compute_metrics=compute_metrics,
    )
    trainer.train()
    trainer.evaluate()
    trainer.save_model("out/hf/best")
    return trainer
