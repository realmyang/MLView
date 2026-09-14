"""The deferred half, said out loud rather than left silent."""
from __future__ import annotations

import yaml


def load_config(path="conf/config.yaml"):
    with open(path) as handle:
        return yaml.safe_load(handle)
