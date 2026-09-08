"""scikit-learn (+ pandas / numpy) knowledge table."""

from __future__ import annotations

from typing import Dict

from .entries import E, Entry, expand

S = "sklearn"
PD = "pandas"
NP = "numpy"

SKLEARN: Dict[str, Entry] = {}

# ---------------------------------------------------------------- data ----
SKLEARN.update({
    "sklearn.model_selection.train_test_split": E("split", "data", S, "SPLIT"),
    "sklearn.model_selection.KFold": E("split", "data", S, "SPLITTER", (), "splitter"),
    "sklearn.model_selection.StratifiedKFold": E("split", "data", S, "SPLITTER", (), "splitter"),
    "sklearn.model_selection.GroupKFold": E("split", "data", S, "SPLITTER", (), "splitter"),
    "sklearn.model_selection.ShuffleSplit": E("split", "data", S, "SPLITTER", (), "splitter"),
    "sklearn.model_selection.StratifiedShuffleSplit": E("split", "data", S, "SPLITTER", (), "splitter"),
    "sklearn.model_selection.TimeSeriesSplit": E("split", "data", S, "SPLITTER", (), "splitter"),
    "sklearn.model_selection.LeaveOneOut": E("split", "data", S, "SPLITTER", (), "splitter"),
})
SKLEARN.update(expand("sklearn.datasets", [
    "load_iris", "load_digits", "load_wine", "load_breast_cancer", "load_diabetes",
    "fetch_openml", "fetch_california_housing", "make_classification", "make_regression",
    "make_blobs",
], E("dataset", "data", S, "DATASET", ("RAW_DATA",))))

# ---------------------------------------------------------- preprocess ----
SKLEARN.update(expand("sklearn.preprocessing", [
    "StandardScaler", "MinMaxScaler", "MaxAbsScaler", "RobustScaler",
    "Normalizer", "QuantileTransformer", "PowerTransformer", "KBinsDiscretizer",
], E("scaler", "preprocess", S, "TRANSFORMER", (), "estimator")))
SKLEARN.update(expand("sklearn.preprocessing", [
    "OneHotEncoder", "OrdinalEncoder", "LabelEncoder", "LabelBinarizer",
    "PolynomialFeatures",
], E("transform", "preprocess", S, "TRANSFORMER", (), "estimator")))
SKLEARN["sklearn.preprocessing.FunctionTransformer"] = E(
    "transform", "preprocess", S, "STATELESS_TRANSFORMER", (), "estimator")
SKLEARN.update(expand("sklearn.decomposition", ["PCA", "TruncatedSVD", "NMF", "FastICA"],
                      E("transform", "preprocess", S, "TRANSFORMER", (), "estimator")))
SKLEARN.update(expand("sklearn.impute", ["SimpleImputer", "KNNImputer", "IterativeImputer"],
                      E("transform", "preprocess", S, "TRANSFORMER", (), "estimator")))
SKLEARN.update(expand("sklearn.feature_selection", ["SelectKBest", "SelectFromModel", "RFE"],
                      E("transform", "preprocess", S, "TRANSFORMER", (), "estimator")))
SKLEARN.update(expand("sklearn.feature_extraction.text", ["TfidfVectorizer", "CountVectorizer"],
                      E("transform", "preprocess", S, "TRANSFORMER", (), "estimator")))
SKLEARN["sklearn.compose.ColumnTransformer"] = E(
    "transform", "preprocess", S, "TRANSFORMER", (), "estimator")

# --------------------------------------------------------------- model ----
SKLEARN["sklearn.pipeline.Pipeline"] = E("model", "model", S, "PIPELINE", ("MODEL",), "estimator")
SKLEARN["sklearn.pipeline.make_pipeline"] = E("model", "model", S, "PIPELINE", ("MODEL",), "estimator")
for _mod, _names in {
    "sklearn.linear_model": ["LogisticRegression", "LinearRegression", "Ridge", "Lasso",
                             "ElasticNet", "SGDClassifier", "SGDRegressor", "Perceptron"],
    "sklearn.ensemble": ["RandomForestClassifier", "RandomForestRegressor",
                         "GradientBoostingClassifier", "GradientBoostingRegressor",
                         "ExtraTreesClassifier", "AdaBoostClassifier",
                         "HistGradientBoostingClassifier", "VotingClassifier",
                         "StackingClassifier"],
    "sklearn.svm": ["SVC", "SVR", "LinearSVC"],
    "sklearn.tree": ["DecisionTreeClassifier", "DecisionTreeRegressor"],
    "sklearn.neighbors": ["KNeighborsClassifier", "KNeighborsRegressor"],
    "sklearn.naive_bayes": ["GaussianNB", "MultinomialNB"],
    "sklearn.cluster": ["KMeans", "DBSCAN", "AgglomerativeClustering"],
    "sklearn.neural_network": ["MLPClassifier", "MLPRegressor"],
    "xgboost": ["XGBClassifier", "XGBRegressor"],
    "lightgbm": ["LGBMClassifier", "LGBMRegressor"],
}.items():
    _fw = S if _mod.startswith("sklearn") else _mod
    SKLEARN.update(expand(_mod, _names, E("model", "model", _fw, "ESTIMATOR", ("MODEL",), "estimator")))

SKLEARN["sklearn.model_selection.GridSearchCV"] = E(
    "model", "model", S, "CV_SEARCH", ("MODEL",), "estimator")
SKLEARN["sklearn.model_selection.RandomizedSearchCV"] = E(
    "model", "model", S, "CV_SEARCH", ("MODEL",), "estimator")
SKLEARN["sklearn.model_selection.HalvingGridSearchCV"] = E(
    "model", "model", S, "CV_SEARCH", ("MODEL",), "estimator")

# ---------------------------------------------------------------- eval ----
SKLEARN.update(expand("sklearn.model_selection", ["cross_val_score", "cross_validate", "cross_val_predict"],
                      E("metric", "eval", S, "CV")))
SKLEARN.update(expand("sklearn.metrics", [
    "accuracy_score", "f1_score", "precision_score", "recall_score",
    "balanced_accuracy_score", "classification_report", "confusion_matrix",
    "mean_squared_error", "mean_absolute_error", "r2_score",
], E("metric", "eval", S, "METRIC")))
SKLEARN.update(expand("sklearn.metrics", ["roc_auc_score", "average_precision_score", "log_loss"],
                      E("metric", "eval", S, "SCORE_METRIC")))

# ------------------------------------------------------------- deliver ----
SKLEARN["joblib.dump"] = E("checkpoint", "deliver", "other", "SAVE")
SKLEARN["joblib.load"] = E("checkpoint", "deliver", "other", "LOAD")
SKLEARN["pickle.dump"] = E("checkpoint", "deliver", "other", "SAVE")
SKLEARN["pickle.load"] = E("checkpoint", "deliver", "other", "LOAD")

# ------------------------------------------------------ pandas / numpy ----
SKLEARN.update(expand("pandas", [
    "read_csv", "read_parquet", "read_json", "read_excel", "read_sql", "read_pickle",
    "read_feather", "read_hdf",
], E("dataset", "data", PD, "DATASET", ("RAW_DATA", "FEATURES"))))
SKLEARN["pandas.DataFrame"] = E("dataset", "data", PD, "DATASET", ("RAW_DATA", "FEATURES"))
SKLEARN["pandas.get_dummies"] = E("transform", "preprocess", PD, "TRANSFORM")
SKLEARN["pandas.concat"] = E("transform", "preprocess", PD, "TRANSFORM", weight=0.5)
SKLEARN["pandas.to_datetime"] = E("transform", "preprocess", PD, "TEMPORAL", weight=0.5)
SKLEARN["numpy.load"] = E("dataset", "data", NP, "DATASET", ("RAW_DATA", "FEATURES"))
SKLEARN["numpy.loadtxt"] = E("dataset", "data", NP, "DATASET", ("RAW_DATA", "FEATURES"))
SKLEARN["numpy.genfromtxt"] = E("dataset", "data", NP, "DATASET", ("RAW_DATA", "FEATURES"))
SKLEARN["numpy.random.seed"] = E("config", "config", NP, "SEED")
SKLEARN["numpy.random.default_rng"] = E("config", "config", NP, "SEED")
SKLEARN["numpy.random.RandomState"] = E("config", "config", NP, "SEED")
SKLEARN["random.seed"] = E("config", "config", "other", "SEED")

# --------------------------------------------- method families (sklearn) ---
SKLEARN_METHODS: Dict[str, Entry] = {
    "sklearn.base.BaseEstimator.fit": E("model", "train", S, "FIT"),
    "sklearn.base.BaseEstimator.partial_fit": E("model", "train", S, "FIT"),
    "sklearn.base.BaseEstimator.fit_transform": E("transform", "preprocess", S, "FIT_TRANSFORM"),
    "sklearn.base.BaseEstimator.transform": E("transform", "preprocess", S, "TRANSFORM"),
    "sklearn.base.BaseEstimator.inverse_transform": E("transform", "preprocess", S, "TRANSFORM"),
    "sklearn.base.BaseEstimator.predict": E("predict", "eval", S, "PREDICT", ("PREDS",)),
    "sklearn.base.BaseEstimator.predict_proba": E("predict", "eval", S, "PREDICT", ("PROBS",)),
    "sklearn.base.BaseEstimator.decision_function": E("predict", "eval", S, "PREDICT", ("LOGITS",)),
    "sklearn.base.BaseEstimator.score": E("metric", "eval", S, "METRIC"),
    "sklearn.model_selection.BaseCrossValidator.split": E("split", "data", S, "SPLIT"),
}

STATELESS_TRANSFORMERS = frozenset({
    "sklearn.preprocessing.FunctionTransformer",
    "sklearn.preprocessing.Normalizer",
})
