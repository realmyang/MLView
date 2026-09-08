"""MLView analyzer core.

Static analysis of Python ML code into an ``MLGraph`` document
(``contracts/graph.schema.json``). Zero runtime dependencies; never imports,
executes or ``exec``s the analyzed source.
"""

from __future__ import annotations

from .version import __version__, SCHEMA_VERSION, GENERATOR_NAME

__all__ = ["__version__", "SCHEMA_VERSION", "GENERATOR_NAME"]
