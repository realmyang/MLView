"""Source reading and `ast.parse`, with failures turned into diagnostics.

Never imports or executes the analyzed source. Keeps the source lines so
snippets and end positions are exact.
"""

from __future__ import annotations

import ast
import io
import tokenize
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = ["ParsedFile", "ParseFailure", "parse_source", "parse_file",
           "parse_all", "parse_bytes", "read_bytes", "decode_source",
           "MAX_SNIPPET"]

MAX_SNIPPET = 200


@dataclass
class ParseFailure:
    """A file that could not be parsed. Becomes a `parse_error` diagnostic."""

    relpath: str
    message: str
    line: Optional[int] = None


@dataclass
class ParsedFile:
    """A successfully parsed source file."""

    relpath: str
    abspath: str
    source: str
    lines: Tuple[str, ...]
    tree: ast.Module
    _ascii: Dict[int, bool] = field(default_factory=dict, repr=False)

    # -- column handling ----------------------------------------------------
    def line_text(self, line: int) -> str:
        """The 1-based source line, or '' when out of range."""
        if 1 <= line <= len(self.lines):
            return self.lines[line - 1]
        return ""

    def char_col(self, line: int, col: int) -> int:
        """Convert `ast` UTF-8 byte columns to character columns.

        They are identical for ASCII lines, which is the overwhelmingly common
        case; the conversion keeps `loc.col` consistent with `loc.snippet` for
        non-ASCII source.
        """
        text = self.line_text(line)
        if not text or col <= 0:
            return max(0, col)
        if self._ascii.get(line) is None:
            self._ascii[line] = text.isascii()
        if self._ascii[line]:
            return col
        raw = text.encode("utf-8", "replace")
        return len(raw[:col].decode("utf-8", "ignore"))

    def snippet(self, line: int) -> Optional[str]:
        """The primary source line, trailing whitespace removed, capped."""
        text = self.line_text(line).rstrip()
        if not text:
            return None
        if len(text) > MAX_SNIPPET:
            return None
        return text

    def slice_line(self, line: int, start: int, end: Optional[int] = None) -> str:
        text = self.line_text(line)
        if end is None:
            return text[start:]
        return text[start:end]


def parse_source(source: str, relpath: str, abspath: str):
    """Parse already-decoded source. Returns (ParsedFile | None, ParseFailure | None).

    PUB-14: `ast.parse` raises CPython's own `SyntaxWarning` for things like an
    invalid escape sequence in the **analyzed** source, and the default warning
    filter prints it - the offending source line and all - on MLView's stderr,
    where the VS Code output channel and the MCP server log it as though the
    analyzer had failed. A fact about somebody else's code belongs in
    `diagnostics[]` or nowhere; it never belongs on this process's stderr.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            warnings.simplefilter("ignore", DeprecationWarning)
            tree = ast.parse(source, filename=relpath)
    except SyntaxError as exc:
        return None, ParseFailure(relpath, "%s: %s" % (type(exc).__name__, exc.msg),
                                  getattr(exc, "lineno", None) or 1)
    except ValueError as exc:  # e.g. source containing null bytes
        return None, ParseFailure(relpath, "ValueError: %s" % exc, 1)
    except RecursionError:
        return None, ParseFailure(relpath, "RecursionError: expression nesting too deep", 1)
    return ParsedFile(relpath=relpath, abspath=abspath, source=source,
                      lines=tuple(source.splitlines()), tree=tree), None


def parse_file(abspath: str, relpath: str):
    """Read and parse one file. Returns (ParsedFile | None, ParseFailure | None)."""
    try:
        with open(abspath, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return None, ParseFailure(relpath, "cannot read file: %s" % exc, None)
    source, failure = decode_source(raw, relpath)
    if source is None:
        return None, failure
    return parse_source(source, relpath, abspath)


def decode_source(raw: bytes, relpath: str):
    """Decode a source file the way CPython does. Returns (text | None, failure)."""
    encoding = "utf-8-sig"
    try:
        # PEP 263: `# -*- coding: latin-1 -*-` is a legal Python file, and
        # decoding it as UTF-8 dropped it out of the analysis entirely.
        detected, _lines = tokenize.detect_encoding(io.BytesIO(raw).readline)
    except (SyntaxError, UnicodeDecodeError):
        detected = None
    if detected and detected.replace("_", "-").lower() not in ("utf-8", "utf-8-sig"):
        encoding = detected
    for candidate in (encoding, "utf-8-sig"):
        try:
            return raw.decode(candidate), None
        except (UnicodeDecodeError, LookupError):
            continue
    try:
        exc_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return None, ParseFailure(
            relpath, "UnicodeDecodeError: not valid UTF-8 (%s at byte %d)"
            % (exc.reason, exc.start), None)
    return exc_text, None


def read_bytes(abspath: str, relpath: str):
    """Read one file. Returns `(bytes | None, ParseFailure | None)`.

    Split out of `parse_file` for CACHE: the content digest that keys the cache
    needs the same bytes the parse needs, and reading a file twice to get both
    is the one cost a cache exists to avoid.
    """
    try:
        with open(abspath, "rb") as fh:
            return fh.read(), None
    except OSError as exc:
        return None, ParseFailure(relpath, "cannot read file: %s" % exc, None)


def parse_bytes(raw: bytes, relpath: str, abspath: str):
    """Decode and parse already-read bytes. The tail half of `parse_file`."""
    source, failure = decode_source(raw, relpath)
    if source is None:
        return None, failure
    return parse_source(source, relpath, abspath)


def parse_all(discovery, progress=None):
    """Parse every discovered file, in sorted order. Returns
    `(parsed, failures, progress)`.

    The third value is the progress sink still in force: `core.progress.safe_call`
    drops a sink that raised, so one bad frame costs one frame and never the
    analysis (H3), and the caller keeps that decision.
    """
    from ..core.progress import safe_call            # local: keeps ingest leaf-ish

    parsed: List[ParsedFile] = []
    failures: List[ParseFailure] = []
    total = len(discovery.files)
    sink = progress
    for index, rel in enumerate(discovery.files, start=1):
        ok, bad = parse_file(discovery.abspath(rel), rel)
        # H3: one frame per file, after the file is read, so `done` counts work
        # completed rather than work started.
        sink = safe_call(sink, index, total, rel)
        if ok is not None:
            parsed.append(ok)
        elif bad is not None:
            failures.append(bad)
    return parsed, failures, sink
