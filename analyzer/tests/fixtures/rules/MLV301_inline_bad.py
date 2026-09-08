# MLVIEW-EXPECT: MLV301 line=37 severity=high ghost=true
# MLVIEW-EXPECT: MLV302 line=37
"""The one-line accuracy accumulator: the forward pass sits inside a comparison
inside a call chain inside an `AugAssign`, so it never appeared as a statement
of its own. The eval region was invisible, MLV301 and MLV302 both went missing,
and the loop was drawn in the Train lane while the Evaluate lane reported
"not detected"."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


class Net(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.drop = nn.Dropout(0.3)
        self.fc = nn.Linear(4, 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc(self.drop(x))


def train(dataset: TensorDataset) -> None:
    torch.manual_seed(0)
    model = Net()
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.1)
    loader = DataLoader(dataset, batch_size=8, shuffle=True)
    val_loader = DataLoader(dataset, batch_size=8)
    for features, labels in loader:
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(model(features), labels)
        loss.backward()
        optimizer.step()
    hits = 0
    for features, labels in val_loader:
        hits += (model(features).argmax(1) == labels).sum().item()
    return hits
