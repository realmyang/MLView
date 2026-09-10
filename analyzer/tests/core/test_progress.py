"""H3: `--progress-json` NDJSON frames on stderr.

`analysisProgress` has been specified in `protocol.ts` and rendered by
`webview/src/ui/states.ts` since the first host shipped, and no host had ever
sent one. Three things are asserted here and nothing else matters: the frame
shape is exactly what the host parses, **stdout is untouched**, and the last
frame always arrives even when the whole analysis fits inside one throttle
interval.
"""

from __future__ import annotations

import io
import json
import os

import pytest

from core_support import REPO_ROOT
from mlview import cli
from mlview.api import AnalyzeOptions, analyze
from mlview.core.progress import INTERVAL_MS, ProgressWriter, frame_text, safe_call

SAMPLE_DIR = os.path.join(REPO_ROOT, "samples", "vision_pipeline")

TINY = {"a.py": "A = 1\n", "b.py": "B = 2\n", "c.py": "C = 3\n"}


class Clock:
    """A hand-cranked monotonic clock, so the throttle is tested and not raced."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance_ms(self, milliseconds: float) -> None:
        self.now += milliseconds / 1000.0


def _frames(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# ------------------------------------------------------------------ the frame
def test_the_frame_is_exactly_what_the_host_parses():
    line = frame_text(3, 45, "src/train.py")
    assert line == '{"t":"progress","done":3,"total":45,"file":"src/train.py"}\n'
    assert list(json.loads(line)) == ["t", "done", "total", "file"]


def test_frames_are_throttled_to_one_per_interval():
    clock = Clock()
    stream = io.StringIO()
    writer = ProgressWriter(stream=stream, clock=clock)
    for done in range(1, 10):
        writer(done, 100, "f%d.py" % done)
        clock.advance_ms(INTERVAL_MS / 5.0)
    frames = _frames(stream.getvalue())
    assert [f["done"] for f in frames] == [1, 6], "one frame per 50 ms, no more"


def test_the_final_frame_is_guaranteed_even_inside_one_interval():
    clock = Clock()
    stream = io.StringIO()
    writer = ProgressWriter(stream=stream, clock=clock)
    writer(1, 3, "a.py")
    writer(2, 3, "b.py")        # throttled away
    writer(3, 3, "c.py")        # final: never throttled
    frames = _frames(stream.getvalue())
    assert [f["done"] for f in frames] == [1, 3]
    assert frames[-1] == {"t": "progress", "done": 3, "total": 3, "file": "c.py"}


def test_a_sink_that_raises_costs_one_frame_and_not_the_analysis():
    def angry(_done, _total, _file):
        raise RuntimeError("no")

    assert safe_call(angry, 1, 2, "a.py") is None
    assert safe_call(None, 1, 2, "a.py") is None


# ------------------------------------------------------------------ the loop
def test_the_pipeline_calls_the_sink_once_per_file(make_workspace):
    seen = []
    root = make_workspace(TINY)
    analyze(AnalyzeOptions(paths=(root,), progress=lambda *args: seen.append(args)))
    assert [done for done, _total, _file in seen] == [1, 2, 3]
    assert {total for _done, total, _file in seen} == {3}
    assert sorted(relpath for _d, _t, relpath in seen) == ["a.py", "b.py", "c.py"]


def test_a_broken_sink_never_reaches_the_caller(make_workspace):
    calls = []

    def angry(done, _total, _file):
        calls.append(done)
        raise RuntimeError("no")

    root = make_workspace(TINY)
    graph = analyze(AnalyzeOptions(paths=(root,), progress=angry))
    assert calls == [1], "dropped after the first failure"
    assert graph.filesAnalyzed == 3


def test_analysis_without_the_flag_emits_nothing(make_workspace, capsys):
    root = make_workspace(TINY)
    analyze(AnalyzeOptions(paths=(root,)))
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


# ------------------------------------------------------------------- the CLI
@pytest.fixture
def run(capsysbinary):
    def _run(*argv):
        code = cli.main(list(argv))
        captured = capsysbinary.readouterr()
        return code, captured.out, captured.err.decode("utf-8", "replace")

    return _run


def test_progress_json_writes_frames_to_stderr_and_leaves_stdout_pure(run):
    code, out, err = run("analyze", SAMPLE_DIR, "--json", "-", "--progress-json")
    assert code == 0
    document = json.loads(out.decode("utf-8"))       # stdout is still ONLY the graph
    assert document["stats"]["nodes"] > 0
    frames = _frames("\n".join(line for line in err.splitlines()
                              if line.startswith('{"t":"progress"')))
    assert frames, "at least one frame"
    assert frames[-1]["done"] == frames[-1]["total"] == 5
    for frame in frames:
        assert set(frame) == {"t", "done", "total", "file"}
        assert not os.path.isabs(frame["file"])


def test_without_the_flag_stderr_carries_no_frames(run):
    _code, _out, err = run("analyze", SAMPLE_DIR, "--json", "-")
    assert '{"t":"progress"' not in err
