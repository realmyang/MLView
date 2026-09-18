> Historical record: the static analyzer was removed on 2026-09-18.
> Commands, paths, and compatibility promises below describe earlier revisions.
> See [current status](STATUS.md) for the supported product.

# Adding a rule, and adding a corpus program

The narrow version of [`CONTRIBUTING.md`](../CONTRIBUTING.md), for the two
contributions most people want to make: teaching MLView to find one more
defect, and giving it one more program to be measured on.

Read the first half even if you only want the second. The corpus is where a
rule's precision is proved, and a rule with no corpus program is a claim with
no evidence behind it.

---

## 0 · Before you write a rule

MLView has **36 rules** and holds **100% precision on every one of them**. That
number is the product, and it is also the constraint: a new rule that finds two
real defects and one thing that was never wrong makes MLView worse, because it
converts every future finding into something a user has to double-check.

So the first question is not "can I detect this?" but **"can I detect this
without ever being wrong about it?"** Three things make that answerable:

* **It has to be decidable from the source text.** MLView never imports,
  executes or evaluates the code it reads. A rule cannot ask for a tensor
  shape, a runtime type or an installed framework's behaviour.
* **It needs a nearest-miss.** Before writing the rule, write down the most
  similar piece of *correct* code you can think of. If you cannot separate the
  two statically, the rule is not ready — and that nearest miss is going to
  become the `_good.py` fixture anyway.
* **An absence is the hard case.** "There is no `zero_grad()` here" is only
  true if you looked everywhere it could be: the enclosing loops, the enclosing
  function, a followed callee, a framework wrapper that does it for you. Rules
  that assert an absence declare `absence=True`, which turns on the severity
  cap and the `negation_absent` evidence gate — and they are where nearly every
  historical false positive came from.

The catalogue of existing rules and the reasoning behind their codes and
severities is [`docs/ISSUE_RULES.md`](ISSUE_RULES.md); its §5 is the authoring
checklist, and `analyzer/tests/rules/test_registry_complete.py` enforces the
first six boxes mechanically.

---

## 1 · The two fixtures

Every rule ships exactly two fixture files, and they are written **first**.
Neither is ever imported or executed; they are parsed, exactly like any
analyzed workspace.

### `analyzer/tests/fixtures/rules/<CODE>_bad.py`

Self-describing: one `# MLVIEW-EXPECT:` line per issue the rule must raise, in
the first comment block.

```python
# MLVIEW-EXPECT: MLV201 line=21 confidence>=0.6
"""Batch loop with backward() and step() but never zero_grad().

Never executed: MLView analyses this file statically.
"""
```

Recognised fields — only `<CODE>` is required, and anything you leave out is
not asserted:

| Field | Means |
|---|---|
| `line=<n>` | the finding's primary line |
| `confidence>=<f>` | also `>`, `<=`, `<`, `==` |
| `severity=<low\|medium\|high>` | |
| `bucket=<certain\|likely\|possible\|speculative>` | |
| `suppressed=<true\|false>` | |
| `ghost=<true\|false>` | the issue owns a ghost node (a required-but-absent step) |
| `file=<relpath>` | for a multi-file fixture directory |

### `analyzer/tests/fixtures/rules/<CODE>_good.py`

Headed by `# MLVIEW-EXPECT-NONE: <CODE>`, and it is **the nearest
false-positive trap, not merely correct code**. MLV201's is gradient
accumulation with `zero_grad()` under an `if step % 4 == 0` — the call is
there, just guarded. That is the bar: correct code that looks as much like the
defect as you can make it.

This matters more than it looks, because of
`analyzer/tests/rules/test_no_cross_fire.py`: the union of *every* `_good.py`
fixture is analyzed as one workspace and must be completely silent. Twenty
near-miss programs in one workspace are twenty adversarial inputs for every
other rule at once, and it is the cheapest precision gate in the tree and the
one that catches the most regressions.

The harness is `analyzer/tests/rules/rule_harness.py`; `analyze_fixture` and
`assert_fixture` do the work, and nothing needs changing to accept a new pair.

---

## 2 · The rule itself

Rules live in `analyzer/src/mlview/rules/r_*.py`, one module per family; the
registry imports every `r_*.py` once, sorted by filename, and each
`@rule`-decorated function registers a `RuleSpec`.

```python
@rule(code="MLV201", severity="high", base_prior=0.90, frameworks=["torch"],
      rule_version=1, tags=["correctness", "train-loop"], absence=True,
      title="Gradients are never zeroed",
      why="Accumulated gradients make each update the sum of all previous batches, "
          "so training diverges or converges to the wrong place - silently.",
      fix_hint="Call optimizer.zero_grad(set_to_none=True) as the first statement of "
               "the training step, before the forward pass.")
def missing_zero_grad(ctx) -> Iterable[Issue]:
    ...
```

Four things the checklist will hold you to, and that reviewers care about most:

* **`message` cites concrete evidence** — variable names and line numbers, not
  a restatement of the title. "The batch loop at `train.py:21` calls
  `loss.backward()` (line 24) and `optimizer.step()` (line 25) but never
  `zero_grad()`" is the register.
* **`why` is the consequence, in ML terms, in one sentence.** Not "this
  violates a convention" but what goes wrong with the model.
* **`fix_hint` names the actual API**, in one actionable sentence.
* **`relatedLocs` carry a named role** from the closed set (`split_site`,
  `fit_site`, `backward_site`, `optimizer_site`, `step_site`, `eval_loop`,
  `final_layer`, `definition`, `call_site`, `construction`). They drive the
  on-canvas connectors and VS Code's related information.

Evidence is a list of `(kind, detail, weight)` from the nine frozen
`Evidence.kind` values; the engine turns it into the confidence and the bucket.
Claiming an evidence kind you do not have — `scope_static` for a scope that is
not static — is the kind of small lie the whole design exists to prevent.

If the rule can offer a structured fix, `analyzer/src/mlview/rules/fixes.py` is
where it goes, and `analyzer/tests/rules/test_fixes.py` will apply your edit to
the bad fixture, re-parse the result, and assert **the rule stops firing**.

### Register it in the test tuples

`analyzer/tests/rules/test_all_rules.py` carries `PROTOTYPE_CODES` and
`TIER_CODES`, and asserts the registry is exactly their union — so a rule that
silently vanishes fails a test rather than quietly disappearing. A new code
goes in one of those tuples, with its per-rule assertions in
`test_all_rules.py` or `test_tier_rules.py`.

---

## 3 · The generated rule page

`docs/rules/<CODE>.md` is **generated, never hand-edited**: the title,
severity, frameworks, prior, tags, fix hint and the bad/good examples all come
from the `@rule` declaration and the two fixtures, so a page cannot drift from
the rule it documents. Every `Issue.docs` field points at it and both hosts
deep-link to it offline.

```sh
python analyzer/tools/gen_rule_docs.py            # write the pages and the index
python analyzer/tools/gen_rule_docs.py --check    # the gate: exits 1 on any drift
```

The one hand-written half is the per-rule prose — what the gate actually keys
on, and what the `_good.py` fixture proves is *not* a finding. It is data, in
`analyzer/tools/gen_rule_notes.py` for the MLV1xx/MLV2xx pipeline rules and
`analyzer/tools/gen_rule_notes_eval.py` for MLV3xx and up. Anything missing
falls back to the declaration text, so a new rule still gets a usable page
without touching either file — but a rule with a real blind spot should say so
there, in the optional **What it cannot analyze** section, because that section
is what makes a limitation reportable instead of surprising.

The extension carries its own copy of these pages; `npm run compile` in
`vscode-extension` re-syncs them, and the sync has a `--check` of its own.

---

## 4 · Run the gates

```sh
python -m pytest analyzer/tests/rules -q      # your fixtures, the checklist, cross-fire
python -m pytest analyzer/tests -q            # everything, including the clean corpus
python analyzer/tools/gen_rule_docs.py --check
python analyzer/tools/gen_expected_issues.py --check   # if it fires on the shipped sample
```

Two of those deserve names, because they are the precision gates:

* `analyzer/tests/rules/test_precision.py` analyzes `analyzer/tests/clean/` —
  six idiomatic, correct programs (the textbook loop, AMP with gradient
  accumulation, a `LightningModule`, a HuggingFace `Trainer` run, a
  scikit-learn `Pipeline` + `GridSearchCV`, a `TimeSeriesSplit` walk-forward
  forecast) — together *and* one at a time, and holds the whole rule set to **0
  high and at most 2 medium** across all of them.
* `analyzer/tests/rules/test_rule_robustness.py` runs every rule over
  deliberately awkward but valid Python and asserts the diagnostic channel is
  empty. A rule that raises becomes a `rule_error` diagnostic rather than a
  crash, which means a broken rule is *invisible* in normal use; this is what
  makes it visible.

---

## 5 · Adding a program to the labelled corpus

`analyzer/tests/accuracy/corpus/` is 158 labelled programs. A program is a
directory with its sources and a `labels.json` beside them; a couple of entries
are label files alone, pointing at a shipped sample through a `root` key so the
corpus never forks a second copy of the demo.

```json
{
  "name": "gbm_tabular",
  "title": "An XGBoost tabular baseline with no torch anywhere",
  "origin": "the GBM script the ROADMAP's ANA-12 entry asks the corpus to contain",
  "tuned": false,
  "labelledBy": "ANA-12, 2026-09-08",
  "expected": [
    {
      "code": "MLV101",
      "file": "train.py",
      "line": 25,
      "symbol": "encoder.fit_transform",
      "severity": "high",
      "verdict": "expected",
      "defect": "the ordinal encoder is fitted on the whole frame seven lines before the split",
      "why": "category codes are assigned from the held-out rows as well, so an unseen category is never unseen"
    }
  ],
  "forbidden": [
    {
      "code": "MLV201",
      "file": "train.py",
      "why": "there is no torch in this project and no hand-written gradient step to zero"
    }
  ],
  "graph": {
    "edges": 9,
    "ops": [
      {"file": "train.py", "line": 22, "symbol": "read_csv", "kind": "dataset"},
      {"file": "train.py", "line": 32, "symbol": "train_test_split", "kind": "split"}
    ]
  }
}
```

**The three verdicts.** A row in `expected[]` carries `"verdict": "expected"`
(a defect planted on purpose — firing on it is a true positive, missing it
moves recall) or `"verdict": "acceptable"` (MLView may reasonably go either
way; scored neither as a hit nor as a false positive). Rows in `forbidden[]`
are findings that would be **wrong**, and every one **must** say why — the
loader refuses a corpus where one does not. Any forbidden hit is a hard
failure, regardless of the baseline.

**Label exhaustively.** An unsuppressed finding that satisfies no label at all
counts as a false positive. That is deliberate — `acceptable` is how a
legitimate-but-unplanted observation is expressed, and a new rule that starts
firing on an existing program needs a *label*, not an exemption.

**Anchors.** A label matches on its code, then on `line` (any of the finding's
locations — `loc` or a `relatedLoc` — spanning that line), or `file`, or
`project` for a whole-workspace claim like MLV601. One finding satisfies at
most one label, and `expected` is assigned first, so a broad file-level
`forbidden` never steals a legitimate hit.

**The graph block** is the small hand-drawn expectation: the ops a person
sketching that pipeline on a whiteboard would draw. An op counts as recovered
only when a node is anchored on **that exact line** — containment would score
an op as recovered merely because the function that should have held it exists,
which is exactly the blind spot this measures.

**`tuned`** means the rules were developed against this program, so its numbers
are a ceiling rather than a measurement. A new program is `false` unless you
wrote a rule against it, and every headline in `docs/ACCURACY.md` is quoted
twice — whole corpus, and unseen-only — for this reason. Write it as a
defective / correct **pair** wherever you can: a clean twin is the strongest
false-positive trap there is.

The corpus lints itself in `analyzer/tests/accuracy/test_accuracy.py`: every
labelled line must exist in the file it names and be inside it, every labelled
code must be a registered rule, every expected label needs a `severity` and a
`defect`, and every forbidden label needs a `why`.

### Measuring it

```sh
python tools/accuracy.py --program <name> --no-gate --verbose   # just yours
python tools/accuracy.py                                        # ip, the default
python tools/accuracy.py --dataflow local                       # the opt-out mode
```

Both modes are gated, against `analyzer/tests/accuracy/baseline.ip.json` and
`analyzer/tests/accuracy/baseline.json` respectively; they are two different
analyses and one ratchet cannot gate both. The three gates are: **zero
`forbidden` findings, ever** (no flag suppresses it), **recall may only ratchet
up** (overall, unseen-only and per rule, in all three readings), and **graph
fidelity may only ratchet up**. Precision is not on that list because it is not
a ratchet: it is 100% and stays 100%.

Adding programs moves the denominator, so a corpus contribution usually needs a
re-recorded baseline:

```sh
python tools/accuracy.py --update-baseline
```

That refuses to run from a `--program` subset, refuses to write while a
forbidden finding fires, prints the before/after of every gated number that
moved either way, and exits `3` if any moved **down**. If your new programs
contain defects MLView genuinely misses — which is the point of adding them —
a headline can legitimately fall, and recording that takes
`--allow-regression "<reason>"`. The reason is written into the baseline's own
`note` field, so the file says why it went backwards. Do both modes.

---

## 6 · The public-repository check

Whenever you change **what a rule fires on**, run the corpus of real
third-party code as well — 37 repositories pinned to exact commits, which
nobody wrote for MLView:

```sh
python tools/public_corpus.py fetch                        # once, ~1.9 GB, network
python tools/public_corpus.py run   --out report.json
python tools/public_corpus.py check --report report.json --strict
```

A new high-severity finding fails the gate until a human has read the code and
recorded a verdict in `analyzer/tests/public_corpus/adjudication.json`, keyed
by `repo|CODE|repo-relative file|symbol`:

```json
"yolov5|MLV402|utils/loss.py|self.loss_fcn": {
  "verdict": "false-positive",
  "state": "fixed",
  "severity": "high",
  "where": "utils/loss.py:26 in BCEBlurWithLogitsLoss.forward (yolov5 @ 35b48237)",
  "why": "…the actual reading of the code, in full…"
}
```

`verdict` is `true-positive`, `false-positive` or `unsure`, and **every verdict
must cite why** — the loader refuses one that does not. A `false-positive`
carries a `state`: `open` means the analyzer still produces it (listed, and
fatal only under `--strict`), `fixed` means it must never come back. Under
`--strict`, an adjudicated false positive that has *gone away* also fails, so
the record cannot go stale in either direction. One file is the review record,
the open list and the regression ratchet at once.

This is the only gate that can see a false positive nobody thought to label. If
your rule produces one here, that is the gate working, and the finding belongs
in the labelled corpus as a `forbidden` label once you have fixed it.

---

## 7 · The checklist, condensed

- [ ] The nearest correct code is written down, and it is `<CODE>_good.py`.
- [ ] `<CODE>_bad.py` carries a `# MLVIEW-EXPECT:` line per issue; `<CODE>_good.py` carries `# MLVIEW-EXPECT-NONE:`.
- [ ] `@rule(...)` declares severity, `base_prior`, frameworks, `rule_version`, tags, and `absence=True` if it asserts an absence.
- [ ] `message` cites variables and lines; `why` is one ML-terms sentence; `fix_hint` names the real API.
- [ ] `relatedLocs` use named roles; evidence kinds are ones the rule actually has.
- [ ] The code is in `PROTOTYPE_CODES` or `TIER_CODES`, with per-rule assertions.
- [ ] `python analyzer/tools/gen_rule_docs.py` re-run; `--check` green.
- [ ] `python -m pytest analyzer/tests -q` green, including the clean-corpus precision gate and the cross-fire gate.
- [ ] `python tools/accuracy.py` **and** `python tools/accuracy.py --dataflow local` green, both at 100% precision, with any baseline move explained in the commit body.
- [ ] `python tools/public_corpus.py check --strict` green, with any new high finding adjudicated in writing.
- [ ] `python scripts/check_docs.py` green.
