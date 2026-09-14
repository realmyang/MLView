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

`analyzer/tests/accuracy/corpus/` holds **92** labelled projects. Each is a
directory with a `labels.json` beside its sources; two of them are label files
alone, pointing at the shipped samples through a `root` key so the corpus never
forks a second copy of the demo.

Fifteen of the 92 are the original set the table below describes — the programs
the rules were written against or re-created from the Sprint-2 audit. The other
77 were added in hardening round 1 (2026-09-14) and are listed by family in
section 3; every one of them is unseen, and most ship as a correct / defective
pair so that a zero-false-positive claim has something to be zero about.

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

## 3 · The numbers on 2026-09-14

Re-recorded in **hardening round 1**. Two things moved at once and they pull in
opposite directions, so they are stated apart before they are stated together.

**The corpus roughly sextupled.** It grew from **15 labelled programs, 78 labels
and 139 hand-drawn graph ops** to **92 programs, 312 labels and 614 ops** — 77
new programs and 188 new source files across five families: 25 vision (DCGAN and
WGAN-GP, VAE, DDPM, SimCLR, detection, U-Net segmentation, 3-D video, ONNX
serving, timm ViT, Keras CNN and transfer, Lightning classification, ImageNet
DDP), 15 infrastructure (DDP, FSDP, DeepSpeed, accelerate, Ignite, fastai, JAX /
Flax, Hydra config trees, the Lightning CLI, a monorepo, a packaged layout,
serving), 13 tabular (Kaggle-shaped, recsys, forecasting, calibration, a feature
store, AutoML search, MLflow, statsmodels + Prophet, custom estimators), 12 NLP
(GPT pre-training, HuggingFace sequence and token classification, seq2seq
summarisation, LoRA / PEFT, sentence embeddings, an RNN tagger, sklearn text
pipelines, serving) and 12 advanced (PPO, DQN, stable-baselines3, GNN,
distillation, MAML, audio, multimodal). Most ship as a **correct / defective
pair**, which is what makes a zero-false-positive claim mean anything. **No
label was deleted and none was weakened**; `git log -p
analyzer/tests/accuracy/corpus` is the record.

**Nothing got worse, and the headline still went down.** Raw recall reads
**73.1% -> 72.4%** and high+medium **64.9% -> 64.5%**, because 77 of the 92
programs are unseen and harder than the fifteen the rules were developed
against. The control is to score the **same fifteen programs** with this build,
which is the only comparison where the denominator is unchanged:

| the original 15 programs | raw recall | visible | high+medium | unseen raw |
|---|---|---|---|---|
| `hardening` ef4fb71 (the previous baseline) | 73.1% | 65.4% | 64.9% | 55.3% |
| this build, `local` | **75.6%** | **68.0%** | **66.7%** | **59.6%** |
| this build, `--dataflow ip` | **82.0%** | **74.4%** | **75.4%** | **70.2%** |

Restricted that way the **previous** baseline passes unchanged — every `perRule`
row and graph fidelity included — so no detection was lost anywhere in the
round; the movement is entirely new, harder, unseen code. Both baselines were
therefore re-recorded with `--allow-regression`, and the reason is written into
`analyzer/tests/accuracy/baseline.json`'s own `note` field rather than only into
a commit body. `scripts/check_docs.py` check 9 holds the headline figures in
this section to that file so the two cannot drift apart.

**Almost every rule is now measured on unseen code.** Under the fifteen-program
corpus sixteen of the 36 rules carried a `*` — every label they had lived in a
program they were tuned against, so their `recall` column was a ceiling. **No
rule carries a `*` today**: all 36 have at least one label in a program nobody
wrote for them, and the `unseen recall` column is a measurement for every row.
That is why nine per-rule ratios moved *down* while the rules themselves did not
change — MLV305 went from one tuned label at 100.0% to six labels at 16.7%, and
the second number is the true one.

```
program                  files found labels    hit   miss     fp  graph
--------------------------------------------------------------------------
adv_advanced_clean           4     0      0      0      0      0   n/l
adv_audio_bad                1    11     11     11      0      0   n/l
adv_audio_clean              1     0      0      0      0      0   n/l
adv_distill_bad              1     3      3      3      0      0   n/l
adv_dqn_bad                  1     7      7      7      0      0   n/l
adv_gnn_bad                  2     4      7      4      3      0   n/l
adv_gnn_clean                2     0      0      0      0      0   n/l
adv_meta_maml_bad            1     4      4      4      0      0   n/l
adv_multimodal_clean         1     0      0      0      0      0   n/l
adv_ppo_bad                  1     4      7      4      3      0   n/l
adv_ppo_clean                1     0      0      0      0      0   n/l
adv_rl_sb3_clean             1     0      0      0      0      0   n/l
amp_accumulation             1     3      7      3      4      0 86.7%
gbm_tabular                  1     3      5      3      2      0 100.0%
hf_no_eval*                  1     1      1      1      0      0   n/l
hf_trainer_finetune          3     6      8      6      2      0 91.7%
hydra_research               4     7     11      7      4      0 81.2%
infra_accelerate             1     0      0      0      0      0   n/l
infra_compile_amp            1     0      0      0      0      0   n/l
infra_ddp_correct            2     0      0      0      0      0   n/l
infra_ddp_sampler_bug        2     2      2      2      0      0   n/l
infra_deepspeed              2     0      0      0      0      0   n/l
infra_fastai                 1     0      0      0      0      0   n/l
infra_fsdp                   1     0      0      0      0      0   n/l
infra_hydra_conf             5     1      2      0      2      0   n/l
infra_ignite                 1     0      0      0      0      0   n/l
infra_jax_flax               1     0      0      0      0      0   n/l
infra_keras_custom_step      3     0      1      0      1      0   n/l
infra_lightning_cli          4     1      1      1      0      0   n/l
infra_monorepo               9     0      0      0      0      0   n/l
infra_pkg_layout            14     2      2      2      0      0   n/l
infra_serving                3     0      0      0      0      0   n/l
keras_se_gate*               3     1      1      1      0      0   n/l
keras_tfdata                 3     4      5      4      1      0 100.0%
keras_uncompiled*            3     2      2      2      0      0   n/l
lightning_manual*            2     3      3      3      0      0   n/l
lightning_tabular            3     4      6      4      2      0 100.0%
nlp_gpt_pretrain             2     8     10      8      2      0 91.7%
nlp_gpt_pretrain_clean       2     0      0      0      0      0 100.0%
nlp_hf_classification        3     9     12      9      3      0 94.1%
nlp_hf_classification_clean     3     0      0      0      0      0 94.7%
nlp_lora_peft                2     2      6      2      4      0   n/l
nlp_rnn_tagger               2     6      6      6      0      0 93.8%
nlp_sentence_embedding       2     4      9      4      5      0   n/l
nlp_seq2seq_summarization     2     7      9      7      2      0 80.0%
nlp_serving                  2     0      0      0      0      0 37.5%
nlp_sklearn_text_leaky       1     5      8      5      3      0 86.7%
nlp_sklearn_text_pipeline     1     0      0      0      0      0 85.7%
nlp_token_classification     2     4      9      4      5      0 71.4%
tabular_automl_search        1     0      3      0      3      0 92.9%
tabular_calibration          1     0      0      0      0      0 86.7%
tabular_cluster_explore      1     0      0      0      0      0 100.0%
tabular_custom_estimators     3     0      0      0      0      0 84.2%
tabular_feature_store        5     0      3      0      3      0 85.0%
tabular_forecast_clean       2     0      0      0      0      0 60.0%
tabular_forecast_shuffled     2     1      3      1      2      0 69.2%
tabular_kaggle_clean         3     0      0      0      0      0 94.7%
tabular_kaggle_leaky         2     5      7      5      2      0 84.6%
tabular_mlflow               1     2      3      2      1      0 100.0%
tabular_recsys_leaky         3     6      7      6      1      0 70.6%
tabular_recsys_mf            3     0      0      0      0      0 75.0%
tabular_statsforecast        1     0      0      0      0      0 76.9%
timeseries_split             2     1      5      1      4      0 91.7%
timeseries_split_clean       1     0      0      0      0      0 83.3%
torch_mechanics*             3     9      9      9      0      0   n/l
vision_ddpm                  2     0      0      0      0      0   n/l
vision_ddpm_bad              2     5      7      5      2      0   n/l
vision_detector              4     0      0      0      0      0   n/l
vision_detector_bad          4    10     11     10      1      0   n/l
vision_gan                   3     0      0      0      0      0 67.6%
vision_gan_bad               3     5      9      5      4      0   n/l
vision_imagenet_ddp          5     0      0      0      0      0 72.7%
vision_imagenet_ddp_bad      5     7     12      7      5      0   n/l
vision_keras_cnn             2     0      0      0      0      0   n/l
vision_keras_cnn_bad         2     2      4      2      2      0   n/l
vision_keras_transfer        3     0      0      0      0      0 87.0%
vision_lightning_cls         2     0      0      0      0      0   n/l
vision_lightning_cls_bad     2     8      7      7      0      0   n/l
vision_onnx_service          3     0      0      0      0      0   n/l
vision_onnx_service_bad      3     3      3      3      0      0   n/l
vision_pipeline*             5    15     15     15      0      0 85.7%
vision_pipeline_clean*       5     0      0      0      0      0 100.0%
vision_simclr                2     0      0      0      0      0   n/l
vision_simclr_bad            2     5      7      5      2      0   n/l
vision_unet_seg              3     0      0      0      0      0   n/l
vision_unet_seg_bad          3     8      9      8      1      0   n/l
vision_vae                   1     0      0      0      0      0   n/l
vision_vae_bad               1     4      7      4      3      0   n/l
vision_video3d               2     0      0      0      0      0   n/l
vision_video3d_bad           2     7      8      7      1      0   n/l
vision_vit_timm              2     0      0      0      0      0 85.0%
vision_vit_timm_bad          2     7      8      7      1      0   n/l
--------------------------------------------------------------------------
* tuned: the rules were developed against this project; excluded from the
  unseen headline below.
```

```
rule       labels  found  visible   fp  precision   recall     f1 unseen recall
--------------------------------------------------------------------------------
MLV101         23      8        8    0     100.0%    34.8%   0.52         31.8%
MLV102          5      4        4    0     100.0%    80.0%   0.89         80.0%
MLV103          7      2        2    0     100.0%    28.6%   0.44         16.7%
MLV106          2      1        1    0     100.0%    50.0%   0.67          0.0%
MLV110         13     12       12    0     100.0%    92.3%   0.96         91.7%
MLV111         12     12       12    0     100.0%   100.0%   1.00        100.0%
MLV112         10     10       10    0     100.0%   100.0%   1.00        100.0%
MLV114          7      3        3    0     100.0%    42.9%   0.60         33.3%
MLV121          3      3        3    0     100.0%   100.0%   1.00        100.0%
MLV201         12      9        8    0     100.0%    75.0%   0.86         72.7%
MLV202          2      1        1    0     100.0%    50.0%   0.67         50.0%
MLV203          3      2        2    0     100.0%    66.7%   0.80         66.7%
MLV204          1      1        1    0     100.0%   100.0%   1.00        100.0%
MLV205         18     10       10    0     100.0%    55.6%   0.71         52.9%
MLV207          5      4        4    0     100.0%    80.0%   0.89         75.0%
MLV208          2      1        1    0     100.0%    50.0%   0.67          0.0%
MLV209          3      3        3    0     100.0%   100.0%   1.00        100.0%
MLV301         26     16        9    0     100.0%    61.5%   0.76         60.0%
MLV302         24     16       14    0     100.0%    66.7%   0.80         65.2%
MLV305          6      1        1    0     100.0%    16.7%   0.29          0.0%
MLV306          3      2        2    0     100.0%    66.7%   0.80         50.0%
MLV401         11      6        6    0     100.0%    54.5%   0.71         50.0%
MLV402          7      2        2    0     100.0%    28.6%   0.44         28.6%
MLV501         11      6        4    0     100.0%    54.5%   0.71         50.0%
MLV502          5      5        5    0     100.0%   100.0%   1.00        100.0%
MLV601         26     23       17    0     100.0%    88.5%   0.94         88.0%
MLV602         19     19       19    0     100.0%   100.0%   1.00        100.0%
MLV701          4      4        4    0     100.0%   100.0%   1.00        100.0%
MLV702          6      6        6    0     100.0%   100.0%   1.00        100.0%
MLV705          2      1        1    0     100.0%    50.0%   0.67          0.0%
MLV706          2      2        2    0     100.0%   100.0%   1.00        100.0%
MLV707          2      2        2    0     100.0%   100.0%   1.00        100.0%
MLV708          3      3        3    0     100.0%   100.0%   1.00        100.0%
MLV709          3      2        2    0     100.0%    66.7%   0.80         66.7%
MLV711          3      3        3    0     100.0%   100.0%   1.00        100.0%
MLV803         21     21       21    0     100.0%   100.0%   1.00        100.0%
--------------------------------------------------------------------------------
visible = confidence >= 0.60, the VS Code Problems panel default.
* every label for this rule lives in a program the rule was developed
  against, so its recall column is a ceiling and not a measurement: the
  unseen column is what the rule is known to find on code nobody tuned it
  on, and `-` there means nothing unseen has been labelled for it yet.
```

```
overall   labels 312   recall  72.4%   visible  66.7%   high+medium  64.5%   precision 100.0%
unseen    labels 281   recall  69.4%   visible  63.0%   high+medium  60.2%   precision 100.0%
```

Two columns exist because the report used to overstate itself. **`n/l`** in the
graph column is a program with no hand-drawn `graph` block in its `labels.json`:
nobody drew a diagram for it, so nothing was measured — it used to print
`100.0%`, four perfect scores off no evidence at all. A **`*` on a program**
means the rules were developed against it, so it is excluded from the unseen
headline; six programs carry it and no rule does.

**Precision is 100%.** Zero forbidden findings, zero unlabelled findings, on 92
projects and 312 labels, in **both** dataflow modes. That is the claim the
product rests on, it is the one number the gate refuses to let move, and it is
now backed by four times the evidence it had a week ago. Round 1 started with it
broken: on this corpus `hardening` at `ef4fb71` measured precision 97.6% with
**5 forbidden findings**, all five of them high-severity claims about correct
code.

**Recall is the weakness, and it has three honest readings.** On the 86 unseen
programs:

| Reading | Number | What it means |
|---|---|---|
| raw recall | **69.4%** | 195 of 281 planted defects produced a finding |
| visible recall | **63.0%** | …of which 177 clear `mlview.minConfidence` 0.6, so the rest never reach the VS Code Problems panel |
| high+medium recall | **60.2%** | 124 of 206 defects that are not reproducibility hygiene |

All three are **up** on the unseen half, and substantially: 55.3% -> 69.4% raw,
42.5% -> 63.0% visible, 37.5% -> 60.2% high+medium. The unseen set is now 86
programs rather than eight, so this is the first reading in the project's history
that is a measurement of unseen recall rather than an anecdote about it.

**Reconciling with the audit's ~26%.** The Sprint-2 audit measured ~26% over
four hand-written projects. The closest reading here is **60.2%** — the
high-and-medium-severity number on unseen code. The gap is real and is not
argued away: these are re-creations of the auditors' probes rather than the same
files, and this corpus labels the reproducibility pair (MLV601, MLV602) that
fires on essentially every program, which lifts the raw figure. Quote the
high+medium number when comparing to the audit, and quote all three when
reporting progress.

**Graph fidelity: 522 of 614 hand-labelled ops, 85.0%.** The score reads lower
than the 127 of 139 (91.4%) recorded on 2026-09-10 for the same reason recall
does: 475 of the 614 ops are new, hand-drawn on code nobody tuned the builder
against. 41 of the 92 programs carry a `graph` block; the other 51 carry none
and contribute nothing to the total, which is the distinction the `n/l` row
exists to keep. The 41 that do:

```
program                       ops    recovered         score      edges
----------------------------------------------------------------------
amp_accumulation               15           13         86.7%      30/16
gbm_tabular                     9            9        100.0%       13/9
hf_trainer_finetune            12           11         91.7%      23/12
hydra_research                 16           13         81.2%      49/20
keras_tfdata                   15           15        100.0%      32/14
lightning_tabular              13           13        100.0%      35/12
nlp_gpt_pretrain               24           22         91.7%      42/42
nlp_gpt_pretrain_clean         23           23        100.0%      46/46
nlp_hf_classification          17           16         94.1%      22/20
nlp_hf_classification_clean       19           18         94.7%      26/24
nlp_rnn_tagger                 16           15         93.8%      37/37
nlp_seq2seq_summarization       15           12         80.0%      21/18
nlp_serving                     8            3         37.5%      14/14
nlp_sklearn_text_leaky         15           13         86.7%      24/24
nlp_sklearn_text_pipeline       14           12         85.7%      17/17
nlp_token_classification       14           10         71.4%      28/28
tabular_automl_search          14           13         92.9%      20/20
tabular_calibration            15           13         86.7%      35/30
tabular_cluster_explore        15           15        100.0%      25/23
tabular_custom_estimators       19           16         84.2%      22/22
tabular_feature_store          20           17         85.0%      21/21
tabular_forecast_clean         15            9         60.0%      28/28
tabular_forecast_shuffled       13            9         69.2%      28/28
tabular_kaggle_clean           19           18         94.7%      40/40
tabular_kaggle_leaky           13           11         84.6%      37/37
tabular_mlflow                 15           15        100.0%      26/25
tabular_recsys_leaky           17           12         70.6%      35/35
tabular_recsys_mf              20           15         75.0%      51/51
tabular_statsforecast          13           10         76.9%      19/16
timeseries_split               12           11         91.7%      22/14
timeseries_split_clean          6            5         83.3%        7/6
vision_gan                     37           25         67.6%    105/105
vision_imagenet_ddp            22           16         72.7%    128/128
vision_keras_transfer          23           20         87.0%      55/55
vision_pipeline                28           24         85.7%      51/45
vision_pipeline_clean          13           13        100.0%      55/45
vision_vit_timm                20           17         85.0%      64/48
----------------------------------------------------------------------
TOTAL                         614          522         85.0%
```

**The 92 ops still missing.** `python tools/accuracy.py --verbose` prints each
one by file and line; grouped by hand from that output they are four families,
and the first is more than twice the size of any other:

| Family | n | What it looks like |
|---|---|---|
| a call through an object or class this workspace defines | 42 | `model(images)`, `criterion(...)`, `SmallCNN()`, `Critic()`, `netD(real_images)`, `bpr_loss`, `WinsorizingTransformer`, `build_from_cfg` |
| a framework method the knowledge tables still do not carry | 32 | pandas `shift` / `rolling.mean` / `sort_values` / `fillna`, HuggingFace `evaluate.load` and `rouge.compute`, Keras `model.compile` / `evaluate` / `export`, `fitted.forecast` |
| an sklearn estimator method on a receiver the analyzer cannot type | 10 | `predict_proba`, `decision_function`, `best.fit`, `fit_resample` |
| a value that reached the line as a function parameter | 8 | `scaler.step(optimizer)` and `scheduler.step()` inside an `engine.py` that takes them as arguments (vision-02), `loss.backward()` on a loss a helper returned |

That list is generated, never asserted, so it is a worklist rather than a claim.
The first family is the single biggest unbought recall on the board and has been
since ANA-1; the fourth is the interprocedural hole round 1 measured and did not
close.

**Calibration.**

```
bucket              n     tp     fp      mean conf  observed prec    error
--------------------------------------------------------------------------
certain           133    133      0          0.935         100.0%    0.065
likely             71     71      0          0.834         100.0%    0.166
possible            9      9      0          0.590         100.0%    0.410
speculative        13     13      0          0.338         100.0%    0.662
--------------------------------------------------------------------------
Reported, not gated: at this corpus size a bucket can hold two findings,
so a single label flips its observed precision by half.
```

The confidence model is **under**-confident, not over-confident, and severely so
at the bottom: 13 findings landed in `speculative` at a mean confidence of 0.34
and every one was a genuine planted defect, and 9 more in `possible` at 0.59.
Most are absence findings under `WRAPPER_FACTOR` 0.4. That single multiplier is
what keeps 22 true findings at or below `possible`, and it is the calibration
finding this table exists to surface. The `certain` bucket now holds **133**
findings at 100% observed precision, against 24 a week ago.

The calibration table is **reported, not gated**: at this corpus size a bucket
can still hold nine findings, so one label flips its observed precision by a
ninth. It becomes gateable when the corpus is several times larger again.

### The history this section replaced

The figures above supersede three earlier recordings, kept here as a record
rather than as a claim, because a number that moved for a stated reason is worth
more than a number that was quietly overwritten:

* **2026-09-09, ten programs.** ANA-12 day one.
* **2026-09-09, fourteen programs.** The ANA-7 / ANA-8 / ANA-9 rule tiers
  (`docs/CONTRACTS.md` §11.26) added sixteen rules; precision stayed 100% and
  every gated recall number moved up.
* **2026-09-10, fifteen programs, 78 labels.** ANA-10's in-Python config
  resolution (§11.45) — module-level dict literals, dataclass field defaults,
  `argparse` `default=` and the chains rooted at them — moved raw recall
  71.8% -> 73.1%, visible 64.1% -> 65.4%, high+medium 63.2% -> 64.9%, unseen
  53.2% -> 55.3%, and graph fidelity 126 -> 127 of 139 (91.4%), measured A/B with
  `ir.bindings._resolve_config` stubbed to a no-op. The larger effect was one no
  table can show, because a table only counts findings that *should* exist: on
  `DataLoader(ds, shuffle=CFG["shuffle"])` with `CFG["shuffle"] = True`, MLV110
  used to report *"shuffle=unset (defaults to False)"* at `likely` — a false
  statement about a correct program. H5's structured fixes (§11.42) moved nothing
  and could not: they add one optional `Issue.fix` field to findings that already
  existed and touch no rule gate, no evidence and no confidence.

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

## 6 · `--dataflow ip`, measured separately

DATAFLOW-IP (`docs/CONTRACTS.md` 11.36) adds a second analysis, not a second
opinion about the first. `--dataflow local` is the default and is the analysis
every number above describes; `--dataflow ip` additionally carries value tags
across the object boundary through constructor, return and method-argument
summaries. The two are scored against **two baselines**, because one number
cannot gate two analyses:

```
python tools/accuracy.py                  # local, gates baseline.json
python tools/accuracy.py --dataflow ip    # ip, gates baseline.ip.json
```

`analyzer/tests/accuracy/baseline.ip.json` has the same shape and the same two
tolerances as its local twin — **zero `forbidden` findings ever, recall may only
ratchet up** — and carries a `dataflow` field so a file can never be read as
the other mode's floor. `analyzer/tests/core/test_dataflow_ip.py` asserts both
tolerances inside `pytest analyzer/tests`, alongside the mode's own fixtures.

### The two modes on the 92-program corpus, 2026-09-14

| mode | recall | visible | high+medium | unseen recall | precision | forbidden | unlabelled |
|---|---|---|---|---|---|---|---|
| `local` | 72.4% | 66.7% | 64.5% | 69.4% | **100%** | 0 | 0 |
| `ip` | **76.3%** | **69.9%** | **69.7%** | **73.7%** | **100%** | 0 | 0 |

Graph fidelity is 85.0% in `local` and 85.2% in `ip`: the mode buys exactly one
op, `nlp_token_classification` 0.7143 -> 0.7857, and nothing else moves. `ip` recovers
**twelve** labels `local` misses and, on one program, still loses one it finds —
`mlflow`'s MNIST autolog example (vision-08) — so `local` is not yet a subset of
`ip`. That is stated here rather than averaged away; it is the mode's one known
honesty gap and it is tracked as open in
`analyzer/tests/public_corpus/adjudication.json`.

### The two modes on the same 15 programs, 2026-09-10

| mode | recall | visible | high+medium | unseen recall | precision | forbidden | unlabelled |
|---|---|---|---|---|---|---|---|
| `local` | 73.1% | 65.4% | 64.9% | 55.3% | **100%** | 0 | 0 |
| `ip` | **79.5%** | **71.8%** | **73.7%** | **66.0%** | **100%** | 0 | 0 |

Graph fidelity is 91.4% in both. Every number in the `local` row is the one
section 3 records, unmoved to four decimal places: the mode is additive by
construction, and `AnalyzeOptions(paths=...)` with no `dataflow` is byte-for-byte
`dataflow="local"`.

The recall the mode buys is **five expected labels**, and two of them are the
high-severity leaks the roadmap named as the whole reason to fund the work: the
Lightning `DataModule` fitting a `StandardScaler` on the whole feature matrix
before `random_split` (`lightning_tabular/datamodule.py:27`), and the same shape
in a research script that scales a whole series before a chronological cut. Both
now fire with related locations at the construction site and the split site, and
neither fires at `certain` — see below.

### Why an `ip` finding is never `certain`

Each hop multiplies the confidence product by an explicit interprocedural
evidence weight (`IP_HOP_WEIGHT`, 0.8), contributed as one `cross_file` evidence
entry whose detail names the hop chain in words. For MLV101's 0.95 prior that is
0.760 after one hop, 0.608 after two and 0.486 after three — so a cross-object
finding lands at `likely` or `possible`, and `certain` (>= 0.9) is arithmetically
out of reach. The calibration table above therefore reads differently in `ip`:
the `likely` bucket grows from 16 findings to 21, and its observed precision
stays 100%.

### What the `ip` numbers do not say

* **The corpus is the same corpus.** It was labelled for `local`, so `ip` is
  measured on defects nobody planted for it. That is the right direction for a
  precision claim and the wrong one for a recall claim: the five labels `ip`
  newly recovers are a floor on what the mode adds, not an estimate of it.
* **Precision at 100% is 61 findings, not a proof.** The mode's whole risk is a
  high-severity false positive, and the corpus can only report the ones it has
  labels for. The three negative fixtures under `analyzer/tests/fixtures/dataflow`
  — a helper that legitimately receives already-split training rows, a helper
  called from two sites with different tag sets, and a parameter merely named
  `X` — are the shapes the mode is most likely to get wrong, and they are
  asserted at the IR level, not only at the finding level.
* **Only MLV101 and MLV102 consume the hop chain.** Every other rule reads the
  widened tags without naming a hop in its evidence or paying its weight. That
  is where most of the recall difference above comes from, and 11.36's gate G6
  is written over the whole document so a rule that starts making cross-object
  claims cannot quietly skip the de-rating.
* **A chain past three hops is reported, not scored.** It emits a `truncated`
  diagnostic and no finding, which is a miss the recall column counts and a
  blindness the document names — the distinction this whole file exists to keep.

---

## 7 · Hardening round 1, analyzer (2026-09-14)

Three things happened at once and the numbers below only make sense if they are
kept apart.

**(a) The corpus roughly sextupled.** Other testers added **77** labelled
programs (188 source files) — vision, NLP, tabular, advanced (RL / GNN /
distillation / meta-learning) and infrastructure (DDP, FSDP, DeepSpeed,
accelerate, Ignite, fastai, Hydra, serving, notebooks). Counted three ways:
`expected` labels **78 → 312**, `forbidden` labels — the ones that assert
MLView must stay *silent* — **125 → 1229**, and hand-drawn graph ops
**139 → 614**. Every per-rule ratio in `analyzer/tests/accuracy/baseline.json`
is therefore against a different denominator, so both baselines were re-recorded
by the integrator with `--allow-regression` and the reason written into each
file's own `note`. Section 3 carries the control that makes the re-record
honest: over the original fifteen programs alone, this build beats the baseline
it replaced on every gated number.

**(b) The tree was red when round 1 started.** On the grown corpus, `hardening`
at `ef4fb71` measured **precision 97.6%** with **5 forbidden findings**, and
`python -m pytest analyzer/tests` reported **17 failures** — four of them from a
contract violation (duplicate `Issue.id`s) that three shipped corpus programs
produced unmutated.

**(c) 47 confirmed analyzer findings were fixed** — the 45 the round's testers
confirmed, plus PUB-14 and PUB-15, which the public-corpus gate found at
integration *on the code the other fixes produced*. Both were high-severity
`certain` claims about correct code, both are recorded in `docs/CONTRACTS.md`
§11.56, and neither moved a single labelled number: the table below was measured
before them and is unchanged after them to four decimal places. What the round
moved, measured on the
**same** corpus before and after, so the two columns are comparable to each
other and to nothing else:

| | `hardening` ef4fb71 | after round 1 |
|---|---|---|
| local · precision | **97.6%** | **100.0%** |
| local · forbidden findings | **5** | **0** |
| local · recall | 64.7% | **72.4%** |
| local · visible recall (≥ 0.60) | 59.3% | **66.7%** |
| local · high+medium recall | 56.7% | **64.5%** |
| `ip` · precision | 97.6% | **100.0%** |
| `ip` · recall | 68.9% | **76.3%** |
| graph fidelity | 79.8% | **85.0%** |
| `pytest analyzer/tests` | 17 failed | **0 failed** (the 8 stale-baseline ratchets of (a) cleared when the integrator re-recorded) |

**The public corpus is the harder measurement**, because nothing there is
labelled for MLView. 24 pinned repositories, 180 runs (90 targets in `local` and
`ip`), **180 clean** in 43 s against a 60 s budget, and `python
tools/public_corpus.py check` reports **ten adjudicated false positives GONE** —
every one that round 1 targeted, and the two the gate itself found:

| Repository | Code | Site | Finding |
|---|---|---|---|
| yolov5 | MLV402 | `utils/loss.py` `self.loss_fcn` | PUB-01 |
| scikit-learn | MLV101 | `examples/model_selection/plot_grid_search_stats.py` `search.fit` | PUB-02 |
| scikit-learn | MLV101 | `examples/release_highlights/plot_release_highlights_0_23_0.py` ×2 | PUB-03 |
| PythonDataScienceHandbook | MLV101 | `05.02-Introducing-Scikit-Learn.ipynb` `model.fit` | PUB-03 |
| keras-io | MLV101 | `examples/timeseries/eeg_signal_classification.py` `le.fit` | PUB-04 |
| vit-pytorch | MLV301 | `tests/test_vit.py` | PUB-05 |
| stable-baselines3 | MLV301 | `tests/test_utils.py` | PUB-05 |
| PythonDataScienceHandbook | MLV102 | `05.03-Hyperparameters-and-Model-Validation.ipynb` cell 16 | PUB-14 |
| scikit-learn | MLV101 | `examples/release_highlights/plot_release_highlights_0_24_0.py` `sfs.fit` | PUB-15 |

Their `state` in `analyzer/tests/public_corpus/adjudication.json` is `fixed`, so
a return is now blocking. High-severity findings across the whole corpus fall
from **37 to 34**. One adjudicated false positive stays **open**: `ip`
drops an MLV110 that `local` reports on `mlflow`'s MNIST autolog example
(vision-08). The mode is documented as a widening of `local`, and `local ⊆ ip`
is not yet true; that is a known gap, not a fixed one.

### What the recall number still does not say

The eleven percentage points recall did not move are the interprocedural cases
the round did not reach, and they are named rather than averaged away: a model,
criterion and optimizer arriving as parameters still cost a training step its
forward, loss and backward nodes (vision-02); `--dataflow ip` still reports a
strict subset of `local` on two programs (vision-08); MLV301 still judges an
architecture from one arbitrary call site when several disagree (vision-09); the
`--max-nodes` rollup is still not stage-aware, so the config lane still takes a
median 49% of the budget on a large real repository (PUB-13); and a
workspace-internal `from x import *` still leaves the objective stage reading as
absent (ROB-09). Each is a measured hole with a repro, and each is a hole this
document would rather name than round off.
