"""Keras / TensorFlow / HuggingFace / Lightning / config-source knowledge."""

from __future__ import annotations

from typing import Dict

from .entries import E, Entry, expand

OTHER: Dict[str, Entry] = {}

# ------------------------------------------------------------- keras/tf ---
K, TF = "keras", "tf"
for _root in ("keras", "tensorflow.keras", "tf.keras"):
    _fw = K if _root == "keras" else TF
    OTHER.update({
        "%s.Sequential" % _root: E("model", "model", _fw, "KERAS_MODEL", ("MODEL",), "keras_model"),
        "%s.Model" % _root: E("model", "model", _fw, "KERAS_MODEL", ("MODEL",), "keras_model"),
        "%s.models.Sequential" % _root: E("model", "model", _fw, "KERAS_MODEL", ("MODEL",), "keras_model"),
        "%s.models.Model" % _root: E("model", "model", _fw, "KERAS_MODEL", ("MODEL",), "keras_model"),
        "%s.models.load_model" % _root: E("model", "model", _fw, "KERAS_LOAD", ("MODEL",), "keras_model"),
    })
    # FW-RECOG: the `keras_model` family is what makes the functional API
    # resolve. `layers.Dense(64)(x)` is a call *of a call*, and without a family
    # the value the inner call produced falls back on its MODEL tag - which
    # proposes `torch.nn.Module.__call__` and puts a phantom `torch` framework
    # on a pure-Keras file.
    OTHER.update(expand("%s.layers" % _root, ["Dense", "Conv2D", "Dropout", "Flatten",
                                              "BatchNormalization", "LSTM", "Embedding"],
                        E("layer", "model", _fw, "LAYER", ("MODEL",), "keras_model")))
    OTHER.update(expand("%s.losses" % _root, ["CategoricalCrossentropy",
                                              "SparseCategoricalCrossentropy",
                                              "BinaryCrossentropy", "MeanSquaredError"],
                        E("loss", "objective", _fw, "LOSS_CLS", ("LOSS",))))
    OTHER.update(expand("%s.optimizers" % _root, ["Adam", "SGD", "RMSprop"],
                        E("optimizer", "train", _fw, "OPTIMIZER", ("OPTIMIZER",))))
OTHER["tensorflow.random.set_seed"] = E("config", "config", TF, "SEED")
OTHER["tf.random.set_seed"] = E("config", "config", TF, "SEED")
OTHER["keras.utils.set_random_seed"] = E("config", "config", K, "SEED")
OTHER["tensorflow.keras.utils.set_random_seed"] = E("config", "config", TF, "SEED")

KERAS_METHODS: Dict[str, Entry] = {
    "keras.Model.compile": E("loss", "objective", K, "KERAS_COMPILE"),
    "keras.Model.fit": E("train_loop", "train", K, "KERAS_FIT"),
    "keras.Model.evaluate": E("eval_loop", "eval", K, "KERAS_EVAL"),
    "keras.Model.predict": E("predict", "eval", K, "PREDICT", ("PREDS",)),
    "keras.Model.save": E("checkpoint", "deliver", K, "SAVE"),
}

# ------------------------------------------------------------ HuggingFace -
HF = "hf"
OTHER.update({
    "transformers.Trainer": E("train_loop", "train", HF, "HF_TRAINER", (), "hf_trainer"),
    "transformers.Seq2SeqTrainer": E("train_loop", "train", HF, "HF_TRAINER", (), "hf_trainer"),
    "transformers.TrainingArguments": E("config", "config", HF, "HF_ARGS"),
    "transformers.Seq2SeqTrainingArguments": E("config", "config", HF, "HF_ARGS"),
    "transformers.pipeline": E("predict", "eval", HF, "HF_PIPELINE"),
    "transformers.set_seed": E("config", "config", HF, "SEED"),
    # FW-RECOG: the `hf_dataset` family is what carries `raw.map(...)` and the
    # `enc["train"].train_test_split(...)` hop - see `knowledge/hf_tbl.py`.
    "datasets.load_dataset": E("dataset", "data", HF, "DATASET", ("RAW_DATA",),
                               "hf_dataset"),
})
for _cls in ("AutoModel", "AutoModelForSequenceClassification", "AutoModelForCausalLM",
             "AutoModelForTokenClassification", "AutoModelForQuestionAnswering"):
    OTHER["transformers.%s.from_pretrained" % _cls] = E(
        "model", "model", HF, "HF_MODEL", ("MODEL",), "module")
    OTHER["transformers.%s" % _cls] = E("model", "model", HF, "HF_MODEL", ("MODEL",), "module")
for _cls in ("AutoTokenizer", "AutoFeatureExtractor", "AutoProcessor"):
    OTHER["transformers.%s.from_pretrained" % _cls] = E(
        "transform", "preprocess", HF, "HF_TOKENIZER")
    OTHER["transformers.%s" % _cls] = E("transform", "preprocess", HF, "HF_TOKENIZER")
HF_METHODS: Dict[str, Entry] = {
    "transformers.Trainer.train": E("train_loop", "train", HF, "HF_TRAIN"),
    "transformers.Trainer.evaluate": E("eval_loop", "eval", HF, "HF_EVAL"),
    "transformers.Trainer.predict": E("predict", "eval", HF, "PREDICT", ("PREDS",)),
    "transformers.Trainer.save_model": E("checkpoint", "deliver", HF, "SAVE"),
}

# -------------------------------------------------------------- Lightning -
L = "lightning"
for _root in ("pytorch_lightning", "lightning", "lightning.pytorch"):
    OTHER.update({
        "%s.LightningModule" % _root: E("model", "model", L, "LIGHTNING_MODULE", ("MODEL",), "module"),
        "%s.LightningDataModule" % _root: E("dataset", "data", L, "LIGHTNING_DM", ("RAW_DATA",)),
        "%s.Trainer" % _root: E("train_loop", "train", L, "LIGHTNING_TRAINER", (), "lightning_trainer"),
        "%s.seed_everything" % _root: E("config", "config", L, "SEED"),
        "%s.Fabric" % _root: E("train_loop", "train", L, "FABRIC"),
    })
LIGHTNING_METHODS: Dict[str, Entry] = {
    "pytorch_lightning.Trainer.fit": E("train_loop", "train", L, "LIGHTNING_FIT"),
    "pytorch_lightning.Trainer.validate": E("eval_loop", "eval", L, "LIGHTNING_VAL"),
    "pytorch_lightning.Trainer.test": E("eval_loop", "eval", L, "LIGHTNING_TEST"),
}

# ------------------------------------------------------------- accelerate -
OTHER["accelerate.Accelerator"] = E("train_loop", "train", "other", "ACCELERATOR", (), "accelerator")

#: GRAPH-R3. `accelerate` and Lightning `Fabric` both **rebind** the objects a
#: script already built - `model, optimizer, loader = accelerator.prepare(model,
#: optimizer, loader)` - and neither method surface existed, so a script written
#: the way both projects' own quickstarts write it lost its model, its optimizer
#: and its loader on one line. `WRAP_PREPARE` is the rebinding role;
#: `ir/bindings_store` gives position *i* of the result the identity of argument
#: *i*, which is what `prepare` documents itself as doing.
WRAP_METHODS: Dict[str, Entry] = {
    "accelerate.Accelerator.prepare": E("model", "train", "other", "WRAP_PREPARE",
                                        (), "accelerator"),
    "accelerate.Accelerator.prepare_model": E("model", "model", "other", "WRAP_MODEL",
                                              ("MODEL",), "module"),
    "accelerate.Accelerator.prepare_data_loader": E("dataloader", "data", "other",
                                                    "WRAP_PREPARE", ("LOADER",), "loader"),
    "accelerate.Accelerator.prepare_optimizer": E("optimizer", "train", "other",
                                                  "WRAP_PREPARE", ("OPTIMIZER",),
                                                  "optimizer"),
    "accelerate.Accelerator.backward": E("loss", "train", "other", "BACKWARD"),
    "accelerate.Accelerator.unwrap_model": E("model", "model", "other", "WRAP_PREPARE",
                                             ("MODEL",), "module"),
    "accelerate.Accelerator.clip_grad_norm_": E("optimizer", "train", "other",
                                                "CLIP_GRAD"),
    "accelerate.Accelerator.accumulate": E("train_loop", "train", "other",
                                           "ACCELERATOR", (), "accelerator", 0.6),
    "accelerate.Accelerator.save_state": E("checkpoint", "deliver", "other", "SAVE"),
    "accelerate.Accelerator.wait_for_everyone": E("train_loop", "train", "other",
                                                  "ACCELERATOR", (), "accelerator", 0.2),
}
for _root in ("pytorch_lightning", "lightning", "lightning.fabric"):
    WRAP_METHODS["%s.Fabric.setup" % _root] = E("model", "train", L, "WRAP_PREPARE",
                                                (), "fabric")
    WRAP_METHODS["%s.Fabric.setup_dataloaders" % _root] = E(
        "dataloader", "data", L, "WRAP_PREPARE", ("LOADER",), "loader")
    WRAP_METHODS["%s.Fabric.setup_module" % _root] = E("model", "model", L,
                                                       "WRAP_MODEL", ("MODEL",), "module")
    WRAP_METHODS["%s.Fabric.setup_optimizers" % _root] = E(
        "optimizer", "train", L, "WRAP_PREPARE", ("OPTIMIZER",), "optimizer")
    WRAP_METHODS["%s.Fabric.backward" % _root] = E("loss", "train", L, "BACKWARD")
OTHER["imblearn.over_sampling.SMOTE"] = E("transform", "preprocess", "imblearn", "RESAMPLE")
OTHER["imblearn.over_sampling.RandomOverSampler"] = E("transform", "preprocess", "imblearn", "RESAMPLE")
OTHER["imblearn.under_sampling.RandomUnderSampler"] = E("transform", "preprocess", "imblearn", "RESAMPLE")
OTHER["imblearn.pipeline.Pipeline"] = E("model", "model", "imblearn", "PIPELINE", ("MODEL",), "estimator")
OTHER.update(expand("albumentations", ["Compose", "HorizontalFlip", "RandomCrop", "Normalize"],
                    E("augment", "preprocess", "albumentations", "AUGMENT")))

# ----------------------------------------------------------- config sources
OTHER.update({
    "argparse.ArgumentParser": E("config", "config", "other", "ARGPARSE", (), "argparse"),
    "yaml.safe_load": E("config", "config", "other", "CONFIG_LOAD"),
    "yaml.load": E("config", "config", "other", "CONFIG_LOAD"),
    "json.load": E("config", "config", "other", "CONFIG_LOAD"),
    "json.loads": E("config", "config", "other", "CONFIG_LOAD"),
    "tomllib.load": E("config", "config", "other", "CONFIG_LOAD"),
    "toml.load": E("config", "config", "other", "CONFIG_LOAD"),
    "omegaconf.OmegaConf.load": E("config", "config", "other", "CONFIG_LOAD"),
    "os.environ.get": E("config", "config", "other", "CONFIG_ENV", weight=0.4),
    "mlflow.log_metric": E("tracker", "deliver", "other", "TRACKER"),
    "mlflow.log_param": E("tracker", "deliver", "other", "TRACKER"),
    "wandb.init": E("tracker", "deliver", "other", "TRACKER"),
    "wandb.log": E("tracker", "deliver", "other", "TRACKER"),
})
# ---------------------------------------------------- pandas / numpy frames
#: Shape-preserving DataFrame / Series / ndarray methods. `X = df.drop(columns=
#: [target])` is *the* canonical way to build a feature matrix in pandas, so the
#: RAW_DATA / FEATURES tags `pandas.read_csv` seeds have to survive the hop -
#: without this, MLV101 never sees the pandas path at all.
_FRAME_OP = E("transform", "data", "pandas", "FRAME_OP", (), "frame", 0.4)
_ARRAY_OP = E("transform", "data", "numpy", "FRAME_OP", (), "frame", 0.4)

#: Methods that return the same rows/columns of data, only reshaped or cleaned.
FRAME_OP_METHODS = (
    "drop", "copy", "dropna", "fillna", "ffill", "bfill", "astype",
    "select_dtypes", "reset_index", "set_index", "sort_values", "sort_index",
    "query", "sample", "head", "tail", "rename", "replace", "clip", "round",
    "abs", "interpolate", "assign", "filter", "reindex", "squeeze",
    "to_numpy", "to_frame", "to_list", "tolist", "values_host",
)
ARRAY_OP_METHODS = ("reshape", "astype", "copy", "ravel", "flatten", "squeeze",
                    "transpose", "clip", "round")

#: IP-03. The same argument as `_FRAME_OP`, made for numpy - and it had never
#: been made. A **module-level** constructor takes its data as argument 0
#: rather than as a receiver, so `X = np.asarray(raw.data)` dropped the
#: RAW_DATA / FEATURES tag on the floor and MLV101 went silent on a genuine
#: leak one wrapper call downstream. `np.asarray` is one of the most common
#: lines in ML preprocessing, and the recovery was one table entry wide.
#: `bindings.call_output_tags` reads argument 0 for this role.
_FRAME_MAKE = E("transform", "data", "numpy", "FRAME_MAKE", (), "frame", 0.4)
_TENSOR_MAKE = E("transform", "data", "torch", "FRAME_MAKE", (), "frame", 0.4)

#: Shape-preserving numpy constructors: same rows, same columns, new container.
ARRAY_MAKE_FUNCTIONS = ("asarray", "array", "asanyarray", "ascontiguousarray",
                        "copy", "concatenate", "vstack", "hstack", "stack",
                        "column_stack", "row_stack")
#: The torch half of the same hop: `torch.from_numpy(X)` is how a numpy feature
#: matrix reaches a `TensorDataset`.
TENSOR_MAKE_FUNCTIONS = ("from_numpy", "as_tensor", "tensor")

FRAME_METHODS: Dict[str, Entry] = {}
for _base in ("pandas.DataFrame", "pandas.Series"):
    FRAME_METHODS.update(expand(_base, FRAME_OP_METHODS, _FRAME_OP))
FRAME_METHODS.update(expand("numpy.ndarray", ARRAY_OP_METHODS, _ARRAY_OP))
OTHER.update(expand("numpy", ARRAY_MAKE_FUNCTIONS, _FRAME_MAKE))
OTHER.update(expand("torch", TENSOR_MAKE_FUNCTIONS, _TENSOR_MAKE))

ARGPARSE_METHODS: Dict[str, Entry] = {
    "argparse.ArgumentParser.parse_args": E("config", "config", "other", "CONFIG_LOAD"),
    "argparse.ArgumentParser.add_argument": E("config", "config", "other", "CONFIG_ARG"),
}
