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

## 3 · The numbers on 2026-09-15

Re-run after the ANA-7 / ANA-8 / ANA-9 rule tiers (`docs/CONTRACTS.md` §11.26),
which added sixteen rules and grew the corpus from ten labelled programs to
fourteen. Precision stayed **100%** on every rule and every program; every
gated recall number moved up; graph fidelity is unchanged, because the four new
programs deliberately carry no `graph` block. `scripts/check_docs.py` check 9
holds the headline figures in this section to
`analyzer/tests/accuracy/baseline.json` so the two cannot drift apart.

**Re-recorded on 2026-09-15 for the recall wave** — R1–R5, `docs/CONTRACTS.md`
§3.11 R1.1–R1.5, §5.3 A7–A13, §14.2 F16–F21 / R13–R21 — and §8 below is that
wave's own record. The block in this section is the **`local`** report, because
`scripts/doc_numbers.py` check 9 binds it to `analyzer/tests/accuracy/baseline.json`,
which is the `local` ratchet; **`ip` is the shipped default and its figures are in
section 6.** The previous re-record, kept because it is what the numbers before this
wave mean:

> **2026-09-10, for ANA-10** (`docs/CONTRACTS.md` §11.45), the
> in-Python half of config resolution: module-level dict literals, dataclass field
> defaults, `argparse` `add_argument(default=)` and the attribute/subscript chains
> rooted at any of them now resolve to literals. Measured A/B with
> `ir.bindings._resolve_config` stubbed to a no-op, that change alone was the whole
> move: raw recall **71.8% → 73.1%**, visible 64.1% → 65.4%, high+medium
> 63.2% → 64.9%, unseen 53.2% → 55.3%, graph fidelity 126 → 127 of 139.

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
amp_accumulation             1     7      7      7      0      0 100.0%
gbm_tabular                  1     3      5      3      2      0 100.0%
hf_no_eval*                  1     1      1      1      0      0 100.0%
hf_trainer_finetune          3     6      8      6      2      0 100.0%
hydra_research               4     7     11      7      4      0 93.8%
keras_se_gate*               3     1      1      1      0      0   n/l
keras_tfdata                 3     4      5      4      1      0 100.0%
keras_uncompiled*            3     2      2      2      0      0   n/l
lightning_manual*            2     3      3      3      0      0 100.0%
lightning_tabular            3     5      6      5      1      0 100.0%
timeseries_split             2     1      5      1      4      0 100.0%
timeseries_split_clean       1     0      0      0      0      0 100.0%
torch_mechanics*             3     9      9      9      0      0   n/l
vision_pipeline*             5    15     15     15      0      0 100.0%
vision_pipeline_clean*       5     0      0      0      0      0 100.0%
--------------------------------------------------------------------------
* tuned: the rules were developed against this project; excluded from the
  unseen headline below.

per-rule precision / recall  (labelled corpus, unsuppressed findings)

rule       labels  found  visible   fp  precision   recall     f1 unseen recall
--------------------------------------------------------------------------------
MLV101         11      3        3    0     100.0%    27.3%   0.43         20.0%
MLV102          2      1        1    0     100.0%    50.0%   0.67         50.0%
MLV103          3      2        2    0     100.0%    66.7%   0.80         50.0%
MLV106*         1      1        1    0     100.0%   100.0%   1.00             -
MLV110          2      2        2    0     100.0%   100.0%   1.00        100.0%
MLV111          3      3        3    0     100.0%   100.0%   1.00        100.0%
MLV112*         1      1        1    0     100.0%   100.0%   1.00             -
MLV114*         1      1        1    0     100.0%   100.0%   1.00             -
MLV121*         2      2        2    0     100.0%   100.0%   1.00             -
MLV201          3      3        3    0     100.0%   100.0%   1.00        100.0%
MLV205          3      3        3    0     100.0%   100.0%   1.00        100.0%
MLV207*         1      1        1    0     100.0%   100.0%   1.00             -
MLV208*         1      1        1    0     100.0%   100.0%   1.00             -
MLV209*         1      1        1    0     100.0%   100.0%   1.00             -
MLV301          4      3        2    0     100.0%    75.0%   0.86         66.7%
MLV302          4      3        2    0     100.0%    75.0%   0.86         66.7%
MLV305*         1      1        1    0     100.0%   100.0%   1.00             -
MLV306*         1      1        1    0     100.0%   100.0%   1.00             -
MLV401          3      2        2    0     100.0%    66.7%   0.80         50.0%
MLV501          4      3        2    0     100.0%    75.0%   0.86         66.7%
MLV502*         1      1        1    0     100.0%   100.0%   1.00             -
MLV601          8      8        5    0     100.0%   100.0%   1.00        100.0%
MLV602          8      8        8    0     100.0%   100.0%   1.00        100.0%
MLV701          1      1        1    0     100.0%   100.0%   1.00        100.0%
MLV702*         1      1        1    0     100.0%   100.0%   1.00             -
MLV705*         1      1        1    0     100.0%   100.0%   1.00             -
MLV706*         1      1        1    0     100.0%   100.0%   1.00             -
MLV707*         1      1        1    0     100.0%   100.0%   1.00             -
MLV708*         1      1        1    0     100.0%   100.0%   1.00             -
MLV709          1      1        1    0     100.0%   100.0%   1.00        100.0%
MLV711*         1      1        1    0     100.0%   100.0%   1.00             -
MLV803*         1      1        1    0     100.0%   100.0%   1.00             -

overall   labels  78   recall  82.0%   visible  74.4%   high+medium  75.4%   precision 100.0%
unseen    labels  47   recall  70.2%   visible  57.5%   high+medium  56.2%   precision 100.0%
```

Two columns exist because the report used to overstate itself. **`n/l`** in the
graph column is a program with no hand-drawn `graph` block in its `labels.json`:
nobody drew a diagram for it, so nothing was measured — it used to print
`100.0%`, four perfect scores off no evidence at all. A **`*` on a rule** means
every label that rule has lives in a program it was developed against, so its
`recall` column is a ceiling and its **`unseen recall`** is `-`: nothing unseen
has been labelled for it yet. Sixteen rules read `recall 100.0%` under the old
table with nothing saying so.

`keras_se_gate` is the fifteenth program — a squeeze-and-excite Keras classifier
on a `ds = ds.<op>(...)` tf.data pipeline. It carries the two MLV709
false-positive shapes and the MLV121 `take(1)` peek as `forbidden` labels and a
rebinding-style shuffle-before-holdout as `expected`. It is marked **tuned**,
because those guards were written against its shapes: its zero-forbidden result
is a regression guard, not an unseen measurement.

**Precision is 100%.** Zero forbidden findings, zero unlabelled findings, on
fifteen projects and 78 labels. That is the claim the product rests on and it now
has a number behind it.

**Recall is the weakness, and it has three honest readings.** On the eight
unseen programs:

| Reading | Number | What it means |
|---|---|---|
| raw recall | **70.2%** | 33 of 47 planted defects produced a finding |
| visible recall | **57.5%** | …of which only 27 clear `mlview.minConfidence` 0.6, so the rest never reach the VS Code Problems panel |
| high+medium recall | **56.2%** | 18 of 32 defects that are not reproducibility hygiene |

Those are the **`--dataflow local`** readings, and `local` is **no longer the
default** (§6, and `docs/CONTRACTS.md` §3.11 R1.1). The numbers a user actually
gets are the `ip` ones in section 6: raw **89.4%**, visible **70.2%**,
high+medium **84.4%** on the same eight unseen programs. Section 3 goes on quoting `local` because
`scripts/doc_numbers.py` check 9 binds this section to
`analyzer/tests/accuracy/baseline.json`, which is the `local` ratchet, and the
two must not be allowed to drift apart; section 6 owns the default mode's
figures against `baseline.ip.json`.

**Reconciling with the audit's ~26%.** The Sprint-2 audit measured ≈26% over
four hand-written projects. The closest reading here is the
high-and-medium-severity number on unseen code — **56.2%** in `local`, **84.4%**
in the default `ip` — and the gap is explained, not argued away: these are
*re-creations* of the auditors' probes rather than the same files, and this
corpus labels the reproducibility pair (MLV601, MLV602) that fires on
essentially every program, which lifts the raw figure. Quote the high+medium
number when comparing to the audit, and quote all three when reporting
progress.

**What the tiers did and did not buy.** All three unseen readings moved by
exactly one label, because the sixteen new rules were written against defects
that the eight unseen programs mostly do not contain: the tiers are recall the
corpus can now *measure*, not recall it has demonstrated on code nobody wrote
for them. The overall figures — 82.0% raw over 78 labels in `local`, 93.6% in `ip` — carry the tuned
programs and should be read as "these rules fire where they are supposed to",
never as a field measurement. Growing the unseen half of the corpus remains the
cheapest recall work on the board.

**What ANA-10 bought, and what it did not.** One label, and it is an unseen one:
MLV201 at `hydra_research/src/train.py:35`, a planted "gradients are never
zeroed" that was unreachable until the `getattr` registry selection let
`optimizer_for(...)` resolve to an optimizer. That is MLV201's unseen recall
moving 50.0% → 100.0% and the corpus's raw unseen recall moving by one label.
The larger effect is one this table cannot show, because the table only counts
findings that *should* exist: on `DataLoader(ds, shuffle=CFG["shuffle"])` with
`CFG["shuffle"] = True`, MLV110 used to report *"shuffle=unset (defaults to
False)"* at `likely` — a false statement about a correct program. It is gone,
and no label ever recorded it. A config read can never mint a `certain` finding:
every read costs one explicit `CONFIG_EVIDENCE_WEIGHT` (0.8) factor and the
highest registered prior, 0.98, lands at 0.784.

**Graph fidelity: 163 of 164 hand-labelled ops, 99.4%**, identically in both
dataflow modes — §7 is the whole record of the move, including why the
denominator went 139 → 164. What follows is how it got to 127 of 139 (91.4%),
which is where §7 starts. This half of the table has moved four times. It was **92 of 139, 66.2%** until ANA-1 stopped dropping
ops written inside a class method (`docs/CONTRACTS.md` §11.19), which took it to
**120 of 139, 86.3%**; FW-RECOG then added the tf.data, HuggingFace `datasets`
and Lightning-hook tables (§11.23) and it reached 0.9065; ANA-10 (§11.45) added
the thirteenth `hydra_research` op — the optimizer behind the `getattr` registry
— for 0.9137. The six ops that
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

**The worklist it left.** `python tools/accuracy.py --verbose` prints every
remaining miss by file and line — generated, never asserted, so it is a worklist
rather than a claim. At the 2026-09-10 reading it was nineteen entries in three
families:

| Family | n | What it looks like | Closed by |
|---|---|---|---|
| a call through an object whose class this workspace defines | 10 | `model(features)`, `criterion(...)`, `SmallCNN()`, `ConvBlock()`, `build_from_cfg` | **R3** (§7.2), 9 of 10 |
| a framework method the knowledge tables do not carry (FW-RECOG) | 6 | the five-call `tf.data` chain, and `datasets.map` in the HF project | FW-RECOG |
| a call the tables do carry that anchored no node on that exact line | 3 | pandas `shift` in both time-series programs, `optimizer.step` in the hand-written hydra loop | **R2** (§7.2) and ANA-10 |

**One entry survives** and it is the first family's tenth: `hydra_research`'s
`model(features)` at `src/train.py:51` — §7.4 says exactly why.

**Calibration.**

```
bucket              n     tp     fp      mean conf  observed prec    error
--------------------------------------------------------------------------
certain            37     37      0          0.928         100.0%    0.072
likely             21     21      0          0.831         100.0%    0.169
speculative         6      6      0          0.336         100.0%    0.664
```

(`--dataflow local`. In `ip` the same 37 land `certain`, `likely` grows to 26
and a `possible` bucket of 2 appears — the cross-object findings, de-rated by
`IP_HOP_WEIGHT` exactly as §6 describes. Every bucket is 100% precise in both.)

The confidence model is **under**-confident, not over-confident, and severely
so at the bottom. Six findings landed in `speculative` at a mean confidence of
0.34, and every one of them was a genuine planted defect. All six are absence
findings under `WRAPPER_FACTOR` 0.4 — MLV301, MLV302 and MLV501 on the
hand-rolled scoring pass inside the HF project, and MLV601 on three
framework-owned projects. That single multiplier is what makes two whole
projects publish nothing to the Problems panel, and it is the calibration
finding this table exists to surface.

The calibration table is **reported, not gated**: at this corpus size a bucket
can hold two findings, so one label flips its observed precision by half.
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

## 6 · `--dataflow ip`, the default, measured separately

DATAFLOW-IP (`docs/CONTRACTS.md` §3.11) adds a second analysis, not a second
opinion about the first: `ip` carries value tags across the object boundary
through constructor, return and method-argument summaries, where `local` does
not. **Since 2026-09-15 `ip` is the product default** (§3.11 R1.1; one constant,
`ir.build_ir.DEFAULT_DATAFLOW`, is the authority and the CLI, the API and
`tools/accuracy.py` all read it). `local` is the shipped, gated opt-out, and it
is the analysis every number in section 3 describes. The two are scored against
**two baselines**, because one number cannot gate two analyses:

```
python tools/accuracy.py                  # local, gates baseline.json
python tools/accuracy.py --dataflow ip    # ip, gates baseline.ip.json
```

`analyzer/tests/accuracy/baseline.ip.json` has the same shape and the same two
tolerances as its local twin — **zero `forbidden` findings ever, recall may only
ratchet up** — and carries a `dataflow` field so a file can never be read as
the other mode's floor. `analyzer/tests/core/test_dataflow_ip.py` asserts both
tolerances inside `pytest analyzer/tests`, alongside the mode's own fixtures.

### The two modes on the same 15 programs, 2026-09-15

| mode | recall | visible | high+medium | unseen recall | precision | forbidden | unlabelled |
|---|---|---|---|---|---|---|---|
| `local` (opt-out) | 82.0% | 74.4% | 75.4% | 70.2% | **100%** | 0 | 0 |
| `ip` (**default**) | **93.6%** | **82.0%** | **91.2%** | **89.4%** | **100%** | 0 | 0 |

Graph fidelity is **99.4% in both** (§7). Every number in the `local` row is the
one section 3 records, unmoved to four decimal places: the mode is additive by
construction, and `AnalyzeOptions(paths=..., dataflow="local")` is byte-for-byte
the analysis that shipped before the flag existed.

**The reading on 2026-09-10, before the recall wave**, kept so the move is
legible: `local` 73.1% / 65.4% / 64.9% / 55.3%, `ip` 79.5% / 71.8% / 73.7% /
66.0%, graph fidelity 91.4% in both. The mode then bought **five** expected
labels, two of them the high-severity leaks the roadmap named as the whole
reason to fund the work: the Lightning `DataModule` fitting a `StandardScaler`
on the whole feature matrix before `random_split`
(`lightning_tabular/datamodule.py:27`), and the same shape in a research script
that scales a whole series before a chronological cut.

**It now buys nine**, and the gap between the rows is what R5 added (§8): the
three interprocedural paths for MLV101 / MLV102 / MLV103 are `ip`-only by
construction (§3.11 R1.5), so `local` is deliberately the narrower analysis and
moves less. No finding fires in `local` and not in `ip`; that direction is a
regression, not a trade (§3.11 R1.3).

### Why an `ip` finding is never `certain`

Each hop multiplies the confidence product by an explicit interprocedural
evidence weight (`IP_HOP_WEIGHT`, 0.8), contributed as one `cross_file` evidence
entry whose detail names the hop chain in words. For MLV101's 0.95 prior that is
0.760 after one hop, 0.608 after two and 0.486 after three — so a cross-object
finding lands at `likely` or `possible`, and `certain` (>= 0.9) is arithmetically
out of reach. The calibration table above therefore reads differently in `ip`:
the `likely` bucket grows from 21 findings to 26 and a `possible` bucket of 2
appears, and every bucket's observed precision stays 100%.

### What the `ip` numbers do not say

* **The corpus is the same corpus.** It was labelled for `local`, so `ip` is
  measured on defects nobody planted for it. That is the right direction for a
  precision claim and the wrong one for a recall claim: the five labels `ip`
  newly recovers are a floor on what the mode adds, not an estimate of it.
* **Precision at 100% is 73 findings, not a proof.** The mode's whole risk is a
  high-severity false positive, and the corpus can only report the ones it has
  labels for. The three negative fixtures under `analyzer/tests/fixtures/dataflow`
  — a helper that legitimately receives already-split training rows, a helper
  called from two sites with different tag sets, and a parameter merely named
  `X` — are the shapes the mode is most likely to get wrong, and they are
  asserted at the IR level, not only at the finding level.
* **Eight rules consume the hop chain now** — MLV101, MLV102, MLV103, MLV111,
  MLV305, MLV306, MLV401 and MLV402 (§5.3 A13, §14.2 R13–R21). Every other rule
  reads the widened tags without naming a hop in its evidence or paying its
  weight. §3.11's gate G6 is written over the whole document, so a rule that
  starts making cross-object claims cannot quietly skip the de-rating.
* **A chain past three hops is reported, not scored.** It emits a `truncated`
  diagnostic and no finding, which is a miss the recall column counts and a
  blindness the document names — the distinction this whole file exists to keep.

---

## 7 · Graph fidelity: the two families that were missing, and what closed them

Section 3's graph-fidelity half measures something the recall columns cannot:
**whether the diagram has a box where a person drew one.** The anchor is
`(file, line)` and it is exact — a card in the right file on the wrong line is
a miss — because a containment test would score an op as recovered merely
because the function that should have contained it exists, which is precisely
the failure mode the score has to be able to see.

On **2026-09-14** it stood at 127 of 139 (91.4%), and every one of the twelve
misses was one of two shapes. Two more programs were hand-labelled the same day
(§7.3), which widens the denominator to 164 and puts the pre-change figure at
**150 of 164 (91.5%)** — the same measurement over more of the corpus.

### 7.1 · What was missing

| Missing op | Where | Why nothing was drawn |
|---|---|---|
| `model(images)` ×2, `model(...)`, `model(features)` ×2 | vision_pipeline, hf_trainer_finetune, amp_accumulation, hydra_research | role `FORWARD` is transparent — correctly, for the layer chain inside a `forward`, and that same rule swallowed the *outer* forward pass |
| `criterion(...)` ×2 | amp_accumulation, hydra_research | the same transparency, on a criterion object |
| `SmallCNN`, `ConvBlock` | vision_pipeline | a call resolving to a workspace class was folded onto the class's **definition** card, so the line where the object is *built* had nothing |
| `build_from_cfg` | hydra_research | a workspace factory whose return `ir.returns` could not type at all |
| `shift` ×2 | timeseries_split, timeseries_split_clean | pandas' lag / window family had no knowledge rows |

### 7.2 · What closed them

**R3 — `analyzer/src/mlview/core/workspace_ops.py`.** Three call shapes now mint
a card: constructing a workspace class, invoking a workspace object, and the
object a workspace factory returns. Five ways a script *carries* such an object
resolve too — `self.<attr>` across sibling methods, a dict, a dataclass field, a
tuple, and a rebinding wrapper (`accelerator.prepare` / `Fabric.setup`). A
factory whose return cannot be typed at all gets an honest `unknown` card naming
the construct that defeated the analyzer, which is ANA-5a's rule one level out.

**R2 — `knowledge/pandas_tbl.py` and `knowledge/stats_tbl.py`.** pandas beyond
the shape-preserving hop (`shift`, `rolling`, `diff`, `pct_change`, `resample`,
`groupby`, `merge`, `join`, the readers `sklearn_tbl.py` had not listed, the
closing aggregations, and `df.loc[...]` / `df.iloc[...]`, which used to stop a
frame's tags dead), statsmodels and Prophet, HuggingFace `evaluate`, the
torchmetrics `update` / `compute` pair, and the rest of the Keras `Model`
surface. Nine new roles, **none of which any rule keys on**: the tables add
sight, not verdicts — the same principle FW-RECOG's tables were added under.

Both are specified in `docs/CONTRACTS.md` — R3 in §5.3 A7–A12′, R2 in §14.2
F16–F21. The fragment they were drafted as was folded into that document and
removed, which is what §15's "a fragment is folded, never kept" rule asks for.

### 7.3 · Where it stands

**163 of 164 hand-labelled ops (99.4%)**, identically in `--dataflow local` and
`--dataflow ip`, up from 150 of 164. Eleven of the twelve labelled programs are
at 100%, and `hydra_research` is at 15 of 16.

| Program | before | after |
|---|---|---|
| `amp_accumulation` | 13 / 15 | **15 / 15** |
| `hf_trainer_finetune` | 11 / 12 | **12 / 12** |
| `hydra_research` | 13 / 16 | **15 / 16** |
| `timeseries_split` | 11 / 12 | **12 / 12** |
| `timeseries_split_clean` | 5 / 6 | **6 / 6** |
| `vision_pipeline` | 24 / 28 | **28 / 28** |
| `lightning_manual` * | 17 / 19 | **19 / 19** |
| `hf_no_eval` * | 6 / 6 | **6 / 6** |
| `gbm_tabular`, `keras_tfdata`, `lightning_tabular`, `vision_pipeline_clean` | 100% | **100%** |

`*` **newly labelled on 2026-09-14**, and the *before* column is a real
measurement: both blocks were drawn from the source against the convention the
sibling HuggingFace and Lightning programs already established, then scored
against the **pre-change** analyzer, which recovers 6 of 6 and 17 of 19. The two
it misses are the two `TaggerLit(...)` constructions R3 adds. Each block records
that provenance in its own `graph.drawnBy` field, because a label drawn by the
person whose change it scores has to say so. Three programs (`keras_se_gate`,
`keras_uncompiled`, `torch_mechanics`) still carry no `graph` block and still
contribute nothing.

**Precision did not move**: 100% in both modes, zero `forbidden` findings, zero
unlabelled findings, and both clean corpora still emit **0**. §8.3 is the
public-corpus measurement that says the same thing about code nobody wrote for
MLView.

### 7.4 · The one that is still missing, and why

`hydra_research`'s `model(features)` at `src/train.py:51`. `model` comes from
`build_from_cfg("model", cfg["model"])`, which reaches
`_REGISTRY[group][name](**kwargs)`: the type is knowable only by reading
`@register("model", "mlp")` at import time. The construction site gets its
`unknown` card, but nothing in the chain ever says `model` is a model, so the
forward pass two functions later has no receiver to resolve against. Making
`ReturnSlot.opaque` travel through `ir.summaries` to a parameter would turn it
into an honest `unknown` card there too; typing it properly needs a decorator
registry model, which nothing in this tree has.

### 7.5 · The ratchet, run

`python tools/accuracy.py --update-baseline` and the same with `--dataflow ip`
were run on **2026-09-15**, and every gated number moved **up**; neither command
had to record a downward move, and neither was given `--allow-regression`.
Section 3 above quotes the new `local` figures and section 6 the new `ip` ones,
which is what `scripts/doc_numbers.py` check 9 requires. Both baselines carry a
`note` saying which change earned the number.

| baseline | overall recall | unseen recall | graph fidelity |
|---|---|---|---|
| `baseline.json` (`local`) | 0.7308 → **0.8205** | 0.5532 → **0.7021** | 0.9137 → **0.9939** |
| `baseline.ip.json` (`ip`, the default) | 0.7949 → **0.9359** | 0.6596 → **0.8936** | 0.9137 → **0.9939** |

---

## 8 · The recall wave, 2026-09-15

Five items, R1–R5, integrated together and measured together. The
constraint was never recall: **precision stays 100% with zero `forbidden`
findings, and zero new high-severity findings on the public corpus.** Both held.

### 8.1 · What landed

| # | Change | Where it is specified |
|---|---|---|
| **R1** | `--dataflow ip` is the product default, from one constant. `local` is a shipped, gated opt-out. | `docs/CONTRACTS.md` §3.11 R1.1–R1.5 |
| **R2** | Knowledge tables: pandas beyond the shape-preserving hop, statsmodels / Prophet, HuggingFace `evaluate`, torchmetrics, the rest of the Keras `Model` surface, and pandas indexer stripping. Nine new roles, **none keyed on by any rule**. | §14.2 F16–F21 |
| **R3** | Calls through workspace-defined objects: constructing one, invoking one, and a factory's returned object, plus five ways a script carries one. | §5.3 A7–A12′ |
| **R4** | `rules/valuetype.py` — LOGITS / PROBS / PREDS typed through a helper's `return` and a `.detach().cpu().numpy()` tail, for MLV305 / MLV306 / MLV401 / MLV402. | §5.3 A13, §14.2 R19–R21 |
| **R5** | The named shapes: MLV101 through a `return`, MLV102 through a fold index, MLV103 through a callee, MLV111's split dictionary, and two corrections to MLV205. | §14.2 R13–R18 |

### 8.2 · The numbers, both modes, 15 programs / 78 labels

| | `local` before | `local` after | `ip` before | **`ip` after** (default) |
|---|---|---|---|---|
| overall recall | 73.1% | **82.0%** | 79.5% | **93.6%** |
| overall visible | 65.4% | **74.4%** | 71.8% | **82.0%** |
| overall high+medium | 64.9% | **75.4%** | 73.7% | **91.2%** |
| unseen recall | 55.3% | **70.2%** | 66.0% | **89.4%** |
| unseen visible | 42.5% | **57.5%** | 53.2% | **70.2%** |
| unseen high+medium | 37.5% | **56.2%** | 53.1% | **84.4%** |
| graph fidelity | 91.4% (127/139) | **99.4% (163/164)** | 91.4% | **99.4%** |
| **precision** | **100%** | **100%** | **100%** | **100%** |
| forbidden findings | 0 | **0** | 0 | **0** |
| unlabelled findings | 0 | **0** | 0 | **0** |

**The target was unseen recall ≥ 82% overall: it is 89.4% in the default mode.**

The seven rules the wave was asked to lift above 60%, in the default mode
(`unseen recall` in brackets; `–` means nothing unseen is labelled for that rule
yet, so its headline figure is the tuned ceiling):

| rule | labels | before | **after** |
|---|---|---|---|
| MLV208 | 1 | 100% (–) | **100% (–)** |
| MLV305 | 1 | 100% (–) | **100% (–)** |
| MLV103 | 3 | 66.7% (50.0%) | **100% (100%)** |
| MLV114 | 1 | 100% (–) | **100% (–)** |
| MLV101 | 11 | 72.7% (70.0%) | **90.9% (90.0%)** |
| MLV401 | 3 | 33.3% (0.0%) | **66.7% (50.0%)** |
| MLV402 | **0** | — | **unmeasurable** |

**MLV402 cannot be scored here**: this corpus carries no MLV402 label. Its two
new paths are covered by `MLV402_helper_bad.py` / `_good.py` and by
`test_value_typing.py` only, and the honest reading is that the target is
**not evaluated** for it rather than met. An MLV402-labelled program is the
cheapest way to close that, and it is the one target of the seven this wave
cannot claim.

Three more rules moved without being asked to: MLV102 50.0% → **100%**,
MLV111 66.7% → **100%**, MLV205 33.3% → **100%**, and MLV301 / MLV302 / MLV501
each 50.0% → **75.0%** in *both* modes — the last three because R3 finally binds
a model held in a bare function parameter, which is what `validate(model, loader)`
needs.

### 8.3 · The public corpus: zero new high findings

37 pinned third-party repositories, 112 targets, three modes, **260 runs**,
`main`'s analyzer against this tree, the dataflow mode spelled explicitly on
both sides so the comparison is of two trees and not of two analyses (§3.11 R1.4):

| mode | findings before → after | new | **new `high`** | removed |
|---|---|---|---|---|
| `ip` (default) | 285 → **291** | 6 | **0** | 0 |
| `local` | 286 → **292** | 6 | **0** | 0 |
| `notebooks` | 213 → **212** | 2 | **0** | 3 |

The three removed high findings are `peft`'s duplicated MLV401 — R20 collapsed
them to one finding per root cause — and with them go **four schema/invariant
violations** the baseline produced: `ids: duplicate issue ids` on two `peft`
notebook runs. The strict gate's blocking count falls **47 → 43** and **every
one of the 43 is also in the baseline**: they are the adjudications of a
sibling branch whose rules this one does not carry, so they measure the branch
gap and not this change.

**One host bug this flushed out, and it is R1.2 in the field.** The corpus
runner spells `local` *by omission* — it appends `--dataflow ip` for the `ip`
column and nothing for the other two. With the default flipped, its `local` and
`notebooks` columns silently became `ip` runs. That is exactly the failure
§3.11 R1.2 names ("a host that needs the narrower analysis passes it
explicitly"), it is a one-line fix in that runner, and the figures above are
measured with the mode spelled on both sides.

### 8.4 · What this wave did not close

* **MLV402 has no label in this corpus** (§8.2), so one of the seven targets is
  unevaluated rather than met.
* **`hydra_research`'s decorator registry** — §7.4. One hand-labelled op and
  four labels (MLV301 / MLV302 / MLV501 / MLV401) still ride on it.
* **`keras_tfdata/pipeline.py:40`** — a `tf.data` normalise closure that
  captures a mean and std computed over every row. It is a closure-capture
  shape, not a split-or-return shape, and nothing here attempts it.
* **MLV306 cannot type a fully inline chain** like
  `roc_auc_score(y, hard_labels(m, x).numpy())` when the inner `.argmax()` sits
  on a receiver that never resolves: no FQN, so no `PREDS` tag, and
  `valuetype` mints no tag from a method name (§5.3 A13). A knowledge-table row
  for an unresolved `.argmax` would close it.
* **The corpus is still 15 programs and 78 labels.** Every figure in this
  section is measured on it, and growing the unseen half remains the cheapest
  recall work on the board.
