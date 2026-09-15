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
#: PUB-10. The five-class enumeration this used to be declared `model` and
#: `preprocess` ABSENT on `transformers/examples/pytorch/image-classification/
#: run_image_classification.py` - a canonical HuggingFace fine-tune - with no
#: `unverified` qualifier and an empty `diagnostics` list, because
#: `AutoModelForImageClassification` and `AutoImageProcessor` (the current
#: spelling; `AutoFeatureExtractor` is the deprecated one) resolved through the
#: import table and then matched no row. Enumerating heads is a losing game -
#: transformers adds them faster than a table can - so the *task* suffixes are
#: listed once and every `AutoModelFor<Task>` is generated from them.
HF_MODEL_TASKS = (
    "SequenceClassification", "TokenClassification", "QuestionAnswering",
    "CausalLM", "MaskedLM", "Seq2SeqLM", "PreTraining", "MultipleChoice",
    "NextSentencePrediction", "ImageClassification", "ImageSegmentation",
    "SemanticSegmentation", "InstanceSegmentation", "UniversalSegmentation",
    "ObjectDetection", "ZeroShotObjectDetection", "ZeroShotImageClassification",
    "DepthEstimation", "VideoClassification", "MaskedImageModeling",
    "AudioClassification", "AudioFrameClassification", "AudioXVector",
    "CTC", "SpeechSeq2Seq", "TextToWaveform", "TextToSpectrogram",
    "Vision2Seq", "VisualQuestionAnswering", "DocumentQuestionAnswering",
    "TableQuestionAnswering", "ImageTextToText", "TextEncoding",
)
HF_MODEL_CLASSES = ("AutoModel", "AutoBackbone", "AutoModelWithLMHead") + tuple(
    "AutoModelFor%s" % task for task in HF_MODEL_TASKS)
#: PUB-10. `AutoImageProcessor` / `AutoVideoProcessor` are the current names.
HF_PROCESSOR_CLASSES = ("AutoTokenizer", "AutoFeatureExtractor", "AutoProcessor",
                        "AutoImageProcessor", "AutoVideoProcessor",
                        "AutoConfig")
for _cls in HF_MODEL_CLASSES:
    OTHER["transformers.%s.from_pretrained" % _cls] = E(
        "model", "model", HF, "HF_MODEL", ("MODEL",), "module")
    OTHER["transformers.%s.from_config" % _cls] = E(
        "model", "model", HF, "HF_MODEL", ("MODEL",), "module")
    OTHER["transformers.%s" % _cls] = E("model", "model", HF, "HF_MODEL", ("MODEL",), "module")
for _cls in HF_PROCESSOR_CLASSES:
    _row = E("config", "config", HF, "HF_CONFIG") if _cls == "AutoConfig" \
        else E("transform", "preprocess", HF, "HF_TOKENIZER")
    OTHER["transformers.%s.from_pretrained" % _cls] = dict(_row)
    OTHER["transformers.%s" % _cls] = dict(_row)
HF_METHODS: Dict[str, Entry] = {
    "transformers.Trainer.train": E("train_loop", "train", HF, "HF_TRAIN"),
    "transformers.Trainer.evaluate": E("eval_loop", "eval", HF, "HF_EVAL"),
    "transformers.Trainer.predict": E("predict", "eval", HF, "PREDICT", ("PREDS",)),
    "transformers.Trainer.save_model": E("checkpoint", "deliver", HF, "SAVE"),
    # INFRA-04: `transformers.Trainer.save_model` was the ONLY SAVE role in the
    # tree, so the Save / Deploy lane was declared absent on every project that
    # checkpoints the framework-native way. `unwrapped.save_pretrained(...)` is
    # what `accelerate`'s own example writes.
    "transformers.PreTrainedModel.save_pretrained":
        E("checkpoint", "deliver", HF, "SAVE"),
    "transformers.PreTrainedTokenizerBase.save_pretrained":
        E("checkpoint", "deliver", HF, "SAVE"),
    "transformers.PreTrainedModel.push_to_hub": E("checkpoint", "deliver", HF, "SAVE"),
}
#: INFRA-04. `save_pretrained` is reached off an `hf_model` binding under many
#: spellings (`model.save_pretrained`, `unwrapped.save_pretrained`,
#: `tokenizer.save_pretrained`), so the method is also registered on the two
#: families those bindings carry.
for _base in ("transformers.AutoModel", "transformers.AutoTokenizer"):
    HF_METHODS["%s.save_pretrained" % _base] = E("checkpoint", "deliver", HF, "SAVE")

# -------------------------------------------------------------- Lightning -
L = "lightning"
for _root in ("pytorch_lightning", "lightning", "lightning.pytorch"):
    OTHER.update({
        "%s.LightningModule" % _root: E("model", "model", L, "LIGHTNING_MODULE", ("MODEL",), "module"),
        "%s.LightningDataModule" % _root: E("dataset", "data", L, "LIGHTNING_DM", ("RAW_DATA",)),
        "%s.Trainer" % _root: E("train_loop", "train", L, "LIGHTNING_TRAINER", (), "lightning_trainer"),
        "%s.seed_everything" % _root: E("config", "config", L, "SEED"),
    })
LIGHTNING_METHODS: Dict[str, Entry] = {
    "pytorch_lightning.Trainer.fit": E("train_loop", "train", L, "LIGHTNING_FIT"),
    "pytorch_lightning.Trainer.validate": E("eval_loop", "eval", L, "LIGHTNING_VAL"),
    "pytorch_lightning.Trainer.test": E("eval_loop", "eval", L, "LIGHTNING_TEST"),
}
# INFRA-04: `ModelCheckpoint(monitor="val/loss", save_top_k=3)` is how a
# Lightning project checkpoints, and the deliver lane read as absent without it.
for _root in ("pytorch_lightning", "lightning", "lightning.pytorch"):
    OTHER["%s.callbacks.ModelCheckpoint" % _root] = E(
        "checkpoint", "deliver", L, "SAVE")
    OTHER["%s.callbacks.EarlyStopping" % _root] = E(
        "config", "train", L, "CALLBACK")

# ------------------------------------------------ torch_geometric (DGRG2-13)
#: PyG is the dominant graph-learning library and carried **zero** rows, so the
#: data lane was empty for every PyTorch Geometric project and MLV110 / MLV111 /
#: MLV112 were structurally inapplicable to it: three planted loader defects in
#: `adv_gnn_sage_bad` (a training loader with `shuffle=False`, a validation
#: loader with `shuffle=True`, `num_workers=4` with no guard) produced no
#: finding at all. The loaders take `shuffle=` and `num_workers=` with torch's
#: own semantics because they **are** `torch.utils.data.DataLoader` subclasses,
#: which is why they are aliased rather than re-described (see
#: `knowledge.CANONICAL_ALIASES`).
PYG = "torch"
OTHER.update(expand("torch_geometric.datasets", [
    "Planetoid", "TUDataset", "QM9", "Reddit", "Reddit2", "PPI", "Flickr",
    "Amazon", "Coauthor", "OGB_MAG", "MovieLens", "ZINC", "GNNBenchmarkDataset",
    "WikiCS", "CitationFull", "Entities", "FakeDataset", "FakeHeteroDataset",
], E("dataset", "data", PYG, "DATASET", ("RAW_DATA",), "dataset")))
OTHER.update(expand("torch_geometric.transforms", [
    "RandomLinkSplit", "RandomNodeSplit",
], E("split", "data", PYG, "SPLIT")))
OTHER.update(expand("torch_geometric.transforms", [
    "NormalizeFeatures", "ToUndirected", "AddSelfLoops", "ToDevice", "Compose",
], E("transform", "preprocess", PYG, "TRANSFORM")))
OTHER["torch_geometric.data.Data"] = E("dataset", "data", PYG, "DATASET",
                                       ("RAW_DATA",), "dataset")
OTHER["torch_geometric.data.HeteroData"] = E("dataset", "data", PYG, "DATASET",
                                             ("RAW_DATA",), "dataset")
OTHER["torch_geometric.utils.negative_sampling"] = E(
    "transform", "preprocess", PYG, "TRANSFORM")

# ------------------------------------------------------------- accelerate -
OTHER["accelerate.Accelerator"] = E("train_loop", "train", "other", "ACCELERATOR", (), "accelerator")
#: The accelerate seed helper seeds `random`, `numpy`, `torch` and `torch.cuda`
#: - it is exactly the `seed_everything` MLV601 says is absent, and its absence
#: from this table was a live MLV601 false positive on `infra_accelerate`.
OTHER["accelerate.utils.set_seed"] = E("config", "config", HF, "SEED")
OTHER["accelerate.set_seed"] = E("config", "config", HF, "SEED")
#: ROB-16. `accelerator.backward(loss)` is not optional in an `accelerate`
#: script - it is the only way the scaled / distributed backward happens - and
#: with no row for it the whole MLV2xx family was blind to the training step it
#: is the centre of. `prepare()` deliberately has **no** row: it is the wrapper
#: idiom `x = f(..., x, ...)`, and `ir/bindings._self_wrapped` keeps the types
#: the names already carried rather than the analyzer inventing an arity rule.
ACCELERATE_METHODS: Dict[str, Entry] = {
    "accelerate.Accelerator.backward": E("loss", "train", HF, "BACKWARD"),
    "accelerate.Accelerator.clip_grad_norm_": E("optimizer", "train", HF, "CLIP_GRAD"),
    "accelerate.Accelerator.clip_grad_value_": E("optimizer", "train", HF, "CLIP_GRAD"),
    "accelerate.Accelerator.unwrap_model": E("model", "model", HF, "WRAP_MODEL",
                                             ("MODEL",), "module"),
    "accelerate.Accelerator.save": E("checkpoint", "deliver", HF, "SAVE"),
    "accelerate.Accelerator.save_state": E("checkpoint", "deliver", HF, "SAVE"),
    "accelerate.Accelerator.save_model": E("checkpoint", "deliver", HF, "SAVE"),
}
#: INFRA-R2-04. Lightning Fabric's `fabric.backward(loss)`, same argument.
#: `fabric.setup(...)` / `setup_module` / `setup_dataloaders` are the wrapper
#: idiom again and are deliberately left unlisted.
#: INFRA-R2-04. Every spelling Fabric is imported under. `from lightning.fabric
#: import Fabric` is the one the docs use and the one `infra_fabric` writes, and
#: it was not in the table, so `fabric.seed_everything(args.seed)` on line 120
#: resolved to nothing and MLV601 reported "No random seed set anywhere" about a
#: program that seeds four generators on its first line.
_FABRIC_ROOTS = ("pytorch_lightning", "lightning", "lightning.pytorch",
                 "lightning.fabric", "pytorch_lightning.fabric",
                 "lightning.pytorch.fabric")
for _root in _FABRIC_ROOTS:
    OTHER["%s.Fabric" % _root] = E("train_loop", "train", L, "FABRIC", (), "fabric")
for _root in _FABRIC_ROOTS:
    ACCELERATE_METHODS["%s.Fabric.backward" % _root] = E("loss", "train", L, "BACKWARD")
    # `fabric.seed_everything(seed)` is `pytorch_lightning.seed_everything` -
    # it seeds random, numpy, torch and torch.cuda - and without a row for it
    # MLV601 reported "No random seed set anywhere" on two Fabric programs that
    # seed on their first line.
    ACCELERATE_METHODS["%s.Fabric.seed_everything" % _root] = E(
        "config", "config", L, "SEED")
    ACCELERATE_METHODS["%s.Fabric.clip_gradients" % _root] = E(
        "optimizer", "train", L, "CLIP_GRAD")
    ACCELERATE_METHODS["%s.Fabric.save" % _root] = E("checkpoint", "deliver", L, "SAVE")
    ACCELERATE_METHODS["%s.Fabric.load" % _root] = E("checkpoint", "deliver", L, "LOAD")
    ACCELERATE_METHODS["%s.Fabric.log" % _root] = E("tracker", "deliver", L, "TRACKER")

# ------------------------------------------ deepspeed / ignite / fastai ----
# INFRA-03 / INFRA-04: these three own a training loop (they are already in
# `WRAPPER_FQNS`) and contributed no knowledge rows at all, so a complete
# fastai script rendered as four nodes with model, objective, train, eval and
# deliver all declared ABSENT - and `workspace.frameworks` did not even name
# the library. A declared-absent stage is a positive claim about the code.
OTHER.update({
    "deepspeed.initialize": E("train_loop", "train", "other", "ACCELERATOR", (),
                              "deepspeed_engine"),
    "ignite.engine.create_supervised_trainer":
        E("train_loop", "train", "other", "IGNITE_TRAIN"),
    "ignite.engine.create_supervised_evaluator":
        E("eval_loop", "eval", "other", "IGNITE_EVAL", (), "ignite_evaluator"),
    "ignite.engine.Engine": E("train_loop", "train", "other", "IGNITE_TRAIN"),
    "ignite.handlers.Checkpoint": E("checkpoint", "deliver", "other", "SAVE"),
    "ignite.handlers.DiskSaver": E("checkpoint", "deliver", "other", "SAVE"),
    "ignite.metrics.Accuracy": E("metric", "eval", "other", "METRIC"),
    "ignite.metrics.Loss": E("metric", "eval", "other", "METRIC"),
    "fastai.vision.learner.vision_learner": E("model", "model", "other", "FASTAI_LEARNER",
                                              ("MODEL",), "fastai_learner"),
    "fastai.vision.all.vision_learner": E("model", "model", "other", "FASTAI_LEARNER",
                                          ("MODEL",), "fastai_learner"),
    "fastai.learner.Learner": E("model", "model", "other", "FASTAI_LEARNER",
                                ("MODEL",), "fastai_learner"),
    "fastai.tabular.all.tabular_learner": E("model", "model", "other", "FASTAI_LEARNER",
                                            ("MODEL",), "fastai_learner"),
    "fastai.text.all.text_classifier_learner": E("model", "model", "other",
                                                 "FASTAI_LEARNER", ("MODEL",),
                                                 "fastai_learner"),
    "fastai.vision.data.ImageDataLoaders.from_name_func":
        E("dataloader", "data", "other", "LOADER", ("LOADER", "RAW_DATA")),
    "fastai.vision.all.ImageDataLoaders.from_name_func":
        E("dataloader", "data", "other", "LOADER", ("LOADER", "RAW_DATA")),
})
#: Methods of the wrapper objects the rows above mint.
WRAPPER_METHODS: Dict[str, Entry] = {
    "deepspeed.DeepSpeedEngine.save_checkpoint": E("checkpoint", "deliver", "other", "SAVE"),
    "deepspeed.initialize.save_checkpoint": E("checkpoint", "deliver", "other", "SAVE"),
    "ignite.engine.Engine.run": E("train_loop", "train", "other", "IGNITE_RUN"),
    "ignite.engine.create_supervised_evaluator.run":
        E("eval_loop", "eval", "other", "IGNITE_EVAL"),
    "fastai.learner.Learner.fit": E("train_loop", "train", "other", "FASTAI_FIT"),
    "fastai.learner.Learner.fit_one_cycle": E("train_loop", "train", "other", "FASTAI_FIT"),
    "fastai.learner.Learner.fine_tune": E("train_loop", "train", "other", "FASTAI_FIT"),
    "fastai.learner.Learner.validate": E("eval_loop", "eval", "other", "FASTAI_EVAL"),
    "fastai.learner.Learner.get_preds": E("predict", "eval", "other", "PREDICT", ("PREDS",)),
    "fastai.learner.Learner.export": E("checkpoint", "deliver", "other", "SAVE"),
    "fastai.learner.Learner.save": E("checkpoint", "deliver", "other", "SAVE"),
}
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
    # TAB-12: the singulars were here and the plurals were not, so a project
    # that builds a dict of metrics drew a run that logs parameters and never
    # logs a result or a model.
    "mlflow.log_metric": E("tracker", "deliver", "other", "TRACKER"),
    "mlflow.log_metrics": E("tracker", "deliver", "other", "TRACKER"),
    "mlflow.log_param": E("tracker", "deliver", "other", "TRACKER"),
    "mlflow.log_params": E("tracker", "deliver", "other", "TRACKER"),
    "mlflow.set_tag": E("tracker", "deliver", "other", "TRACKER"),
    "mlflow.set_tags": E("tracker", "deliver", "other", "TRACKER"),
    "mlflow.start_run": E("tracker", "deliver", "other", "TRACKER"),
    "mlflow.set_experiment": E("tracker", "deliver", "other", "TRACKER"),
    "mlflow.log_artifact": E("checkpoint", "deliver", "other", "SAVE"),
    "wandb.init": E("tracker", "deliver", "other", "TRACKER"),
    "wandb.log": E("tracker", "deliver", "other", "TRACKER"),
})
#: TAB-12. `mlflow.<flavour>.log_model` / `save_model` write the model artefact,
#: so they are SAVE rather than TRACKER: the deliver lane should name the
#: artefact, not just the run.
for _flavour in ("sklearn", "pytorch", "keras", "tensorflow", "xgboost", "lightgbm",
                 "transformers", "pyfunc", "onnx", "statsmodels", "prophet"):
    OTHER["mlflow.%s.log_model" % _flavour] = E("checkpoint", "deliver", "other", "SAVE")
    OTHER["mlflow.%s.save_model" % _flavour] = E("checkpoint", "deliver", "other", "SAVE")
    OTHER["mlflow.%s.load_model" % _flavour] = E("checkpoint", "deliver", "other", "LOAD")
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
#: VIS2-15. `tolist` / `item` / `mean` / `sum` were registered for pandas ONLY,
#: so `np.array(record["boxes"]).tolist()` resolved to `pandas.Series.tolist`
#: and put **pandas** into `workspace.frameworks` - a statement the README, the
#: VS Code status-bar tooltip and every chat digest present as a fact about the
#: project - on a pure numpy + torch vision workspace with no `import pandas`
#: anywhere. `.tolist()` is ubiquitous in data pipelines.
ARRAY_OP_METHODS = ("reshape", "astype", "copy", "ravel", "flatten", "squeeze",
                    "transpose", "clip", "round", "tolist", "to_list", "item",
                    "view", "swapaxes", "repeat", "take", "cumsum")

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
