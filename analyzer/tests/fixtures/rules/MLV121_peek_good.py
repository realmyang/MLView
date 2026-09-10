# MLVIEW-EXPECT-NONE: MLV121
"""The trap: `for images, labels in train_ds.take(1)` is the commonest line in
TensorFlow code - a peek at one batch to print its shapes. It is a TFDATA_SUBSET
downstream of a shuffle, and nothing else about it resembles a holdout: there is
no skip, no evaluation dataset and no two halves to re-draw. A subset on its own
is not a split, so the rule stays silent."""
import tensorflow as tf
from tensorflow import keras

keras.utils.set_random_seed(0)
BATCH = 32


def make_dataset(features, labels):
    base = tf.data.Dataset.from_tensor_slices((features, labels))
    train_ds = base.shuffle(2048).batch(BATCH).prefetch(tf.data.AUTOTUNE)
    for images, targets in train_ds.take(1):
        print(images.shape, targets.shape)
    return train_ds
