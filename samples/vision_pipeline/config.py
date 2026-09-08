"""Hyperparameters and paths for the demo pipeline.

This is the *dirty* sample: it carries exactly the fifteen planted defects
listed in `samples/README.md`. It is never executed - MLView reads it
statically, and neither torch nor scikit-learn is installed.

Planted here: MLV601 - no random seed is set anywhere in this workspace.
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
