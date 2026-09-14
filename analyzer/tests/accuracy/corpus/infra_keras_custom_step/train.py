"""Entrypoint: build the datasets, compile, fit with callbacks, evaluate.

Seeded with `keras.utils.set_random_seed`, so MLV601 must not fire.
"""
from __future__ import annotations

import glob
import os

import tensorflow as tf
from tensorflow import keras

from data import SEED, build_datasets
from model import EMAClassifier, build_backbone, compile_model

EPOCHS = 25
BATCH_SIZE = 64
RUN_DIR = "runs/tiny_convnet"


def discover(root: str = "data/images"):
    paths = sorted(glob.glob(os.path.join(root, "*", "*.jpg")))
    classes = sorted({os.path.basename(os.path.dirname(p)) for p in paths})
    index = {name: i for i, name in enumerate(classes)}
    labels = [index[os.path.basename(os.path.dirname(p))] for p in paths]
    return paths, labels


def callbacks():
    return [
        keras.callbacks.ModelCheckpoint(
            filepath=os.path.join(RUN_DIR, "best.keras"),
            monitor="val_accuracy", mode="max", save_best_only=True),
        keras.callbacks.EarlyStopping(monitor="val_loss", patience=6,
                                      restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                                          patience=3, min_lr=1e-6),
        keras.callbacks.CSVLogger(os.path.join(RUN_DIR, "history.csv")),
        keras.callbacks.TensorBoard(log_dir=os.path.join(RUN_DIR, "tb")),
    ]


def main() -> None:
    keras.utils.set_random_seed(SEED)
    os.makedirs(RUN_DIR, exist_ok=True)

    paths, labels = discover()
    train_ds, val_ds = build_datasets(paths, labels, batch_size=BATCH_SIZE)

    model = EMAClassifier(build_backbone())
    compile_model(model, lr=1e-3)

    history = model.fit(train_ds, validation_data=val_ds, epochs=EPOCHS,
                        callbacks=callbacks())
    print(history.history.keys())

    results = model.evaluate(val_ds, return_dict=True)
    print(results)
    model.save(os.path.join(RUN_DIR, "final.keras"))


if __name__ == "__main__":
    main()
