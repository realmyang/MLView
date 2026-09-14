"""A Keras functional backbone plus a `Model` subclass that overrides
`train_step`, and the project's `compile_model` helper.

Planted defect: the output layer carries `activation="softmax"` while
`compile_model` builds the loss with `from_logits=True`, so the loss
log-softmaxes an already-normalised vector and the gradients are wrong from
step one. Nothing raises. (MLV709.)
"""
from __future__ import annotations

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

NUM_CLASSES = 10


def build_backbone(input_shape=(96, 96, 3)) -> keras.Model:
    inputs = keras.Input(shape=input_shape, name="image")
    x = layers.Conv2D(32, 3, padding="same", use_bias=False)(inputs)
    x = layers.BatchNormalization()(x)
    x = layers.Activation("relu")(x)
    x = layers.MaxPooling2D()(x)

    x = layers.Conv2D(64, 3, padding="same", use_bias=False)(x)
    x = layers.BatchNormalization()(x)
    x = layers.Activation("relu")(x)
    x = layers.MaxPooling2D()(x)

    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.3)(x)
    outputs = layers.Dense(NUM_CLASSES, activation="softmax", name="logits")(x)
    return keras.Model(inputs, outputs, name="tiny_convnet")


class EMAClassifier(keras.Model):
    """Overrides the training step; everything else is stock Keras."""

    def __init__(self, backbone: keras.Model, ema_decay: float = 0.999,
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self.backbone = backbone
        self.ema_decay = ema_decay
        self.loss_tracker = keras.metrics.Mean(name="loss")
        self.accuracy_tracker = keras.metrics.SparseCategoricalAccuracy(
            name="accuracy")

    def call(self, inputs, training=False):
        return self.backbone(inputs, training=training)

    @property
    def metrics(self):
        return [self.loss_tracker, self.accuracy_tracker]

    def train_step(self, data):
        images, labels = data
        with tf.GradientTape() as tape:
            predictions = self(images, training=True)
            loss = self.compiled_loss(labels, predictions,
                                      regularization_losses=self.losses)
        gradients = tape.gradient(loss, self.trainable_variables)
        self.optimizer.apply_gradients(zip(gradients,
                                           self.trainable_variables))
        self.loss_tracker.update_state(loss)
        self.accuracy_tracker.update_state(labels, predictions)
        return {m.name: m.result() for m in self.metrics}

    def test_step(self, data):
        images, labels = data
        predictions = self(images, training=False)
        loss = self.compiled_loss(labels, predictions,
                                  regularization_losses=self.losses)
        self.loss_tracker.update_state(loss)
        self.accuracy_tracker.update_state(labels, predictions)
        return {m.name: m.result() for m in self.metrics}


def compile_model(model: keras.Model, lr: float = 1e-3) -> keras.Model:
    model.compile(
        optimizer=keras.optimizers.AdamW(learning_rate=lr),
        loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        metrics=["accuracy"],
    )
    return model
