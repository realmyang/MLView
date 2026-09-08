# MLVIEW-EXPECT: MLV301 line=36 severity=high confidence>=0.6 bucket=likely ghost=true
"""`model = Net().to(device)` - construction chained with the device move, the
most common way a PyTorch model is written. The chained call used to drop the
class binding, so MLV301 could not see the Dropout layer and capped itself to
medium / 0.595, below the 0.6 Problems-panel threshold."""
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
    device = torch.device("cuda")
    model = Net().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.1)
    loader = DataLoader(dataset, batch_size=8, shuffle=True)
    val_loader = DataLoader(dataset, batch_size=8)
    for features, labels in loader:
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(model(features.to(device)), labels.to(device))
        loss.backward()
        optimizer.step()
    with torch.no_grad():
        for features, labels in val_loader:
            model(features.to(device)).argmax(1)
