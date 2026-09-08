"""Regenerate `samples/vision_pipeline/expected_issues.json` from a live run.

    PYTHONUTF8=1 python analyzer/tools/gen_expected_issues.py [--check]

`--check` exits 1 when the file on disk differs, which is what a CI step wants.
The file is the machine-checked contract for the sample (CONTRACTS section 7.1):
a canonically sorted list of `{code, severity, file, line}`.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(REPO, "analyzer", "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mlview.api import AnalyzeOptions, analyze_to_dict  # noqa: E402

SAMPLE = os.path.join(REPO, "samples", "vision_pipeline")
TARGET = os.path.join(SAMPLE, "expected_issues.json")


def expected_rows(path: str = SAMPLE):
    """`{code, severity, file, line}` for every issue, canonically sorted."""
    doc = analyze_to_dict(AnalyzeOptions(paths=(path,)))
    rows = [{"code": i["code"], "severity": i["severity"],
             "file": i["loc"]["file"], "line": i["loc"]["line"]}
            for i in doc["issues"]]
    rows.sort(key=lambda r: (r["file"], r["line"], r["code"]))
    return rows


def render(rows) -> str:
    return json.dumps(rows, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the file on disk is out of date")
    args = parser.parse_args(argv)

    rows = expected_rows()
    text = render(rows)
    counts = {"low": 0, "medium": 0, "high": 0}
    for row in rows:
        counts[row["severity"]] += 1
    summary = ("%d issues - %d high / %d medium / %d low, %d distinct codes"
               % (len(rows), counts["high"], counts["medium"], counts["low"],
                  len({r["code"] for r in rows})))

    if args.check:
        current = io.open(TARGET, encoding="utf-8").read() if os.path.exists(TARGET) else ""
        if current != text:
            sys.stderr.write("expected_issues.json is out of date (%s)\n" % summary)
            return 1
        sys.stderr.write("expected_issues.json is current: %s\n" % summary)
        return 0

    io.open(TARGET, "w", encoding="utf-8", newline="\n").write(text)
    sys.stderr.write("wrote %s\n%s\n" % (TARGET.replace("\\", "/"), summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
