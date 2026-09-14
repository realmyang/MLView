"""tf.data input pipeline for the flowers transfer-learning classifier.

The holdout is carved **before** anything is shuffled, so the two halves are
fixed for the life of the run: `base` is built once from the file list, the
first `validation_size` rows become validation and the rest become training,
and only the training half is ever shuffled. That ordering is the whole point -
`shuffle()` re-draws its buffer on every epoch unless you say otherwise, so a
`shuffle().take()/skip()` pair swaps rows between the halves every pass.

Augmentation lives in `augment()` and is mapped onto the training half only.
The validation and test halves go through `decode()` and nothing else.
"""

from __future__ import annotations

import tensorflow as tf

AUTOTUNE = tf.data.AUTOTUNE
IMAGE_SIZE = (300, 300)
BATCH_SIZE = 32
SHUFFLE_BUFFER = 2048
SEED = 20260913


def decode(path: tf.Tensor, label: tf.Tensor):
    """Read one JPEG off disk and resize it to the backbone's input size."""
    raw = tf.io.read_file(path)
    image = tf.io.decode_jpeg(raw, channels=3)
    image = tf.image.convert_image_dtype(image, tf.float32)
    image = tf.image.resize(image, IMAGE_SIZE, method="bilinear")
    return image, label


def augment(image: tf.Tensor, label: tf.Tensor):
    """Training-only jitter: flip, brightness, contrast, a small random crop."""
    image = tf.image.random_flip_left_right(image, seed=SEED)
    image = tf.image.random_brightness(image, max_delta=0.15, seed=SEED)
    image = tf.image.random_contrast(image, lower=0.85, upper=1.15, seed=SEED)
    padded = tf.image.resize_with_crop_or_pad(
        image, IMAGE_SIZE[0] + 32, IMAGE_SIZE[1] + 32)
    image = tf.image.random_crop(padded, IMAGE_SIZE + (3,), seed=SEED)
    return tf.clip_by_value(image, 0.0, 1.0), label


def base_dataset(paths, labels) -> tf.data.Dataset:
    """The decoded, un-shuffled, un-augmented rows in file order."""
    dataset = tf.data.Dataset.from_tensor_slices((paths, labels))
    return dataset.map(decode, num_parallel_calls=AUTOTUNE)


def finalize(dataset: tf.data.Dataset, training: bool) -> tf.data.Dataset:
    """Batch and prefetch; shuffle and augment only when this is the train half."""
    if training:
        dataset = dataset.shuffle(SHUFFLE_BUFFER, seed=SEED,
                                  reshuffle_each_iteration=True)
        dataset = dataset.map(augment, num_parallel_calls=AUTOTUNE)
    return dataset.batch(BATCH_SIZE).prefetch(AUTOTUNE)


def build_datasets(paths, labels, validation_fraction: float = 0.2):
    """Split first, then shuffle the training half - never the other way round."""
    total = len(paths)
    validation_size = int(total * validation_fraction)

    base = base_dataset(paths, labels)
    validation_raw = base.take(validation_size)
    train_raw = base.skip(validation_size)

    train_ds = finalize(train_raw, training=True)
    validation_ds = finalize(validation_raw, training=False)
    return train_ds, validation_ds


def build_test_dataset(paths, labels) -> tf.data.Dataset:
    """The test split is its own file list and is never shuffled or augmented."""
    return finalize(base_dataset(paths, labels), training=False)


def class_names(label_map: dict) -> list:
    """Stable ordering for the confusion matrix and the served label list."""
    return [name for name, _index in sorted(label_map.items(),
                                            key=lambda pair: pair[1])]
