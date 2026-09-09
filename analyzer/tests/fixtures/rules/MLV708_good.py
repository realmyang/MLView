# MLVIEW-EXPECT-NONE: MLV708
"""The trap: TrainingArguments sets no eval_strategy at all, so a rule keying on
that alone would fire - but the Trainer is given both an eval_dataset and a
compute_metrics callback and is evaluated explicitly, which is evaluation."""
from transformers import (AutoModelForSequenceClassification, Trainer,
                          TrainingArguments, set_seed)

CHECKPOINT = "distilbert-base-uncased"


def fine_tune(encoded, compute_metrics):
    set_seed(42)
    model = AutoModelForSequenceClassification.from_pretrained(CHECKPOINT,
                                                               num_labels=2)
    args = TrainingArguments(
        output_dir="runs/sentiment",
        per_device_train_batch_size=16,
        num_train_epochs=3,
        learning_rate=2e-5,
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=encoded["train"],
        eval_dataset=encoded["validation"],
        compute_metrics=compute_metrics,
    )
    trainer.train()
    trainer.evaluate()
    return trainer
