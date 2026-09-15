# MLVIEW-EXPECT: MLV305 line=26 severity=medium
"""REC-07: a batched evaluation collects one array per batch and joins them.

`predictions.append(raw_scores(model, features))` then `accuracy_score(...,
np.concatenate(predictions))` is how every torch eval loop is written, and the
PROBS tag used to die in the list - so MLV305 stayed silent on the dominant
real-world spelling of its own defect and only disclosed the gap."""
import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import accuracy_score


def raw_scores(model, features):
    return F.softmax(model(features), dim=-1).detach().cpu().numpy()


def evaluate(model, loader) -> float:
    model.eval()
    predictions = []
    truths = []
    with torch.no_grad():
        for features, labels in loader:
            predictions.append(raw_scores(model, features))
            truths.append(labels.numpy())
    return accuracy_score(np.concatenate(truths), np.concatenate(predictions))
