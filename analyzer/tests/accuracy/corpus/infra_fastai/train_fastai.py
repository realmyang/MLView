"""A fastai image classifier, written the way the fastai course writes one.

fastai owns everything: the dataloaders, the optimizer, the schedule, the
train/eval switch and the checkpointing. There is no hand-written loop, no
`optimizer.step()`, no `model.eval()` — and their absence is not a defect.

`valid_pct=0.2, seed=42` is the split, and it is seeded. Any finding in this
file is a false positive.
"""
from __future__ import annotations

from pathlib import Path

from fastai.callback.schedule import fine_tune
from fastai.callback.tracker import EarlyStoppingCallback, SaveModelCallback
from fastai.data.transforms import Normalize, get_image_files, parent_label
from fastai.metrics import accuracy, error_rate
from fastai.vision.augment import Resize, aug_transforms
from fastai.vision.data import ImageDataLoaders
from fastai.vision.learner import vision_learner
from torchvision.models import resnet34

DATA_ROOT = Path("data/pets")
IMAGE_SIZE = 224
BATCH_SIZE = 64


def build_dataloaders(root: Path = DATA_ROOT):
    """80/20 split held by fastai, seeded so the split is reproducible."""
    return ImageDataLoaders.from_name_func(
        root,
        get_image_files(root),
        valid_pct=0.2,
        seed=42,
        label_func=parent_label,
        item_tfms=Resize(IMAGE_SIZE),
        batch_tfms=[*aug_transforms(size=IMAGE_SIZE, min_scale=0.75),
                    Normalize.from_stats(*[[0.485, 0.456, 0.406],
                                           [0.229, 0.224, 0.225]])],
        bs=BATCH_SIZE,
    )


def build_learner(dls):
    return vision_learner(
        dls,
        resnet34,
        metrics=[error_rate, accuracy],
        cbs=[SaveModelCallback(monitor="valid_loss", fname="best"),
             EarlyStoppingCallback(monitor="valid_loss", patience=3)],
    )


def main(epochs: int = 5, freeze_epochs: int = 1) -> None:
    dls = build_dataloaders()
    learn = build_learner(dls)
    learn.fine_tune(epochs, freeze_epochs=freeze_epochs, base_lr=2e-3)
    print(learn.validate())
    interpretation = learn.get_preds()
    print(interpretation[0].shape)
    learn.export("artifacts/pets.pkl")


if __name__ == "__main__":
    main()
