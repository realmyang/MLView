# MLVIEW-EXPECT-NONE: MLV709
"""The trap: a softmax head sits in the same module as a from_logits=True loss -
but that loss is BinaryCrossentropy, which belongs to the sigmoid family and
pairs with the linear one-unit head below. The pairing is by activation family,
not by proximity."""
from tensorflow import keras
from tensorflow.keras import layers

keras.utils.set_random_seed(0)


def build_multiclass(n_features: int = 20, classes: int = 4) -> keras.Model:
    inputs = keras.Input(shape=(n_features,))
    hidden = layers.Dense(128, activation="relu")(inputs)
    outputs = layers.Dense(classes, activation="softmax")(hidden)
    model = keras.Model(inputs, outputs)
    model.compile(optimizer=keras.optimizers.Adam(1e-3),
                  loss=keras.losses.CategoricalCrossentropy(from_logits=False))
    return model


def build_binary(n_features: int = 20) -> keras.Model:
    inputs = keras.Input(shape=(n_features,))
    logits = layers.Dense(1)(inputs)
    model = keras.Model(inputs, logits)
    model.compile(optimizer=keras.optimizers.Adam(1e-3),
                  loss=keras.losses.BinaryCrossentropy(from_logits=True))
    return model
