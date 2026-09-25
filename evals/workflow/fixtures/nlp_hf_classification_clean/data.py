"""The correct twin of `nlp_hf_classification/data.py`.

Same corpus, same two paths, every leak closed: the `datasets` split is seeded,
and the TF-IDF baseline fits inside a `Pipeline` that only ever sees the
training rows.
"""
from __future__ import annotations

import pandas as pd
from datasets import load_dataset
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from transformers import AutoTokenizer

CHECKPOINT = "roberta-base"
MAX_LENGTH = 192
LABEL_NAMES = ["billing", "shipping", "technical", "other"]
TEST_FRACTION = 0.2
SEED = 1234


def load_tokenizer():
    return AutoTokenizer.from_pretrained(CHECKPOINT)


def encode_corpus(csv_path: str):
    """Tokenise the whole corpus, then hold out a fifth of it — seeded."""
    tokenizer = load_tokenizer()
    raw = load_dataset("csv", data_files=csv_path)["train"]

    def tokenize(batch):
        return tokenizer(batch["utterance"], truncation=True,
                         max_length=MAX_LENGTH)

    encoded = raw.map(tokenize, batched=True)
    encoded = encoded.class_encode_column("label")
    split = encoded.train_test_split(test_size=TEST_FRACTION, seed=SEED)
    return tokenizer, split


def keyword_baseline(csv_path: str):
    """The TF-IDF baseline, with the vectorizer inside the pipeline."""
    frame = pd.read_csv(csv_path)
    texts = frame["utterance"]
    target = frame["label"]
    train_x, test_x, train_y, test_y = train_test_split(
        texts, target, test_size=TEST_FRACTION, random_state=SEED,
        stratify=target)
    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(max_features=20000, ngram_range=(1, 2))),
        ("clf", LogisticRegression(max_iter=1000, C=4.0)),
    ])
    pipeline.fit(train_x, train_y)
    return pipeline, test_x, test_y
