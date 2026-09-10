# MLVIEW-EXPECT-NONE: MLV306
"""The trap: predict() output really is used, but for accuracy_score, where hard
labels are exactly right; the ranking metric gets the positive-class column of
predict_proba. Both metrics in one expression, only one of them ranking."""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

np.random.seed(0)


def evaluate(features, labels):
    train_x, test_x, train_y, test_y = train_test_split(
        features, labels, test_size=0.2, random_state=0)
    pipeline = Pipeline([
        ("scale", StandardScaler()),
        ("model", LogisticRegression(max_iter=500, random_state=0)),
    ])
    pipeline.fit(train_x, train_y)

    predictions = pipeline.predict(test_x)
    scores = pipeline.predict_proba(test_x)[:, 1]
    return accuracy_score(test_y, predictions), roc_auc_score(test_y, scores)
