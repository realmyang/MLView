
"""A local module that shadows the stdlib `random`."""

SEED = 1234


def seed(value=SEED):
    return value
