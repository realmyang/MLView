
import os
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

try:
    import lightning.pytorch as pl
except ImportError:  # pragma: no cover
    try:
        import pytorch_lightning as pl
    except ImportError:
        pl = None

if os.environ.get("USE_AMP"):
    from torch.amp import GradScaler
else:
    GradScaler = None

HAS_SK = True
try:
    from sklearn.model_selection import train_test_split
except ImportError:
    HAS_SK = False

    def train_test_split(*a, **k):
        raise RuntimeError


def train(X, y):
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(list(zip(X_tr, y_tr)), batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        out = model(xb)
        loss = crit(out, yb)
        loss.backward()
        opt.step()
    return model
