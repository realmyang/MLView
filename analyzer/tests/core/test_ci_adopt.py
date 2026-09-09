"""CI-ADOPT: change attribution, the baseline ratchet, and their degradation.

The acceptance battery from `docs/ROADMAP.md` NEXT / CI-ADOPT, run against a
real `git init` of `samples/vision_pipeline` rather than a mock, because the
whole feature is a claim about what `git diff` says.

Every failure path is asserted too: no repository, an unknown revision, a
baseline that cannot be read. All three must degrade to *unattributed, showing
everything* with a `config_warning` - never to an error, never to an empty
list. A gate that passes because git was missing is worse than no gate.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from core_support import REPO_ROOT, validate
from mlview import cli
from mlview.adopt import baseline as baseline_mod
from mlview.adopt import gitdiff

SAMPLE_DIR = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
HAS_GIT = shutil.which("git") is not None
needs_git = pytest.mark.skipif(not HAS_GIT, reason="git is not on PATH")

#: Seven lines appended to `train.py` - the audit's own PR fixture.
SEVEN_LINES = ("\n\ndef extra_helper(x):\n"
               "    y = x + 1\n"
               "    z = y * 2\n"
               "    return z\n")

#: A self-contained training step with `step()` before `backward()`. It builds
#: its own optimizer and criterion because MLV203 reads roles, not names, and a
#: bare parameter carries none; `MSELoss` keeps MLV401 (softmax before
#: CrossEntropyLoss, which `SmallCNN.forward` would otherwise trip) out of the
#: way, so the plant is the only new finding.
PLANTED_MLV203 = ("\n\ndef finetune():\n"
                  "    model = SmallCNN()\n"
                  "    model.to(torch.device(DEVICE))\n"
                  "    criterion = nn.MSELoss()\n"
                  "    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)\n"
                  "    for images, labels in train_loader:\n"
                  "        images = images.to(torch.device(DEVICE))\n"
                  "        labels = labels.to(torch.device(DEVICE))\n"
                  "        optimizer.zero_grad()\n"
                  "        logits = model(images)\n"
                  "        loss = criterion(logits, labels)\n"
                  "        optimizer.step()\n"
                  "        loss.backward()\n"
                  "    return model\n")

#: The same loop in the right order but with no `zero_grad()`: a brand new
#: MLV201 beside the one the sample already carries.
PLANTED_MLV201 = PLANTED_MLV203.replace("        optimizer.zero_grad()\n", "") \
                               .replace("        optimizer.step()\n"
                                        "        loss.backward()\n",
                                        "        loss.backward()\n"
                                        "        optimizer.step()\n")


@pytest.fixture
def run(capsysbinary):
    def _run(*argv):
        code = cli.main(list(argv))
        captured = capsysbinary.readouterr()
        return code, captured.out.decode("utf-8", "replace"), \
            captured.err.decode("utf-8", "replace")

    return _run


def _git(root, *args):
    subprocess.run(["git", "-c", "user.email=t@example.invalid",
                    "-c", "user.name=t"] + list(args), cwd=root, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture
def sample_copy(tmp_path):
    """A plain (non-git) copy of `samples/vision_pipeline`."""
    root = tmp_path / "ws"
    shutil.copytree(SAMPLE_DIR, root)
    return str(root)


@pytest.fixture
def pr_fixture(sample_copy):
    """The copy, committed, so `HEAD` is the pre-change state."""
    _git(sample_copy, "init", "-q", ".")
    _git(sample_copy, "add", "-A")
    _git(sample_copy, "commit", "-qm", "base")
    return sample_copy


def _append(root, relpath, text):
    with open(os.path.join(root, relpath), "a", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _codes(stdout):
    return sorted(line.split()[1] for line in stdout.splitlines()
                  if line.strip().startswith(("[!!]", "[!]", "[i]")))


# --------------------------------------------------------------- diff parsing
def test_parse_unified_diff_reads_added_line_ranges():
    diff = ("diff --git a/train.py b/train.py\n"
            "--- a/train.py\n+++ b/train.py\n"
            "@@ -49,0 +50,6 @@ def validate(model):\n"
            "+one\n+two\n+three\n+four\n+five\n+six\n")
    changes = gitdiff.parse_unified_diff(diff, root="/ws")
    assert changes.ok and changes.files == ("train.py",)
    assert changes.added == {"train.py": ((50, 55),)}
    assert changes.added_lines == 6
    assert changes.in_added("train.py", 52)
    assert not changes.in_added("train.py", 49)
    assert changes.is_changed("train.py") and not changes.is_changed("data.py")


def test_a_pure_deletion_changes_the_file_but_adds_no_lines():
    diff = ("diff --git a/train.py b/train.py\n"
            "--- a/train.py\n+++ b/train.py\n"
            "@@ -32 +31,0 @@\n-    loss.backward()\n")
    changes = gitdiff.parse_unified_diff(diff, root="/ws")
    assert changes.files == ("train.py",)
    assert changes.added == {}                 # nothing to attribute a line to
    assert not changes.in_added("train.py", 32)


def test_a_deleted_file_contributes_nothing():
    diff = ("diff --git a/gone.py b/gone.py\n"
            "--- a/gone.py\n+++ /dev/null\n@@ -1,3 +0,0 @@\n-a\n-b\n-c\n")
    changes = gitdiff.parse_unified_diff(diff, root="/ws")
    assert changes.files == ()


def test_a_rename_is_the_new_path_and_is_not_all_new():
    diff = ("diff --git a/old.py b/new.py\nsimilarity index 100%\n"
            "rename from old.py\nrename to new.py\n")
    changes = gitdiff.parse_unified_diff(diff, root="/ws")
    assert changes.files == ("new.py",)
    assert changes.added == {}, "-M means a moved file is not 15 new findings"


def test_a_hidden_directory_keeps_its_leading_dot():
    diff = ("+++ b/.github/workflows/ci.yml\n@@ -0,0 +1,2 @@\n+a\n+b\n")
    changes = gitdiff.parse_unified_diff(diff, root="/ws")
    assert changes.files == (".github/workflows/ci.yml",)


def test_changed_paths_accepts_a_bare_path_list(tmp_path):
    listing = tmp_path / "changed.txt"
    listing.write_text("# what the runner knows\ntrain.py\ndata.py\n", encoding="utf-8")
    changes = gitdiff.changed_from_file(str(listing), root=str(tmp_path))
    assert changes.ok and changes.files == ("data.py", "train.py")
    assert changes.hunks_known is False
    assert not changes.in_added("train.py", 3), "no hunks means no line is 'new'"


def test_changed_paths_accepts_a_diff_the_runner_already_has(tmp_path):
    listing = tmp_path / "pr.diff"
    listing.write_text("+++ b/train.py\n@@ -0,0 +1,2 @@\n+a\n+b\n", encoding="utf-8")
    changes = gitdiff.changed_from_file(str(listing), root=str(tmp_path))
    assert changes.hunks_known is True and changes.in_added("train.py", 2)


def test_an_unreadable_changed_paths_file_degrades(tmp_path):
    changes = gitdiff.changed_from_file(str(tmp_path / "nope.txt"), root=str(tmp_path))
    assert changes.ok is False and "cannot read" in changes.reason


# ------------------------------------------------------------- degradation
def test_a_non_git_directory_reports_everything_with_a_diagnostic(run, sample_copy):
    plain, _out, _err = run("issues", sample_copy)
    code, out, _err = run("issues", sample_copy, "--changed-since", "HEAD",
                          "--changed-only")
    assert code == 0 and plain == 0
    assert out.startswith("15 issue(s)"), "never an empty list, never an error"

    code, payload, _err = run("analyze", sample_copy, "--json", "-",
                              "--changed-since", "HEAD", "--changed-only")
    doc = json.loads(payload)
    assert code == 0 and len(doc["issues"]) == 15
    assert all("change" not in i for i in doc["issues"]), "unattributed, not 'existing'"
    warnings = [d["message"] for d in doc["diagnostics"] if d["kind"] == "config_warning"]
    assert any("change attribution is unavailable" in m for m in warnings)
    assert any("--changed-only had no effect" in m for m in warnings)
    assert validate(doc) == []


@needs_git
def test_an_unknown_revision_degrades_the_same_way(run, pr_fixture):
    code, payload, _err = run("analyze", pr_fixture, "--json", "-",
                              "--changed-since", "no-such-ref")
    doc = json.loads(payload)
    assert code == 0 and len(doc["issues"]) == 15
    assert any("is unknown to git" in d["message"] for d in doc["diagnostics"])


def test_changed_only_without_a_source_is_a_usage_error(run, sample_copy):
    code, out, err = run("issues", sample_copy, "--changed-only")
    assert code == 1 and out == "", "stdout stays clean on a usage error"
    assert "--changed-only needs a change source" in err


def test_two_change_sources_at_once_is_a_usage_error(run, sample_copy):
    code, _out, err = run("issues", sample_copy, "--changed-since", "HEAD",
                          "--changed-paths", "x.txt")
    assert code == 1 and "pass one" in err


# --------------------------------------------------------------- acceptance
@needs_git
def test_the_pr_fixture_shows_fifteen_findings_and_none_of_them_changed(run, pr_fixture):
    _append(pr_fixture, "train.py", SEVEN_LINES)
    code, out, _err = run("issues", pr_fixture)
    assert code == 0 and out.startswith("15 issue(s)")

    code, out, _err = run("issues", pr_fixture, "--changed-since", "HEAD",
                          "--changed-only")
    assert code == 0, "no findings on the change means exit 0"
    # HOST-4: never a bare "none found" while findings were set aside.
    assert out.startswith("0 issue(s)") and "not shown" in out
    assert "none found" not in out and "do not touch the change" in out
    assert "Notes (" in out


@needs_git
def test_every_issue_is_classified_and_the_classes_are_honest(run, pr_fixture):
    _append(pr_fixture, "train.py", SEVEN_LINES)
    _code, payload, _err = run("analyze", pr_fixture, "--json", "-",
                               "--changed-since", "HEAD")
    doc = json.loads(payload)
    assert len(doc["issues"]) == 15, "the WHOLE workspace is still analyzed"
    classes = {i["id"]: i["change"] for i in doc["issues"]}
    assert set(classes.values()) == {"touched", "existing"}
    # train.py changed but not on any finding's line; nothing else changed.
    for issue in doc["issues"]:
        expected = "touched" if issue["loc"]["file"] == "train.py" else "existing"
        assert classes[issue["id"]] == expected, issue["code"]
    assert validate(doc) == []


@needs_git
def test_a_planted_mlv203_inside_the_hunk_is_the_only_finding(run, pr_fixture):
    _append(pr_fixture, "train.py", PLANTED_MLV203)
    code, out, _err = run("issues", pr_fixture, "--changed-since", "HEAD",
                          "--changed-only")
    assert code == 0
    assert out.startswith("1 issue(s)") and _codes(out) == ["MLV203"]

    code, _out, _err = run("issues", pr_fixture, "--changed-since", "HEAD",
                           "--changed-only", "--fail-on", "high")
    assert code == 2, "the plant is high severity and it is inside the hunk"


@needs_git
def test_a_related_loc_inside_a_hunk_is_touched_and_never_dropped(run, pr_fixture):
    """The upstream-leak case the three-value enum exists for.

    Swapping `loss.backward()` and `optimizer.step()` moves `backward()` into
    an added hunk while git matches the unchanged `step()` line. Neither
    finding's own line is inside the hunk - MLV203 anchors on `step()`, MLV201
    on the `for` statement - so both are `touched` **by evidence**, and
    `--changed-only` keeps both. Dropping them would lose the very defect the
    diff introduced.
    """
    path = os.path.join(pr_fixture, "train.py")
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    source = source.replace("            loss.backward()\n            optimizer.step()\n",
                            "            optimizer.step()\n            loss.backward()\n")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(source)
    _code, payload, _err = run("analyze", pr_fixture, "--json", "-",
                               "--changed-since", "HEAD", "--changed-only")
    doc = json.loads(payload)
    kept = {i["code"]: i["change"] for i in doc["issues"]}
    assert kept == {"MLV201": "touched", "MLV203": "touched"}
    assert validate(doc) == [], "dropping issues must leave a valid document"


@needs_git
def test_changed_only_leaves_no_orphan_ghost_behind(run, pr_fixture):
    """Invariant 1.1.8: dropping the only finding a ghost carried drops the
    ghost too, or the document stops validating."""
    _append(pr_fixture, "train.py", SEVEN_LINES)
    _code, payload, _err = run("analyze", pr_fixture, "--json", "-",
                               "--changed-since", "HEAD", "--changed-only")
    doc = json.loads(payload)
    assert doc["issues"] == []
    assert [n for n in doc["nodes"] if n["ghost"]] == []
    assert validate(doc) == []


# ----------------------------------------------------------------- baseline
def test_snippet_hash_is_whitespace_normalised():
    assert baseline_mod.snippet_hash("    loss = crit(x, y)") == \
        baseline_mod.snippet_hash("loss  =  crit(x,\ty)".replace(",\t", ", "))
    assert baseline_mod.snippet_hash("a = 1") != baseline_mod.snippet_hash("a = 2")
    assert len(baseline_mod.snippet_hash("x")) == 12


def test_baseline_write_then_issues_reports_zero_unsuppressed(run, sample_copy, tmp_path):
    out_path = str(tmp_path / "baseline.json")
    code, out, err = run("baseline", "write", sample_copy, "--out", out_path)
    assert code == 0 and out == "", "the payload is the file, not stdout"
    assert "15 entry/entries" in err

    code, out, _err = run("issues", sample_copy, "--baseline", out_path)
    assert code == 0
    assert out.startswith("0 issue(s)") and "· 15 baselined" in out

    code, _out, _err = run("issues", sample_copy, "--baseline", out_path,
                           "--fail-on", "high")
    assert code == 0, "a baselined finding does not trip the gate"


def test_a_baselined_issue_is_marked_not_deleted(run, sample_copy, tmp_path):
    out_path = str(tmp_path / "baseline.json")
    run("baseline", "write", sample_copy, "--out", out_path)
    _code, payload, _err = run("analyze", sample_copy, "--json", "-",
                               "--baseline", out_path)
    doc = json.loads(payload)
    assert len(doc["issues"]) == 15
    assert all(i["baselined"] is True for i in doc["issues"])
    assert doc["stats"]["issues"] == {"low": 4, "medium": 6, "high": 5}, \
        "stats keeps the project-level truth; the renderer nets it out"
    assert validate(doc) == []

    _code, shown, _err = run("issues", sample_copy, "--baseline", out_path,
                             "--show-suppressed")
    assert shown.startswith("15 issue(s)")


@needs_git
def test_the_summary_table_marks_a_baselined_row_the_way_it_marks_a_suppressed_one(
        run, sample_copy, tmp_path):
    """VW-11: with `--show-suppressed` the header netted six findings out of a
    table that then listed all fifteen, and a baselined row carried no marker
    while a suppressed one did - so one command's output stated two numbers and
    a reader could not tell which rows were already accepted."""
    out_path = str(tmp_path / "baseline.json")
    run("baseline", "write", sample_copy, "--out", out_path)
    with open(out_path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["entries"] = data["entries"][:6]
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)

    _code, out, _err = run("analyze", sample_copy, "--baseline", out_path,
                           "--format", "summary", "--show-suppressed")
    heading = [line for line in out.splitlines() if line.startswith("Issues (")]
    assert heading == ["Issues (9 · 6 baselined)"], heading
    rows = [line for line in out.splitlines() if line.strip().startswith(("[!!]", "[!]", "[i]"))]
    assert len(rows) == 15
    assert sum(1 for r in rows if "(baselined)" in r) == 6, rows

    # ...and without --show-suppressed the table is the net nine, unmarked.
    _code, net, _err = run("analyze", sample_copy, "--baseline", out_path,
                           "--format", "summary")
    assert [l for l in net.splitlines() if l.startswith("Issues (")] == ["Issues (9)"]
    assert "(baselined)" not in net


def test_a_new_finding_after_a_baseline_exits_2_with_exactly_it(run, sample_copy, tmp_path):
    out_path = str(tmp_path / "baseline.json")
    run("baseline", "write", sample_copy, "--out", out_path)
    _append(sample_copy, "train.py", PLANTED_MLV201)

    code, out, _err = run("issues", sample_copy, "--baseline", out_path)
    assert code == 0
    assert out.startswith("1 issue(s)") and _codes(out) == ["MLV201"]
    assert "· 15 baselined" in out

    code, _out, _err = run("issues", sample_copy, "--baseline", out_path,
                           "--fail-on", "high")
    assert code == 2, "the new finding is not in the baseline, so the gate trips"


def test_matching_is_counted_so_a_copied_finding_is_not_pre_forgiven(sample_copy, tmp_path):
    """Two textually identical findings share one key; one entry forgives one."""
    from mlview.api import AnalyzeOptions, analyze

    graph = analyze(AnalyzeOptions(paths=(sample_copy,)))
    doc = baseline_mod.build_baseline(graph)
    key_rows = [e for e in doc["entries"] if e["code"] == "MLV201"]
    assert len(key_rows) == 1

    _append(sample_copy, "train.py", PLANTED_MLV201)
    graph = analyze(AnalyzeOptions(paths=(sample_copy,)))
    mlv201 = [i for i in graph.issues if i.code == "MLV201"]
    assert len(mlv201) == 2
    baseline_mod.apply_baseline(graph, doc["entries"], "b.json")
    assert [i.baselined for i in mlv201] == [True, False]


def test_a_stale_baseline_entry_is_reported_not_silently_permissive(sample_copy, tmp_path):
    from mlview.api import AnalyzeOptions, analyze

    graph = analyze(AnalyzeOptions(paths=(sample_copy,)))
    entries = baseline_mod.build_baseline(graph)["entries"] + [
        {"code": "MLV999", "symbol": "gone", "snippetHash": "0" * 12,
         "file": "gone.py", "line": 1, "title": "stale"}]
    diagnostics = baseline_mod.apply_baseline(graph, entries, "b.json")
    messages = [d.message for d in diagnostics]
    assert any(m.startswith("1 baseline entries no longer match") for m in messages)


def test_an_unreadable_baseline_reports_everything(run, sample_copy, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    code, out, _err = run("issues", sample_copy, "--baseline", str(bad))
    assert code == 0 and out.startswith("15 issue(s)"), "fail open, loudly"

    _code, payload, _err = run("analyze", sample_copy, "--json", "-",
                               "--baseline", str(bad))
    doc = json.loads(payload)
    assert any("baseline ignored" in d["message"] for d in doc["diagnostics"])


def test_the_baseline_document_is_byte_deterministic(sample_copy, tmp_path):
    from mlview.api import AnalyzeOptions, analyze

    graph = analyze(AnalyzeOptions(paths=(sample_copy,)))
    first = baseline_mod.write_baseline(graph, str(tmp_path / "a.json"))
    second = baseline_mod.write_baseline(graph, str(tmp_path / "b.json"))
    with open(first, "rb") as fh_a, open(second, "rb") as fh_b:
        assert fh_a.read() == fh_b.read()
    assert "createdAt" not in open(first, encoding="utf-8").read(), \
        "a committed file must not churn on a re-run"


# ------------------------------- HOST-1: notebooks are a PR's content too
NOTEBOOK_FIXTURE = os.path.join(REPO_ROOT, "analyzer", "tests", "fixtures",
                                "notebooks", "leak.ipynb")


@pytest.fixture
def notebook_pr(tmp_path):
    """A repository whose pull request is one leaky notebook, and nothing else."""
    root = str(tmp_path / "nbpr")
    os.makedirs(root)
    with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as fh:
        fh.write(".mlview/\n")
    with open(os.path.join(root, "readme.py"), "w", encoding="utf-8") as fh:
        fh.write("X = 1\n")
    _git(root, "init", "-q", ".")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    shutil.copyfile(NOTEBOOK_FIXTURE, os.path.join(root, "leak.ipynb"))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "PR: add a leaky notebook")
    return root


@needs_git
def test_a_pull_request_that_adds_a_leaky_notebook_fails_its_gate(run, notebook_pr):
    """The intersection of NB and CI-ADOPT that no single item owned. A
    notebook finding's `loc.file` is the generated module (11.29 N5), a path
    git has never seen, so `--changed-only` - the default of BOTH shipped CI
    surfaces - dropped every one of them and the gate came back green on a
    pull request whose entire content was a fit-before-split notebook."""
    code, out, _err = run("issues", notebook_pr, "--include-notebooks")
    assert code == 0 and out.startswith("2 issue(s)"), out

    code, payload, _err = run("analyze", notebook_pr, "--json", "-",
                              "--include-notebooks", "--changed-since", "HEAD~1")
    doc = json.loads(payload)
    assert [i["change"] for i in doc["issues"]] == ["new", "new"], doc["issues"]
    assert all(i["loc"]["file"].startswith(".mlview/notebooks/") for i in doc["issues"])
    assert any("generated notebook module" in d["message"]
               for d in doc["diagnostics"]), doc["diagnostics"]

    code, out, _err = run("issues", notebook_pr, "--include-notebooks",
                          "--changed-since", "HEAD~1", "--changed-only",
                          "--fail-on", "high")
    assert code == cli.EXIT_FAIL_ON, out
    assert _codes(out) == ["MLV101", "MLV201"], out


@needs_git
def test_a_notebook_nobody_touched_stays_existing(run, notebook_pr):
    """The other direction: the same notebook one commit later is not new."""
    _append(notebook_pr, "readme.py", "Y = 2\n")
    _git(notebook_pr, "add", "-A")
    _git(notebook_pr, "commit", "-qm", "unrelated")
    code, payload, _err = run("analyze", notebook_pr, "--json", "-",
                              "--include-notebooks", "--changed-since", "HEAD~1")
    doc = json.loads(payload)
    assert {i["change"] for i in doc["issues"]} == {"existing"}, doc["issues"]
