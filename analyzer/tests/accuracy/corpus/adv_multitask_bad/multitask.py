"""Multi-task learning with uncertainty weighting - the defective version.

The twin of `adv_advanced_clean/multitask.py`: three heads (classification,
regression, a binary auxiliary), each with a learned homoscedastic log-variance
that weights its term. Ten defects.

The one that silently destroys the method is the log-variances living in a
plain Python list: `nn.Parameter` objects in a list are not registered, so
`optimizer.step()` never moves them and every task keeps its initial weight for
the whole run - while the loss still *looks* like uncertainty weighting.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

EPOCHS = 40
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class MultiTaskNet(nn.Module):
    def __init__(self, in_dim: int, hidden: int, num_classes: int) -> None:
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(in_dim, hidden),
            nn.BatchNorm1d(hidden),
            nn.ReLU(),
            nn.Dropout(0.3),
        )
        # DEFECT: the three heads live in a plain dict, so none of them is
        # registered and .parameters() never yields their weights.
        self.heads = {
            "class": nn.Linear(hidden, num_classes),
            "regress": nn.Linear(hidden, 1),
            "aux": nn.Linear(hidden, 1),
        }
        # DEFECT: the learned log-variances live in a plain list, so the
        # optimizer never sees them and the task weights never move.
        self.log_vars = [nn.Parameter(torch.zeros(1)) for _ in range(3)]

    def forward(self, x):
        features = self.trunk(x)
        return (self.heads["class"](features),
                self.heads["regress"](features).squeeze(-1),
                self.heads["aux"](features).squeeze(-1))


def weighted_loss(model, outputs, targets, criteria):
    """Kendall-style uncertainty weighting over the three task losses."""
    class_logits, regression, auxiliary = outputs
    class_target, regression_target, aux_target = targets
    class_criterion, regression_criterion, aux_criterion = criteria

    # DEFECT: the classification logits are softmaxed before CrossEntropyLoss,
    # which log-softmaxes them a second time.
    class_loss = class_criterion(F.softmax(class_logits, dim=-1), class_target)
    regression_loss = regression_criterion(regression, regression_target)
    # DEFECT: raw logits are handed to BCELoss, which expects probabilities.
    aux_loss = aux_criterion(auxiliary, aux_target)

    total = 0.0
    for index, term in enumerate((class_loss, regression_loss, aux_loss)):
        precision = torch.exp(-model.log_vars[index])
        total = total + precision * term + model.log_vars[index]
    return total


def train_epoch(model, loader, criteria, optimizer) -> float:
    model.train()
    running = 0.0
    for features, class_target, regression_target, aux_target in loader:
        features = features.to(DEVICE)
        outputs = model(features)
        loss = weighted_loss(model, outputs,
                             (class_target, regression_target, aux_target),
                             criteria)
        optimizer.zero_grad(set_to_none=True)
        # DEFECT: the optimizer steps before the gradients for this batch
        # exist, so every update applies the previous batch's gradients.
        optimizer.step()
        loss.backward()
        # DEFECT: the epoch loss keeps the live tensor.
        running += loss
    return running


def evaluate(model, loader, criteria) -> float:
    """DEFECT: no model.eval() and no torch.no_grad(), so the 0.3 dropout is
    active and the BatchNorm running statistics keep moving while the model is
    being measured."""
    total = 0.0
    batches = 0
    for features, class_target, regression_target, aux_target in loader:
        outputs = model(features.to(DEVICE))
        total += float(weighted_loss(model, outputs,
                                     (class_target, regression_target, aux_target),
                                     criteria))
        batches += 1
    return total / max(batches, 1)


def main() -> None:
    # DEFECT: nothing seeds torch, numpy or random anywhere in this project.
    features = torch.randn(512, 16)
    train_set = TensorDataset(features, torch.randint(0, 4, (512,)),
                              torch.randn(512), torch.rand(512))
    test_set = TensorDataset(torch.randn(128, 16), torch.randint(0, 4, (128,)),
                             torch.randn(128), torch.rand(128))
    # DEFECT: the training loader does not shuffle.
    train_loader = DataLoader(train_set, batch_size=32, shuffle=False)
    # DEFECT: the evaluation loader shuffles.
    test_loader = DataLoader(test_set, batch_size=32, shuffle=True)

    model = MultiTaskNet(16, 64, 4).to(DEVICE)
    criteria = (nn.CrossEntropyLoss(), nn.MSELoss(), nn.BCELoss())
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    for epoch in range(EPOCHS):
        loss = train_epoch(model, train_loader, criteria, optimizer)
        if epoch % 10 == 0:
            print("epoch %d train %.4f test %.4f"
                  % (epoch, float(loss), evaluate(model, test_loader, criteria)))
    # DEFECT: the whole module is pickled rather than its state_dict.
    torch.save(model, "multitask.pt")


main()
