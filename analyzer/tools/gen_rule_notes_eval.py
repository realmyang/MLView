"""What each MLV3xx-MLV8xx rule detects: the prose half of its rule page.

Data only, and the second half of `gen_rule_notes.py` - see that module for
what the shape means and why it is not generated. This file holds the rules
about what a run *concludes*: evaluation and metrics (MLV3xx), the objective
and its inputs (MLV4xx), calibration and thresholds (MLV5xx), reproducibility
(MLV6xx), robustness and hygiene (MLV7xx) and serving (MLV8xx). The pipeline
half - the data and training-mechanics families - is in `gen_rule_notes.py`.

Keyed by rule code, sorted by it. A rule with no entry here still gets a usable
page: `gen_rule_docs.page` falls back to the `@rule` declaration text.
"""

from __future__ import annotations

from typing import Dict

__all__ = ["EVAL_NOTES"]


#: MLV3xx and up: what the rule detects, and the traps its `_good.py` fixture
#: encodes so a reader can see what is deliberately *not* a finding.
EVAL_NOTES: Dict[str, Dict[str, object]] = {
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
        "cannot": "A prediction the value typing cannot follow at all - built by a "
                  "construct `rules/valuetype` does not read, or arriving from outside "
                  "the workspace. R4 closed the two commonest gaps: the "
                  "`.detach().cpu().numpy()` tail, which changes the container and "
                  "not what the value holds, and a workspace helper whose `return` is "
                  "the softmax (`probs = probabilities(model, x)`); a per-batch list "
                  "later joined by `np.concatenate(...)` is typed by the "
                  "**intersection** of every `append`, so one unreadable append "
                  "yields no answer rather than a guess. A value the walk still "
                  "cannot type leaves the finding **de-rated** to evidence weight 0.6 "
                  "rather than dropped.",
    },
    "MLV306": {
        "detects": "A `roc_auc_score` / `average_precision_score` whose score "
                   "argument carries `PREDS` and was produced by a `PREDICT` or an "
                   "`ARGMAX` role - `clf.predict(X)`, and since R4 also "
                   "`logits.argmax(dim=1)`, which is the torch spelling of the same "
                   "mistake. The value typing follows the same two hops MLV305 reads: "
                   "the tensor tail and one workspace helper.",
        "avoids": ["`predict_proba(...)[:, 1]` and `decision_function(...)`, which "
                   "carry `PROBS` / `LOGITS`.",
                   "`accuracy_score(y, clf.predict(X))`, where hard labels are exactly "
                   "right."],
    },
    "MLV401": {
        "detects": "The value passed as the first argument to a `CrossEntropyLoss` "
                   "instance or to `F.cross_entropy`, traced back through the SSA "
                   "chain, reaches a softmax / log-softmax - directly, through a "
                   "model whose `forward` returns one, or through the last element of "
                   "its final `nn.Sequential` - for a bare "
                   "`net = nn.Sequential(..., nn.Softmax(dim=1))` binding as well as "
                   "for a Sequential stored on an attribute of an `nn.Module`. The "
                   "model class is any **model module** (`is_model_module`), so a "
                   "`pl.LightningModule`'s `self(features)` in a `training_step` is a "
                   "forward pass here exactly as a bare `nn.Module`'s is. Failing "
                   "that - and only after the model-class branch, which is what keeps "
                   "the finding its class, its edge and its `definition` location - "
                   "R4 reads one workspace helper's `return`: "
                   "`def probabilities(m, x): return F.softmax(m(x), dim=-1)` pairs "
                   "just as wrongly as an inline softmax, and pays one "
                   "`IP_HOP_WEIGHT` for the crossing.",
        "avoids": ["A user class merely *named* `Softmax`: matching is on canonical "
                   "FQNs resolved through the import table, never on the attribute "
                   "name.",
                   "A softmax applied under an `if`, which is de-rated.",
                   "Softmax computed elsewhere for reporting, which never reaches the "
                   "loss input.",
                   "The **same** softmax reported twice. One root cause is one "
                   "finding: a LightningModule applies one `forward` in both "
                   "`training_step` and `validation_step`, so the second loss site "
                   "merges into the first finding's `relatedLocs` instead of raising "
                   "a copy."],
        "rendering": "the marker is drawn on the `model -> loss` **edge**, and the "
                     "multi-location connector links the softmax site to the loss.",
    },
    "MLV402": {
        "detects": "Two symmetric checks over the same final-op chain. "
                   "`double_sigmoid`: the loss is `BCEWithLogitsLoss` / "
                   "`binary_cross_entropy_with_logits` and the chain ends in a sigmoid. "
                   "`missing_sigmoid`: the loss is `BCELoss` / "
                   "`binary_cross_entropy` and the resolved chain ends in something "
                   "that is not. The chain steps through shape-only tensor methods "
                   "(`.squeeze(-1)`, `.view(...)`), reads both operands of a "
                   "`BinOp` argument, resolves a forward through any **model module** "
                   "rather than only a bare `nn.Module`, and - R4 - through one "
                   "workspace helper's `return`, which pays an `IP_HOP_WEIGHT`.",
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
    "MLV803": {
        "detects": "`torch.save(<MODEL>, path)` where the saved expression contains no "
                   "`.state_dict()`, and `torch.load(...)` with neither "
                   "`map_location=` nor `weights_only=`.",
        "avoids": ["`torch.save(model.state_dict(), path)` and a dict of state dicts.",
                   "A saved value that carries no `MODEL` tag - the rule records an "
                   "`untagged_dataflow` note instead of guessing."],
    },
    # ----------------------------------------------------- ANA-9 (11.26)
}
