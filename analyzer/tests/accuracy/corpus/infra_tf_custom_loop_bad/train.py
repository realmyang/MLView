"""The defective twin of `infra_tf_custom_loop` — same TF2 custom loop, three bugs.

1. lines 49-53 — the holdout is cut with `shuffle(...)` → `take()` / `skip()`
   and no `reshuffle_each_iteration=False`. `tf.data` re-draws the shuffle
   buffer on every epoch, so the "validation" rows swap with training rows each
   pass and the holdout stops existing. This is a **total** holdout failure, not
   a partial leak (MLV121).
2. line 40 — the head is `Dense(classes, activation="softmax")` while the loss
   at line 116 is built with `from_logits=True`, so the loss takes the log of
   probabilities that have already been normalised: the gradients are wrong and
   nothing raises (MLV709).
3. nothing anywhere calls `tf.random.set_seed` / `keras.utils.set_random_seed`
   / `np.random.seed`, so neither the shuffle nor the initialisation is
   reproducible (MLV601).

Everything else is the correct twin verbatim, so any other finding is a false
positive.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

AUTOTUNE = tf.data.AUTOTUNE


def build_model(features: int, classes: int) -> keras.Model:
    """The head normalises — and the loss is told the opposite at line 116."""
    inputs = keras.Input(shape=(features,), name="features")
    x = layers.Dense(128)(inputs)
    x = layers.BatchNormalization()(x)
    x = layers.Activation("gelu")(x)
    x = layers.Dropout(0.2)(x)
    x = layers.Dense(64, activation="gelu")(x)
    outputs = layers.Dense(classes, activation="softmax", name="probs")(x)
    return keras.Model(inputs, outputs, name="tabular_mlp")


def build_datasets(batch_size: int):
    rng = np.random.default_rng()
    features = rng.normal(size=(8192, 32)).astype("float32")
    labels = rng.integers(0, 4, size=(8192,)).astype("int32")

    full = tf.data.Dataset.from_tensor_slices((features, labels))
    shuffled = full.shuffle(8192)
    val_ds = shuffled.take(1638).batch(batch_size).prefetch(AUTOTUNE)
    train_ds = (shuffled.skip(1638)
                .batch(batch_size, drop_remainder=True)
                .prefetch(AUTOTUNE))
    return train_ds, val_ds


def make_step(strategy, model, optimizer, loss_fn, train_metric):
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
    parser.add_argument("--out", type=Path, default=Path("checkpoints/tf"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    strategy = tf.distribute.MirroredStrategy()
    train_ds, val_ds = build_datasets(args.batch_size)
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
