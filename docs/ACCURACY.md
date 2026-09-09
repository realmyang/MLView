# ACCURACY — the labelled corpus, and what it says today

ANA-12. MLView's core asset is that it does not lie, and its core weakness is
how much it misses. Neither number was measured anywhere in this tree until
now. This document describes the corpus that measures them, the numbers it
produced on **2026-09-09**, and the three gates that keep them from going
backwards.

```
python tools/accuracy.py                    # the report and the gate
python tools/accuracy.py --verbose          # every missed label and missing op
python tools/accuracy.py --program hydra_research --no-gate
python tools/accuracy.py --update-baseline  # ratchet, after a rule change earns it
python -m pytest analyzer/tests/accuracy -q # the same thing, asserted
```

---

## 1 · What the corpus is

`analyzer/tests/accuracy/corpus/` holds fourteen labelled projects. Each is a
directory with a `labels.json` beside its sources; two of them are label files
alone, pointing at the shipped samples through a `root` key so the corpus never
forks a second copy of the demo.

| Program | Shape | Labels | Origin |
|---|---|---|---|
| `hf_trainer_finetune` | HuggingFace `Trainer` + a hand-rolled scoring pass | 8 | re-created from the Sprint-2 audit |
| `lightning_tabular` | `LightningModule` + `LightningDataModule` | 6 | re-created from the Sprint-2 audit |
| `keras_tfdata` | Keras functional model fed by `tf.data` | 5 | re-created from the Sprint-2 audit |
| `hydra_research` | config dict, name registry, `getattr` factories, hand-written loop | 11 | re-created from the Sprint-2 audit |
| `timeseries_split` | walk-forward forecast with `TimeSeriesSplit` | 5 | the shape `REQUIREMENTS` R3.7 asks for |
| `timeseries_split_clean` | its correct twin: every transform inside a `Pipeline` | 0 | the R3.7 negative |
| `amp_accumulation` | AMP + gradient accumulation, written wrong | 7 | dirty twin of `analyzer/tests/clean/amp_accumulation.py` |
| `gbm_tabular` | an XGBoost tabular baseline with no torch at all | 5 | the GBM script ANA-12 asks for |
| `vision_pipeline` * | the shipped demo | 15 | `samples/vision_pipeline/expected_issues.json` |
| `vision_pipeline_clean` * | the shipped clean twin | 0 | `samples/vision_pipeline_clean` |
| `torch_mechanics` * | AMP + clipping + a cosine schedule, with a tabular baseline beside it | 9 | written alongside ANA-8 / ANA-9 |
| `keras_uncompiled` * | Keras head fed by a shuffled `tf.data` take/skip holdout | 2 | written alongside ANA-7 / ANA-9 |
| `lightning_manual` * | two `LightningModule`s with a hand-rolled gradient update | 3 | written alongside ANA-7 |
| `hf_no_eval` * | a HuggingFace fine-tune that never evaluates | 1 | written alongside ANA-7 |

`*` **tuned**: the rules were developed against these six, so their numbers are
a ceiling, not a measurement. Every headline below is quoted twice — over the
whole corpus, and over the **unseen** eight alone.

## 2 · What a label is

Three verdicts, not two, so *"the tool may or may not say this"* is expressible
and the corpus does not become a ceiling of its own.

```json
{"code": "MLV101", "file": "datamodule.py", "line": 27,
 "symbol": "self.scaler.fit_transform", "severity": "high",
 "verdict": "expected",
 "defect": "the scaler is fitted on the whole frame inside setup()",
 "why":    "every validation row has already contributed its mean and variance"}
```

* **`expected`** — a defect planted on purpose. Firing on it is a true
  positive; missing it moves recall.
* **`acceptable`** — the tool may reasonably go either way. Scored neither as a
  hit nor as a false positive.
* **`forbidden`** — firing here is *wrong*, and the label **must** say why
  (`tools/accuracy.py` refuses to load a corpus where one does not). Any hit is
  a hard failure, regardless of the baseline.

An unsuppressed finding that satisfies no label is counted as a false positive.
That is deliberate: the corpus is labelled exhaustively, and `acceptable` is
how a legitimate-but-unplanted observation gets expressed. A new rule that
starts firing here needs a label, not an exemption.

**Anchors.** A label matches on its code, then on its anchor: `line` (one of
the finding's locations — `loc` or any `relatedLoc` — *spans* that line, so a
loop-anchored absence finding still matches the statement a human would point
at), `file`, or `project` for a whole-workspace claim like MLV601. One finding
satisfies at most one label. `expected` is assigned first, so a broad
file-level `forbidden` never steals a legitimate hit.

**Graph labels.** Each program also carries a small hand-drawn expectation:
the ops a person sketching that pipeline on a whiteboard would draw, each as a
`file` + `line`. An op counts as recovered only when a node is **anchored on
that exact line** — containment would score an op as recovered merely because
the function that should have held it exists, which is precisely the failure
mode the class-method blind spot produces.

## 3 · The numbers on 2026-09-09

Re-run after the ANA-7 / ANA-8 / ANA-9 rule tiers (`docs/CONTRACTS.md` §11.26),
which added sixteen rules and grew the corpus from ten labelled programs to
fourteen. Precision stayed **100%** on every rule and every program; every
gated recall number moved up; graph fidelity is unchanged, because the four new
programs deliberately carry no `graph` block. `scripts/check_docs.py` check 9
holds the headline figures in this section to
`analyzer/tests/accuracy/baseline.json` so the two cannot drift apart.

The four new programs — `keras_uncompiled`, `lightning_manual`, `hf_no_eval`
and `torch_mechanics` — are marked **tuned**, like the two shipped samples: they
were written alongside the rules that find their defects, so they are a ceiling
rather than a measurement and they are excluded from the unseen headline. The
unseen numbers moved on **one** label: `keras_tfdata`'s `model.py:16` was
labelled MLV402, a torch rule that can never resolve on a Keras program, and is
now labelled MLV709 — the same line, the same severity, the same defect, under
the code that can actually see it.

```
program                  files found labels    hit   miss     fp  graph
--------------------------------------------------------------------------
amp_accumulation             1     3      7      3      4      0 86.7%
gbm_tabular                  1     3      5      3      2      0 100.0%
hf_no_eval*                  1     1      1      1      0      0 100.0%
hf_trainer_finetune          3     5      8      5      3      0 91.7%
hydra_research               4     5     11      5      6      0 75.0%
keras_tfdata                 3     4      5      4      1      0 100.0%
keras_uncompiled*            3     2      2      2      0      0 100.0%
lightning_manual*            2     3      3      3      0      0 100.0%
lightning_tabular            3     4      6      4      2      0 100.0%
timeseries_split             2     1      5      1      4      0 91.7%
timeseries_split_clean       1     0      0      0      0      0 83.3%
torch_mechanics*             3     9      9      9      0      0 100.0%
vision_pipeline*             5    15     15     15      0      0 85.7%
vision_pipeline_clean*       5     0      0      0      0      0 100.0%

rule       labels    found  visible       fp  precision   recall      f1
--------------------------------------------------------------------------
MLV101         11        3        3        0     100.0%    27.3%    0.43
MLV102          2        1        1        0     100.0%    50.0%    0.67
MLV103          3        2        2        0     100.0%    66.7%    0.80
MLV106          1        1        1        0     100.0%   100.0%    1.00
MLV110          2        2        2        0     100.0%   100.0%    1.00
MLV111          3        2        2        0     100.0%    66.7%    0.80
MLV112          1        1        1        0     100.0%   100.0%    1.00
MLV114          1        1        1        0     100.0%   100.0%    1.00
MLV121          1        1        1        0     100.0%   100.0%    1.00
MLV201          3        2        2        0     100.0%    66.7%    0.80
MLV205          3        1        1        0     100.0%    33.3%    0.50
MLV207          1        1        1        0     100.0%   100.0%    1.00
MLV208          1        1        1        0     100.0%   100.0%    1.00
MLV209          1        1        1        0     100.0%   100.0%    1.00
MLV301          4        2        1        0     100.0%    50.0%    0.67
MLV302          4        2        1        0     100.0%    50.0%    0.67
MLV305          1        1        1        0     100.0%   100.0%    1.00
MLV306          1        1        1        0     100.0%   100.0%    1.00
MLV401          3        1        1        0     100.0%    33.3%    0.50
MLV501          4        2        1        0     100.0%    50.0%    0.67
MLV502          1        1        1        0     100.0%   100.0%    1.00
MLV601          8        8        5        0     100.0%   100.0%    1.00
MLV602          8        8        8        0     100.0%   100.0%    1.00
MLV701          1        1        1        0     100.0%   100.0%    1.00
MLV702          1        1        1        0     100.0%   100.0%    1.00
MLV705          1        1        1        0     100.0%   100.0%    1.00
MLV706          1        1        1        0     100.0%   100.0%    1.00
MLV707          1        1        1        0     100.0%   100.0%    1.00
MLV708          1        1        1        0     100.0%   100.0%    1.00
MLV709          1        1        1        0     100.0%   100.0%    1.00
MLV711          1        1        1        0     100.0%   100.0%    1.00
MLV803          1        1        1        0     100.0%   100.0%    1.00

overall   labels  77   recall  71.4%   visible  63.6%   high+medium  62.5%   precision 100.0%
unseen    labels  47   recall  53.2%   visible  40.4%   high+medium  34.4%   precision 100.0%
```

**Precision is 100%.** Zero forbidden findings, zero unlabelled findings, on
fourteen projects and 77 labels. That is the claim the product rests on and it now
has a number behind it.

**Recall is the weakness, and it has three honest readings.** On the eight
unseen programs:

| Reading | Number | What it means |
|---|---|---|
| raw recall | **53.2%** | 25 of 47 planted defects produced a finding |
| visible recall | **40.4%** | …of which only 19 clear `mlview.minConfidence` 0.6, so the rest never reach the VS Code Problems panel |
| high+medium recall | **34.4%** | 11 of 32 defects that are not reproducibility hygiene |

**Reconciling with the audit's ~26%.** The Sprint-2 audit measured ≈26% over
four hand-written projects. The closest reading here is **34.4%** — the
high-and-medium-severity number on unseen code — and the gap is explained, not
argued away: these are *re-creations* of the auditors' probes rather than the
same files, and this corpus labels the reproducibility pair (MLV601, MLV602)
that fires on essentially every program, which lifts the raw figure to 53.2%.
Quote the high+medium number when comparing to the audit, and quote all three
when reporting progress.

**What the tiers did and did not buy.** All three unseen readings moved by
exactly one label, because the sixteen new rules were written against defects
that the eight unseen programs mostly do not contain: the tiers are recall the
corpus can now *measure*, not recall it has demonstrated on code nobody wrote
for them. The overall figures — 71.4% raw over 77 labels — carry the tuned
programs and should be read as "these rules fire where they are supposed to",
never as a field measurement. Growing the unseen half of the corpus remains the
cheapest recall work on the board.

**Graph fidelity: 126 of 139 hand-labelled ops, 90.6%.** This half of the table
has moved twice. It was **92 of 139, 66.2%** until ANA-1 stopped dropping ops
written inside a class method (`docs/CONTRACTS.md` §11.19), which took it to
**120 of 139, 86.3%**; FW-RECOG then added the tf.data, HuggingFace `datasets`
and Lightning-hook tables (§11.23) and it reached 0.9065. The six ops that
moved are `keras_tfdata`'s `map` / `shuffle` / `batch` — recognised at all for
the first time, and anchored on the method name rather than on the start of the
chain — `hf_trainer_finetune`'s `datasets.Dataset.map`, and the two
`lightning_tabular` ops its hook units bring in. **Every precision and recall
number is unchanged**, which is the point: the tables add sight, not verdicts.
The distribution is still the story, not the average:

* `lightning_tabular` **100.0%** (13 of 13), from 15.4% (2 of 13). Every op in
  that project is written inside a method body, and the class-method blind spot
  in `core/build.py` swallowed all of them — `read_csv`, `fit_transform`,
  `TensorDataset`, `random_split` and both `DataLoader`s drew no node at all.
  ANA-1 split the one overloaded `CallSite.class_ir` field into *what this call
  resolves to* and *what class it is written in*, and all thirteen now anchor.
  This project is what the re-baseline bought, and it is the corpus's only
  perfect unseen score.
* `vision_pipeline` **85.7%** (24 of 28), from 60.7%. The Model lane is drawn:
  `Conv2d`, `BatchNorm2d`, `Dropout`, `AdaptiveAvgPool2d`, `Linear` and
  `softmax` all carry nodes now. The four still missing are `SmallCNN()` and
  `ConvBlock()` — instantiations of a class this workspace defines — and the two
  `model(images)` call sites that go through the instance.
* `keras_tfdata` **66.7%** (10 of 15) is now the corpus's *worst* score, which
  is the point of re-measuring. The five missing ops are the whole `tf.data`
  chain — `from_tensor_slices` twice, `map`, `shuffle`, `batch` — absent from
  the knowledge tables (FW-RECOG).

**The nineteen still missing.** `python tools/accuracy.py --verbose` prints each
one by file and line. They are no longer one worklist; they are three:

| Family | n | What it looks like |
|---|---|---|
| a call through an object whose class this workspace defines | 10 | `model(features)`, `criterion(...)`, `SmallCNN()`, `ConvBlock()`, `build_from_cfg` |
| a framework method the knowledge tables do not carry (FW-RECOG) | 6 | the five-call `tf.data` chain, and `datasets.map` in the HF project |
| a call the tables do carry that anchored no node on that exact line | 3 | pandas `shift` in both time-series programs, `optimizer.step` in the hand-written hydra loop |

That list is generated, never asserted, so it is a worklist rather than a claim.
The ANA-1 entries that used to dominate it are gone.

**Calibration.**

```
bucket              n     tp     fp      mean conf  observed prec    error
--------------------------------------------------------------------------
certain            24     24      0          0.931         100.0%    0.069
likely              9      9      0          0.842         100.0%    0.158
speculative         6      6      0          0.336         100.0%    0.664
```

The confidence model is **under**-confident, not over-confident, and severely
so at the bottom. Six findings landed in `speculative` at a mean confidence of
0.34, and every one of them was a genuine planted defect. All six are absence
findings under `WRAPPER_FACTOR` 0.4 — MLV301, MLV302 and MLV501 on the
hand-rolled scoring pass inside the HF project, and MLV601 on three
framework-owned projects. That single multiplier is what makes two whole
projects publish nothing to the Problems panel, and it is the calibration
finding this table exists to surface.

The calibration table is **reported, not gated**: at this corpus size a bucket
can hold six findings, so one label flips its observed precision by a sixth.
It becomes gateable when the corpus is several times larger.

## 4 · The gates

`tools/accuracy.py` (the tables, the gate and the CLI) over
`tools/accuracy_corpus.py` (loading, matching and scoring) exits `0` green,
`2` on a forbidden finding, `3` on a regression — or on an `--update-baseline`
that would have recorded one — `4` on a malformed corpus. `analyzer/tests/accuracy/test_accuracy.py`
asserts the same three things inside `pytest analyzer/tests`, the
`accuracy` job in `.github/workflows/ci.yml` runs the tool on every push, and
both `scripts/e2e` drivers carry it as a row of the acceptance table, so the
signal does not depend on being able to reach GitHub Actions.

1. **Zero `forbidden` findings, ever.** Not a baseline, not a ratchet, no
   tolerance. This is the lead's stated tolerance for ANA-12 and it is checked
   before anything else. **No flag suppresses it**: `--no-gate` covers the
   ratchet comparison only and still exits `2` on a forbidden finding, and
   `--update-baseline` refuses to write at all while one is firing.
2. **Recall may only ratchet up**, against `analyzer/tests/accuracy/baseline.json`:
   overall, unseen-only, and per rule, in all three readings (raw, visible,
   high+medium).
3. **Graph fidelity may only ratchet up.**

The baseline is a floor, never a pin — a rule that starts finding something it
used to miss passes. When a change legitimately earns a new number, re-record
it with `python tools/accuracy.py --update-baseline` and say in the commit body
which change earned it.

`--update-baseline` enforces gate 2 rather than bypassing it (fixed 2026-09-08,
TB-02 — it used to rewrite the file unconditionally, so one command erased a
recall regression and the note it wrote still claimed the invariant). It now:

* refuses to run from a `--program` subset, so a partial run can never quietly
  lower the floor;
* refuses to write while a `forbidden` finding fires (exit `2`);
* loads the baseline it is about to overwrite, prints the before/after of
  **every** gated number that moved in either direction, and exits `3` if any
  moved down.

Recording a downward move therefore takes an explicit
`--allow-regression "<reason>"`, and that reason is appended to the new
baseline's own `note` field, so the file says why it went backwards rather than
leaving the evidence in a commit body nobody reads next to it.

## 5 · Known limits of this corpus

* **It encodes one opinion.** Every label was written by one engineer on one
  day; `origin`, `defect` and `why` are on every row so a disagreement has
  something specific to argue with.
* **A defect with no rule cannot be labelled.** Recall is per rule, so real
  mistakes the rule set does not model — `train_test_split(shuffle=True)` on a
  time series, `scaler.step()` without `scaler.update()` — are present in the
  sources and absent from the labels. They become labels the day a rule exists.
* **Eight unseen programs is small.** A single label moves unseen recall by
  two points, which is why the tool prints counts beside every percentage.
* **The two shipped samples are a ceiling.** They score 100% recall because the
  rules were written against them. They stay in the corpus for their forbidden
  labels — a clean twin is the strongest false-positive trap there is — and are
  excluded from every headline.
* **Notebooks are absent.** The ROADMAP's ANA-12 entry asks for one; notebooks
  are not in this sprint (`NB`), and a corpus entry that scores `0 files
  analyzed` would only measure the skip.
