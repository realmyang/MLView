# MLVIEW-EXPECT: MLV306 line=24 confidence>=0.6
"""roc_auc_score is fed hard 0/1 predictions, so the curve has two points and the
number reported is balanced accuracy wearing an AUC label."""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
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
    return roc_auc_score(test_y, predictions)
