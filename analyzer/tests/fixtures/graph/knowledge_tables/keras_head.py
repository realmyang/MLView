"""GRAPH-R2: the rest of the Keras `Model` surface.

`compile` / `fit` / `evaluate` / `predict` were already rows. `export` - the
SavedModel / TF-Lite hand-off - had none, and neither did `save`, so a Keras
project's Save / Deploy lane was empty however it shipped.
"""
from __future__ import annotations

import keras


def build_and_ship(train_ds, val_ds, out_dir: str):
    model = keras.Sequential([
        keras.layers.Dense(64, activation="relu"),
        keras.layers.Dense(10),
    ])
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy")
    model.fit(train_ds, epochs=3, validation_data=val_ds)
    model.evaluate(val_ds)
    scores = model.predict(val_ds)
    model.save(out_dir + "/model.keras")
    model.export(out_dir + "/saved_model")
    return scores
