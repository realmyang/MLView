# MLVIEW-EXPECT-NONE: MLV101, MLV102
"""PUB-14. Hand-rolled two-fold cross-validation is not a leak.

The shape is cell 16 of the Python Data Science Handbook's
`05.03-Hyperparameters-and-Model-Validation.ipynb`, one of the most-read
notebooks in the public corpus: split fifty/fifty, fit on each half in turn and
score each fit on the half it never saw.

MLView reported the second statement at high / `certain` 0.97, calling a
`KNeighborsClassifier` "the transformer" and saying *"the held-out score is not
an estimate of unseen-data performance at all"* - about a model whose only score
is computed on the rows it was not fitted on. `sklearn.base.BaseEstimator.fit`
carries the role FIT, so every estimator fit was an MLV102 candidate; MLV101 has
asked `_is_transformer_fit` since ROB-10 and MLV102 did not.

A *transformer* fitted on the held-out half is still MLV102 and still high -
`MLV102_bad` is the fixture that says so.
"""
from sklearn.datasets import load_iris
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier

X, y = load_iris(return_X_y=True)
model = KNeighborsClassifier(n_neighbors=1)

X1, X2, y1, y2 = train_test_split(X, y, random_state=0, train_size=0.5)

y2_model = model.fit(X1, y1).predict(X2)
y1_model = model.fit(X2, y2).predict(X1)

print(accuracy_score(y1, y1_model), accuracy_score(y2, y2_model))
