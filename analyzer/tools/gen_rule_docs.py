"""Generate `docs/rules/<CODE>.md` (and its index) from the rule registry.

    PYTHONUTF8=1 python analyzer/tools/gen_rule_docs.py [--check] [--out DIR]

Every `Issue.docs` field points at `docs/rules/<CODE>.md`, so these pages are
the offline documentation both hosts deep-link to. They are generated, never
hand-edited: the title, severity, frameworks, prior, tags, fix hint and the
bad/good examples all come from the `@rule` declaration and the two fixtures,
so a page can never drift from the rule it documents.

`--check` exits 1 when anything on disk differs, which is what CI wants.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(REPO, "analyzer", "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mlview.rules.registry import RuleSpec, all_rules  # noqa: E402

FIXTURES = os.path.join(REPO, "analyzer", "tests", "fixtures", "rules")
DOCS = os.path.join(REPO, "docs", "rules")

#: Hand-written context per rule: the detection summary and the traps the
#: `_good.py` fixture encodes. Keyed by code; anything missing falls back to
#: the declaration text, so a new rule still gets a usable page.
NOTES: Dict[str, Dict[str, object]] = {
    "MLV101": {
        "detects": "A `FIT` / `FIT_TRANSFORM` call whose primary argument carries "
                   "`RAW_DATA` or `FEATURES` but not `TRAIN_SPLIT`, followed by a "
                   "`SPLIT`-role call whose input is reachable from that value through "
                   "the SSA-lite chain. Shape-preserving pandas / numpy methods "
                   "(`df.drop(columns=...)`, `.copy()`, `.fillna()`, `.to_numpy()`, "
                   "`arr.reshape()`) pass the tags through, so the canonical pandas "
                   "feature matrix is covered as well as the numpy one.",
        "avoids": ["A split on a *different* dataset - reachability is by value "
                   "identity through the binding chain, never by name equality.",
                   "Unsupervised code with no test set - a split site must exist.",
                   "A stateless transformer (`FunctionTransformer`, `Normalizer`) - "
                   "listed in `knowledge/sklearn.yaml:stateless_transformers`.",
                   "A `LabelEncoder` on `y` alone is de-rated: it carries only `TARGET`."],
    },
    "MLV102": {
        "detects": "A `FIT` / `FIT_TRANSFORM` call whose primary argument carries "
                   "`VAL_SPLIT` or `TEST_SPLIT`. Statement order does not matter.",
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
                   "into the CV call's `X`.",
        "avoids": ["A `Pipeline` / `make_pipeline` estimator - the transform is refit "
                   "per fold, which is the correct answer.",
                   "An estimator that cannot be resolved at all - the rule stays quiet "
                   "rather than guessing.",
                   "Stateless transformers, which are fold-invariant.",
                   "A transformer MLV101 already reported at the same line: one root "
                   "cause never yields two findings."],
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
                   "An accumulator created *inside* the loop, which is reset each pass."],
    },
    "MLV301": {
        "detects": "An eval region - a loop over a loader, or an evaluation-named "
                   "function, that runs a model forward and never calls `backward()` "
                   "or `optimizer.step()` - with no `torch.nn.Module.eval()` "
                   "dominating it, searched in the enclosing function and one level up "
                   "at the resolved call site. The forward pass counts wherever it "
                   "sits in the body, including nested inside a compound expression "
                   "such as `hits += (model(x).argmax(1) == y).sum().item()`.",
        "avoids": ["`eval()` called in the caller rather than in the eval helper - the "
                   "one-level dominance search finds it.",
                   "A loop that only accumulates a loss for one backward per epoch: a "
                   "region also needs positive evidence of evaluation (a no-grad "
                   "context, an evaluation-shaped name, a metric call, or a held-out "
                   "loader).",
                   "Lightning `validation_step` / HF `Trainer` in this module or one "
                   "it imports: the framework gate multiplies the confidence by 0.4, "
                   "dropping the finding to `speculative` (off the Problems panel, "
                   "behind the canvas toggle) rather than deleting it.",
                   "A model with no `Dropout` / `BatchNorm` - `LayerNorm` is exempt "
                   "because it behaves identically in both modes - is reported at "
                   "`medium`, as is a model whose architecture could not be resolved. "
                   "`model = Net().to(device)` keeps its class through the chained "
                   "identity-preserving call, and a bare `nn.Sequential(...)` is "
                   "classified from its resolved element FQNs, so neither is capped "
                   "for an architecture that is in fact known."],
        "ghost": "the eval loop shows a dashed `model.eval() · missing` placeholder at "
                 "its head",
    },
    "MLV302": {
        "detects": "The same eval region as MLV301 - including the one-line "
                   "accumulator form, where the forward pass is nested inside a "
                   "comparison inside a call chain - when it is not inside a "
                   "`torch.no_grad()` / `torch.inference_mode()` context and the "
                   "enclosing function carries no such decorator.",
        "avoids": ["An `@torch.no_grad()` or `@torch.inference_mode()` decorator, and "
                   "any enclosing `with` block.",
                   "Evaluation that genuinely needs gradients - saliency maps, "
                   "adversarial evaluation, influence functions - detected through "
                   "`requires_grad_` / `torch.autograd.*` and skipped.",
                   "The framework gate, as MLV301 - a de-rating, not a deletion.",
                   "This is `medium`, not `high`: it wastes memory and can OOM, but it "
                   "does not corrupt results."],
    },
    "MLV401": {
        "detects": "The value passed as the first argument to a `CrossEntropyLoss` "
                   "instance or to `F.cross_entropy`, traced back through the SSA "
                   "chain, reaches a softmax / log-softmax - directly, through a "
                   "model whose `forward` returns one, or through the last element of "
                   "its final `nn.Sequential` - for a bare "
                   "`net = nn.Sequential(..., nn.Softmax(dim=1))` binding as well as "
                   "for a Sequential stored on an attribute of an `nn.Module`.",
        "avoids": ["A user class merely *named* `Softmax`: matching is on canonical "
                   "FQNs resolved through the import table, never on the attribute "
                   "name.",
                   "A softmax applied under an `if`, which is de-rated.",
                   "Softmax computed elsewhere for reporting, which never reaches the "
                   "loss input."],
        "rendering": "the marker is drawn on the `model -> loss` **edge**, and the "
                     "multi-location connector links the softmax site to the loss.",
    },
    "MLV402": {
        "detects": "Two symmetric checks over the same final-op chain. "
                   "`double_sigmoid`: the loss is `BCEWithLogitsLoss` / "
                   "`binary_cross_entropy_with_logits` and the chain ends in a sigmoid. "
                   "`missing_sigmoid`: the loss is `BCELoss` / "
                   "`binary_cross_entropy` and the resolved chain ends in something "
                   "that is not.",
        "avoids": ["A user class named `Sigmoid` that is not `nn.Sigmoid` - FQN "
                   "resolution again.",
                   "An unresolvable producer: the rule stays quiet rather than "
                   "guessing which half applies."],
    },
    "MLV501": {
        "detects": "Two symmetric halves, reported with a `variant` tag. "
                   "`batch_not_moved`: a `MODEL`-tagged value has a `.to(device)` / "
                   "`.cuda()`, while the loop targets that flow into the forward pass "
                   "are never moved on any path before it. `model_not_moved`: the "
                   "batch *is* moved and no `nn.Module` in that module ever is.",
        "avoids": ["A `Dataset.__getitem__` that already returns device tensors - the "
                   "resolved class is checked.",
                   "A custom `collate_fn` that does the move - resolved and checked.",
                   "`device` resolving to the literal `'cpu'` - on both halves.",
                   "A model built by a factory: `build_model(cfg).to(device)` is "
                   "recognised as a move through one level of return-type inference.",
                   "Lightning / `accelerate` / HF `Trainer` in this module or one it "
                   "imports, which handle placement - a de-rating to `speculative`, "
                   "not a deletion.",
                   "One finding per placement, not one per loop.",
                   "The `model_not_moved` half is deliberately strict - it needs an "
                   "explicit batch move, a receiver that really resolves to a network, "
                   "*and* no model move in the same module - so a model moved in "
                   "another file is never mistaken for a missing one, and the cited "
                   "move site is always inside the anchor's own function.",
                   "A network from a model zoo the knowledge tables do not carry "
                   "(`timm.create_model`, an in-workspace import that did not "
                   "resolve): the only FORWARD call left in the loop is then "
                   "`criterion(...)`, because a loss module is an `nn.Module` too. "
                   "Loss receivers are dropped rather than fallen back to - no model "
                   "resolved means no finding."],
    },
    "MLV601": {
        "detects": "A confirmed training loop, or a `SPLIT` / fit call, exists and the "
                   "**whole workspace** contains no `torch.manual_seed`, "
                   "`numpy.random.seed`, `random.seed`, `seed_everything`, `set_seed` "
                   "- and no `random_state=` / `generator=` keyword anywhere.",
        "avoids": ["Seeding done in an imported `utils.py`: the check is workspace-wide, "
                   "not per file.",
                   "A workspace with no ML framework at all, where a `for i in "
                   "range(10)` is just a loop.",
                   "Fires at most once, on the **ranked** primary entrypoint "
                   "(`workspace.entrypoints[0]`) or, when that module has no "
                   "module-scope block, on its training loop - never on whichever "
                   "file happens to sort first.",
                   "Deliberately stochastic ensembling - hence `low`."],
    },
    "MLV602": {
        "detects": "A split whose result actually depends on an RNG - "
                   "`train_test_split`, `ShuffleSplit`, `random_split`, or a `KFold` "
                   "with `shuffle=True` - with no `random_state=` (scikit-learn) or "
                   "`generator=` (PyTorch).",
        "avoids": ["`KFold` without `shuffle=True`, which is deterministic.",
                   "`TimeSeriesSplit` and `LeaveOneOut`, which are chronological or "
                   "exhaustive.",
                   "A workspace that *is* globally seeded: the finding drops to "
                   "`possible` and the wording becomes \"prefer an explicit "
                   "`random_state` for locality\"."],
    },
    "MLV701": {
        "detects": "A class whose resolved base chain includes `torch.nn.Module` or a "
                   "`LightningModule`, defines `__init__`, and calls neither "
                   "`super().__init__()` nor `<Base>.__init__(self, ...)` anywhere in "
                   "that body.",
        "avoids": ["Abstract intermediate bases, which are never instantiated - "
                   "detected through `@abstractmethod` members or an `ABC` base.",
                   "The explicit `Base.__init__(self)` spelling, which is correct.",
                   "A class whose base is an in-workspace `nn.Module` subclass still "
                   "has to chain: that is not a false positive."],
    },
    "MLV702": {
        "detects": "Inside an `nn.Module`'s `__init__`, a `self.<attr> = [...]` / "
                   "`{...}` / comprehension whose elements are calls resolving under "
                   "`torch.nn.` or to another in-workspace `nn.Module` subclass, with "
                   "no `nn.ModuleList` / `nn.ModuleDict` / `nn.Sequential` wrapper.",
        "avoids": ["A list of *configs* or ints: the check is on the resolved callee of "
                   "the elements, not on the container.",
                   "A list built and then passed into `nn.Sequential(*blocks)` on a "
                   "later line - the binding is followed and the finding suppressed."],
    },
    # ----------------------------------------------------- ANA-7 (11.26)
    "MLV705": {
        "detects": "A `keras.Model.fit(...)` in a workspace that contains **no** "
                   "`keras.Model.compile(...)` anywhere and no "
                   "`keras.models.load_model(...)`.",
        "avoids": ["A `compile()` written in a builder module and the `fit()` in an "
                   "entrypoint - the claim is workspace-wide precisely so that shape "
                   "stays silent.",
                   "A model loaded with `keras.models.load_model`, which arrives "
                   "already compiled."],
        "cannot": "Which binding was compiled. One `compile()` anywhere silences the "
                  "rule for the whole workspace, so a project that compiles one of "
                  "two models is not judged.",
    },
    "MLV706": {
        "detects": "A `.backward()` or optimizer `.step()` written inside the "
                   "`training_step` of a class whose resolved bases include a "
                   "`LightningModule`, with no `self.automatic_optimization = False` "
                   "anywhere in that class.",
        "avoids": ["Correct manual optimisation: `automatic_optimization = False` plus "
                   "`self.manual_backward(loss)` and `self.optimizers()`.",
                   "A class whose base chain does not resolve to a `LightningModule` - "
                   "the rule is not applied at all rather than guessed at."],
    },
    "MLV707": {
        "detects": "A Lightning `training_step` whose every `return` yields `None`, or "
                   "a dict literal with no `'loss'` key - including the case of no "
                   "`return` statement at all.",
        "avoids": ["`return {\"loss\": loss, ...}`, the other shape Lightning accepts.",
                   "A `**spread` dict, whose keys are not knowable statically.",
                   "A generator-shaped step (`yield`), which is not a plain return."],
    },
    "MLV708": {
        "detects": "A `transformers.Trainer(...)` with no `eval_dataset=` whose "
                   "`TrainingArguments` set neither `eval_strategy` nor "
                   "`evaluation_strategy` to anything but `\"no\"`.",
        "avoids": ["A Trainer with an `eval_dataset`, whatever the strategy says.",
                   "A Trainer whose `args=` could not be resolved to a "
                   "`TrainingArguments` construction - unresolvable is not absent.",
                   "An `eval_strategy=\"epoch\"` that asks for evaluation without "
                   "naming the dataset at construction time."],
    },
    "MLV709": {
        "detects": "One `compile()` call whose `loss=` is a `<Loss>(from_logits=True)` "
                   "and whose receiver resolves to a `keras.Model(inputs, outputs)` / "
                   "`Sequential([...])` whose **output** layer carries the literal "
                   "`activation=\"softmax\"` / `\"sigmoid\"` of the matching family "
                   "(softmax pairs with the categorical losses, sigmoid with the "
                   "binary ones). The layer and the loss must meet on the same model.",
        "avoids": ["`from_logits=False`, which is the correct partner for an "
                   "activated head.",
                   "A softmax head beside a `BinaryCrossentropy(from_logits=True)`: "
                   "the pairing is by activation family, not by proximity.",
                   "Two builders in one module - a probs head and a logits head of the "
                   "same categorical problem - which used to accuse each other at "
                   "severity high, confidence 0.95.",
                   "An internal activation: a squeeze-and-excite "
                   "`Dense(ch, activation=\"sigmoid\")` channel gate is not the "
                   "model's output, and the rule judges position in the graph.",
                   "A loss built in another module, which is not paired at all."],
        "cannot": "A model whose `outputs=` expression the analyzer cannot follow back "
                  "to a layer call - a subclassed `keras.Model` with a `call()` method, "
                  "a head built by a helper more than one hop away, or a model compiled "
                  "in a different module from the one that built it. In each case the "
                  "rule stays silent rather than pairing by family alone.",
    },
    "MLV711": {
        "detects": "A `OneCycleLR` / `CyclicLR` / `get_*_schedule_with_warmup` built "
                   "inside `configure_optimizers` with no `{\"interval\": \"step\"}` "
                   "literal anywhere in that method.",
        "avoids": ["The correct return shape, "
                   "`{\"scheduler\": sched, \"interval\": \"step\"}`.",
                   "An epoch-cadence scheduler (`StepLR`, `CosineAnnealingLR`), for "
                   "which the Lightning default is already right."],
    },
    # ----------------------------------------------------- ANA-8 (11.26)
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
                   "A scaler built in a different function from the loop."],
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
    "MLV502": {
        "detects": "A `torch.device(\"cuda\")` written with a string literal at the "
                   "call site, or a `.cuda()` call, in a workspace where nothing calls "
                   "`torch.cuda.is_available()` (or any `*_is_available` / "
                   "`device_count` probe).",
        "avoids": ["`torch.device(\"cuda\" if torch.cuda.is_available() else \"cpu\")` "
                   "- the literal is there, and so is the guard.",
                   "A device that arrives through a module constant or a config "
                   "object, whose default this analyzer cannot see.",
                   "Repetition: one finding per module, with the other sites as "
                   "related locations."],
    },
    "MLV803": {
        "detects": "`torch.save(<MODEL>, path)` where the saved expression contains no "
                   "`.state_dict()`, and `torch.load(...)` with neither "
                   "`map_location=` nor `weights_only=`.",
        "avoids": ["`torch.save(model.state_dict(), path)` and a dict of state dicts.",
                   "A saved value that carries no `MODEL` tag - the rule records an "
                   "`untagged_dataflow` note instead of guessing."],
    },
    # ----------------------------------------------------- ANA-9 (11.26)
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
                   "coincidence in any dataset."],
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
    "MLV305": {
        "detects": "A class metric (`accuracy_score`, `f1_score`, `precision_score`, "
                   "`recall_score`, `confusion_matrix`, the torchmetrics functionals) "
                   "whose prediction argument carries `LOGITS` or `PROBS` and was not "
                   "produced by `argmax` / `round` / `topk` / a threshold comparison.",
        "avoids": ["The score-metric carve-out - `roc_auc_score`, "
                   "`average_precision_score`, `log_loss`, the curves and the ranking "
                   "metrics - which legitimately take scores and are checked before "
                   "anything else.",
                   "Regression metrics, which are not on the class-metric list at all.",
                   "An `argmax` anywhere on the producing chain, including "
                   "`probs.argmax(axis=1)` and a subscript."],
        "cannot": "A prediction returned by a helper function looks unproduced to a "
                  "flow-insensitive IR, so the finding is **de-rated** to evidence "
                  "weight 0.6 rather than dropped; DATAFLOW-IP is what would resolve "
                  "it.",
    },
    "MLV306": {
        "detects": "A `roc_auc_score` / `average_precision_score` whose score argument "
                   "is bound to a `predict(...)` call, whose knowledge-table tag is "
                   "`PREDS`.",
        "avoids": ["`predict_proba(...)[:, 1]` and `decision_function(...)`, which "
                   "carry `PROBS` / `LOGITS`.",
                   "`accuracy_score(y, clf.predict(X))`, where hard labels are exactly "
                   "right."],
    },
}

_SEVERITY_BLURB = {
    "high": "red octagon - very likely a real defect that silently corrupts results "
            "or crashes",
    "medium": "amber triangle - likely wrong, or right only under an assumption that "
              "cannot be checked statically",
    "low": "blue circle - hygiene, reproducibility, portability, or a question worth "
           "asking",
}


def _read(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def _fixture(code: str, kind: str) -> Tuple[Optional[str], str]:
    name = "%s_%s.py" % (code, kind)
    return _read(os.path.join(FIXTURES, name)), name


def _body(text: Optional[str]) -> str:
    """The fixture without its MLVIEW-EXPECT header lines."""
    if text is None:
        return ""
    lines = [l for l in text.splitlines()
             if not l.lstrip().startswith("# MLVIEW-EXPECT")]
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines).rstrip()


def _bullets(items) -> str:
    return "\n".join("- %s" % item for item in items)


def page(spec: RuleSpec) -> str:
    notes = NOTES.get(spec.code, {})
    bad, bad_name = _fixture(spec.code, "bad")
    good, good_name = _fixture(spec.code, "good")
    frameworks = ", ".join(spec.frameworks) if spec.frameworks else "any"
    tags = ", ".join("`%s`" % t for t in spec.tags) if spec.tags else "-"

    out: List[str] = []
    out.append("# %s - %s\n" % (spec.code, spec.title or spec.code))
    if not spec.enabled:
        out.append("> **Disabled in this build.** %s\n"
                   % (notes.get("disabled_reason")
                      or "It could not be made reliable enough to ship on."))
    out.append("| | |")
    out.append("|---|---|")
    out.append("| **Severity** | `%s` - %s |"
               % (spec.severity, _SEVERITY_BLURB.get(spec.severity, "")))
    out.append("| **Frameworks** | %s |" % frameworks)
    out.append("| **Base prior** | %.2f |" % spec.base_prior)
    out.append("| **Rule version** | %d |" % spec.rule_version)
    out.append("| **Tags** | %s |" % tags)
    out.append("| **Absence rule** | %s |"
               % ("yes - severity is capped at `medium` unless the enclosing construct "
                  "resolved statically and no framework wrapper was detected"
                  if spec.absence else "no"))
    out.append("| **Enabled** | %s |" % ("yes" if spec.enabled else "**no**"))
    out.append("")

    if spec.why:
        out.append("## Why it matters\n")
        out.append(spec.why + "\n")

    detects = notes.get("detects")
    if detects:
        out.append("## How it is detected\n")
        out.append(str(detects) + "\n")

    if notes.get("ghost"):
        out.append("## What you see\n")
        out.append("When this fires, %s (a **ghost node**). Showing the hole beats "
                   "narrating it.\n" % notes["ghost"])
    elif notes.get("rendering"):
        out.append("## What you see\n")
        out.append("When this fires, %s\n" % notes["rendering"])

    avoids = notes.get("avoids")
    if avoids:
        out.append("## False positives it avoids\n")
        out.append(_bullets(avoids) + "\n")

    # ROADMAP "the framing to carry forward": a rule that stays silent where it
    # is blind has to say so, or silence reads as a clean bill of health.
    cannot = notes.get("cannot")
    if cannot:
        out.append("## What it cannot analyze\n")
        out.append(str(cannot) + "\n")

    out.append("## How to fix it\n")
    out.append((spec.fix_hint or "See the rule catalog.") + "\n")

    if bad is not None:
        out.append("## Example that fires\n")
        out.append("`analyzer/tests/fixtures/rules/%s`\n" % bad_name)
        out.append("```python\n%s\n```\n" % _body(bad))
    if good is not None:
        out.append("## Example that does not\n")
        out.append("`analyzer/tests/fixtures/rules/%s` - the nearest false-positive "
                   "trap this rule has to survive.\n" % good_name)
        out.append("```python\n%s\n```\n" % _body(good))

    out.append("## Suppressing it\n")
    out.append("```python\nresult = risky_call()  # mlview: ignore[%s]\n```\n"
               % spec.code)
    out.append("Or `# mlview: ignore-file` in the first five lines of the file, or\n"
               "`.mlview.toml`:\n")
    out.append("```toml\n[rules]\ndisable = [\"%s\"]\n```\n" % spec.code)
    out.append("A suppressed issue is still emitted with `suppressed: true`, so the "
               "viewer can offer \"show suppressed\"; hosts never publish it as an "
               "editor diagnostic.\n")
    out.append("---\n")
    out.append("*Generated by `analyzer/tools/gen_rule_docs.py` from the rule registry "
               "and the fixtures - do not edit by hand.*")
    return "\n".join(out) + "\n"


def index(specs: List[RuleSpec]) -> str:
    counts = {"high": 0, "medium": 0, "low": 0}
    for spec in specs:
        counts[spec.severity] = counts.get(spec.severity, 0) + 1
    out: List[str] = []
    out.append("# MLView rule documentation\n")
    out.append("One page per registered rule, generated from the registry and the "
               "per-rule fixtures. Every `Issue.docs` field points here, and both "
               "hosts deep-link to these pages offline.\n")
    out.append("**%d rules** - %d high, %d medium, %d low.\n"
               % (len(specs), counts["high"], counts["medium"], counts["low"]))
    out.append("| Code | Sev | Title | Frameworks | Prior | Absence | Enabled |")
    out.append("|---|---|---|---|---|---|---|")
    for spec in specs:
        out.append("| [%s](%s.md) | %s | %s | %s | %.2f | %s | %s |"
                   % (spec.code, spec.code, spec.severity, spec.title or spec.code,
                      ", ".join(spec.frameworks) if spec.frameworks else "any",
                      spec.base_prior, "yes" if spec.absence else "-",
                      "yes" if spec.enabled else "**no**"))
    out.append("")
    out.append("## Reading a page\n")
    out.append("- **How it is detected** is the real algorithm, not a restatement of "
               "the title.")
    out.append("- **False positives it avoids** is traceable: each bullet is a case "
               "the `_good.py` fixture or the rule body actually handles.")
    out.append("- **Example that fires / does not** are the two shipped fixtures "
               "verbatim, so the page cannot drift from the test suite.\n")
    out.append("Regenerate with:\n")
    out.append("```bash\nPYTHONUTF8=1 python analyzer/tools/gen_rule_docs.py\n```\n")
    out.append("`--check` exits 1 when anything on disk is out of date.\n")
    return "\n".join(out) + "\n"


def build(out_dir: str = DOCS) -> Dict[str, str]:
    """`{relative filename: content}` for every page plus the index."""
    specs = all_rules()
    pages = {"README.md": index(specs)}
    for spec in specs:
        pages["%s.md" % spec.code] = page(spec)
    return pages


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any page on disk is out of date")
    parser.add_argument("--out", default=DOCS, help="output directory")
    args = parser.parse_args(argv)

    pages = build(args.out)
    if args.check:
        stale = []
        for name, text in sorted(pages.items()):
            current = _read(os.path.join(args.out, name))
            if current != text:
                stale.append(name)
        extra = []
        if os.path.isdir(args.out):
            for name in sorted(os.listdir(args.out)):
                if name.endswith(".md") and name not in pages:
                    extra.append(name)
        if stale or extra:
            sys.stderr.write("docs/rules is out of date: %s\n"
                             % ", ".join(stale + ["%s (orphan)" % e for e in extra]))
            return 1
        sys.stderr.write("docs/rules is current (%d pages)\n" % len(pages))
        return 0

    os.makedirs(args.out, exist_ok=True)
    for name, text in sorted(pages.items()):
        io.open(os.path.join(args.out, name), "w", encoding="utf-8",
                newline="\n").write(text)
    sys.stderr.write("wrote %d pages to %s\n"
                     % (len(pages), args.out.replace("\\", "/")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
