"""Pre-train a small RoBERTa from scratch with the HuggingFace Trainer.

Defective twin of `nlp_mlm_pretrain/pretrain_mlm.py`.
"""

from transformers import (
    AutoConfig,
    AutoModelForMaskedLM,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
)

from corpus import prepare

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


def training_arguments(out_dir, epochs=3):
    return TrainingArguments(
        output_dir=out_dir,
        overwrite_output_dir=True,
        num_train_epochs=epochs,
        per_device_train_batch_size=32,
        gradient_accumulation_steps=4,
        learning_rate=5e-4,
        weight_decay=0.01,
        warmup_ratio=0.06,
        lr_scheduler_type="cosine",
        save_strategy="epoch",
        logging_steps=100,
        bf16=True,
        report_to=[],
    )


def main(data_files="shards/*.txt", out_dir="runs/mlm"):
    tokenizer, split = prepare(CHECKPOINT, data_files)
    model = build_model(tokenizer)
    collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer, mlm=True, mlm_probability=0.15
    )
    trainer = Trainer(
        model=model,
        args=training_arguments(out_dir),
        train_dataset=split["train"],
        data_collator=collator,
    )
    trainer.train()
    trainer.save_model(out_dir)
    tokenizer.save_pretrained(out_dir)
    return out_dir


if __name__ == "__main__":
    print(main())
