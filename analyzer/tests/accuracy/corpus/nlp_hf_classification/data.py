"""Support-ticket intent corpus: load, tokenise, split.

The `datasets` path is the one real teams use; the TF-IDF baseline beside it is
the thing somebody adds in the first week and never removes. Both halves carry
planted defects.
"""
from __future__ import annotations

import pandas as pd
from datasets import load_dataset
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from transformers import AutoTokenizer

CHECKPOINT = "roberta-base"
MAX_LENGTH = 192
LABEL_NAMES = ["billing", "shipping", "technical", "other"]
TEST_FRACTION = 0.2


def load_tokenizer():
    return AutoTokenizer.from_pretrained(CHECKPOINT)


def encode_corpus(csv_path: str):
    """Tokenise the whole corpus, then hold out a fifth of it."""
    tokenizer = load_tokenizer()
    raw = load_dataset("csv", data_files=csv_path)["train"]

    def tokenize(batch):
        return tokenizer(batch["utterance"], truncation=True,
                         max_length=MAX_LENGTH)

    encoded = raw.map(tokenize, batched=True)
    encoded = encoded.class_encode_column("label")
    split = encoded.train_test_split(test_size=TEST_FRACTION)
    return tokenizer, split


def keyword_baseline(csv_path: str):
    """A TF-IDF baseline, fitted on everything before anything is held out."""
    frame = pd.read_csv(csv_path)
    vectorizer = TfidfVectorizer(max_features=20000, ngram_range=(1, 2))
    features = vectorizer.fit_transform(frame["utterance"])
    target = frame["label"]
    X_train, X_test, y_train, y_test = train_test_split(
        features, target, test_size=TEST_FRACTION)
    return X_train, X_test, y_train, y_test
