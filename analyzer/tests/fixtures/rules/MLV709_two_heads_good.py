# MLVIEW-EXPECT-NONE: MLV709
"""The trap: one module, two builders, the same activation family. The probs
head is compiled with from_logits=False and the logits head with
from_logits=True, and each is correct. Pairing by family alone accused the
correct softmax head of contradicting the *other* model's loss; the pairing has
to reach the same keras.Model(inputs, outputs) to mean anything."""
from tensorflow import keras
from tensorflow.keras import layers

keras.utils.set_random_seed(0)


def probs_model(classes: int = 4) -> keras.Model:
    inputs = keras.Input(shape=(32,))
    outputs = layers.Dense(classes, activation="softmax")(inputs)
    model = keras.Model(inputs, outputs)
    model.compile(optimizer="adam",
                  loss=keras.losses.CategoricalCrossentropy(from_logits=False))
    return model


def logits_model(classes: int = 4) -> keras.Model:
    inputs = keras.Input(shape=(32,))
    outputs = layers.Dense(classes)(inputs)
    model = keras.Model(inputs, outputs)
    model.compile(optimizer="adam",
                  loss=keras.losses.CategoricalCrossentropy(from_logits=True))
    return model
