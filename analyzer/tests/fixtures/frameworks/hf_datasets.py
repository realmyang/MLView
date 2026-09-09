"""FW-RECOG positive fixture: the HuggingFace `datasets` path.

`datasets` used to be a single knowledge row (`load_dataset`), so `raw.map(...)`
and `enc["train"].train_test_split(...)` produced **zero nodes and no SPLIT** -
which makes MLV101, MLV106 and MLV602 structurally impossible on this path.

The `train_test_split` here takes no `seed=`, so MLV602 must fire on it: that
is the point of the fixture, not an oversight.
"""
from __future__ import annotations

from datasets import load_dataset, load_from_disk
from transformers import AutoTokenizer, DataCollatorWithPadding

CHECKPOINT = "distilbert-base-uncased"


def build(name: str = "imdb"):
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT)
    raw = load_dataset(name)

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True, max_length=256)

    encoded = raw.map(tokenize, batched=True)
    split = encoded["train"].train_test_split(test_size=0.1)
    collator = DataCollatorWithPadding(tokenizer=tokenizer)
    return split, collator


def reload_cached(path: str):
    return load_from_disk(path).with_format("torch")
