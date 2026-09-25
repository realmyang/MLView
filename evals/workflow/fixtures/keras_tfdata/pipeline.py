"""tf.data input pipeline for a tabular Keras classifier.

Planted defects: the scaler is fitted on the whole matrix before the split, and
the normalisation constants baked into the tf.data map closure are computed
from every row including the validation half.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

FEATURES = ["latency_ms", "payload_kb", "retries", "hour", "region_code"]
TARGET = "failed"
BATCH = 128


def load_matrix(csv_path: str):
    frame = pd.read_csv(csv_path)
    features = frame[FEATURES].to_numpy(dtype="float32")
    labels = frame[TARGET].to_numpy(dtype="float32")
    return features, labels


def build_splits(csv_path: str):
    features, labels = load_matrix(csv_path)

    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)

    train_x, val_x, train_y, val_y = train_test_split(scaled, labels, test_size=0.2)
    return train_x, val_x, train_y, val_y, features


def make_datasets(csv_path: str):
    train_x, val_x, train_y, val_y, features = build_splits(csv_path)

    mean = features.mean(axis=0)
    std = features.std(axis=0) + 1e-6

    def normalize(x, y):
        return (x - mean) / std, y

    train_ds = (tf.data.Dataset.from_tensor_slices((train_x, train_y))
                .map(normalize, num_parallel_calls=tf.data.AUTOTUNE)
                .shuffle(4096)
                .batch(BATCH)
                .prefetch(tf.data.AUTOTUNE))
    val_ds = (tf.data.Dataset.from_tensor_slices((val_x, val_y))
              .map(normalize, num_parallel_calls=tf.data.AUTOTUNE)
              .batch(BATCH)
              .prefetch(tf.data.AUTOTUNE))
    return train_ds, val_ds
