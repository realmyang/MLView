"""Cross-validate with fresh models, then refit the chosen model on everything.

Nothing scored here ever sees rows its own estimator was fitted on. The five
fold models (`m`) are each fitted on `X[train_idx]` and scored on the held-out
`X[test_idx]`; `final` is fitted on all of `X` and never scored at all - it is
the artefact that ships. Refitting the final estimator on the full dataset
after cross-validation is what `sklearn.model_selection.GridSearchCV(refit=True)`
does by default and what the scikit-learn user guide recommends.

ROB-10: MLView reports `MLV101` (high, confidence 0.95) on line 14 -
"`final.fit()` is fitted on X ..., before split splits it at line 16, so the
transformer sees the held-out rows". `final` is a RandomForestClassifier: it is
not a transformer, it transforms nothing, and `KFold.split` holds nothing out
from it.
"""
from sklearn.datasets import make_classification
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import KFold


def cross_validate_then_refit():
    X, y = make_classification(n_samples=200, random_state=0)
    final = RandomForestClassifier(random_state=0)
    final.fit(X, y)
    kf = KFold(n_splits=5, shuffle=True, random_state=0)
    scores = []
    for train_idx, test_idx in kf.split(X, y):
        m = RandomForestClassifier(random_state=0)
        m.fit(X[train_idx], y[train_idx])
        scores.append(m.score(X[test_idx], y[test_idx]))
    return final, scores
