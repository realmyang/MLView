#!/usr/bin/env python
"""Generate `media/icon.png` — the 128x128 marketplace icon, with no dependencies.

    python vscode-extension/tools/make_icon.py            # write media/icon.png
    python vscode-extension/tools/make_icon.py --check     # exit 1 if it has drifted

PACKAGING needs an icon before `vsce package` will publish, and a binary asset
that nobody can regenerate is a liability: three years from now the only way to
change the mark would be to open a paint program and guess. So the icon is
*source* — thirty lines of arithmetic and a hand-rolled PNG writer (zlib and
struct are both stdlib) — and the committed `media/icon.png` is its output. The
`--check` mode is what makes that claim testable: it re-renders into memory and
compares bytes, so an edited PNG that no longer matches this script fails rather
than drifting.

The mark is deliberately two-tone and legible at 16 px, which is the size the
extension actually renders at in the Extensions list: three nodes on the
diagonal, joined by two cables — MLView's whole picture, reduced until only its
shape is left.

Everything is drawn at 4x and box-filtered down, so the circles have smooth
edges while the palette stays two colours plus their blend.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import zlib
from typing import List, Tuple

SIZE = 128
SUPERSAMPLE = 4
#: Deep slate, the same family as the report's dark theme ground.
BACKGROUND = (14, 20, 32)
#: The one accent: nodes and cables.
FOREGROUND = (122, 162, 247)

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(os.path.dirname(HERE), "media", "icon.png")

Point = Tuple[float, float]


def _nodes(scale: int) -> List[Tuple[float, float, float]]:
    """The three node discs as (cx, cy, r), in supersampled pixels."""
    return [
        (30.0 * scale, 94.0 * scale, 15.0 * scale),
        (64.0 * scale, 64.0 * scale, 17.0 * scale),
        (98.0 * scale, 34.0 * scale, 15.0 * scale),
    ]


def _cables(scale: int) -> List[Tuple[Point, Point, float]]:
    """The two cables as (start, end, half-width), in supersampled pixels."""
    half = 5.0 * scale
    return [
        ((30.0 * scale, 94.0 * scale), (64.0 * scale, 64.0 * scale), half),
        ((64.0 * scale, 64.0 * scale), (98.0 * scale, 34.0 * scale), half),
    ]


def _on_segment(px: float, py: float, a: Point, b: Point, half: float) -> bool:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return False
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2 <= half * half


def _coverage() -> List[List[int]]:
    """How many of the SUPERSAMPLE^2 subsamples in each pixel are foreground."""
    scale = SUPERSAMPLE
    big = SIZE * scale
    nodes = _nodes(scale)
    cables = _cables(scale)
    counts = [[0] * SIZE for _ in range(SIZE)]
    for y in range(big):
        py = y + 0.5
        row = counts[y // scale]
        for x in range(big):
            px = x + 0.5
            hit = False
            for cx, cy, r in nodes:
                if (px - cx) ** 2 + (py - cy) ** 2 <= r * r:
                    hit = True
                    break
            if not hit:
                for a, b, half in cables:
                    if _on_segment(px, py, a, b, half):
                        hit = True
                        break
            if hit:
                row[x // scale] += 1
    return counts


def render() -> bytes:
    """The complete PNG file, as bytes."""
    counts = _coverage()
    total = float(SUPERSAMPLE * SUPERSAMPLE)
    raw = bytearray()
    for y in range(SIZE):
        raw.append(0)  # filter type 0 (None) for every row
        row = counts[y]
        for x in range(SIZE):
            alpha = row[x] / total
            for back, front in zip(BACKGROUND, FOREGROUND):
                raw.append(int(round(back + (front - back) * alpha)))
    return _png(bytes(raw), SIZE, SIZE)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def _png(raw: bytes, width: int, height: int) -> bytes:
    """8-bit RGB, no interlace — the simplest PNG a marketplace accepts."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", header),
            _chunk(b"IDAT", zlib.compress(raw, 9)),
            _chunk(b"IEND", b""),
        ]
    )


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="make_icon", description="Render vscode-extension/media/icon.png (128x128)."
    )
    parser.add_argument("--check", action="store_true",
                        help="verify the committed PNG is what this script renders")
    parser.add_argument("--out", default=ICON_PATH, help="where to write (default: media/icon.png)")
    args = parser.parse_args(argv)

    data = render()
    if args.check:
        if not os.path.isfile(args.out):
            print("make_icon: FAIL %s does not exist" % args.out, file=sys.stderr)
            return 1
        with open(args.out, "rb") as fh:
            on_disk = fh.read()
        if on_disk != data:
            print(
                "make_icon: FAIL %s is %d bytes, this script renders %d — "
                "run `python vscode-extension/tools/make_icon.py`"
                % (args.out, len(on_disk), len(data)),
                file=sys.stderr,
            )
            return 1
        print("make_icon: OK %s matches (%d bytes, %dx%d)" % (args.out, len(data), SIZE, SIZE))
        return 0

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(data)
    print("make_icon: wrote %s (%d bytes, %dx%d)" % (args.out, len(data), SIZE, SIZE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
