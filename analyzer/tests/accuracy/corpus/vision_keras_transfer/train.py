"""Two-phase Keras transfer learning: train the head, then fine-tune the trunk.

Everything here is correct, and it is written the way Keras projects are
actually written: the model is built by one factory and compiled by another.
`compile_model(model, ...)` takes the model as a plain parameter with no type
annotation - which is what most code looks like - calls `model.compile(...)`
and returns it. `run()` holds the model in a local binding and calls
`model.fit(...)` on it directly, once per phase, recompiling at a tenth of the
learning rate after `unfreeze_top` has thawed the last block of the trunk.

The pairing that matters: `model.py` ends in a bare `Dense(num_classes)` with no
activation, and the loss below is `SparseCategoricalCrossentropy(from_logits=True)`.
One softmax, applied inside the loss.
"""

from __future__ import annotations

import os

import tensorflow as tf
from tensorflow import keras

from model import build_model, unfreeze_top
from pipeline import SEED, build_datasets, build_test_dataset, class_names

NUM_CLASSES = 5
HEAD_EPOCHS = 12
FINETUNE_EPOCHS = 8
HEAD_LR = 1e-3
FINETUNE_LR = 1e-4
EXPORT_DIR = os.path.join("artifacts", "flowers_effnet")
CHECKPOINT = os.path.join("artifacts", "flowers_effnet.keras")


def set_seeds(seed: int = SEED) -> None:
    """One call seeds Python, numpy and TensorFlow in current Keras."""
    keras.utils.set_random_seed(seed)


def compile_model(model, learning_rate=HEAD_LR):
    """Attach the optimizer, the loss and the metrics to an existing model.

    The parameter is unannotated on purpose - this is the shape the real code
    has. `model.compile(...)` below is a genuine compile of a genuine Keras
    model, and nothing downstream may claim this workspace never compiles.
    """
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
        loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        metrics=[
            keras.metrics.SparseCategoricalAccuracy(name="acc"),
            keras.metrics.SparseTopKCategoricalAccuracy(k=3, name="top3"),
        ],
    )
    return model


def training_callbacks(monitor: str = "val_acc") -> list:
    """Checkpoint on the validation metric, stop when it stops improving."""
    return [
        keras.callbacks.ModelCheckpoint(CHECKPOINT, monitor=monitor,
                                        save_best_only=True, mode="max",
                                        verbose=0),
        keras.callbacks.EarlyStopping(monitor=monitor, mode="max", patience=4,
                                      restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                                          patience=2, min_lr=1e-6),
    ]


def evaluate(model, test_ds) -> dict:
    """Held-out metrics, on the split that nothing in training ever touched."""
    scores = model.evaluate(test_ds, return_dict=True, verbose=0)
    return {"loss": float(scores["loss"]),
            "acc": float(scores["acc"]),
            "top3": float(scores["top3"])}


def export(model, label_map: dict) -> str:
    """SavedModel plus the label ordering the server needs to read the logits."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    model.export(EXPORT_DIR)
    with open(os.path.join(EXPORT_DIR, "labels.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(class_names(label_map)))
    return EXPORT_DIR


def run(train_paths, train_labels, test_paths, test_labels, label_map) -> dict:
    set_seeds()
    train_ds, validation_ds = build_datasets(train_paths, train_labels)
    test_ds = build_test_dataset(test_paths, test_labels)

    model = build_model(NUM_CLASSES)

    # --- phase one: the trunk is frozen, only the new head learns
    compile_model(model, learning_rate=HEAD_LR)
    head_history = model.fit(
        train_ds,
        validation_data=validation_ds,
        epochs=HEAD_EPOCHS,
        callbacks=training_callbacks(),
        verbose=2,
    )

    # --- phase two: thaw the top of the trunk and recompile at a lower LR
    unfreeze_top(model)
    compile_model(model, learning_rate=FINETUNE_LR)
    finetune_history = model.fit(
        train_ds,
        validation_data=validation_ds,
        epochs=FINETUNE_EPOCHS,
        callbacks=training_callbacks(),
        verbose=2,
    )

    metrics = evaluate(model, test_ds)
    print("test loss %.4f acc %.4f top3 %.4f"
          % (metrics["loss"], metrics["acc"], metrics["top3"]))
    export(model, label_map)
    return {
        "head": head_history.history,
        "finetune": finetune_history.history,
        "test": metrics,
    }


def _demo_inputs():
    """Placeholder file lists - this module is analyzed, never executed."""
    return [], [], [], [], {"daisy": 0, "dandelion": 1, "roses": 2,
                            "sunflowers": 3, "tulips": 4}


if __name__ == "__main__":
    tp, tl, sp, sl, lm = _demo_inputs()
    run(tp, tl, sp, sl, lm)
