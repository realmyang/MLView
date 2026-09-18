> Historical record: the static analyzer was removed on 2026-09-18.
> Commands, paths, and compatibility promises below describe earlier revisions.
> See [current status](STATUS.md) for the supported product.

# Expanding coverage and improving accuracy

**A research review of MLView's rule catalog and analysis accuracy.**
Branch `research`, 2026-09-15. Evidence-first: every claim resolves to a numbered
source in [`docs/research/sources.md`](research/sources.md) or to a local
measurement whose command is printed in §2. No claim rests on recollection.

---

## 1. Executive summary

### 1.1 What MLView covers today, in numbers

All figures reproduced on this machine on 2026-09-15 (§2, M1–M3).

| Measure | Value |
|---|---|
| Shipped rules | **36** (`MLV101`–`MLV803`), plus `MLV999` |
| Catalogued but unbuilt codes | **50** (`ISSUE_RULES.md` §4) [110] |
| Knowledge rows / distinct roles | **1,263** FQN rows + **880** method rows, **76** roles |
| Labelled corpus | **158** programs, **546** scored labels, **2,327** `forbidden` rows [120] |
| Recall (`--dataflow ip`, default) | **80.4 %** overall, **79.2 %** on unseen programs |
| Visible recall (confidence ≥ 0.60) | **72.5 %** overall, **70.9 %** unseen |
| Precision | **100.0 %**, 0 forbidden findings, 0 unlabelled findings |
| Graph fidelity | **1,072 / 1,166 = 91.9 %** over the 66 programs with a labelled graph |
| Public precision gate | 37 pinned repositories, 4,467 parsed `.py` files, **260** runs, **706** findings, **0** adjudicated false positives |

Twelve of the 36 rules sit at 100 % recall (`MLV111`, `MLV121`, `MLV204`,
`MLV207`, `MLV209`, `MLV502`, `MLV602`, `MLV701`, `MLV702`, `MLV706`, `MLV707`,
`MLV711`) and account for 114 labels — 20.9 % of the corpus with nothing left to
win. The 107 misses concentrate in thirteen rules; five of them are below 50 %:

| Rule | Labels | Recall | Unseen |
|---|---|---|---|
| `MLV305` metric on the wrong operand | 15 | **20.0 %** | 14.3 % |
| `MLV208` AMP GradScaler protocol | 7 | **28.6 %** | 16.7 % |
| `MLV402` sigmoid/BCE pairing | 11 | **36.4 %** | 36.4 % |
| `MLV114` augmentation on the eval path | 17 | **41.2 %** | 37.5 % |
| `MLV103` CV over preprocessed data | 9 | **44.4 %** | 37.5 % |

### 1.2 The three biggest coverage gaps

**Gap 1 — evaluation-integrity leakage that is not a fit-before-split.**
MLView has four leakage rules and all four are variants of "a transformer was
fitted on the wrong rows". The literature's taxonomy has eight types [95]; the
one most prevalent in the wild is the one MLView does not implement at all:
the held-out split steering early stopping or best-model selection (`MLV107`,
catalogued, unbuilt). **Measured size:** `MLV107` is the single most-cited
unbuilt code in the corpus's own gap records — 6 of 173 "no rule models this"
rows name it (M6). On the public corpus, 91 call sites across 7 repositories
pass a test-named value to `eval_set=` / `validation_data=` / `eval_dataset=`,
and 6 of those also carry a selection mechanism in the same file (M4).
Nothing in the catalog covers group leakage, resampling-before-split,
target-derived features, or mask-based splits either. This is the family
MLView is *known for* and it is the thinnest.

**Gap 2 — the deliver stage is empty.**
Not one of the 1,263 knowledge rows covers `torch.onnx.export`,
`torch.jit.trace`, `torch.jit.script`, `torch.export.export` or
`torch.ao.quantization.*` (M5). **Measured size:** 78 export/trace/script call
sites across 13 of 37 public repositories; 35 of them appear in a file with no
`.eval()` anywhere (M4). Exporting a module in train mode bakes a live dropout
node and the last training batch's BatchNorm statistics into the shipped
artifact — the exporter warns about it itself [13] — and MLView has neither a
rule nor a graph node for it. Two corpus programs (`adv_qat_bad`,
`vision_onnx_service_bad`) record this as the worst defect present and
unrulable.

**Gap 3 — the auxiliary-network family.**
A second model that must not be trained — a distillation teacher, a DPO
reference policy, an RL target network, a MoCo key encoder, a perceptual VGG —
forwarded with gradients on, not detached, not frozen. **Measured size:** the
largest single cluster in the corpus's 173 unrulable-defect rows, spanning 11
programs (`adv_distill_bad`, `adv_dpo_bad`, `adv_moco_bad`, `adv_dqn_bad`,
`adv_sac_bad`, `adv_ppo_bad`, `nlp_distil_bert_bad`, `nlp_dpo_preference_bad`,
`vision_gan_bad`, `vision_superres_bad`, `vision_simclr_bad`). No rule in the
36, and no sketch in the 50, covers any of it. Nothing in Humbatova [86],
NeuraLint [93], dslinter [75] or SpecDetect4AI [84] covers it either — this
family comes from MLView's own domain testers, and the honest attribution is
to them.

### 1.3 The three biggest accuracy blockers

All 107 missed labels were read against the source and the blocking rule
predicate, and classified into seven causes (M7). One label is 0.183 recall
points.

**Blocker 1 — the rule predicate is narrower than the IR.** 35 of 107 misses
(32.7 % of the gap, **6.4 recall points**). The shape is present in the IR and
the rule does not look at it: `MLV208` never implemented its fp16-without-a-
scaler variant (5 misses); `MLV601` accepts a scoped `env.reset(seed=…)` as a
workspace seed (4); `MLV114` reads only three keyword names for a transform
(4); `MLV402`/`MLV401` do not follow a workspace loss wrapper (7). These are
rule edits, not analysis research.

**Blocker 2 — value identity dies at an expression boundary.** 22 of 107
(20.6 %, **4.0 points**). A `[:, 1]`, a `.view(-1)`, an `outputs.loss`, or a
`loss = criterion(...) / ACCUM_STEPS` terminates the producer chain.
`MLV305` loses 10 labels to this alone and is the worst rule in the catalog at
20.0 %. `rules/valuetype.py` already follows a `.detach().cpu().numpy()` tail
[119]; it stops one expression short of the shapes that matter.

**Blocker 3 — the evaluation region is defined by name and metric.** 16 of 107
(15.0 %, **2.9 points**), concentrated in the two rules with the most labels in
the whole corpus (`MLV301`: 46, `MLV302`: 44). `_EVAL_NAME_RE` [118] matches
`validate|evaluate|val|test|predict|infer|score`; a diffusion sampler
(`p_sample_loop`), a VAE `sample()`, a GAN `sample_grid()`, a retrieval
`encode_texts()` and a `generate()` loop are all inference and match none of
them.

And one more that is not a miss at all: **43 of 439 recovered true positives
are computed and then hidden** below the 0.60 Problems-panel threshold — the
entire 80.4 % → 72.5 % gap — and every one of the 43 is a true positive (M1).
`MLV301` loses 13 of its own 34 hits this way (38 %).

### 1.4 Two confirmed defects in shipped rules

Found while calibrating, reproduced in this session, and each verified against
primary documentation. These are not candidates; they are bugs.

**D1 — `MLV306` fires `certain` on correct Keras code, and `MLV305` goes silent
on a real bug, from one knowledge row.** `other_tbl.py:45` [114] tags
`keras.Model.predict` as `PREDICT → ("PREDS",)` — hard labels. Keras `predict()`
returns the network's output: probabilities from a softmax/sigmoid head, logits
from a bare `Dense`. Measured (M8):

```
keras_auc.py   roc_auc_score(y_test, model.predict(X_test))       <- CORRECT [30]
  -> [i] MLV306 certain keras_auc.py:15  Ranking metric fed hard labels    FALSE POSITIVE

keras_acc.py   accuracy_score(y_test, model.predict(X_test))      <- REAL BUG (softmax head)
  -> 0 issue(s) ... none found                                             FALSE NEGATIVE
```

The project has already made this exact fix once. `gbm_tbl.py:109–118` [113]
carries the comment: *"the native `Booster.predict` returns the margin or
probability, not a class… Tagging it PREDS made MLV306 fire at 0.90 on
`float(roc_auc_score(test_y, booster.predict(dtest)))`, which is the
textbook-correct way to score a booster."* The Keras twin was never swept.
`transformers.Trainer.predict` (`other_tbl.py:104`) and the statsmodels
`.predict` rows carry the same latent risk.

**D2 — `MLV106`'s splitter table has the two group splitters backwards.**
`holdout_splits.py:73–77` [115] puts `GroupShuffleSplit` in
`_SHUFFLE_OPTIONAL_SPLITTERS`, so an absent `shuffle=` reads as False and
`MLV106` is suppressed — but `GroupShuffleSplit` has **no `shuffle` parameter
at all** and always shuffles [22]. `StratifiedGroupKFold` is in neither set, so
it falls through to "can shuffle" — but its `shuffle` defaults to **False**
[23]. Measured (M9), on two fixtures identical but for the splitter:

```
StratifiedGroupKFold, temporal signals -> [!] MLV106 possible sgkf.py:10   FALSE POSITIVE
GroupShuffleSplit,    temporal signals -> (no MLV106)                      FALSE NEGATIVE
```

A third, milder finding: `MLV803`'s `torch.load` arm skips whenever
`weights_only` is present — so the one genuinely unsafe spelling,
`weights_only=False`, is invisible — and accuses the bare call of unpickling
arbitrary objects, which [1] shows is false on current PyTorch, where the
default is `weights_only=True` (M10, [116]).

### 1.5 Recommendation

Do the repairs first, then the leverage, then the coverage — in that order,
because the first two cost almost nothing and the third is priced by them.

1. **Repair (days).** D1, D2, and the `MLV803` message split. Each is a
   knowledge row or a table entry; each has a reproduced fixture; none needs new
   analysis. D1 in particular converts a `certain` false positive into a
   recovered true positive with one edit.
2. **Leverage (one sprint).** Three IR changes buy **~11 recall points** between
   them and are each smaller than a new rule: widen the evaluation region
   (§6.3, 16 labels), carry value identity through subscripts and shape ops
   (§6.1, 22 labels), and stop the interprocedural summary from intersecting
   identity tags (§6.1, 6 labels). Then re-scope the wrapper confidence de-rate
   (§6.6) to recover the 43 hidden true positives, which is worth another 7.5
   points of *visible* recall with no new detection at all.
3. **Coverage (two sprints).** Ship the ten tier-1 rules in §5 — all of them
   measured at zero or near-zero false-positive exposure on the pinned
   corpus — then the tier-2 set behind the guards this document prices.

The single most important methodological change is smaller than any of them:
**measure the naive form of a candidate rule on the 37 pinned repositories
before writing it** (§7.2). That method is what found D1 and D2, and in three
separate cases in §5 it changed the rule's design by an order of magnitude —
`MLV107` from 91 candidate sites to 6, `MLV117` from 228 to a recommendation not
to ship, a `zip`-truncation rule from 713 to 3.

---

## 2. Method

### 2.1 What was read

- **The tree.** `docs/ISSUE_RULES.md` (36 shipped rules in §3, 50 sketches in
  §4, the twelve-box authoring checklist in §5) [110]; `docs/ACCURACY.md`
  (corpus, label format, §9's named blockers) [111]; `docs/CONTRACTS.md` v1.1
  (the IR, the rule API, the confidence model, the five iron laws) [112]; and
  the implementing modules for every rule with a miss — `r_leakage.py`,
  `leakage_paths.py`, `r_eval.py`, `eval_regions.py`, `r_trainloop.py`,
  `r_mechanics.py`, `r_repro.py`, `r_holdout.py`, `holdout_splits.py`,
  `valuetype.py`, `loss_chain.py`, `helpers.py`, `confidence.py`,
  `ir/summaries.py` and the thirteen knowledge tables.
- **Primary framework documentation.** 68 entries in §A–§E of the bibliography,
  spanning PyTorch 2.14, scikit-learn 1.9, Keras 3, TensorFlow, HuggingFace
  Transformers/Datasets/Accelerate, Lightning, pandas 3, XGBoost, LightGBM,
  CatBoost, MONAI, timm, Prophet, statsmodels, and the Python standard library.
- **Prior-art rule catalogs.** TorchFix (15 codes) [69][70], SonarSource's
  ML-tagged Python rules (31 of 450) [71][72], ruff PD+NPY (17) [74],
  dslinter / Zhang et al. (22 smells) [75], UMLAUT's own `heuristics.py` [77],
  NeuraLint (23 rules) [93], TheDeepChecker (19 issues) [94], MLScent (76
  detectors) [83], SpecDetect4AI (22 smells) [84], Pynblint [78], Deepchecks
  [80], Great Expectations [81].
- **Peer-reviewed literature.** 24 entries in §G, including the two taxonomies
  that set the severity ordering in §4 — Humbatova et al. [86] and Kapoor &
  Narayanan [95].

### 2.2 What was measured

Every command below was run on this machine on 2026-09-15 and its output is
what this document cites. All commands are prefixed by:

```sh
cd /path/to/MLView
. .venv/bin/activate
export PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
```

**M1 — the accuracy baseline, with every miss listed.**

```sh
python tools/accuracy.py --verbose > $SCRATCH/acc_ip.txt
```
> 158 programs, 546 labels. overall recall **80.4 %**, visible **72.5 %**,
> high+medium **74.3 %**, precision **100.0 %**; unseen 515 labels, recall
> **79.2 %**, visible **70.9 %**. Graph fidelity 1,072/1,166 = **91.9 %**.
> Calibration: `certain` n=221 / 100.0 % observed, `likely` n=155 / 100.0 %,
> `possible` n=46 / 100.0 %, `speculative` n=17 / 100.0 %.
> `accuracy gate: PASS`. 3.44 s user time. 107 missed labels and 95 missing
> graph ops printed in full.

**M2 — what the interprocedural pass actually buys.**

```sh
python tools/accuracy.py --dataflow local
```
> overall **78.2 %**, visible 70.7 %, unseen 76.9 %. So `--dataflow ip` gains
> **+2.2 points** (12 labels) and every one of the 12 is `MLV101`/`MLV102`/
> `MLV103`. The IP pass is a leakage-family pass; it buys nothing for the
> `MLV2xx`/`MLV3xx`/`MLV4xx` families, where 55 of the 107 misses live.

**M3 — catalog and knowledge-table size.**

```sh
python -m mlview rules | wc -l
python -c "import sys; sys.path.insert(0,'analyzer/src'); import mlview.knowledge as K; \
           print(len(K.KNOWLEDGE), len(K.METHODS))"
```
> 36 user rules; 1,263 FQN rows, 880 method rows, 76 distinct roles.
> Framework spread: tf 284, torch 233, other 192, hf 169, keras 136,
> sklearn 106, pandas 28, torchvision 24, lightning 24, torchmetrics 20,
> numpy 17, xgboost 13, lightgbm 9, imblearn 4, albumentations 4.

**M4 — AST prevalence sweep over the 37 pinned public repositories.**
A reusable, execution-free scanner implementing 28 candidate shapes.

```sh
python $SCRATCH/sweep.py .public-corpus        # 4,471 files seen, 4,467 parsed, 16 s
python $SCRATCH/sweep.py analyzer/tests/accuracy/corpus   # 357 files
```
Selected counts (public corpus, `count / repositories affected of 37`):

| shape | public | labelled corpus |
|---|---|---|
| unsorted `os.listdir` / `glob.glob` | **563** / 23 | 16 / 12 |
| `nn.init.constant_/zeros_/ones_` on a `.weight` | **110** / 10 | 1 / 1 |
| test-named value into `eval_set=` family | **91** / 7 | 2 / 2 |
| `torch.onnx.export` / `jit.trace` / `jit.script` / `export.export` | **78** / 13 | 5 / 5 |
| …of those, in a file with no `.eval()` anywhere | **35** / 11 | — |
| Keras `fit(validation_split=…)` | **55** / 2 | 0 |
| Keras `EarlyStopping` with no `restore_best_weights` | **34** / 4 | 1 / 1 |
| `DataLoader(drop_last=True)` | 31 / 7 | 64 / 55 |
| `cudnn.benchmark = True` | 20 / 7 | 1 / 1 |
| …of those, in a file that also seeds | **4** / 4 | 1 / 1 |
| `DistributedSampler` with shuffling | 19 / 9 | 4 / 4 |
| …with no `set_epoch` in the same file | **5** / 3 | 1 / 1 |
| callback `monitor=` a training metric | **18** / 1 | 0 |
| `TrainingArguments(load_best_model_at_end=True)` | 17 / 3 | 1 / 1 |
| direct `self.<sub>.forward(x)` | **14** / 5 | 0 |
| tf.data `.cache()` after `.shuffle()` | **12** / 1 | 0 |
| `onnx.export` with neither `dynamic_axes` nor `dynamic_shapes` | **11** / 5 | — |
| `F.dropout` with no `training=` | **9** / 4 | 0 |
| `autocast(dtype=torch.float16)` explicit | 8 / 4 | 15 / 11 |
| test-named `eval_set=` **and** a selection mechanism | **6** / 3 | 2 / 2 |
| tf.data `.shuffle()` after `.batch()` (excluding `batch(1)`) | **4** / 1 | 0 |
| `fillna(<frame statistic>)` | **2** / 1 | 0 |
| `groupby(...).transform(...)` | 1 / 1 | 4 / 2 |
| `imblearn` `fit_resample` | **0** | 2 / 2 |
| `require_grad =` (the typo) | **0** | 0 |
| `DataLoader(shuffle=True, sampler=…)` | **0** | 0 |
| `load_best_model_at_end` with an inconsistent strategy | **0** | 0 |

The four zero rows are the rules that can ship against the precision gate at
literally no cost. The 563-row and 110-row shapes are the ones whose naive form
must never ship.

**M5 — knowledge-table gap probe.** 21 FQNs the candidate rules need:

```sh
python -c "<probe KNOWLEDGE and METHODS for each name>"
```
> **MISS** (all of them): `torch.onnx.export`, `torch.jit.trace`,
> `torch.jit.script`, `torch.export.export`, `torch.cuda.synchronize`,
> `torch.cuda.empty_cache`, `torch.backends.cudnn.benchmark`,
> `torch.utils.checkpoint.checkpoint`, `sklearn.metrics.roc_curve`,
> `sklearn.metrics.precision_recall_curve`,
> `sklearn.preprocessing.TargetEncoder`, `numpy.random.Generator`,
> `sklearn.model_selection.{StratifiedGroupKFold, GroupShuffleSplit,
> RepeatedKFold, PredefinedSplit, LeaveOneGroupOut}`, `monai.data.DataLoader`,
> `monai.transforms.Compose`, `keras.layers.TextVectorization.adapt`.
> Method names `set_epoch`, `fit_resample`, `adapt`, `generate`,
> `clear_session`, `empty_cache`: **all MISS**.
> **HIT**: `timm.data.create_transform`.
>
> Note that four of the missing `model_selection` names are *already written
> into rule source* — `holdout_splits.ORDERED_SPLITTERS` and
> `r_repro._SHUFFLE_OPTIONAL` name them as strings while the knowledge table
> has no row for them, so those entries are dead code today.

**M6 — the corpus's own record of what it cannot express** [120]**.**

```sh
python -c "<walk 158 labels.json for unsupported / gaps / unruledDefects>"
```
> **173 rows recording a real defect that no rule can express**, across
> **66 of 158 programs** (plus 19 rows that record correct code). Top
> `wouldBe` attributions: `UNRULED` (no code exists) 106, `MLV107` 6,
> `MLV201` 4, `MLV211` 4, `MLV802` 4, `MLV902` 4, `MLV301` 3, `MLV205` 3,
> `MLV101` 3, `MLV306` 3, `MLV901` 3, `MLV105` 2, `MLV117` 2, `MLV206` 2.
> This is the highest-signal rule-gap oracle in the project: the rows were
> written by domain testers against real defect shapes, not derived from a
> paper.

**M7 — root-cause classification of all 107 misses.** Each missed label was
read against its source and against the blocking predicate in the rule, then
assigned to one of seven causes. The mapping is explicit and reproducible:

```sh
python $SCRATCH/classify.py     # 107 of 107 classified, no residue
```

**M8 — the `MLV306`/`MLV305` Keras defect (two minimal fixtures).**

```sh
python -m mlview issues $SCRATCH/verify/keras_auc.py   # -> MLV306 certain  (FP)
python -m mlview issues $SCRATCH/verify/keras_acc.py   # -> 0 issues        (FN)
```

**M9 — the `MLV106` splitter-table defect (two fixtures identical but for the
splitter).**

```sh
python -m mlview issues $SCRATCH/verify/sgkf.py   # -> MLV106 possible      (FP)
python -m mlview issues $SCRATCH/verify/gss.py    # -> no MLV106            (FN)
```

**M10 — `MLV803`'s `torch.load` arm, read in source.**

```sh
grep -n -A22 'calls_of("torch.load")' analyzer/src/mlview/rules/r_mechanics.py
```
> `if "map_location" in call.kwarg_nodes or "weights_only" in call.kwarg_nodes:
> continue` — presence of either keyword skips, so `weights_only=False` is never
> judged; and the emitted message says the bare call "unpickles arbitrary
> objects", which [1] contradicts for torch ≥ 2.6.

**M11 — public-corpus findings aggregate.**

```sh
python -c "<aggregate issues[] from .public-corpus/_reports/graphs/*.json>"
```
> 260 reports, **706 findings**: 381 low / 276 medium / 49 high. By code:
> `MLV602` 180, `MLV803` 118, `MLV112` 85, `MLV110` 69, `MLV111` 51,
> `MLV708` 33, `MLV601` 32, `MLV301` 32, `MLV302` 25, `MLV401` 14, `MLV121` 12,
> `MLV103` 11. Note that `MLV803` is the second-largest contributor and §1.4
> shows its dominant arm is asserting something that is no longer true.

### 2.3 Honesty notes on the evidence

- **The AST sweep approximates a rule; it does not implement one.** Every count
  in M4 is an **upper bound** on the rule's firing rate: it matches on names
  where the real rule matches on resolved FQNs and dataflow tags, and it is
  file-scoped where several candidates are workspace-scoped. Where a clause
  could not be approximated (cross-module reachability, receiver identity across
  scopes, per-loop containment), this document says so and quotes no number.
- **Two claims in the source material could not be verified and are not used.**
  The per-class leakage effect sizes attributed to [109] are not in that paper's
  abstract and could not be checked; §5 cites the paper only for the existence
  of a measured effect-size ordering and quotes no number from it. The
  per-type prevalence breakdown from [96] is in the full text, not the abstract;
  where it appears it is marked.
- **The labelled corpus's prevalence is not a prior for real code.** `MLV111`'s
  shape appears in 20 of 158 corpus programs and 7 of 37 public repositories —
  a ~9× density difference, because the corpus was written for the rules.
  Prevalence claims in §5 therefore lead with the public number.
- **Nothing in this document has been implemented.** Every candidate still owes
  the twelve-box authoring checklist [110 §5], and §7.3 argues it owes a
  thirteenth box that does not exist yet.

---

## 3. Where the recall goes

### 3.1 Miss analysis: 107 labels, seven causes

Every missed label was opened, read against its rule's blocking predicate, and
assigned exactly one **primary** cause — the one that alone unblocks it. Where
a miss had two blockers the secondary is named in the candidate text in §5/§6.
The classification is reproducible (M7) and has no residue.

| # | Cause | Misses | % of gap | Recall pts | Rules affected |
|---|---|---:|---:|---:|---|
| **E** | Rule predicate is narrower than the IR | **35** | 32.7 % | **6.4** | `MLV208`×5, `MLV601`×4, `MLV402`×4, `MLV114`×4, `MLV102`×3, `MLV401`×3, `MLV203`×2, `MLV110`×2, `MLV305`×2, `MLV201`×2, `MLV112`, `MLV306`, `MLV708`, `MLV803` |
| **C** | Value identity lost at an expression boundary | **22** | 20.6 % | **4.0** | `MLV305`×10, `MLV205`×8, `MLV402`×2, `MLV401`, `MLV202` |
| **D** | Cross-scope / cross-module chain | **17** | 15.9 % | **3.1** | `MLV101`×7, `MLV103`×5, `MLV106`×2, `MLV709`×2, `MLV705` |
| **A** | Evaluation region not recognised | **16** | 15.0 % | **2.9** | `MLV301`×9, `MLV302`×7 |
| **B** | Bare parameter / IP summary intersection | **6** | 5.6 % | **1.1** | `MLV301`×2, `MLV302`×2, `MLV401`, `MLV501` |
| **G** | Needs shape/type inference or a domain convention | **6** | 5.6 % | **1.1** | `MLV114`×4, `MLV402`, `MLV401` |
| **F** | Knowledge-table gap | **5** | 4.7 % | **0.9** | `MLV114`×2, `MLV301`, `MLV302`, `MLV401` |
| | **Total** | **107** | 100 % | **19.6** | |

Read top-down, the table says something specific: **63 of 107 misses (causes E,
D and F) are edits to rules and tables, not analysis research.** A further 28
(causes C and A) are two small, well-bounded IR changes. Only 12 (causes B and
G) need work that could be called hard, and 6 of those are outside MLView's
declared design (§9.11).

#### Cause A — the evaluation region is not recognised (16 misses, 2.9 pts)

`rules/eval_regions.py` builds a region from a loop or function that (a) is
named by `_EVAL_NAME_RE` [118], (b) contains a metric call, or (c) carries a
`no_grad` decorator. Generative and retrieval inference is none of those.

| Program | Rules | The region |
|---|---|---|
| `vision_ddpm_bad` | `MLV301`, `MLV302` | `p_sample_loop()` — a 1,000-step sampler in train mode with gradients on |
| `vision_vae_bad` | `MLV301`, `MLV302` | `sample()` → `model.decoder(z)` → `save_image` |
| `vision_gan_bad` | `MLV301` | `sample_grid(netG, noise, epoch)` |
| `nlp_rag_index_bad` | `MLV301`, `MLV302` | `encode_texts()` — the retrieval encoder |
| `nlp_seq2seq_summarization` | `MLV301`, `MLV302` | `rouge_eval` calling `model.generate()` |
| `nlp_token_classification` | `MLV301`, `MLV302` | `token_accuracy()` |
| `vision_metric_bad` | `MLV301` | `extract()` — a re-ID feature extractor |
| `nlp_dpo_preference_bad` | `MLV302`, `MLV301` | `sample_completions()`; and `evaluate()` where only the *reference* model is `.eval()`'d |
| `nlp_distil_bert_bad` | `MLV301` | `evaluate()` where only the *teacher* is `.eval()`'d |

The last two are a distinct sub-cause worth naming: the region **is**
recognised, but the rule asks "does an `.eval()` exist here?" rather than "was
*this* model put in eval mode?". In a two-model program a single
`teacher.eval()` satisfies the region and the untrained student is never
checked. That is a two-line change (§6.3) worth 2 labels immediately and more
on the GAN/MoCo shapes.

#### Cause B — bare parameter, or the IP summary intersects the tag (6 misses)

`ir/summaries.py` applies the argument→parameter summary with **intersection**
across call sites — deliberately, for leakage precision. For provenance tags
(`TRAIN_SPLIT`, `TEST_SPLIT`, `FEATURES`) that is right: intersecting stops one
call site's `TRAIN_SPLIT` from laundering another's `TEST_SPLIT`. For identity
tags (`MODEL`, `OPTIMIZER`, `LOADER`, `DEVICE`) it is wrong — every call site
agrees about what *kind* of object it passes, so the intersection of two
differently-provenanced `MODEL` facts is empty and the parameter ends up
untagged. MLView reports this itself: of 44 `truncated` diagnostics corpus-wide,
36 carry the message *"is called from N sites whose arguments arrive through
different interprocedural chains; MLView does not merge them"*, and the lost
parameter is `device` 17×, `model` 8×, `loader` 4×.

`hydra_research` is the other half: the model comes from
`build_from_cfg('model', cfg['model'])`, a dict-of-factories registry, so it
carries no `MODEL` tag — yet `optimizer_for(model, cfg)` calls
`model.parameters()` thirteen lines away. Four labels (`MLV301`, `MLV302`,
`MLV501`, `MLV401`) and one missing graph node turn on one fact the IR could
duck-type from evidence it already has.

#### Cause C — value identity lost at an expression boundary (22 misses, 4.0 pts)

Four sub-shapes, all in the same place:

| Sub-shape | Misses | Example |
|---|---:|---|
| **Subscript** — a column select or a boolean mask | 5 | `accuracy_score(y, model.predict_proba(X)[:, 1])` — 4 programs, identical line |
| **Framework output object** — `.loss` / `.logits` on an HF `ModelOutput` | 6 | `loss = outputs.loss` then `loss.backward()`; `MLV205`, `MLV202`, `MLV305` |
| **Arithmetic with a scalar** — a BinOp drops `LOSS` | 8 | `loss = criterion(...) / ACCUM_STEPS`; `g_loss = w1*a + w2*b + c` |
| **Shape-preserving method** — `.view/.squeeze/.permute` | 3 | `return self.net(images).view(-1)` where `self.net` ends in `nn.Sigmoid` |

The subscript case is the cleanest demonstration that this is an IR problem and
not a rule problem: `rules/valuetype.py` [119] already carries a
`_PASSTHROUGH_METHODS = {detach, cpu, cuda, numpy, tolist, clone, contiguous}`
set with a documented rationale — *"the `.detach().cpu().numpy()` tail that
every torch program writes"*. It stops exactly one expression short.

#### Cause D — cross-scope / cross-module chain (17 misses, 3.1 pts)

Three shapes, each with a named guard that is currently doing too much work:

- **`MLV101`, 7 misses.** REV5-01 confined the fit↔split match to one scope
  because `_split_consuming` matches by *dotted name*, and a shared local name
  in two functions once produced a self-contradicting high-severity finding.
  The confinement is right for a name match and unnecessary for an identity
  match. All seven misses are cross-scope: `tabular_feature_store` fits an
  imputer, a scaler and an encoder on `self.frame` in one method and splits in
  another (3 labels); `tabular_automl_search` fits in `build_matrix()` and
  splits in `refit_best()` (2 labels — this is scikit-learn's own worked
  leakage example [20]); `tabular_seq_lstm_bad`; `keras_tfdata`.
- **`MLV103`, 5 misses, all one shape.** `features, target = prepare(path)` in
  one function; `cross_val_score(<bare estimator>, features, target)` in
  another. The rule refuses when the caller's binding does not record which
  tuple position it unpacked — a guard added to stop it blaming the wrong
  `fit_transform`. `ir/returns.py` already computes per-slot return values; the
  guard becomes *more* informed with slot identity, not less.
- **`MLV106`, 2 misses.** The rule requires two independent temporal signals in
  the **same module** as the split. Real projects parse dates in a feature
  module and split in a training module.

#### Cause E — the rule predicate is narrower than the IR (35 misses, 6.4 pts)

The largest cause and the cheapest to close. A representative sample:

| Rule | Misses | What the predicate does not look at |
|---|---:|---|
| `MLV208` | 5 | Three sub-variants unimplemented: fp16 autocast with no `GradScaler` anywhere; a second scaler in the same loop (`vision_superres_bad` has `d_scaler` and `g_scaler`); `clip_grad_norm_` with no preceding `unscale_` [5][55] |
| `MLV601` | 4 | `helpers.is_seeded()` [117] accepts **any** `seed=` keyword. `env.reset(seed=0)` seeds a gymnasium env; `datasets.train_test_split(seed=7)` seeds one split; a `tf.data.shuffle(seed=1)` seeds one shuffle. None seeds the process, and each silences the rule workspace-wide |
| `MLV402` | 4 | A hand-written `class MultiTaskLoss(nn.Module)` delegating to `nn.BCEWithLogitsLoss` is not recognised as a BCE-family loss |
| `MLV114` | 4 | Reads only `transform`/`transforms`/`target_transform`; misses `augment=`, positional arguments, and a Dataset whose augmentation is switched by a `train=True` constructor flag |
| `MLV201`/`MLV203` | 4 | Both bail out when the loop has more than one optimizer receiver — which is exactly the GAN, actor-critic and multi-head shape where the bug lives |
| `MLV110` | 2 | A loader returned directly from a factory has no binding name; a semi-supervised pool loader is a training loader with no name that says so |

#### Cause F — knowledge-table gap (5 misses)

MONAI accounts for 3 (`vision_medical3d_bad`: `monai.data.DataLoader` is not a
`DataLoader`, so the `LOADER` tag never exists and the whole `MLV1xx` family
plus every `MLV2xx` rule keyed on it is unreachable [63]); `timm`'s
`create_transform(is_training=True)` for 1 [64]; `CTCLoss`'s input contract for
1 [8]. Graph fidelity tells the same story more loudly — the five worst-scoring
programs are all table gaps: `nlp_instruction_sft` 38.5 % (trl/peft),
`tabular_survival_cox` 52.9 % (lifelines/sksurv, eight missing ops),
`adv_sac_clean` 56.0 %, `nlp_rag_index` 58.3 % (faiss), `tabular_online_sgd`
61.5 %.

#### Cause G — beyond MLView's declared design (6 misses)

Honest exclusions, not backlog. A horizontal flip that mirrors keypoint
coordinates without swapping the left/right joint channels (`vision_pose_bad`,
2 labels); a paired super-resolution augmentation applied to one member of the
tuple (1); a segmentation head emitting 1 channel while the loss one-hots to 14
(1, needs shape inference); a cosine similarity scaled by 20 fed to `nn.BCELoss`
(1, needs range inference). Zhang et al. [88] reach the same conclusion from the
other direction: dimension mismatch and type confusion are the static-amenable
classes, and MLView deliberately has no shape lattice.

### 3.2 The 95 missing graph ops

Graph fidelity is 91.9 % — but over the **66 of 158 programs that carry a
labelled graph**. The 92 unlabelled programs include every RL program, most
infra programs and most `_bad` vision twins, i.e. the domains where the IR is
weakest. The headline is measured on the easier half; see §7.4.

Of the 95 missing ops, the concentration is extreme: **39 come from five
programs**, all of them knowledge-table gaps — `adv_sac_clean` 11,
`tabular_survival_cox` 8 (the entire `lifelines`/`sksurv` surface),
`nlp_instruction_sft` 8 (trl/peft), `tabular_online_sgd` 5,
`tabular_anomaly_iforest` 5 (`LocalOutlierFactor`, `EllipticEnvelope`). A
second cluster of 7 is one shape MLView does not model at all: a **boolean or
quantile timestamp cut used as a split** —

```python
cutoff = frame["event_time"].quantile(0.9)
train  = frame.loc[frame["event_time"] <  cutoff]
test   = frame.loc[frame["event_time"] >= cutoff]
```

This is the *correct* temporal split, it is how five corpus programs partition
their data, and MLView draws no split node and mints no `TRAIN_SPLIT`/
`TEST_SPLIT` tags for it — so every rule keyed on those tags is blind to the
entire class of programs that split without `train_test_split`. See §6.1 (IR-6).

### 3.3 Calibration: 43 true positives found and then hidden

The referee's calibration block (M1):

| Bucket | n | true pos | false pos | mean confidence | observed precision | calibration error |
|---|---:|---:|---:|---:|---:|---:|
| `certain` | 221 | 221 | 0 | 0.934 | 100.0 % | 0.066 |
| `likely` | 155 | 155 | 0 | 0.826 | 100.0 % | 0.174 |
| `possible` | 46 | 46 | 0 | 0.600 | 100.0 % | 0.400 |
| `speculative` | 17 | 17 | 0 | 0.352 | 100.0 % | 0.648 |

The model is under-confident in every bucket, and the cost is paid entirely in
visible recall. 439 labels are recovered; 396 are visible; **43 correct findings
are computed and then kept off the Problems panel by the ≥ 0.60 threshold.**
That is the whole 80.4 % → 72.5 % gap, and it is 7.9 points of visible recall.

Per rule (`found` − `visible`):

| Rule | found | visible | hidden | share of its own hits |
|---|---:|---:|---:|---:|
| `MLV301` | 34 | 21 | **13** | 38.2 % |
| `MLV601` | 43 | 35 | **8** | 18.6 % |
| `MLV111` | 26 | 21 | 5 | 19.2 % |
| `MLV302` | 34 | 29 | 5 | 14.7 % |
| `MLV110` | 25 | 22 | 3 | 12.0 % |
| `MLV114` | 7 | 4 | 3 | 42.9 % |
| `MLV501` | 11 | 9 | 2 | 18.2 % |
| `MLV103`, `MLV106`, `MLV201`, `MLV205` | — | — | 1 each | — |

The mechanism is legible in the evidence vectors and is dominated by one
factor. `rules/confidence.py` multiplies an absence rule's confidence by
`WRAPPER_FACTOR = 0.4` when "an absence rule sees a framework wrapper", and the
test is **workspace-wide**. A hand-written evaluation loop in a project that
merely *imports* `transformers.Trainer` is de-rated to
`0.85 × 0.7 (class_base) × 0.4 = 0.238` and disappears — even though the
finding is about code the Trainer never touches. `MLV601` lands at
`0.90 × 0.4 = 0.36` in six programs by the same route.

Two cautions before anyone reaches for the dial. First, a bucket at 100 %
observed precision on n=17 is weak evidence; the referee says so itself
(*"at this corpus size a bucket can hold two findings, so a single label flips
its observed precision by half"*). Second, the corpus is labelled exhaustively
so that an unlabelled finding counts as a false positive — it is designed to
make precision *measurable*, not to be a natural distribution. The
recalibration in §6.6 is therefore scoped as a **targeting** fix (apply
`WRAPPER_FACTOR` only where the wrapper governs the region) rather than a
**threshold** fix, and the public corpus is its veto.

---

## 4. Coverage matrix

Defect classes drawn from the two taxonomies that have practitioner validation —
Kapoor & Narayanan's eight leakage types [95] and Humbatova et al.'s fault
taxonomy [86] — plus the four rule catalogs that overlap MLView's territory
(dslinter [75], TorchFix [69], SonarSource's ML-tagged rules [71], NeuraLint
[93]). "Candidates" are the identifiers used in §5; `§6.x` means the fix is an
IR, knowledge or calibration change rather than a rule.

Legend: **&#9679;** shipped and measured &middot; **&#9680;** shipped but narrow
(a named miss cluster in §3) &middot; **&#9675;** catalogued, unbuilt &middot;
**&mdash;** no rule and no sketch.

### 4.1 Leakage (Kapoor & Narayanan's taxonomy [95])

| Type | MLView today | Recall | Candidates |
|---|---|---|---|
| L1.2 preprocessing fitted on train+test | &#9679; `MLV101` (fit before split), `MLV102` (fit on holdout) | 77.4 % / 70.0 % | §6.1 IR-3 (cross-scope identity), **C-23** (whole-frame pandas statistics) |
| L1.2 CV over pre-processed data | &#9680; `MLV103` | **44.4 %** | §6.1 IR-3 (tuple-slot identity), §6.5 (widened producer set) |
| L1.3 feature selection on train+test | &#9680; `MLV101` covers it *if* the selector resolves as a transformer | — | scikit-learn's own worked example [20] is a corpus miss (`tabular_automl_search:51`) |
| L1.1 no clean separation — **selection on the holdout** | **&mdash;** | — | **C-02** (`MLV107`), **C-30** (threshold tuned on test) |
| L1.1 no test set at all | &#9675; `MLV304` | — | tier 3 |
| L1.4 duplicates / resampling across the cut | &#9675; `MLV104` | — | **C-01** |
| L2 illegitimate features — target in `X`, or a target-derived statistic | &#9675; `MLV105` (arm 1 only) | — | **C-21** |
| L3.1 temporal leakage — the split | &#9680; `MLV106` | **50.0 %** | §6.1 IR-3 (cross-module signals), §6.5 (splitter table, **defect D2**) |
| L3.1 temporal leakage — the **features** | **&mdash;** | — | **C-22** (unlagged rolling target), **C-23** (backward fill) |
| L3.2 non-independence — group / entity leakage | **&mdash;** | — | **C-20** |
| L3.2 non-independence — mask / index splits (GNN, meta-learning) | **&mdash;** | — | **C-35** |
| L3.3 sampling bias in the test distribution | **&mdash;** | — | out of scope (needs the data) |
| Fit on train, test never transformed | **&mdash;** | — | **C-25** — scikit-learn's *first* pitfall [20] |
| tf.data holdout reshuffled | &#9679; `MLV121` | 100 % | **C-11**, **C-12** extend the same chain walk |

MLView's four shipped leakage rules all sit inside L1.2. Seven of the eight
types are unaddressed or partial. The literature's judgement of which matters
most is not MLView's: Kapoor & Narayanan find leakage across 17 fields and 294
papers [95]; Yang et al. find it "pervasive" across over 100,000 public
notebooks [96]; and [109] — verified to exist, whose per-class effect sizes this
document does **not** quote because they could not be checked — states that its
constraints are grounded in *measured effect sizes*, which is itself an argument
that the eight classes are not interchangeable.

### 4.2 Training-loop mechanics

| Defect class | MLView today | Candidates | Prior art |
|---|---|---|---|
| Gradients not cleared | &#9679; `MLV201` 89.5 % | **C-10** (per-optimizer lanes) | dslinter [75] |
| Backward without step; step before backward | &#9679; `MLV202`, `MLV203` (50 % each) | **C-10** (per-lane) | — |
| Backward under `no_grad` | &#9679; `MLV204` 100 % | — | — |
| Loss accumulated as a live tensor | &#9679; `MLV205` 73.3 % | §6.1 IR-1/IR-2 (arithmetic, output objects) | — |
| Scheduler cadence | &#9679; `MLV207` 100 % | — | *rejected*: the ordering variant (§9.6) |
| AMP: scaler protocol | &#9680; `MLV208` **28.6 %** | **C-10** — three unbuilt sub-variants | [4][5][55] |
| AMP: clipping position | &#9679; `MLV209` 100 % | **C-10** (the `unscale_` arm) | Lightning #9330 [55] |
| Backward inside `autocast` | **&mdash;** | **C-10** (1 measured site) | [4] |
| Gradient accumulation: loss not scaled | **&mdash;** | tier 2 | [50] |
| Auxiliary network with gradients on | **&mdash;** | **C-13** | *none — MLView's own corpus* |
| Target tensor not detached | **&mdash;** | **C-24** | *none* |
| Parameters no optimizer owns, or owns wrongly | &#9675; `MLV211` (rebinding arm only) | tier 2 | NeuraLint rule 11 [93] |
| Loss never back-propagated | &#9675; `MLV206` | tier 2, blocked on §6.1 IR-2 | — |
| EMA / target-network protocol | **&mdash;** | tier 2 | *none* |
| Recurrent model, no gradient clipping | &#9675; `MLV210` | advisory | — |
| `require_grad` typo | **&mdash;** | **C-05** | TorchFix TOR002 [69] |

### 4.3 Evaluation and held-out integrity

| Defect class | MLView today | Candidates |
|---|---|---|
| Eval loop without `eval()` / `no_grad` | &#9679; `MLV301` 73.9 %, `MLV302` 77.3 % | **§6.3** — widen the region (16 labels), judge per model value |
| `train()` never restored | &#9675; `MLV303` | **C-29** — blocked on the order-aware pass |
| Metric on the wrong operand | &#9680; `MLV305` **20.0 %**, `MLV306` 87.5 % | **§6.1 IR-1** (subscripts), **§6.5 defect D1** (framework-aware producer test) |
| Only accuracy on an imbalanced problem | &#9675; `MLV307` | advisory, tier 3 |
| Metric inappropriate for the task | &#9675; `MLV308` | tier 3 |
| Loaded checkpoint used with no mode call | **&mdash;** | tier 3 — **do not adopt Sonar S6982 as stated** (§9.1) |
| Checkpoint selected on a training metric | &#9675; `MLV802` | **C-19** |
| Best weights never restored | &#9675; `MLV802` variant | **C-19** |
| Export in train mode | **&mdash;** | **C-08** |
| Export with static shapes | **&mdash;** | **C-32** |
| Threshold tuned on the reported split | **&mdash;** | **C-30** |

### 4.4 Data and loader hygiene

| Defect class | MLView today | Candidates |
|---|---|---|
| Training loader does not shuffle | &#9679; `MLV110` 92.6 % | §6.5 (factory return, pool loader) |
| Eval loader shuffles | &#9679; `MLV111` 100 % | **C-12** (the tf.data twin) |
| `num_workers` without a `__main__` guard | &#9679; `MLV112` 94.7 % | — |
| `drop_last` on an eval loader | &#9675; `MLV113` | tier 2 |
| Custom Dataset missing `__len__` / `__getitem__` | &#9675; `MLV115` | **C-06** (measured 0 FP over 178 subclasses) |
| Augmentation on the eval path | &#9680; `MLV114` **41.2 %** | **§6.5** (kwarg surface, positional args, split flag) |
| `shuffle=True` **and** a sampler | **&mdash;** | **C-04** (measured 0 FP; raises at construction) |
| `DistributedSampler` without `set_epoch` | **&mdash;** | **C-09** |
| Multi-worker loader, unseeded non-torch RNG | &#9675; `MLV604` | **C-26** |
| IterableDataset duplicated across workers | **&mdash;** | tier 3 [2] |
| Keras `fit` argument silently ignored | **&mdash;** | **C-15** |
| Keras `fit` on an infinite dataset, no `steps_per_epoch` | **&mdash;** | **C-16** |
| Keras `validation_split` on ordered data | **&mdash;** | **C-18** |
| tf.data shuffle after batch / cache after shuffle | **&mdash;** | **C-11**, **C-12** |
| Unsorted file / label ordering | **&mdash;** | **C-27** — narrow form only (563 raw sites) [67] |
| Unstratified split | &#9675; `MLV117` | *do not ship as sketched* (§9.7) |

### 4.5 Reproducibility

| Defect class | MLView today | Candidates |
|---|---|---|
| Nothing seeded | &#9679; `MLV601` 91.5 % | **C-07** — the `is_seeded` loophole [117] |
| Split without `random_state` | &#9679; `MLV602` 100 % | §6.5 (HF `datasets.shuffle`; a `RandomState` instance shared across CV calls) |
| Partial seeding | &#9675; `MLV603` | **C-07** |
| Worker seeding | &#9675; `MLV604` | **C-26** |
| Nondeterministic backend with a determinism request | &#9675; `MLV605` | **C-34** |
| `use_deterministic_algorithms` without `CUBLAS_WORKSPACE_CONFIG` | **&mdash;** | tier 3, advisory [16] |
| Seed set after the splitter | **&mdash;** | tier 3 — and *not* the DataLoader variant (§9.13) |

### 4.6 Model definition, framework and device

| Defect class | MLView today | Candidates |
|---|---|---|
| `nn.Module` missing `super().__init__` | &#9679; `MLV701` 100 % | — |
| Submodules in a plain list | &#9679; `MLV702` 100 % | — |
| `F.dropout` without `training=` | &#9675; `MLV703` | **C-03** |
| Direct `.forward()` call | **&mdash;** | **C-33** (advisory) [75][7] |
| Constant / zero weight initialization | **&mdash;** | tier 3 — NeuraLint rule 1 [93]; 110 raw sites, needs the norm-layer exclusion |
| Missing / redundant activation | **&mdash;** | out of scope (no shape lattice) [88] |
| Activation contradicts the loss | &#9679; `MLV401` 53.3 %, `MLV402` 36.4 %, `MLV709` 60 % | **C-14** (`CTCLoss`/`NLLLoss`/`KLDivLoss`), §6.5 (workspace loss wrappers) |
| Keras metric contradicts `from_logits` | **&mdash;** | **C-17** |
| Keras `fit` without `compile` | &#9679; `MLV705` 50 % | §6.5 (functional-API chain) |
| Lightning hooks | &#9679; `MLV706`, `MLV707`, `MLV711` 100 % | tier 3 (manual-optimization flags, datamodule state) |
| HF Trainer without evaluation | &#9679; `MLV708` 75 % | *do not build* the strategy-consistency rule (§9.9) |
| `tf.function` side effects, non-singleton `tf.Variable` | **&mdash;** | **C-37** |
| Model on device, batches not | &#9679; `MLV501` 91.7 % | — |
| Hard-coded `.cuda()` | &#9679; `MLV502` 100 % | — |
| Tensor allocated on the default device in `forward` | &#9675; `MLV503` | tier 3 |
| Whole model pickled / unsafe load | &#9680; `MLV803` 97.7 % | **§6.5** — split the arms; the message is inverted [1] |
| Checkpoint written by every rank | **&mdash;** | **C-28** |
| Train–serve skew | &#9675; `MLV901`, `MLV902` | **C-31** |

### 4.7 What other tools ship that MLView does not — and the reverse

Differenced against the four catalogs, MLView already has an equivalent for
roughly 30 items. Four areas are genuinely uncovered:

1. **TensorFlow / `tf.function`.** SonarSource ships 7 TF rules [71]; MLView
   ships **0**, despite 284 TF knowledge rows. A `tf.function` that `print`s or
   appends to a captured list runs that side effect once per trace and never
   again — a silent failure of exactly MLView's kind. (**C-37**.)
2. **pandas correctness.** Sonar ships 6, ruff 13, dslinter 6 [71][74][75] —
   and van Oort et al. measured across 74 ML projects that a general-purpose
   linter "cannot reliably check correct usage of imported dependencies,
   including PyTorch" [91], which is the gap MLView's FQN-resolved tables fill.
   MLView ships 0; its 28 pandas rows exist only as stage votes. Chained
   assignment (`df[mask]["col"] = v`) is a write that is silently lost [56] — but
   it needs a DataFrame-typed receiver before it can be a rule, or it fires on
   every list-of-lists (§6.1, IR-7).
3. **The AMP and distributed contract.** Documented in PyTorch's own pitfall
   pages [5][2], partially covered by `MLV208`/`MLV209`, with three named
   sub-variants unbuilt (**C-10**, **C-09**, **C-28**).
4. **The fit/transform symmetry on the serving side.** scikit-learn's *first*
   documented pitfall [20], and Google's Rules of ML #32 [104]. **C-25**, **C-31**.

What MLView is **ahead** on is substantial and worth recording, because it is
the part a later agent might trade away by mistake. No other tool in this survey
has `MLV205` (loss accumulated without `.item()`), `MLV207` (scheduler cadence),
`MLV208`/`MLV209` (AMP mechanics), `MLV401`/`MLV402`/`MLV709` (activation–loss
pairing), `MLV121` (tf.data reshuffled holdout), `MLV702` (unregistered
submodules), `MLV711` (Lightning scheduler interval) or `MLV112` (`num_workers`
without a `__main__` guard).

### 4.8 Deliberate scope boundaries

Argued exclusions with sources, not backlog. Reasoning in §9.

| Class | Why not | Source |
|---|---|---|
| Tensor shape / dtype mismatch, dimension errors | Needs a shape lattice; the taxonomy authors say so themselves | [88], [86] |
| Data quality (nulls, outliers, class balance, drift) | Properties of data files, not of source; requires execution | [98], [80], [81] |
| System-level debt (undeclared consumers, feedback loops, correction cascades) | Not visible in one repository | [97] |
| Performance tuning as a defect class | Architecture- and workload-dependent; 607–709 raw sites measured | [14], §9.5 |
| Architectural smells (god file, scattered library use) | Not defect-level; a different product | [92] |

## 5. The candidate rule catalog

Thirty-seven candidates in three tiers. Every one states the same fields, and
every one is constrained by the five iron laws in `CONTRACTS.md` [112] — in
particular **law 2: a name regex reinforces a claim, it never creates one.**
Where a candidate's detection reduces to a name match it is marked as such and
placed in tier 3 or rejected.

**Effort scale.** **S** = a rule file plus two fixtures, ≤ 1 day.
**M** = plus a knowledge-table or small IR dependency, 2–4 days.
**L** = needs a new IR capability, more than one sprint.

**Tier discipline.** Tier 1 is everything whose false-positive exposure is
*measured* at zero or near-zero on the 37 pinned repositories and whose
detection needs no new IR. Tier 2 needs a guard this document prices, or a
knowledge/IR dependency from §6. Tier 3 needs an IR capability that does not
exist, or a corpus that does not exist.

---

### Tier 1 — Now

#### C-01 · `MLV104` — Resampling applied before the split

**Family** 1xx leakage · **Severity** high · **Effort** S · **Depends on**
knowledge rows for `imblearn.*.fit_resample` (§6.2)

**Defect.** `SMOTE().fit_resample(X, y)` before `train_test_split` synthesises
rows by interpolating between neighbours drawn from the whole frame, so
near-copies of held-out rows land in training. The nastier variant in the
corpus resamples the *holdout* itself, so the reported metric describes an
interpolation problem. imbalanced-learn's own pitfalls page warns against both
[32].

**Shape.**
```python
X_res, y_res = SMOTE().fit_resample(X, y)              # <- whole frame
X_tr, X_te, y_tr, y_te = train_test_split(X_res, y_res)
```

**Prevalence.** Public corpus **0 / 4,467 files** (M4) — the FP exposure against
the precision gate is literally zero. Labelled corpus **2 programs**
(`tabular_kaggle_leaky:53`, `tabular_imbalance_resample_bad:48`), both with
clean twins, so the two-fixture discipline is already half satisfied.

**Detection.** Exactly the §4 sketch [110]: a call resolving to
`imblearn.over_sampling.*.fit_resample` / `under_sampling.*` / `combine.*`
whose argument 0 lacks `TRAIN_SPLIT`, with a later `SPLIT`-role call consuming
a value reachable from the resample output. Reuse `_split_consuming` from
`MLV101` verbatim. Third arm: argument 0 carries `TEST_SPLIT` — that is
`MLV102`'s shape with a sampler instead of a transformer.

**Guards.** (a) Skip when the sampler is a step of an `imblearn.pipeline.Pipeline`
— that resamples per fold and is the documented fix [32]. (b) Skip when the
input already carries `TRAIN_SPLIT`. (c) Skip when no `SPLIT` and no CV call
exists anywhere (a dataset-construction utility is not a leak).
(d) `_good.py` must be imbalanced-learn's own correct example:
`make_pipeline(RandomUnderSampler(), HistGradientBoostingClassifier())` inside
`cross_validate`.

**Evidence.** [32]; M4; `ISSUE_RULES.md` §4 `MLV104` ("essentially no false
positives — resampling before splitting duplicates rows across the boundary and
is always wrong") [110]. Blocked today not by logic but by data: the knowledge
tables carry 4 imblearn rows, all constructors, and no `fit_resample` method row
(M5).

---

#### C-02 · `MLV107` — The held-out split steers early stopping or model selection

**Family** 1xx leakage · **Severity** high · **Effort** S · **Depends on** —

**Defect.** A `TEST_SPLIT` value reaches `eval_set=` / `validation_data=` /
`eval_dataset=` on a fit that *also* selects a model from that signal — early
stopping, `load_best_model_at_end=True`, a best-metric-guarded save. The
reported test number is then a maximum over the training trajectory taken on the
rows it reports, which is an optimistically biased selection score rather than a
held-out estimate [103]. The vendor docs make this frictionless and warn about
none of it [59].

**Shape.**
```python
clf = xgb.XGBClassifier(early_stopping_rounds=10)
clf.fit(X_train, y_train, eval_set=[(X_test, y_test)])   # <- the test set picks n_trees
print(accuracy_score(y_test, clf.predict(X_test)))       # <- reported as held-out
```

**Prevalence.** Public corpus: **91 sites / 7 repos** for the bare shape;
**6 sites / 3 repos** once a selection mechanism is required in the same file
(M4). The 15× reduction *is* the rule — see §7.2. Labelled corpus:
**2 programs** (`tabular_group_cv_leaky:56`, `tabular_kaggle_leaky:59`), both
recorded as `unsupported` with `wouldBe: MLV107`, and `MLV107` is the
most-cited unbuilt code in the whole corpus (6 of 173 rows, M6).

**Detection.** Resolve the keyword's value (a Name, a tuple of Names, a list of
tuples, a subscript with a literal key) to ValueRefs; require at least one to
carry `TEST_SPLIT` — the *tag*, with any `(?i)test` naming reinforcing at ×0.8
only. Then require a selection consumer: a resolved `EarlyStopping` callback in
the same `callbacks=`, an `early_stopping_rounds=` literal, a
`lightgbm.early_stopping(...)` callback, `TrainingArguments(load_best_model_at_end=True)`,
or a comparison on an eval-region metric guarding a `SAVE`-role call. Escalate
when a distinct `VAL_SPLIT` also exists in the workspace — the author had the
right split and used the wrong one. Anchor at the fit; `relatedLocs`
`split_site` at the split and `call_site` at the selection mechanism.

**Guards.** (a) **Both** clauses are mandatory; the selection clause is what
takes 91 to 6. (b) Silent when only one split exists — a two-way split with no
validation set is a weaker, different finding. (c) Silent when the same value is
also the *training* argument: `evals=[(dtrain,'train'),(dtest,'test')]` with no
early stopping is a learning-curve idiom. (d) For `xgboost.train`, judge only
the **last** `evals` entry — that is what the docs say early stopping uses [59].
(e) Under the `negation_absent` gate, the torch "a metric guards a save" arm is
unreadable; keep only the literal arm there.
(f) Note for adjudication: `xgboost/demo/guide-python/sklearn_examples.py:93`
pairs `early_stopping_rounds=10` with `eval_set=[(X_test, y_test)]` and is a
**genuine true positive** on a pinned repository — it needs a `true_positive`
state in the adjudication file, not a suppression.

**Evidence.** [59], [61], [103], [95] L1.1; M4; M6; `ISSUE_RULES.md` §4 `MLV107`
(basePrior 0.85) [110].

---

#### C-03 · `MLV703` — `F.dropout` inside a Module with no `training=`

**Family** 7xx model definition · **Severity** medium · **Effort** S ·
**Depends on** —

**Defect.** `torch.nn.functional.dropout` defaults to `training=True` [6].
Called inside an `nn.Module` method without the keyword, dropout stays on under
`model.eval()` — every evaluation and every served prediction is stochastic and
systematically degraded, and `model.eval()` does nothing about it because the
functional form does not consult module state. `ISSUE_RULES.md` §4 already calls
this "purely syntactic and always a bug" [110].

**Shape.**
```python
def forward(self, x):
    x = F.dropout(x, p=0.3)                      # <- always on
    x = F.dropout(x, p=0.3, training=self.training)   # <- two lines later, correct
```
That is not invented: `pytorch_geometric/examples/shadow.py` writes the wrong
form at line 33 and the right form at lines 35 and 37 of the same `forward()`.

**Prevalence.** Public corpus **9 sites / 4 repos** raw; **4 sites / 2 repos**
after the Module-method requirement and the `if self.training:` guard (M4).
Labelled corpus **0** — no fixture exists, which is itself a corpus gap (§7.4).

**Detection.** A Call resolving to `torch.nn.functional.{dropout, dropout1d,
dropout2d, dropout3d, alpha_dropout, feature_alpha_dropout}` with no `training=`
keyword and fewer than three positional arguments, lexically inside a method of
a class whose resolved base chain reaches `torch.nn.Module`.

**Guards.** (a) Outside an `nn.Module` method → silent; functional dropout as a
noise operator is legitimate (`stable-diffusion/ldm/models/diffusion/ddim.py:202`
is exactly this and must not fire). (b) An enclosing `if self.training:` →
silent (`fastai` `awdlstm.py:83` writes the hand-rolled equivalent).
(c) `training=` present with **any** value, including a variable → silent; the
author is in control. (d) `nn.Dropout`, the module form, is correct and is never
a target.

**Evidence.** [6]; [75] (dslinter catalogs the family); M4; `ISSUE_RULES.md` §4
`MLV703`, basePrior 0.95 [110].

---

#### C-04 · `MLV124` — `DataLoader` given both `shuffle=True` and a sampler

**Family** 1xx loader hygiene · **Severity** high · **Effort** S ·
**Depends on** —

**Defect.** `DataLoader(ds, shuffle=True, sampler=s)` raises
`ValueError("sampler option is mutually exclusive with shuffle")` at
construction [2]. `MLV110` explicitly *excludes* loaders that carry a sampler
and `MLV111` only looks at eval loaders, so the contradiction is never reported
by anything.

**Shape.**
```python
loader = DataLoader(ds, batch_size=32, shuffle=True, sampler=DistributedSampler(ds))
```

**Prevalence.** Public corpus **0 / 4,467** with a literal `True` (M4) — 21
loaders pass both keywords and every one passes `shuffle=False` or a
non-literal, which is legal. Labelled corpus **0**.

**Detection.** Literal only, one call site, no dataflow: `shuffle` resolves to
the literal `True` (directly or through a module constant, the same resolution
`MLV112` already performs) **and** `sampler=` / `batch_sampler=` is present with
a non-`None` argument.

**Guards.** (a) The literal `True` is required — `shuffle=(sampler is None)` is
the idiomatic correct spelling and is the whole reason the measured count is
zero. (b) `sampler=None` is the default and is legal alongside shuffle.
(c) Skip inside a `try:` whose handler catches `ValueError` (a deliberate probe).

**Evidence.** [2]; M4.

---

#### C-05 · `MLV215` — `require_grad` assigned (the `requires_grad` typo)

**Family** 2xx training loop · **Severity** high · **Effort** S ·
**Depends on** —

**Defect.** `param.require_grad = False` creates a new attribute and freezes
nothing. The backbone the author believes is frozen keeps training. Python's
dynamism makes it unfixable by any type checker, which is exactly why a linter
has to catch it; TorchFix ships it as TOR002 and notes it "is unlikely to cause
false-positives on real code" [69].

**Shape.**
```python
for p in backbone.parameters():
    p.require_grad = False        # <- silently does nothing
```

**Prevalence.** Public corpus **0 / 4,467** (M4). Labelled corpus **0**. The
rule's whole value is on user code and its cost against the gate is provably
nil — which is the profile of `MLV701`/`MLV702`, both at 100 % recall.

**Detection.** An `Assign`/`AnnAssign` whose target is an `Attribute` named
exactly `require_grad`, where the receiver resolves to a tensor-family value,
an `nn.Parameter`, a `MODEL`-tagged value, or an element of a `.parameters()`
iteration. Also cover the keyword form `torch.tensor(x, require_grad=True)`,
which TorchFix does not check and which is a `TypeError`.

**Guards.** (a) The receiver must resolve to a tensor/parameter/module family —
a bare `cfg.require_grad = True` on a config object must not fire, and iron law
2 forbids matching the attribute name alone. (b) Suppress when the workspace
defines a class with a `require_grad` attribute or property. (c) Do not extend
to reads.

**Evidence.** [69] TOR002; M4.

---

#### C-06 · `MLV115` — Custom `Dataset` missing `__len__` / `__getitem__`

**Family** 1xx loader hygiene · **Severity** high · **Effort** S ·
**Depends on** —

**Defect.** A class whose base chain reaches `torch.utils.data.Dataset` and
which, counting in-workspace inherited bases, lacks `__getitem__` or `__len__`.
A map-style loader over it fails at the first batch; a subtler variant is a
missing `__len__` on a Dataset used with a sampler that needs one.

**Prevalence.** Public corpus **0 firings across 178 `Dataset` subclasses** —
i.e. the rule as sketched is silent on every one of them. That makes it the
cheapest high-severity recall available anywhere in this document.

**Detection.** Exactly the §4 sketch [110]: `ctx.class_bases` supplies the
resolved chain; `IterableDataset` is checked for `__iter__` instead.

**Guards.** (a) The sketch's own guard — suppress for abstract bases only
subclassed in-workspace — plus `abc.ABC` bases and `@abstractmethod` decorators.
(b) A class defining `__getattr__`, or inheriting from an unresolved external
base, cannot be judged and stays silent. (c) A `Dataset` with no construction
site anywhere is a mixin; de-rate.

**Evidence.** `ISSUE_RULES.md` §4 `MLV115` [110]; the 178/0 measurement.

---

#### C-07 · `MLV603` — Partial seeding, and the `is_seeded` loophole

**Family** 6xx reproducibility · **Severity** low · **Effort** S ·
**Depends on** a new `seeded_sources()` predicate (must **not** reuse
`is_seeded`)

**Defect.** Two things at once. The rule: at least one seed exists, but the
seeded set does not cover the libraries the workspace actually draws randomness
from — PyTorch's own note requires `torch.manual_seed`, `random.seed` and
`np.random.seed` independently [3]. The bug behind it: `helpers.is_seeded()`
[117] returns True for **any** `random_state=` / `generator=` / `seed=` keyword
anywhere in the workspace, so a *scoped* seed silences `MLV601` for the whole
project.

**Shape.** All four measured misses are the same:
```python
obs, _ = env.reset(seed=0)          # seeds a gymnasium env and nothing else
ds = ds.train_test_split(seed=7)    # seeds one split
ds = ds.shuffle(buffer, seed=1)     # seeds one shuffle
# -> MLV601 goes silent workspace-wide; torch init and dropout masks still move
```

**Prevalence.** Labelled corpus: **4 direct misses** (`adv_ppo_bad`,
`adv_sac_bad`, `nlp_lora_peft`, `vision_keras_cnn_bad`), each with the corpus
stating the cause verbatim — *"the only seed in the file is
`env.reset(seed=...)`, which seeds the gymnasium environment and nothing else"*.
`MLV601` is the joint-largest rule in the corpus at 47 labels.

**Detection.** Partition seeds. **Global**: `torch.manual_seed`,
`torch.cuda.manual_seed_all`, `numpy.random.seed`, a module-level
`numpy.random.default_rng`, `random.seed`, `tensorflow.random.set_seed`,
`transformers.set_seed`, `lightning.seed_everything`, `keras.utils.set_random_seed`.
**Local**: a `seed=`/`random_state=`/`generator=` keyword on anything else.
Then collect randomness *users* by resolved FQN (`numpy.random.*`, `random.*`,
`tensorflow.random.*`, a shuffling loader or splitter) and fire once per
workspace naming the uncovered pairs. `MLV601` keeps `is_seeded` (its question
is "is anything seeded at all"); `MLV603` must not.

**Guards.** (a) Never fires together with `MLV601` — the catalog already says so.
(b) A pure-sklearn/pandas workspace where every estimator and splitter carries
`random_state=` *is* reproducible; local seeds are a full witness there.
(c) Framework helpers (`seed_everything`, `set_seed`) cover all sources —
suppress. (d) A JAX workspace using `jax.random.PRNGKey` needs no global seeding;
de-rate hard. (e) A `random.randint(...)` feeding a `manual_seed` argument is
deliberate entropy — suppress. (f) The CUDA sub-case is informational:
`torch.manual_seed` seeds CUDA in current versions [3], so demanding
`manual_seed_all` is obsolete advice. (g) Low severity, phrased as hygiene,
naming the call: *"numpy randomness is used at `<loc>` and never seeded."*

**Evidence.** [3]; [117]; M1 (four named misses); `ISSUE_RULES.md` §4 `MLV603`
[110]; [75] (dslinter "Randomness Uncontrolled").

---

#### C-08 · `MLV804` — Model exported, traced or scripted while in train mode

**Family** 8xx checkpointing / serving · **Severity** high · **Effort** M ·
**Depends on** knowledge rows for the export family (§6.2)

**Defect.** `torch.jit.trace(model, x)` / `torch.onnx.export(model, …)` on a
module last put in `train()` bakes the live dropout mask and the current
BatchNorm batch statistics into the artifact. Nothing raises at run time, and
the served model is quietly wrong. The exporter warns about it itself:
*"Exporting a model while it is in training mode… Calling `model.eval()` before
export is recommended"* [13] — a warning in a build log, which is not a finding
a reader sees.

**Shape.**
```python
model.train()
for epoch in range(epochs): ...            # training completes
torch.onnx.export(model, sample, "model.onnx")   # <- still in train mode
```

**Prevalence.** Public corpus **78 export/trace/script sites across 13 of 37
repositories**, of which **35 sit in a file with no `.eval()` anywhere** (M4).
Labelled corpus **5 sites / 5 programs**, and two of them
(`adv_qat_bad/qat_export.py:87–88`, `vision_onnx_service_bad/export.py:104`)
are recorded as `unsupported` with the label calling it the single most severe
defect in the file.

**Detection.** Resolve the FQN to `torch.onnx.export` / `torch.jit.trace` /
`torch.jit.script` / `torch.export.export` / `torch.ao.quantization.convert`.
Take the module argument's ValueRef. Fire when **no** `EVAL_MODE` call on that
same ValueRef exists anywhere on its lifetime, while positive evidence that this
module was trained in *this* workspace does exist (a `TRAIN_MODE` call, or a
backward reachable from it).

**Guards.** (a) "`eval()` anywhere on the value's lifetime", never "lexically
before" — the module is usually put in eval mode by the loading helper, and a
lexical test would produce the 35-site noise the measurement warns about.
(b) Refuse the absence claim the moment **any** `.eval()` exists whose receiver
did not resolve — `MLV705`'s escape hatch, which was added for exactly this
class of bug. (c) Require positive evidence of training in-workspace; a module
that only ever arrives as a parameter is not judged. (d) Skip modules whose
resolved class contains no `DROPOUT` or `NORM_TRAIN_SENSITIVE` submodule — a
pure-functional export does not care. (e) `training=TrainingMode.TRAINING`
passed explicitly → the author said so; suppress.

**Evidence.** [12], [13]; [90] ("wrong save/reload" is 13 % of silent
framework bugs, at impact level "model's result"); M4; M5 (every FQN missing);
M6.

---

#### C-09 · `MLV132` — `DistributedSampler` whose `set_epoch()` is never called

**Family** 1xx loader hygiene · **Severity** medium · **Effort** M ·
**Depends on** a knowledge row for `DistributedSampler.set_epoch` (§6.2)

**Defect.** Verbatim from the PyTorch docs: *"In distributed mode, calling the
`set_epoch()` method at the beginning of each epoch **before** creating the
`DataLoader` iterator is necessary to make shuffling work properly across
multiple epochs"* [2]. Without it the permutation derives from
`(seed, epoch=0)` forever: every rank replays one fixed batch order for the
entire run and `shuffle=True` buys nothing. Nothing raises; the loss curve looks
normal.

**Prevalence.** Public corpus **19 shuffling constructions / 9 repos**, of which
**5 have no `set_epoch` in the same file** (M4). Labelled corpus **4 programs**,
and `infra_ddp_sampler_bug/train_ddp.py:125` records it as an
`unruledDefects` row with the recommended rule already drafted by the labeller
— one of only two such rows in the entire corpus.

**Detection.** A `DistributedSampler(...)` with `shuffle` absent or literal
`True`, bound and passed as a loader's `sampler=`. Locate the epoch loop that
consumes the loader (`MLV207`'s machinery already does this, including one call
hop into `train_one_epoch`). Fire when no call resolving to
`DistributedSampler.set_epoch` on a receiver identical to that sampler appears
in the loop body or a followed callee. Declare `absence=True`.

**Guards.** (a) `shuffle=False` never fires — there is no permutation to
refresh, and this alone excludes every eval sampler. (b) `negation_absent`:
Lightning states in its own docs that it injects and drives the sampler [52];
accelerate's `prepare()`, HF Trainer, Fabric and DeepSpeed all call `set_epoch`
internally. (c) Refuse the absence when any unresolved `.set_epoch(` exists
anywhere. (d) **Workspace-scoped, not file-scoped** — the measured false
positives are library modules (`timm/data/loader.py`) that construct the sampler
and let the caller drive it; scope to a workspace with an epoch loop.
(e) Prefer the sampler's identity over the loader's, so a train/val sampler pair
yields one finding.

**Evidence.** [2] (verified verbatim); [15]; [52]; M4; M6.

---

#### C-10 · `MLV208` extension — the three unbuilt AMP sub-variants

**Family** 2xx training loop · **Severity** medium · **Effort** M ·
**Depends on** recording the autocast dtype on the CallSite (§6.1, IR-5)

**Defect.** `MLV208` sits at **28.6 % recall / 16.7 % unseen** — the second-worst
rule in the catalog — and all five of its misses are sub-variants the rule never
implemented:

1. **fp16 autocast with no `GradScaler` anywhere.** Gradients with small
   magnitudes "flush to zero ('underflow'), so the update for the corresponding
   parameters will be lost" [4]. The run trains, logs a loss, and converges
   worse. `vision_multitask_bad/train.py:73`, whose own gap note says *"MLV208
   cannot fire when the GradScaler is absent altogether, which is the commonest
   fp16 mistake; the rule would have to read the autocast dtype to tell fp16
   (needs a scaler) from bf16 (must not have one)."*
2. **A second scaler in the same loop.** `_scaler_for` resolves one scaler per
   loop. `vision_superres_bad` has `d_scaler` and `g_scaler` and loses three
   labels: a bare `backward()` while a scaler is in use, a `step()` with no
   `update()`, and —
3. **`clip_grad_norm_` on still-scaled gradients.** The AMP recipe is explicit
   that `unscale_()` must precede clipping [5], and Lightning shipped this as a
   framework bug [55].

Plus a fourth, cheap and separate: **`backward()` lexically inside an
`autocast` block**, which the docs call "not recommended" [4] — measured at
exactly **1 site in 4,467 files**, which is both proof the rule is real and
proof it is nearly silent.

**Prevalence.** Public corpus: 8 sites carry an explicit `dtype=torch.float16`
(M4); the file-scoped "autocast + backward + no scaler" shape is 104 sites, of
which only one names bfloat16 — which is precisely why **dtype resolution is the
whole rule** and a dtype-blind version would accuse 104 files. Labelled corpus:
5 misses, plus `amp_accumulation` as the clean twin.

**Detection.** Per sub-variant, over roles that already exist
(`AUTOCAST`, `GRAD_SCALER`, `BACKWARD`, `CLIP_GRAD`, `OPT_STEP`):
(1) resolve the autocast's effective dtype — the `dtype=` literal if present,
else `float16` when `device_type` resolves to `'cuda'`, else `bfloat16` when
`'cpu'`, else **unknown** — and fire only on `float16`, when the existing
`_scaler_for` walk finds no scaler at all. (2) Group the loop body's `OPT_STEP`,
`ZERO_GRAD`, `BACKWARD` and scaler calls by resolved receiver identity into
per-optimizer *lanes*, and evaluate each existing sub-variant within one lane.
(3) A `CLIP_GRAD` in a lane with no preceding `unscale_` on the governing
scaler. (4) A `BACKWARD` lexically inside an `AUTOCAST` `with` body — the exact
structural mirror of the shipped `MLV204`.

**Guards.** (a) **bfloat16 never fires**; an unresolved dtype is `unknown` and
also never fires — the same refusal `MLV208` already makes for a non-literal
`enabled=`. (b) `negation_absent`: accelerate, Lightning, Fabric, DeepSpeed and
HF Trainer all own the scaler. (c) Lane comparisons never cross lanes — that is
what makes a correct GAN step (D's `step` legitimately preceding G's `backward`)
safe, and it is why the current bail-out exists. (d) Accumulation guards
(`if step % N == 0`) must be matched against an `unscale_` under the *same*
guard. (e) The autocast arm is severity **low** and must quote the docs' own
"not recommended", not accuse. (f) At most one `MLV208` finding per lane.

**Evidence.** [4], [5], [55]; M4; `ACCURACY.md` §9 names variant 1 as
unimplemented [111]; `ISSUE_RULES.md` §4 lists four sub-variants and these are
the fifth through eighth [110].

---

#### C-11 · `MLV122` — tf.data pipeline batches before it shuffles

**Family** 1xx loader hygiene · **Severity** medium · **Effort** S ·
**Depends on** — (reuses `MLV121`'s receiver-chain walk)

**Defect.** `ds.batch(n).shuffle(k)` shuffles the elements of a *batched*
dataset — and after `batch()` an element **is** a batch. The composition of
every batch is frozen for the life of the run; only the order in which those
fixed batches arrive varies. When the source is sorted (a `TextLineDataset` over
a corpus, a class-ordered image listing) the batches are homogeneous every
epoch. The correct order is `map → shuffle → batch → prefetch` [41].

**Shape.**
```python
ds = (raw.batch(BATCH_SIZE)
         .shuffle(buffer_size=256))     # <- permutes batches, not examples
```

**Prevalence.** Public corpus **4 sites / 1 repo** after excluding `batch(1)`
(M4): `keras-io/examples/generative/text_generation_gpt.py:89` (a sorted text
corpus — the strongest single instance) and `ddpm.py:184`, plus their notebook
mirrors. Correct `shuffle→batch` chains outnumber it by roughly 50:1 in the same
repository. Labelled corpus **0** — a fixture gap (§7.4).

**Detection.** Walk the receiver chain (fluent or through bindings, exactly as
`MLV121` already does) and fire when a `TFDATA_SHUFFLE` role appears downstream
of a `TFDATA_BATCH` on the same chain. Report at the shuffle;
`relatedLocs` `construction` at the batch. Require the dataset to reach a
training consumer.

**Guards.** (a) A literal `batch(1)` → suppress; a batch of one *is* an example,
and this was the only benign shape found. (b) A chain containing an *earlier*
`shuffle` → the deliberate two-level shape; suppress. (c) A chain containing
`bucket_by_sequence_length` / `group_by_window` batches first on purpose;
suppress. (d) Eval datasets → `MLV111`'s territory, and the batch-composition
argument does not apply. (e) `reshuffle_each_iteration=False` is *not* a guard
here (unlike `MLV121`) — it makes the situation worse, not better.
(f) The message must reason from `batch()` semantics: the tf.data guide
demonstrates that ordering matters but issues **no blanket prohibition** [41],
and the rule text should say what is frozen rather than cite a rule that does
not exist.

**Evidence.** [41]; M4.

---

#### C-12 · `MLV123` — tf.data `.cache()` after `.shuffle()`

**Family** 1xx loader hygiene · **Severity** medium · **Effort** S ·
**Depends on** — (same walk as C-11)

**Defect.** `cache()` memoizes the elements it sees on the first pass. Placed
downstream of `shuffle()`, it freezes one permutation and replays it identically
every epoch, silently defeating `reshuffle_each_iteration`. Placed downstream of
a random augmentation `map`, it freezes one draw of the augmentation — the model
then sees the same "augmented" example every epoch, which is the opposite of
augmentation.

**Prevalence.** Public corpus **12 sites / 1 repo** (keras-io), all on the
shuffle arm; the random-`map` arm measured **0** (M4). Of five sampled sites,
three are training datasets built by a shared `make_dataset()` helper applied to
both splits — so the training instance is a real defect and the val instance is
harmless. Labelled corpus **0**.

**Detection.** A `tensorflow.data.Dataset.cache()` whose receiver chain reaches
a `.shuffle()` (arm 1) or a `.map()` whose function body contains a
`tf.random.*` or a random-augmentation FQN from the set `MLV114` already uses
(arm 2). Two messages; arm 1 is the higher-confidence one.

**Guards.** (a) Eval/test dataset → suppress; a frozen order on a holdout is
harmless. (b) `shuffle(..., reshuffle_each_iteration=False)` downstream →
the author has opted out of reshuffling and cache changes nothing; suppress.
(c) A `.repeat()` between shuffle and cache does **not** rescue it — do not
treat repeat as a guard. (d) A disk cache with a filename argument in a separate
chain is not this pattern. (e) Arm 2 requires an actual resolved random FQN in
the function body, never an identifier containing "augment". (f) Ship arm 2
disabled until a fixture exists — it has zero measured occurrences.
(g) **Weaker citation, and the rule text must reflect it:** the TF performance
guide discusses cache placement and notes shuffle's internal buffer, but does
not state the freeze-the-permutation consequence [42]; the message must argue
from `cache()` semantics.

**Evidence.** [42] (with the limit above); M4.

---

#### C-13 · `MLV213` — Auxiliary network forwarded with gradients on

**Family** 2xx training loop · **Severity** medium (detach arm: high) ·
**Effort** M · **Depends on** an optimizer-ownership reachability query

**Defect.** A second model that must not be trained — a distillation teacher, a
DPO/PPO reference policy, an RL target network, a MoCo key encoder, a perceptual
VGG, a frozen CLIP — is forwarded inside the training step with none of the four
disciplines applied: no enclosing `no_grad`/`inference_mode`, no `.detach()` on
its output, no `requires_grad_(False)`, no `.eval()`. Gradients and memory flow
into it, and in DPO/MoCo the method's whole premise — a *frozen* reference —
quietly stops holding.

**Prevalence.** Labelled corpus: the **largest single cluster** in the 173
unrulable-defect rows, spanning **11 programs**: `adv_distill_bad:82` and `:63`,
`adv_dpo_bad:65` and `:115`, `adv_moco_bad:67/:57/:137`, `adv_dqn_bad:90`,
`adv_sac_bad:123`, `adv_ppo_bad:115`, `nlp_distil_bert_bad`,
`nlp_dpo_preference_bad`, `vision_gan_bad` ×2, `vision_superres_bad/models.py:119`,
`vision_simclr_bad/pretrain.py:118` (M6). Public corpus: 431 `requires_grad=False`
sites show the *correct* spelling is common, which is what gives the guard signal.

**Detection.** Inside a region containing `BACKWARD`, find `FORWARD`-role calls
on two or more distinct `MODEL`-tagged ValueRefs. Classify: a model whose
parameters reach a `torch.optim.*` construction is **trained**; one that does not
is **auxiliary**. Identify auxiliary status by *evidence*, not name: receiving a
`load_state_dict` copy of the primary, being built by `copy.deepcopy(primary)`,
or being the second argument of a knowledge-table distillation/DPO loss. Fire on
an auxiliary model forwarded in the training step when none of
{enclosing `NO_GRAD`, a `.detach()` on the produced value, `requires_grad_(False)`
on the model, `EVAL_MODE` on the model} is present. Sub-variant, high severity
and unambiguous: the auxiliary model's parameters are reachable from an
optimizer's `params` argument.

**Guards.** (a) The name arm (`teacher|reference|target|ema|key_encoder|frozen`)
**reinforces only** — identification must come from deepcopy / state_dict /
loss-position evidence (iron law 2). (b) Suppress entirely when two or more
optimizers partition the models — that is the GAN / actor-critic shape, and a
generator step legitimately back-propagates through the discriminator.
`MLV201` already handles multi-optimizer GAN loops, and C-10's lanes make the
partition computable. (c) Online distillation and mutual learning co-train the
"teacher"; the optimizer-ownership test excludes them. (d) Require the forward
to be inside the backward-reachable region, not merely in the same function.
(e) Emit medium, with the evidence naming *which* of the four disciplines was
absent.

**Evidence.** M6 (11 programs, quoted); [86] ("training process > wrong memory
management" is the nearest taxonomy leaf, and the fit is poor — this family is
MLView's own discovery and is cited to its corpus, not to a paper).

---

#### C-14 · `MLV403` — Loss-input normalisation for `CTCLoss`, `NLLLoss`, `KLDivLoss`

**Family** 4xx loss/activation pairing · **Severity** high · **Effort** S ·
**Depends on** IR-2 (shape-method transparency, §6.1) for the CTC arm

**Defect.** `MLV401` pairs softmax with `CrossEntropyLoss` and `MLV709` does the
Keras equivalent. The same class of defect is invisible for the losses whose
input contract is different: `nn.CTCLoss` "requires logarithmized probabilities
of the outputs, obtained with `torch.nn.functional.log_softmax()`" [8], and
feeding it plain softmax makes the loss finite but wrong, so the model converges
to all-blank rather than raising [19]. `nn.NLLLoss` (the unbuilt `MLV403`) needs
`log_softmax`; `KLDivLoss` needs log-probabilities in argument 0.

**Shape.**
```python
probs = F.softmax(logits, dim=2).permute(1, 0, 2)   # <- should be log_softmax
loss  = criterion(probs, targets, input_lengths, target_lengths)
```

**Prevalence.** Labelled corpus: `vision_ocr_ctc_bad/train.py:78` is a direct
`MLV401` miss; `adv_asr_ctc_bad/train_asr.py:88` is recorded as `unsupported`
with the documentation quoted in the label; `adv_distill_bad/distill.py:64` is
the KLDiv arm. Both CTC programs have clean twins
(`adv_asr_ctc_clean/train_asr.py:108` uses `F.log_softmax`), so the fixtures
exist.

**Detection.** Generalise `MLV401` into a table rather than writing four rules:
each `LOSS_CLS`/`LOSS_FN` knowledge row gains `expects: logits | log_probs |
probs | none`, plus the keyword that flips it where one exists. The rule becomes
one predicate — the value-type of argument 0 (via `rules/valuetype.py`) against
the row's `expects` — with `MLV401`'s existing ×0.8 regex de-rate and its
"unresolvable producer drops to `possible`" rule, both unchanged.
`loss_chain.trace_softmax` already distinguishes `SOFTMAX` from `LOG_SOFTMAX`.

**Guards.** (a) Every new row needs its own good/bad fixture pair — a row whose
`expects` is recorded wrongly fires everywhere it appears, and that is the only
new risk this candidate carries. (b) An unresolvable producer drops to
`possible`, never dropped. (c) The CTC arm needs IR-2 to see through the
`.permute(1, 0, 2)` that every CTC program writes to reach `(T, N, C)`.
(d) `KLDivLoss(log_target=True)` changes what the **target** must be, not the
input — do not conflate the two arguments.

**Evidence.** [8], [9], [19]; [93] NeuraLint rule 10 ("valid loss linkage");
[77] (UMLAUT's `check_softmax_computed_before_loss` is the Keras twin); M6.
Current `MLV401` recall is 53.3 %.

---

### Tier 2 — Next

#### C-15 · `MLV125` — Keras `fit()` argument silently ignored for its input type

**Family** 7xx framework · **Severity** medium · **Effort** S ·
**Depends on** —

**Defect.** Verbatim: `shuffle` "is ignored when `x` is a `keras.utils.PyDataset`,
`tf.data.Dataset`, `torch.utils.data.DataLoader` or Python generator function"
[33]. `model.fit(train_ds, shuffle=True)` does nothing; the author believes the
training data is shuffled and it is not. This is `MLV110`'s defect wearing a
correct-looking keyword, on a path where MLView has no rule at all.
`sample_weight` is the second arm, unsupported for the same input types.

**Prevalence.** Public corpus: measured against a name-based proxy at 13 sites
in 10 files; the tag-resolved form is smaller. The decisive instance is in
Keras's own examples — `keras-io/examples/vision/3D_image_classification.py:389`
passes `shuffle=True` where the input (line 259) is
`train_loader.shuffle(len(x_train)).map(...).batch(2).prefetch(2)`, so the
fit-level keyword is documented dead code.

**Detection.** A `KERAS_FIT` call whose argument 0's ValueRef resolves to a
`tensorflow.data.Dataset` (any `tf_dataset` row), a `torch DataLoader`
(`LOADER` tag), or a workspace class whose bases include `keras.utils.PyDataset`,
carrying a literal `shuffle=` or `sample_weight=`.

**Guards.** (a) Argument 0 must **resolve** — a name containing "ds" is the
regex-only match iron law 2 forbids; an unresolved `x` suppresses rather than
de-rates, because the whole claim is about its type. (b) A NumPy/pandas `x`
never fires; `shuffle` is honoured there. (c) `shuffle=False` on a dataset input
misleads nobody; suppress. (d) When the input pipeline already contains a
`.shuffle(...)` the intent is satisfied and the keyword is merely dead — emit
at low. (e) Do **not** extend to `validation_split`, which raises loudly rather
than silently; a raising API is not MLView's business.

**Evidence.** [33] (verified verbatim); M4.

---

#### C-16 · `MLV126` — Keras `fit()` over an infinitely repeating dataset with no `steps_per_epoch`

**Family** 7xx framework · **Severity** high · **Effort** S · **Depends on** —

**Defect.** Verbatim: "When passing an infinitely repeating dataset, you must
specify the `steps_per_epoch` argument, otherwise the training will run
indefinitely" [33]. The first epoch never ends.

**Prevalence.** Public corpus: 23 `fit(..., steps_per_epoch=)` sites in 19
files — i.e. the correct pairing is well represented and the rule would be
silent on it.

**Detection.** Argument 0 of a `KERAS_FIT` resolves through the `tf_dataset`
chain to a `.repeat()` with no positional argument and no `count=` (or a literal
`None`/`-1`), and `steps_per_epoch` is absent from `kwarg_nodes`.

**Guards.** (a) Any literal `repeat(n)` → silent. (b) An argument 0 that does not
resolve to a tf.data chain → suppress. (c) `steps_per_epoch` present but
non-literal → presence is what matters; suppress. (d) Skip inside a tuner/sweep
body where an external step budget may apply.

**Evidence.** [33] (verified verbatim).

---

#### C-17 · `MLV710` — Keras binary head with `from_logits=True` and the string `'accuracy'`

**Family** 7xx framework · **Severity** medium · **Effort** S ·
**Depends on** `MLV709`'s existing compile→model walk

**Defect.** `compile(loss=BinaryCrossentropy(from_logits=True), metrics=['accuracy'])`
on a model whose last layer is `Dense(1)`: Keras resolves the string by *shape*
to `BinaryAccuracy` [37], which thresholds at 0.5. On logits the correct
threshold is 0, so the reported accuracy is wrong — usually pinned near the
majority-class rate. The loss is right and the metric lies, which is the worst
combination.

**Prevalence and the guard that is the whole rule.** Public corpus: **25 sites**
pair `from_logits=True` with the string `'accuracy'`. Split by loss family:
**0 are binary, 25 are categorical/sparse.** `CategoricalAccuracy` and
`SparseCategoricalAccuracy` document that "you can provide logits of classes as
`y_pred`, since argmax of logits and probabilities are same" [36] — so with a
categorical loss the pairing is *correct*. The unguarded rule scores 25 false
positives on the precision gate; the guarded rule scores zero findings and zero
false positives.

**Detection.** Reuse `MLV709`'s walk from `compile()` back to the model (one hop
through a builder, one back through a parameter, call sites must agree). Fire
when the `loss=` argument constructs `BinaryCrossentropy`/`BinaryFocalCrossentropy`
with literal `from_logits=True`, `metrics=` contains the string `'accuracy'` or
`'acc'`, and the model's final layer literal is `Dense(1, ...)` with no
activation.

**Guards.** (a) The categorical arm must never fire (above). (b) An explicit
`keras.metrics.BinaryAccuracy(threshold=0.0)` suppresses. (c) `from_logits=False`
never fires. (d) A final layer that is not a literal `Dense(units)` suppresses.

**Evidence.** [35], [36], [37]; the 25/0 split measurement.

---

#### C-18 · `MLV133` — Keras `validation_split` on ordered data

**Family** 1xx loader hygiene · **Severity** medium · **Effort** M ·
**Depends on** `MLV106`'s temporal-signal predicate, inverted

**Defect.** Verbatim: "The validation data is selected from the last samples in
the `x` and `y` data provided, **before shuffling**" [33]. `shuffle=True` does
not help — it shuffles the training remainder each epoch, after the tail has
been carved off. On class-ordered arrays the validation set can be one class; on
time-ordered arrays it is a chronological holdout the author did not intend.
Every reported `val_loss` and every `EarlyStopping` decision rests on it.

**Prevalence.** Public corpus **55 sites / 2 repos**; 48 with no shuffle visible
anywhere in the module (M4). Of five sampled, three are on pre-shuffled
`keras.datasets` arrays (benign in effect, fragile in principle) and two matter:
`approximating_non_function_mappings.py:126` generates `x,y` in order and then
early-stops on the tail; and the keras-io timeseries family, where the tail is a
different regime.

**Detection.** A `KERAS_FIT` with a literal numeric `validation_split=`, whose
`x` is an in-memory array, and where the array carries an **ordering signal**:
`MLV106`'s existing two-independent-signals predicate (`pd.to_datetime`,
`parse_dates=`, a `sort_values` on a date-named column, a `DatetimeIndex`, an
import of statsmodels/prophet/darts) *plus* a fourth signal — an unshuffled
`sort_values` / `np.sort` / per-class `concatenate` upstream. Phrase as a
question, as `MLV106` does.

**Guards.** (a) Never fire on `validation_split` alone — that is `MLV117`'s
lesson (§9.7): 55 sites of a keyword is not 55 defects. (b) One signal only →
×0.6 and out of the Problems panel. (c) `x` resolving to a
`tf.data.Dataset`/`PyDataset`/generator → suppress; `validation_split` is
rejected there. (d) `x` from `keras.datasets.*` or another source recorded as
pre-shuffled → de-rate heavily; this was 3 of 5 sampled. (e) A prior explicit
shuffle of `x` and `y` together → suppress. (f) `validation_data=` present
instead → not this rule. (g) De-rate when no `EarlyStopping`/`ModelCheckpoint`
consumes the validation metric — the consequence is then a misreported number,
not a steered run.

**Evidence.** [33] (verified verbatim); M4.

---

#### C-19 · `MLV802` extension — selection on a training metric, and best weights never restored

**Family** 8xx checkpointing · **Severity** medium / low · **Effort** S ·
**Depends on** —

**Defect, two arms.**
1. `monitor='loss'` or `monitor='accuracy'` (rather than `val_*`) on
   `EarlyStopping` / `ModelCheckpoint` / `ReduceLROnPlateau`. Training loss
   almost always keeps falling, so early stopping never triggers, the checkpoint
   saves the most-overfit epoch, and the LR never reduces. Silent: the run
   completes and the checkpoint exists.
2. `EarlyStopping` with `restore_best_weights` absent — it defaults to False, and
   "If False, the model weights obtained at the last step of training are used"
   [34]. Training stops `patience` epochs *after* the best epoch and keeps the
   worse, later weights, while the headline number is reported from the best
   epoch's log.

**Prevalence.** Arm 1: public **18 sites / 1 repo** for an explicit
non-validation monitor (M4). The "monitor absent" arm is worthless and must not
exist — Keras already defaults to `val_loss` [34], and it was 86 of 106 raw
matches. Arm 2: public **34 sites / 4 repos** after the Keras FQN gate; 7 of 41
raw matches were Lightning/ignite `EarlyStopping`, which has no such parameter
at all — a pure FQN-resolution false positive the gate removes. Labelled corpus:
arm 1 has **2 matches and both are false positives** — `infra_lightning_cli`
uses `monitor='val/loss'`, and a bare `val_` prefix test misses the slash
convention.

**Detection.** Arm 1: a resolved `keras.callbacks.*` (and the Lightning mirrors)
with an explicit string-literal `monitor=` that is not a validation metric,
where "is a validation metric" is decided by prefix **and separator** —
`val`/`valid`/`validation`/`eval`/`test` followed by `_`, `/` or `-`. Escalate
when a validation split demonstrably exists. Arm 2: a resolved Keras
`EarlyStopping` with `restore_best_weights` absent or literal False, reaching a
`fit(callbacks=[...])`.

**Guards.** (a) Arm 1: the separator set is mandatory — the measured false
positives are `val/loss`. (b) Self-supervised or generative pretraining with no
validation data anywhere legitimately monitors the training loss (SimSiam, the
GAN/diffusion families); suppress. (c) Arm 2: FQN gate to Keras only —
`pytorch_lightning.callbacks.EarlyStopping` and ignite's have no
`restore_best_weights`. (d) Arm 2: a sibling `ModelCheckpoint(save_best_only=True)`
means the best weights are on disk; suppress. (e) Arm 2: `patience=0` → suppress.
(f) Arm 2 is **low** and advisory: keeping the last epoch is a legitimate choice
for pretraining.

**Evidence.** [34] (signature and the quoted behaviour); M4;
`ISSUE_RULES.md` §4 `MLV802` [110], whose sketch covers only the hand-rolled
`if loss < best: torch.save(...)` shape — the callback spelling is the same
defect declared rather than coded, and is far more common.

---

#### C-20 · `MLV108` — Group / entity leakage: a split that ignores a grouping key

**Family** 1xx leakage · **Severity** medium · **Effort** M ·
**Depends on** a `GROUP_KEY` value tag (§6.2)

**Defect.** Rows from one patient, user, account or session land in both halves,
so the model memorises the entity rather than the phenomenon and the held-out
score is fiction. Kapoor & Narayanan's L3.2 [95]; scikit-learn ships
`GroupKFold`, `GroupShuffleSplit`, `LeaveOneGroupOut` and `StratifiedGroupKFold`
for exactly this and states the guarantee explicitly [21].

**Prevalence.** Public corpus: **0 measurable** — and that is a finding about the
corpus, not the defect (§7.4). The 37 pinned repositories are frameworks and
model zoos with essentially no real tabular pipeline, so this rule's
false-positive behaviour **cannot be claimed from the current gate**. Labelled
corpus: the twin pair `tabular_group_cv_clean` / `tabular_group_cv_leaky` exists
and its central defect is recorded as unscorable — *"Group leakage — one
`account_id` appearing on both sides of a cut — has no rule in the catalogue."*

**Detection.** Two arms, and the strong one first. **Arm A:** a value is passed
as `groups=` to *some* split in the workspace, and a *different* split of the
same frame is group-unaware — the author knows about groups and forgot once.
**Arm B:** a literal column key matching
`(?i)^(patient|subject|user|customer|session|device|group|series|store|account)_?id$`
is read from the frame, the frame reaches a shuffling split, no group-aware
splitter exists anywhere, **and** the key independently participates in a
`groupby` / `merge(on=)` / `drop_duplicates(subset=)`. Phrase as a question.

**Guards.** (a) Arm B requires **two independent signals** — the key existing is
not one of them; firing on the name alone violates iron law 2. (b) Suppress when
any `Group*`/`StratifiedGroupKFold`/`LeaveOneGroupOut` splitter appears
anywhere. (c) Suppress when the key is dropped from the features before the
split *and* never used to group. (d) Suppress after an aggregation that makes
the key unique (`groupby(key).agg`, `drop_duplicates(subset=[key])`) — one row
per group cannot straddle. (e) Suppress on `TimeSeriesSplit` — that is
`MLV106`'s territory. (f) **Ship arm B in the advisory group and start
base_prior low (0.55)** until §7.4's tabular corpus exists; anything else is
asserting a precision claim the project has never measured.

**Evidence.** [95] L3.2; [21]; [80] (`identifier_label_correlation` is the
runtime counterpart); M6.

---

#### C-21 · `MLV105` — Target column, and target-derived statistics, in the feature matrix

**Family** 1xx leakage · **Severity** medium/high · **Effort** M ·
**Depends on** IR-7 (column-level provenance, §6.1)

**Defect, two arms.** (1) `y = df['label']` then `X = df` — the model reads its
own answer. (2) The arm the §4 sketch does *not* cover and which the corpus
records twice: a **statistic derived from the target** left in the features —
`out['contract_churn_rate'] = out.groupby('contract')[TARGET].transform('mean')`
(target encoding computed over the whole frame) or
`out[TARGET].rolling(w).mean()` used as a predictor. Each row's own label
contributes to its own feature. CatBoost goes out of its way to avoid the naive
global target mean [62] and scikit-learn's `TargetEncoder` cross-fits for the
same reason [25].

**Prevalence.** Public corpus: `groupby(...).transform(...)` **1 site / 1 repo**;
`fillna(<frame statistic>)` **2 / 1** (M4). Labelled corpus:
`tabular_kaggle_leaky/prep.py:34` records arm 2 verbatim — *"each row's own
outcome contributes to its own feature value, so validation accuracy is a memory
test"* — and `tabular_forecast_shuffled/lags.py:33` the rolling variant;
`MLV105` is cited in 2 `wouldBe` rows.

**Detection.** Arm 1 exactly as the §4 sketch [110], on literal keys.
Arm 2: an assignment into a `FEATURES`-tagged frame whose right-hand side is a
`groupby(...)[k].transform(...)`/`.agg(...)`/`.map(series)` chain where `k` is
the **same literal key** the target was taken from, with a `SPLIT` or `FIT`
later consuming the frame.

**Guards.** (a) Literal keys only; a dynamic column list sets `dynamic` and
suppresses. (b) Arm 2 requires the grouped column to be the literal target —
never a name regex. (c) Model `pop` as removing the key. (d) `TargetEncoder`
inside a Pipeline refitted by a CV search cross-fits internally and is correct —
this is the sharpest trap, and the corpus names it at `tabular_nested_cv`.
(e) Suppress when the derivation happens *after* the split or inside a fold
loop — reuse `MLV101`'s ordering machinery so the two rules cannot disagree.
(f) ×0.6 for autoregressive names (`next|shift|lag|y_t|future`) — a lagged target
IS the correct feature in forecasting.

**Evidence.** [95] L2; [62]; [25]; [101]; M4; M6; `ISSUE_RULES.md` §4 `MLV105`
[110].

---

#### C-22 · `MLV127` — Unlagged rolling / expanding aggregate of the target

**Family** 1xx leakage (temporal) · **Severity** high · **Effort** M ·
**Depends on** IR-7 (column provenance)

**Defect.** `out['roll_mean_24'] = out[TARGET].rolling(24).mean()`. pandas'
`closed` defaults to `'right'`, i.e. `(first, last]` — "the last point is
included in the calculations" [57] — so the value at time *t* sits inside its own
feature. `expanding()`, `cumsum()`, `ewm()` and `groupby(...).transform('cumsum')`
have the same property. The correct spelling is `.shift(1).rolling(24).mean()`.
A second variant: `rolling(w, center=True)` labels the window at its centre [57],
so half the window is in the future of the labelled row — legitimate for
plotting and decomposition, a look-ahead the moment it becomes a model input.

**Prevalence.** Public corpus: `center=True` **0 occurrences** in 4,467 files —
so the `center` variant is free against the gate. Labelled corpus:
`tabular_forecast_shuffled/lags.py:33` records it as unsupported — *"`roll_mean_24`
at time t contains the value at time t, so the model can read its own answer out
of the feature"* — and line 34 repeats it with `expanding().mean()`. The clean
twin `tabular_forecast_clean` is the `_good.py`.

**Detection.** The IR is already built: `knowledge/pandas_tbl.py` gives
`rolling`/`expanding`/`ewm`/`cumsum` the `FRAME_TEMPORAL` role and keeps the
frame receiver family, so `frame[col].shift(1).rolling(24).mean()` resolves as
one four-link chain **today** — and the table's own docstring says *"No rule
keys on FRAME_TEMPORAL… the rules that want them can ask for them later."*
This candidate is that ask. Fire when the chain's base subscript key is the
literal target key, the chain contains a `FRAME_TEMPORAL` window, the chain
contains **no** `shift(k≥1)` before the window, and the assigned column reaches
a `FIT` or `SPLIT`.

**Guards.** (a) Literal target key only — a rolling mean of an exogenous column
is ordinary smoothing and must never fire. (b) Any `shift(k≥1)` before the
window, including `groupby(...).shift(1).rolling(...)`, suppresses. (c) The
assigned column must reach a model; a column computed and only plotted is
silent. (d) Suppress when the frame carries `TRAIN_SPLIT`. (e) ×0.7 on a
`groupby` panel base, where per-entity semantics are harder to be sure about.
(f) The `center=True` variant ships as a second arm of the same code, so one lag
block is one finding. (g) A related, weaker candidate held for tier 3: a
`TimeSeriesSplit` with no `gap=` where the target is a multi-step-ahead shift —
`gap` is documented as "the number of samples to exclude from the end of each
train set before the test set" [24], and the overlapping-label problem it
addresses is López de Prado's purging [108]. It must restate the literal horizon
and never assert an embargo length, which has no static answer.

**Evidence.** [57] (both `closed` and `center`); [95] L3.1; [101]; [107]; M4;
M6.

---

#### C-23 · `MLV128` — Backward fill or two-directional interpolation on a temporal frame

**Family** 1xx leakage (temporal) · **Severity** medium · **Effort** M ·
**Depends on** knowledge rows for the fill family (§6.2)

**Defect.** `frame.fillna(method='bfill')`, `frame.bfill()`, or
`interpolate(limit_direction='both'|'backward')`. bfill propagates "non-null
values from later positions to earlier positions" [58]. On a time-ordered frame
that moves information backwards across every future cut — the opposite
direction from the leak everyone looks for, which is why it survives review.
A second arm: `fillna(frame.mean())` computed over the whole frame is `MLV101`'s
defect written without a transformer.

**Prevalence.** Public corpus: the whole-frame-statistic arm is **2 sites / 1
repo** — `mlflow/examples/pytorch/CaptumExample/Titanic_Captum_Interpret.py:53–54`
fills age and fare with their means and splits at line 99, a textbook leak on
which MLView today reports `MLV401` and `MLV803` and **not** `MLV101` (M4).
Labelled corpus: `tabular_forecast_shuffled/lags.py:47` records the bfill arm
verbatim, with `tabular_forecast_clean/lags.py:48` (which uses `dropna`) as the
exact `_good.py`.

**Detection.** Add `bfill`/`backfill`/`interpolate`/`fillna` to the pandas method
table (`FRAME_TEMPORAL_METHODS` carries shift/rolling/diff/pct_change/resample
and not the fill family). Arm 1: a bfill spelling, or `interpolate` with
`limit_direction` in `{both, backward}`, on a `RAW_DATA`/`FEATURES` frame with a
temporal signal in the module (reuse `_temporal_signals` verbatim) and a `FIT`
or `SPLIT` downstream. Arm 2: `fillna(v)` where `v` traces to an aggregation of
the *same* SSA root.

**Guards.** (a) Arm 1 requires a temporal signal — a bfill on an unordered
categorical table is not a leak. (b) `ffill` is the correct direction and never
fires. (c) `groupby(...).ffill()` per group is fine. (d) Arm 2 requires the fill
value to trace to an aggregation of the same frame; a literal or a domain
sentinel (`-999`) is never a statistic. (e) Suppress when the frame carries
`TRAIN_SPLIT`. (f) Arm 2 must dedupe with `MLV101` when a `SimpleImputer` also
touches the frame — one root cause, one finding.

**Evidence.** [58]; [20] ("Always split the data into train and test subsets
first, particularly before any preprocessing steps"); [100]; M4; M6.

---

#### C-24 · `MLV214` — Target tensor reaching a loss without `.detach()`

**Family** 2xx training loop · **Severity** medium · **Effort** M ·
**Depends on** C-13's optimizer-ownership test; a per-loss record of which
argument is the target

**Defect.** `loss = F.mse_loss(q(s, a), target_net(s2).max(1)[0])` — the
regression target keeps its graph, so the optimizer also minimises by moving the
target. The canonical DQN / SAC / distillation bug; the run trains and the
objective is not the one the author wrote.

**Prevalence.** Labelled corpus **4 programs**, each recording it as unrulable:
`adv_ppo_bad` (*"no rule models a target tensor reaching a loss without
`.detach()`; MLV212 is the nearest later-tier code and it is about
`reduction=none`"*), `adv_sac_bad`, `adv_dqn_bad`, `adv_distill_bad` (M6).
Public corpus: 584 `.detach()` sites show the correct discipline is well
represented, which gives the guard signal.

**Detection.** For a `LOSS_FN`/`LOSS_CLS` call inside a backward-reachable
region, take the **target** operand — the knowledge table records which argument
position that is per loss FQN. Fire when that operand's producer chain contains
a `FORWARD` on any model and contains no `DETACH` role, no `.data`, no enclosing
`NO_GRAD`, and is not constructed from literals or labels. The `DETACH` role
already exists.

**Guards.** (a) Fire only when the target operand's model is **auxiliary** by
C-13's optimizer-reachability test, or is the same module under an explicit
target/EMA construction. (b) Never fire when the loss is symmetric in its
arguments by knowledge-table declaration — contrastive NT-Xent, cosine
objectives, consistency losses with a deliberately symmetric gradient.
(c) Suppress when `create_graph=True` appears on any backward in the region —
second-order training (`adv_meta_maml_bad` in the corpus needs the graph kept on
purpose) is explicit. (d) The GAN generator loss legitimately back-propagates
through the discriminator; C-13's two-optimizer partition excludes it.

**Evidence.** M6 (4 programs, quoted); no external catalog covers this — the
honest attribution is to MLView's corpus.

---

#### C-25 · `MLV129` — Transformer fitted on train, but the test matrix is never transformed

**Family** 1xx leakage / serving · **Severity** high · **Effort** M ·
**Depends on** SSA receiver identity (already present)

**Defect.** scikit-learn's **first** documented pitfall (their §12.1) [20]: a transformer is
fitted on the training half and the estimator is then scored on the raw,
untransformed test half. The guide shows the cost concretely — MSE 62.80 instead
of 0.90 on their own example. MLView has no rule: `MLV101`/`102`/`103` all fire
on the leak direction, and `MLV901` (unbuilt) only diffs training against a
separate *inference entrypoint*, so the single-script shape — the commonest one
in a notebook — is invisible.

**Prevalence.** Public corpus: a name-based proxy finds 43 candidate sites, but
**40 are in one notebook-derived file** where `X` is rebound between independent
sections, and the remaining hits are the same rebinding shape. That is precisely
the false-positive class MLView's SSA identity defeats and a name match does
not — the measurement is the argument for the design (§7.2).

**Detection.** A `FIT_TRANSFORM` on a transformer (reuse `_is_transformer_fit`,
the ROB-10 predicate `MLV101`/`102` already share) whose argument carries
`TRAIN_SPLIT`; record the **receiver** ValueRef R and the fitted output V. Find
an estimator `.fit` whose X is reachable from V, then a `PREDICT`/`SCORE` on that
estimator whose argument carries `TEST_SPLIT`/`VAL_SPLIT`. Fire when no
`TRANSFORM` **with receiver R** produces a value reachable from that argument.

**Guards.** (a) **Receiver identity, not name** — the `transform` must be on the
same ValueRef as the `fit`, which is what removes the 40-site notebook case.
(b) Skip when the estimator is a `Pipeline`/`make_pipeline`/CV-search object —
it transforms internally. (c) Skip stateless transformers
(`knowledge/sklearn.yaml:stateless_transformers`, already consulted by
`MLV101`/`103`). (d) Skip when the fit's output and the predict's argument come
from different `train_test_split` sites. (e) A name rebound between the fit and
the predict from a value not derived from the fitted one breaks the chain and
discloses through `ctx.untraced` rather than firing — the PUB-03 discipline.
(f) ×0.6 for unsupervised embeddings (`TSNE`, `MDS`, `Isomap`) that have no
`transform` at all: the code is odd but the accusation is wrong.

**Evidence.** [20] (their §12.1) with the 62.80/0.90 numbers; [104] Rule #32; [86]
("missing preprocessing" is a top-5 leaf, 11 GitHub/SO + 22 interview
instances).

---

#### C-26 · `MLV604` — Multi-worker loader with unseeded non-torch randomness

**Family** 6xx reproducibility · **Severity** low · **Effort** M ·
**Depends on** a dataset/transform-path walk

**Defect.** Verbatim: torch seeds each worker automatically, but "seeds for
other libraries may be duplicated upon initializing workers, causing each worker
to return identical random numbers" [2]. A Dataset or transform using
`np.random.*` or `random.*` draws the identical augmentation stream in every
worker — effective augmentation diversity becomes `1/num_workers`.

**Prevalence.** Public corpus: 267 loaders with `num_workers>0` and neither
`worker_init_fn=` nor `generator=`; **96** once python/numpy randomness is also
required in the file — and the class-scoped version will be smaller still.
96 is an upper bound, not a firing rate.

**Detection.** A `DataLoader` with `num_workers` resolving to an int literal > 0
(the same resolution `MLV112` performs), with neither keyword, where the
**dataset's class or the resolved transform Compose** — not merely the file —
contains a call whose FQN is under `random.*` or `numpy.random.*`.

**Guards.** (a) The randomness clause must be scoped to the dataset/transform
path, not the file; torch-only randomness genuinely is seeded per worker and
must be silent — the §4 sketch already says this. (b) **Lightning:**
`seed_everything(workers=True)` installs `pl_worker_init_function` on every
dataloader the Trainer sees, and a user-supplied `worker_init_fn` wins [54] — so
under Lightning the *absence of `workers=True`* is the defect, not the absence
of `worker_init_fn`. (c) accelerate and HF Trainer own worker seeding;
`negation_absent`. (d) Low severity: the cost is augmentation diversity, not
correctness. (e) Never stacks with `MLV601`/`MLV603`.

**Evidence.** [2] (verified verbatim); [54]; `ISSUE_RULES.md` §4 `MLV604` [110].

---

#### C-27 · `MLV606` — Non-deterministic file or label ordering

**Family** 6xx reproducibility · **Severity** medium · **Effort** M ·
**Depends on** reachability to a sample list or label mapping

**Defect.** A dataset's sample list or a label vocabulary built from
`os.listdir` / `glob.glob` / `set(...)` has filesystem- or hash-dependent order
— `os.listdir` returns entries "in arbitrary order" [67] — so class index 3
means a different class on another machine. A silent, unreproducible
relabelling: the model trains fine and its predictions mean something else.

**Prevalence and the reason the narrow form is the only form.** Public corpus:
**563 unsorted directory-listing call sites across 23 of 37 repositories** (M4).
A rule that fired on the call site alone would emit ~563 findings on a corpus
whose entire purpose is to stay clean. The reachability clause is not a
refinement; it is the rule.

**Detection.** An unsorted listing result that reaches **either** a Dataset's
sample list (an attribute assigned in a class whose base chain includes
`torch.utils.data.Dataset`, or the argument of an `ImageFolder`-style
constructor) **or** an index mapping that becomes label ids
(`{c: i for i, c in enumerate(...)}`).

**Guards.** (a) Reachability is mandatory: a listing used to count files, clean
a directory or write a log must never fire. (b) Skip when the result is passed
to `sorted`, `natsorted`, or a `.sort()` on the bound name. (c) Cap at one
finding per file. (d) Medium at most.

**Evidence.** [67] (normative); M4 (the 563 measurement is the guard's
justification).

---

#### C-28 · `MLV805` — Checkpoint written by every rank in a distributed job

**Family** 8xx checkpointing · **Severity** medium · **Effort** M ·
**Depends on** a rank-value resolution helper

**Defect.** N processes race on one path; the artifact is whichever rank
finished last, and can be a torn write.

**Prevalence.** Labelled corpus: `infra_ddp_sampler_bug/train_ddp.py:133` is the
**second** of only two `unruledDefects` rows in the entire corpus, with the
labeller's own `wouldBeRule` naming a new `MLV8xx`. The clean twin
`infra_ddp_correct` and the larger `vision_imagenet_ddp` pair exist.

**Detection.** A `SAVE`-role call inside a scope carrying distributed evidence
(`torch.distributed.init_process_group`, a DDP/FSDP wrap, a `RANK`/`LOCAL_RANK`
environment read, a `torchrun` entrypoint) with no enclosing guard comparing a
rank value to 0. The guard test is a syntactic ancestor walk over `If` tests
whose operands resolve to a rank-valued call or an env read — no name regex
creates it.

**Guards.** (a) Enumerate the guard spellings exhaustively (`rank == 0`,
`dist.get_rank() == 0`, `accelerator.is_main_process`, `trainer.is_global_zero`,
`fabric.global_rank == 0`) and refuse the absence the moment any comparison
against an unresolved rank-like value appears — `MLV705`'s escape hatch.
(b) Skip rank-aware framework APIs (`accelerator.save`, `fabric.save`, Lightning
callbacks). (c) Skip when the path expression contains the rank value —
that is deliberate sharding. (d) `negation_absent` for Lightning / accelerate /
DeepSpeed / HF Trainer.

**Evidence.** M6 (the `unruledDefects` row); [93] (MLmisFinder-class checkpoint
rules are tractable statically).

---

### Tier 3 — Later

These need an IR capability that does not exist, a corpus that does not exist,
or an advisory tier that does not exist (§6.7). Stated compactly: each carries
enough to be picked up later without re-deriving it.

#### C-29 · `MLV303` — `model.train()` never restored after evaluation
**Severity** medium · **Effort** L · **Depends on** IR-4 (the order-aware pass)

An `eval()` on a `MODEL` ValueRef with no `train()` on any path back into the
training step; every epoch after the first then trains with dropout off and
BatchNorm frozen. `ISSUE_RULES.md` §4 defers it explicitly because the
flow-insensitive IR makes the ordering weak, and the correct pattern —
`model.train()` at the *top* of the epoch loop — must be treated as restoring via
the loop back-edge [110]. **Measured price of not having that pass:** the naive
form ("an `.eval()` with no matching `.train()` anywhere") fires **257 times
across 24 of 37 repositories**; narrowing to files that also contain a
`.backward()` gives 19, and 5 of 5 sampled were still benign (generation entry
points, frozen second models). Two preconditions are mandatory: a confirmed
training loop must exist in the workspace, and the back-edge must count as a
restoration. [7], [75] ("Training/Evaluation Mode Improper Toggling").

#### C-30 · `MLV109` — Decision threshold selected on the held-out split
**Severity** medium · **Effort** M · **Depends on** knowledge rows for
`roc_curve` / `precision_recall_curve` (M5: both MISS)

`roc_curve` on a `TEST_SPLIT`, an `argmax` over a derived score picking a
threshold index, and that scalar used as a cut-off producing `PREDS` on the same
split. The reported F1 is a maximum over `|thresholds|` choices made on the
reporting data; scikit-learn says "You should never use the same data for
training the classifier and tuning the decision threshold" and names
`TunedThresholdClassifierCV` as the supported route [28]. **Prevalence caution:**
`roc_curve` appears 7 times and `precision_recall_curve` 5 times in 4,467 files,
and the full four-step chain appears in none of them — so the rule may be
unreachable on real code and needs a written fixture plus corpus programs before
it counts as coverage. SpecDetect4AI measures its threshold rule at F1 0.34, the
worst of its 22 [84] — ship narrow or not at all. [28], [103].

Three sibling candidates sit behind the same knowledge work and are recorded
here so they are not re-derived: a **calibrator fitted on the classifier's own
training rows**, which scikit-learn warns "would thus result in a biased
calibrator" [27]; **only accuracy reported where imbalance is signalled**
(`MLV307`), for which `balanced_accuracy_score` exists precisely because it
"avoids inflated performance estimates on imbalanced datasets" [29]; and
**R² reported on a short forecast horizon**, where the baseline the formula
compares against is the in-sample mean [31] and the forecasting metrics are
MAE/RMSE/MAPE [107]. A fourth, for recommender systems: a **negative sampler
built from the full interaction set** and shared across a timestamp cut, which
Ji et al. measure as changing accuracy and making relative model orderings
unpredictable across four datasets [102].

#### C-31 · `MLV901` / `MLV902` — Train–serve skew
**Severity** medium · **Effort** L · **Depends on** an entrypoint role
classifier and resolved web-route decorators (§6.1, IR-8)

A transform reachable from a training entrypoint and not from an inference one
(`MLV901`); a `from_pretrained('<A>')` on the training path and `'<B>'` on the
serving path for the same role (`MLV902`). scikit-learn states it first-party —
"If these data transforms are used when training a model, they also must be used
on subsequent datasets, whether it's test data or data in a production system"
[20] — and Google's Rules of ML names a discrepancy between the two pipelines as
the first cause of skew, with Rule #32 prescribing shared code [104]. **The
machinery already exists:** `core/pipelines.py`'s `PipelineIndex.reach` maps each
entrypoint to its reachable nodes, and `PipelineIndex.shared` names nodes two
entrypoints both reach — a transform in `shared` is by definition not skewed, so
the dominant false-positive guard is pre-built. What is missing is the
classifier: `core/build_edges._entrypoints` ranks by main-guard then by filename
(`train.py`, `main.py`, `run.py`, `__main__.py`) and caps at 10, so it is
train-biased by construction and a `serve.py` can be dropped entirely; and
`FunctionIR.decorators` falls back to a bare dotted name when resolution fails,
so `@app.post` is recorded as the string `"app.post"` — matching on that would
violate iron law 1. **Not measured:** this is a whole-workspace claim and the
file-scoped sweep cannot approximate it; the firing rate is unknown.
`MLV902`'s measured caution: 12 public files carry more than one distinct
`from_pretrained` literal and every sampled one is a legitimately multi-model
program, so the **role partition** (tokenizer vs model) is not optional.

#### C-32 · `MLV806` — Export pins static shapes
**Severity** low · **Effort** S (rides on C-08's knowledge rows)

`torch.onnx.export` with neither `dynamic_axes` (legacy) nor `dynamic_shapes`
(dynamo): "By default the exported model will have the shapes of all input and
output tensors set to exactly match those given in `args`" [12]. Serving then
silently rejects or mishandles any other batch size. **Prevalence** 11 sites / 5
repos (M4), and the sampled ones are tutorials exporting a fixed-shape
classifier where that is the point — so this is advisory, phrased as a question.
**The API version matters and the rule must read it:** with `dynamo=True`,
`dynamic_axes` is ignored and `dynamic_shapes` is the keyword; getting it
backwards would advise the deprecated one. 4 of the 19 measured export calls
pass `dynamo=True`, so the split is real in this corpus.

#### C-33 · `MLV704` — Submodule invoked as `self.sub.forward(x)`
**Severity** low · **Effort** S · Advisory group

Bypassing `__call__` means "the former takes care of running the registered
hooks while the latter silently ignores them" [7] — so quantization observers,
feature-extraction hooks, FSDP pre-forward logic, activation checkpointing and
profiling silently stop for that submodule. dslinter ships it [75].
**Prevalence** 14 sites / 5 repos (M4); of 5 sampled, 2 are mmdetection
`_forward()` debug entry points and RPC `RRef` proxies where the author is
deliberately reaching past the wrapper — which is why this is low and advisory.
Guards: `super().forward` excluded; the receiver must resolve to a Module base
(that alone kills the RRef case); de-rate inside tracing/export helpers; de-rate
when no hooks are registered anywhere in the workspace.

#### C-34 · `MLV605` — Nondeterministic backend alongside a determinism request
**Severity** low · **Effort** M · **Depends on** IR-6 (resolved attribute
assignments — MLView has **no rule that reads an assignment today**)

`torch.backends.cudnn.benchmark = True` in a workspace that also seeds:
`benchmark=False` "causes cuDNN to deterministically select an algorithm" [3],
so the two settings ask for incompatible things. **Prevalence** 20 sites / 7
repos, of which **4 also seed** (M4): `diffusers/examples/vqgan/train_vqgan.py:557`,
`yolov5/utils/dataloaders.py:381`, `pytorch-examples/dcgan/main.py:51`,
`DeepLearningExamples/.../ConvNets/main.py:676`. The other 16 are benchmark and
inference scripts where the setting is correct — the seed conjunction *is* the
claim. Two measured guards: an adjacent `cudnn.deterministic = False` is an
informed opt-out (the diffusers case), and an inference-only scope with a
fixed-shape comment is the right call (the yolov5 case). Frame as a trade-off,
not an error. `ISSUE_RULES.md` §4 `MLV605` [110], [75].

#### C-35 · `MLV130` — Mask / index-based split leakage
**Severity** high · **Effort** L · **Depends on** generalising `MLV102`'s fold
projection

`loss = F.cross_entropy(out[data.test_mask], y[data.test_mask])` in the training
step; or a support/query pair cut from the same index slice. Identical to
`MLV102` in consequence, but there is no transformer and no split call, so
nothing sees it. Three corpus programs record it, one of them calling it *"the
single highest-severity defect in the program, and MLView says nothing"*
(`adv_gnn_bad`, `adv_gnn_sage_bad`, `adv_meta_maml_bad`). Detection must be
identity-based — one mask value subscripted inside a backward-reachable
statement and the *same* mask value subscripted inside an eval region — not two
similarly named bindings. Guards: transductive learning legitimately forwards
over all nodes, so fire only when the held-out mask indexes the **target**
operand of a loss, never the forward's input; carve out
`sklearn.semi_supervised`; emit medium until a two-fixture pair exists.
Depends on IR-1 (subscripts preserving identity), which is why it is here and
not in tier 1.

#### C-36 · The performance advisory group
**Severity** low · **Effort** M · **Depends on** §6.7 (an advisory tier)

Three candidates that are true and cheap and must not enter the Problems panel:
`empty_cache()` in the batch loop (64 in-loop vs 189 out-of-loop sites — the
split is the discriminator, and 5 of 5 sampled in-loop cases were the deliberate
`del pipeline; empty_cache()` idiom); `.item()`/`.cpu()` synchronisations at
≥3 per step (78 files) [14]; `model.to(device)` inside the loop — which must key
on the `MODEL` tag, because a receiver-blind version matches 595 tensor moves
across 272 files and would be the noisiest thing in the catalog. All three are
`low`, aggregated one-per-loop, worded as a cost.

#### C-37 · `tf.function` side effects and non-singleton `tf.Variable`
**Severity** medium · **Effort** M · **Not measured**

The largest single uncovered area in the merged catalog: SonarSource ships 7
TensorFlow rules (S6908 recursion, S6911 global/free-variable dependence, S6918
non-singleton `tf.Variable`, S6928 Python side effects, and three more) [71] and
MLView ships **0**, despite 284 TF knowledge rows. Tracing runs the Python body
once per input signature, so a `print`, a list append or a counter increment
happens on the first trace and never again — the developer's logging, their
accumulator and their augmentation counter all quietly stop. Ship the
unambiguous variants first (`print`/collection mutation; a `tf.Variable` created
outside a singleton guard; self-recursion) and hold the global-dependence arm
for the advisory group. **Not measured here:** keras-io and tensorflow-models use
`tf.function` heavily and a naive version would be noisy; this needs its own
two-stage sweep (§7.2) before it is scheduled.

---

## 6. The accuracy program

### 6.1 IR improvements, ranked by recall unlocked

Ranked by labels recovered per unit of risk. The first three are each smaller
than a single new rule and between them address 44 of the 107 misses.

| # | Change | Labels | Pts | Effort | Risk |
|---|---|---:|---:|---|---|
| **IR-1** | Value identity survives a `Subscript` | 5 (+co-blocks 4) | 0.9 | S | low, bounded |
| **IR-2** | Shape-preserving methods and framework output objects are transparent | 9 | 1.6 | S | low |
| **IR-3** | Cross-scope identity: tuple slot, `self.<attr>`, one caller hop | 17 | 3.1 | M | **medium — touches a precision guard** |
| **IR-4** | Arithmetic propagates `LOSS`; `.backward()` is a `LOSS` witness | 8 | 1.5 | M | medium |
| **IR-5** | Record the autocast dtype on the CallSite | (enables C-10) | — | S | none |
| **IR-6** | Duck-typed `MODEL`/`OPTIMIZER`; union identity tags in the IP summary | 6 | 1.1 | M | low |
| **IR-7** | Column-level provenance and a resolved attribute-assignment index | (enables C-21, C-22, C-34) | — | M | none (additive) |
| **IR-8** | Recognise a boolean / quantile / `iloc` cut as a `SPLIT` | 7 graph ops | — | M | **medium — mints new split tags** |

#### IR-1 · Value identity survives a `Subscript`

**Problem.** A tag is dropped the moment a value passes through
`ast.Subscript`. `predict_proba(X)[:, 1]` loses `PROBS`;
`probabilities[data.test_mask]` loses the softmax producer; `logits[mask]` loses
`LOGITS`. Five misses directly, and it is the prerequisite for C-35.

**Design.** In `ir/bindings_values.py`, when the RHS is a Subscript, resolve the
base and copy its producer, `class_ir`, `canonical_fqns` and its **value-kind**
tags (`LOGITS`, `PROBS`, `PREDS`, `LOSS`, `FEATURES`, `TARGET`, `MODEL`) onto the
new ValueRef, recording a `projection` hop so the rules pay the existing
`IP_HOP_WEIGHT`. Rule side: `MLV305`/`MLV306`'s `_decided` predicate must treat
a non-scalar slice as transparent rather than as a decision.

**The one direction this can be wrong, and the guard.** Do **not** copy
*split-provenance* tags (`TRAIN_SPLIT`/`VAL_SPLIT`/`TEST_SPLIT`) through a
boolean-mask or fancy-index slice: a mask can select a different partition from
its base, and that is exactly the laundering the leakage family's precision
depends on not doing. Copy value-kind tags only. Exclude an index containing a
comparison (`probs[probs > 0.5]` is a different value). Every projected finding
carries a hop and can therefore never reach `certain`.

**Blast radius.** 27,036 `name[...]` subscripts in the public corpus — large by
volume, which is why the tag partition is not optional. Against that, the shape
IR-1 unblocks (a class metric fed `predict_proba(...)`) occurs **0 times** in
4,467 files, so the measurable precision risk on the current gate is nil.

#### IR-2 · Shape-preserving methods and framework output objects

**Problem.** `.view/.reshape/.squeeze/.unsqueeze/.flatten/.permute/.transpose/
.contiguous/.ravel/.t` terminate the producer chain, so a sigmoid at the tail of
a `Sequential` is invisible to `MLV401`/`MLV402`. Separately, an HF `ModelOutput`
attribute read (`outputs.loss`, `outputs.logits`) produces an untyped value, so
`outputs.loss.backward()` back-propagates something MLView cannot type and the
whole `MLV2xx` family goes silent on the program. MLView says so itself: of 66
`untagged_dataflow` diagnostics, 21 are *"back-propagates a value MLView could
not type."*

**Design.** (a) Extend `valuetype._PASSTHROUGH_METHODS` [119] — which already
carries `{detach, cpu, cuda, numpy, tolist, clone, contiguous}` with the
documented rationale "the `.detach().cpu().numpy()` tail that every torch
program writes" — with the shape-only set, behind **two flags** rather than one:
`changes_container` (transparent for identity) and `detaches_graph` (opaque for
`MLV205`). `.detach()` is transparent for identity and opaque for the graph
question; conflating them would break `MLV205`. `.item()`/`.tolist()` are **not**
in the set: they really do change what the value is.
(b) Knowledge rows on `transformers.modeling_outputs.ModelOutput.<attr>`:
`.loss → LOSS`, `.logits → LOGITS`, `.last_hidden_state → FEATURES`,
`.predictions → LOGITS`, gated on the receiver already carrying `MODEL_OUTPUT`
from a resolved HF model call — never on a bare `foo.loss`.

**Blast radius.** 5,138 shape-only chains and 252 `.loss` / 112 `.logits` reads
in the public corpus; the HF half is precisely bounded by the receiver gate.

#### IR-3 · Cross-scope identity — and the guard it must not break

**Problem.** 17 misses, three shapes (§3.1 cause D). This is the only IR change
on this list that touches a guard written in response to a measured regression,
and it must be treated accordingly.

**Design.** (a) Give `ValueRef` a resolved `origin_expr` — the AST node in the
defining scope that produced it — populated from a Tuple-unpack target index
matched against the callee's return tuple position (`ir/returns.py` already
computes `_returned_names(func, index)`), and from a parameter resolved to the
argument expression **only when every call site agrees**. (b) Treat
`self.<attr>` as a ValueRef keyed by `(class, attribute)` within one class, so a
fit in `build()` and a split in `materialise()` are the same value.
(c) For `MLV101`, replace the name-based `_split_consuming` match with an
identity match on the ip path only, leaving `--dataflow local` byte-identical.
(d) For `MLV106`, collect temporal signals workspace-wide but require the split's
input to be **reachable from** a signal-bearing value, not merely co-resident.

**The regression this must not reproduce.** REV5-01 confined `MLV101`'s fit↔split
match to one scope because `_split_consuming` matched by *dotted name*, and a
shared local name in two functions produced a self-contradicting high-severity
finding. The confinement is correct for a name match and unnecessary for an
identity match — but the distinction is the entire safety argument, so:
identity never name; reachability never co-residence; every cross-scope claim
pays its hops and cannot reach `certain`; and the program that produced the
original regression (`hydra_research`) is in the corpus and is the gate.
For `MLV103`, note the guard becomes **more** informed, not less: the refusal
exists because the caller's binding did not record which tuple position it
unpacked, and slot identity is exactly what supplies it.

#### IR-4 · Arithmetic propagates `LOSS`; `.backward()` is a witness

**Problem.** `loss = criterion(...) / ACCUM_STEPS` and
`g_loss = w1*pixel + w2*perceptual + adv` drop the `LOSS` tag, silencing
`MLV201`/`202`/`203`/`205`/`206` on every RL, GAN, VAE and multi-task program.
`vision_vae_bad`'s own gap note states the conclusion: *"every train-loop rule is
silent on this program because the loss comes from `elbo()`, a function whose
return is an arithmetic combination."*

**Design.** (a) When the RHS is a `BinOp`/`UnaryOp` whose operands include
**exactly one** tensor-tagged value and whose others are scalars, module
constants or config reads, propagate the tensor operand's tags with a `combined`
hop. Two `LOSS` operands combine to `LOSS`. (b) A converge pass: for every call
with method `backward` whose receiver is a resolvable local name, union `LOSS`
onto that binding and re-run the tag fixpoint — a value on which `.backward()`
is called **is** a differentiable objective, and that is the one unambiguous
witness the language offers.

**Guards.** Exactly one tensor-tagged operand; two differently-tagged operands
produce **no** tag rather than a union. Never propagate `FEATURES`/`TARGET` or
any split tag through arithmetic — `MLV101`'s precision argument depends on split
identity being exact. Restrict the witness to `backward` on a simple local Name
or Attribute in the same scope. Both behind the ip/local flag split, as
DATAFLOW-IP already is. 663 `.backward()` sites in the public corpus make (b)
the cheapest high-value change on this list.

#### IR-5 · Record the autocast dtype

`MLV208` and C-10 both need to know whether an AMP region is fp16 or bf16, and
nothing in the IR answers it. At the `AUTOCAST` call site record `amp_dtype`:
the `dtype=` literal if present; else `float16` when `device_type` resolves to
`'cuda'`; else `bfloat16` when `'cpu'`; else **`unknown`**. `unknown` must never
default to float16 — only 8 of the corpus's autocast sites pass an explicit
dtype (M4), so most answers come from the device literal and the evidence string
must say which.

#### IR-6 · Duck-typed identity, and union (not intersection) in the IP summary

**Two halves of one fact.** (a) `ir/summaries.py` applies the argument→parameter
summary with intersection across call sites. Partition the tag vocabulary:
**identity** tags (`MODEL`, `OPTIMIZER`, `LOADER`, `DEVICE`, `LOSS`,
`FITTED_TRANSFORMER`) **union** across sites; **provenance** tags (`RAW_DATA`,
`FEATURES`, `TARGET`, the three split tags, `BATCH`) keep intersection. The
false positive the intersection rule was written to prevent is a *cross-object
leakage* claim, and that is entirely inside the provenance set, which is
untouched. Provenance chains merge to the **longest** chain so the hop de-rate
reflects the weakest site. (b) A converge pass duck-types `MODEL` from member
evidence — the receiver of `.parameters()`, `.state_dict()`, `.train()`,
`.eval()`, `.requires_grad_()`, or the first argument of a resolved
`torch.optim.*` / `DataParallel` / `DDP` / `torch.compile` / `fabric.setup` /
`accelerator.prepare` — requiring either one knowledge-resolved witness or two
independent unresolved-method witnesses. One bare `.parameters()` is not enough.

**Evidence.** 36 of 44 `truncated` diagnostics are the intersection refusal, and
they name the lost parameter: `device` 17×, `model` 8×, `loader` 4×. Six labels
follow directly. `hydra_research` supplies the duck-typing half: the model comes
from a dict-of-factories registry and carries no tag, yet `model.parameters()`
is called thirteen lines away.

#### IR-7 · Column provenance, and an attribute-assignment index

Two additive affordances that unblock five candidates and no existing rule reads:

- **`ValueRef.column_keys: frozenset[str] | None`**, populated from *literal*
  subscripts only (`df["a"]`, `df[["a","b"]]`, `df.drop(columns=[...])`,
  `df.assign(k=…)`, `get_dummies` → `None`). `None` means unknown and every rule
  reading it must fall silent rather than guess, exactly as `ctx.untraced`
  already does for tags. `ISSUE_RULES.md` §4's `MLV105` sketch **assumes** this
  facility, which is why that rule has been unbuilt for four sprints.
- **`ctx.attr_assignments(*fqns)`** — MLView has no rule that reads an attribute
  assignment today, and C-34 plus any future `torch.backends.*` rule is an
  assignment. `ir/symbols.resolve` already canonicalises arbitrary
  `Name`/`Attribute` chains against the alias table, so
  `torch.backends.cudnn.benchmark = True` and `cudnn.benchmark = True` reach the
  same FQN — which is what makes such a rule legal under iron law 1 rather than
  a bare-attribute match. Return **only** assignments whose target resolved.

A third, larger one belongs here for the record: a **DataFrame-typed receiver**
answer, without which pandas chained assignment cannot be a rule. The measured
reason: 350 chained-subscript assignments in the public corpus, and 0 of 5
sampled were pandas at all — nested dicts, config trees, numpy arrays and torch
tensors, for all of which the pattern is correct.

#### IR-8 · A boolean, quantile or `iloc` cut is a `SPLIT`

```python
cutoff = frame["event_time"].quantile(0.9)
train  = frame.loc[frame["event_time"] <  cutoff]
test   = frame.loc[frame["event_time"] >= cutoff]
```

This is the **correct** temporal split, five corpus programs use it, and MLView
draws no split node and mints no split tags for it — so `MLV101`, `MLV102`,
`MLV103` and candidates C-01, C-02, C-22 are blind to the whole class of
programs that split without `train_test_split`. Recognise two complementary
comparisons (`<`/`>=` or `<=`/`>`) on the same SSA frame against the same scalar,
both bound; also `frame.iloc[:n]` / `frame.iloc[n:]` and `frame[frame.index < ts]`.
Tag the earlier side `TRAIN_SPLIT` and the later `TEST_SPLIT` when the compared
column carries a temporal signal.

**Risk, stated plainly.** Drawing a split box where a split exists is right; the
risk is downstream, because newly minted split tags will activate high-severity
leakage rules on code that was previously invisible. De-rate by one confidence
bucket relative to a `train_test_split`-derived tag, record it as a provenance
hop so `hops()` de-rates automatically, and measure on the full corpus **and**
the public gate before recording a baseline.

### 6.2 Knowledge-table expansion plan

**The discipline first, because it has a precedent.** Round R2 of the recall
campaign shipped nine new roles **with no rule keys on any of them**, purely so
the diagram could draw the box — and graph fidelity moved 84.5 % → 86.2 % on
that alone [111]. Rows first, rules later: a row with no rule key cannot fire,
so the identification half of every gap below can land, be measured, and improve
graph fidelity before any rule is armed.

**Batch 1 — the rows that make tier-1 candidates reachable at all** (each is
MISS today, M5):

| Rows | New role | Unblocks |
|---|---|---|
| `torch.onnx.export`, `torch.jit.trace`, `torch.jit.script`, `torch.export.export` | `EXPORT` (deliver stage) | **C-08**, **C-32** |
| `torch.utils.data.distributed.DistributedSampler.set_epoch` | `SAMPLER_EPOCH` | **C-09** |
| `imblearn.base.BaseSampler.fit_resample` (+ the full `over_sampling`/`under_sampling`/`combine` constructor set — 4 rows today) | `RESAMPLE_FIT` | **C-01** |
| `sklearn.model_selection.{StratifiedGroupKFold, GroupShuffleSplit, LeaveOneGroupOut, LeavePGroupsOut, RepeatedKFold, RepeatedStratifiedKFold, PredefinedSplit}` | `SPLITTER` | **§6.5 D2**, **C-20** |

That last row is not merely a gap: four of those FQNs are **already written into
rule source** as strings (`holdout_splits.ORDERED_SPLITTERS`,
`r_repro._SHUFFLE_OPTIONAL`) while the knowledge table has no row for them — so
those entries are dead code today and adding the rows changes live behaviour.
Ship them with corpus labels ready.

**Batch 2 — the families that disable whole rule groups.**
**MONAI** is the sharpest case: `monai.data.DataLoader` is a
`torch.utils.data.DataLoader` subclass [63] and is not recognised, so no `LOADER`
tag exists and the entire `MLV1xx` family plus every `MLV2xx` rule keyed on it
is unreachable for medical imaging. `vision_medical3d_bad` loses 3 labels to
this and its own gap note says so. Add `monai.data.{DataLoader, CacheDataset,
Dataset, PersistentDataset}`, `monai.transforms.Compose` with the
`Rand*`/deterministic split (MONAI's own `Rand` prefix convention makes it
mechanical), `monai.inferers.sliding_window_inference` declared as
**model-in-argument-position** so `eval_regions` can find the receiver, and
`monai.losses.{DiceLoss, DiceCELoss, FocalLoss}`.

**Batch 3 — identification-only rows that remove diagnostics and lift graph
fidelity.** MLView names its own gaps: 52 of 73 `unresolved_callee` diagnostics
are literally *"no knowledge table for X"* — PIL 13, gymnasium 6, cv2 6, monai 4,
fastapi 3, optuna 2, faiss 2, onnxruntime 2, then one each for
`stable_baselines3`, `lifelines`, `sksurv`, `peft`, `trl`, `ray`, `bitsandbytes`,
`apex`, `flax`, `jax`, `optax`, `pyspark`, `airflow`. The five worst graph-fidelity
programs are all in that list, and 39 of 95 missing graph ops come from five of
them.

**Batch 4 — rows keyed by an argument, and two new value tags.**
`timm.data.create_transform` exists as a row but nothing reads its
`is_training=` literal, which is the single keyword that decides train-vs-eval
[64]. `keras.layers.{TextVectorization, Normalization, StringLookup,
IntegerLookup, Discretization}.adapt` is the Keras spelling of `fit` [40] and has
no row, so neither the correct ordering nor the leaking one can be scored —
`nlp_keras_text` records exactly that. Two tags are genuinely new facts that no
existing tag encodes and should go through a CONTRACTS v1.2: `GROUP_KEY` (C-20)
and `RESAMPLED` (C-01).

**The one live risk.** A knowledge row is not a claim, but adding a *role* can
arm a rule that was previously blind. `gbm_tbl.py` records both directions of
this: a missing Booster row hid three whole stages (PUB2-08), and a wrongly
assigned `PREDS` tag made `MLV306` fire at 0.90 on textbook-correct code [113].
Add rows in small batches and re-run both gates between batches.

### 6.3 The evaluation region — the single largest lever

Two changes to `rules/eval_regions.py` address 16 of the 107 misses (2.9 points)
and touch the two rules with the most labels in the corpus. Neither is a new
rule.

**(a) A third region kind.** Today a region is a loop or function that is named
by `_EVAL_NAME_RE` [118], contains a metric call, or carries a `no_grad`
decorator. Add: *a function or loop containing a `FORWARD` on a `MODEL`-tagged
ValueRef from which no `BACKWARD`/`OPT_STEP` is reachable (transitively, through
the same one module-local call hop the rules already follow), whose model's
resolved class contains a `DROPOUT` or `NORM_TRAIN_SENSITIVE` submodule.* That
last clause is what makes the claim actionable — a model with no train/eval
sensitive layer does not care. `GenerationMixin.generate` counts as a forward by
declaration.

The name set may be widened in parallel (`sample|generate|decode|render|extract|
encode|embed|reconstruct|denoise|query|gallery|retrieve`) but **only as
reinforcement**: iron law 2 means the name never creates the region. The
positive evidence is the dataflow — a forward whose output reaches a
`save_image` / `PIL.Image` / `np.save` / `faiss.add` / returned-list sink, or a
region reached from a site that is itself post-training.

**Guards.** Require the absence of a reachable backward *in the region*, and
require the region not to be lexically inside a batch loop that has one — that
case is C-13, a different finding about a teacher forward, and conflating them
would be a high-severity false positive. Keep the existing pytest exclusions.
Pay a hop and de-rate when the region is reached through a call.

**(b) Judge each model value, not the region.** `EvalRegion` already carries
`model_ref`. Enumerate **every** distinct `MODEL`-tagged ValueRef forwarded in
the region and require the `EVAL_MODE` / `NO_GRAD` evidence **per ValueRef**.
Today a single `teacher.eval()` satisfies the region and the untrained student
is never checked — which is precisely the two measured misses
(`nlp_distil_bert_bad`: *"only the teacher is put in eval mode, on line 75"*;
`nlp_dpo_preference_bad`: *"only the reference model is put in eval mode, on
line 94"*). Guard: only models whose resolved class contains a train/eval
sensitive submodule; and an unresolved receiver is **not** an absence — stay
silent, the `MLV705` rule.

This change also unblocks C-08, which needs the same "this value was never
evaluated" notion.

### 6.4 Ground-truth expansion: mining real bug-fix commits

**Why.** All 546 labels are MLView's own. `ACCURACY.md` says as much, and the
173 "no rule models this" rows prove the corpus is shaped by the catalog: a
defect with no rule cannot be labelled as expected. Recall measured that way is
a measurement of a corpus written by the project that writes the rules.

**How, concretely.** Mine paired before/after states from real fix commits,
which give a defect and its correct twin **for free** — the same structure the
corpus already relies on.

1. **Query.** Over the pinned repositories plus a wider set of ML repositories
   with a permissive licence, search commit messages for the defect vocabulary
   this document has assembled: `set_epoch`, `weights_only`, `restore_best_weights`,
   `worker_init_fn`, `detach`, `requires_grad`, `\.eval\(\)`, `unscale_`,
   `GradScaler`, `from_logits`, `log_softmax`, `stratify`, `groups=`,
   `shuffle=False`, `drop_last`, `zero_grad`, `leak`, `leakage`. Restrict to
   commits touching ≤ 3 Python files with ≤ 30 changed lines — the size band where
   a commit is one defect rather than a refactor.
2. **Filter.** Keep commits where the *pre* state produces a candidate shape and
   the *post* state does not. That is a mechanical filter using the same AST
   sweep as §7.2, and it is what makes this tractable at scale.
3. **Adjudicate.** A human reads the commit message and the diff and writes the
   label. The commit message is the ground truth for intent, which is the part
   static analysis cannot supply.
4. **Import.** Write an *equivalent* program into the corpus — never copy
   repository source (the existing corpus already does this with neutral fixture
   paths, and it is what keeps redistribution clean).

**Licensing, stated properly.** The pinned corpus is used read-only for
measurement, which is fine. Importing code is different. Only permissive
licences (MIT / BSD / Apache-2.0) should be considered at all, and even then the
recommendation is to **write equivalents rather than copy**: it avoids the
attribution and notice obligations entirely, it lets the fixture encode the
*nearest false-positive trap* rather than whatever the original happened to
contain, and it keeps the corpus a teaching artifact rather than a derived work.
Record the source commit URL in the label's `note` for provenance without
carrying the code. Never import GPL/AGPL, never import code with no licence
file, and never import from a repository whose licence post-dates the commit.

**The cheaper half, available immediately.** Three external benchmarks are
already labelled by other people and need no mining: **defect4ML** [89] (100
reproducible TF/Keras bugs across 30 Humbatova fault types), **NeuraLint's**
34-program set [93] (which reports 100 % precision / 70.5 % recall, a directly
comparable pair), and **Yang et al.'s** leakage notebooks [96]. Running MLView
over these and reporting the number unchanged would give `ACCURACY.md` its first
externally-anchored figure. Expect it to be much lower than 80.4 %; that is the
point of running it (§7.3).

### 6.5 Precision protections

Precision is the product. Four items, in order of urgency.

**D1 — `keras.Model.predict` is tagged as hard labels.** The confirmed defect
from §1.4. `other_tbl.py:45` [114] must become `("PROBS",)` when the model's
final layer carries `activation='softmax'/'sigmoid'` (`MLV709` already resolves
that layer through a builder hop and a parameter hop, so the machinery exists),
`("LOGITS",)` otherwise, and `("PROBS",)` when the head is unresolvable —
because `PROBS` is the **conservative** tag: it silences `MLV306` and still lets
`MLV305` fire. Then `rules/valuetype.py` answers both rules correctly with no
rule change. Audit `keras.Model.predict_on_batch`/`predict_generator`
(`tf_tbl.py:224/229`), `transformers.Trainer.predict` (`other_tbl.py:104`, which
returns a `PredictionOutput` carrying logits) and the statsmodels `.predict` rows
(`stats_tbl.py:72–102`, which return probabilities for Logit/Probit/GLM-binomial)
the same way.

Additionally, make `MLV306`'s producer test **framework-aware** rather than
role-based: "the `PREDICT` role" is not the same claim as "returns class
labels". Introduce an explicit `HARD_LABEL_PRODUCERS` set —
`sklearn.base.BaseEstimator.predict` and the sklearn-wrapper estimators, plus
`MLV306`'s existing `ARGMAX` arm and a threshold comparison — and let everything
else tagged `PREDS` be a producer `MLV306` must not cite. Keep the score-metric
carve-out (`roc_auc_score`, `average_precision_score`, `log_loss` are never
`MLV305` targets) exactly as it is.

**D2 — the `MLV106` splitter table.** Move `GroupShuffleSplit` out of
`_SHUFFLE_OPTIONAL_SPLITTERS` into an always-shuffles set (with `ShuffleSplit`,
`StratifiedShuffleSplit`, `RepeatedKFold`, `RepeatedStratifiedKFold`) — it has
no `shuffle` parameter [22]. Add `StratifiedGroupKFold` to
`_SHUFFLE_OPTIONAL_SPLITTERS` — its `shuffle` defaults to False [23]. Add a unit
test asserting each splitter's classification against its documented signature,
so the table cannot drift again, plus two fixtures: `StratifiedGroupKFold` on
temporal data (must not fire) and `GroupShuffleSplit` on temporal data (must
fire).

**D3 — `MLV803` must stop asserting something that is no longer true.** Split
the rule's three claims, which today share one message. Arm 1 (`torch.save` of a
whole module) is a real, stable defect and stays `certain` — it is the arm worth
keeping, and it is what fires on `pytorch-examples/word_language_model/main.py`.
Arm 2 (`weights_only`) should fire **only** on an explicit `weights_only=False`,
or when the workspace pins `torch<2.6` (readable from `pyproject.toml` /
`requirements*.txt`); an absent keyword on an unpinned workspace is no longer
evidence, because the default is `True` [1]. Arm 3 (`map_location`) should be
deleted as a *finding* and kept as a Note — it is a portability convenience, not
a correctness requirement. Two further guards the measurement supplies: a
`**kwargs` splat into `torch.load` is dynamic and supports no absence claim
(fastai computes `weights_only` from a version check and passes it through
`**load_kwargs`); and arm 1 must key on the `MODEL` tag, never the name — 3 of 5
sampled name-based matches were dict-valued variables (`model_data`,
`model_state_dict`). This matters at volume: `MLV803` is the **second-largest**
contributor to the public-corpus findings at 118 of 706 (M11).

**D4 — narrowings for rules that are about to get wider.**
`MLV601` must keep `is_seeded` and `MLV603` must not (C-07).
`MLV114`'s widened kwarg surface (`augment=`, positional, split flag) must still
require the bound value to be a Compose containing an `AUGMENT`-role element,
and must keep the TTA carve-out and the one-finding-per-Compose dedupe.
`MLV103`'s widened producer set (adding `RESAMPLE_FIT`, target-reading
aggregations, and in-workspace classes whose `fit` stores state on `self`) must
gate that last clause on the class also defining a `transform` that *reads* the
attribute the fit wrote, and must de-rate it by one bucket — it reasons about
`self`, not about a knowledge row.

### 6.6 Calibration and confidence

**The finding.** 43 of 439 recovered true positives are invisible, all four
buckets are at 100 % observed precision, and the calibration error is 0.40 in
`possible` and 0.65 in `speculative` (§3.3). The model is systematically
under-confident and the cost is paid entirely in visible recall.

**What to change, and what not to.** Do **not** move the 0.60 threshold: it is a
product contract (the Problems-panel default), and moving it changes what a red
octagon means. Do not "raise confidence because the corpus says precision is
100 %": the corpus is labelled exhaustively so that an unlabelled finding counts
as a false positive — it is built to make precision *measurable*, not to be a
natural distribution, and a bucket at n=17 flips by half on one label.

**Change the targeting instead.** `WRAPPER_FACTOR = 0.4` is applied whenever an
absence rule sees a framework wrapper **anywhere in the workspace**. Scope it to
regions the wrapper actually governs: the region is a framework hook
(`eval_regions.framework_hook` already answers this), **or** the model reaching
the region is the one handed to the wrapper (`Trainer(model=m)`,
`trainer.fit(module)`, `accelerator.prepare(m)`, `fabric.setup(m)`), **or** the
region is lexically inside a callee of the wrapper. A hand-written loop over a
hand-built loader, in a module that merely *imports* a wrapper, is not governed
and takes no de-rate. Keep the full 0.4 for any finding whose region or model
MLView could not separate from the wrapper — the default stays conservative.

This cannot create a finding; it can only move an existing one across 0.60. All
43 currently below it are true positives, and `MLV301` alone recovers 13.

**Then fit the remaining weights against data, one at a time.** For each evidence
factor (the ×0.8 regex de-rate, `IP_HOP_WEIGHT`, the absence cap, the notebook
factor) compute the observed precision of findings carrying it and move the
multiplier toward the observed rate — a reliability-diagram fit. Move **one
factor per round** and re-measure, as §9's five-item campaign did; do not touch
the absence cap and the wrapper gate together, because `MLV301` is affected by
both and the attribution would be lost. Track the calibration error in the
baseline the way recall already is. **The public corpus is the veto**, not the
labelled one.

### 6.7 An advisory tier

`ISSUE_RULES.md` §4 places `MLV116` and `MLV120` "in the advisory group" and
marks `MLV120` "off by default" — but no advisory group exists in the
implementation: `core/config.py` knows only `enabled` and `disable`, and the
registry's only graded axes are severity and confidence. Nine candidates in §5
are hygiene or performance smells (C-19 arm 2, C-27, C-32, C-33, C-34, C-36,
parts of C-12 and C-20), and they would land in the same `low` bucket as
`MLV601` "no random seed set anywhere", which is a correctness-adjacent finding
a reader should act on.

Add a `group` field on `@rule` (`"correctness" | "advisory"`), with advisory
rules off unless enabled in `.mlview.toml`. The alternative — giving advisory
rules a sub-0.5 base prior so they land in `speculative` — is cheaper and
dishonest: `DataLoader(num_workers=0)` is a *certainty* about the code and merely
an *opinion* about its cost. Severities stay frozen (a red octagon means the same
thing in every screenshot), so this must be a new orthogonal axis, never a
re-grading. TorchFix's TOR4XX tier is the precedent [69]; dslinter's catalogue
makes the same split, 14 "Code Smell" against 6 "Code Smell Advice" [99].

**Why this is a precision protection, not a feature.** Adding nine low-severity
smells to a panel whose 100 %-precision reputation is the product's core asset
would dilute it — and the dilution is not a precision failure, so **no existing
gate would catch it**.

### 6.8 An optional host-LLM-assisted triage tier

**The proposition.** The analyzer stays exactly as it is: offline, deterministic,
never executing user code. A separate, opt-in tier asks the *host's* model — the
one already running in VS Code or Claude Code — to triage findings MLView has
already computed. It never generates findings, and the core never calls a model.

**Where it would actually pay.** Not on `certain` findings, which do not need
help. On the two places this document has measured a limit:
(a) the 17 `speculative` and 46 `possible` findings, where the question is
"is this region really an inference path?" or "is this `id` column really an
entity key?" — judgements a reader makes in seconds from context MLView cannot
resolve; and (b) the 66 `untagged_dataflow` and 73 `unresolved_callee`
coverage notes, where the question is "what does this unresolved callee return?"
— which is a *knowledge-table* question, and a triage tier that proposed rows
for human review would compound into the offline core rather than bypass it.

**Contract implications, which are the whole difficulty.**

1. **The offline guarantee is a product claim, so the tier must be off by
   default, per-workspace, and visibly labelled.** A finding that passed through
   a model must carry a distinct provenance marker in the document — not a
   confidence adjustment, a *separate field* — so that "MLView holds 100 %
   precision" continues to mean the deterministic analyzer, and the triaged tier
   is measured and reported separately or not at all.
2. **It must never raise confidence, only lower it or annotate.** Allowing a
   model to promote a finding above 0.60 would make the Problems panel's
   contract depend on a non-deterministic component, and the ratchet would stop
   meaning anything. Suppression-only is the sound direction: a triage pass may
   move a finding *down* or attach a note; it may not move one up.
3. **Determinism and the accuracy gate.** `tools/accuracy.py` compares against a
   recorded baseline. A non-deterministic stage cannot be inside that
   comparison. The tier must run strictly *after* the gate reads its numbers,
   and the baseline must record the pre-triage findings.
4. **Data egress.** Triage means sending source to a model. That is a materially
   different privacy posture from "works offline", and it must be a consent
   surface, not a setting buried in a config file — and it must never be
   available in the CI/`--strict` path.
5. **CONTRACTS.** This is a v1.2 change: a new document field, a new rule-result
   provenance value, and an explicit statement that the deterministic core's
   guarantees are unchanged and separately measured.

**Recommendation.** Worth prototyping for (b) — proposing knowledge rows for the
52 measured *"no knowledge table for X"* diagnostics is a high-value, low-risk
use where the output is reviewed by a human and lands in a table, not in a
finding. For (a), do §6.6 first: 43 of the findings a triage tier would be asked
to rescue are already true positives being hidden by a misapplied constant, and
fixing a constant is cheaper and more honest than asking a model.

---

## 7. Evaluation methodology upgrades

### 7.1 The gate cannot currently accept a new rule

Measured (M6): the corpus carries **555 `expected` rows and 2,327 `forbidden`
rows spanning exactly 36 distinct codes** — precisely the 36 shipped rules. (The
referee scores **546** of the 555; nine rows across eight programs are not
counted. One is a duplicate label at the same site, `vision_explain_bad`
`MLV114 report.py:42`; the other eight have no single explanation and are worth
a one-hour audit, because an `expected` row that is silently not scored is a
label nobody is measuring.)
There is not one label, expected or forbidden, for any of the 50 later-tier
codes. Because `tools/accuracy.py` counts an unsuppressed finding satisfying no
label as a false positive, **the first run of any new rule from §5 will fail the
accuracy gate on every program it fires on — including the programs where it is
right.**

The forbidden:expected ratio on shipped rules is **4.2 : 1**. That is the real
shape of the discipline, and it says that a new rule that ships with two
fixtures and no forbidden rows has had its precision *asserted*, not measured.

**The fix is a thirteenth box on the authoring checklist.** `ISSUE_RULES.md` §5
has twelve and none of them is this: *run the rule over the 158-program corpus
with `--no-gate` and adjudicate every finding into expected / acceptable /
forbidden before recording a baseline.* That step is where precision is actually
earned, and its absence is why the cost of a rule is currently under-estimated
by roughly an order of magnitude.

### 7.2 Two-stage guard measurement, before the rule is written

The public-corpus harness is used today as a post-hoc regression gate (260 runs,
260 clean). It is also, unused, the best available estimator of a proposed
rule's false-positive rate: 4,467 parsed files of real code across 37 projects.

**The protocol.** (1) Write a throwaway AST scanner for the **raw** shape the
rule's title describes and count it. (2) Add each proposed guard as a conjunct
and re-count. (3) The ratio is the guard's measured value; the final count is
the upper bound on the firing rate. (4) Read the survivors by hand — a survivor
that is correct code is a guard you have not written yet.

**It changed the design in five measured cases in this document:**

| Candidate | Raw | Guarded | What the guard is |
|---|---:|---:|---|
| C-02 `MLV107` | 91 | **6** | the selection-mechanism conjunct |
| C-17 Keras `from_logits` + `'accuracy'` | 25 | **0** | the binary-vs-categorical split [36] |
| C-27 unsorted listing | 563 | (narrow) | reachability to a sample list |
| `MLV117` stratify (§9.7) | 228 | — | *no guard found* → do not ship |
| a `zip`-truncation rule | 713 | **3** | both arguments must carry `LOADER` |

In three of the five, the documentation alone would have produced a rule that
fails the precision gate on its first run.

**The method's own limitation, stated:** 37 expert repositories under-represent
the beginner mistakes the `MLV1xx`/`MLV2xx` families target. A zero-hit naive
scan (C-05's `require_grad` typo: 0 in 4,467 files) is evidence that the rule
costs nothing on the gate — **not** evidence it is worthless on user code.
Conversely a high-hit scan is strong evidence about what a rule must not do.

### 7.3 Measure against something MLView did not write

Three external, independently labelled sets are available now and need no
mining: **defect4ML** [89] (100 reproducible TF/Keras bugs across 30 Humbatova
fault types, and it already reports comparative tool results), **NeuraLint's**
34-program set [93] (100 % precision / 70.5 % recall — a directly comparable
pair of numbers), and **Yang et al.'s** leakage notebooks [96].

Report external recall as a **separate figure** and never fold it into the
ratchet; the in-house baseline stays the gate. Expect it to be substantially
below 80.4 %. Two of the three sets are Keras/TF-heavy, which is where MLView's
coverage is thinnest (§4.7) — so the number will be informative in the direction
that matters.

### 7.4 Four gaps in the two corpora

**(a) Graph fidelity is measured on the easier half.** 91.9 % is computed over
the **66 of 158 programs** that carry a labelled `graph` block. The 92 unlabelled
programs include every RL program, most infra programs and most `_bad` vision
twins — the domains where the IR is weakest, and where `adv_sac_clean` already
scores 56.0 % and `nlp_instruction_sft` 38.5 %. Label the `_bad` twin of every
already-labelled clean program first, so each new row has a matched pair.

**(b) Twenty candidate shapes have no corpus representation at all.** Measured
(M4): the Keras `validation_split`, tf.data cache-after-shuffle, direct
`.forward()`, tf.data shuffle-after-batch and `F.dropout` shapes all fire in the
public corpus and score **0** in the labelled one. That is exactly how D1
survived: the sklearn-metric-on-`keras.Model.predict` shape occurs in neither
corpus, so a `certain` false positive on documented-correct code was invisible
to a gate reporting 100 % precision.

**(c) The public corpus contains almost no tabular data science.** Five
leakage-family shapes return **exactly zero** across 4,467 files — resampling
before the split, a groupby-target transform, a `pd.merge`, a `drop_last` on an
eval loader, a `zip` over two loaders. These are not rare mistakes in the wild;
they are the canonical applied-science shapes, and Kapoor & Narayanan found them
across 294 papers [95]. They are absent because the 37 pinned repositories are
frameworks, model zoos and tutorial collections. **Consequence:** C-20 and C-01
would ship with their false-positive behaviour measured only against fixtures
the same team wrote. Pin a second tier of applied tabular and time-series
repositories, scored separately so a DL regression is not masked by tabular
volume.

**(d) Notebooks are skipped by default.** `.ipynb` files raise a
`notebook_skipped` diagnostic unless `--include-notebooks` is passed; the corpus
even contains `infra_notebooks_only`, where MLView analyses 0 files by default.
876 notebooks sit in the public corpus. Every large-scale leakage prevalence
number in the literature is measured on notebooks [96][85]. If inclusion becomes
the default, cell order must be treated as source order **with a coverage note
saying so** — Yang et al.'s own stated limitation is that out-of-order and
repeated cell execution is the one thing static notebook analysis cannot see
[96], and an absence rule must never cross a cell boundary without that note.

### 7.5 Make the "no rule exists" channel machine-readable

The corpus encodes "MLView cannot express this" in three incompatible places:
`unsupported` (142 rows), `gaps` (48, vision programs only) and `unruledDefects`
(2, one program). 106 of the 173 real-defect rows carry `wouldBe: null` or a
prose sentence instead of a code. So the single best rule-gap oracle in the
project is half prose and cannot be counted without hand-reading — which is what
§2's M6 had to do.

One schema for all three (`{wouldBe, class, file, line, symbol, defect, why,
twin}` with `class` a controlled vocabulary), plus a
`tools/accuracy.py --unsupported` report that counts by class. Then the new-rule
backlog becomes a measured number that moves with the corpus. Keep
`test_every_labelled_code_is_a_real_rule` working by validating `wouldBe` against
the union of registered **and** §4 codes.

### 7.6 Report what the referee already knows but does not print

Two numbers exist in the run and are not tracked as gates: the **hidden-finding
count** (recovered − visible, currently 43) and the **calibration error** per
bucket. Both are the subject of §6.6 and neither can be managed while it is
printed once and forgotten. Add both to `baseline.json` and to the ratchet.

---

## 8. A proposed sequence

Three sprints. Every item carries an acceptance gate that is a **measurement**,
not a review. Two invariants hold across all of them and are never traded:
**forbidden findings stay at 0** on the 158-program corpus, and the 37-repository
public run stays clean. Where an item can break the second, it says so.

### Sprint A — Repair and leverage

The whole sprint is defects and IR. No new rules ship, and recall moves more
than it would from any five rules in §5.

| # | Item | Gate |
|---|---|---|
| A1 | **D1** — `keras.Model.predict` → `PROBS`/`LOGITS`; audit `Trainer.predict`, `predict_on_batch`, statsmodels rows; framework-aware `HARD_LABEL_PRODUCERS` for `MLV306` (§6.5) | `keras_auc.py` silent **and** `keras_acc.py` fires `MLV305`; both become corpus fixtures; public run unchanged; no `MLV306`/`MLV305` recall regression |
| A2 | **D2** — fix the splitter table; add the 7 missing `model_selection` rows (§6.2 batch 1) | `StratifiedGroupKFold` fixture silent, `GroupShuffleSplit` fixture fires; a unit test asserts each splitter against its documented signature; `MLV106` recall ≥ 50 % and ≥ 0 new FPs |
| A3 | **D3** — split `MLV803` into three arms; delete the `map_location` finding (§6.5) | Public-corpus `MLV803` count drops from 118 and every survivor is arm 1 or an explicit `weights_only=False`; corpus `MLV803` recall ≥ 97.7 % |
| A4 | **IR-1 + IR-2** — subscripts, shape methods, HF output objects (§6.1) | ≥ 12 of the 22 cause-C labels recovered; `MLV305` recall ≥ 60 %; **split tags provably not propagated through a mask** (a dedicated fixture); public run clean |
| A5 | **§6.3(a)+(b)** — widen the evaluation region; judge per model value | ≥ 12 of the 16 cause-A labels recovered; `MLV301` and `MLV302` recall ≥ 85 %; the C-13 carve-out fixture (a teacher forward inside a training step) stays silent |
| A6 | **IR-6** — union identity tags; duck-type `MODEL` | ≥ 4 of the 6 cause-B labels; the 36 `truncated` intersection diagnostics drop; `hydra_research` graph fidelity ≥ 93.8 % and its 4 labels recovered |
| A7 | **§6.6** — scope `WRAPPER_FACTOR` to governed regions | Hidden-finding count drops from 43 to ≤ 15; **forbidden stays 0**; public run clean; calibration error recorded in the baseline |
| A8 | **§7.1** — add box 13 to the authoring checklist; add hidden-count and calibration error to `baseline.json` (§7.6) | Documentation and referee change only |

**Expected at the end of Sprint A:** recall ≈ 86–88 %, visible recall ≈ 84–86 %
(the visible number moves further than the raw one, because A7 recovers findings
that were already computed), precision unchanged at 100 %, and two classes of
false positive that the gate could not see permanently closed.

### Sprint B — Tier-1 coverage

Ten rules, every one measured at zero or near-zero false-positive exposure.
Ship them in the order below, because the first four cost almost nothing and buy
the schedule room for the last two.

| # | Item | Gate |
|---|---|---|
| B1 | **§6.2 batch 1** — `EXPORT`, `SAMPLER_EPOCH`, `RESAMPLE_FIT` rows, **with no rule keys** | Graph fidelity ≥ 91.9 % and ideally higher; findings unchanged (the R2 discipline) |
| B2 | **C-05** `require_grad`, **C-04** shuffle+sampler, **C-06** Dataset dunders | 0 findings on the public corpus for all three (each is measured at 0); each has a `_bad`/`_good` pair; corpus adjudicated |
| B3 | **C-01** `MLV104` resampling before the split | 0 public findings; both corpus programs' `unsupported` rows promoted to `expected` and recovered; the imbalanced-learn `_good.py` stays silent |
| B4 | **C-03** `MLV703` `F.dropout` | ≤ 4 public findings, each adjudicated a true positive; the `if self.training` and non-Module `_good.py` cases stay silent |
| B5 | **C-07** `MLV603` partial seeding + the `is_seeded` split | 4 corpus labels re-classified and recovered; `MLV601` recall unchanged; a pure-sklearn `_good.py` stays silent; never co-fires with `MLV601` |
| B6 | **C-02** `MLV107` held-out steers selection | ≤ 6 public findings; `xgboost/demo/guide-python/sklearn_examples.py:93` adjudicated **true positive** (a new state in the adjudication file, §1.4); both corpus rows promoted; the learning-curve `_good.py` silent |
| B7 | **IR-5** + **C-10** the three `MLV208` sub-variants | `MLV208` recall ≥ 70 %; **bf16 fixture provably silent**; ≤ 1 public finding; the correct multi-optimizer GAN fixture (`vision_gan`) stays silent |
| B8 | **C-08** export in train mode, **C-09** `set_epoch` | ≤ 5 and ≤ 3 public findings respectively, each adjudicated; the `timm/data/loader.py` library-module case silent under workspace scoping; Lightning/accelerate fixtures silent |
| B9 | **C-11** + **C-12** tf.data ordering; **C-14** `MLV403` loss-input normalisation | ≤ 4 and ≤ 12 public findings; the `batch(1)` and val-dataset `_good.py` cases silent; each new loss row has its own fixture pair |
| B10 | **C-13** `MLV213` auxiliary network | Corpus: ≥ 6 of the 11 recorded programs newly covered; **the GAN two-optimizer partition fixture stays silent**; medium severity; public run clean |

**Expected at the end of Sprint B:** 10 new rules, 46 → 56 shipped codes, the
deliver stage populated for the first time, and the largest unrulable-defect
cluster in the corpus addressed.

### Sprint C — Tier-2 coverage and the measurement infrastructure

| # | Item | Gate |
|---|---|---|
| C1 | **§6.7** the advisory tier (`group` on `@rule`, off by default) | Advisory rules absent from the default Problems panel; a config fixture enables them; CONTRACTS entry |
| C2 | **§7.4(c)** a second pinned corpus of applied tabular / time-series repositories | Pinned by commit, scored separately, clean before any tier-2 leakage rule ships |
| C3 | **IR-7** column provenance + attribute-assignment index | Additive; no existing rule changes behaviour; `column_keys = None` provably silences rather than guesses |
| C4 | **C-21**, **C-22**, **C-23** the temporal / target-derived leakage family | Measured on C2 before shipping; each `unsupported` corpus row promoted; the autoregressive-label `_good.py` (a `shift(-1)` target) stays silent |
| C5 | **C-15**–**C-19** the Keras/callback family | C-17 measured at 0 findings on the 25 categorical sites; C-19's `val/loss` separator fixture stays silent; C-18 gated on the ordering signal, never the keyword |
| C6 | **C-20** group leakage (arm A only; arm B advisory, prior 0.55) | Clean on C2; arm B off by default; `GroupKFold` `_good.py` silent |
| C7 | **C-24** detach, **C-25** untransformed test, **C-26** worker seeding, **C-27** unsorted ordering, **C-28** rank-guarded save | Each ≤ 5 public findings; C-27's reachability clause provably takes 563 → single digits |
| C8 | **§7.3** run defect4ML and NeuraLint's set; publish external recall separately | A number exists in `ACCURACY.md`, reported unchanged and not folded into the ratchet |
| C9 | **§7.5** unify the `unsupported`/`gaps`/`unruledDefects` schema; `--unsupported` report | The backlog is a number that moves with the corpus |
| C10 | **§6.4** first mining round: 20 labelled programs from real fix commits, written as equivalents | Provenance URL in each label; no repository source copied; licences recorded |

### Cross-sprint acceptance rules

1. **Never record a baseline where `forbidden > 0` or the public gate is not
   clean.** This is the existing ratchet and nothing here suspends it.
2. **One change per measured round.** The §9 campaign established this; A4, A5
   and A7 in particular must be measured separately, because `MLV301` is
   affected by all three and attribution would otherwise be lost.
3. **Every rule ships with its nearest *measured* false-positive trap as its
   `_good.py`** — not an invented one. This document names the trap for every
   candidate in §5, and in five cases (§7.2) the trap is the reason the rule is
   shippable at all.
4. **`--dataflow local` stays byte-identical** through every IR change, as
   DATAFLOW-IP already established.

---

## 9. Rejected ideas, with the measurement

Negative results, recorded so a later agent does not re-derive them. By raw
match volume these represent roughly **2,300 findings MLView will not have to
suppress later**, which makes this the highest-value-per-line section in the
document.

**9.1 Sonar S6982 — "a model state is loaded and `eval()`/`train()` is not
called" — as stated.** Measured: **339 candidate sites of 426 total
`load_state_dict` calls (~80 %)** across the pinned corpus. Adopting it
unmodified would put 339 findings on repositories the project's own gate calls
clean. A narrowed form (load → forward/export, no mode call, no training loop in
scope) is defensible and is tier 3; the rule *as Sonar states it* is not [72].

**9.2 NeuraLint rule 17 — dropout before batch normalization.** The variance-shift
result is real [106], and the bad ordering has **zero textual occurrences** in
4,467 files. A rule with no instances is not coverage.

**9.3 "Construct the optimizer after `model.to(device)`."** The folk rule comes
from the PyTorch 0.4 docs [11] and was refuted in pytorch/pytorch#7844 [17]:
`Module._apply` mutates `param.data` in place, so parameter identity survives.
The warning is **absent from the current documentation** [10] — I looked for it
specifically. Measured: 30 sites across 6 repositories, 0 of 5 sampled were
defects. `MLV211`'s sketch already excludes `.to(device)`; that exclusion is
correct and should be cited rather than revisited. The genuine `MLV211` shapes
(`DataParallel`, `DDP`, `torch.compile`, reconstruction) do replace parameter
objects and remain worth building.

**9.4 "Frozen parameters still passed to the optimizer."** Not a defect: a
parameter with `requires_grad=False` has `p.grad is None` and every torch
optimizer skips it — neither weight decay nor momentum is applied. Measured 21
sites, 0 of 5 real; one is a *documented tutorial example* whose own comment
explains why it is fine. In the labelled corpus it would produce **9 forbidden
findings**. The real variant is the inverse — `filter(lambda p: p.requires_grad,
…)` captured *before* a later unfreeze — which is a genuine staged-unfreezing bug
and a different rule. Relatedly, **Adam with a non-zero `weight_decay`**
(47 sites, 43 of them in one repository, 0 of 5 real) is a documented, valid API
choice [105] and must not be a rule either.

**9.5 `.item()` / `.cpu()` in the loop, and missing `pin_memory` / `num_workers`.**
709 and 607 raw matches respectively — the two largest counts measured. Worse,
`.item()` is the exact remedy `MLV205` demands ("loss accumulated without
`.item()`/`.detach()`"), so a rule flagging it would put MLView in direct
contradiction with itself. **The derived principle is worth more than the
rejection: MLView must never ship a rule whose fix contradicts another rule's
fix.** The only defensible residue is C-36's narrow, advisory, off-by-default
form.

**9.6 An ordering variant of `MLV207` ("`scheduler.step()` before
`optimizer.step()`").** The docs do warn that the pre-1.1.0 order skips the first
schedule value [10]. Measured: **4 matches, 0 of 4 real.** Three are
`if lr_scheduler is not None and start_epoch > 0: lr_scheduler.step(start_epoch)`
— a resume fast-forward, outside any loop. The fourth is the canonical correct
epoch loop, where `optimizer.step()` lives one call hop down inside `train()`.
Lexical order in the caller is not execution order. Leave `MLV207` as specified
(constructor-resolved cadence, not ordering).

**9.7 `MLV117` (unstratified split) as sketched.** Measured **228 firings across
4,467 files**. `ISSUE_RULES.md` §4 already calls it "the noisiest rule relative
to its value" [110]; this is that judgement as a number. The contrast is
instructive: `MLV602` fires on the *same call sites* for a missing
`random_state` and holds 100 % recall with 0 forbidden hits — because "this split
is not reproducible" is true whenever the keyword is absent, whereas "this split
should have been stratified" is not. If revived, it needs `MLV116`'s positive
imbalance evidence as a **precondition** and a `test_size` below 0.2.

**9.8 `EarlyStopping` with no `monitor=`.** Worthless by construction: Keras
already defaults `monitor="val_loss"` [34], so an absent keyword is correct — and
it was 86 of 106 raw matches. Only the *explicit* non-validation monitor is a
finding (C-19).

**9.9 HF `load_best_model_at_end` strategy consistency.** The constraint is real
and documented [44], and modern `transformers` raises on the violating
combination, so it barely occurs in code that runs. Measured: **1 site in the
entire public corpus, and it is a false positive** —
`optuna-examples/transformers/transformers_simple.py:59` pairs
`eval_strategy='epoch'` with `save_strategy='best'`, which the docs explicitly
exempt. A 1/1 false-positive rate. Encode the constraint as a note on `MLV708`,
not as a rule.

**9.10 Data-quality checks.** Deepchecks' ~15 data-integrity checks [80] and
Great Expectations' 300+ expectations [81] all evaluate against real data at
runtime; Foidl et al.'s 36 data smells are properties of data files [98]. A
static analyzer that never executes code cannot compute them. The only code-
visible proxy worth anything is a dummy sentinel written into `fillna` — one
rule, not a family.

**9.11 Shape and dtype inference.** The dominant categories in the DL fault
taxonomies — wrong tensor shape, unaligned tensors, dimension mismatch, absence
of type checking [86][87] — need a shape lattice. Zhang et al. say so themselves
[88]. MLView's architecture deliberately has none, and 6 of the 107 misses
(cause G) are honestly outside it. Keeping that boundary is what lets the rest
hold 100 % precision.

**9.12 System-level and architectural debt.** Sculley et al.'s undeclared
consumers, correction cascades and hidden feedback loops [97], and Gesi et al.'s
Deep God File and Scattered Use of ML Library [92], are not visible in one
repository or are not defect-level. Only dead experimental code paths
(`MLV903`) and configuration debt (`MLV120`) are in scope, and both are already
catalogued.

**9.13 "Seed set after the `DataLoader`."** A false premise. A `DataLoader`
draws its permutation at `__iter__` time, so a seed set between construction and
the first epoch still governs shuffling. Measured: 44 total matches, of which
**36 are the loader arm and all 5 sampled are benign** — four are accelerate
examples whose own comment reads *"we build the model here so that the seed also
control new weights initialization"*. Only the **splitter** arm (8 matches) is
real, and it is tier 3.

**9.14 Detector count as a coverage metric.** MLScent ships 76 detectors and its
most-fired produces **10,795 instances across 43 projects** [83]. SpecDetect4AI
reports its own two worst rules at F1 0.47 and 0.34 [84]. A detector that fires
ten thousand times is noise, not coverage — and the number of codes in
`ISSUE_RULES.md` §1 is not a measure of anything either.

---

## 10. Open questions for the maintainer

These are decisions this document cannot make, each with what turns on it.

**10.1 Does the 100 %-precision claim survive contact with a defect the gate
could not see?** D1 is a `certain` false positive on documented-correct Keras
code, and neither corpus contains the shape. The number was true; the gate was
blind. Is the right response to (a) fix it quietly and add fixtures, (b) fix it
and restate the claim as "100 % on the measured corpus, with the corpus's known
blind spots enumerated", or (c) treat blind-spot enumeration as a standing
deliverable? §7.4 argues for (c), but it is a product-voice decision, not a
technical one.

**10.2 What is the target — recall, or visible recall?** 43 true positives are
computed and hidden. §6.6 recommends re-targeting `WRAPPER_FACTOR` rather than
moving the 0.60 threshold, on the grounds that the threshold is a product
contract. If the maintainer disagrees and the threshold is negotiable, the
cheapest single accuracy improvement in this document is a one-line change — but
it changes what a Problems-panel entry means, and the ratchet would need to
re-baseline.

**10.3 Is `MLV107` a `high` or a `medium`?** It is the most-cited unbuilt code
in the corpus and the most prevalent leakage class in the literature [96]. But
its consequence — an optimistically biased number — is softer than `MLV101`'s,
and a project with only two splits and no validation set is doing the only thing
available to it. §5 proposes `high` with the selection conjunct mandatory;
`medium` with question-phrasing is defensible.

**10.4 Should `C-02`'s true positive on `xgboost/demo` change the public-corpus
claim?** B6's gate expects a genuine true positive on a pinned repository. The
README currently says "no false positives on 37 pinned public repositories",
which stays true — but the adjudication file has no `true_positive` state, and
the README's counts should be re-derived from a run rather than edited by hand.

**10.5 Should the advisory tier exist before tier-2 rules ship, or after?**
§6.7 argues before, because nine tier-2/3 candidates would otherwise dilute a
panel whose reputation is the product. The cost is a CONTRACTS change and a
config surface in three hosts. Deferring it means shipping those nine as `low`
correctness findings and re-grading later, which the frozen-severity rule makes
awkward.

**10.6 Is a second pinned corpus affordable?** §7.4(c) shows the leakage family
— MLView's flagship — has essentially no false-positive evidence on the current
gate, because the 37 repositories are frameworks. A tabular tier would be
another 1–2 GB and another 200+ runs per round. Without it, C-20 and C-01 ship
on an unmeasured precision claim.

**10.7 What is the policy on knowledge rows for libraries with no rule?**
§6.2 batch 3 would add ~20 identification-only tables to remove 52 measured
diagnostics and lift graph fidelity. That is maintenance surface with no
finding attached. The R2 precedent says it pays (84.5 % → 86.2 % on rows alone),
but it is a recurring cost as those libraries move.

**10.8 Does the host-LLM triage tier belong in the product at all?** §6.8 finds
one use that compounds into the offline core (proposing knowledge rows from
unresolved-callee diagnostics) and one that does not (rescuing speculative
findings, which §6.6 shows is mostly a misapplied constant). The contract
implications — provenance marking, suppression-only, exclusion from the gate and
from CI, and a consent surface for egress — are five separate decisions, and
"works offline" is currently a headline claim.

**10.9 Why does the referee score 546 of 555 `expected` rows?** Nine rows across
eight programs are not counted (§7.1). One is a duplicate; the rest are
unexplained. An `expected` row that is silently not scored is a label nobody is
measuring, and the discrepancy should be resolved before the corpus grows.

**10.10 Who labels the corpus?** §6.4's mining round and §7.4's gaps both add
labels. `ACCURACY.md`'s `unseen` column exists because a rule's author labelling
its own programs makes recall a ceiling rather than a measurement. At 158
programs that discipline is holding; at 250 it needs a written rule about who
may label what.

---

*Measurements in this document were taken on 2026-09-15 against branch
`research` at the tree state recorded in §2. Every number is reproducible with
the commands printed there. No repository file outside
`docs/RESEARCH_COVERAGE_ACCURACY.md` and `docs/research/sources.md` was modified,
and no git operation was performed.*
