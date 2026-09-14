"""The correct twin of `nlp_sklearn_text_leaky/sentiment.py`.

One `Pipeline` holds the vectorizer, the reducer and the classifier, so every
grid-search fold refits the vocabulary on its own training rows; the holdout is
cut before anything is fitted and is only ever `transform`ed through the fitted
pipeline. This file is the false-positive trap for the leakage family: nothing
here is wrong, and nothing may be reported.
"""
from __future__ import annotations

import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline

DATA = "data/reviews.csv"
SEED = 20240917
TEST_SIZE = 0.25
GRID = {
    "tfidf__min_df": [1, 3],
    "svd__n_components": [128, 256],
    "clf__C": [0.1, 1.0, 4.0],
}


def load_frame(path: str = DATA):
    frame = pd.read_csv(path)
    frame["length"] = frame["review"].str.len()
    return frame


def split_corpus(frame):
    texts = frame["review"]
    labels = frame["sentiment"]
    return train_test_split(texts, labels, test_size=TEST_SIZE,
                            random_state=SEED, stratify=labels)


def build_pipeline():
    return Pipeline([
        ("tfidf", TfidfVectorizer(max_features=50000, ngram_range=(1, 2),
                                  sublinear_tf=True)),
        ("svd", TruncatedSVD(n_components=256, random_state=SEED)),
        ("clf", LogisticRegression(max_iter=2000, random_state=SEED)),
    ])


def search(train_text, train_y):
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    grid = GridSearchCV(build_pipeline(), GRID, cv=folds, scoring="f1_macro",
                        n_jobs=-1)
    grid.fit(train_text, train_y)
    return grid


def report(grid, test_text, test_y):
    hard = grid.predict(test_text)
    probabilities = grid.predict_proba(test_text)[:, 1]
    return {
        "accuracy": accuracy_score(test_y, hard),
        "macro_f1": f1_score(test_y, hard, average="macro"),
        "roc_auc": roc_auc_score(test_y, probabilities),
    }


def main():
    frame = load_frame()
    train_text, test_text, train_y, test_y = split_corpus(frame)
    grid = search(train_text, train_y)
    print(grid.best_params_)
    print(report(grid, test_text, test_y))


main()
