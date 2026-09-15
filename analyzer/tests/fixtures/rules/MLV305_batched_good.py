# MLVIEW-EXPECT-NONE: MLV305
"""REC-07's negative twin: the per-batch list is argmaxed before it is filled.

The collector hop is an **intersection** over the appends it can see, not a
union, so a list whose elements are class decisions carries no LOGITS / PROBS
and MLV305 stays quiet - and a list that received both would carry neither,
which is the safe direction for a rule that must never accuse correct code."""
import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import accuracy_score


def hard_labels(model, features):
    return F.softmax(model(features), dim=-1).argmax(dim=-1).detach().cpu().numpy()


def evaluate(model, loader) -> float:
    torch.manual_seed(0)
    model.eval()
    predictions = []
    truths = []
    with torch.no_grad():
        for features, labels in loader:
            predictions.append(hard_labels(model, features))
            truths.append(labels.numpy())
    return accuracy_score(np.concatenate(truths), np.concatenate(predictions))
