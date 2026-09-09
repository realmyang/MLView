# MLVIEW-EXPECT: MLV709 line=15 confidence>=0.6 severity=high
"""A softmax output layer compiled against CategoricalCrossentropy(from_logits=
True), so the loss log-softmaxes an already-normalised distribution."""
from tensorflow import keras
from tensorflow.keras import layers

keras.utils.set_random_seed(0)


def build_model(n_features: int = 20, classes: int = 4) -> keras.Model:
    inputs = keras.Input(shape=(n_features,))
    hidden = layers.Dense(128, activation="relu")(inputs)
    hidden = layers.BatchNormalization()(hidden)
    hidden = layers.Dropout(0.3)(hidden)
    outputs = layers.Dense(classes, activation="softmax")(hidden)

    model = keras.Model(inputs, outputs)
    model.compile(
        optimizer=keras.optimizers.Adam(1e-3),
        loss=keras.losses.CategoricalCrossentropy(from_logits=True),
        metrics=[keras.metrics.CategoricalAccuracy()],
    )
    return model
