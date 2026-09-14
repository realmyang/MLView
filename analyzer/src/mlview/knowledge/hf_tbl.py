"""HuggingFace `datasets` and the collators (FW-RECOG).

`other_tbl.py` knows `transformers` - the trainer, the auto-classes, the
tokenizers - and exactly **one** row of `datasets`: `load_dataset`. The
consequence measured in ROADMAP b.1 is that

    enc = raw.map(tokenize, batched=True)
    split = enc["train"].train_test_split(test_size=0.1)

produced **zero nodes and no SPLIT at all**, which makes MLV101, MLV106 and
MLV602 structurally impossible on the HuggingFace path - not silent, not
low-confidence: impossible, because the graph has nothing for them to key on.

The whole file is data. Two shapes matter:

* every `datasets` row carries the **`hf_dataset` receiver family**, so a
  method call resolves against the value the previous call returned. That is
  what carries the chain across `raw.map(...)` and across the `enc["train"]`
  subscript, which `ir/resolve._chained_receiver` already models;
* `Dataset.train_test_split` carries the real **`SPLIT`** role, and
  `rules/r_repro.py` lists it in `_ALWAYS_RANDOM` under the `seed` keyword -
  the HuggingFace spelling of `random_state`. It shuffles by default, so an
  unseeded call really is a different split on every run.

`DatasetDict` methods are keyed on `datasets.Dataset` too: the two classes
share this surface, and one canonical base keeps the receiver resolver from
having to guess which one it is holding.
"""

from __future__ import annotations

from typing import Dict

from .entries import E, Entry, expand

__all__ = ["HF_DATA", "HF_DATA_METHODS"]

HF = "hf"

#: Sources: everything that hands back a `Dataset` / `DatasetDict`.
HF_DATA: Dict[str, Entry] = {
    "datasets.load_from_disk": E("dataset", "data", HF, "DATASET", ("RAW_DATA",),
                                 "hf_dataset"),
    "datasets.Dataset.from_pandas": E("dataset", "data", HF, "DATASET", ("RAW_DATA",),
                                      "hf_dataset"),
    "datasets.Dataset.from_dict": E("dataset", "data", HF, "DATASET", ("RAW_DATA",),
                                    "hf_dataset"),
    "datasets.Dataset.from_list": E("dataset", "data", HF, "DATASET", ("RAW_DATA",),
                                    "hf_dataset"),
    "datasets.Dataset.from_generator": E("dataset", "data", HF, "DATASET", ("RAW_DATA",),
                                         "hf_dataset"),
    "datasets.concatenate_datasets": E("transform", "data", HF, "HF_DATA_OP",
                                       ("RAW_DATA",), "hf_dataset"),
    "datasets.interleave_datasets": E("transform", "data", HF, "HF_DATA_OP",
                                      ("RAW_DATA",), "hf_dataset"),
}

#: NLP2-08. `transformers.optimization.get_*_schedule_with_warmup` is the LR
#: schedule of essentially every transformer fine-tune, and it had **no row
#: anywhere**: `r_mechanics._BATCH_CADENCE` and `r_framework` both named
#: `get_linear_schedule_with_warmup`, but `scheduler.step()` never acquired the
#: `SCHED_STEP` role, so the tuple entry was unreachable code and MLV207 could
#: not fire on the commonest LR mistake in transformer fine-tuning (a warmup
#: built for `len(loader) * epochs` steps and stepped once per epoch, so warmup
#: never finishes). The scheduler and its `.step()` also drew no node at all.
#:
#: They return a `torch.optim.lr_scheduler.LambdaLR`, so the `scheduler` family
#: is the right one and the per-step cadence is a property of the construction,
#: not of the class - which is exactly why `LambdaLR` itself carries no cadence.
_HF_SCHEDULES = (
    "get_linear_schedule_with_warmup",
    "get_cosine_schedule_with_warmup",
    "get_cosine_with_hard_restarts_schedule_with_warmup",
    "get_polynomial_decay_schedule_with_warmup",
    "get_constant_schedule",
    "get_constant_schedule_with_warmup",
    "get_inverse_sqrt_schedule",
    "get_wsd_schedule",
    "get_scheduler",
)
for _root in ("transformers", "transformers.optimization"):
    HF_DATA.update(expand(_root, _HF_SCHEDULES,
                          E("scheduler", "train", HF, "SCHEDULER", (), "scheduler")))
HF_DATA["transformers.AdamW"] = E("optimizer", "train", HF, "OPTIMIZER",
                                  ("OPTIMIZER",), "optimizer")
HF_DATA["transformers.optimization.AdamW"] = E("optimizer", "train", HF, "OPTIMIZER",
                                               ("OPTIMIZER",), "optimizer")
HF_DATA["transformers.Adafactor"] = E("optimizer", "train", HF, "OPTIMIZER",
                                      ("OPTIMIZER",), "optimizer")

#: Collators - the last preprocessing step before a batch reaches the model.
HF_DATA.update(expand("transformers", [
    "DataCollatorWithPadding", "DataCollatorForLanguageModeling",
    "DataCollatorForSeq2Seq", "DataCollatorForTokenClassification",
    "DataCollatorForWholeWordMask", "DefaultDataCollator",
], E("transform", "preprocess", HF, "COLLATOR")))
HF_DATA["transformers.default_data_collator"] = E(
    "transform", "preprocess", HF, "COLLATOR")
HF_DATA["transformers.AutoConfig.from_pretrained"] = E(
    "config", "config", HF, "CONFIG_LOAD")

#: Methods on a `Dataset` / `DatasetDict`.
HF_DATA_METHODS: Dict[str, Entry] = {
    "datasets.Dataset.map": E("transform", "preprocess", HF, "HF_MAP", ("RAW_DATA",),
                              "hf_dataset"),
    "datasets.Dataset.filter": E("transform", "data", HF, "HF_DATA_OP", ("RAW_DATA",),
                                 "hf_dataset", 0.7),
    # The one row that unlocks the leakage and reproducibility families on the
    # HuggingFace path. `seed=` is its `random_state=`.
    "datasets.Dataset.train_test_split": E("split", "data", HF, "SPLIT", (),
                                           "hf_dataset"),
    "datasets.Dataset.select": E("transform", "data", HF, "HF_DATA_OP", ("RAW_DATA",),
                                 "hf_dataset", 0.7),
    "datasets.Dataset.shuffle": E("augment", "preprocess", HF, "HF_SHUFFLE",
                                  ("RAW_DATA",), "hf_dataset"),
    "datasets.Dataset.shard": E("transform", "data", HF, "HF_DATA_OP", ("RAW_DATA",),
                                "hf_dataset", 0.6),
    "datasets.Dataset.sort": E("transform", "data", HF, "HF_DATA_OP", ("RAW_DATA",),
                               "hf_dataset", 0.5),
    "datasets.Dataset.rename_column": E("transform", "data", HF, "HF_DATA_OP",
                                        ("RAW_DATA",), "hf_dataset", 0.4),
    "datasets.Dataset.remove_columns": E("transform", "data", HF, "HF_DATA_OP",
                                         ("RAW_DATA",), "hf_dataset", 0.4),
    "datasets.Dataset.cast_column": E("transform", "data", HF, "HF_DATA_OP",
                                      ("RAW_DATA",), "hf_dataset", 0.4),
    "datasets.Dataset.class_encode_column": E("transform", "preprocess", HF,
                                              "HF_DATA_OP", ("RAW_DATA", "TARGET"),
                                              "hf_dataset"),
    "datasets.Dataset.with_format": E("transform", "data", HF, "HF_DATA_OP",
                                      ("RAW_DATA",), "hf_dataset", 0.3),
    "datasets.Dataset.set_format": E("transform", "data", HF, "HF_DATA_OP",
                                     ("RAW_DATA",), "hf_dataset", 0.3),
    "datasets.Dataset.save_to_disk": E("checkpoint", "deliver", HF, "SAVE"),
    "datasets.Dataset.to_pandas": E("transform", "data", HF, "HF_DATA_OP",
                                    ("RAW_DATA",), "frame", 0.5),
}
