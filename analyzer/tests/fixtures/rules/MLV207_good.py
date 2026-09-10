# MLVIEW-EXPECT-NONE: MLV207
"""The trap: StepLR is stepped inside the batch loop on purpose, because its
step_size is len(train_loader) * 2 - the schedule counts batches, so a rule that
only compared the scheduler class against the loop kind would fire here."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset, epochs: int = 5) -> nn.Module:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(16, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.1)
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)
    scheduler = optim.lr_scheduler.StepLR(optimizer, gamma=0.5,
                                          step_size=len(train_loader) * 2)

    model.train()
    for epoch in range(epochs):
        for features, labels in train_loader:
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(features), labels)
            loss.backward()
            optimizer.step()
            scheduler.step()
    return model
