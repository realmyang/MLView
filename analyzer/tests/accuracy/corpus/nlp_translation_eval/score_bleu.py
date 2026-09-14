"""Score a translation checkpoint on a held-out test set with sacreBLEU + chrF."""

import json

import evaluate
import torch
from datasets import load_dataset
from transformers import set_seed

from generate import CHECKPOINT, load, translate

SEED = 515


def read_testset(name="wmt16", config="de-en", split="test"):
    raw = load_dataset(name, config, split=split)
    sources = [row["translation"]["en"] for row in raw]
    references = [row["translation"]["de"] for row in raw]
    return sources, references


def score(hypotheses, references):
    bleu = evaluate.load("sacrebleu")
    chrf = evaluate.load("chrf")
    wrapped = [[reference] for reference in references]
    return {
        "bleu": bleu.compute(predictions=hypotheses, references=wrapped)["score"],
        "chrf": chrf.compute(predictions=hypotheses, references=wrapped)["score"],
    }


def write_predictions(path, sources, hypotheses, references):
    with open(path, "w", encoding="utf-8") as handle:
        for source, hypothesis, reference in zip(sources, hypotheses, references):
            handle.write(json.dumps({"src": source, "hyp": hypothesis,
                                     "ref": reference}) + "\n")


def main(out_path="predictions.jsonl", beams=4):
    set_seed(SEED)
    torch.use_deterministic_algorithms(False)
    model, tokenizer, device = load(CHECKPOINT)
    sources, references = read_testset()
    hypotheses = translate(model, tokenizer, sources, device, beams=beams)
    write_predictions(out_path, sources, hypotheses, references)
    metrics = score(hypotheses, references)
    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    main()
