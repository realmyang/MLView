"""Fit the squeeze-and-excite classifier on the tf.data pipeline."""
from __future__ import annotations

from model import build_model
from pipeline import make_datasets

EPOCHS = 8


def main(npz_path: str = "data/panels.npz"):
    train_ds, val_ds = make_datasets(npz_path)
    model = build_model()
    model.fit(train_ds, validation_data=val_ds, epochs=EPOCHS)
    model.evaluate(val_ds)
    return model


if __name__ == "__main__":
    main()
