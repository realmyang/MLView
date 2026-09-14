"""ROB-16. The canonical HuggingFace `accelerate` loop, and the whole training
step is missing from the diagram.

This is the loop `accelerate`'s own quick tour prints, down to the argument
order. `accelerator.prepare(...)` is not optional in `accelerate` - it is how
the model, the optimizer and the loader are placed - and neither is
`accelerator.backward(loss)`.

Observed, `--dataflow local` and `ip` alike::

    train lane nodes:  main()  accelerator  optimizer  for-epoch  for-batch
    NOT drawn:         model(**batch) · accelerator.backward(loss) ·
                       optimizer.step() · lr_scheduler.step() ·
                       optimizer.zero_grad()

Five calls of the training step, none of them on the diagram, because
`accelerator.prepare` has no knowledge-table entry: it returns untagged, and
re-binding `model`/`optimizer`/`loader` to its result **erases** the MODEL,
OPTIMIZER and LOADER tags those names already carried.

The cost is not only the picture. Delete `optimizer.zero_grad()` from this file
and MLView reports **nothing at all** in either mode - not a de-rated finding,
not a suppressed one - while the same deletion in a plain torch loop is
`MLV201 high`. The one diagnostic the document carries names
`accelerator.backward()` and says nothing about the optimizer.

`analyzer/tests/accuracy/corpus/infra_accelerate/train_accelerate.py`, which
ships with the corpus and says "Any finding in this file is a false positive",
reproduces this unmodified.
"""
import torch
import torch.nn as nn
from accelerate import Accelerator
from torch.utils.data import DataLoader


def main(dataset, epochs=3):
    accelerator = Accelerator()
    model = nn.Linear(16, 3)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4)
    criterion = nn.CrossEntropyLoss()
    loader = DataLoader(dataset, batch_size=8, shuffle=True)
    lr_scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    model, optimizer, loader, lr_scheduler = accelerator.prepare(
        model, optimizer, loader, lr_scheduler)

    for _ in range(epochs):
        model.train()
        for features, targets in loader:
            outputs = model(features)
            loss = criterion(outputs, targets)
            accelerator.backward(loss)
            optimizer.step()
            lr_scheduler.step()
            optimizer.zero_grad()
    return model
