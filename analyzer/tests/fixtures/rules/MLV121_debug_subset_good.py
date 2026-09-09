# MLVIEW-EXPECT-NONE: MLV121
"""The trap: a debug subset carved off the same shuffled dataset that the real
pipeline batches. `debug_rows` is eight rows to eyeball, not an evaluation half:
there is no complementary skip and the name is not an evaluation name, so the
"two halves are re-drawn every epoch" claim would be a statement about code that
does not exist."""
import tensorflow as tf
from tensorflow import keras

keras.utils.set_random_seed(0)
BATCH = 32


def make_dataset(rows):
    base = tf.data.Dataset.from_tensor_slices(rows)
    shuffled = base.shuffle(1024)
    debug_rows = shuffled.take(8)
    full_ds = shuffled.batch(BATCH).prefetch(tf.data.AUTOTUNE)
    return full_ds, debug_rows
