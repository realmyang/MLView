# MLVIEW-EXPECT: MLV302 confidence>=0.6
"""H5, withheld: the evaluation loop is at module level.

There is no `def` to decorate, and the only remaining shape of the fix is the
`with torch.no_grad():` wrap - which means re-indenting every physical line of
the suite. A triple-quoted string inside such a suite would silently change
value, so no edit is offered here at all.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset


class Net(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.fc1 = nn.Linear(64, 32)
        self.drop = nn.Dropout(0.5)
        self.fc2 = nn.Linear(32, 10)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(self.drop(F.relu(self.fc1(x))))


torch.manual_seed(0)
model = Net()
model.eval()
test_loader = DataLoader(TensorDataset(torch.zeros(4, 64), torch.zeros(4)),
                         batch_size=2, shuffle=False)

hits = 0
for features, labels in test_loader:
    preds = model(features).argmax(dim=1)
    hits += (preds == labels).sum().item()
