"""Text vectorisation for the Keras review classifier.

Defective twin of `nlp_keras_text/vectorize.py`: the vocabulary is adapted on
every review in the file, and the held-out slices are cut out of a tf.data
pipeline that reshuffles its buffer on every epoch.
"""

import tensorflow as tf
from tensorflow import keras

MAX_TOKENS = 20000
SEQUENCE_LENGTH = 200


def read_frame(path):
    import pandas as pd

    return pd.read_csv(path)


def make_dataset(frame, batch_size=32):
    return tf.data.Dataset.from_tensor_slices(
        (frame["review"].values, frame["label"].values)
    )


def split_dataset(dataset, n_test, n_val, batch_size=32):
    shuffled = dataset.shuffle(2048)
    test = shuffled.take(n_test)
    rest = shuffled.skip(n_test)
    val = rest.take(n_val)
    train = rest.skip(n_val)
    return (train.batch(batch_size).prefetch(tf.data.AUTOTUNE),
            val.batch(batch_size).prefetch(tf.data.AUTOTUNE),
            test.batch(batch_size).prefetch(tf.data.AUTOTUNE))


def build_vectorizer(full_dataset):
    vectorizer = keras.layers.TextVectorization(
        max_tokens=MAX_TOKENS,
        output_mode="int",
        output_sequence_length=SEQUENCE_LENGTH,
        standardize="lower_and_strip_punctuation",
    )
    vectorizer.adapt(full_dataset.map(lambda text, label: text))
    return vectorizer


def vectorize_dataset(dataset, vectorizer):
    return dataset.map(lambda text, label: (vectorizer(text), label),
                       num_parallel_calls=tf.data.AUTOTUNE)
