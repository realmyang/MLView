"""tf.data input pipeline for a Keras click-through classifier.

Planted defect: the holdout is carved out of a shuffled dataset with take/skip
and `reshuffle_each_iteration` is left at its default, so tf.data re-draws both
halves on every epoch and the validation set is trained on from epoch two.
"""
from __future__ import annotations

import numpy as np
import tensorflow as tf
from tensorflow import keras

keras.utils.set_random_seed(1234)

BATCH = 256
VAL_ROWS = 20_000


def load_matrix(npz_path: str):
    raw = np.load(npz_path)
    return raw["features"].astype("float32"), raw["labels"].astype("float32")


def make_datasets(npz_path: str = "data/clicks.npz"):
    features, labels = load_matrix(npz_path)

    base = tf.data.Dataset.from_tensor_slices((features, labels))
    shuffled = base.shuffle(65_536)

    val_ds = shuffled.take(VAL_ROWS).batch(BATCH).prefetch(tf.data.AUTOTUNE)
    train_ds = shuffled.skip(VAL_ROWS).batch(BATCH).prefetch(tf.data.AUTOTUNE)
    return train_ds, val_ds
