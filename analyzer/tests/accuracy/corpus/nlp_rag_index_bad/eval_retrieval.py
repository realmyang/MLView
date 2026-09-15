"""Score the retriever on a held-out query set: recall@k and MRR@k.

Defective twin of `nlp_rag_index/eval_retrieval.py`.
"""

import json

import numpy as np
import torch

from build_index import build, chunk, read_passages, read_queries
from encoder import encode_texts, load_tokenizer

K = 10


def recall_at_k(ranked_parents, gold_parent, k=K):
    return float(gold_parent in ranked_parents[:k])


def reciprocal_rank(ranked_parents, gold_parent, k=K):
    for position, parent in enumerate(ranked_parents[:k], start=1):
        if parent == gold_parent:
            return 1.0 / position
    return 0.0


def search(index, chunks, query_vectors, k=K):
    scores, indices = index.search(query_vectors.astype(np.float32), k)
    ranked = []
    for row in indices:
        ranked.append([chunks[position]["parent"] for position in row])
    return scores, ranked


def evaluate(index, chunks, model, tokenizer, whitener, queries, device, k=K):
    vectors = encode_texts(model, tokenizer, [q["question"] for q in queries], device)
    projected = whitener.fit_transform(vectors)
    _, ranked = search(index, chunks, projected, k)
    recalls = [recall_at_k(row, q["parent"], k) for row, q in zip(ranked, queries)]
    rrs = [reciprocal_rank(row, q["parent"], k) for row, q in zip(ranked, queries)]
    return {"recall@%d" % k: float(np.mean(recalls)),
            "mrr@%d" % k: float(np.mean(rrs))}


def main(passages_path="passages.jsonl", queries_path="dev_queries.jsonl"):
    device = torch.device("cuda")
    chunks = chunk(read_passages(passages_path))
    queries = read_queries(queries_path)
    index, model, tokenizer, whitener = build(chunks, queries)
    metrics = evaluate(index, chunks, model, tokenizer, whitener, queries, device)
    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    main()
