"""tf.data input pipeline for the image classifier.

The holdout is carved out **before** anything is shuffled: `take`/`skip` on the
ordered base dataset, and only the training half is shuffled afterwards. That
ordering is the whole reason the validation split stays the same set of images
on every epoch.
"""

from __future__ import annotations

import tensorflow as tf

IMAGE_SIZE = (180, 180)
BATCH_SIZE = 32
SEED = 1234
SHUFFLE_BUFFER = 2048
AUTOTUNE = tf.data.AUTOTUNE


def decode(path: tf.Tensor, label: tf.Tensor):
    """Read one JPEG, resize it, scale it to [0, 1]."""
    image = tf.io.decode_jpeg(tf.io.read_file(path), channels=3)
    image = tf.image.resize(image, IMAGE_SIZE)
    return tf.cast(image, tf.float32) / 255.0, label


def augment(image: tf.Tensor, label: tf.Tensor):
    """Flip, brightness and contrast jitter - training only."""
    image = tf.image.random_flip_left_right(image, seed=SEED)
    image = tf.image.random_brightness(image, max_delta=0.2, seed=SEED)
    image = tf.image.random_contrast(image, lower=0.8, upper=1.2, seed=SEED)
    return tf.clip_by_value(image, 0.0, 1.0), label


def base_dataset(paths, labels) -> tf.data.Dataset:
    """An ordered dataset of (path, label) pairs, decoded in parallel."""
    dataset = tf.data.Dataset.from_tensor_slices((paths, labels))
    return dataset.map(decode, num_parallel_calls=AUTOTUNE)


def build_datasets(paths, labels, validation_fraction: float = 0.2):
    """Split first, then shuffle the training half only."""
    total = len(paths)
    validation_size = int(total * validation_fraction)

    base = base_dataset(paths, labels)
    validation_raw = base.take(validation_size)
    train_raw = base.skip(validation_size)

    train_ds = (train_raw
                .shuffle(SHUFFLE_BUFFER, seed=SEED, reshuffle_each_iteration=True)
                .map(augment, num_parallel_calls=AUTOTUNE)
                .batch(BATCH_SIZE)
                .prefetch(AUTOTUNE))
    validation_ds = (validation_raw
                     .batch(BATCH_SIZE)
                     .cache()
                     .prefetch(AUTOTUNE))
    return train_ds, validation_ds


def build_test_dataset(paths, labels) -> tf.data.Dataset:
    """The test split is its own file list: never sampled, never augmented."""
    return (base_dataset(paths, labels)
            .batch(BATCH_SIZE)
            .prefetch(AUTOTUNE))
