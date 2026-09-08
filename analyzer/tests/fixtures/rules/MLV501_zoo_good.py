# MLVIEW-EXPECT-NONE: MLV501, MLV301, MLV302
"""The trap: the network comes from a model zoo the knowledge tables do not
know (`timm.create_model`), so the only FORWARD call that resolves in the loop
is `criterion(...)` - `nn.CrossEntropyLoss` is an `nn.Module` too. Reporting it
produced a finding that named the *loss* as "the model" and claimed no
nn.Module was ever moved, two lines under `model.to(device)`."""
import timm
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset) -> None:
    torch.manual_seed(0)
    device = torch.device("cuda")
    model = timm.create_model("resnet18", num_classes=2)
    model.to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.1)
    loader = DataLoader(dataset, batch_size=8, shuffle=True)
    for features, labels in loader:
        features = features.to(device)
        labels = labels.to(device)
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(model(features), labels)
        loss.backward()
        optimizer.step()
