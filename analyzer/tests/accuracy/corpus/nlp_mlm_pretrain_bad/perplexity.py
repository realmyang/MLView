"""Score a pre-trained checkpoint on the held-out blocks.

Defective: the model is never put in eval mode, the pass runs with gradients
on, the evaluation loader shuffles, the batches are left on the CPU while the
model is moved to the GPU, and the masked accuracy is read off the raw logits.
"""

import math

import torch
from sklearn.metrics import accuracy_score
from torch.utils.data import DataLoader
from transformers import AutoModelForMaskedLM, DataCollatorForLanguageModeling

from corpus import load_tokenizer, prepare

CHECKPOINT = "roberta-base"
BATCH_SIZE = 16


def build_eval_loader(split, tokenizer):
    collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer, mlm=True, mlm_probability=0.15
    )
    return DataLoader(
        split["test"],
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=8,
        collate_fn=collator,
    )


def score(model, loader, device):
    total_loss = 0.0
    batches = 0
    flat_labels = []
    flat_logits = []
    for batch in loader:
        outputs = model(**batch)
        total_loss += outputs.loss.item()
        batches += 1
        labels = batch["labels"].reshape(-1)
        keep = labels != -100
        flat_labels.append(labels[keep])
        flat_logits.append(outputs.logits.reshape(-1, outputs.logits.shape[-1])[keep])
    labels = torch.cat(flat_labels).cpu().numpy()
    logits = torch.cat(flat_logits).cpu().numpy()
    accuracy = accuracy_score(labels, logits)
    return {
        "eval_loss": total_loss / max(batches, 1),
        "perplexity": math.exp(total_loss / max(batches, 1)),
        "masked_accuracy": accuracy,
    }


def main(run_dir="runs/mlm", data_files="shards/*.txt"):
    device = torch.device("cuda")
    state = torch.load(run_dir + "/pytorch_model.bin")
    model = AutoModelForMaskedLM.from_pretrained(CHECKPOINT)
    model.load_state_dict(state)
    model.to(device)
    tokenizer = load_tokenizer(CHECKPOINT)
    _, split = prepare(CHECKPOINT, data_files)
    loader = build_eval_loader(split, tokenizer)
    return score(model, loader, device)


print(main())
