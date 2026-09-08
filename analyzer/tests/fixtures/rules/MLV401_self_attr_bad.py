# MLVIEW-EXPECT: MLV401 line=33 confidence>=0.7 severity=high
"""ANA-2: the criterion is held on `self`, not in a local.

`self.loss_fn(logits, labels)` used to resolve to `torch.nn.Module.loss_fn` -
a symbol nobody ever declared, which prefix-matches to role LAYER - so the
softmax feeding CrossEntropyLoss was invisible on the `self` spelling and
certain on the local one. The binding already says the attribute holds a
`torch.nn.CrossEntropyLoss`; the resolver now reads it.
"""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


class Classifier(nn.Module):
    def __init__(self, features: int = 10, classes: int = 3) -> None:
        super().__init__()
        self.encoder = nn.Linear(features, classes)

    def forward(self, x):
        return torch.softmax(self.encoder(x), dim=1)


class Trainer:
    def __init__(self, features: int = 10, classes: int = 3) -> None:
        self.model = Classifier(features, classes)
        self.loss_fn = nn.CrossEntropyLoss()
        self.optimizer = optim.SGD(self.model.parameters(), lr=0.01)

    def step(self, features, labels):
        self.optimizer.zero_grad()
        loss = self.loss_fn(self.model(features), labels)
        loss.backward()
        self.optimizer.step()
        return loss


def train(dataset: TensorDataset) -> None:
    torch.manual_seed(0)
    trainer = Trainer()
    loader = DataLoader(dataset, batch_size=16, shuffle=True)
    for features, labels in loader:
        trainer.step(features, labels)
