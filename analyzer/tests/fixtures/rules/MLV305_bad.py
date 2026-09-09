# MLVIEW-EXPECT: MLV305 line=24 confidence>=0.6
"""accuracy_score is handed the probability matrix, so it compares floats with
integer labels and reports roughly the chance rate whatever the model does."""
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
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
    return accuracy_score(test_y, probabilities)
