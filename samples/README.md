# MLView sample projects

Two small PyTorch + scikit-learn projects that exist to be *read*, never run.
Neither `torch` nor `scikit-learn` needs to be installed: MLView parses them.

| Directory | Expected result |
|---|---|
| `vision_pipeline/` | **exactly 15 issues** — 5 high, 6 medium, 4 low, across 14 rule codes |
| `vision_pipeline_clean/` | **0 issues**, same five files, same shape |

```
python -m mlview analyze samples/vision_pipeline --format summary
python -m mlview analyze samples/vision_pipeline --html report.html --open
python -m mlview analyze samples/vision_pipeline_clean --format summary
```

`vision_pipeline/expected_issues.json` is the machine-checked contract
(`{code, severity, file, line}`, sorted by file/line/code). It is asserted by
`analyzer/tests/rules/test_samples.py` and by `scripts/e2e.ps1`. **If you edit a
sample file, regenerate that JSON in the same commit** — a line number moves
with the code.

---

## The demo story

1. **Open the dirty project.** Seven of the eight stage lanes light up:
   configuration, data, preprocess, model, objective, train, evaluate. The
   pipeline is legible before a single issue is read.
2. **Follow the red.** Five high-severity markers, one in each stage that
   matters: leakage in `sklearn_baseline.py`, a training step with no
   `zero_grad`, an evaluation loop with no `eval()`, a softmax feeding
   `CrossEntropyLoss`, and four convolutional blocks the optimizer will never
   see.
3. **Look at the holes.** Two **ghost nodes** are drawn as dashed placeholders
   in the slot where the missing call belongs — `zero_grad()` inside the batch
   loop and `model.eval()` at the head of the evaluation loop. Showing the hole
   beats narrating it.
4. **Follow a connector.** MLV101 draws a line from `scaler.fit_transform(X)`
   to the `train_test_split` five lines below it: two locations, one finding.
5. **Look at an edge, not a node.** MLV401 marks the `model → loss` *edge* —
   the defect is the pairing, and that is where the marker sits.
6. **Open the clean twin.** The same five files, the same shape, no markers at
   all. That is what makes the first screen believable.

---

## The fifteen planted defects

Each row is a real mistake that a competent person makes on a Tuesday. The
number is the fix comment in `vision_pipeline_clean/`.

### High — silently corrupts results

| # | Code | File · line | What is wrong |
|---|---|---|---|
| 1 | **MLV101** | `sklearn_baseline.py:24` | `StandardScaler().fit_transform(X)` runs on the whole feature matrix, five lines *before* `train_test_split`. Test-set means and variances leak into training, so the reported hold-out accuracy is optimistic. |
| 2 | **MLV201** | `train.py:29` | The batch loop calls `loss.backward()` and `optimizer.step()` but never `optimizer.zero_grad()`. Gradients accumulate across batches, so each update is the sum of every batch so far. |
| 3 | **MLV301** | `train.py:44` | `validate()` runs the model without `model.eval()`. `SmallCNN` contains `BatchNorm2d` **and** `Dropout` (inside `ConvBlock`), so validation both drops activations and keeps updating the running statistics. |
| 4 | **MLV401** | `train.py:31` | `SmallCNN.forward` returns `F.softmax(...)` while `train.py` uses `nn.CrossEntropyLoss`, which log-softmaxes again. Marked on the `model → loss` edge. |
| 5 | **MLV702** | `model.py:34` | `self.blocks = [ConvBlock(...) for _ in range(4)]` — a plain list. Those four blocks never appear in `parameters()`, so the optimizer never updates them and `.to(device)` leaves them behind. |

### Medium — likely wrong, or right only under an assumption

| # | Code | File · line | What is wrong |
|---|---|---|---|
| 6 | **MLV103** | `sklearn_baseline.py:34` | `PCA` is fitted once on the whole training split, then a *bare* `LogisticRegression` is handed to `cross_val_score`. Every fold is scored on a projection that saw it. |
| 7 | **MLV110** | `data.py:33` | The training `DataLoader` has no `shuffle=True` and no `sampler=`, so batches arrive in dataset order every epoch. |
| 8 | **MLV112** | `data.py:33` | `num_workers=4` on a loader constructed **at module scope** in a module with no `__main__` guard. On Windows and macOS spawn re-imports the module in every worker. |
| 9 | **MLV205** | `train.py:34` | `running_loss += loss` accumulates the tensor, not `loss.item()`, so the whole epoch's autograd graph stays alive. |
| 10 | **MLV302** | `train.py:44` | The validation loop is not wrapped in `torch.no_grad()`, so it builds a graph nobody backpropagates. |
| 11 | **MLV501** | `train.py:29` | `model.to(device)` moves the network to the GPU; `images` and `labels` are never moved. |

### Low — hygiene, reproducibility, a question worth asking

| # | Code | File · line | What is wrong |
|---|---|---|---|
| 12 | **MLV111** | `data.py:35` | `DataLoader(test_ds, shuffle=True)` — predictions no longer line up with dataset order. |
| 13 | **MLV601** | `config.py:10` | No `torch.manual_seed`, no `np.random.seed`, no `random_state=` anywhere in the workspace. |
| 14 | **MLV602** | `sklearn_baseline.py:26` | `train_test_split(...)` without `random_state`. |
| 15 | **MLV602** | `data.py:31` | `random_split(full_train, [45000, 5000])` without `generator=`. |

These fifteen findings span 14 of the 36 shipped rule codes. The rest —
`MLV102`, `MLV202`, `MLV203`, `MLV204`, `MLV402`, `MLV701` and the framework,
mechanics and held-out tiers — are deliberately **absent** from this sample and
are exercised by their own fixtures under `analyzer/tests/fixtures/rules/`, so a
slip in one of them cannot break the walkthrough. `python -m mlview rules --list`
prints the whole registry.

---

## Why the high-severity findings are allowed to be `high`

Three of them (`MLV201`, `MLV301`, plus `MLV202` elsewhere) are **absence
rules**: they fire on a call that is *not* there. Those may only reach `high`
when the enclosing construct resolved with no dynamic constructs **and** no
framework wrapper was detected. This sample deliberately contains neither
`exec`/`getattr` indirection nor Lightning / HF `Trainer` / `accelerate`, which
is exactly the precondition — so the sample also demonstrates *why* the cap
exists. Add `import pytorch_lightning` to any file here and watch both drop to
`medium` / `speculative` with a visible "training loop handled by Lightning"
chip.

---

## Regenerating `expected_issues.json`

```bash
PYTHONUTF8=1 python analyzer/tools/gen_expected_issues.py
```

It rewrites `vision_pipeline/expected_issues.json` from a live analysis, sorted
canonically. Run it whenever a sample file changes, and check the counts still
read 5 high / 6 medium / 4 low.

---

## Where else to look

`analyzer/tests/clean/` is the larger silent corpus: correct programs that must
produce **zero** findings, together and one file at a time.
`analyzer/tests/accuracy/corpus/` is the 158-program labelled corpus that
`python tools/accuracy.py` scores — see [`../docs/ACCURACY.md`](../docs/ACCURACY.md)
for what a label is and what is still missed, and
[`../docs/STATUS.md`](../docs/STATUS.md) for the current state of the tree.
