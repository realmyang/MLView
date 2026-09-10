# MLVIEW-EXPECT-NONE: MLV709
"""The trap: a squeeze-and-excite block - the standard SENet / EfficientNet /
MobileNetV3 primitive - ends in Dense(ch, activation="sigmoid"), and that
sigmoid is a channel gate multiplied back into the feature map, not an output.
The head below it is linear, which is exactly what from_logits=True wants. The
rule judges position in the graph, not the presence of a literal."""
from tensorflow import keras
from tensorflow.keras import layers

keras.utils.set_random_seed(0)


def se_block(x, channels: int):
    squeeze = layers.GlobalAveragePooling2D()(x)
    squeeze = layers.Dense(channels // 8, activation="relu")(squeeze)
    excite = layers.Dense(channels, activation="sigmoid")(squeeze)
    return layers.Multiply()([x, excite])


def build_model() -> keras.Model:
    inputs = keras.Input(shape=(64, 64, 3))
    hidden = layers.Conv2D(32, 3)(inputs)
    hidden = se_block(hidden, 32)
    hidden = layers.GlobalAveragePooling2D()(hidden)
    outputs = layers.Dense(1)(hidden)
    model = keras.Model(inputs, outputs)
    model.compile(optimizer="adam",
                  loss=keras.losses.BinaryCrossentropy(from_logits=True))
    return model
