"""The Keras head. Planted defect: nothing ever compiles this model, so the
first fit() raises before a single gradient is computed.

The output layer carries an explicit softmax activation, and there is no loss
object anywhere in the project - the activation on its own is not a defect.
"""
from __future__ import annotations

from tensorflow import keras
from tensorflow.keras import layers


def build_model(n_features: int = 40, classes: int = 3) -> keras.Model:
    inputs = keras.Input(shape=(n_features,))
    hidden = layers.Dense(256, activation="relu")(inputs)
    hidden = layers.BatchNormalization()(hidden)
    hidden = layers.Dropout(0.4)(hidden)
    hidden = layers.Dense(128, activation="relu")(hidden)
    outputs = layers.Dense(classes, activation="softmax")(hidden)

    return keras.Model(inputs, outputs, name="clicks")
