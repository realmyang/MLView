"""A JAX / Flax / optax trainer.

MLView models PyTorch, scikit-learn, Keras/TF, HuggingFace and Lightning. It
models **none** of JAX, Flax or optax, and this program exists to pin down what
it does with a framework it does not know.

The correct behaviour is: recognise nothing, claim nothing, and say so. Every
finding on this file would be a false positive, because every rule that could
fire here would have to have resolved `optax.adamw` or `nn.Module.apply` to a
torch/sklearn/keras FQN that it is not.

The program itself is a complete, correct training job: a Flax `nn.Module`, an
optax chain, a `TrainState`, a jitted update step, a jitted eval step, and an
orbax-style checkpoint write.
"""
from __future__ import annotations

import functools
from typing import Any, Dict, Tuple

import flax.linen as nn
import jax
import jax.numpy as jnp
import numpy as np
import optax
from flax.training import checkpoints, train_state

SEED = 0
BATCH = 128
EPOCHS = 15


class MLP(nn.Module):
    hidden: int = 256
    classes: int = 10
    dropout: float = 0.1

    @nn.compact
    def __call__(self, x, train: bool = False):
        x = nn.Dense(self.hidden)(x)
        x = nn.gelu(x)
        x = nn.Dropout(rate=self.dropout, deterministic=not train)(x)
        x = nn.Dense(self.hidden // 2)(x)
        x = nn.gelu(x)
        return nn.Dense(self.classes)(x)


def create_train_state(rng, learning_rate: float, features: int):
    model = MLP()
    params = model.init(rng, jnp.ones([1, features]), train=False)["params"]
    tx = optax.chain(
        optax.clip_by_global_norm(1.0),
        optax.adamw(learning_rate=learning_rate, weight_decay=1e-4),
    )
    return train_state.TrainState.create(apply_fn=model.apply, params=params,
                                         tx=tx)


@functools.partial(jax.jit, static_argnums=())
def train_step(state, batch, dropout_rng):
    def loss_fn(params):
        logits = state.apply_fn({"params": params}, batch["x"], train=True,
                                rngs={"dropout": dropout_rng})
        one_hot = jax.nn.one_hot(batch["y"], 10)
        loss = optax.softmax_cross_entropy(logits=logits,
                                           labels=one_hot).mean()
        return loss, logits

    grad_fn = jax.value_and_grad(loss_fn, has_aux=True)
    (loss, logits), grads = grad_fn(state.params)
    state = state.apply_gradients(grads=grads)
    accuracy = jnp.mean(jnp.argmax(logits, -1) == batch["y"])
    return state, {"loss": loss, "accuracy": accuracy}


@jax.jit
def eval_step(state, batch) -> Dict[str, Any]:
    logits = state.apply_fn({"params": state.params}, batch["x"], train=False)
    one_hot = jax.nn.one_hot(batch["y"], 10)
    loss = optax.softmax_cross_entropy(logits=logits, labels=one_hot).mean()
    accuracy = jnp.mean(jnp.argmax(logits, -1) == batch["y"])
    return {"loss": loss, "accuracy": accuracy}


def batches(x: np.ndarray, y: np.ndarray, rng: np.random.Generator,
            shuffle: bool) -> Tuple[Dict[str, jnp.ndarray], ...]:
    order = rng.permutation(len(x)) if shuffle else np.arange(len(x))
    out = []
    for start in range(0, len(order) - BATCH + 1, BATCH):
        index = order[start:start + BATCH]
        out.append({"x": jnp.asarray(x[index]), "y": jnp.asarray(y[index])})
    return tuple(out)


def main() -> None:
    rng = jax.random.PRNGKey(SEED)
    numpy_rng = np.random.default_rng(SEED)

    x = numpy_rng.normal(size=(8192, 32)).astype("float32")
    y = numpy_rng.integers(0, 10, size=(8192,))
    cut = int(len(x) * 0.8)
    x_train, x_val = x[:cut], x[cut:]
    y_train, y_val = y[:cut], y[cut:]

    rng, init_rng = jax.random.split(rng)
    state = create_train_state(init_rng, learning_rate=1e-3,
                               features=x.shape[1])

    for epoch in range(EPOCHS):
        rng, dropout_rng = jax.random.split(rng)
        for batch in batches(x_train, y_train, numpy_rng, shuffle=True):
            state, metrics = train_step(state, batch, dropout_rng)

        totals = [eval_step(state, batch)
                  for batch in batches(x_val, y_val, numpy_rng, shuffle=False)]
        accuracy = float(jnp.mean(jnp.stack([m["accuracy"] for m in totals])))
        print("epoch %d val_acc %.4f" % (epoch, accuracy))

    checkpoints.save_checkpoint(ckpt_dir="checkpoints", target=state, step=EPOCHS,
                                overwrite=True)


if __name__ == "__main__":
    main()
