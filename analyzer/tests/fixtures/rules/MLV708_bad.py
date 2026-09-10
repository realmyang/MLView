# MLVIEW-EXPECT: MLV708 line=21 confidence>=0.6
"""A HuggingFace Trainer with no eval_dataset, no compute_metrics and no
evaluation strategy, so the run only ever reports the training loss."""
from transformers import (AutoModelForSequenceClassification, Trainer,
                          TrainingArguments, set_seed)

CHECKPOINT = "distilbert-base-uncased"


def fine_tune(encoded):
    set_seed(42)
    model = AutoModelForSequenceClassification.from_pretrained(CHECKPOINT,
                                                               num_labels=2)
    args = TrainingArguments(
        output_dir="runs/sentiment",
        per_device_train_batch_size=16,
        num_train_epochs=3,
        learning_rate=2e-5,
        save_strategy="epoch",
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=encoded["train"],
    )
    trainer.train()
    return trainer
