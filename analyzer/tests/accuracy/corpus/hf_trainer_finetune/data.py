"""Feature preparation for the review-sentiment fine-tune.

Planted defect: the TF-IDF auxiliary features and the numeric metadata are both
fitted on the WHOLE frame, then split. The vectoriser's vocabulary and the
scaler's means are computed from rows that end up in the evaluation half.
"""
from __future__ import annotations

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

NUMERIC = ["length", "exclamations", "capitals"]


def load_frame(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["length"] = frame["text"].str.len()
    frame["exclamations"] = frame["text"].str.count("!")
    frame["capitals"] = frame["text"].str.count(r"[A-Z]")
    return frame


def build_features(path: str):
    frame = load_frame(path)

    vectorizer = TfidfVectorizer(max_features=4096, ngram_range=(1, 2))
    tfidf = vectorizer.fit_transform(frame["text"])

    scaler = StandardScaler()
    numeric = scaler.fit_transform(frame[NUMERIC])

    labels = frame["label"].to_numpy()
    train_tfidf, test_tfidf, train_num, test_num, train_y, test_y = train_test_split(
        tfidf, numeric, labels, test_size=0.2)
    return {
        "train": (train_tfidf, train_num, train_y),
        "test": (test_tfidf, test_num, test_y),
        "vectorizer": vectorizer,
        "scaler": scaler,
        "frame": frame,
    }
