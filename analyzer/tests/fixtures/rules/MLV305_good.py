# MLVIEW-EXPECT-NONE: MLV305
"""The trap: the same predict_proba output is used twice - argmaxed for accuracy,
and fed raw to roc_auc_score, which is one of the score metrics carved out of
this rule because it legitimately takes continuous scores."""
import numpy as np
from sklearn.ensemble import RandomForestClassifier
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
        ("model", RandomForestClassifier(n_estimators=100, random_state=0)),
    ])
    pipeline.fit(train_x, train_y)

    probabilities = pipeline.predict_proba(test_x)
    predictions = probabilities.argmax(axis=1)
    return (accuracy_score(test_y, predictions),
            roc_auc_score(test_y, probabilities[:, 1]))
