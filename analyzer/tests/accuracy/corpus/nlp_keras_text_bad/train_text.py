"""A bidirectional-LSTM review classifier in Keras.

Defective twin of `nlp_keras_text/train_text.py`.
"""

import numpy as np
import tensorflow as tf
from sklearn.metrics import accuracy_score
from tensorflow import keras

from vectorize import (
    MAX_TOKENS,
    SEQUENCE_LENGTH,
    build_vectorizer,
    make_dataset,
    read_frame,
    split_dataset,
    vectorize_dataset,
)


def build_model(embedding_dim=128, units=64):
    inputs = keras.Input(shape=(SEQUENCE_LENGTH,), dtype="int64")
    x = keras.layers.Embedding(MAX_TOKENS, embedding_dim, mask_zero=True)(inputs)
    x = keras.layers.Bidirectional(keras.layers.LSTM(units, return_sequences=True))(x)
    x = keras.layers.GlobalMaxPooling1D()(x)
    x = keras.layers.Dropout(0.3)(x)
    outputs = keras.layers.Dense(1, activation="sigmoid")(x)
    return keras.Model(inputs, outputs, name="review_classifier")


def compile_model(model, lr=1e-3):
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=lr),
        loss=keras.losses.BinaryCrossentropy(from_logits=True),
        metrics=[keras.metrics.BinaryAccuracy(name="acc")],
    )
    return model


def main(csv_path="reviews.csv", epochs=5, out_dir="runs/reviews"):
    frame = read_frame(csv_path)
    full = make_dataset(frame)
    vectorizer = build_vectorizer(full)
    n_test = int(0.2 * len(frame))
    n_val = int(0.1 * len(frame))
    train_raw, val_raw, test_raw = split_dataset(full, n_test, n_val)
    train_ds = vectorize_dataset(train_raw, vectorizer)
    val_ds = vectorize_dataset(val_raw, vectorizer)
    test_ds = vectorize_dataset(test_raw, vectorizer)
    model = compile_model(build_model())
    history = model.fit(train_ds, validation_data=val_ds, epochs=epochs, verbose=2)
    probabilities = model.predict(test_ds, verbose=0).ravel()
    truth = np.concatenate([labels.numpy() for _, labels in test_ds])
    print("test accuracy", accuracy_score(truth, probabilities))
    model.save(out_dir + "/final.keras")
    return history


if __name__ == "__main__":
    main()
