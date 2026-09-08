# MLVIEW-EXPECT: MLV112 line=14 confidence>=0.6 severity=medium
"""num_workers=4 in a module with no __main__ guard: spawn re-imports this file."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

NUM_WORKERS = 4

DATASET = TensorDataset(torch.zeros(8, 10), torch.zeros(8, dtype=torch.long))
MODEL = nn.Sequential(nn.Linear(10, 3))
CRITERION = nn.CrossEntropyLoss()
OPTIMIZER = optim.SGD(MODEL.parameters(), lr=0.01)
LOADER = DataLoader(DATASET, batch_size=4, shuffle=True, num_workers=NUM_WORKERS)

torch.manual_seed(0)
for features, labels in LOADER:
    OPTIMIZER.zero_grad()
    loss = CRITERION(MODEL(features), labels)
    loss.backward()
    OPTIMIZER.step()
