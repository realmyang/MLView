"""A small feature-store package: splits in one module, fits in another."""
from .registry import FeatureStore
from .splits import stratified_split

__all__ = ["FeatureStore", "stratified_split"]
