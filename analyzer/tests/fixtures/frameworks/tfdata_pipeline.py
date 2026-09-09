"""FW-RECOG positive fixture: a tf.data input pipeline.

The audit's probe: this exact five-call shape produced **one node and zero
edges**, because `knowledge/other_tbl.py` held no tf.data entries at all. Every
link is now a node, and the chain is connected because each method resolves
against the value the previous one returned.

`take` / `skip` are here on purpose and are deliberately **not** split nodes:
ANA-9's MLV121 is the rule that judges a `take`/`skip` holdout, and giving them
the SPLIT role before it exists would fire MLV602 on every tf.data pipeline.
"""
from __future__ import annotations

import tensorflow as tf

AUTOTUNE = tf.data.AUTOTUNE
BATCH = 64


def normalize(image, label):
    return image / 255.0, label


def build_dataset(paths, labels):
    return (tf.data.Dataset.from_tensor_slices((paths, labels))
            .map(normalize, num_parallel_calls=AUTOTUNE)
            .shuffle(1024, reshuffle_each_iteration=False)
            .cache()
            .repeat()
            .batch(BATCH)
            .prefetch(AUTOTUNE))


def build_holdout(paths, labels, val_batches: int = 20):
    full = (tf.data.Dataset.from_tensor_slices((paths, labels))
            .batch(BATCH))
    return full.skip(val_batches), full.take(val_batches)


def build_from_directory(root: str):
    return (tf.keras.utils.image_dataset_from_directory(root, batch_size=BATCH)
            .prefetch(AUTOTUNE))
