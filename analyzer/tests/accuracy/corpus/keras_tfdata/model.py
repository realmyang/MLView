"""The Keras model. Planted defect: a sigmoid output paired with a loss that
has been told the head emits logits.
"""
from __future__ import annotations

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers


def build_model(n_features: int = 5) -> keras.Model:
    inputs = keras.Input(shape=(n_features,))
    hidden = layers.Dense(64, activation="relu")(inputs)
    hidden = layers.BatchNormalization()(hidden)
    hidden = layers.Dropout(0.3)(hidden)
    outputs = layers.Dense(1, activation="sigmoid")(hidden)

    model = keras.Model(inputs, outputs)
    model.compile(
        optimizer=keras.optimizers.Adam(1e-3),
        loss=keras.losses.BinaryCrossentropy(from_logits=True),
        metrics=[keras.metrics.AUC(name="auc")],
    )
    return model
