"""Distil a fine-tuned BERT into a 4-layer student on a classification task."""

import random

import numpy as np
import torch
from sklearn.metrics import f1_score
from torch.utils.data import DataLoader
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    get_linear_schedule_with_warmup,
)

from losses import DistillationLoss, teacher_logits

SEED = 7
TEACHER = "bert-base-uncased"
STUDENT = "google/bert_uncased_L-4_H-512_A-8"


def seed_everything(seed=SEED):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device():
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_loaders(encoded, tokenizer, batch_size=32):
    collator = DataCollatorWithPadding(tokenizer=tokenizer)
    train_loader = DataLoader(encoded["train"], batch_size=batch_size,
                              shuffle=True, collate_fn=collator)
    eval_loader = DataLoader(encoded["validation"], batch_size=batch_size * 2,
                             shuffle=False, collate_fn=collator)
    return train_loader, eval_loader


def move(batch, device):
    return {key: value.to(device) for key, value in batch.items()}


def train_epoch(student, teacher, loader, criterion, optimizer, scheduler, device):
    student.train()
    running = 0.0
    for batch in loader:
        batch = move(batch, device)
        labels = batch.pop("labels")
        optimizer.zero_grad(set_to_none=True)
        soft = teacher_logits(teacher, batch)
        logits = student(**batch).logits
        loss = criterion(logits, soft, labels)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
        optimizer.step()
        scheduler.step()
        running += loss.item()
    return running / max(len(loader), 1)


@torch.no_grad()
def evaluate(student, loader, device):
    student.eval()
    predictions = []
    targets = []
    for batch in loader:
        batch = move(batch, device)
        labels = batch.pop("labels")
        logits = student(**batch).logits
        predictions.append(logits.argmax(dim=-1).cpu().numpy())
        targets.append(labels.cpu().numpy())
    return f1_score(np.concatenate(targets), np.concatenate(predictions),
                    average="macro")


def main(encoded, epochs=3, lr=5e-5, out_path="student.pt"):
    seed_everything()
    device = pick_device()
    tokenizer = AutoTokenizer.from_pretrained(TEACHER)
    teacher = AutoModelForSequenceClassification.from_pretrained(TEACHER, num_labels=2)
    student = AutoModelForSequenceClassification.from_pretrained(STUDENT, num_labels=2)
    teacher.to(device)
    teacher.eval()
    student.to(device)
    train_loader, eval_loader = build_loaders(encoded, tokenizer)
    criterion = DistillationLoss(temperature=4.0, alpha=0.7)
    optimizer = torch.optim.AdamW(student.parameters(), lr=lr, weight_decay=0.01)
    total = len(train_loader) * epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, int(0.06 * total), total)
    best = 0.0
    for epoch in range(epochs):
        loss = train_epoch(student, teacher, train_loader, criterion,
                           optimizer, scheduler, device)
        score = evaluate(student, eval_loader, device)
        print("epoch %d loss %.4f macro-f1 %.4f" % (epoch, loss, score))
        if score > best:
            best = score
            torch.save(student.state_dict(), out_path)
    return best


if __name__ == "__main__":
    raise SystemExit("call main() with an encoded DatasetDict")
