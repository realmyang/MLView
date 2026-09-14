"""Instruction-tune the LoRA adapters on a small instruction corpus.

The loop is hand-written so the adapters can be stepped without touching the
frozen base. Five defects are planted: the gradients are computed and never
applied, the batch is never moved to the device the model is on, the
perplexity pass forgets `model.eval()`, the checkpoint pickles the whole
module, and nothing is seeded.
"""
from __future__ import annotations

import math

import torch
from datasets import load_dataset
from torch.utils.data import DataLoader
from transformers import DataCollatorForLanguageModeling

from lora import AdapterStack, load_base, trainable_parameters

EPOCHS = 3
LEARNING_RATE = 1e-4
MAX_LENGTH = 512


def build_loaders(tokenizer):
    raw = load_dataset("tatsu-lab/alpaca")["train"]

    def encode(batch):
        prompts = ["%s\n%s" % (i, o)
                   for i, o in zip(batch["instruction"], batch["output"])]
        return tokenizer(prompts, truncation=True, max_length=MAX_LENGTH)

    encoded = raw.map(encode, batched=True, remove_columns=raw.column_names)
    holdout = encoded.train_test_split(test_size=0.05, seed=7)
    collate = DataCollatorForLanguageModeling(tokenizer, mlm=False)
    train_loader = DataLoader(holdout["train"], batch_size=4, shuffle=True,
                              collate_fn=collate)
    return train_loader, holdout["test"], collate


def train(model, adapters, train_loader, device="cuda"):
    optimizer = torch.optim.AdamW(trainable_parameters(adapters),
                                  lr=LEARNING_RATE)
    model.to(device)
    model.train()
    for epoch in range(EPOCHS):
        for batch in train_loader:
            optimizer.zero_grad()
            outputs = model(input_ids=batch["input_ids"],
                            attention_mask=batch["attention_mask"],
                            labels=batch["labels"])
            outputs.loss.backward()
        print("epoch", epoch, "done")
    return model


def evaluate(model, holdout, collate):
    """Perplexity over the holdout — under no_grad, but never in eval mode."""
    eval_loader = DataLoader(holdout, batch_size=8, shuffle=False,
                             collate_fn=collate)
    total = 0.0
    batches = 0
    with torch.no_grad():
        for batch in eval_loader:
            outputs = model(input_ids=batch["input_ids"],
                            attention_mask=batch["attention_mask"],
                            labels=batch["labels"])
            total += float(outputs.loss)
            batches += 1
    return math.exp(total / max(batches, 1))


def main():
    tokenizer, model = load_base()
    adapters = AdapterStack(model.config.hidden_size)
    train_loader, holdout, collate = build_loaders(tokenizer)
    model = train(model, adapters, train_loader)
    print("perplexity", evaluate(model, holdout, collate))
    torch.save(adapters, "runs/lora/adapters.pt")


main()
