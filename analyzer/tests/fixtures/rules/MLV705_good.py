# MLVIEW-EXPECT-NONE: MLV705
"""The trap: compile() is written in the builder and fit() in the entrypoint, so
the two calls never share a scope and no binding links them. The rule is a
workspace-wide claim precisely so this shape stays silent."""
from tensorflow import keras
from tensorflow.keras import layers

keras.utils.set_random_seed(0)


def build_model(n_features: int = 20) -> keras.Model:
    inputs = keras.Input(shape=(n_features,))
    hidden = layers.Dense(64, activation="relu")(inputs)
    outputs = layers.Dense(3)(hidden)
    model = keras.Model(inputs, outputs)
    model.compile(optimizer=keras.optimizers.Adam(1e-3),
                  loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
                  metrics=["accuracy"])
    return model


def main(features, labels):
    model = build_model()
    model.fit(features, labels, epochs=5, batch_size=32, validation_split=0.2)
    return model
