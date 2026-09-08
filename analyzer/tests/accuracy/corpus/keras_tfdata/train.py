"""Entry point: `model.fit` owns the loop and no seed is set anywhere."""
from __future__ import annotations

from tensorflow import keras

from model import build_model
from pipeline import make_datasets


def main(csv_path: str = "data/requests.csv"):
    train_ds, val_ds = make_datasets(csv_path)
    model = build_model()
    model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=30,
        callbacks=[keras.callbacks.EarlyStopping(patience=4, restore_best_weights=True)],
    )
    print(model.evaluate(val_ds))
    return model.predict(val_ds)


if __name__ == "__main__":
    main()
