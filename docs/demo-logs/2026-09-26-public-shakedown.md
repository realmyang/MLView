# Public shakedown (Campaign 3): 2026-09-26

> Dated evaluation record. Model reviewers provisionally reviewed artifacts written by models. It is not human review and not ground truth. It is not the held-out pilot and does not count toward it, and it does not measure accuracy. In the first run each host ran once per repository; in the confirmation each case ran once, and one case was re-run after a fix.

## Purpose

Campaign 3 ran the shipped MLView 0.3.0 skill (`main` at `00e5d45`) on 12 public ML repositories outside the held-out pilot, once per host. The goal was to find product problems before the pilot's run policy and candidate are frozen. The runs used the pilot's proposed skill prompt, but not its frozen references, scoring or operator procedure, so nothing here counts toward the pilot.

After local fixes, a confirmation run repeated ten of the 36 cases with the fixed skill, on the same evening and with the same prompt, harness and budget. This record covers both runs.

## What ran

### Hosts

| Host | Model and reasoning (as run) | Invocation | Host version |
|---|---|---|---|
| Claude Code | Fable 5.1 (`claude-fable-5-1`), extra-high effort | `/mlview` | 2.1.283 |
| Codex | gpt-6-luna, ultra reasoning | `$mlview` | Codex CLI 0.155.0-alpha.16.3 (`exec`) |
| GitHub Copilot | Auto. Host events show gpt-6-luna in 11 first-run runs and gpt-5.6-luna in the whisper run; gpt-6-luna in all 4 confirmation runs | "Use the mlview skill." | Copilot CLI 1.0.88 |

- **Prompt.** The proposed skill prompt in [run-policy.md](../../evals/workflow/decisions/run-policy.md), which is still pending. Each repository's task prompt and selected scenario were filled in, with `shakedown.mlview.json` as the artifact path. The prompt did not state a time budget. The confirmation used byte-identical prompts.
- **Budget.** 40 minutes of wall-clock time per run, one attempt, no retries. A harness drove each host non-interactively. This is not the pilot's operator-driven procedure in VS Code.
- **Workspace.** A copy of the pinned source without Git metadata, plus the installed skill. Hosts were told to read the source without importing or executing it. The reviewers did not execute target code either.
- **Skill versions.** First run: 0.3.0 (`00e5d45`). Confirmation: the fixed skill as committed at `590c97d`. Claude Code yolov5 re-run: `c37a275`. The last change, `577a381`, has not run on a live host.

### Repositories

| Repository | Pinned commit | License | Selected scenario |
|---|---|---|---|
| openai/CLIP | `d05afc436d78f1c48dc0dbf8e5980a9d471f35f6` | MIT License | Zero-shot ImageNet evaluation in `notebooks/Prompt_Engineering_for_ImageNet.ipynb`, through the workspace `clip/` package |
| lucidrains/denoising-diffusion-pytorch | `7755321814cb53d756f418fbac06784ce87ba9c6` | MIT License | The README `Trainer` example: image-folder DDPM training with EMA, DDIM sampling and FID |
| lucidrains/vit-pytorch | `d01bbb31ec889a338f6048c273dcf2af1a097d30` | MIT License | `examples/cats_and_dogs.ipynb` with `vit_pytorch/efficient.py` wrapping an external Linformer |
| facebookresearch/detr | `29901c51d7fe8712168b8d0d64351170bc0f83e0` | Apache License | Distributed COCO training (`main.py`, `engine.py`) with the README command plus an output directory |
| facebookresearch/dino | `7c446df5b9f45747937fb0d72314eb9f7b66930a` | Apache License | `main_dino.py` pretraining with the README "Vanilla DINO training" command and its defaults |
| openai/whisper | `86098128c0b4f24f0e2aa2994de830614b474227` | MIT License | CLI transcription with defaults (`whisper/transcribe.py`) |
| ultralytics/yolov5 | `35b48237aef6d71ca9de2c5dea345d7536eb7fa7` | GNU Affero General Public License | `train.py` on `data/coco128.yaml` from pretrained weights |
| huggingface/pytorch-image-models | `43d74d69291a9abd59a9ba82fac55ec5a106ae58` | Apache License | `train.py`: ResNet-50 with mixup, label smoothing and EMA |
| Lightning-AI/pytorch-lightning | `bc858a3455415e67b0820bb20e07286c7a46a079` | Apache License | `examples/pytorch/domain_templates/computer_vision_fine_tuning.py` fit, with LightningCLI and staged unfreezing |
| huggingface/trl | `a8bc1816152facaf5441983195c40ffae27f2081` | Apache License | `trl/scripts/dpo.py`: full DPO training |
| pytorch/torchtune | `bd2a0fc7c31430972728494fa01aaeeb0ebf1ba1` | BSD 3-Clause License | `recipes/lora_finetune_single_device.py` with the Llama 3.2 1B LoRA config |
| dmlc/xgboost | `6c3fde7aefa6abee7458f2ba23ac291a31b88204` | Apache License | `demo/guide-python/custom_rmsle.py`: native versus custom objective and metric |

## How the artifacts were reviewed

- One model reviewer per repository compared all three first-run artifacts with the pristine source. In the confirmation, one model reviewer per published artifact compared it with the source and with the first-run artifact and review, so those reviewers were not blind to the first run.
- Before the runs, a model wrote a review checklist for each repository. Hosts never saw it. Reviewers checked every item against the source before using it, and found errors in several checklists (see Limitations).
- Checklist coverage counts an item as 1 when covered, ½ when partial, and 0 when missing or wrong.
- Reviewers chose which claims to check. The samples are not random, so the supported counts are not precision estimates.
- Each finding was graded valid, trivial (accurate but not actionable), plausible-unverified, or intended behaviour.
- A friction analysis read the first-run transcripts. To reproduce failed validations, it rebuilt drafts from the edit history and re-ran the helper on scratch copies. The confirmation transcripts were parsed for helper calls, refusals and repair rounds.
- A viewer check opened all 32 first-run artifacts through the extension's own open path and renderer, and five of them in a live Extension Development Host. The confirmation artifacts were not opened in the viewer.

## First run results

### Publication: 32 of 36

32 runs published an artifact that revalidated. Four did not:

| Run | Outcome | Time |
|---|---|---|
| Codex, trl | Timed out; its last draft never passed validation | 40.1 min |
| Codex, torchtune | Timed out; the draft was written at 37.9 min and never validated | 40.1 min |
| Copilot, vit-pytorch | Stopped at the two-repair limit with one quote error left | 2.8 min |
| Copilot, detr | Stopped at the two-repair limit with one quote error left, and deleted its draft | 4.6 min |

### Quality by host

| Host | Published | Ratings | Mean checklist coverage | Claims chk/sup/unsup/wrong | Findings V/T/P/I | Failed validations | Median wall min |
|---|---|---|---|---|---|---|---|
| Claude Code | 12/12 | strong 12 | 99.7% | 321/303/14/4 | 37/10/3/0 | 1 | 20.2 |
| Codex | 10/12 | strong 4, adequate 6, failed 2 | 86% | 200/190/8/2 | 6/3/1/1 | 8 | 19.9 |
| Copilot | 10/12 | adequate 9, weak 1, failed 2 | 82% | 191/175/9/7 | 5/3/0/1 | 27 | 6.5 |

Coverage is averaged over published runs. Findings V/T/P/I means valid / trivial / plausible-unverified / intended behaviour, counted over published artifacts only. The median wall time covers all 12 runs, including those that published nothing.

### By repository

| Repository | Claude Code | Codex | Copilot |
|---|---|---|---|
| CLIP | strong, 100%, 22/22/0/0, 14.0 min | adequate, 75%, 16/16/0/0, 14.0 min | adequate, 64%, 15/13/2/0, 5.1 min |
| denoising-diffusion-pytorch | strong, 100%, 24/23/0/1, 13.3 min | adequate, 89%, 18/16/1/1, 14.4 min | adequate, 86%, 20/18/0/2, 4.1 min |
| vit-pytorch | strong, 100%, 23/20/3/0, 11.1 min | adequate, 89%, 18/16/2/0, 14.3 min | failed (repair limit), 2.8 min |
| detr | strong, 100%, 22/19/2/1, 15.4 min | strong, 92%, 20/19/1/0, 17.2 min | failed (repair limit), 4.6 min |
| dino | strong, 100%, 30/28/2/0, 13.1 min | strong, 86%, 27/26/0/1, 25.2 min | adequate, 79%, 22/21/0/1, 8.2 min |
| whisper | strong, 100%, 25/24/0/1, 21.8 min | adequate, 68%, 16/14/2/0, 24.1 min | weak, 75%, 18/16/1/1, 2.9 min |
| yolov5 | strong, 100%, 31/27/3/1, 27.2 min | adequate, 89%, 22/22/0/0, 19.2 min | adequate, 86%, 20/18/1/1, 11.6 min |
| pytorch-image-models | strong, 100%, 30/30/0/0, 24.3 min | strong, 93%, 23/23/0/0, 20.7 min | adequate, 89%, 24/21/1/2, 10.2 min |
| pytorch-lightning | strong, 100%, 26/24/2/0, 21.1 min | strong, 96%, 18/18/0/0, 31.5 min | adequate, 96%, 17/16/1/0, 8.0 min |
| trl | strong, 96%, 28/27/1/0, 22.8 min | failed (timeout), 40.1 min | adequate, 82%, 18/17/1/0, 8.2 min |
| torchtune | strong, 100%, 30/29/1/0, 20.0 min | failed (timeout), 40.1 min | adequate, 82%, 16/15/1/0, 8.6 min |
| xgboost | strong, 100%, 30/30/0/0, 20.4 min | adequate, 79%, 22/20/2/0, 11.3 min | adequate, 82%, 21/20/1/0, 2.8 min |

Each cell gives: rating, checklist coverage, claims checked/supported/unsupported/wrong, and wall time.

Artifact size:
- Claude Code: median 43 nodes and 94 evidence records (31–67 nodes).
- Codex: median 18 nodes and 45 evidence records (13–23 nodes).
- Copilot: median 16 nodes and 49 evidence records (13–18 nodes).

Claude Code reported about 118 USD for its 12 runs (5.0–14.7 per run). Codex and Copilot did not expose cost.

### Validator friction

| Host | Helper runs (validate/publish) | Failed validations | First validation passed | Error instances |
|---|---|---|---|---|
| Claude Code | 19/12 | 1 | 11 of 12 runs | quote_mismatch 1 |
| Codex | 23/11 | 8 | 6 of the 11 runs that validated | quote_mismatch 53, reference 15, invalid_json 1, duplicate_reference 1 |
| Copilot | 54/10 | 27 | 1 of 12 runs | quote_mismatch 102, reference 27, 13 others |

- **Quote mismatches dominate.** 26 of the 36 failed validations contained `quote_mismatch`, 156 instances in all.
- **Most were wrong line numbers.** Of the 72 Copilot instances reproduced exactly, 57 had the right text at the wrong line numbers. In 30 of those, the start line was right and the end line was off by at most two. Ten were paraphrases or typos.
- **The message could not show the difference.** In 37 of the 72, the first difference came after the 200 characters the error message shows.
- **No encoding or notebook problems.** None of the reproduced mismatches involved CR, tab or BOM characters, and no notebook citation failed in any run.
- **Scripted quotes never failed.** Runs that built quotes by slicing the cited line ranges in a script (8 of 12 Claude Code runs, 5 Codex runs) had no quote errors.
- **Unused features.** No run used `upsert`, and no run published an early `partial` revision.

### Time

- Median wall time was 20.2 min for Claude Code (range 11.1–27.2), 19.9 for Codex (11.3–40.1) and 6.5 for Copilot (2.8–11.6).
- Median time to the first successfully written draft was 15.9, 14.8 and 3.6 min respectively.
- Runs over 20 minutes of wall time: Claude Code 6 of 12, Codex 6 of 12, Copilot 0 of 12.
- Measured at the moment of publication, 24 of 36 runs published within 20 minutes (Claude Code 7, Codex 7, Copilot 10), 30 within 25, 31 within 30 and 32 within 40.

## What the artifacts showed

Across the 32 artifacts, reviewers found no scenario mixing, and hosts avoided almost all the traps the checklists anticipated. For example, none invented training or evaluation steps, and none presented a docstring's learning-rate schedule as the code's. All three hosts treated the yolov5 COCO128 validation split, which uses the training images (`data/coco128.yaml:15-16`), as a configuration fact rather than a bug in `train.py`.

**Points only one host established.** All are Claude Code's, and each was checked against source by its reviewer.

- **CLIP.** Two class names in notebook cell 8 (zero-based) are duplicated: "missile" at indices 657 and 744, and "sunglasses" at 836 and 837. The duplicates give identical classifier columns. Claude Code found this by parsing the literal as data.
- **dino.** The help text for `--warmup_teacher_temp_epochs` gives a default of 30, but the actual default is 0 (`main_dino.py:74-75`). Separately, building the argument parser calls `torch.hub.list` (`main_dino.py:45-47`).
- **whisper.**
  - A cleared first segment gains a `words` key (`whisper/transcribe.py:484-489`). This switches the subtitle writers onto the word-timing path (`whisper/utils.py:196`), which can raise `KeyError`.
  - `whisper/decoding.py:660` returns a `TypeError` instead of raising it.
- **xgboost.** The demo's comparison is not like for like:
  - the Python squared-log objective lacks the native Hessian floor (`src/objective/squared_log_obj.h:24`);
  - the custom-objective run starts from the default intercept, while the native runs estimate it (`src/learner.cc:1045` versus `1073`).
- **torchtune.** With `seed: null`, the drawn seed is never logged or saved: the recipe sets the log level to INFO (`recipes/lora_finetune_single_device.py:152`) before `set_seed` (`:164`) reports the seed at debug level (`torchtune/training/seed.py:60`).
- **pytorch-lightning.** Only Claude Code resolved that `feature_extractor[-5:]` (`examples/pytorch/domain_templates/computer_vision_fine_tuning.py:83`) unfreezes all four ResNet stages, not "the last two layer groups". All three hosts found that the example's module docstring states learning rates ten times the code defaults.
- **detr.** `class_error` is logged as 100 for batches without targets (`util/misc.py:435-436`).
- **denoising-diffusion-pytorch.** FID reference statistics are drawn from the training iterator and advance it (`denoising_diffusion_pytorch/fid_evaluation.py:75`). The flash-attention check requires compute capability strictly above 8.0 (`denoising_diffusion_pytorch/attend.py:66`).

**Errors in published artifacts (examples).**

- **Copilot, pytorch-image-models.** Stated the ResNet-50 evaluation transform from the base config template (bilinear, crop 0.875). The registry's default tag, `resnet50.a1_in1k` (`timm/models/resnet.py:909`), uses `_rcfg`, which gives bicubic and crop 0.95 (`:824-829`). Claude Code resolved this correctly; Codex left it unresolved.
- **Copilot, denoising-diffusion-pytorch.** Described a shorter-side resize followed by a real centre crop. The image size is a tuple, so the resize squashes images to 128x128 and the crop does nothing.
- **Codex and Copilot, dino.** Gave the teacher network two backbone passes. The teacher receives only the global crops (`main_dino.py:318`).
- **Copilot, whisper.** The graph routes the fallback result around the no-speech gate and leaves out the retry edge, although the node text is mostly correct.
- **Claude Code, yolov5.** A finding claims no gradient is lost at epoch boundaries. During warmup, the arithmetic drops 9 batches (for 128 images), because `optimizer.zero_grad()` at the start of each epoch (`train.py:376`) discards gradients not yet stepped.
- **Codex, denoising-diffusion-pytorch.** Reported a critique correction that never reached the artifact, because its edit script's string replacement did not match.

**Patterns.**

- **Depth versus speed.** Claude Code was deepest and slowest. Copilot was fastest and thinnest. Codex was compact and accurate, but lost two runs to timeouts.
- **Basis labels.**
  - Some artifacts marked nearly everything observed, including claims about code they had not read: Codex on whisper (32 of 32 elements) and Copilot on xgboost (34 of 34).
  - Claude Code often marked nodes observed and qualified inferred sub-claims only in the text.
- **Findings.** Of the 70 findings in published artifacts, 48 were valid, 16 trivial, 4 plausible but unverified, and 2 described intended behaviour.
  - Trivial findings mostly restated coverage limitations or described intended design.
  - All three CLIP artifacts carried the same medium finding restating an external uncertainty the scenario allowed.
  - `counterEvidence` was rarely used, and twice it only repeated the supporting evidence.
- **Citations.**
  - Codex cited coarse spans, up to 131 lines.
  - Copilot's quotes after repair were often single lines that do not show the claim.
  - Claude Code's spans were narrow (medians of about 5–10 lines).
- **Edge kinds.** Codex left edge kinds empty in most artifacts, and Copilot used free text. The viewer styled only four kinds and drew everything else as unknown.

## Why four runs published nothing

- **Copilot, vit-pytorch.** The failing quote was a 27-line citation of `vit_pytorch/efficient.py` (lines 9-35) with two paraphrased assertion messages. It took three validations to surface:
  1. The first reported only a misplaced `cell` field, and the helper skipped the quote check after that error.
  2. The second reported invalid JSON that the host's own edit had introduced.
  3. The third reported the quote mismatch, but its first difference lay after the 200 characters the message shows.

  The host then stopped at the two-round limit. With that one quote corrected, the draft validates.
- **Copilot, detr.**
  1. The first round had an off-by-one range.
  2. The fix moved the range in the wrong direction.
  3. The host copied a quote from the error message for a range it had just changed, leaving one extra trailing newline.

  The host stopped at the limit and deleted its draft.
- **Codex, trl and torchtune.** The drafts (45–90 KB) were written through JavaScript template literals in the host's exec tool. Backticks from Markdown code spans broke the parse repeatedly, and once the draft directory was missing. About 25 and 15 minutes respectively went to failed writes.
  - The trl draft then failed on a duplicate JSON member and 11 quote mismatches.
  - The torchtune draft was never validated. Checked on a copy, it has 17 quote mismatches and 2 unknown evidence IDs.

The same failure mode was recorded in the development follow-ups, where a Copilot run failed within its two-repair budget ([PILOT_READINESS.md](../../evals/workflow/PILOT_READINESS.md)).

## Viewer check

- **Opening.** All 32 artifacts opened through the extension's open and validation path in their own workspaces, with no refusal, banner or page error. Opening plus validation took 7–60 ms, with one 197 ms cold-cache outlier. Rendering took under 60 ms.
- **Navigation.** Evidence links opened the cited file at the cited line in all 32, including notebook cells in the five notebook artifacts.
- **Banners.** On a scratch copy, the stale, restored and unsaved-buffer banners behaved as designed. A deleted cited file was reported as "changed" rather than missing.
- **Layout was the problem.**
  - In a 1440x900 window, with the panel beside the artifact editor (541 px wide), the request and coverage header took 736–915 px. That left the diagram canvas at 0 px for all 12 Claude Code artifacts. Codex and Copilot artifacts got a strip of 39–196 px. At 393 px (fresh profile, secondary side bar open) the canvas was 0 px for 31 of 32.
  - With the panel filling the editor area, 27 of 32 artifacts opened below the zoom level at which edge labels and card details are drawn. Fit reached the 0.15 zoom floor for the three largest (dino, whisper and pytorch-lightning, all Claude Code).
  - In 4 Claude Code artifacts, the default-collapse rule folded away the main training loop.
  - 723 of 865 node labels exceed the 34-character title limit.
  - 87% of non-group nodes (711 of 817) are drawn with the unknown-kind question-mark glyph.
- **Dropped edge.** One Copilot self-loop edge passed the helper but was not drawn.

Screenshots were taken but are not committed.

## Product issues, ranked

The ranking is the review's, by impact on the first run. The last column says what the local fixes did (see [What was changed](#what-was-changed)).

| # | Area | Issue | Direction | Held-out note | Local change |
|---|---|---|---|---|---|
| 1 | Viewer | The authored header has no size limit; the canvas is 0 px at the default panel size | Collapse and cap the header; give the canvas a minimum height; add a regression test | Viewer only | Changed |
| 2 | Helper | `quote_mismatch`, reference and duplicate errors do not locate the problem; some errors hide others | Report the evidence id, range, first difference and "found at lines X–Y"; name IDs; keep checking | General | Changed |
| 3 | Helper and skill | No way to get an exact excerpt; no guidance on span size | A read-only `excerpt` command; cite the narrowest operative range; warn on very broad spans | Makes `exactAnchors` near-automatic | Changed |
| 4 | Skill | The two-round repair limit is undefined and stops converging runs; drafts are deleted | Define a round; make the limit progress-based or higher; keep failing drafts | Policy decision before freeze | Changed in the skill text; the policy value is the owner's |
| 5 | Skill | Drafting starts late; the budget is unknown to hosts; no partial publication; fragile draft writes | Validate a skeleton early; publish partial revisions; write drafts with the file-edit tool; multi-record `upsert` | Scoring of partial coverage | Changed |
| 6 | Viewer | Large diagrams are illegible (zoom, Fit, rail, minimap, collapsed loop) | Phase overview, rail overlay, zoom to selection, a better collapse rule | Viewer only | Partly (no phase overview) |
| 7 | Skill | Basis labels do not track framework- or runtime-dependent claims | Basis is the weakest load-bearing claim; split inferred consequences into their own nodes | Keep wording framework-agnostic | Changed |
| 8 | Skill and contract | Findings restate limitations; severity is uncalibrated; `counterEvidence` is undefined | An admission test, a severity rubric and a definition of `counterEvidence` | Use no domain examples (risk for sklearn and notebook tasks) | Changed |
| 9 | Contract and viewer | No shared edge or node kind vocabulary | A recommended vocabulary, synonym normalisation and a helper warning | General | Changed, without a warning |
| 10 | Skill | Loops, shared components and branch outcomes are not drawn | A loop example and critique items | Moderate (loops, averaged or frozen components) | Changed |
| 11 | Helper | Isolated nodes, unused evidence, self-loops and duplicate files pass silently | Non-blocking warnings; draw self-loops | General | Changed |
| 12 | Skill | The critique does not verify claims or its own corrections | Re-read corrections; check lifecycle intervals; confirm the cited lines execute | Low to moderate | Changed; bounded after the confirmation |
| 13 | Skill | Registry-resolved and omitted-parameter values are taken from the wrong source | Cite the selection logic and the selected entry; list differences between compared variants | **High** (config-inheritance task) | Deferred |
| 14 | Viewer | Double title truncation; question-mark glyph on 87% of nodes | Wrap titles; use a neutral glyph | Viewer only | Changed |
| 15 | Run policy | Codex resolves `python3` to 3.9; permission blocks; unrelated MCP servers | Fix the login-shell interpreter, isolate host configuration, adjust allowlists | General | Skill part only (one helper call per command) |
| 16 | Skill | No supported way to list notebook cells | A documented read-only listing or excerpt | **High** (notebook task); weak evidence of need | Deferred (`excerpt --cell` covers exact citations) |
| 17 | Skill | The request question is paraphrased; limitations are mislabelled; the path rule is over-applied | Record the question verbatim; tag limitations; narrow the path rule | General | Changed |
| 18 | Host integration | `producer.model` and campaign metrics are unreliable | Record the exact model id; count from transcripts | General | Skill part only |
| 19 | Contract | `request.entrypoints` accepts non-file strings | Resolve entrypoints, or formalise `path::symbol` | General | Deferred |
| 20 | Contract | Long single-line literals cannot be cited economically | Consider column ranges (low priority) | Low | Deferred |
| 21 | Extension | A deleted file is reported as "changed" | Word the banner from the stale reason | None | Changed |
| 22 | Evaluation | Model-written review aids contained errors | Verify reference facts against source | Process only | No product change |

## What was changed

The fixes are summarised in [CHANGELOG.md](../../CHANGELOG.md), section "Unreleased — Campaign 3: public shakedown fixes". The CHANGELOG describes them as local changes checked by local tests; the version stays 0.3.0, and this record does not re-report those checks. In brief:

- **Helper** (`artifact.py`, no schema change): a read-only `excerpt` command that prints one evidence record exactly as `validate` accepts it; `quote_mismatch` details (id, file, range, first difference, a `foundAt` hint that rewrites nothing); reference and duplicate errors that name the value; errors that no longer hide one another; six non-blocking warnings and a basis summary; multi-record `upsert`.
- **Contract documentation:** the helper commands and warnings, a verbatim `request.question`, limitation prefixes (`Excluded by request:`, `Not inspected:`) and an optional recommended kind vocabulary. Free-text kinds stay valid.
- **Skill:** citations come from `excerpt`; a repair round is defined; drafts start in the run folder with the file tool, as an early validated skeleton grown with `upsert`; basis is the weakest load-bearing claim; findings need a consequence and a change; structure rules for loops, shared components and branch outcomes; critique checks; a new small example.
- **Viewer:** a collapsed, capped header with a canvas floor. In a headless Chrome measurement of the 32 artifacts plus one contract-maximum document, panels with a zero-height canvas went from 13/33 (541 px), 32/33 (393 px) and 1/33 (1382 px) to none. Also: wrapped titles, styled kinds, rail and zoom rules, and drawn self-edges.
- **Extension:** a deleted cited file is reported as missing.
- **After the confirmation:** `c37a275` bounds the critique (correct, qualify and connect what the draft covers, then publish); `577a381` counts a repair round only as an edit after a `validate` or `publish` error, and removes publish-as-partial at the limit. `577a381` was not re-run (see below).

**Deferred, and why.**
- Issue 13: the review rated its overfitting risk high because registry and override resolution overlaps held-out pilot tasks. The existing generic obligation stays; the owner decides after the first pilot stage.
- Issue 16: weak evidence of need (no notebook citation failed) and direct relevance to a held-out task. `excerpt --cell` covers exact notebook citations.
- Issues 19 and 20: both are contract changes across schema, helper, extension, viewer and docs, and are kept out of the pre-freeze contract.
- Also not done: the optional phase overview (issue 6), the harness side of issue 18, an `ancestor_edge` warning and a missing-kind warning. Issue 22 needs no product change.

**Measurement caveat.** Once quotes come from `excerpt`, the pilot's `exactAnchors` target (T2) shows only that cited ranges exist and are fresh. Whether a range supports its claim rests on supported-claim scoring (`supportedClaimPrecision`, T3). The CHANGELOG lists further points for the owner: the skill's repair-round limit and counting rule must agree with the run policy; one `excerpt` call per record has not been timed against the proposed 20-minute budget; a published partial revision may lower `essentialFactRecall` (T4); a verbatim question lengthens the header's one-line question.

## Confirmation run

### Cases

The ten cases, with what each had shown in the first run:

| Host | Case | First run |
|---|---|---|
| Copilot | vit-pytorch | Nothing published: stopped at the repair limit |
| Copilot | detr | Nothing published: stopped at the repair limit, draft deleted |
| Copilot | pytorch-image-models | Published after 4 failed validations; wrong evaluation transform |
| Copilot | pytorch-lightning | Published after 5 failed validations, reported as 2 rounds |
| Codex | trl | Nothing published: 40-minute timeout after failed draft writes |
| Codex | torchtune | Nothing published: 40-minute timeout, never validated |
| Codex | dino | Published after 2 failed validations (16 quote mismatches) |
| Codex | whisper | Published after 2 failed validations; all 32 elements observed |
| Claude Code | whisper | Published at 21.4 min (21.8 min wall time); 58 nodes |
| Claude Code | yolov5 | Published at 26.9 min (27.2 min wall time, the longest Claude Code run); the wrong zero_grad finding |

All runs in a batch started together: four Copilot, four Codex and two Claude Code runs. After the timeout described below, Claude Code yolov5 was re-run with the bounded critique.

### Infrastructure stops

Four of the ten cases were stopped by account quotas. These are infrastructure stops, not skill outcomes, and nothing was published in them.

- **Codex trl, torchtune and dino** stopped at 26.8, 27.4 and 27.6 minutes with "You've hit your usage limit". The account's limit resets on 2026-10-26.
- **Copilot pytorch-image-models** stopped at 10.9 minutes with "You have exceeded your monthly quota" (200 of 200 chat requests; resets 2026-10-01).

| Case | Validations before the stop | Upserts | Draft left in the run folder |
|---|---|---|---|
| Copilot pytorch-image-models | 1 passed (1.7 min) | 9 accepted | 44 nodes, 77 edges, 93 evidence |
| Codex trl | 1 passed (6.5 min) | 9 accepted, 2 refused | 39 nodes, 67 edges, 54 evidence |
| Codex torchtune | 1 failed (1 quote_mismatch), then 1 passed (8.2 min) | 6 accepted, 1 with no parsed result | 38 nodes, 66 edges, 68 evidence |
| Codex dino | 1 passed (4.0 min) | 5 accepted, 2 refused, 1 with truncated output | 59 nodes, 2 edges, 60 evidence |

In each stopped run, the last helper call was an accepted upsert, and upsert validates the whole draft. None of these drafts was reviewed.

### Before and after, completed cases

| Case | Run | Wall min | Failed validations / repair rounds | Outcome | Rating | Checklist coverage |
|---|---|---|---|---|---|---|
| Copilot vit-pytorch | first | 2.8 | 3 / 2 | stopped at the limit, nothing published | failed | — |
| | confirmation | 5.4 | 0 / 0 | published | strong | 92.9% |
| Copilot detr | first | 4.6 | 3 / 2 | stopped at the limit, draft deleted | failed | — |
| | confirmation | 10.0 | 1 / 1 | published | strong | 92.3% |
| Copilot pytorch-lightning | first | 8.0 | 5 / 5 (reported 2) | published | adequate | 96.4% |
| | confirmation | 10.1 | 0 / 0 | published | adequate | 92.9% |
| Codex whisper | first | 24.1 | 2 / 2 | published | adequate | 67.9% |
| | confirmation | 27.3 (published at 24.2) | 0 / 2, as the host counted 3 refused upserts | published a 3-node partial revision | failed | 7.1% |
| Claude Code whisper | first | 21.8 | 0 / 0 | published | strong | 100% |
| | confirmation | 18.4 | 0 / 0 | published | strong | 100% |
| Claude Code yolov5 | first | 27.2 | 0 / 0 | published | strong | 100% |
| | confirmation | 40.1 | 0 / 0 | timed out, nothing published | not reviewed | — |
| | re-run (bounded critique) | 21.5 (published at 21.1) | 0 / 0 | published | strong | 100% |

Claude Code cost 10.05 USD for whisper (9.32 in the first run) and 13.38 USD for the yolov5 re-run (14.74). The timed-out yolov5 attempt reported no cost.

### Helper use

| Run | `excerpt` calls (errors) | `upsert` (refused) | `validate` (failed) | `publish` | First `validate` (min) |
|---|---|---|---|---|---|
| Copilot vit-pytorch | 34 (0) | 7 (0) | 5 (0) | 1 | 1.8 |
| Copilot detr | 25 (0), plus a script run 6 times | 11 (0) | 4 (1) | 1 | 0.8 |
| Copilot pytorch-lightning | 68 (1), plus a script run 4 times | 12 (0) | 4 (0) | 1 | 2.1 |
| Codex whisper | 62 (1) | 4 (3) | 2 (0) | 1 | 5.2 |
| Claude Code whisper | 2 (0), plus a script for 119 records | 8 (0) | 3 (0) | 1 | 8.0 |
| Claude Code yolov5, timed out | 0 direct; a script | 7 (0) | 2 (0) | 0 | 26.5 |
| Claude Code yolov5, re-run | 3 (0), plus a script for about 120 records | 8 (0) | 3 (0) | 1 | 6.6 |

Excerpt errors (a range past the end of a file, a path outside the workspace) and refused upserts leave the draft unchanged. Every run used `upsert`; none had in the first run. In the first run, the first helper call came at 21.3 min (Claude Code whisper), 26.8 (Claude Code yolov5) and 20.6 (Codex whisper).

### Claude Code yolov5: timeout and re-run

The first confirmation attempt had a complete draft that validated at 28.4 minutes. The critique then turned into new tracing, and the draft grew to 62 nodes, 127 edges and 194 evidence records. The harness stopped the run at 40 minutes, during upserts, with nothing published. The 0.3.0 skill had published this case at 26.9 minutes.

Commit `c37a275` bounds the critique: it corrects, qualifies and connects what the draft already covers, and then the run publishes. Further work is named as a `Not inspected:` limitation and continued in a child revision. The re-run with that skill validated a skeleton at 6.6 minutes and a complete draft at 17.7 minutes. It spent about 3.4 minutes on one critique pass, published at 21.1 minutes, and reported 0 repair rounds, with critique corrections listed separately.

### Codex whisper: a regression, and a rule change that was not re-run

The Codex whisper confirmation published a valid partial revision with 3 nodes, 2 edges and no findings. Of its 24 evidence records, 20 are uncited. Checklist coverage fell from 67.9% to 7.1%.

The host validated a 3-node skeleton at 5.2 minutes, then retyped `excerpt` output into hand-written record files. Three upserts on two record batches were refused: two quote mismatches, then invalid JSON, then five quote mismatches. The reviewer found that 5 of the 7 mismatches were a dropped trailing empty line. Under the skill as run, the host counted the refusals as its two repair rounds. A rule then in force published a still-valid draft as `partial` at the limit, so the skeleton was published at 24.2 minutes, with about 16 minutes of budget left. The host's chat report traced most of the workflow, and it contained a valid finding on the whisper subtitle writers that never reached the artifact.

Commit `577a381` changes the rule. A repair round is now only an edit after a `validate` or `publish` error. A refused upsert changes nothing: the host fixes the record file and applies it again, drops it after a third refusal and names the dropped work. Publish-as-partial at the limit is removed. **This change was not re-run on a live host**, because the Codex and Copilot quotas were exhausted. Codex trl also had two refused upserts, but each was fixed on the next attempt, so no error remained at the limit and it kept growing its draft until the quota stop.

### What the reviews found

Six confirmation artifacts were reviewed: the five completed cases plus the yolov5 re-run. As before, these are provisional model reviews.

| Artifact | Rating (first run) | Checklist (first run) | Claims chk/sup/unsup/wrong | Findings V/T/P/I | Nodes/edges/evidence (first run) | Citation span median/max, lines (first run) |
|---|---|---|---|---|---|---|
| Copilot vit-pytorch | strong (failed) | 92.9% (—) | 28/25/3/0 | 1/0/0/0 | 25/39/25 (—) | 6/27 (—) |
| Copilot detr | strong (failed) | 92.3% (—) | 30/28/1/1 | none | 42/84/56 (—) | 17/49 (—) |
| Copilot pytorch-lightning | adequate (adequate) | 92.9% (96.4%) | 25/23/1/1 | 1/1/0/0 | 39/60/61 (18/23/60) | 20/45 (10/41) |
| Codex whisper | failed (adequate) | 7.1% (67.9%) | 22/18/2/2 | none | 3/2/24 (13/19/52) | 10.5/30 (9/39) |
| Claude Code whisper | strong (strong) | 100% (100%) | 30/29/1/0 | 2/0/0/1 | 55/99/121 (58/64/96) | 8/31 (10.5/57) |
| Claude Code yolov5 re-run | strong (strong) | 100% (100%) | 40/37/2/1 | 3/1/0/0 | 59/113/132 (48/74/160) | 8.5/31 (5/21) |

In total, 175 claims were checked: 160 supported, 10 unsupported and 5 wrong. The 10 findings were 7 valid, 2 trivial and 1 intended behaviour.

**Improvements.**
- Two first-run non-publications, Copilot vit-pytorch and detr, published strong artifacts. In detr, the new `quote_mismatch` detail (the difference, `foundAt` and a trailing-empty-line hint) fixed both first-round errors in one round. Over the four Copilot cases, including the one stopped by quota, failed validations fell from 15 in the first run to 1.
- In five of the six artifacts every evidence record came from `excerpt`; Codex whisper retyped `excerpt` output by hand. All published quotes match the source, and all six artifacts revalidated.
- The new guidance is visible:
  - verbatim questions and tagged limitations, in the five reviews that checked them;
  - recommended kinds, except five Copilot detr nodes whose kind repeats a basis value;
  - loop nodes with back-edges in every artifact that published those stages;
  - shared components wired to each consumer;
  - separate state nodes for different update mechanisms in pytorch-lightning and yolov5.
- Framework- and runtime-dependent consequences moved into their own inferred or unresolved nodes and edges (Claude Code whisper and yolov5, Copilot detr, pytorch-lightning and, in part, vit-pytorch).
- First-run errors were corrected. The yolov5 finding now says warmup drops batches and none are dropped afterwards. A re-run of the step arithmetic confirms 9 dropped batches, at the starts of epochs 3–8 and 10 (zero-based). The one wrong claim in Claude Code whisper was fixed. Trivial findings from the first run were dropped in Claude Code whisper and yolov5.
- Claude Code published faster on both cases (wall time 18.4 against 21.8 min; 21.5 against 27.2).

**Regressions.**
- **Wider citations.** yolov5 went from a median span of 5 to 8.5 lines (max 21 to 31) and Copilot pytorch-lightning from 10 to 20 (max 41 to 45). Copilot detr has a median of 17 and a max of 49, with 9 records over 30 lines; the first-run Claude Code detr artifact had a median of 10 and a max of 26. Claude Code whisper went the other way (10.5 to 8). The helper's `wide_evidence` warning starts above 60 lines, while the skill says rarely more than about 30, so none fired.
- **Denser graphs.** Edges per node rose from 1.54 to 1.92 in yolov5, from 1.10 to 1.80 in Claude Code whisper and from 1.28 to 1.54 in Copilot pytorch-lightning; Copilot detr has 2.00. The yolov5 model node has 18 edges. Readability was judged from structure only; these artifacts were not rendered.
- **Findings that fail the admission test.** Claude Code whisper admitted documented, announced behaviour (language detected once from the first 30 seconds) as a medium finding with an observed basis. Copilot pytorch-lightning rated a trivial BatchNorm finding medium. yolov5 added a trivial low finding on best.pt being written on exact fitness ties.
- **Wrong claims where the first run was right.** yolov5 states the next epoch's rate after `scheduler.step()` as `lf(epoch + 1)`. Because the scheduler's constructor steps once and `train.py:344` resets `last_epoch`, the rate is `lf(epoch)` (`train.py:249`, `344`, `439`); the claim is labelled inferred. Copilot pytorch-lightning draws validation before the epoch scheduler step. In source, `MultiStepLR` steps at the last batch (`src/lightning/pytorch/loops/training_epoch_loop.py:358-362`) and validation runs afterwards (`:406`).
- **Other wrong claims.** Copilot detr says distributed mode needs `RANK` and `WORLD_SIZE`, missing the SLURM branch of `init_distributed_mode` (`util/misc.py:412-414`). A Codex whisper limitation misstates which evidence the helper refused.
- **Basis.** yolov5 still has 17 observed nodes that carry inline inferred sub-claims. Copilot vit-pytorch labels nothing unresolved, although two unresolved points sit inline in observed nodes.
- **Process.** Codex whisper retyped `excerpt` output instead of using it unchanged. Copilot pytorch-lightning rewrote draft fields from Python string literals, against the drafting rule, with no effect on the published artifact. The Copilot confirmation runs took longer than their first runs (5.4, 10.0 and 10.1 min against 2.8, 4.6 and 8.0), and their artifacts were larger (25–42 nodes, against a first-run Copilot median of 16).

## Observations for the run-policy decision

These are data for the owner's decision in [run-policy.md](../../evals/workflow/decisions/run-policy.md). This record does not make the decision.

- **Budget.**
  - First run: applying the proposed policy strictly (20 active minutes, at most two repair rounds, no retries) would leave 21 of 36 runs valid, 7 per host. With 30 minutes, 31 of 36 published in time, or 28 with a strict two-round limit.
  - Confirmation: the six publications came at 5.0, 9.7, 9.8, 18.0, 21.1 and 24.2 minutes, so 4 were within 20 minutes and all 6 within 25. The 24.2-minute one was the forced Codex whisper partial. The timed-out yolov5 attempt would have missed any cap.
  - The first validation now comes early, but complete drafts still come late for Claude Code (15.3 and 17.7 minutes).
  - The prompt still did not state the budget, and no run published a partial revision under the partial-publication rule. Keeping 20 minutes with early partial publication therefore remains untested.
  - One `excerpt` call per record ran on all three hosts: up to 68 direct calls in a published Copilot run (144 in the stopped one) and 62 in Codex whisper. There was no stated budget, and the prompt was unchanged.
- **Repair rounds.**
  - First run: both Copilot give-ups were one fix from valid. Three Copilot runs published valid artifacts after three to five failed validations. Self-reported round counts were wrong twice.
  - Confirmation: five of the six publications used 0 or 1 validation repair rounds, and every reviewed report stated its round count accurately. The exception is the Codex whisper case above, where refused upserts counted as rounds under a rule since replaced and not re-run.
  - The skill now allows "at most two rounds unless the user or the run sets another limit" and counts only edits after `validate` or `publish` errors. Whatever the run policy records should use the same count.
- **Infrastructure retries.** The first run had no infrastructure failure. In the confirmation, 4 of 10 cases stopped on account quotas after the prompt was sent: Codex in 3 of 4 runs at about 27 minutes, and Copilot in 1 of 4 at 11 minutes. All four Codex runs, and all four Copilot runs, had started at once. Under the proposed rule, a retry is allowed only if the prompt was never sent, so quota headroom is a precondition for a pilot stage.
- **Helper Python.** Codex's login shell resolved `python3` to 3.9 in all 12 first-run runs and all 4 confirmation runs; each run then found a 3.10 or newer interpreter itself. The interpreter has to be set in the host's login shell, not only in the launcher environment.
- **Copilot model and reasoning.** Auto resolved to gpt-6-luna in 11 first-run runs and gpt-5.6-luna in one, and to gpt-6-luna in all 4 confirmation runs. The harness records "auto", and the Copilot artifacts omit `producer.model`, which the skill allows when the host does not expose it. The resolved model should be recorded for every run. Auto rejects an explicit reasoning effort; the stopped confirmation run's host telemetry reported "medium".

## Limitations

- This is a provisional review of model output by model reviewers. There was no human review and no reference adjudication.
- Each host ran once per repository in the first run, and each confirmation case ran once, so run-to-run variance is unknown. The yolov5 re-run is a second sample of one case, not a replicate.
- The confirmation cases are the first run's problem cases plus two long Claude Code runs. They are not a representative sample, and 4 of the 10 were stopped by quotas.
- The last rule change (`577a381`) has not run on a live host.
- Reviewers chose which claims to check. Supported counts are not precision estimates. Confirmation reviewers saw the first-run results.
- The checklists were model-written. Reviewers found errors in several:
  - trl item 1: unknown CLI arguments still raise (`trl/scripts/_hf_argparser.py:379-380`);
  - vit-pytorch items 2 and 14;
  - whisper items 10 and 14;
  - torchtune's external-boundary list;
  - pytorch-image-models, which treated a statically resolvable data config as a runtime value;
  - denoising-diffusion-pytorch, which missed `drop_last` and the capability check.
- Host differences are confounded by model, reasoning setting and tools. Copilot's Auto mode resolved to the same model family that Codex ran.
- The hosts ran from a harness, not through the pilot's operator-driven VS Code procedure. The prompt did not state the budget. Workspaces were sanitized copies without Git metadata.
- No target code was executed, so runtime behaviour is qualified rather than observed.
- The viewer check ran on macOS only, at a small set of window sizes, and only on first-run artifacts.
- These repositories are not the pilot repositories, and these results do not predict pilot scores.

## Next steps

- The owner decides the run-policy fields, and which changes go into the candidate before `pilot-01` is frozen. Any change to the skill, helper, contract, extension or viewer produces a new candidate. After the freeze, a change means a new campaign.
- `577a381` is untested on a live host. Re-running the Codex whisper case and the four quota-stopped cases would test it, which is possible once the quotas reset (Copilot on 2026-10-01, Codex on 2026-10-26 for this account).
- The confirmation reviews proposed further changes, none of them verified:
  - bring the `wide_evidence` threshold closer to the skill's span guidance;
  - let `excerpt` write records to a file, so hosts never retype quotes;
  - warn on duplicate edges and on a node kind that repeats a basis value;
  - say where a user's scenario paragraph belongs in the request.

  These are candidate changes for the owner to accept or leave.
- Fixes with high held-out relevance (issues 13 and 16) need an explicit owner decision, not a routine change.
- The denser confirmation artifacts have not been opened in the viewer.
- `docs/STATUS.md` changes only when what ships changes.
