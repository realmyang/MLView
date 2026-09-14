"""Customer segmentation: scale, reduce, cluster, then look at it.

There is no supervised target and no train/test split anywhere in this file,
which is the whole point of keeping it in the corpus: every leakage rule needs
a holdout to leak across, and an exploratory notebook-shaped script that has
none must produce silence rather than a red badge.

The one fitted object that escapes the script is the `Pipeline`, and it is
fitted once, on the only data there is.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import calinski_harabasz_score, silhouette_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

SEED = 11
FEATURES = ["recency_days", "frequency", "monetary", "basket_size",
            "discount_share"]


def load(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path)
    return frame.dropna(subset=FEATURES)


def build_reducer(n_components: int = 6) -> Pipeline:
    return Pipeline(steps=[
        ("scale", StandardScaler()),
        ("pca", PCA(n_components=n_components, random_state=SEED)),
    ])


def choose_k(components: np.ndarray, candidates=(3, 4, 5, 6, 7, 8)) -> dict:
    scores = {}
    for k in candidates:
        model = KMeans(n_clusters=k, n_init=10, random_state=SEED)
        assignments = model.fit_predict(components)
        scores[k] = {
            "silhouette": float(silhouette_score(components, assignments)),
            "calinski": float(calinski_harabasz_score(components, assignments)),
            "inertia": float(model.inertia_),
        }
    return scores


def density_clusters(components: np.ndarray) -> np.ndarray:
    scanner = DBSCAN(eps=0.8, min_samples=25)
    return scanner.fit_predict(components)


def embed_for_plot(components: np.ndarray) -> np.ndarray:
    projector = TSNE(n_components=2, perplexity=35.0, init="pca",
                     random_state=SEED)
    return projector.fit_transform(components)


def profile(frame: pd.DataFrame, assignments: np.ndarray) -> pd.DataFrame:
    labelled = frame.assign(segment=assignments)
    return labelled.groupby("segment")[FEATURES].agg(["mean", "median", "count"])


def main(csv_path: str = "data/customers.csv") -> dict:
    np.random.seed(SEED)
    frame = load(csv_path)

    reducer = build_reducer()
    components = reducer.fit_transform(frame[FEATURES])

    scores = choose_k(components)
    best_k = max(scores, key=lambda k: scores[k]["silhouette"])

    final = KMeans(n_clusters=best_k, n_init=10, random_state=SEED)
    assignments = final.fit_predict(components)

    return {
        "k": best_k,
        "scores": scores,
        "noise_fraction": float((density_clusters(components) == -1).mean()),
        "embedding_shape": embed_for_plot(components).shape,
        "profile": profile(frame, assignments).to_dict(),
    }


if __name__ == "__main__":
    print(main())
