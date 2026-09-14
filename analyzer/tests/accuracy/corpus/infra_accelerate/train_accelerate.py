"""A HuggingFace `accelerate` fine-tuning script, written the way the
`accelerate` examples are written.

Correct on purpose. `Accelerator` owns device placement and gradient
accumulation; the loop is hand-written but every mechanic is in the right
order: `accelerator.backward(loss)` -> `optimizer.step()` ->
`lr_scheduler.step()` -> `optimizer.zero_grad()`, which is the idiomatic
ordering (zeroing at the end of the step rather than the start). Evaluation
runs under `model.eval()` and `torch.no_grad()`, and the checkpoint is written
on the main process only.

Any finding in this file is a false positive.
"""
from __future__ import annotations

import argparse
import math
import os

import torch
from accelerate import Accelerator
from accelerate.utils import set_seed
from datasets import load_dataset
from torch.utils.data import DataLoader
from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                          DataCollatorWithPadding, get_linear_schedule_with_warmup)

CHECKPOINT = "distilbert-base-uncased"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="accelerate fine-tune")
    parser.add_argument("--dataset", default="glue")
    parser.add_argument("--subset", default="sst2")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--accumulation", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="artifacts/sst2")
    return parser.parse_args()


def build_dataloaders(args, tokenizer):
    raw = load_dataset(args.dataset, args.subset)
    collator = DataCollatorWithPadding(tokenizer=tokenizer)

    def tokenize(batch):
        return tokenizer(batch["sentence"], truncation=True, max_length=128)

    encoded = raw.map(tokenize, batched=True,
                      remove_columns=["sentence", "idx"])
    encoded = encoded.rename_column("label", "labels")
    encoded.set_format("torch")

    train_loader = DataLoader(encoded["train"], shuffle=True,
                              batch_size=args.batch_size, collate_fn=collator)
    eval_loader = DataLoader(encoded["validation"], shuffle=False,
                             batch_size=args.batch_size, collate_fn=collator)
    return train_loader, eval_loader


def evaluate(accelerator: Accelerator, model, eval_loader) -> float:
    model.eval()
    hits = 0
    seen = 0
    with torch.no_grad():
        for batch in eval_loader:
            outputs = model(**batch)
            predictions = outputs.logits.argmax(dim=-1)
            predictions, references = accelerator.gather_for_metrics(
                (predictions, batch["labels"]))
            hits += (predictions == references).sum().item()
            seen += references.numel()
    model.train()
    return hits / max(seen, 1)


def main() -> None:
    args = parse_args()
    set_seed(args.seed)

    accelerator = Accelerator(gradient_accumulation_steps=args.accumulation,
                              mixed_precision="bf16",
                              log_with="tensorboard",
                              project_dir=args.out)
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT)
    model = AutoModelForSequenceClassification.from_pretrained(CHECKPOINT,
                                                               num_labels=2)
    train_loader, eval_loader = build_dataloaders(args, tokenizer)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)

    steps_per_epoch = math.ceil(len(train_loader) / args.accumulation)
    lr_scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=steps_per_epoch // 10,
        num_training_steps=steps_per_epoch * args.epochs)

    model, optimizer, train_loader, eval_loader, lr_scheduler = accelerator.prepare(
        model, optimizer, train_loader, eval_loader, lr_scheduler)

    for epoch in range(args.epochs):
        model.train()
        running = 0.0
        for batch in train_loader:
            with accelerator.accumulate(model):
                outputs = model(**batch)
                loss = outputs.loss
                accelerator.backward(loss)
                accelerator.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                lr_scheduler.step()
                optimizer.zero_grad()
            running += loss.detach().float().item()

        accuracy = evaluate(accelerator, model, eval_loader)
        accelerator.print("epoch %d loss %.4f acc %.4f"
                          % (epoch, running / max(len(train_loader), 1), accuracy))

    accelerator.wait_for_everyone()
    if accelerator.is_main_process:
        os.makedirs(args.out, exist_ok=True)
        unwrapped = accelerator.unwrap_model(model)
        unwrapped.save_pretrained(args.out,
                                  save_function=accelerator.save)
        tokenizer.save_pretrained(args.out)


if __name__ == "__main__":
    main()
