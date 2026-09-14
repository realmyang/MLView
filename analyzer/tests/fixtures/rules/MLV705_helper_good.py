# MLVIEW-EXPECT-NONE: MLV705
"""vision-01. The trap: the compile lives in a helper with an untyped parameter.

MLV705 is a workspace-wide absence claim: it fires when `ctx.calls_with_role(
"KERAS_COMPILE")` is empty. `model.compile(...)` earns that role only when its
receiver resolves to a Keras model, and an unannotated parameter never does -
so the textbook `build_model()` / `compile_model(model)` split produced zero
KERAS_COMPILE calls, and the rule accused correct code at high / 0.95 with the
message "no compile() call exists anywhere in this workspace" about a workspace
whose first function contains `model.compile(`. An unresolved receiver is not
an absence.
"""
import keras
from keras import layers


def build_model(classes: int = 5):
    inputs = keras.Input(shape=(32, 32, 3))
    x = layers.Conv2D(16, 3, activation="relu")(inputs)
    x = layers.GlobalAveragePooling2D()(x)
    return keras.Model(inputs, layers.Dense(classes)(x))


def compile_model(model, lr: float = 1e-3):
    model.compile(optimizer=keras.optimizers.Adam(lr),
                  loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
                  metrics=["accuracy"])
    return model


def main(train_ds, val_ds, epochs: int = 3):
    keras.utils.set_random_seed(0)
    model = build_model()
    compile_model(model)
    model.fit(train_ds, validation_data=val_ds, epochs=epochs)
    return model
