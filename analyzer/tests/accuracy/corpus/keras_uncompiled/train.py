"""Entry point: build the datasets, build the model, fit. Nothing compiles."""
from __future__ import annotations

from tensorflow import keras

from model import build_model
from pipeline import make_datasets


def main(npz_path: str = "data/clicks.npz"):
    train_ds, val_ds = make_datasets(npz_path)
    model = build_model()

    model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=15,
        callbacks=[keras.callbacks.EarlyStopping(patience=3,
                                                 restore_best_weights=True)],
    )
    return model.evaluate(val_ds)


if __name__ == "__main__":
    main()
