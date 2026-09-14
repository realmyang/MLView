"""The transfer-learning model: a frozen EfficientNet trunk plus a linear head.

The head deliberately carries **no activation**. The loss in `train.py` is built
with `from_logits=True`, which is the matching half of that choice: the softmax
is applied once, inside the loss, where it is numerically stable. Putting
`activation="softmax"` here as well would apply it twice.

`build_model` and `unfreeze_top` are plain factories - they build and return,
they never compile and they never fit. Compilation is `train.compile_model`'s
job so that the fine-tuning phase can recompile with a lower learning rate
without rebuilding the graph.
"""

from __future__ import annotations

from tensorflow import keras
from tensorflow.keras import layers

from pipeline import IMAGE_SIZE

DROPOUT = 0.2
LABEL_SMOOTHING = 0.0


def preprocessing_block() -> keras.Sequential:
    """Rescaling only - the random ops live in `pipeline.augment`."""
    return keras.Sequential(
        [layers.Rescaling(scale=255.0)],
        name="to_backbone_range",
    )


def backbone(trainable: bool = False) -> keras.Model:
    """ImageNet-pretrained EfficientNetB3 with its classifier head removed."""
    trunk = keras.applications.EfficientNetB3(
        include_top=False,
        weights="imagenet",
        input_shape=IMAGE_SIZE + (3,),
        pooling=None,
    )
    trunk.trainable = trainable
    return trunk


def build_model(num_classes: int, trainable_trunk: bool = False) -> keras.Model:
    """Functional model: inputs -> rescale -> trunk -> pool -> dropout -> logits."""
    inputs = keras.Input(shape=IMAGE_SIZE + (3,), name="image")
    x = preprocessing_block()(inputs)
    trunk = backbone(trainable=trainable_trunk)
    # `training=False` keeps the trunk's BatchNorm layers in inference mode while
    # they are frozen; unfreezing them later without this is the classic way to
    # destroy a pretrained backbone in the first few steps.
    x = trunk(x, training=False)
    x = layers.GlobalAveragePooling2D(name="pool")(x)
    x = layers.Dropout(DROPOUT, name="head_dropout")(x)
    outputs = layers.Dense(num_classes, name="logits")(x)
    return keras.Model(inputs, outputs, name="flowers_effnet")


def unfreeze_top(model, layers_to_unfreeze: int = 40):
    """Make the last N trunk layers trainable for the fine-tuning phase.

    BatchNorm layers stay frozen: their running statistics were estimated on
    ImageNet over millions of images and a few hundred fine-tuning batches will
    only make them worse.
    """
    trunk = model.get_layer("efficientnetb3")
    trunk.trainable = True
    for layer in trunk.layers[:-layers_to_unfreeze]:
        layer.trainable = False
    for layer in trunk.layers:
        if isinstance(layer, layers.BatchNormalization):
            layer.trainable = False
    return model


def head_layer_names(model) -> list:
    """The names a served model is allowed to differ in between the two phases."""
    return [layer.name for layer in model.layers
            if layer.name in ("pool", "head_dropout", "logits")]
