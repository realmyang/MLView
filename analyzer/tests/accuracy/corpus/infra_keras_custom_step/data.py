"""tf.data input pipelines.

The holdout is cut **before** anything is shuffled, which is the correct order:
`take`/`skip` run on the deterministic base dataset and only the training half
is shuffled afterwards. MLV121 must not fire here.
"""
from __future__ import annotations

import tensorflow as tf

AUTOTUNE = tf.data.AUTOTUNE
IMAGE_SIZE = (96, 96)
SEED = 1917


def _decode(path: tf.Tensor, label: tf.Tensor):
    image = tf.io.decode_jpeg(tf.io.read_file(path), channels=3)
    image = tf.image.resize(image, IMAGE_SIZE)
    return tf.cast(image, tf.float32) / 255.0, label


def _augment(image: tf.Tensor, label: tf.Tensor):
    image = tf.image.random_flip_left_right(image, seed=SEED)
    image = tf.image.random_brightness(image, max_delta=0.1, seed=SEED)
    return image, label


def build_datasets(paths, labels, batch_size: int = 64,
                   val_fraction: float = 0.2):
    base = tf.data.Dataset.from_tensor_slices((paths, labels))
    base = base.map(_decode, num_parallel_calls=AUTOTUNE)

    total = len(paths)
    val_size = int(total * val_fraction)

    # Split first. `base` has never been shuffled, so these two halves are
    # disjoint and stable across epochs.
    val_ds = base.take(val_size)
    train_ds = base.skip(val_size)

    train_ds = (train_ds
                .shuffle(2048, seed=SEED, reshuffle_each_iteration=True)
                .map(_augment, num_parallel_calls=AUTOTUNE)
                .batch(batch_size, drop_remainder=True)
                .prefetch(AUTOTUNE))
    val_ds = (val_ds
              .batch(batch_size)
              .prefetch(AUTOTUNE))
    return train_ds, val_ds
