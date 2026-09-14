"""Score saved generations with BLEU and ROUGE.

An evaluation-only script: the predictions were written by an earlier run, so
there is no model, no loader and no loop over anything but a JSONL file. It is
the second false-positive trap in this project — an `eval` stage with no
`train` stage anywhere is a legitimate program, not a finding.
"""
from __future__ import annotations

import json

import evaluate
import numpy as np

PREDICTIONS = "runs/sum/predictions.jsonl"


def read_jsonl(path: str = PREDICTIONS):
    predictions = []
    references = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            predictions.append(row["prediction"].strip())
            references.append(row["reference"].strip())
    return predictions, references


def length_profile(predictions):
    lengths = np.array([len(text.split()) for text in predictions])
    return {"median_tokens": float(np.median(lengths)),
            "empty": int((lengths == 0).sum())}


def score(predictions, references):
    bleu = evaluate.load("sacrebleu")
    rouge = evaluate.load("rouge")
    bleu_score = bleu.compute(predictions=predictions,
                              references=[[r] for r in references])
    rouge_score = rouge.compute(predictions=predictions, references=references)
    return {"bleu": bleu_score["score"],
            "rouge1": rouge_score["rouge1"],
            "rougeL": rouge_score["rougeL"]}


def main():
    predictions, references = read_jsonl()
    report = score(predictions, references)
    report.update(length_profile(predictions))
    print(json.dumps(report, indent=2, sort_keys=True))


main()
