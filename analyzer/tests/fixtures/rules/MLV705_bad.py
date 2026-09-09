# MLVIEW-EXPECT: MLV705 line=19 confidence>=0.6 severity=high
"""A Keras model that is fitted straight after construction, never compiled."""
from tensorflow import keras
from tensorflow.keras import layers

keras.utils.set_random_seed(0)


def build_model(n_features: int = 20) -> keras.Model:
    inputs = keras.Input(shape=(n_features,))
    hidden = layers.Dense(64, activation="relu")(inputs)
    hidden = layers.Dropout(0.2)(hidden)
    outputs = layers.Dense(3)(hidden)
    return keras.Model(inputs, outputs)


def main(features, labels):
    model = build_model()
    model.fit(features, labels, epochs=5, batch_size=32,
              validation_split=0.2)
    return model
