# MLVIEW-EXPECT-NONE: MLV201
"""H5: the clean twin of `MLV201_nested_loop_bad.py` - the same four suites of
nesting with the `zero_grad()` already in the slot the fix would have written
it into. It must raise **no** issue at all and offer **no** fix.
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
                    self.optimizer.zero_grad(set_to_none=True)
                    outputs = self.model(features)
                    loss = self.criterion(outputs, labels)
                    loss.backward()
                    self.optimizer.step()
