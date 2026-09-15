"""MONAI dictionary transforms for a 3-D CT segmentation task.

Everything in MONAI is keyed: a transform takes `{"image": ..., "label": ...}`
and applies itself to the keys it is given, which is how a geometric
augmentation stays consistent between the volume and its mask. The two
pipelines below differ in exactly one way - the training one has the four
`Rand*` stages and the validation one does not.
"""

from __future__ import annotations

from monai.transforms import (Compose, CropForegroundd, EnsureChannelFirstd,
                              EnsureTyped, LoadImaged, NormalizeIntensityd,
                              Orientationd, RandCropByPosNegLabeld, RandFlipd,
                              RandRotate90d, RandScaleIntensityd,
                              RandShiftIntensityd, ScaleIntensityRanged, Spacingd)

KEYS = ("image", "label")
PATCH_SIZE = (96, 96, 96)
HU_WINDOW = (-175.0, 250.0)


def train_transforms(patch=PATCH_SIZE, samples: int = 4) -> Compose:
    """Load, resample, window, crop positives, then augment."""
    return Compose([
        LoadImaged(keys=KEYS),
        EnsureChannelFirstd(keys=KEYS),
        Orientationd(keys=KEYS, axcodes="RAS"),
        Spacingd(keys=KEYS, pixdim=(1.5, 1.5, 2.0),
                 mode=("bilinear", "nearest")),
        ScaleIntensityRanged(keys="image", a_min=HU_WINDOW[0], a_max=HU_WINDOW[1],
                             b_min=0.0, b_max=1.0, clip=True),
        CropForegroundd(keys=KEYS, source_key="image"),
        RandCropByPosNegLabeld(keys=KEYS, label_key="label",
                               spatial_size=patch, pos=1, neg=1,
                               num_samples=samples, image_key="image",
                               image_threshold=0),
        RandFlipd(keys=KEYS, spatial_axis=[0], prob=0.10),
        RandRotate90d(keys=KEYS, prob=0.10, max_k=3),
        RandScaleIntensityd(keys="image", factors=0.1, prob=0.50),
        RandShiftIntensityd(keys="image", offsets=0.10, prob=0.50),
        EnsureTyped(keys=KEYS),
    ])


def val_transforms() -> Compose:
    """The same geometry and the same windowing, with nothing random."""
    return Compose([
        LoadImaged(keys=KEYS),
        EnsureChannelFirstd(keys=KEYS),
        Orientationd(keys=KEYS, axcodes="RAS"),
        Spacingd(keys=KEYS, pixdim=(1.5, 1.5, 2.0),
                 mode=("bilinear", "nearest")),
        ScaleIntensityRanged(keys="image", a_min=HU_WINDOW[0], a_max=HU_WINDOW[1],
                             b_min=0.0, b_max=1.0, clip=True),
        CropForegroundd(keys=KEYS, source_key="image"),
        EnsureTyped(keys=KEYS),
    ])


def test_transforms() -> Compose:
    """Inference on an unlabelled volume: the image key only."""
    return Compose([
        LoadImaged(keys="image"),
        EnsureChannelFirstd(keys="image"),
        Orientationd(keys="image", axcodes="RAS"),
        Spacingd(keys="image", pixdim=(1.5, 1.5, 2.0), mode="bilinear"),
        ScaleIntensityRanged(keys="image", a_min=HU_WINDOW[0], a_max=HU_WINDOW[1],
                             b_min=0.0, b_max=1.0, clip=True),
        NormalizeIntensityd(keys="image", nonzero=True, channel_wise=True),
        EnsureTyped(keys="image"),
    ])
