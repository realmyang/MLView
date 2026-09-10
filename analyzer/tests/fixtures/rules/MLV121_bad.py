# MLVIEW-EXPECT: MLV121 line=15 confidence>=0.6 severity=high
"""shuffle() feeds take()/skip() with reshuffle_each_iteration left at its
default, so tf.data re-draws the two halves on every epoch and the validation
set has been trained on by the second pass."""
import tensorflow as tf
from tensorflow import keras

keras.utils.set_random_seed(0)
BATCH = 64
VAL_SIZE = 500


def make_datasets(features, labels):
    base = tf.data.Dataset.from_tensor_slices((features, labels))
    shuffled = base.shuffle(4096)
    val_ds = shuffled.take(VAL_SIZE).batch(BATCH)
    train_ds = shuffled.skip(VAL_SIZE).batch(BATCH)
    return train_ds.prefetch(tf.data.AUTOTUNE), val_ds.prefetch(tf.data.AUTOTUNE)
