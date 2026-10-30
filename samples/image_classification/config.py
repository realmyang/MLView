"""Hyperparameters and paths for the image-classification example.

The dataset and the feature file are external.
"""

DATA_ROOT = "data/cifar10"
FEATURE_PATH = "data/features.npz"

BATCH_SIZE = 128
EVAL_BATCH_SIZE = 256
NUM_WORKERS = 4
EPOCHS = 20
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 0.0
DEVICE = "cuda"

TRAIN_SIZE = 45000
VAL_SIZE = 5000
NUM_CLASSES = 10
WIDTH = 32
DEPTH = 4

PCA_COMPONENTS = 32
CV_FOLDS = 5
TEST_FRACTION = 0.2
