# MLView — Issue Rule Catalog

**Status:** frozen for the prototype build. Version 1.0, 2026-09-06.
Rule codes are stable identifiers. Severities are **fixed** — a red octagon means the same thing in every screenshot. Rules can be disabled (`.mlview.toml`, `mlview.disabledRules`, `# mlview: ignore[CODE]`), never re-graded.

---

## 0. How to read this catalog

Every rule is a pure function `check(ctx: GraphContext) -> Iterable[Issue]` registered by `@rule(...)`. `GraphContext` exposes the graph, the IR, the AST index, and helper queries (`ctx.calls_of(fqn)`, `ctx.loops(kind="batch")`, `ctx.values_tagged(ValueTag.TEST_SPLIT)`, `ctx.binding_of(name)`, `ctx.class_bases(node)`, `ctx.frameworks`), so a rule is 10–40 lines rather than an ad-hoc tree walk.

### Iron laws

1. **No rule may match a bare attribute name.** Every rule matches **canonical FQNs** resolved through `ir/symbols.py` against `knowledge/*.yaml`. `model.eval()` is only `torch.nn.Module.eval` if the binding resolves there.
2. **Name regexes reinforce, they never create.** A `ValueTag` comes from dataflow. A regex like `(?i)^(x_)?(test|val|valid|holdout)` may only strengthen an existing tag; a regex-only match multiplies confidence by **0.8**.
3. **Absence-of-evidence rules are capped.** A rule that fires on the *absence* of a call (`MLV201`, `MLV202`, `MLV301`, `MLV601`) may emit `high` **only** when the enclosing construct resolved with no dynamic constructs **and** no framework wrapper was detected. Otherwise it is emitted at `medium`. These rules are marked **H\*** below.
4. **The `negation_absent` gate is mandatory.** When Lightning, HuggingFace `Trainer`, `accelerate`, `ignite`, `fastai`, `Fabric`, DDP/FSDP/DeepSpeed is detected in the workspace, absence rules are multiplied by **0.4** (dropping them to `speculative`, off the Problems panel and behind the canvas toggle) and a visible chip explains why: *"training loop handled by Lightning — 7 rules not applicable."*
5. **Every rule has two fixtures.** `tests/fixtures/rules/<CODE>_bad.py` must fire; `<CODE>_good.py` must not. Every "false-positive note" below is a concrete `_good.py` file — that is the traceability link between this document and the test suite. `test_no_cross_fire` additionally asserts the *union* of all `_good.py` fixtures yields zero issues.
6. **Confidence, not severity, carries uncertainty.** `confidence = clamp(basePrior × Π evidence factors, 0.05, 0.99)`. Only `≥ 0.6` reaches the editor's Problems panel; the rest stay on the canvas behind `mlview.showSpeculative`.

### Severity semantics

| Severity | Marker | Means | Bar to clear |
|---|---|---|---|
| **high** | red octagon with `!` | This is very likely a real defect that silently corrupts results or crashes | Near-zero false positives on correct code — gated by `test_precision.py` |
| **medium** | amber warning triangle with `!` | Likely wrong, or right only under an assumption we cannot check | Should be right most of the time; phrased as a finding |
| **low** | small blue circle with `i` | Hygiene, reproducibility, portability, or a question worth asking | Phrased as advice or a question, never an accusation |

---

## 1. Catalog summary

**Prototype = 20 rules**, spanning all three severities and covering PyTorch and scikit-learn. **14 of them are marked ★**: those are the codes planted in `samples/vision_pipeline`, so the acceptance walkthrough depends only on those 14 and a slip in the other six cannot break the demo. The six unstarred prototype rules (MLV102, 202, 203, 204, 402, 701) still ship and are still gated by their own fixtures — they simply do not appear in the sample.

| Code | Sev | Title | Frameworks | Base prior | Status |
|---|---|---|---|---|---|
| **MLV000** | — | Analyzer diagnostic channel (not a user rule) | — | — | **prototype** |
| **MLV101** ★ | high | Preprocessing fitted before the train/test split | sklearn, pandas | 0.95 | **prototype** |
| **MLV102** | high | Transformer fitted on validation or test data | sklearn | 0.97 | **prototype** |
| **MLV103** ★ | medium | Preprocessing done outside cross-validation | sklearn | 0.85 | **prototype** |
| MLV104 | high | Resampling / oversampling applied before the split | imblearn, sklearn | 0.95 | later |
| MLV105 | medium | Target column left inside the feature matrix | pandas, sklearn | 0.80 | later |
| MLV106 | medium | Random split used on apparently temporal data | sklearn, pandas | 0.70 | **sprint 4** |
| MLV107 | medium | Test set used for model selection or early stopping | torch, sklearn, xgboost, keras | 0.85 | later |
| **MLV110** ★ | medium | Training DataLoader does not shuffle | torch | 0.85 | **prototype** |
| **MLV111** ★ | low | `shuffle=True` on a validation or test DataLoader | torch | 0.90 | **prototype** |
| **MLV112** ★ | medium | `DataLoader(num_workers>0)` without a `__main__` guard | torch | 0.98 | **prototype** |
| MLV113 | low | `drop_last=True` on an evaluation DataLoader | torch | 0.95 | later |
| MLV114 | medium | Random augmentation in the eval transform pipeline | torchvision, albumentations | 0.90 | **sprint 4** |
| MLV115 | high | Custom `Dataset` missing `__len__` or `__getitem__` | torch | 0.95 | later |
| MLV116 | low | Class imbalance signalled but never handled | torch, sklearn | 0.55 | later |
| MLV117 | medium | `train_test_split` without `stratify` on a classification target | sklearn | 0.65 | later |
| MLV118 | low | `ToTensor()` without `Normalize()` in an image pipeline | torchvision | 0.70 | later |
| MLV119 | low | Hard-coded absolute or user-specific data path | — | 0.95 | later |
| MLV120 | low | Hyperparameter magic numbers inline (off by default) | — | 0.50 | later |
| **MLV121** | high | `tf.data` shuffle feeds a `take`/`skip` holdout | tf, keras | 0.95 | **sprint 4** |
| **MLV201** ★ | high\* | Missing `optimizer.zero_grad()` in the training step | torch | 0.90 | **prototype** |
| **MLV202** | high\* | Gradients computed but `optimizer.step()` never called | torch | 0.90 | **prototype** |
| **MLV203** | high | `optimizer.step()` called before `loss.backward()` | torch | 0.95 | **prototype** |
| **MLV204** | high | `.backward()` inside `torch.no_grad()` / `inference_mode()` | torch | 0.97 | **prototype** |
| **MLV205** ★ | medium | Loss accumulated without `.item()` / `.detach()` | torch | 0.85 | **prototype** |
| MLV206 | high\* | Loss computed but never backpropagated | torch | 0.90 | later |
| MLV207 | medium | Scheduler stepped at the wrong granularity | torch | 0.80 | **sprint 4** |
| MLV208 | medium | AMP `GradScaler` used inconsistently | torch | 0.85 | **sprint 4** |
| MLV209 | medium | Gradient clipping in the wrong position | torch | 0.85 | **sprint 4** |
| MLV210 | low | Recurrent model trained without gradient clipping | torch | 0.60 | later |
| MLV211 | medium | Optimizer built over parameters of a model later wrapped or replaced | torch | 0.80 | later |
| MLV212 | medium | `reduction='none'` loss backpropagated without aggregation | torch | 0.90 | later |
| **MLV301** ★ | high\* | Evaluation loop without `model.eval()` | torch | 0.85 | **prototype** |
| **MLV302** ★ | medium | Evaluation loop not wrapped in `torch.no_grad()` | torch | 0.85 | **prototype** |
| MLV303 | medium | `model.train()` never restored after evaluation | torch | 0.85 | later |
| MLV304 | medium | No validation loop at all | torch, sklearn, keras | 0.80 | later |
| MLV305 | medium | Accuracy computed on raw logits instead of predicted classes | sklearn, torch, torchmetrics | 0.85 | **sprint 4** |
| MLV306 | low | Ranking metric (`roc_auc`, `average_precision`) fed hard labels | sklearn | 0.90 | **sprint 4** |
| MLV307 | low | Only accuracy reported on an apparently imbalanced problem | sklearn | 0.55 | later |
| MLV308 | low | Metric inappropriate for the task type | torch, sklearn, keras | 0.75 | later |
| **MLV401** ★ | high | Softmax / LogSoftmax applied before `CrossEntropyLoss` | torch | 0.95 | **prototype** |
| **MLV402** | high | Sigmoid / BCE pairing is inconsistent | torch | 0.95 | **prototype** |
| MLV403 | high | `NLLLoss` without a preceding `log_softmax` | torch | 0.90 | later |
| MLV404 | medium | Loss function does not match the task shape | torch | 0.75 | later |
| **MLV501** ★ | medium | Model moved to a device but batch tensors are not | torch | 0.90 | **prototype** |
| MLV502 | medium | Hard-coded `.cuda()` without an availability check | torch | 0.85 | **sprint 4** |
| MLV503 | low | Tensor allocated inside the training loop without `device=` | torch | 0.70 | later |
| **MLV601** ★ | low | No random seed set anywhere | all | 0.90 | **prototype** |
| **MLV602** ★ | low | Split / CV splitter without `random_state` or `generator` | sklearn, torch | 0.95 | **prototype** |
| MLV603 | low | Partial seeding — some randomness sources left unseeded | torch, numpy | 0.85 | later |
| MLV604 | low | Multi-worker DataLoader without `worker_init_fn` / `generator` | torch | 0.70 | later |
| MLV605 | low | Determinism claimed but nondeterministic backend settings left on | torch | 0.60 | later |
| **MLV701** | high | `nn.Module.__init__` does not call `super().__init__()` | torch, lightning | 0.97 | **prototype** |
| **MLV702** ★ | high | Submodules in a plain list/dict are never registered as parameters | torch | 0.95 | **prototype** |
| MLV703 | medium | `F.dropout` called without `training=self.training` | torch | 0.95 | later |
| MLV705 | high | Keras model `.fit()` without `.compile()` | keras | 0.95 | **sprint 4** |
| MLV706 | medium | Manual `backward()`/`step()` inside a Lightning `training_step` | lightning | 0.90 | **sprint 4** |
| MLV707 | medium | `LightningModule.training_step` does not return a loss | lightning | 0.90 | **sprint 4** |
| MLV708 | medium | HuggingFace `Trainer` configured without evaluation | hf | 0.85 | **sprint 4** |
| **MLV709** | high | Keras output activation contradicts `from_logits=True` | keras, tf | 0.95 | **sprint 4** |
| **MLV711** | medium | Batch-cadence scheduler returned without `interval: step` | lightning | 0.90 | **sprint 4** |
| MLV801 | medium | Training loop with no checkpointing | torch, sklearn, keras | 0.85 | later |
| MLV802 | medium | Best checkpoint selected on training loss, or never restored | torch | 0.80 | later |
| MLV803 | low | Whole model pickled; `torch.load` without `weights_only` | torch | 0.95 | **sprint 4** |
| MLV901 | medium | Preprocessing applied in training but missing on the inference path | sklearn, torch, keras, hf | 0.80 | later |
| MLV902 | medium | Tokenizer / checkpoint identifier mismatch between train and inference | hf | 0.85 | later |
| MLV903 | low | Orphan stage — defined but never reached from an entrypoint | all | 0.70 | later |

**Sprint 4 — the three rule tiers.** Sixteen codes carry the status **sprint 4** above: MLV705–709 and MLV711 (ANA-7, framework rules), MLV207–209, MLV502 and MLV803 (ANA-8, training mechanics), MLV106, MLV114, MLV121, MLV305 and MLV306 (ANA-9, held-out integrity). Three of them — MLV121, MLV709 and MLV711 — were not in this catalog at all and their detection sketches are in section 4 with the rest. Each carries the two-fixture discipline of section 5 and a generated `docs/rules/<CODE>.md` page, and each is measured per rule by `tools/accuracy.py`; the tolerance the lead set is zero `forbidden` findings, ever, and recall that may only ratchet up. `docs/CONTRACTS.md` §11.26 is the normative record.

**Prototype severity spread:** 11 high (2 of them `high*`, capped to medium under the absence rule), 6 medium, 3 low.
**Prototype framework spread:** sklearn/pandas — MLV101, 102, 103, 602. PyTorch — everything else. MLV601 is framework-agnostic.

---

## 2. MLV000 — the diagnostics channel

Not a user rule and never rendered as a badge. `MLV000` is the code carried by `diagnostics[]` entries, which exist so that failures are *visible* rather than silent:

| `diagnostics[].kind` | Emitted when | Surfaced as |
|---|---|---|
| `parse_error` | `ast.parse` raised | Dismissible banner: *"3 files could not be parsed"*, expandable to filename + message, each clickable |
| `dynamic_scope` | A scope contains `exec`, `eval`, `getattr` on a call target, a star-import, or `**kwargs` forwarding | "Partial understanding" banner; confidence ×0.7 in that scope; `unknown` nodes rendered dashed |
| `rule_error` | A rule raised (never re-raised unless `--strict`) | Status bar: *"N analyzer notes"* |
| `truncated` | One of four caps was hit, and `scope` says which: `files` (discovery), `nodes` (`--max-nodes`), `rounds` (IR resolution), `dataflow` (an interprocedural chain). A consumer asking *"was the GRAPH capped?"* reads `scope == "nodes"` rather than the prose (CONTRACTS 11.59 A1) | Banner naming what was dropped |
| `notebook_skipped` | `.ipynb` found | Status bar: *"3 notebooks not analyzed"* — a silently skipped notebook is indistinguishable from a broken analyzer |
| `framework_suppressed` | **Two different statements, and the message prefix `--framework ` is the discriminator** (CONTRACTS 11.57 A3). Without it: the `negation_absent` gate fired and those rules RAN and were capped. With it: a host `--framework` filter meant those rules DID NOT RUN, and the message names the filter, the count and the detected frameworks | Chip: *"training loop handled by Lightning — 7 rules not applicable"*; the filter form is also a coverage row in the plugin's note block |
| `config_warning` | `.mlview.toml` tried to override a severity | Output channel line |

Exit code stays **0** for all of these.

---

## 3. Prototype rules — full detail

### MLV101 ★ · high · Preprocessing fitted before the train/test split
**Frameworks:** sklearn, pandas · **basePrior 0.95** · *the flagship leakage rule*

**Detection.** Find call sites whose resolved FQN carries the knowledge-table role `FIT` or `FIT_TRANSFORM` **and whose subject is a transformer** — the role alone is not enough, because `sklearn.base.BaseEstimator.fit` carries `FIT` and every estimator answers to it (ROB-10). `FIT_TRANSFORM` qualifies by definition; a bare `.fit()` qualifies only when the receiver's constructor resolves to a knowledge row in the `preprocess` stage (`sklearn.preprocessing.*`, `sklearn.decomposition.*`, `sklearn.impute.*`, `sklearn.feature_selection.*`, `sklearn.feature_extraction.*`), and never when it resolves to `CV_SEARCH` / `PIPELINE` / `ESTIMATOR` / `MODEL_FACTORY`. A receiver that resolves to nothing is not evidence of a transformer, so the rule stays silent. The primary argument's `ValueRef` must carry `RAW_DATA` or `FEATURES` but **not** `TRAIN_SPLIT`. Then walk forward through the SSA-lite chain in the same scope: does a later statement call a `SPLIT`-role FQN (`train_test_split`, `KFold.split`, `StratifiedKFold.split`, `random_split`) consuming a value **reachable from the fit's output or its input**? Reachability is by value identity, so both `X = scaler.fit_transform(X); … train_test_split(X, y)` and `Xs = scaler.fit_transform(X); … train_test_split(Xs, y)` fire. Primary `loc` at the fit site; `relatedLocs[role="split_site"]` at the split.

**False-positive notes (each is a `_good.py`).** (a) The split is on a *different* dataset — guarded two ways. Value identity through the SSA chain is preferred; where the match can only be made by dotted **name**, a name re-assigned between the fit and the split **from a value that does not derive from the fitted one** breaks the chain and the rule discloses the gap through `ctx.untraced` instead of firing (PUB-03). `X = scaler.fit_transform(X)` and `features = imputer.fit_transform(features)` continue the chain and still fire; two independent sections of one sphinx-gallery script or notebook that happen to reuse `X` do not. (a2) A cross-validator refits inside every fold: `GridSearchCV(...).fit(X, y)` and a refit-on-everything after a `KFold` loop are correct, and are excluded by the transformer test above (ROB-10 / PUB-02). (b) Unsupervised code with no test set — guarded by requiring a split site to exist at all. (c) The fitted value carries only `TARGET` (e.g. `LabelEncoder` on `y`), which is usually benign — de-rate to `medium` with confidence ×0.6. TARGET evidence may also come from the **column key**: a subscript whose literal key matches `(?i)^(label|labels|target|targets|y|class|classes|outcome|category)$` is reinforcing evidence of the same kind a variable name is, and carries the same de-rate — a pandas column never acquires the dataflow tag, which is why the commonest spelling of the case this note exists for used to keep full `high` (PUB-04). (d) The transformer is stateless (`FunctionTransformer` with no fitted state) — listed in `knowledge/sklearn.yaml:stateless_transformers` and skipped.

**Fix.** Split first, then `fit_transform` on train and `transform` on val/test — or put the transformer and estimator in `sklearn.pipeline.Pipeline` and fit the pipeline inside the split/CV.

---

### MLV102 · high · Transformer fitted on validation or test data
**Frameworks:** sklearn · **basePrior 0.97**

**Detection.** Call sites with role `FIT` / `FIT_TRANSFORM` / `PARTIAL_FIT` **on a transformer** whose primary argument's `ValueRef` carries `VAL_SPLIT` or `TEST_SPLIT`. Split tags are assigned at `train_test_split` by the known positional convention (`X_train, X_test, y_train, y_test`) and reinforced — never created — by `(?i)^(x|y)?_?(test|val|valid|eval|holdout)`. Fires regardless of statement order. **"On a transformer"** is the same test MLV101 has applied since ROB-10 (`_is_transformer_fit`): `fit_transform` qualifies by definition, a bare `.fit()` is attributed through the receiver's constructor, and a receiver resolving to `CV_SEARCH` / `PIPELINE` / `ESTIMATOR` / `MODEL_FACTORY` — or to nothing at all — does not.

**False-positive notes.** (a) Transductive / semi-supervised setups that intentionally fit on unlabeled test features — skipped when the module imports `sklearn.semi_supervised.*`; otherwise suppressible with the ignore comment, and this is documented in the rule doc. (b) A regex-only match (no dataflow tag) is emitted at confidence ×0.8, which usually lands it in `likely` rather than `certain`. (c) **An estimator refitted on the other half of a split is cross-validation, not a leak** (PUB-14): hand-rolled k-fold — `model.fit(X1, y1).predict(X2)` then `model.fit(X2, y2).predict(X1)` — scores each fit on the rows it never saw, and the transformer test in Detection is what keeps this rule out of it. Every `expected` MLV102 label in the labelled corpus is a `fit_transform` on a transformer.

**Fix.** Call `transform` (not `fit` / `fit_transform`) on validation and test data, using the transformer already fitted on train.

---

### MLV103 ★ · medium · Preprocessing done outside cross-validation
**Frameworks:** sklearn · **basePrior 0.85**

**Detection.** A `CV`-role call (`cross_val_score`, `cross_validate`, `GridSearchCV.fit`, `RandomizedSearchCV.fit`, `HalvingGridSearchCV.fit`) whose estimator argument resolves to a **bare estimator** rather than `sklearn.pipeline.Pipeline` / `make_pipeline`, **and** a `FIT_TRANSFORM`-role call earlier in the same function on a value that flows into the CV call's `X` argument.

**False-positive notes.** (a) Fold-invariant, stateless transforms — the `stateless_transformers` list is consulted and those are skipped. (b) If `MLV101` already fired on the same transformer at the same `loc`, `MLV103` is suppressed — never stack two findings for one root cause.

**Fix.** Wrap the transformer and estimator in a `Pipeline` and pass the pipeline to the CV call, so preprocessing is refit per fold.

---

### MLV110 ★ · medium · Training DataLoader does not shuffle
**Frameworks:** torch · **basePrior 0.85**

**Detection.** A `torch.utils.data.DataLoader(...)` construction whose `dataset` argument's `ValueRef` carries `TRAIN_SPLIT` (or whose assignment target matches `(?i)train_?(loader|dl)` — reinforcing only), with `shuffle` absent or the literal `False`, **and** no `sampler=` / `batch_sampler=` keyword. A loader also counts as a training loader if the `for` loop iterating it contains a `.backward()` call — and "the loop iterating it" follows one hop through a factory: when the construction is the single `return` of an in-workspace function, the **caller's** binding names it (vision-12). Without that hop the clause could only ever apply to a loader built and consumed in one scope.

**False-positive notes.** (a) `IterableDataset` — shuffle is illegal there; the dataset's resolved class base is checked and the rule is skipped. (b) A `DistributedSampler` or any `sampler=` — covered by the sampler check. (c) Intentional curriculum learning or sequential/time-series batching — confidence ×0.6 when the dataset class name or file signals sequence modelling. The inverse rule ("training loader shuffles when it should not") is deliberately **not** written; it would cost more precision than it buys.

**Fix.** Set `shuffle=True` on the training loader (or pass a shuffling `sampler`) so batches are not correlated with dataset order.

---

### MLV111 ★ · low · `shuffle=True` on a validation or test DataLoader
**Frameworks:** torch · **basePrior 0.90**

**Detection.** A `DataLoader(...)` whose `dataset` argument's `ValueRef` carries `VAL_SPLIT`/`TEST_SPLIT` (or whose target name matches `(?i)(val|valid|test|eval)_?(loader|dl)`, or whose dataset argument is a subscript with a literal split key — `split["test"]`, `encoded["validation"]` — both reinforcing only, both at the ×0.8 regex factor) with the literal `shuffle=True`. The key is evidence of exactly the kind a variable name is: it cannot create a tag, and `DataLoader(split["test"], shuffle=True)` bound to a variable merely called `loader` used to satisfy neither half (NLP-14).

**False-positive notes.** Deliberately shuffled evaluation for visualising random samples is legitimate; hence **low** severity and wording that says the cost is per-sample alignment and reproducible confusion matrices, not metric correctness.

**Fix.** Use `shuffle=False` for evaluation loaders so predictions stay aligned with dataset order.

---

### MLV112 ★ · medium · `DataLoader(num_workers>0)` without a `__main__` guard
**Frameworks:** torch · **basePrior 0.98** — *purely syntactic, essentially zero false positives, and a genuine footgun on this exact Windows machine*

**Detection.** A `DataLoader(...)` with `num_workers` resolving to an int literal > 0 (directly, or through a module-level constant binding). Then check the enclosing module for an `if __name__ == "__main__":` guard **and** that the loader's consuming loop is inside a function called from that guard rather than at module scope. Fire when the module has no guard, or the loader is constructed at module top level.

**False-positive notes.** POSIX-only projects using `fork` do not hit this. The message names Windows/macOS spawn semantics explicitly rather than asserting the code is universally wrong, and the rule is `medium`, not `high`.

**Fix.** Wrap the entrypoint in `if __name__ == "__main__": main()` — Windows and macOS use `spawn`, so worker processes re-import the module.

---

### MLV201 ★ · high\* · Missing `optimizer.zero_grad()` in the training step
**Frameworks:** torch · **basePrior 0.90** · *absence rule — capped to medium unless fully resolved and unwrapped*

**Detection.** Locate the batch loop: the innermost `for` whose iterable's `ValueRef` is tagged `LOADER` and whose body — transitively, following one level of module-local function calls — contains a `torch.Tensor.backward` call **and** an `OPT_STEP`-role call (`torch.optim.Optimizer.step`, `torch.amp.GradScaler.step`). Fire when no `ZERO_GRAD`-role call (`Optimizer.zero_grad`, `Module.zero_grad`, `self.optimizers().zero_grad()`) appears in that loop body, in the enclosing epoch loop body before the backward, or in a followed callee.

**False-positive notes.** (a) **Gradient accumulation** — a `zero_grad` guarded by `if step % N == 0` is found because the search descends into `If` bodies; a fixture covers it. (b) **Multi-optimizer GAN loops** — suppressed when `zero_grad` is called on a *different but resolved* optimizer in a multi-optimizer set. (c) **`LBFGS`** closure pattern — skipped by optimizer class. (d) **Framework wrappers** — the `negation_absent` gate drops this to `speculative` on Lightning / HF `Trainer` / `accelerate` / `ignite` / `fastai`, with the visible suppression chip.

**Rendering.** When it fires, the batch loop shows a **ghost node** — a dashed `zero_grad()  ·  missing` placeholder in its correct slot carrying the red marker. Showing the hole beats narrating it.

**Fix.** Call `optimizer.zero_grad(set_to_none=True)` at the top of each training step, before the forward pass.

---

### MLV202 · high\* · Gradients computed but `optimizer.step()` never called
**Frameworks:** torch · **basePrior 0.90** · *absence rule*

**Detection.** Mirror of MLV201: a `.backward()` call exists inside a confirmed batch loop, but no `OPT_STEP`-role call appears in that loop, the enclosing epoch loop, or a followed callee. Searches nested `If` bodies, so accumulation stepping every N batches does not fire.

**False-positive notes.** (a) Adversarial-example / input-optimization code that backprops to a leaf input rather than to model parameters — confidence ×0.5 when the `.backward()` target's graph traces to a value tagged `BATCH` with `requires_grad_`. (b) `accelerator.backward(loss)` and `scaler.step(optimizer)` both count as steps. (c) Framework gate as MLV201.

**Fix.** Call `optimizer.step()` after `loss.backward()` — or `scaler.step(optimizer); scaler.update()` under AMP. If you accumulate gradients, step every N batches.

---

### MLV203 · high · `optimizer.step()` called before `loss.backward()`
**Frameworks:** torch · **basePrior 0.95** — *ordering inside a single block is nearly unambiguous statically*

**Detection.** Within one loop body - **and one level of module-local helper calls, the same hop MLV201 and MLV202 take** - compare statement indices of the `OPT_STEP`-role call and the `.backward()` call on the same iteration path (same immediate parent block, no intervening loop). `block_id` and `stmt_index` are per-function, so two statements in different functions are never compared with each other and the claim stays a same-block claim. Before the hop, moving the identical three statements into the canonical `def train_step(model, crit, opt, x, y)` helper made the finding vanish with no diagnostic, which also made the rule structurally unreachable for RL and multi-optimizer code, where the update is always a function (DGRG2-02). Fire when `step_index < backward_index`. Also fire the variant `backward → zero_grad → step`, where the intervening `zero_grad` wipes the gradients that were just computed.

**False-positive notes.** Multi-optimizer GAN loops where `d_optimizer.step()` legitimately precedes `g_loss.backward()` — guarded by requiring the optimizer and the loss to be *linked* (the optimizer's `params` argument traces to the module that produced the loss's logits). When the link cannot be established, drop to `possible` confidence, which keeps it off the Problems panel.

**Fix.** Order the step as `zero_grad()` → forward → `loss.backward()` → (clip) → `optimizer.step()`.

---

### MLV204 · high · `.backward()` inside `torch.no_grad()` / `inference_mode()`
**Frameworks:** torch · **basePrior 0.97** — *a hard runtime error, essentially never intentional*

**Detection.** The scope pass marks every statement with `insideNoGrad`, set by `with torch.no_grad():` / `with torch.inference_mode():` statements and `@torch.no_grad()` decorators, and cleared by a nested `torch.enable_grad()`. Fire when a `.backward()` call, or an `OPT_STEP` call following one, has `insideNoGrad == True`.

**False-positive notes.** A nested `enable_grad()` re-enabling gradients is tracked as a negating context, so the correct `no_grad` → `enable_grad` → `backward` pattern does not fire.

**Fix.** Move the backward pass outside the `no_grad` block, or wrap only the parts that genuinely need no gradients.

---

### MLV205 ★ · medium · Loss accumulated without `.item()` / `.detach()`
**Frameworks:** torch · **basePrior 0.85**

**Detection.** An `AugAssign` (`total += x`) or `x = x + y` inside a loop, where the accumulated `ValueRef` carries `LOSS` (or any tensor tag), the accumulator is defined **outside the accumulating loop** — `running = 0.0` in the epoch loop with `running += loss` in the batch loop is the canonical placement and must fire, which the `_within` predicate had backwards (vision-06) — and the right-hand side is not wrapped in `.item()`, `.detach()` or `float(...)` and is not inside a `torch.no_grad()` scope. Also fires for `losses.append(loss)` on a list defined outside the loop.

**False-positive notes.** (a) Intentional multi-step loss accumulation for a single `backward()` — suppressed when `.backward()` is called on the accumulator itself, matched **syntactically** as well as by role, because an accumulator initialised `total = 0.0` never resolves to a tensor and so never earned the BACKWARD role. (b) A list of tensors later `torch.stack`ed and backwarded — same suppression. (c) A custom `nn.Module` loss that accumulates its terms and **returns** them: the caller back-propagates the returned value under another name in another scope, and this rule cannot see whether that caller detaches, so silence is the only defensible answer. The discriminator against `def train_one_epoch(...): running += loss; return running / n` is what the enclosing function does with the gradients — a function that itself calls `.backward()` or `.step()` **is** the training loop and keeps firing (vision-05). (d) The accumulated value is not a live tensor: the producer chain is followed up to three hops and a `.item()` / `.detach()` / `float(...)` / `math.*` hop, or a workspace callee annotated `-> float` / `-> int`, ends it (PUB-08). The terminator test is **value-directed**: the detaching call has to *be* the producer of the value being followed, not merely appear somewhere inside the statement - an `int(w)` in a comprehension two lines earlier used to declare a live CTC loss a Python number (VIS2-02). It also crosses the **return boundary**: when the producer is an in-workspace call with no `-> float` annotation, every `return` of that callee is reduced by the same test, so the `def train_epoch(...): total += loss.item(); return total / len(loader)` shape - every tutorial's epoch helper - is a float and not a tensor. Round 1 taught the return inference to carry LOSS across an arithmetic return, and that same inference then handed MLV205 a float wearing a LOSS tag, measured three times on the canonical PyTorch seq2seq tutorial (PUB2-04). Symmetrically, the call of an in-workspace `nn.Module` that registers **no** submodules and reduces a tensor in its body *is* a loss and earns the tag, so `DiceLoss` / `FocalLoss` / `JointsMSELoss` / YOLO's `ComputeLoss` stop silencing the rule with no diagnostic at all (VIS2-09). (e) The whole accumulation runs under `torch.no_grad()` / `inference_mode()` — no graph was recorded, so there is none to keep alive (INFRA-01). The message names the **call** rather than its receiver when the LOSS-tagged binding is a criterion module: "`total` accumulates the result of `self.classification(...)`", never "the tensor `self.classification`", which is an `nn.BCEWithLogitsLoss` instance and not a tensor at all (vision-16).

**Fix.** Accumulate scalars: `running_loss += loss.item()` (or `loss.detach()`), so the autograd graph is not retained across the epoch.

---

### MLV301 ★ · high\* · Evaluation loop without `model.eval()`
**Frameworks:** torch · **basePrior 0.85** · *absence rule*

**Detection.** Identify eval regions: (a) a `for` over a `LOADER`-tagged value whose body performs a model forward but contains no `.backward()` / `OPT_STEP`; or (b) a `FunctionDef` named `(?i)^(validate|evaluate|val|test|predict|inference)` whose body matches that shape **and carries positive evidence of evaluation** — it runs with gradients off, it computes a metric / prediction, or it calls `eval()`. The name selects the candidate; it may never be the evidence (iron law 2). Without that gate, `test(_|$)` in the name regex made every pytest case an eval region, and `vit-pytorch/tests/test_vit.py:4` and `stable-baselines3/tests/test_utils.py:389` were reported at high / 0.85 (PUB-05). A `test_*` function - or one carrying a `@pytest.*` decorator - in a file matching `test_*.py` / `*_test.py` / `*_tests.py` / `tests.py` / `test.py` / `conftest.py`, under a `tests/` directory, **or in any module that imports `pytest` / `unittest` / `hypothesis`**, is a pytest case and is excluded structurally. Round 1 tested one filename pattern, and a module literally called `tests.py` matched neither arm - four findings on rasbt/LLMs-from-scratch, at 0.85 and 0.68, told the reader to wrap a pytest case in `torch.no_grad()` (PUB2-03). The model receiver must also resolve to a **torch** model: this rule and MLV302 declare `frameworks=["torch"]`, and that declaration is now enforced at the receiver, so a `keras.Model` forward is never told to call `.eval()` (PUB-09). Fire when no `torch.nn.Module.eval()` call on the same `MODEL` `ValueRef` **dominates** the loop — searched in **three** places, because a region is not one function: the loop's own function, the callee the forward pass happens in, and one level up at the resolved call site. The search used to read only the module the forward is written in and ask only whether the call sat in the loop's function, so the TTA / adversarial shape (`tta_accuracy` → `tta_logits`, `robust_accuracy` → `fgsm`) had nine `model.eval()` calls in the workspace and an evidence row asserting "no torch.nn.Module.eval() dominates this region" (VIS2-13). The architecture probe reads an `nn.Sequential` / `ModuleList` / `ModuleDict` **subclass** as a model class, so the `ConvNormActivation` idiom no longer drops the finding from high / 0.85 to medium / 0.51 - below `mlview.minConfidence`, i.e. out of the Problems panel entirely (VIS2-11).

**Severity refinement — the guard that makes this rule trustworthy.** Only emit at the declared severity when the model actually contains train/eval-sensitive layers: `nn.Dropout*` or `nn.BatchNorm*` resolved in the model class body (`nn.LayerNorm` is **exempt** — it behaves identically in train and eval). If the architecture cannot be resolved, drop to `medium` with confidence ×0.7.

**False-positive notes.** (a) `eval()` called once in an outer setup function — mitigated by the one-level dominance search; if the model is a parameter of the eval function and `eval()` is called at the single resolved call site, suppress. (b) Framework gate (Lightning `validation_step`, HF `Trainer`) suppresses entirely. (c) A pytest case, and a Keras / tf model — see Detection. (d) The evaluation **answer** ranks an `eval_loop` unit and a metric above a bare `no_grad()` block, so a weight-copying `with torch.no_grad(): sd[k].copy_(...)` inside a `from_pretrained` loader can never be what the reader is sent to first (PUB-11).

**Rendering.** Fires a **ghost node** `model.eval()  ·  missing` at the head of the eval loop.

**Fix.** Call `model.eval()` before the validation loop and `model.train()` when returning to training.

---

### MLV302 ★ · medium · Evaluation loop not wrapped in `torch.no_grad()`
**Frameworks:** torch · **basePrior 0.85**

**Detection.** Same eval-region identification as MLV301. Fire when the region's `insideNoGrad` is `False` and the enclosing function carries no `@torch.no_grad()` / `@torch.inference_mode()` decorator.

**False-positive notes.** Evaluation that genuinely needs gradients — saliency maps, adversarial evaluation, influence functions — de-rated ×0.5 when the region contains `.backward()`, `torch.autograd.grad`, or `requires_grad_`, which effectively suppresses it. Severity is `medium`, not `high`: it wastes memory and can OOM, but it does not corrupt results.

**Fix.** Wrap the loop in `with torch.no_grad():` (or `torch.inference_mode():`) to avoid building the autograd graph.

---

### MLV401 ★ · high · Softmax / LogSoftmax applied before `CrossEntropyLoss`
**Frameworks:** torch · **basePrior 0.95**

**Detection.** The value passed as the first (input) argument to a `torch.nn.CrossEntropyLoss` instance call, or to `torch.nn.functional.cross_entropy`, is traced through the SSA chain. Fire if it reaches `torch.softmax` / `F.softmax` / `Tensor.softmax` / `F.log_softmax`, **or** the output of a model whose resolved `forward` returns an expression ending in `nn.Softmax` / `nn.LogSoftmax`, **or** whose final `nn.Sequential` element is one of those.

**False-positive notes.** (a) An intervening `log()` making it effectively log-softmax — the chain walker detects it and redirects to `MLV403` (later-tier) rather than firing here. (b) A softmax applied conditionally (`if self.return_probs:`) — confidence ×0.6 when the softmax sits inside an `If`. (c) A user class *named* `Softmax` that is not `nn.Softmax` — prevented by FQN resolution rather than name matching.

**Rendering.** Draws the marker on the `model → loss` **edge**, and the multi-location connector links the softmax site to the loss construction.

**Fix.** `CrossEntropyLoss` applies log-softmax internally — return raw logits from `forward`, and apply softmax only where you need probabilities for reporting.

---

### MLV402 · high · Sigmoid / BCE pairing is inconsistent
**Frameworks:** torch · **basePrior 0.95**

**Detection.** Two symmetric checks using the same final-op chain walk as MLV401.
`variant: "double_sigmoid"` — the loss resolves to `nn.BCEWithLogitsLoss` / `F.binary_cross_entropy_with_logits` **and** the producing chain ends in `torch.sigmoid` / `F.sigmoid` / `nn.Sigmoid`.
`variant: "missing_sigmoid"` — the loss resolves to `nn.BCELoss` / `F.binary_cross_entropy` **and** the producing chain does **not** reach a sigmoid.
Reported at the loss construction with a `relatedLocs[role="final_layer"]` at the model's last op.

**False-positive notes.** A custom module named `Sigmoid` that is not `nn.Sigmoid` — prevented by FQN resolution. An unresolvable producer drops the finding to `possible`. **The producer must reach the use**: the argument's binding is resolved against the store in effect at the loss call's own line, not the scope's last store, so `loss = self.loss_fcn(pred, true)` followed by `pred = torch.sigmoid(pred)` — the shape of yolov5's `BCEBlurWithLogitsLoss` and of every focal-loss implementation — is correct and silent. The old reading produced high / 0.95 / `certain` with a message whose own line numbers ran backwards ("its input comes from torch.sigmoid at m.py:17" for a use at m.py:16). The same guard applies to MLV401 (PUB-01).

**Fix.** Feed raw logits to `BCEWithLogitsLoss` (numerically stable) and remove the trailing `nn.Sigmoid()`; or feed sigmoid outputs to `BCELoss`. Not the mismatched pairing.

---

### MLV501 ★ · medium · Model moved to a device but batch tensors are not
**Frameworks:** torch · **basePrior 0.90**

**Detection.** Fire when (a) a `MODEL`-tagged value has a `.to(<device>)` / `.cuda()` call, and (b) inside the batch loop, the values flowing into the model call — the loop target names, including tuple-unpacked elements — have no `.to(...)` / `.cuda()` / `pin_memory`-with-`non_blocking` applied on any path before the forward, directly or in a followed helper. The inverse (batches moved, model not) fires under the same code with `variant: "model_not_moved"`.

**False-positive notes.** (a) The `Dataset.__getitem__` already returns device tensors — the resolved `__getitem__` is checked for `.to(` / `.cuda()`. (b) A custom `collate_fn` doing the move — resolved and checked. (c) Lightning / `accelerate` / HF `Trainer` handle placement — framework gate suppresses. (d) `device` resolves to the literal `'cpu'` — skipped. (e) **`variant: "model_not_moved"` searches the whole workspace**, not the finding's own module: `engine/trainer.py` moving the model and handing it to `evaluate()` in `engine/evaluator.py` is the canonical package layout, and a module-scoped search made the rule assert "the model is never moved" about a workspace whose own IR carries the move, at confidence 0.900 / `certain` (INFRA-02). A negative claim needs the whole workspace - **and needs the search to have been completable**: a `.to(...)` whose receiver the IR could not type is an unknown, not an absence, so it refutes the negative. With the model built by a dynamic factory the same document already declares (`importlib.import_module` + `getattr`), the workspace-wide search silently returned False and the rule stated the negative as fact at 0.900 / `certain`, twice, about a file whose line 161 is `model = build_model(...).to(device)` (INFRA-R2-10). (f) A batch **rebound from an expression that carries a move** counts as moved - `batch = {k: v.to(device) for k, v in batch.items()}` is what every HuggingFace tokenizer batch requires and what the HF course, `run_glue.py`-style loops and the accelerate examples all write, and the rule reported it at 0.900 / `certain` one line after a `.to(device)` - and so does a batch handed to a followed helper whose body moves it, which is what "directly or in a followed helper" above already promised (NLP2-03).

**Reporting.** One finding per *placement*, not per loop — the fix is the same line for every loop — but every other offending loop is named in `relatedLocs`, so a reader who fixes the reported one does not still crash on the next (DGRG-11).

**Fix.** Move each batch inside the loop: `x, y = x.to(device, non_blocking=True), y.to(device)`.

---

### MLV601 ★ · low · No random seed set anywhere
**Frameworks:** all · **basePrior 0.90** · *workspace-level, fires at most once* · *absence rule*

**Detection.** A confirmed training loop, or a `SPLIT`/model-fit call, exists **and** the workspace contains no call resolving to `random.seed`, `numpy.random.seed`, `numpy.random.default_rng`, `torch.manual_seed`, `torch.cuda.manual_seed_all`, `pytorch_lightning.seed_everything`, `lightning.seed_everything`, `transformers.set_seed`, `tensorflow.random.set_seed`, `tf.keras.utils.set_random_seed`, and **no** `random_state=` keyword anywhere. Attached to the primary entrypoint node (or the first train loop).

**False-positive notes.** (a) Seeding done in an imported `utils.py` — prevented by scanning the whole workspace, not just the entrypoint. (b) Deliberately stochastic ensembling — hence `low`. (c) Detected but partial seeding is `MLV603` (later tier), not this rule; the two never both fire.

**Fix.** Seed all sources at startup: `random.seed(s); np.random.seed(s); torch.manual_seed(s); torch.cuda.manual_seed_all(s)`.

---

### MLV602 ★ · low · Split / CV splitter without `random_state` or `generator`
**Frameworks:** sklearn, torch · **basePrior 0.95**

**Detection.** A `SPLIT`-role call (`train_test_split`, `KFold`, `StratifiedKFold`, `ShuffleSplit`, `torch.utils.data.random_split`) with `shuffle` not explicitly `False` and no `random_state=` (sklearn) / `generator=` (torch) keyword. One issue per call site.

**False-positive notes.** A global `np.random.seed` does make sklearn splits reproducible via the global RNG — so when `MLV601` is *satisfied*, this drops to `possible` confidence and the wording becomes "prefer an explicit `random_state` for locality" rather than "not reproducible".

**Fix.** Pass `random_state=42` (sklearn) or `generator=torch.Generator().manual_seed(42)` (torch), so the split is reproducible independently of global state.

---

### MLV701 · high · `nn.Module.__init__` does not call `super().__init__()`
**Frameworks:** torch, lightning · **basePrior 0.97** — *purely syntactic, always a bug*

**Detection.** For each `ClassDef` whose resolved base chain includes `torch.nn.Module`, `pytorch_lightning.LightningModule` / `lightning.LightningModule` / `lightning.pytorch.LightningModule`, or `pytorch_lightning.LightningDataModule` / `lightning.LightningDataModule` / `lightning.pytorch.LightningDataModule`, if it defines `__init__` and no statement in that body is a call to `super().__init__` or `<Base>.__init__(self, …)`, fire at the `def __init__` line with a `relatedLocs[role="definition"]` at the `class` line.

`LightningDataModule` is in that set for the same reason the others are: its `__init__` installs the hook bookkeeping Lightning needs, so skipping it makes `save_hyperparameters()` raise and the trainer's dataloader wiring misbehave — the same always-a-bug, purely syntactic defect (vision-13).

**False-positive notes.** Abstract intermediate bases that are never instantiated — suppressed when the class carries `@abstractmethod`-bearing members and is only subclassed within the workspace. A class whose base is an *in-workspace* module subclass whose own `__init__` chains correctly is still required to call `super()` — that is not a false positive.

**Fix.** Add `super().__init__()` as the first statement of `__init__`.

---

### MLV702 ★ · high · Submodules in a plain list/dict are never registered as parameters
**Frameworks:** torch · **basePrior 0.95** — *precise, syntactic, and silently ruins training*

**Detection.** Inside a class whose resolved bases include `nn.Module`, in `__init__`, find `self.<attr> = <List | Dict literal | comprehension>` where any element expression is a `Call` whose callee resolves under `torch.nn.` or to another in-workspace `nn.Module` subclass, and the literal is **not** wrapped in `nn.ModuleList` / `nn.ModuleDict` / `nn.Sequential` / `nn.ParameterList`.

**False-positive notes.** A list of *configs* or *ints* is not matched — the check is on the resolved callee of the elements, not on the container. A list built and then passed into `nn.Sequential(*blocks)` on a later line is detected by following the binding and suppressed.

**Fix.** Wrap in `nn.ModuleList([...])` or `nn.ModuleDict({...})` so the submodules are registered, get parameters, and move with `.to(device)`.

---

## 4. Later-tier rules — detection sketches

These are designed and specified but **not built in the prototype**. They are listed so the catalog is complete and so a follow-on agent can implement one without re-deriving it. Each still requires the two fixtures before it ships.

### Data & leakage
- **MLV104** *(high)* — Calls resolving to `imblearn.over_sampling.*.fit_resample` / `under_sampling.*` / `combine.*` where the input lacks `TRAIN_SPLIT` and a `SPLIT` call later consumes a value reachable from the resample output. Essentially no false positives — resampling before splitting duplicates rows across the boundary and is always wrong. *Fix: resample only the training partition, or use `imblearn.pipeline.Pipeline`.*
- **MLV105** *(medium)* — For a `TARGET` value created by `y = df['label']` / `df.pop('label')` / `df.label`, record the literal key `k`; fire when the `FEATURES` value is the whole frame, or a `df.drop(columns=[…])` whose literal list lacks `k`, or a `df[[…]]` whose list contains `k`. Only fires on literal keys; dynamic lists set `dynamic` and suppress. FP guards: `df` reassigned between the statements (SSA identity); autoregressive setups (×0.6 when the target name matches `(?i)(next|shift|lag)`).
- **MLV106** *(medium)* — `train_test_split` / `random_split` with `shuffle` absent or `True` where **two independent** temporal signals exist (`pd.to_datetime`, `parse_dates=`, `.sort_values` on a date-named column, a `DatetimeIndex`, or an import of `statsmodels`/`prophet`/`darts`). One signal only ⇒ ×0.6. Phrased as a question. **The splitter must be able to shuffle**: a `.split()` whose receiver resolves to an order-preserving cross-validator (`TimeSeriesSplit`, `GroupKFold`, `LeaveOneGroupOut`, `LeavePGroupsOut`, `LeaveOneOut`, `LeavePOut`, `PredefinedSplit`, or `KFold` / `StratifiedKFold` / `GroupShuffleSplit` constructed with `shuffle=False`, which is the default) is skipped — MLView told a scikit-learn example that `TimeSeriesSplit` "shuffles rows that look like a time series" and offered "use TimeSeriesSplit" as the fix (PUB-06). *Fix: `TimeSeriesSplit` or a chronological cut.*
- **MLV107** *(medium)* — A `TEST_SPLIT` value reaching `eval_set=` / `validation_data=`, the `X`/`y` of a `GridSearchCV`-family `.fit`, or an early-stopping comparison controlling a `torch.save` or `break`. Escalate confidence when a distinct `VAL_SPLIT` also exists.
- **MLV113** *(low)* — `DataLoader(drop_last=True)` on a `VAL_SPLIT`/`TEST_SPLIT` dataset: silently discards the final partial batch and biases metrics. Noted exception: fixed-batch-shape requirements (TPU, static graphs).
- **MLV114** *(medium)* — A `transforms.Compose([...])` / `albumentations.Compose` containing a `random_augmentation`-set FQN whose resulting value flows into a Dataset consumed by a `VAL_SPLIT`/`TEST_SPLIT` loader. The transform argument is read one hop further than a bare name: a `Call` to an in-workspace function or method whose single `return` is a `Compose(...)` is followed, so `ImageFolder(root, transform=eval_transform())` and the Lightning `transform=self.train_transform()` idiom are judged — before that, only a module-level *named* `Compose` passed by name in the same file was visible, which is one shape out of six (vision-07). The dataset construction may be an **in-workspace `Dataset` subclass** as well as a knowledge-table row: every OCR, detection, segmentation, re-identification and multi-task project loads through its own subclass, which made this rule structurally unreachable for all of them (VIS2-01). One pipeline is one finding however many evaluation loaders are served from it; the others are named in `relatedLocs`. FP guard: deliberate TTA — ×0.5 when the eval code averages over repeated passes or an identifier contains `tta`.
- **MLV115** *(high)* — A class whose resolved base chain includes `torch.utils.data.Dataset` and which (with inherited in-workspace bases) lacks `__getitem__` or `__len__`; `IterableDataset` checked for `__iter__` instead. Suppress for abstract bases only subclassed in-workspace.
- **MLV116** *(low)* — Imbalance evidence exists (`stratify=`, `value_counts()`/`Counter` on the target, an explicit class-count dict) with no handling (`class_weight=`, `pos_weight=`, `weight=` on the loss, `WeightedRandomSampler`, `imblearn`, focal loss). Advisory group, off by default.
- **MLV117** *(medium)* — `train_test_split` with no `stratify=`, fired only when a classification signal exists (`*Classifier`/`LogisticRegression`/`SVC`, `CrossEntropyLoss`/`BCELoss`, or `accuracy_score`/`f1_score`/`roc_auc_score`). **Deliberately later-tier**: it is the noisiest rule relative to its value and will fire on many correct scripts.
- **MLV118** *(low)* — `transforms.Compose` containing `ToTensor()` with no `Normalize` in the same Compose, for a `torchvision.datasets.*` / `ImageFolder` dataset.
- **MLV119** *(low)* — A string literal in an `data`- or `deliver`-stage node matching `^[A-Za-z]:[\\/]`, `^/(home|Users|mnt|data)/`, or a UNC `\\\\`.
- **MLV120** *(low, off by default)* — ≥ 3 numeric literals bound to hyperparameter slots (`lr=`, `batch_size=`, `epochs=`, `weight_decay=`, `dropout=`, `hidden_size=`) with no argparse / config dataclass / YAML source in the module. **Aggregated to one issue per file**, never one per literal. This is a taste rule and is in the `advisory` group.
- **MLV121** *(high, added by ANA-9)* — a `tensorflow.data.Dataset.shuffle(...)` that reaches a `take()` / `skip()` through the receiver chain — either fluently (`base.shuffle(n).take(k)`) or through a binding (`ds = base.shuffle(n)` then `ds.take(k)` / `ds.skip(k)`) — with no `reshuffle_each_iteration=False`. tf.data re-draws the buffer on every epoch by default, so the two halves swap rows every pass and the holdout stops existing: a **total** holdout failure, not a partial leak. Literal-only, essentially no false positives. One finding per `shuffle`, however many `take`/`skip` calls follow. **A holdout must be visible before the rule describes one: both `take` and `skip` have to reach the same shuffled receiver.** A lone `take` is a subsample - `train_ds.shuffle(n).batch(b).take(k)` caps how many batches a trial consumes - and a variable called `valid_ds` is a name, which iron law 2 forbids from creating a claim: that arm produced the only high-severity false positive in 260 runs over 37 public repositories (PUB2-01). FP guards: `reshuffle_each_iteration=False`; splitting first and shuffling only the training half afterwards; a `shuffle` → `batch` → `prefetch` chain with no holdout in it. **Hard sequencing note:** this is the ordering check `knowledge/tf_tbl.py` defers to when it refuses to give `take` / `skip` the `SPLIT` role. *Fix: pass `reshuffle_each_iteration=False`, or split before you shuffle.*

### Training loop
- **MLV206** *(high\*)* — A `LOSS`-tagged value created inside a confirmed batch loop with no `.backward()` reachable from it or from any value derived from it (arithmetic propagates the `LOSS` tag). Suppressed entirely when a Lightning `training_step` returns the loss. Distinct from MLV202: this is "loss never used", that is "gradients never applied".
- **MLV207** *(medium)* — A `SCHED_STEP` call whose receiver's constructor is in the epoch-based set (`StepLR`, `MultiStepLR`, `ExponentialLR`, `CosineAnnealingLR`, `ReduceLROnPlateau`) but whose enclosing loop is the **batch** loop; and the inverse for the per-batch set (`OneCycleLR`, `CyclicLR`, and the whole `transformers.optimization.get_*_schedule_with_warmup` family) stepped in the epoch loop. **The two sets are exhaustive and a class outside them is not judged.** `LambdaLR` and `PolynomialLR` were in the implementation's epoch set and never in this one, and neither belongs: a `LambdaLR` has no intrinsic cadence at all (the lambda receives whatever counter its owner steps, and `get_linear_schedule_with_warmup` *returns* one), and `PolynomialLR` is mmsegmentation's per-iteration `poly` policy. Both are removed (VIS2-04); the `transformers` family now carries knowledge rows, so `scheduler.step()` on one acquires the role at all (NLP2-08). Loop role comes from confirmed nesting, not names. The **constructor** is resolved through one hop in either direction when it is not local: a `scheduler = build_scheduler(...)` factory's single returned constructor, and a `scheduler` that arrives as a function parameter, taken from the resolved call sites and only when every site agrees — both are the shapes torchvision's own reference, timm, detectron2 and mmdet use, and neither was visible (vision-14). The **batch loop** may be one call hop down: `for epoch in range(N): train_one_epoch(...); scheduler.step()` is the decomposition every repository above one file uses, and the enclosure test was lexical, so a `OneCycleLR` that finishes its cycle in the first few epochs was never reported (VIS2-03); the evidence names the callee the batch loop was found in. A `.step()` written **after** the batch loop inside such a helper has no enclosing loop of its own and is read at the cadence of the epoch loop its caller sits in, when every call site agrees (NLP2-08). The `.step` name selects the candidate; the claim still rests entirely on the resolved constructor, and a candidate whose constructor does not resolve is dropped without a word. FP guard: `StepLR(step_size=len(loader)*k)` — detect `len(<loader>)` in the argument and suppress. Second variant: `ReduceLROnPlateau.step()` called with no metric argument.
- **MLV208** *(medium)* — With a `GradScaler` present, require `scaler.scale(loss).backward()`, `scaler.step(optimizer)`, `scaler.update()`. Sub-variants: a bare `loss.backward()` while a scaler exists; `step` without `update`; `optimizer.step()` instead of `scaler.step(optimizer)`; `clip_grad_norm_` without a preceding `scaler.unscale_(optimizer)`. FP guard: `GradScaler(enabled=False)`.
- **MLV209** *(medium)* — `clip_grad_norm_` / `clip_grad_value_` whose statement index in the batch loop is before `.backward()` or after `OPT_STEP`.
- **MLV210** *(low)* — The model class instantiates `nn.LSTM`/`nn.GRU`/`nn.RNN` and no clipping call appears in any train loop. FP guard: Lightning's `gradient_clip_val=` on the `Trainer`.
- **MLV211** *(medium)* — The `params` argument of a `torch.optim.*` constructor traces to a `MODEL` value that is later rebound to `nn.DataParallel(m)`, `DistributedDataParallel(m)`, `torch.compile(m)`, or a fresh construction. **`.to(device)` is explicitly excluded** — modern PyTorch preserves parameter identity across a standard CUDA move.
- **MLV212** *(medium)* — A loss constructed with the literal `reduction='none'` whose output has `.backward()` called without an intervening `.mean()` / `.sum()` / weighted-mean. A `gradient=` argument to `backward` is treated as intentional and suppresses.

### Evaluation
- **MLV303** *(medium)* — `Module.eval()` inside the epoch loop with no `Module.train()` on the same `ValueRef` afterwards on any path back into the training step. **Deliberately later-tier**: the flow-insensitive IR makes ordering-sensitive detection weaker, and the common correct pattern (`model.train()` at the top of the epoch loop, before eval) must be treated as restoring via the loop back-edge — which needs the order-aware pass to be right before this rule is trustworthy.
- **MLV304** *(medium)* — A confirmed training loop exists and the graph contains no `eval`-stage node anywhere in the workspace: no eval loop, no `sklearn.metrics.*`/`torchmetrics.*` outside the training step, no `validation_step`, no `Trainer(eval_…)`.
- **MLV305** *(medium)* — A metric call (`accuracy_score`, `f1_score`, `precision_score`, `recall_score`, `torchmetrics.functional.accuracy`) whose prediction argument carries `LOGITS`/`PROBS` and was not produced by `argmax` / `round` / a threshold comparison / `topk`. **Score-metrics carve-out**: `roc_auc_score`, `average_precision_score`, `log_loss` legitimately take scores and are in a separate list that never fires.
- **MLV306** *(low)* — `roc_auc_score` / `average_precision_score` whose score argument is bound to `<clf>.predict(...)` rather than `predict_proba(...)[:, 1]` / `decision_function(...)`.
- **MLV307** *(low)* — The only eval-stage metrics are accuracy-family **and** an imbalance signal exists. Hedged wording.
- **MLV308** *(low)* — Regression signal (`MSELoss`/`L1Loss`/`*Regressor`/`loss='mse'`) paired with `accuracy_score`/`f1_score`, or a classification signal paired with `mean_squared_error`/`r2_score`.

### Loss / activation
- **MLV403** *(high)* — The first argument of `nn.NLLLoss` / `F.nll_loss` does not trace to `F.log_softmax` / `nn.LogSoftmax` / a `softmax` followed by `log`. Follows one level of in-workspace function returns; an unresolvable producer drops to `possible`.
- **MLV404** *(medium)* — Cross-check the loss against the resolved final-layer output dimension: `MSELoss`/`L1Loss` with integer-class evidence on the target; `CrossEntropyLoss` with a final `nn.Linear(_, 1)`; `BCE*` with `out_features > 1` and no multilabel evidence. Skipped when the model is not resolvable. Hedged — ordinal regression is a legitimate exception.

### Device
- **MLV502** *(medium)* — A `.cuda()` call or a `torch.device('cuda')` / `'cuda:0'` literal with no `torch.cuda.is_available()` in the file and no device from a config/argparse. Skipped when an explicit `assert torch.cuda.is_available()` guard exists.
- **MLV503** *(low)* — `torch.zeros/ones/tensor/randn/arange/full` inside a confirmed batch loop with no `device=` and no chained `.to(device)`, in a file where a device value exists. ×0.6 when the value never reaches the model or the loss.

### Reproducibility
- **MLV603** *(low)* — At least one seed call exists, but the seeded set does not cover the libraries actually used for randomness (numpy used, `np.random.seed` absent; `random.*` used, `random.seed` absent). The CUDA sub-case is emitted as an informational note only, since `torch.manual_seed` seeds CUDA in current versions. Never fires together with MLV601.
- **MLV604** *(low)* — `DataLoader(num_workers>0)` with no `worker_init_fn=` and no `generator=`, in a file whose Dataset or transform path uses `random.*` / `np.random.*` (torch's own RNG is seeded per worker automatically, so torch-only randomness does not fire).
- **MLV605** *(low)* — A seed call exists **and** `torch.backends.cudnn.benchmark = True`, or both `cudnn.deterministic = True` and `use_deterministic_algorithms(True)` are absent while a determinism intent is signalled. Framed as a trade-off, not an error.

### Model & framework definition
- **MLV703** *(medium)* — `torch.nn.functional.dropout` / `dropout2d` / `alpha_dropout` called inside a method of an `nn.Module` subclass with no `training=` keyword. Purely syntactic and always a bug.
- **MLV705** *(high)* — A `keras.Model` / `Sequential` binding with a `.fit(...)` and no `.compile(...)` anywhere for that binding, and not produced by `keras.models.load_model`. The absence claim is **workspace-wide**, so it is refused the moment any `.compile(` exists whose receiver did not resolve: an unresolved receiver is not an absence (the same escape hatch MLV201 uses for `zero_grad`). Without it, the textbook `build_model()` / `compile_model(model)` split — one missing type annotation — produced high / 0.95 with the message *"no compile() call exists anywhere in this workspace"* about a workspace whose first function contains `model.compile(` (vision-01).
- **MLV706** *(medium)* — `.backward()` or an optimizer `.step()` inside `LightningModule.training_step`, with no `self.automatic_optimization = False` in `__init__`.
- **MLV707** *(medium)* — `LightningModule.training_step` with no `Return`, or whose every `Return` yields `None` or a dict without a `'loss'` key. **Skipped under manual optimization**, where returning nothing is the documented, correct shape: the class sets `self.automatic_optimization = False` anywhere (the predicate MLV706 already uses, so the two rules cannot disagree), or the `training_step` calls `self.manual_backward` / `self.toggle_optimizer` / `self.untoggle_optimizer`, which raise under automatic optimization and so can only mean the flag is off. `self.optimizers()` is deliberately **not** in that set — reaching for the optimizer while automatic optimization is still on is MLV706's defect, not evidence of manual mode (PUB-07).
- **MLV708** *(medium)* — `transformers.Trainer(...)` with `eval_dataset` absent, or `compute_metrics` absent while `eval_dataset` is present, or `TrainingArguments` setting neither `eval_strategy` nor `evaluation_strategy` to a non-`"no"` constant. *ANA-9 narrowed this to the conjunction — no `eval_dataset` **and** no evaluation strategy — because the middle clause on its own accuses every Trainer that is content with `eval_loss`.*
- **MLV709** *(high, added by ANA-7)* — a Keras layer carrying the string literal `activation="softmax"` in the **same module** as a loss constructed with `from_logits=True` from the categorical family (`CategoricalCrossentropy`, `SparseCategoricalCrossentropy`, `CategoricalFocalCrossentropy`); and the binary mirror, `activation="sigmoid"` against `BinaryCrossentropy` / `BinaryFocalCrossentropy`. The direct analogue of MLV401, with both operands literals, so it is cheap and high-confidence. Reported at the layer with `relatedLocs[role="final_layer"]` there and `role="construction"` at the loss. FP guards: `from_logits=False`, which is the correct partner for an activated head; a softmax head beside a `BinaryCrossentropy(from_logits=True)`, since the pairing is by activation family rather than by proximity; a loss built in another module, which is not paired at all. The walk from `compile()` back to the model follows one hop through a builder (`model = build_model()`) **and** one hop back through a parameter (`def compile_model(model): model.compile(...)`), taking the argument at the resolved call sites and only when every site agrees — the second hop is the split the Keras guide itself teaches, and without it the "same module" claim above was false: only a head and a loss written inside one function body were ever paired (vision-10). *Fix: return logits from the output layer, or build the loss with `from_logits=False` — never both.*
- **MLV711** *(medium, added by ANA-7)* — a `OneCycleLR` / `CyclicLR` / `get_*_schedule_with_warmup` constructed inside `LightningModule.configure_optimizers` with no `{"interval": "step"}` literal anywhere in that method. Lightning steps a returned scheduler once per **epoch** unless the returned config says otherwise, so a one-cycle schedule completes its whole cycle in the first few epochs and the rest of the run trains at the floor learning rate — silently, because nothing raises. FP guards: the correct `{"scheduler": sched, "interval": "step"}` return shape; an epoch-cadence scheduler, for which the Lightning default is already right. *Fix: return `{"optimizer": opt, "lr_scheduler": {"scheduler": sched, "interval": "step"}}`.*

### Checkpointing & serving
- **MLV801** *(medium)* — A confirmed epoch loop of non-trivial length and no `torch.save`, `state_dict()` write, `ModelCheckpoint`, `save_pretrained`, `joblib.dump`, or `Trainer(save_strategy=…)` anywhere. ×0.6 for notebook sources and for epoch counts under 5.
- **MLV802** *(medium)* — A comparison controlling a save (`if <metric> < best:` guarding `torch.save`) where the metric originates inside the *training* loop rather than the eval loop. Second variant `not_restored`: a best checkpoint is saved but no `load_state_dict`/`torch.load` occurs before the final evaluation. Suppressed when MLV304 already fired — one root cause, one finding.
- **MLV803** *(low)* — `torch.save(<MODEL>, path)` where the first argument is the module rather than a `state_dict()` call; and `torch.load(...)` with neither `map_location=` nor `weights_only=True` (an arbitrary-code-execution risk on untrusted checkpoints).

### Cross-stage / train–serve skew
- **MLV901** *(medium)* — Reachability diff in the `data`-edge subgraph: collect the `transform` nodes reachable from a *training* entrypoint (one whose subgraph contains a loss/optimizer/`fit` node) and from each *inference* entrypoint. Fire for every transform in the training set but not the inference set, anchored at the inference entrypoint. One of the highest-value findings in real production code.
- **MLV902** *(medium)* — All `from_pretrained(<str literal>)` calls grouped by training-reachable vs inference-reachable; fire when the tokenizer literal on the inference path differs from the one on the training path.
- **MLV903** *(low)* — BFS over `control` + `data` edges from every entrypoint (or module top-level when none exists). Any model / train_loop / eval_loop / transform / metric node not reached, not decorated (`@pytest.*`, `@app.*`, `@task`), and not underscore-prefixed, is emitted once at its `defLoc`.

---

## 5. Rule authoring checklist

A rule is not mergeable until every box is ticked. `tests/test_registry_complete.py` enforces boxes 1–6 mechanically.

1. Registered via `@rule(code=…, severity=…, base_prior=…, frameworks=[…], rule_version=1, tags=[…])`.
2. `tests/fixtures/rules/<CODE>_bad.py` exists, carries `# MLVIEW-EXPECT: <CODE> line=N`, and fires.
3. `tests/fixtures/rules/<CODE>_good.py` exists — encoding the *nearest false-positive trap*, not merely correct code — and does not fire.
4. Every "false-positive note" in this document is a distinct `_good.py` case.
5. `fixHint` is non-empty, is one actionable sentence, and names the actual API.
6. `docs/rules/<CODE>.md` exists (offline rule doc; the diagnostic `code.target` points at it).
7. `message` cites the concrete evidence — variable names and line numbers — not a generic restatement of the title.
8. `why` explains the consequence in one sentence, in ML terms ("reported test performance is optimistic"), not in linter terms.
9. Multi-location findings populate `relatedLocs` with a **named role** from the closed set: `split_site`, `fit_site`, `backward_site`, `optimizer_site`, `step_site`, `eval_loop`, `final_layer`, `definition`, `call_site`, `construction`.
10. `MLV000` is never emitted by a rule; rule exceptions are caught by the registry.
11. If the rule is an absence rule, it declares `absence=True`, which activates the severity cap and the `negation_absent` gate automatically.
12. It does not duplicate another rule's finding at the same `loc` — check the dedupe list.
