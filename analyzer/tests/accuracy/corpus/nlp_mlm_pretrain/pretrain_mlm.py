"""Pre-train a small RoBERTa from scratch with the HuggingFace Trainer."""

import math

import numpy as np
from transformers import (
    AutoConfig,
    AutoModelForMaskedLM,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
    set_seed,
)

from corpus import SEED, prepare

CHECKPOINT = "roberta-base"


def build_model(tokenizer, layers=6, hidden=384, heads=6):
    config = AutoConfig.from_pretrained(
        CHECKPOINT,
        num_hidden_layers=layers,
        hidden_size=hidden,
        num_attention_heads=heads,
        intermediate_size=hidden * 4,
        vocab_size=len(tokenizer),
    )
    return AutoModelForMaskedLM.from_config(config)


def compute_metrics(eval_pred):
    """Masked-token accuracy, computed over the positions the collator masked."""
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)
    masked = labels != -100
    hits = (predictions[masked] == labels[masked]).sum()
    return {"masked_accuracy": float(hits) / float(masked.sum())}


def training_arguments(out_dir, epochs=3):
    return TrainingArguments(
        output_dir=out_dir,
        overwrite_output_dir=True,
        num_train_epochs=epochs,
        per_device_train_batch_size=32,
        per_device_eval_batch_size=64,
        gradient_accumulation_steps=4,
        learning_rate=5e-4,
        weight_decay=0.01,
        warmup_ratio=0.06,
        lr_scheduler_type="cosine",
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        logging_steps=100,
        bf16=True,
        seed=SEED,
        data_seed=SEED,
        report_to=[],
    )


def main(data_files="shards/*.txt", out_dir="runs/mlm"):
    set_seed(SEED)
    tokenizer, blocks = prepare(CHECKPOINT, data_files)
    model = build_model(tokenizer)
    collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer, mlm=True, mlm_probability=0.15
    )
    trainer = Trainer(
        model=model,
        args=training_arguments(out_dir),
        train_dataset=blocks["train"],
        eval_dataset=blocks["test"],
        data_collator=collator,
        compute_metrics=compute_metrics,
    )
    trainer.train()
    metrics = trainer.evaluate()
    metrics["perplexity"] = math.exp(metrics["eval_loss"])
    trainer.save_model(out_dir)
    tokenizer.save_pretrained(out_dir)
    return metrics


if __name__ == "__main__":
    print(main())
