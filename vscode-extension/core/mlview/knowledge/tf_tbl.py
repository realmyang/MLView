"""tf.data and the Keras families `other_tbl.py` never covered (FW-RECOG).

`other_tbl.py` holds the seven Keras layers, the four losses and the three
optimizers that shipped with the prototype. It holds **no tf.data at all**, so
the measured five-call chain

    tf.data.Dataset.from_tensor_slices((x, y)).map(f).shuffle(4096)
                   .batch(128).prefetch(tf.data.AUTOTUNE)

produced **one node and zero edges**: the source resolved to nothing and every
method on it answered to no FQN, so the whole input pipeline of a Keras project
was invisible. Everything here is plain data, in the shape `entries.E` defines.

Three things are deliberate and normative:

* **`take` / `skip` are not `SPLIT`.** They are the tf.data holdout idiom, and
  giving them the split role would fire MLV602 on every pipeline that windows a
  dataset. The ordering check that makes a `take`/`skip` holdout judgeable is
  ANA-9's (MLV121), and this table does not pre-empt it. Their role is
  `TFDATA_SUBSET`, which no rule keys on today.
* **`batch` / `prefetch` do not use the `LOADER` role**, even though they
  produce the LOADER tag: `LOADER` is in `core/coverage.UNTRACED_ROLES`, whose
  sweep reads argument 0 of every site - and argument 0 of `.batch(128)` is an
  integer, so every correct tf.data pipeline would emit a coverage note saying
  the analyzer could not trace it. The tag is what carries the meaning.
* The tf.data chain keeps the **`tf_dataset` receiver family** end to end, so
  `ir/resolve._canonical_for_receiver` can resolve `.map` on the value the
  previous link returned rather than on a name.
"""

from __future__ import annotations

from typing import Dict

from .entries import E, Entry, expand

__all__ = ["TFDATA", "TFDATA_METHODS", "KERAS_EXTRA", "KERAS_EXTRA_METHODS",
           "TF_PREFIX_RULES", "KERAS_ROOTS"]

TF = "tf"
K = "keras"

#: The roots a Keras symbol can be written under. `tf.` is normalised to
#: `tensorflow.` by `knowledge.lookup`, but the explicit rows are cheap and
#: keep an exact hit exact.
KERAS_ROOTS = ("keras", "tensorflow.keras", "tf.keras")


def _fw(root: str) -> str:
    return K if root == "keras" else TF


# ---------------------------------------------------------------- tf.data --
TFDATA: Dict[str, Entry] = {}

#: Sources. Every one of them hands back a `tf.data.Dataset`, so they all carry
#: RAW_DATA and the `tf_dataset` family.
_SOURCE = E("dataset", "data", TF, "DATASET", ("RAW_DATA",), "tf_dataset")
TFDATA.update(expand("tensorflow.data.Dataset", [
    "from_tensor_slices", "from_generator", "from_tensors", "list_files",
    "range", "zip", "load",
], _SOURCE))
TFDATA["tensorflow.data.TFRecordDataset"] = dict(_SOURCE)
TFDATA["tensorflow.data.TextLineDataset"] = dict(_SOURCE)
TFDATA["tensorflow.data.experimental.make_csv_dataset"] = dict(_SOURCE)

#: `keras.utils.image_dataset_from_directory` returns a `tf.data.Dataset`, so it
#: is a tf.data source that happens to live under the Keras namespace - the one
#: entry point most Keras image projects actually use.
for _root in KERAS_ROOTS:
    for _mid in ("utils", "preprocessing"):
        for _name in ("image_dataset_from_directory", "text_dataset_from_directory",
                      "audio_dataset_from_directory", "timeseries_dataset_from_array"):
            TFDATA["%s.%s.%s" % (_root, _mid, _name)] = E(
                "dataset", "data", _fw(_root), "DATASET", ("RAW_DATA",), "tf_dataset")

#: Chain methods. Each keeps the family so the next link resolves, and each
#: carries the tags the value it returns really has.
TFDATA_METHODS: Dict[str, Entry] = {
    "tensorflow.data.Dataset.map": E(
        "transform", "preprocess", TF, "TFDATA_MAP", ("RAW_DATA",), "tf_dataset"),
    "tensorflow.data.Dataset.flat_map": E(
        "transform", "preprocess", TF, "TFDATA_MAP", ("RAW_DATA",), "tf_dataset"),
    "tensorflow.data.Dataset.interleave": E(
        "transform", "preprocess", TF, "TFDATA_MAP", ("RAW_DATA",), "tf_dataset"),
    "tensorflow.data.Dataset.filter": E(
        "transform", "data", TF, "TFDATA_OP", ("RAW_DATA",), "tf_dataset", 0.7),
    "tensorflow.data.Dataset.shuffle": E(
        "augment", "preprocess", TF, "TFDATA_SHUFFLE", ("RAW_DATA",), "tf_dataset"),
    "tensorflow.data.Dataset.repeat": E(
        "transform", "data", TF, "TFDATA_OP", ("RAW_DATA",), "tf_dataset", 0.6),
    "tensorflow.data.Dataset.cache": E(
        "transform", "data", TF, "TFDATA_OP", ("RAW_DATA",), "tf_dataset", 0.5),
    "tensorflow.data.Dataset.batch": E(
        "dataloader", "data", TF, "TFDATA_BATCH", ("LOADER", "RAW_DATA"), "tf_dataset"),
    "tensorflow.data.Dataset.padded_batch": E(
        "dataloader", "data", TF, "TFDATA_BATCH", ("LOADER", "RAW_DATA"), "tf_dataset"),
    "tensorflow.data.Dataset.unbatch": E(
        "transform", "data", TF, "TFDATA_OP", ("RAW_DATA",), "tf_dataset", 0.6),
    "tensorflow.data.Dataset.prefetch": E(
        "dataloader", "data", TF, "TFDATA_PREFETCH", ("LOADER", "RAW_DATA"),
        "tf_dataset", 0.6),
    # take / skip are the tf.data holdout idiom. They are NOT given the SPLIT
    # role: see the module docstring and ROADMAP ANA-9 / MLV121.
    "tensorflow.data.Dataset.take": E(
        "transform", "data", TF, "TFDATA_SUBSET", ("RAW_DATA",), "tf_dataset"),
    "tensorflow.data.Dataset.skip": E(
        "transform", "data", TF, "TFDATA_SUBSET", ("RAW_DATA",), "tf_dataset"),
    "tensorflow.data.Dataset.shard": E(
        "transform", "data", TF, "TFDATA_SUBSET", ("RAW_DATA",), "tf_dataset"),
    "tensorflow.data.Dataset.with_options": E(
        "transform", "data", TF, "TFDATA_OP", ("RAW_DATA",), "tf_dataset", 0.4),
    "tensorflow.data.Dataset.as_numpy_iterator": E(
        "transform", "data", TF, "TFDATA_OP", ("RAW_DATA",), "tf_dataset", 0.4),
    "tensorflow.data.Dataset.cardinality": E(
        "metric", "data", TF, "TFDATA_CARD", (), "tf_dataset", 0.3),
}

# ------------------------------------------------------------ keras extras --
KERAS_EXTRA: Dict[str, Entry] = {}
KERAS_EXTRA_METHODS: Dict[str, Entry] = {}

#: The transfer-learning backbones. `keras.applications.` also gets a prefix
#: rule, so a backbone nobody listed still lands in the Model lane.
_APPLICATIONS = ("ResNet50", "ResNet101", "ResNet152", "ResNet50V2", "VGG16", "VGG19",
                 "MobileNet", "MobileNetV2", "MobileNetV3Small", "MobileNetV3Large",
                 "EfficientNetB0", "EfficientNetB1", "EfficientNetV2S", "InceptionV3",
                 "InceptionResNetV2", "DenseNet121", "DenseNet169", "Xception",
                 "ConvNeXtTiny", "NASNetMobile")
_LAYERS = ("Conv1D", "Conv3D", "SeparableConv2D", "DepthwiseConv2D", "Conv2DTranspose",
           "MaxPooling1D", "MaxPooling2D", "AveragePooling2D", "GlobalAveragePooling1D",
           "GlobalAveragePooling2D", "GlobalMaxPooling2D", "Activation", "Add",
           "Concatenate", "Multiply", "LayerNormalization", "GroupNormalization",
           "GRU", "SimpleRNN", "Bidirectional", "TimeDistributed", "Attention",
           "MultiHeadAttention", "Reshape", "Permute", "RepeatVector",
           "SpatialDropout2D", "GaussianNoise", "Lambda")
_PREPROC = ("Rescaling", "Normalization", "Resizing", "CenterCrop", "Discretization",
            "CategoryEncoding", "IntegerLookup", "StringLookup", "TextVectorization",
            "Hashing")
_AUGMENT = ("RandomFlip", "RandomRotation", "RandomZoom", "RandomContrast",
            "RandomCrop", "RandomTranslation", "RandomBrightness")
_METRICS = ("Accuracy", "BinaryAccuracy", "CategoricalAccuracy",
            "SparseCategoricalAccuracy", "AUC", "Precision", "Recall",
            "MeanAbsoluteError", "RootMeanSquaredError", "F1Score")
_LOSSES = ("Huber", "MeanAbsoluteError", "CategoricalFocalCrossentropy",
           "CosineSimilarity", "KLDivergence", "Hinge")
_OPTIMIZERS = ("AdamW", "Nadam", "Adadelta", "Adagrad", "Adamax", "Ftrl", "Lion")

for _root in KERAS_ROOTS:
    _f = _fw(_root)
    KERAS_EXTRA.update(expand("%s.applications" % _root, _APPLICATIONS,
                              E("model", "model", _f, "MODEL_FACTORY", ("MODEL",),
                                "keras_model")))
    KERAS_EXTRA.update(expand("%s.layers" % _root, _LAYERS,
                              E("layer", "model", _f, "LAYER", ("MODEL",),
                                "keras_model")))
    KERAS_EXTRA.update(expand("%s.layers" % _root, _PREPROC,
                              E("transform", "preprocess", _f, "TRANSFORM", (),
                                "keras_model")))
    KERAS_EXTRA.update(expand("%s.layers" % _root, _AUGMENT,
                              E("augment", "preprocess", _f, "AUGMENT", (),
                                "keras_model")))
    KERAS_EXTRA.update(expand("%s.metrics" % _root, _METRICS,
                              E("metric", "eval", _f, "METRIC")))
    KERAS_EXTRA.update(expand("%s.losses" % _root, _LOSSES,
                              E("loss", "objective", _f, "LOSS_CLS", ("LOSS",))))
    KERAS_EXTRA.update(expand("%s.optimizers" % _root, _OPTIMIZERS,
                              E("optimizer", "train", _f, "OPTIMIZER", ("OPTIMIZER",),
                                "keras_optimizer")))
    KERAS_EXTRA["%s.optimizers.Optimizer" % _root] = E(
        "optimizer", "train", _f, "OPTIMIZER", ("OPTIMIZER",), "keras_optimizer")
    # `Input` is written both as `keras.Input` and `keras.layers.Input`.
    _input = E("layer", "model", _f, "LAYER", ("MODEL",), "keras_model")
    KERAS_EXTRA["%s.Input" % _root] = dict(_input)
    KERAS_EXTRA["%s.layers.Input" % _root] = dict(_input)
    KERAS_EXTRA["%s.layers.InputLayer" % _root] = dict(_input)
    # callbacks: the two that change the run get their own semantics, the rest
    # are recorded as training-control configuration.
    KERAS_EXTRA["%s.callbacks.ModelCheckpoint" % _root] = E(
        "checkpoint", "deliver", _f, "SAVE")
    KERAS_EXTRA["%s.callbacks.ReduceLROnPlateau" % _root] = E(
        "scheduler", "train", _f, "SCHEDULER")
    KERAS_EXTRA["%s.callbacks.LearningRateScheduler" % _root] = E(
        "scheduler", "train", _f, "SCHEDULER")
    KERAS_EXTRA.update(expand("%s.callbacks" % _root,
                              ["EarlyStopping", "TerminateOnNaN", "BackupAndRestore",
                               "LambdaCallback", "Callback"],
                              E("config", "train", _f, "CALLBACK", (), None, 0.7)))
    KERAS_EXTRA.update(expand("%s.callbacks" % _root, ["TensorBoard", "CSVLogger"],
                              E("tracker", "deliver", _f, "TRACKER")))
    KERAS_EXTRA["%s.utils.to_categorical" % _root] = E(
        "transform", "preprocess", _f, "TRANSFORM")
    KERAS_EXTRA["%s.Sequential" % _root] = E(
        "model", "model", _f, "KERAS_MODEL", ("MODEL",), "keras_model")

#: INFRA-R2-05. The TF2 custom training loop - `with tf.GradientTape() as tape`,
#: `tape.gradient(...)`, `optimizer.apply_gradients(...)` - is one of exactly
#: two ways to train in TensorFlow, and carried no rows at all, so every one of
#: them was drawn in the Evaluate lane with the answer card saying "Evaluation
#: runs in ..." at 0.95 about a file that evaluates nothing.
#:
#: The two roles are deliberately **not** `BACKWARD` / `OPT_STEP`: MLV201-205
#: are torch rules that read those roles and reason about `zero_grad()`, which
#: TensorFlow does not have. `core/views` names these two explicitly instead,
#: so the lane is right without a torch rule ever firing on a TF loop in a
#: mixed workspace.
KERAS_EXTRA["tensorflow.GradientTape"] = E(
    "train_loop", "train", TF, "GRAD_TAPE", (), "grad_tape")

KERAS_EXTRA_METHODS.update({
    "tensorflow.GradientTape.gradient": E(
        "loss", "train", TF, "TAPE_GRADIENT", ("GRADS",), "tensor"),
    "tensorflow.GradientTape.watch": E("loss", "train", TF, "TAPE_WATCH"),
    "keras.optimizers.Optimizer.apply_gradients": E(
        "optimizer", "train", K, "TF_OPT_STEP"),
    "keras.optimizers.Optimizer.minimize": E(
        "optimizer", "train", K, "TF_OPT_STEP"),
    "keras.Model.train_on_batch": E("train_loop", "train", K, "KERAS_FIT"),
    "keras.Model.test_on_batch": E("eval_loop", "eval", K, "KERAS_EVAL"),
    "keras.Model.predict_on_batch": E("predict", "eval", K, "PREDICT", ("PREDS",)),
    "keras.Model.evaluate": E("eval_loop", "eval", K, "KERAS_EVAL"),
    "keras.Model.save_weights": E("checkpoint", "deliver", K, "SAVE"),
    "keras.Model.load_weights": E("checkpoint", "deliver", K, "LOAD"),
    "keras.Model.summary": E("model", "model", K, "MODEL_SUMMARY"),
    "keras.Model.__call__": E("model", "model", K, "FORWARD", ("LOGITS",)),
    "keras.Model.add": E("model", "model", K, "LAYER", ("MODEL",)),
    "keras.Model.trainable_variables": E("model", "train", K, "PARAMETERS"),
})

#: Prefix fallbacks contributed to `knowledge._PREFIX_RULES`, longest first.
TF_PREFIX_RULES = tuple(
    [("tensorflow.data.",
      E("dataset", "data", TF, "DATASET", ("RAW_DATA",), "tf_dataset", 0.6))]
    + [("%s.applications." % root,
        E("model", "model", _fw(root), "MODEL_FACTORY", ("MODEL",), "keras_model", 0.8))
       for root in KERAS_ROOTS]
    + [("%s.callbacks." % root, E("config", "train", _fw(root), "CALLBACK", (), None, 0.5))
       for root in KERAS_ROOTS]
    + [("%s.metrics." % root, E("metric", "eval", _fw(root), "METRIC", (), None, 0.8))
       for root in KERAS_ROOTS]
)
