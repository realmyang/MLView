"""Build the FAISS index a retrieval-augmented generator reads from."""

import json

import faiss
import numpy as np
import torch

from encoder import PooledEncoder, encode_texts, load_tokenizer

SEED = 20240914


def read_passages(path):
    passages = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            passages.append({"id": record["id"], "text": record["text"]})
    return passages


def chunk(passages, words=180, stride=120):
    """Split each passage into overlapping word windows, keeping the parent id."""
    chunks = []
    for passage in passages:
        tokens = passage["text"].split()
        for start in range(0, max(len(tokens) - 1, 1), stride):
            window = tokens[start:start + words]
            if not window:
                continue
            chunks.append({"parent": passage["id"], "text": " ".join(window)})
    return chunks


def build(chunks, device, dim=384):
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    tokenizer = load_tokenizer()
    model = PooledEncoder(out_dim=dim)
    model.to(device)
    model.eval()
    vectors = encode_texts(model, tokenizer, [c["text"] for c in chunks], device)
    index = faiss.IndexFlatIP(dim)
    index.add(vectors.astype(np.float32))
    return index, model, tokenizer


def save(index, chunks, index_path="corpus.faiss", meta_path="corpus.jsonl"):
    faiss.write_index(index, index_path)
    with open(meta_path, "w", encoding="utf-8") as handle:
        for record in chunks:
            handle.write(json.dumps(record) + "\n")


def main(passages_path="passages.jsonl"):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    passages = read_passages(passages_path)
    chunks = chunk(passages)
    index, _, _ = build(chunks, device)
    save(index, chunks)
    return index.ntotal


if __name__ == "__main__":
    print(main())
