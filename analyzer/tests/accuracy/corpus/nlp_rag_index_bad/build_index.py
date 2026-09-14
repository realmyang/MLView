"""Build the FAISS index a retrieval-augmented generator reads from.

Defective twin of `nlp_rag_index/build_index.py`.
"""

import json

import faiss
import numpy as np
import torch
from sklearn.decomposition import PCA

from encoder import PooledEncoder, encode_texts, load_tokenizer


def read_passages(path):
    passages = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            passages.append({"id": record["id"], "text": record["text"]})
    return passages


def read_queries(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def chunk(passages, words=180, stride=120):
    chunks = []
    for passage in passages:
        tokens = passage["text"].split()
        for start in range(0, max(len(tokens) - 1, 1), stride):
            window = tokens[start:start + words]
            if not window:
                continue
            chunks.append({"parent": passage["id"], "text": " ".join(window)})
    return chunks


def fit_whitener(corpus_vectors, query_vectors, dim=256):
    """Whiten the embedding space using the corpus *and* the dev queries."""
    whitener = PCA(n_components=dim, whiten=True)
    everything = np.vstack([corpus_vectors, query_vectors])
    whitener.fit(everything)
    return whitener


def build(chunks, queries, dim=256):
    device = torch.device("cuda")
    tokenizer = load_tokenizer()
    model = PooledEncoder()
    model.to(device)
    corpus_vectors = encode_texts(model, tokenizer, [c["text"] for c in chunks], device)
    query_vectors = encode_texts(model, tokenizer,
                                 [q["question"] for q in queries], device)
    whitener = fit_whitener(corpus_vectors, query_vectors, dim)
    index = faiss.IndexFlatIP(dim)
    index.add(whitener.transform(corpus_vectors).astype(np.float32))
    return index, model, tokenizer, whitener


def save(index, chunks, index_path="corpus.faiss", meta_path="corpus.jsonl"):
    faiss.write_index(index, index_path)
    with open(meta_path, "w", encoding="utf-8") as handle:
        for record in chunks:
            handle.write(json.dumps(record) + "\n")


def main(passages_path="passages.jsonl", queries_path="dev_queries.jsonl"):
    chunks = chunk(read_passages(passages_path))
    queries = read_queries(queries_path)
    index, _, _, _ = build(chunks, queries)
    save(index, chunks)
    return index.ntotal


if __name__ == "__main__":
    print(main())
