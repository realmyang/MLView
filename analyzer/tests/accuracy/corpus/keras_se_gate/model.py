"""A small squeeze-and-excite CNN with a linear head.

Nothing here is a defect. The `Dense(channels, activation="sigmoid")` inside
`se_block` is the SENet / EfficientNet / MobileNetV3 channel gate - its output
is multiplied back into the feature map, it is not the model's output - and the
head really is linear, which is exactly what `from_logits=True` asks for.
"""
from __future__ import annotations

from tensorflow import keras
from tensorflow.keras import layers


def se_block(x, channels: int, ratio: int = 8):
    squeeze = layers.GlobalAveragePooling2D()(x)
    squeeze = layers.Dense(channels // ratio, activation="relu")(squeeze)
    excite = layers.Dense(channels, activation="sigmoid")(squeeze)
    return layers.Multiply()([x, excite])


def build_model(side: int = 64) -> keras.Model:
    inputs = keras.Input(shape=(side, side, 3))
    hidden = layers.Conv2D(32, 3, padding="same", activation="relu")(inputs)
    hidden = se_block(hidden, 32)
    hidden = layers.Conv2D(64, 3, padding="same", activation="relu")(hidden)
    hidden = se_block(hidden, 64)
    hidden = layers.GlobalAveragePooling2D()(hidden)
    outputs = layers.Dense(1)(hidden)

    model = keras.Model(inputs, outputs, name="panels")
    model.compile(
        optimizer=keras.optimizers.Adam(1e-3),
        loss=keras.losses.BinaryCrossentropy(from_logits=True),
        metrics=[keras.metrics.AUC(name="auc")],
    )
    return model
