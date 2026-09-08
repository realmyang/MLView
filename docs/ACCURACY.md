# ACCURACY — the labelled corpus, and what it says today

ANA-12. MLView's core asset is that it does not lie, and its core weakness is
how much it misses. Neither number was measured anywhere in this tree until
now. This document describes the corpus that measures them, the numbers it
produced on **2026-09-08**, and the three gates that keep them from going
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

`analyzer/tests/accuracy/corpus/` holds ten labelled projects. Each is a
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

`*` **tuned**: the rules were developed against these two, so their numbers are
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

## 3 · The numbers on 2026-09-08

```
program                  files found labels    hit   miss     fp  graph
--------------------------------------------------------------------------
amp_accumulation             1     3      7      3      4      0 73.3%
gbm_tabular                  1     3      5      3      2      0 100.0%
hf_trainer_finetune          3     5      8      5      3      0 83.3%
hydra_research               4     5     11      5      6      0 56.2%
keras_tfdata                 3     3      5      3      2      0 66.7%
lightning_tabular            3     4      6      4      2      0 15.4%
timeseries_split             2     1      5      1      4      0 91.7%
timeseries_split_clean       1     0      0      0      0      0 83.3%
vision_pipeline*             5    15     15     15      0      0 60.7%
vision_pipeline_clean*       5     0      0      0      0      0 61.5%

rule       labels    found  visible       fp  precision   recall      f1
--------------------------------------------------------------------------
MLV101         11        3        3        0     100.0%    27.3%    0.43
MLV102          2        1        1        0     100.0%    50.0%    0.67
MLV103          3        2        2        0     100.0%    66.7%    0.80
MLV110          2        2        2        0     100.0%   100.0%    1.00
MLV111          3        2        2        0     100.0%    66.7%    0.80
MLV112          1        1        1        0     100.0%   100.0%    1.00
MLV201          3        2        2        0     100.0%    66.7%    0.80
MLV205          3        1        1        0     100.0%    33.3%    0.50
MLV301          4        2        1        0     100.0%    50.0%    0.67
MLV302          4        2        1        0     100.0%    50.0%    0.67
MLV401          3        1        1        0     100.0%    33.3%    0.50
MLV402          1        0        0        0          -     0.0%    0.00
MLV501          4        2        1        0     100.0%    50.0%    0.67
MLV601          8        8        5        0     100.0%   100.0%    1.00
MLV602          8        8        8        0     100.0%   100.0%    1.00
MLV701          1        1        1        0     100.0%   100.0%    1.00
MLV702          1        1        1        0     100.0%   100.0%    1.00

overall   labels  62   recall  62.9%   visible  53.2%   high+medium  48.8%   precision 100.0%
unseen    labels  47   recall  51.1%   visible  38.3%   high+medium  31.2%   precision 100.0%
```

**Precision is 100%.** Zero forbidden findings, zero unlabelled findings, on
ten projects and 62 labels. That is the claim the product rests on and it now
has a number behind it.

**Recall is the weakness, and it has three honest readings.** On the eight
unseen programs:

| Reading | Number | What it means |
|---|---|---|
| raw recall | **51.1%** | 24 of 47 planted defects produced a finding |
| visible recall | **38.3%** | …of which only 18 clear `mlview.minConfidence` 0.6, so the rest never reach the VS Code Problems panel |
| high+medium recall | **31.2%** | 10 of 32 defects that are not reproducibility hygiene |

**Reconciling with the audit's ~26%.** The Sprint-2 audit measured ≈26% over
four hand-written projects. The closest reading here is **31.2%** — the
high-and-medium-severity number on unseen code — and the gap is explained, not
argued away: these are *re-creations* of the auditors' probes rather than the
same files, and this corpus labels the reproducibility pair (MLV601, MLV602)
that fires on essentially every program, which lifts the raw figure to 51.1%.
Quote the high+medium number when comparing to the audit, and quote all three
when reporting progress.

**Graph fidelity: 92 of 139 hand-labelled ops, 66.2%.** The distribution is the
story, not the average:

* `lightning_tabular` **15.4%** (2 of 13). Every op in that project is written
  inside a method body, and the class-method blind spot (`core/build.py:234-238`,
  ANA-1) swallows all of them: `read_csv`, `fit_transform`, `TensorDataset`,
  `random_split` and both `DataLoader`s produce no node at all.
* `vision_pipeline` **60.7%**. The eleven missing ops are the whole Model lane —
  `Conv2d`, `BatchNorm2d`, `Dropout`, `AdaptiveAvgPool2d`, `Linear`, `softmax` —
  plus `SmallCNN()` itself and the two `model(images)` call sites. The demo's
  Model lane is empty for the same reason.
* `keras_tfdata` **66.7%**. The five missing ops are the whole `tf.data` chain,
  which is absent from the knowledge tables (FW-RECOG).

`python tools/accuracy.py --verbose` prints every one of them by file and line.
That list is the ANA-1 and FW-RECOG worklists, generated rather than asserted.

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
`2` on a forbidden finding, `3` on a regression, `4` on a malformed corpus. `analyzer/tests/accuracy/test_accuracy.py`
asserts the same three things inside `pytest analyzer/tests`, and the
`accuracy` job in `.github/workflows/ci.yml` runs the tool on every push.

1. **Zero `forbidden` findings, ever.** Not a baseline, not a ratchet, no
   tolerance. This is the lead's stated tolerance for ANA-12 and it is checked
   before anything else.
2. **Recall may only ratchet up**, against `analyzer/tests/accuracy/baseline.json`:
   overall, unseen-only, and per rule, in all three readings (raw, visible,
   high+medium).
3. **Graph fidelity may only ratchet up.**

The baseline is a floor, never a pin — a rule that starts finding something it
used to miss passes. When a change legitimately earns a new number, re-record
it with `python tools/accuracy.py --update-baseline` and say in the commit body
which change earned it. `--update-baseline` refuses to run from a `--program`
subset, so a partial run can never quietly lower the floor.

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
