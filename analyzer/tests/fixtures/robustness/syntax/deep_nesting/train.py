import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for i0 in range(2):
        for i1 in range(2):
            for i2 in range(2):
                for i3 in range(2):
                    for i4 in range(2):
                        for i5 in range(2):
                            for i6 in range(2):
                                for i7 in range(2):
                                    for i8 in range(2):
                                        for i9 in range(2):
                                            for i10 in range(2):
                                                for i11 in range(2):
                                                    for i12 in range(2):
                                                        for i13 in range(2):
                                                            for i14 in range(2):
                                                                for i15 in range(2):
                                                                    for i16 in range(2):
                                                                        for i17 in range(2):
                                                                            for xb, yb in loader:
                                                                                opt.zero_grad()
                                                                                loss = crit(model(xb), yb)
                                                                                loss.backward()
                                                                                opt.step()
    return model
