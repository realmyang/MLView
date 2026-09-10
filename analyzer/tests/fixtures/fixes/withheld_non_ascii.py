# MLVIEW-EXPECT: MLV111 confidence>=0.7
"""H5, withheld: the line the edit would touch is not ASCII.

CONTRACTS section 0 says a column is 0-based and "matches `ast.col_offset` and
`vscode.Position.character`". Both are true for an ASCII line and neither is
true for this one: `ast` counts UTF-8 bytes, VS Code counts UTF-16 code units.
Reading a location a few columns wide off by a character costs a highlight;
applying an *edit* at the wrong offset corrupts the file. So the finding fires
and no edit is offered.
"""
import torch
from torch.utils.data import DataLoader, TensorDataset, random_split


def build(dataset: TensorDataset):
    train_ds, test_ds = random_split(dataset, [45000, 5000],
                                     generator=torch.Generator().manual_seed(0))
    train_loader = DataLoader(train_ds, batch_size=64, shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=256, shuffle=True)  # ordre aléatoire ☑
    return train_loader, test_loader
