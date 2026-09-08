"""Hyperparameters and paths for the demo pipeline - corrected twin.

Same five files, same structure as `samples/vision_pipeline`, every planted
defect fixed. MLView reports **nothing** here; that is the point of the file.

Fix 13 (MLV601): every random source is seeded from one place.
"""

import random

import numpy as np
import torch

SEED = 1337

DATA_ROOT = "data/cifar10"
FEATURE_PATH = "data/features.npz"

BATCH_SIZE = 128
EVAL_BATCH_SIZE = 256
NUM_WORKERS = 4
EPOCHS = 20
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 0.0
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

TRAIN_SIZE = 45000
VAL_SIZE = 5000
NUM_CLASSES = 10
WIDTH = 32
DEPTH = 4

PCA_COMPONENTS = 32
CV_FOLDS = 5
TEST_FRACTION = 0.2


def set_seed(seed: int = SEED) -> None:
    """Pin every random source the pipeline touches."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
