"""Build a masked-language-modelling corpus out of raw text shards.

Defective twin of `nlp_mlm_pretrain/corpus.py`: the shards are packed into
fixed-size blocks *before* the held-out slice is cut, so the tail of a training
document and the head of a validation block are the same sentences.
"""

from datasets import load_dataset
from transformers import AutoTokenizer

BLOCK_SIZE = 256
VALIDATION_FRACTION = 0.02


def load_tokenizer(checkpoint):
    return AutoTokenizer.from_pretrained(checkpoint, use_fast=True)


def read_shards(data_files):
    raw = load_dataset("text", data_files=data_files)
    return raw["train"]


def encode(tokenizer, documents, num_proc=4):
    def _encode(batch):
        return tokenizer(batch["text"], return_special_tokens_mask=True)

    return documents.map(
        _encode,
        batched=True,
        num_proc=num_proc,
        remove_columns=["text"],
        desc="tokenizing",
    )


def group_texts(examples, block_size=BLOCK_SIZE):
    joined = {key: sum(examples[key], []) for key in examples}
    total = (len(joined["input_ids"]) // block_size) * block_size
    return {
        key: [values[i:i + block_size] for i in range(0, total, block_size)]
        for key, values in joined.items()
    }


def build_blocks(encoded, block_size=BLOCK_SIZE):
    return encoded.map(
        lambda batch: group_texts(batch, block_size),
        batched=True,
        batch_size=1000,
        desc="packing into blocks",
    )


def prepare(checkpoint, data_files):
    tokenizer = load_tokenizer(checkpoint)
    documents = read_shards(data_files)
    encoded = encode(tokenizer, documents)
    blocks = build_blocks(encoded)
    split = blocks.train_test_split(test_size=VALIDATION_FRACTION)
    return tokenizer, split
