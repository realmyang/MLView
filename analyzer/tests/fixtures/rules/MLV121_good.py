# MLVIEW-EXPECT-NONE: MLV121
"""The trap: the identical shuffle-then-take/skip chain, made honest by the one
keyword that pins the permutation - reshuffle_each_iteration=False. The training
half is then shuffled again per epoch, which is what you actually want."""
import tensorflow as tf
from tensorflow import keras

keras.utils.set_random_seed(0)
BATCH = 64
VAL_SIZE = 500


def make_datasets(features, labels):
    base = tf.data.Dataset.from_tensor_slices((features, labels))
    fixed = base.shuffle(4096, reshuffle_each_iteration=False)
    val_ds = fixed.take(VAL_SIZE).batch(BATCH)
    train_ds = fixed.skip(VAL_SIZE).shuffle(2048).batch(BATCH)
    return train_ds.prefetch(tf.data.AUTOTUNE), val_ds.prefetch(tf.data.AUTOTUNE)
