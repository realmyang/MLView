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
