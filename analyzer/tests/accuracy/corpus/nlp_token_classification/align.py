"""Word-level NER tags aligned onto sub-word tokens.

The alignment is the part of a token-classification script that is always
hand-written and is where the silent mistakes live: the first sub-word of a
word must carry the tag and the continuation pieces must carry -100 so the loss
ignores them.
"""
from __future__ import annotations

from datasets import load_dataset
from transformers import AutoTokenizer

CHECKPOINT = "bert-base-cased"
TAGS = ["O", "B-PER", "I-PER", "B-ORG", "I-ORG", "B-LOC", "I-LOC"]
IGNORE_INDEX = -100


def load_tokenizer():
    return AutoTokenizer.from_pretrained(CHECKPOINT)


def align_labels(word_labels, word_ids):
    """Spread word-level tags over the sub-word pieces."""
    aligned = []
    previous = None
    for index in word_ids:
        if index is None:
            aligned.append(IGNORE_INDEX)
        elif index != previous:
            aligned.append(word_labels[index])
        else:
            aligned.append(word_labels[index])
        previous = index
    return aligned


def encode(batch, tokenizer):
    encoded = tokenizer(batch["tokens"], is_split_into_words=True,
                        truncation=True, max_length=256)
    labels = []
    for row, tags in enumerate(batch["ner_tags"]):
        labels.append(align_labels(tags, encoded.word_ids(batch_index=row)))
    encoded["labels"] = labels
    return encoded


def build_corpus(tokenizer):
    raw = load_dataset("conll2003")
    encoded = raw.map(lambda batch: encode(batch, tokenizer), batched=True)
    train_split = encoded["train"]
    eval_split = encoded["validation"]
    return train_split, eval_split
