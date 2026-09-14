"""Build and fit the Keras CNN (defective twin).

Defect 3: the output layer carries `activation="softmax"` while the loss is
built with `from_logits=True`, so the softmax is applied twice.
Defect 4: the fine-tuning model is fitted without ever being compiled.
Defect 5: nothing seeds TensorFlow, numpy or Python.
"""

from __future__ import annotations

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

from pipeline import IMAGE_SIZE, build_datasets, build_test_dataset

NUM_CLASSES = 5
EPOCHS = 30
LEARNING_RATE = 1e-3
CHECKPOINT = "keras_cnn.keras"


def build_model(num_classes: int = NUM_CLASSES) -> keras.Model:
    """Defect 3: a softmax head in front of a from_logits loss."""
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
    outputs = layers.Dense(num_classes, activation="softmax")(x)
    return keras.Model(inputs, outputs, name="small_vgg")


def compile_model(model: keras.Model) -> keras.Model:
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=LEARNING_RATE),
        loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        metrics=[keras.metrics.SparseCategoricalAccuracy(name="acc")],
    )
    return model


def build_finetune_model(base: keras.Model) -> keras.Model:
    """Defect 4: this head is fitted below without a compile() of its own."""
    base.trainable = False
    inputs = keras.Input(shape=IMAGE_SIZE + (3,))
    features = base(inputs, training=False)
    outputs = layers.Dense(NUM_CLASSES, activation="softmax")(features)
    return keras.Model(inputs, outputs, name="finetune_head")


def callbacks() -> list:
    return [
        keras.callbacks.ModelCheckpoint(CHECKPOINT, monitor="val_acc",
                                        save_best_only=True, mode="max"),
        keras.callbacks.EarlyStopping(monitor="val_loss", patience=5),
    ]


def main(train_paths, train_labels, test_paths, test_labels) -> dict:
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

    finetune = build_finetune_model(model)
    finetune.fit(train_ds, validation_data=validation_ds, epochs=5, verbose=2)

    scores = model.evaluate(test_ds, return_dict=True, verbose=0)
    print("test loss %.4f acc %.4f" % (scores["loss"], scores["acc"]))
    return {"history": history.history, "test": scores}


if __name__ == "__main__":
    main([], [], [], [])
