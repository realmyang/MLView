"""A hand-written fine-tune of a token-classification head.

No Trainer: the loop is written out, which is how most NER scripts that need a
custom alignment end up. Seven defects are planted in it.
"""
from __future__ import annotations

import torch
from torch.utils.data import DataLoader
from transformers import (AutoModelForTokenClassification,
                          DataCollatorForTokenClassification)

from align import IGNORE_INDEX, TAGS, build_corpus, load_tokenizer

EPOCHS = 3
LEARNING_RATE = 3e-5
RESUME_FROM = "runs/ner/last.pt"


def build_loaders():
    tokenizer = load_tokenizer()
    train_split, eval_split = build_corpus(tokenizer)
    collate = DataCollatorForTokenClassification(tokenizer)
    train_loader = DataLoader(train_split, batch_size=16, collate_fn=collate)
    eval_loader = DataLoader(eval_split, batch_size=32, shuffle=True,
                             collate_fn=collate)
    return train_loader, eval_loader


def train(model, train_loader, device="cuda"):
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE)
    model.to(device)
    model.train()
    running = 0.0
    for epoch in range(EPOCHS):
        for batch in train_loader:
            outputs = model(input_ids=batch["input_ids"],
                            attention_mask=batch["attention_mask"],
                            labels=batch["labels"])
            loss = outputs.loss
            loss.backward()
            optimizer.step()
            running += loss
        print("epoch", epoch, "loss", running)
    return model


def token_accuracy(model, eval_loader):
    """Score the validation split — a forward pass and nothing else."""
    hits = 0
    total = 0
    for batch in eval_loader:
        logits = model(input_ids=batch["input_ids"],
                       attention_mask=batch["attention_mask"]).logits
        predicted = logits.argmax(dim=-1)
        gold = batch["labels"]
        keep = gold != IGNORE_INDEX
        hits += (predicted[keep] == gold[keep]).sum().item()
        total += int(keep.sum())
    return hits / max(total, 1)


def main():
    model = AutoModelForTokenClassification.from_pretrained(
        "bert-base-cased", num_labels=len(TAGS))
    state = torch.load(RESUME_FROM)
    model.load_state_dict(state["model"])
    train_loader, eval_loader = build_loaders()
    model = train(model, train_loader)
    print("token accuracy", token_accuracy(model, eval_loader))


main()
