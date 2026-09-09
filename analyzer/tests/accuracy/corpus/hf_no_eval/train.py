"""A HuggingFace fine-tune that never evaluates anything.

Planted defect: the Trainer is given a train_dataset and nothing else - no
eval_dataset, no compute_metrics, and TrainingArguments names no evaluation
strategy - so the only number the run ever prints is the training loss and the
checkpoint that is kept is the last one rather than the best one.
"""
from __future__ import annotations

from datasets import load_dataset
from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                          DataCollatorWithPadding, Trainer, TrainingArguments,
                          set_seed)

CHECKPOINT = "distilbert-base-uncased"
MAX_LENGTH = 192
SEED = 17


def build(dataset_name: str = "yelp_polarity"):
    set_seed(SEED)
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT)
    raw = load_dataset(dataset_name)

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True, max_length=MAX_LENGTH)

    encoded = raw.map(tokenize, batched=True)
    model = AutoModelForSequenceClassification.from_pretrained(CHECKPOINT,
                                                               num_labels=2)
    return tokenizer, encoded, model


def fine_tune(output_dir: str = "runs/yelp"):
    tokenizer, encoded, model = build()
    args = TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=32,
        num_train_epochs=2,
        learning_rate=3e-5,
        logging_steps=50,
        save_strategy="epoch",
        seed=SEED,
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=encoded["train"],
        data_collator=DataCollatorWithPadding(tokenizer),
    )
    trainer.train()
    trainer.save_model(output_dir + "/final")
    return trainer


if __name__ == "__main__":
    fine_tune()
