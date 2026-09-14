"""TensorFlow 2 the *low-level* way: `tf.GradientTape` inside `tf.function`,
distributed over a `MirroredStrategy`, with no `model.fit()` anywhere.

This is the shape every TF research repo and every `tensorflow/models` example
uses once it outgrows `.fit()`, and it is a different program from the Keras
functional script in `keras_tfdata`: there is no `compile()`, no callback list
and no `fit()` call for a rule to hang a claim on. The training step is
`with tf.GradientTape() as tape: ... optimizer.apply_gradients(...)`, and it is
a per-replica function handed to `strategy.run`.

Everything here is correct:

* the holdout is cut **before** any shuffling (`splits.py` slices the arrays and
  only the training half is ever `shuffle`d), so `tf.data`'s per-epoch reshuffle
  cannot move a row across the boundary;
* the head is `Dense(classes)` with no activation and the loss is built with
  `from_logits=True`, which is the pairing those two require;
* `tf.random.set_seed(...)` and `keras.utils.set_random_seed(...)` both run
  before anything is built;
* the evaluation pass runs `training=False` on every forward, which is how TF
  spells `model.eval()` — there is no `.eval()` and no `torch.no_grad()` in
  TensorFlow and there must not be;
* the checkpoint is a `tf.train.Checkpoint` / `CheckpointManager` pair.

Any finding in this file is a false positive, and any finding that recommends a
PyTorch API is doubly one.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

from splits import chronological_split

AUTOTUNE = tf.data.AUTOTUNE


def build_model(features: int, classes: int) -> keras.Model:
    """Functional model whose head emits logits - no softmax, on purpose."""
    inputs = keras.Input(shape=(features,), name="features")
    x = layers.Dense(128)(inputs)
    x = layers.BatchNormalization()(x)
    x = layers.Activation("gelu")(x)
    x = layers.Dropout(0.2)(x)
    x = layers.Dense(64, activation="gelu")(x)
    outputs = layers.Dense(classes, name="logits")(x)
    return keras.Model(inputs, outputs, name="tabular_mlp")


def build_datasets(batch_size: int, seed: int):
    rng = np.random.default_rng(seed)
    features = rng.normal(size=(8192, 32)).astype("float32")
    labels = rng.integers(0, 4, size=(8192,)).astype("int32")

    (x_train, y_train), (x_val, y_val) = chronological_split(features, labels,
                                                            holdout=0.2)

    train_ds = (tf.data.Dataset.from_tensor_slices((x_train, y_train))
                .shuffle(4096, seed=seed, reshuffle_each_iteration=True)
                .batch(batch_size, drop_remainder=True)
                .prefetch(AUTOTUNE))
    val_ds = (tf.data.Dataset.from_tensor_slices((x_val, y_val))
              .batch(batch_size)
              .prefetch(AUTOTUNE))
    return train_ds, val_ds


def make_step(strategy, model, optimizer, loss_fn, train_metric):
    """The per-replica training step, compiled once and run under the strategy."""

    def step_fn(batch):
        features, labels = batch
        with tf.GradientTape() as tape:
            logits = model(features, training=True)
            per_example = loss_fn(labels, logits)
            loss = tf.nn.compute_average_loss(per_example)
        grads = tape.gradient(loss, model.trainable_variables)
        grads, _norm = tf.clip_by_global_norm(grads, 1.0)
        optimizer.apply_gradients(zip(grads, model.trainable_variables))
        train_metric.update_state(labels, logits)
        return loss

    @tf.function
    def distributed_step(batch):
        per_replica = strategy.run(step_fn, args=(batch,))
        return strategy.reduce(tf.distribute.ReduceOp.SUM, per_replica, axis=None)

    return distributed_step


def make_eval_step(strategy, model, loss_fn, val_metric):
    """Evaluation: `training=False` is how TensorFlow turns dropout off."""

    def step_fn(batch):
        features, labels = batch
        logits = model(features, training=False)
        val_metric.update_state(labels, logits)
        return tf.reduce_mean(loss_fn(labels, logits))

    @tf.function
    def distributed_step(batch):
        per_replica = strategy.run(step_fn, args=(batch,))
        return strategy.reduce(tf.distribute.ReduceOp.MEAN, per_replica, axis=None)

    return distributed_step


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TF2 custom training loop")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=Path("checkpoints/tf"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tf.random.set_seed(args.seed)
    keras.utils.set_random_seed(args.seed)

    strategy = tf.distribute.MirroredStrategy()
    train_ds, val_ds = build_datasets(args.batch_size, args.seed)
    train_dist = strategy.experimental_distribute_dataset(train_ds)
    val_dist = strategy.experimental_distribute_dataset(val_ds)

    with strategy.scope():
        model = build_model(features=32, classes=4)
        optimizer = keras.optimizers.AdamW(learning_rate=args.lr,
                                           weight_decay=1e-4)
        loss_fn = keras.losses.SparseCategoricalCrossentropy(
            from_logits=True, reduction=keras.losses.Reduction.NONE)
        train_metric = keras.metrics.SparseCategoricalAccuracy(name="train_acc")
        val_metric = keras.metrics.SparseCategoricalAccuracy(name="val_acc")
        checkpoint = tf.train.Checkpoint(model=model, optimizer=optimizer)

    manager = tf.train.CheckpointManager(checkpoint, str(args.out), max_to_keep=3)
    train_step = make_step(strategy, model, optimizer, loss_fn, train_metric)
    eval_step = make_eval_step(strategy, model, loss_fn, val_metric)

    for epoch in range(args.epochs):
        train_metric.reset_state()
        val_metric.reset_state()
        total = 0.0
        steps = 0
        for batch in train_dist:
            total += float(train_step(batch))
            steps += 1
        for batch in val_dist:
            eval_step(batch)
        manager.save(checkpoint_number=epoch)
        print("epoch %d loss %.4f train_acc %.4f val_acc %.4f"
              % (epoch, total / max(steps, 1),
                 float(train_metric.result()), float(val_metric.result())))

    model.export(str(args.out / "saved_model"))


if __name__ == "__main__":
    main()
