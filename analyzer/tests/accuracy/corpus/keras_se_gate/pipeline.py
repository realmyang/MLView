"""tf.data input pipeline for the defect-classifier, written the way the
official tf.data guide writes one: `ds = ds.<op>(...)`, rebinding the same name
at every step.

Planted defect: the validation half is carved out of a shuffled dataset with
take/skip and `reshuffle_each_iteration` is left at its default, so tf.data
re-draws both halves on every epoch and the validation set is trained on from
epoch two.
"""
from __future__ import annotations

import numpy as np
import tensorflow as tf
from tensorflow import keras

keras.utils.set_random_seed(7)

BATCH = 64
VAL_ROWS = 4_096


def load_matrix(npz_path: str):
    raw = np.load(npz_path)
    return raw["images"].astype("float32"), raw["labels"].astype("float32")


def make_datasets(npz_path: str = "data/panels.npz"):
    images, labels = load_matrix(npz_path)

    ds = tf.data.Dataset.from_tensor_slices((images, labels))
    ds = ds.map(lambda x, y: (x / 255.0, y), num_parallel_calls=tf.data.AUTOTUNE)
    ds = ds.shuffle(32_768)

    val_ds = ds.take(VAL_ROWS).batch(BATCH).prefetch(tf.data.AUTOTUNE)
    train_ds = ds.skip(VAL_ROWS).batch(BATCH).prefetch(tf.data.AUTOTUNE)
    return train_ds, val_ds
