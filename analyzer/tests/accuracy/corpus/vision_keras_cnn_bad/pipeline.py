"""tf.data input pipeline (defective twin).

Defect 1: the base dataset is shuffled and *then* split with take/skip. tf.data
re-draws the shuffle buffer on every epoch, so the validation rows swap with
the training rows every pass and the holdout stops existing.
Defect 2: the augmentation map is applied to the validation dataset too.
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
    """Flip, brightness and contrast jitter."""
    image = tf.image.random_flip_left_right(image)
    image = tf.image.random_brightness(image, max_delta=0.2)
    image = tf.image.random_contrast(image, lower=0.8, upper=1.2)
    return tf.clip_by_value(image, 0.0, 1.0), label


def base_dataset(paths, labels) -> tf.data.Dataset:
    dataset = tf.data.Dataset.from_tensor_slices((paths, labels))
    return dataset.map(decode, num_parallel_calls=AUTOTUNE)


def build_datasets(paths, labels, validation_fraction: float = 0.2):
    """Defects 1 and 2: shuffle then split, and augment both halves."""
    total = len(paths)
    validation_size = int(total * validation_fraction)

    shuffled = base_dataset(paths, labels).shuffle(SHUFFLE_BUFFER, seed=SEED)
    validation_raw = shuffled.take(validation_size)
    train_raw = shuffled.skip(validation_size)

    train_ds = (train_raw
                .map(augment, num_parallel_calls=AUTOTUNE)
                .batch(BATCH_SIZE)
                .prefetch(AUTOTUNE))
    validation_ds = (validation_raw
                     .map(augment, num_parallel_calls=AUTOTUNE)
                     .batch(BATCH_SIZE)
                     .prefetch(AUTOTUNE))
    return train_ds, validation_ds


def build_test_dataset(paths, labels) -> tf.data.Dataset:
    return (base_dataset(paths, labels)
            .map(augment, num_parallel_calls=AUTOTUNE)
            .batch(BATCH_SIZE)
            .prefetch(AUTOTUNE))
