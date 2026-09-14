"""Text vectorisation for the Keras review classifier.

The vocabulary is adapted on the training split only; the validation and test
splits are merely transformed by the layer the training split produced.
"""

import tensorflow as tf
from tensorflow import keras

MAX_TOKENS = 20000
SEQUENCE_LENGTH = 200


def read_frame(path):
    import pandas as pd

    return pd.read_csv(path)


def split_frame(frame, seed=1337):
    shuffled = frame.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    n_test = int(0.2 * len(shuffled))
    n_val = int(0.1 * len(shuffled))
    test = shuffled.iloc[:n_test]
    val = shuffled.iloc[n_test:n_test + n_val]
    train = shuffled.iloc[n_test + n_val:]
    return train, val, test


def make_dataset(frame, batch_size=32, shuffle=False, seed=1337):
    dataset = tf.data.Dataset.from_tensor_slices(
        (frame["review"].values, frame["label"].values)
    )
    if shuffle:
        dataset = dataset.shuffle(2048, seed=seed, reshuffle_each_iteration=True)
    return dataset.batch(batch_size).prefetch(tf.data.AUTOTUNE)


def build_vectorizer(train_dataset):
    vectorizer = keras.layers.TextVectorization(
        max_tokens=MAX_TOKENS,
        output_mode="int",
        output_sequence_length=SEQUENCE_LENGTH,
        standardize="lower_and_strip_punctuation",
    )
    vectorizer.adapt(train_dataset.map(lambda text, label: text))
    return vectorizer


def vectorize_dataset(dataset, vectorizer):
    return dataset.map(lambda text, label: (vectorizer(text), label),
                       num_parallel_calls=tf.data.AUTOTUNE)
