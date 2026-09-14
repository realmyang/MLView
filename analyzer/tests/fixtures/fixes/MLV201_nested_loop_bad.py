# MLVIEW-EXPECT: MLV201 confidence>=0.7
"""H5: the batch loop is four suites deep - method, epoch loop, `if` - so the
inserted `zero_grad()` has to be indented 20 columns and not 4.

This is the fixture the "edits are computed from the AST, never spliced" rule
exists for: the only correct answer for the indentation is the first body
statement's own `col_offset`.
"""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


class Trainer:
    def __init__(self, model: nn.Module) -> None:
        self.model = model
        self.criterion = nn.CrossEntropyLoss()
        self.optimizer = optim.Adam(model.parameters(), lr=0.001)

    def run(self, dataset: TensorDataset, epochs: int = 5, enabled: bool = True) -> None:
        torch.manual_seed(0)
        loader = DataLoader(dataset, batch_size=32, shuffle=True)
        self.model.train()
        for epoch in range(epochs):
            if enabled:
                for features, labels in loader:
                    outputs = self.model(features)
                    loss = self.criterion(outputs, labels)
                    loss.backward()
                    self.optimizer.step()
