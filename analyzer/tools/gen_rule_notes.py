"""What each rule detects: the hand-written half of `docs/rules/<CODE>.md`.

Data only - `gen_rule_docs.py` renders it into the page every `Issue.docs`
field deep-links to. It is prose rather than generated output because the two
things a reader needs are the two things a `@rule` declaration cannot state:
what the gate actually keys on, and what the `_good.py` fixture proves is
**not** a finding. Anything missing falls back to the declaration text, so a
new rule still gets a usable page without touching this file.

Split in two along the line the rule codes already draw. This module holds the
**pipeline** families - data and leakage (MLV1xx) and training mechanics
(MLV2xx); `gen_rule_notes_eval.py` holds everything from MLV3xx on, the rules
about what a run concludes. `NOTES` is the union, and is the only name
`gen_rule_docs.py` imports.
"""

from __future__ import annotations

from typing import Dict

from gen_rule_notes_eval import EVAL_NOTES

__all__ = ["NOTES", "PIPELINE_NOTES"]


#: MLV1xx / MLV2xx: what the rule detects, and the traps its `_good.py` fixture
#: encodes so a reader can see what is deliberately *not* a finding.
PIPELINE_NOTES: Dict[str, Dict[str, object]] = {
    "MLV101": {
        "detects": "A `FIT` / `FIT_TRANSFORM` call whose primary argument carries "
                   "`RAW_DATA` or `FEATURES` but not `TRAIN_SPLIT`, followed by a "
                   "`SPLIT`-role call whose input is reachable from that value through "
                   "the SSA-lite chain, **written in the same scope as the fit**. "
                   "Shape-preserving pandas / numpy methods (`df.drop(columns=...)`, "
                   "`.copy()`, `.fillna()`, `.to_numpy()`, `arr.reshape()`) and the "
                   "module-level numpy constructors (`np.asarray`, `np.array`, "
                   "`np.concatenate`, `np.vstack`, `torch.from_numpy`) pass the tags "
                   "through, so the canonical pandas feature matrix is covered as well "
                   "as the numpy one.\n\n"
                   "In `--dataflow ip` a second shape is reached (R5): the fit and "
                   "the split are in **different functions**, and the value crossed "
                   "between them through a `return`. No name is matched across "
                   "scopes - the split's argument has to be bound by the very call "
                   "site that invoked the fit's function, at a returned position the "
                   "fitted value feeds - so the claim rests on the call graph rather "
                   "than on a spelling. It pays one `IP_HOP_WEIGHT` per hop, names "
                   "the chain in its evidence, and can never reach `certain`.",
        "avoids": ["A split on a *different* dataset - reachability is by value "
                   "identity through the binding chain, never by name equality.",
                   "A split written in **another function** that the call graph does "
                   "not join. Name reachability stays confined to one scope in both "
                   "modes, because a name means something else in a foreign scope; "
                   "only the `return`-carried shape above crosses, and only in `ip`. "
                   "A leak whose two halves are joined by nothing the analyzer can "
                   "see is still **not reported** - the honest cost of never "
                   "reporting a leak that is not there.",
                   "Unsupervised code with no test set - a split site must exist.",
                   "A stateless transformer (`FunctionTransformer`, `Normalizer`) - "
                   "listed in `knowledge/sklearn.yaml:stateless_transformers`.",
                   "A `LabelEncoder` on `y` alone is de-rated: it carries only `TARGET`."],
    },
    "MLV102": {
        "detects": "A `FIT` / `FIT_TRANSFORM` call whose primary argument carries "
                   "`VAL_SPLIT` or `TEST_SPLIT`. Statement order does not matter.\n\n"
                   "In `--dataflow ip` the rows may also be a **fold** rather than a "
                   "named split (R5): `scaler.fit_transform(features[test_idx])`, "
                   "where `test_idx` is position **1** of the tuple a scikit-learn "
                   "cross-validator yields and the `for` header iterating it is the "
                   "very `SPLIT` call the index came from. Position 1 is the held-out "
                   "half by the splitter protocol, so the fact lives in the index "
                   "rather than in a tag; every step has to hold, and the finding "
                   "pays a projection hop.",
        "avoids": ["Transductive / semi-supervised code - skipped when the module "
                   "imports `sklearn.semi_supervised.*`.",
                   "A stateless transformer learns nothing, so re-fitting it on the "
                   "test split is harmless and is skipped.",
                   "A tag that came from the naming convention alone is evidence at "
                   "weight 0.8, which lands the finding in `likely` rather than "
                   "`certain`."],
    },
    "MLV103": {
        "detects": "A `CV`-role call (or `GridSearchCV.fit`) whose estimator argument "
                   "is a bare estimator rather than a `Pipeline`, together with a "
                   "`FIT_TRANSFORM` earlier in the same function whose output flows "
                   "into the CV call's `X`.\n\n"
                   "In `--dataflow ip` the fit may be one `def` away (R5): the CV's "
                   "`X` is resolved to the workspace call that produced it, the "
                   "callee's `return` is read **at the tuple position the caller "
                   "unpacked**, and a non-stateless `fit_transform` whose output "
                   "reaches that returned value is the fit whose statistics every "
                   "fold shares. A returned *call* stands for the names it is written "
                   "on, so `return scaler.fit_transform(frame)` reads the same as the "
                   "two-statement spelling. When the caller's binding does not say "
                   "which position it unpacked, only a returned value of the same "
                   "name is accepted - a helper that hands back five values does not "
                   "match on all five.",
        "avoids": ["A `Pipeline` / `make_pipeline` estimator - the transform is refit "
                   "per fold, which is the correct answer.",
                   "An estimator that cannot be resolved at all - the rule stays quiet "
                   "rather than guessing.",
                   "Stateless transformers, which are fold-invariant.",
                   "A transformer MLV101 already reported at the same line: one root "
                   "cause never yields two findings."],
    },
    "MLV106": {
        "detects": "A `train_test_split` / `random_split` that does not pass "
                   "`shuffle=False`, in a module carrying **two or more independent** "
                   "temporal signals: `pd.to_datetime`, `parse_dates=`, a "
                   "`sort_values` on a date-named column, `.shift` / `.rolling` / "
                   "`.resample`, a `DatetimeIndex`, or an import of statsmodels / "
                   "prophet / darts / sktime.",
        "avoids": ["`shuffle=False`, which is how a chronological cut is spelled.",
                   "A single temporal signal: the catalog allowed one at x0.6, and "
                   "this build requires two, because one date column is a "
                   "coincidence in any dataset.",
                   "An **order-preserving splitter**: `TimeSeriesSplit`, "
                   "`GroupKFold`, `LeaveOneGroupOut`, `LeavePGroupsOut`, "
                   "`LeaveOneOut`, `LeavePOut`, `PredefinedSplit`, and `KFold` / "
                   "`StratifiedKFold` / `GroupShuffleSplit` built with "
                   "`shuffle=False` (the default). MLView told a scikit-learn "
                   "example that `TimeSeriesSplit` \"shuffles rows that look like "
                   "a time series\" and offered \"use TimeSeriesSplit\" as the fix "
                   "(PUB-06)."],
        "cannot": "**This rule is deliberately quiet by default, and that is a "
                  "calibration, not an accident.** The two-signal case - "
                  "`parse_dates=` plus a `sort_values` on a date-named column - is "
                  "scored `0.70 x 0.8 = 0.560`, which is below `mlview.minConfidence` "
                  "0.6: it is emitted, it reaches the canvas and the MCP digests, and "
                  "it does **not** reach the VS Code Problems panel. Only a "
                  "three-signal series clears the floor at 0.700. The reason is "
                  "TAB-11: the same two signals appear in correct cross-sectional "
                  "code - a churn snapshot read with `parse_dates=[\"signup_date\"]`, "
                  "sorted by it, where the date is used to compute a *tenure feature* "
                  "and the label is measured at one fixed moment - and a random "
                  "stratified split there is the right design. The finding is phrased "
                  "as a question for the same reason.",
    },
    "MLV110": {
        "detects": "A `DataLoader(...)` whose dataset carries `TRAIN_SPLIT` (or whose "
                   "loop calls `backward()`, or whose variable matches the training "
                   "naming convention) with `shuffle` absent or `False` and no "
                   "`sampler=` / `batch_sampler=`.",
        "avoids": ["`IterableDataset`, where `shuffle=True` is illegal - the dataset's "
                   "resolved base is checked.",
                   "A `DistributedSampler` or any other `sampler=`, which owns the "
                   "shuffling.",
                   "Sequence / time-series modelling, where ordered batches can be "
                   "deliberate - de-rated when the names hint at it.",
                   "A name-only match is evidence at weight 0.8."],
    },
    "MLV111": {
        "detects": "A `DataLoader(...)` with the literal `shuffle=True` whose dataset "
                   "carries `VAL_SPLIT` / `TEST_SPLIT`, or whose variable matches the "
                   "evaluation naming convention.",
        "avoids": ["Training loaders, which *should* shuffle.",
                   "This is deliberately `low`: shuffled evaluation is legitimate when "
                   "you are sampling examples to look at. The cost is per-sample "
                   "alignment and reproducible confusion matrices, not correctness."],
    },
    "MLV112": {
        "detects": "A `DataLoader` with `num_workers` resolving to an int literal "
                   "greater than zero (directly, or through a module constant, "
                   "including one imported from another workspace module) that is "
                   "**constructed while the module is imported**.",
        "avoids": ["A loader built inside a function that only the entrypoint calls: "
                   "the module is import-safe, so spawn can re-import it.",
                   "A loader inside the `if __name__ == \"__main__\"` guard.",
                   "`num_workers=0`, and POSIX-only projects using `fork` are named "
                   "explicitly in the message rather than accused."],
    },
    "MLV114": {
        "detects": "A `transforms.Compose` / `albumentations.Compose` containing an "
                   "`AUGMENT`-role element, named as the `transform=` of a dataset "
                   "construction whose value is served **directly** by an evaluation "
                   "`DataLoader`.",
        "avoids": ["A training pipeline and an evaluation pipeline in one module, "
                   "correctly kept apart.",
                   "A deterministic `Resize` / `ToTensor` / `Normalize` pipeline."],
        "cannot": "An augmented dataset that is later `random_split` into a training "
                  "and a validation half. The analyzer cannot tell which half "
                  "inherits what, so it says nothing rather than guessing - this is "
                  "the shape `samples/vision_pipeline` writes. The evaluation loader "
                  "is identified as a `torch.utils.data.DataLoader`, which is why the "
                  "rule declares torch rather than albumentations: an "
                  "`albumentations.Compose` is read, but only where a torch loader "
                  "serves it.",
    },
    "MLV121": {
        "detects": "A `tf.data` `Dataset.shuffle(...)` reaching a **holdout** through "
                   "the receiver chain, with no `reshuffle_each_iteration=False`. A "
                   "holdout is the pair - the same shuffled receiver reaching both a "
                   "`take()` and a `skip()` - or a subset whose result is bound to an "
                   "evaluation name (`val_ds`, `test_ds`, `holdout`, ...).",
        "avoids": ["`shuffle(n, reshuffle_each_iteration=False)`, which pins the "
                   "permutation so the two halves are stable.",
                   "Splitting first and shuffling only the training half afterwards.",
                   "A `shuffle` -> `batch` -> `prefetch` chain with no holdout in it.",
                   "`for images, labels in train_ds.take(1)` - a peek at one batch, "
                   "which used to be reported as a leaking train/val split at severity "
                   "high, confidence 0.95, with a message asserting two halves that do "
                   "not exist.",
                   "A debug subset (`debug_rows = shuffled.take(8)`) with no "
                   "complementary `skip` and no evaluation name."],
        "cannot": "A dataset rebuilt inside a helper. The chain is followed through at "
                  "most eight links and only through bindings that resolve. A holdout "
                  "whose two halves come off *different* `shuffle` calls is judged only "
                  "when the subset carries an evaluation name.",
    },
    "MLV201": {
        "detects": "A batch loop - the innermost `for` over a `LOADER`-tagged value - "
                   "whose body contains a `backward()` and an `OPT_STEP`, with no "
                   "`ZERO_GRAD` in that loop, any enclosing loop, or a followed callee.",
        "avoids": ["Gradient accumulation: a `zero_grad` under `if step % N == 0` is "
                   "found because the search descends into `If` bodies.",
                   "`LBFGS`, whose closure pattern zeroes gradients itself.",
                   "An optimizer that comes back from a factory "
                   "(`opt = build_optimizer(model, cfg)`, or one position of a "
                   "`(optimizer, scheduler)` tuple): one level of return-type "
                   "inference types the binding, so `opt.zero_grad()` resolves.",
                   "A `zero_grad()` whose receiver the IR could not type at all - an "
                   "unresolved call is not an absence, so the rule stays quiet.",
                   "Lightning / HF `Trainer` / `accelerate` / `ignite` / `fastai` **in "
                   "the finding's own module or one it imports**: the "
                   "`negation_absent` gate multiplies the confidence by 0.4 and a chip "
                   "explains why. A wrapper in an unrelated file does not gate it."],
        "cannot": "A full-batch loop not driven by a DataLoader - "
                  "`for epoch in range(20):` over tensors already in memory, which is "
                  "what a tabular script and a notebook write. The batch loop is the "
                  "rule's anchor, so the shape is not judged; it is never silent, "
                  "though - a `backward()` and an optimizer `step()` in a loop nothing "
                  "confirmed raise an `untagged_dataflow` coverage note naming the "
                  "line.",
        "ghost": "the batch loop shows a dashed `zero_grad() · missing` placeholder in "
                 "the slot where the call belongs",
    },
    "MLV202": {
        "detects": "The mirror of MLV201: a `backward()` inside a confirmed batch loop "
                   "with no `OPT_STEP` in that loop, an enclosing loop, or a followed "
                   "callee.",
        "avoids": ["`scaler.step(optimizer)` under AMP, which resolves to the same "
                   "`OPT_STEP` role.",
                   "A step under an accumulation guard - `If` bodies are searched.",
                   "Adversarial / input-optimization code that backprops to the batch: "
                   "skipped when the loop touches `requires_grad_`.",
                   "An optimizer built by a factory, and an unresolved `.step()` "
                   "receiver, exactly as MLV201.",
                   "The framework gate, as MLV201."],
        "ghost": "the batch loop shows a dashed `optimizer.step() · missing` placeholder",
    },
    "MLV203": {
        "detects": "Within one block of a batch loop, an `OPT_STEP` whose statement "
                   "index is lower than the `backward()`'s - or the variant where a "
                   "`zero_grad` sits between the backward and the step and wipes the "
                   "gradients that were just computed.",
        "avoids": ["Multi-optimizer GAN loops, where `d_optimizer.step()` legitimately "
                   "precedes `g_loss.backward()`: the rule requires exactly one "
                   "optimizer and one loss in the loop, so the two are linked.",
                   "Calls in different blocks, which are not on one iteration path."],
    },
    "MLV204": {
        "detects": "A `backward()` whose statement is marked `insideNoGrad` by the "
                   "scope pass - set by `with torch.no_grad():`, "
                   "`with torch.inference_mode():` and `@torch.no_grad()` decorators.",
        "avoids": ["A nested `torch.enable_grad()`, which the scope pass tracks as a "
                   "negating context, so `no_grad -> enable_grad -> backward` is "
                   "silent."],
    },
    "MLV205": {
        "detects": "`total += loss`, `total = total + loss` or `losses.append(loss)` "
                   "inside a loop, where the accumulated value carries `LOSS`, the "
                   "accumulator is created outside the loop, and the right-hand side "
                   "is not wrapped in `.item()`, `.detach()` or `float()`.",
        "avoids": ["Deliberate multi-step accumulation for a single `backward()`: "
                   "suppressed when the accumulator itself is back-propagated.",
                   "A list of tensors later `torch.stack`ed and backwarded - the same "
                   "suppression follows the stack.",
                   "An accumulator created *inside* the loop, which is reset each pass.",
                   "A loop inside `torch.no_grad()` or under a `@torch.no_grad()` "
                   "decorator (R18): there is no autograd graph behind a validation "
                   "total, so nothing is kept alive.",
                   "A running total the program then **uses** as a live tensor - "
                   "`style_loss += mse(...)`, `total = content + style_loss`, "
                   "`total.backward()`. One arithmetic step, in the accumulator's own "
                   "scope; `.item()` there would detach the term from training."],
    },
    "MLV207": {
        "detects": "A `scheduler.step()` whose receiver's constructor is in the epoch "
                   "set (`StepLR`, `MultiStepLR`, `ExponentialLR`, "
                   "`CosineAnnealingLR`, `ReduceLROnPlateau`) but which sits in a "
                   "confirmed **batch** loop, or a per-batch scheduler (`OneCycleLR`, "
                   "`CyclicLR`) stepped in an epoch loop that encloses a batch loop. "
                   "Plus `ReduceLROnPlateau.step()` called with no metric.",
        "avoids": ["`StepLR(step_size=len(loader) * k)`, which really does count "
                   "batches - a `len(...)` in the constructor's arguments suppresses "
                   "the finding.",
                   "A scheduler whose constructor could not be resolved.",
                   "A loop whose kind the IR did not confirm."],
    },
    "MLV208": {
        "detects": "With a `GradScaler` governing the loop's function: a `backward()` "
                   "not wrapped in `scaler.scale(...)`; an `optimizer.step()` instead "
                   "of `scaler.step(optimizer)`; a `scaler.step` with no "
                   "`scaler.update()`; or a `clip_grad_*` with no preceding "
                   "`scaler.unscale_()`.",
        "avoids": ["`GradScaler(enabled=False)`, which is a no-op.",
                   "The correct accumulation protocol, where scale, unscale_, clip, "
                   "step and update are spread across two blocks of one loop.",
                   "A loop with no scaler at all - proximity first, then identity: "
                   "a `scaler.step(...)` in this very loop whose receiver resolves to "
                   "a `GradScaler(...)` built elsewhere (a `make_state()` factory, a "
                   "parameter dict) is that scaler, whatever function built it. The "
                   "first arm guesses from position; the second one knows."],
        "cannot": "A non-literal `GradScaler(enabled=cfg.amp)`. That **de-rates** the "
                  "finding to evidence weight 0.6 - it never suppresses it and never "
                  "escalates it.",
    },
    "MLV209": {
        "detects": "A `clip_grad_norm_` / `clip_grad_value_` whose statement index in "
                   "**one block** of a confirmed batch loop is lower than the "
                   "`backward()`'s, or higher than the optimizer step's.",
        "avoids": ["The correct order in the same block: backward, clip, step.",
                   "Calls in different blocks - a clip inside an accumulation `if` is "
                   "never compared with a backward outside it, because there is no "
                   "single iteration path through them."],
    },
}

#: Every rule's notes, in one mapping. The two halves share no code - a rule
#: belongs to exactly one family - so the merge can never silently drop one.
NOTES: Dict[str, Dict[str, object]] = dict(PIPELINE_NOTES)
NOTES.update(EVAL_NOTES)
assert len(NOTES) == len(PIPELINE_NOTES) + len(EVAL_NOTES), \
    "a rule code appears in both halves of the notes"
