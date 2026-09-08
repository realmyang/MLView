# shellcheck shell=sh
# Pick the interpreter both sh drivers should use — sourced, never executed.
#
# `python` is the right name on Windows (Git Bash, miniconda) and frequently the
# wrong one everywhere else: most Linux distributions and every macOS since 12.3
# ship `python3` only, so the `PYTHON=${PYTHON:-python}` both drivers used to
# carry fails on the two platforms CI-01 adds. Conversely, on Windows
# `python3.exe` is usually the Microsoft Store app-execution alias, which is not
# an interpreter at all — so the order the candidates are tried in is
# per-platform, not universal, and each candidate has to prove it can report a
# 3.10+ version (`analyzer/pyproject.toml` requires-python) before it is taken.
#
# Sets and exports PYTHON, so `sh scripts/build.sh` called from e2e.sh inherits
# the same interpreter. Returns non-zero with a message on stderr when nothing on
# PATH qualifies. An explicit `PYTHON=/path/to/python sh scripts/e2e.sh` always
# wins — it is checked, never second-guessed.

mlview_python_is_usable() {
  command -v "$1" >/dev/null 2>&1 || return 1
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

mlview_pick_python() {
  if [ -n "$PYTHON" ]; then
    if mlview_python_is_usable "$PYTHON"; then
      export PYTHON
      return 0
    fi
    echo "FAIL: PYTHON=$PYTHON is not a Python 3.10+ interpreter" >&2
    return 1
  fi

  case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*) mlview_python_candidates="python python3 py" ;;
    *)                    mlview_python_candidates="python3 python" ;;
  esac

  for mlview_python_candidate in $mlview_python_candidates; do
    if mlview_python_is_usable "$mlview_python_candidate"; then
      PYTHON=$mlview_python_candidate
      export PYTHON
      return 0
    fi
  done

  echo "FAIL: no Python 3.10+ on PATH (tried: $mlview_python_candidates)" >&2
  echo "      set PYTHON=/path/to/python and re-run" >&2
  return 1
}
