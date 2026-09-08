"""Version identity for the MLView core.

`RENDERER_SHA` is *not* stored here: per CONTRACTS amendment A2 the analyzer
computes the SHA-256 of ``emit/assets/mlview.js`` at runtime (cached per
process) and emits 64 zeros when the asset has not been synced yet.
"""

from __future__ import annotations

__all__ = ["__version__", "SCHEMA_VERSION", "GENERATOR_NAME", "renderer_sha"]

__version__ = "0.1.0"
SCHEMA_VERSION = "1.0"
GENERATOR_NAME = "mlview"

_ZERO_SHA = "0" * 64
_renderer_sha_cache: str | None = None


def renderer_sha() -> str:
    """SHA-256 of the shipped viewer bundle, or 64 zeros when absent."""
    global _renderer_sha_cache
    if _renderer_sha_cache is not None:
        return _renderer_sha_cache
    import hashlib
    import os

    asset = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emit", "assets", "mlview.js")
    try:
        with open(asset, "rb") as fh:
            _renderer_sha_cache = hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        _renderer_sha_cache = _ZERO_SHA
    return _renderer_sha_cache
