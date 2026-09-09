"""FW-RECOG positive fixture: the Keras families the prototype table missed.

`keras.applications`, `Input`, `Rescaling`, `GlobalAveragePooling2D` and the
callbacks were all absent, so a textbook transfer-learning model contributed a
`compile` and a `fit` and nothing in between.

It also exercises the **functional API**: `layers.Dense(...)(x)` is a call whose
callee is another call, which ANA-5a's syntactic check would otherwise flag as
an unresolvable callee and draw as an `unknown` node - four of them in fifteen
lines. `ir/resolve._called_value` resolves it to `keras.Model.__call__`, role
FORWARD, which the graph already draws through its receiver.
"""
from __future__ import annotations

import keras
from keras import layers

CLASSES = 10
SIZE = (224, 224, 3)


def build_model(num_classes: int = CLASSES):
    base = keras.applications.MobileNetV2(include_top=False, weights="imagenet")
    base.trainable = False

    inputs = keras.Input(shape=SIZE)
    x = layers.Rescaling(1.0 / 255)(inputs)
    x = layers.RandomFlip("horizontal")(x)
    x = base(x, training=False)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.2)(x)
    outputs = layers.Dense(num_classes, activation="softmax")(x)

    model = keras.Model(inputs, outputs)
    model.compile(optimizer=keras.optimizers.AdamW(learning_rate=1e-3),
                  loss=keras.losses.SparseCategoricalCrossentropy(),
                  metrics=[keras.metrics.SparseCategoricalAccuracy()])
    return model


def fit(model: keras.Model, train_ds, val_ds, epochs: int = 10):
    keras.utils.set_random_seed(21)
    callbacks = [
        keras.callbacks.EarlyStopping(patience=3, restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(factor=0.5, patience=2),
        keras.callbacks.ModelCheckpoint("out/best.keras", save_best_only=True),
        keras.callbacks.CSVLogger("out/history.csv"),
    ]
    return model.fit(train_ds, validation_data=val_ds, epochs=epochs,
                     callbacks=callbacks)
