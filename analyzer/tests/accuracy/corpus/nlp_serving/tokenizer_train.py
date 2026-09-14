"""Train a byte-level BPE tokenizer over the raw corpus.

Nothing here is a model: there is no split, no gradient and no metric. It is in
this corpus as a false-positive trap — a file full of the word `train` that
must not be mistaken for a training loop.
"""
from __future__ import annotations

import json
import os

from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

VOCAB_SIZE = 32000
SPECIAL_TOKENS = ["<pad>", "<unk>", "<s>", "</s>", "<mask>"]
CORPUS_DIR = "data/corpus"
OUTPUT = "artifacts/tokenizer.json"


def corpus_files(directory: str = CORPUS_DIR):
    return [os.path.join(directory, name)
            for name in sorted(os.listdir(directory))
            if name.endswith(".txt")]


def build_tokenizer():
    tokenizer = Tokenizer(models.BPE(unk_token="<unk>"))
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=True)
    tokenizer.decoder = decoders.ByteLevel()
    return tokenizer


def train_tokenizer(files, vocab_size: int = VOCAB_SIZE):
    tokenizer = build_tokenizer()
    trainer = trainers.BpeTrainer(vocab_size=vocab_size,
                                  special_tokens=SPECIAL_TOKENS,
                                  show_progress=False)
    tokenizer.train(files, trainer)
    return tokenizer


def main():
    files = corpus_files()
    tokenizer = train_tokenizer(files)
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    tokenizer.save(OUTPUT)
    with open("artifacts/tokenizer_meta.json", "w", encoding="utf-8") as handle:
        json.dump({"vocab_size": VOCAB_SIZE, "files": len(files)}, handle)


main()
