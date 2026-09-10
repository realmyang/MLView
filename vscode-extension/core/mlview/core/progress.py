"""NDJSON progress frames (ROADMAP H3).

`analysisProgress` has been fully specified in `vscode-extension/src/protocol.ts`
since the first host landed, with a working `done / total` bar and a per-file
label in `webview/src/ui/states.ts` - and **no host had ever sent one**, so a
445-file workspace showed an indeterminate spinner for 5.6 s.

The core half is one frame per analyzed file, on **stderr**::

    {"t":"progress","done":3,"total":45,"file":"src/train.py"}

Three rules make it safe to turn on unconditionally in a host:

* **stdout is never touched.** stdout purity is a frozen gate
  (`tests/core/test_stdout_purity.py`); progress is a log, and logs go to
  stderr like every other MLView log line.
* **The library never opens the sink itself.** `AnalyzeOptions.progress` is a
  plain callable; `run()` calls it and nothing else. A caller that wants the
  frames on stderr passes `ProgressWriter()`; an in-process host passes its own
  function and no bytes are written anywhere. That is what keeps
  `mlview.api.analyze()` free of I/O.
* **A frame can never break an analysis.** Every call is wrapped: a sink that
  raises is dropped for the rest of the run, silently, because a progress bar
  is not worth an exit code.

Throttling is one frame per `INTERVAL_MS` (50 ms) with a **guaranteed final
frame** at `done == total`, so a consumer always sees 100% exactly once even
when the whole analysis fits inside one interval.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Callable, Optional, TextIO

__all__ = ["ProgressWriter", "INTERVAL_MS", "frame_text", "safe_call"]

#: At most one frame per this many milliseconds, plus the guaranteed final one.
INTERVAL_MS = 50


def frame_text(done: int, total: int, relpath: str) -> str:
    """One NDJSON frame, exactly as CONTRACTS records it - no spaces, key
    order `t, done, total, file`, one trailing newline."""
    payload = {"t": "progress", "done": int(done), "total": int(total),
               "file": str(relpath)}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


class ProgressWriter:
    """A throttled sink writing `frame_text` to a stream (stderr by default).

    Stateful and single-threaded, exactly like the analysis loop that drives
    it. `reset()` exists for tests and for a second `run()` on the same sink.
    """

    def __init__(self, stream: Optional[TextIO] = None,
                 interval_ms: int = INTERVAL_MS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._stream = stream
        self._interval = max(0.0, float(interval_ms) / 1000.0)
        self._clock = clock
        self._last: Optional[float] = None
        self.frames = 0

    def reset(self) -> None:
        self._last = None
        self.frames = 0

    # `run()` calls this once per file.
    def __call__(self, done: int, total: int, relpath: str) -> None:
        now = self._clock()
        final = total > 0 and done >= total
        if not final and self._last is not None and (now - self._last) < self._interval:
            return
        self._last = now
        self.frames += 1
        stream = self._stream if self._stream is not None else sys.stderr
        stream.write(frame_text(done, total, relpath))
        try:
            stream.flush()
        except Exception:  # pragma: no cover - closed stream
            pass


def safe_call(sink: Optional[Callable[..., Any]], done: int, total: int,
              relpath: str) -> Optional[Callable[..., Any]]:
    """Call `sink(done, total, relpath)`; return the sink, or `None` if it
    raised. The caller drops a sink that returned `None`, so one bad frame
    costs one frame and never the analysis."""
    if sink is None:
        return None
    try:
        sink(done, total, relpath)
    except Exception:  # noqa: BLE001 - a progress bar never fails a run
        return None
    return sink
