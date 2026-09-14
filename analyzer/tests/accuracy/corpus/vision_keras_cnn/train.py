"""Build, compile and fit the Keras CNN.

The output layer is a bare `Dense(num_classes)` and the loss is built with
`from_logits=True`: exactly one of the two applies the softmax, and it is the
loss.
"""

from __future__ import annotations

import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

from pipeline import BATCH_SIZE, IMAGE_SIZE, SEED, build_datasets, build_test_dataset

NUM_CLASSES = 5
EPOCHS = 30
LEARNING_RATE = 1e-3
CHECKPOINT = "keras_cnn.keras"


def set_seeds(seed: int = SEED) -> None:
    np.random.seed(seed)
    tf.random.set_seed(seed)
    keras.utils.set_random_seed(seed)


def build_model(num_classes: int = NUM_CLASSES) -> keras.Model:
    """A small VGG-shaped convnet whose head returns logits."""
    inputs = keras.Input(shape=IMAGE_SIZE + (3,))
    x = layers.Conv2D(32, 3, padding="same", activation="relu")(inputs)
    x = layers.BatchNormalization()(x)
    x = layers.MaxPooling2D()(x)
    x = layers.Conv2D(64, 3, padding="same", activation="relu")(x)
    x = layers.BatchNormalization()(x)
    x = layers.MaxPooling2D()(x)
    x = layers.Conv2D(128, 3, padding="same", activation="relu")(x)
    x = layers.BatchNormalization()(x)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.3)(x)
    outputs = layers.Dense(num_classes)(x)
    return keras.Model(inputs, outputs, name="small_vgg")


def compile_model(model: keras.Model) -> keras.Model:
    """Logits in, so `from_logits=True` on both the loss and the metric."""
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=LEARNING_RATE),
        loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        metrics=[keras.metrics.SparseCategoricalAccuracy(name="acc")],
    )
    return model


def callbacks() -> list:
    return [
        keras.callbacks.ModelCheckpoint(CHECKPOINT, monitor="val_acc",
                                        save_best_only=True, mode="max"),
        keras.callbacks.EarlyStopping(monitor="val_loss", patience=5,
                                      restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                                          patience=2),
    ]


def main(train_paths, train_labels, test_paths, test_labels) -> dict:
    set_seeds()
    train_ds, validation_ds = build_datasets(train_paths, train_labels)
    test_ds = build_test_dataset(test_paths, test_labels)

    model = build_model()
    compile_model(model)
    history = model.fit(
        train_ds,
        validation_data=validation_ds,
        epochs=EPOCHS,
        callbacks=callbacks(),
        verbose=2,
    )

    scores = model.evaluate(test_ds, return_dict=True, verbose=0)
    print("test loss %.4f acc %.4f" % (scores["loss"], scores["acc"]))
    model.save(CHECKPOINT)
    return {"history": history.history, "test": scores}


if __name__ == "__main__":
    main([], [], [], [])
