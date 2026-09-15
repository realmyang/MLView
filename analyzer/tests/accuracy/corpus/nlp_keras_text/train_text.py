"""A bidirectional-LSTM review classifier in Keras."""

import numpy as np
import tensorflow as tf
from tensorflow import keras

from vectorize import (
    MAX_TOKENS,
    SEQUENCE_LENGTH,
    build_vectorizer,
    make_dataset,
    read_frame,
    split_frame,
    vectorize_dataset,
)

SEED = 1337


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
        loss=keras.losses.BinaryCrossentropy(from_logits=False),
        metrics=[keras.metrics.BinaryAccuracy(name="acc"),
                 keras.metrics.AUC(name="auc")],
    )
    return model


def main(csv_path="reviews.csv", epochs=5, out_dir="runs/reviews"):
    keras.utils.set_random_seed(SEED)
    tf.config.experimental.enable_op_determinism()
    frame = read_frame(csv_path)
    train_frame, val_frame, test_frame = split_frame(frame, seed=SEED)
    train_raw = make_dataset(train_frame, shuffle=True, seed=SEED)
    val_raw = make_dataset(val_frame)
    test_raw = make_dataset(test_frame)
    vectorizer = build_vectorizer(train_raw)
    train_ds = vectorize_dataset(train_raw, vectorizer)
    val_ds = vectorize_dataset(val_raw, vectorizer)
    test_ds = vectorize_dataset(test_raw, vectorizer)
    model = compile_model(build_model())
    callbacks = [
        keras.callbacks.EarlyStopping(monitor="val_auc", mode="max", patience=2,
                                      restore_best_weights=True),
        keras.callbacks.ModelCheckpoint(out_dir + "/best.keras",
                                        monitor="val_auc", mode="max",
                                        save_best_only=True),
    ]
    history = model.fit(train_ds, validation_data=val_ds, epochs=epochs,
                        callbacks=callbacks, verbose=2)
    scores = model.evaluate(test_ds, return_dict=True, verbose=0)
    probabilities = model.predict(test_ds, verbose=0).ravel()
    print("test", scores, "mean p", float(np.mean(probabilities)))
    model.export(out_dir + "/saved_model")
    return history, scores


if __name__ == "__main__":
    main()
