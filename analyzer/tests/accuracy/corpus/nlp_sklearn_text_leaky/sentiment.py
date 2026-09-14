"""A classic bag-of-words sentiment baseline — the leaky version.

This is the script that gets written before anyone reaches for a transformer,
and it is where text leakage is most often introduced: the vocabulary and the
idf weights are fitted on the whole corpus, the held-out half is then
re-vectorised with a *second* fitted vectorizer, and the grid search is handed
an already-transformed matrix so every fold shares one vocabulary.
"""
from __future__ import annotations

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import GridSearchCV, train_test_split

DATA = "data/reviews.csv"
GRID = {"C": [0.1, 1.0, 4.0], "penalty": ["l2"]}
TEST_SIZE = 0.25


def build_features(path: str = DATA):
    frame = pd.read_csv(path)
    frame["length"] = frame["review"].str.len()
    texts = frame["review"]
    labels = frame["sentiment"]
    vectorizer = TfidfVectorizer(max_features=50000, ngram_range=(1, 2),
                                 sublinear_tf=True)
    features = vectorizer.fit_transform(texts)
    train_x, test_x, train_y, test_y = train_test_split(
        features, labels, test_size=TEST_SIZE)
    train_text, test_text = train_test_split(texts, test_size=TEST_SIZE)
    extra = TfidfVectorizer(max_features=50000, ngram_range=(1, 2))
    test_x = extra.fit_transform(test_text)
    return vectorizer, train_x, test_x, train_y, test_y


def search(train_x, train_y):
    estimator = LogisticRegression(max_iter=2000, solver="liblinear")
    grid = GridSearchCV(estimator, GRID, cv=5, scoring="f1_macro")
    grid.fit(train_x, train_y)
    return grid


def report(grid, test_x, test_y):
    scores = grid.decision_function(test_x)
    hard = grid.predict(test_x)
    return {
        "accuracy": accuracy_score(test_y, scores),
        "macro_f1": f1_score(test_y, hard, average="macro"),
        "roc_auc": roc_auc_score(test_y, hard),
    }


def main():
    vectorizer, train_x, test_x, train_y, test_y = build_features()
    grid = search(train_x, train_y)
    print(report(grid, test_x, test_y))


main()
