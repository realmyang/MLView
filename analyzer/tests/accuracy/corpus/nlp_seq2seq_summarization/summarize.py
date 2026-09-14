"""Fine-tune T5-small as an abstractive summariser.

The data half is `datasets` + a seq2seq collator; the training half is
`Seq2SeqTrainer`. Three defects live here, all of them configuration rather
than code: the split is unseeded, the Trainer is never told to evaluate, and
the checkpoint is reloaded with a bare `torch.load`.
"""
from __future__ import annotations

import torch
from datasets import load_dataset
from transformers import (AutoModelForSeq2SeqLM, AutoTokenizer,
                          DataCollatorForSeq2Seq, Seq2SeqTrainer,
                          Seq2SeqTrainingArguments)

CHECKPOINT = "t5-small"
SOURCE_LENGTH = 512
TARGET_LENGTH = 96
PREFIX = "summarize: "
RESUME = "runs/sum/last.pt"


def build_corpus(tokenizer):
    raw = load_dataset("cnn_dailymail", "3.0.0")["train"]

    def encode(batch):
        model_inputs = tokenizer([PREFIX + a for a in batch["article"]],
                                 max_length=SOURCE_LENGTH, truncation=True)
        targets = tokenizer(text_target=batch["highlights"],
                            max_length=TARGET_LENGTH, truncation=True)
        model_inputs["labels"] = targets["input_ids"]
        return model_inputs

    encoded = raw.map(encode, batched=True, remove_columns=raw.column_names)
    holdout = encoded.train_test_split(test_size=0.05)
    return holdout


def build_trainer(output_dir: str = "runs/sum"):
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT)
    model = AutoModelForSeq2SeqLM.from_pretrained(CHECKPOINT)
    holdout = build_corpus(tokenizer)
    args = Seq2SeqTrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=8,
        gradient_accumulation_steps=4,
        learning_rate=3e-4,
        num_train_epochs=2,
        predict_with_generate=True,
        generation_max_length=TARGET_LENGTH,
    )
    trainer = Seq2SeqTrainer(
        model=model,
        args=args,
        train_dataset=holdout["train"],
        data_collator=DataCollatorForSeq2Seq(tokenizer, model=model),
    )
    return tokenizer, model, holdout, trainer


def resume(model):
    state = torch.load(RESUME)
    model.load_state_dict(state)
    return model
