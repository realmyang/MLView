# MLView rule documentation

One page per registered rule, generated from the registry and the per-rule fixtures. Every `Issue.docs` field points here, and both hosts deep-link to these pages offline.

**20 rules** - 11 high, 6 medium, 3 low.

| Code | Sev | Title | Frameworks | Prior | Absence | Enabled |
|---|---|---|---|---|---|---|
| [MLV101](MLV101.md) | high | Preprocessing fitted before the train/test split | sklearn, pandas | 0.95 | - | yes |
| [MLV102](MLV102.md) | high | Transformer fitted on validation or test data | sklearn | 0.97 | - | yes |
| [MLV103](MLV103.md) | medium | Preprocessing happens outside cross-validation | sklearn | 0.85 | - | yes |
| [MLV110](MLV110.md) | medium | Training DataLoader does not shuffle | torch | 0.85 | - | yes |
| [MLV111](MLV111.md) | low | Evaluation DataLoader shuffles | torch | 0.90 | - | yes |
| [MLV112](MLV112.md) | medium | DataLoader worker processes without a __main__ guard | torch | 0.98 | - | yes |
| [MLV201](MLV201.md) | high | Gradients are never zeroed | torch | 0.90 | yes | yes |
| [MLV202](MLV202.md) | high | Gradients are computed but never applied | torch | 0.90 | yes | yes |
| [MLV203](MLV203.md) | high | optimizer.step() runs before loss.backward() | torch | 0.95 | - | yes |
| [MLV204](MLV204.md) | high | backward() inside torch.no_grad() | torch | 0.97 | - | yes |
| [MLV205](MLV205.md) | medium | Loss accumulated without .item() | torch | 0.85 | - | yes |
| [MLV301](MLV301.md) | high | Evaluation runs without model.eval() | torch | 0.85 | yes | yes |
| [MLV302](MLV302.md) | medium | Evaluation loop not wrapped in torch.no_grad() | torch | 0.85 | - | yes |
| [MLV401](MLV401.md) | high | Softmax applied before CrossEntropyLoss | torch | 0.95 | - | yes |
| [MLV402](MLV402.md) | high | Sigmoid and BCE loss are paired inconsistently | torch | 0.95 | - | yes |
| [MLV501](MLV501.md) | medium | Model and batches are on different devices | torch | 0.90 | - | yes |
| [MLV601](MLV601.md) | low | No random seed set anywhere | any | 0.90 | yes | yes |
| [MLV602](MLV602.md) | low | Split without random_state / generator | sklearn, torch, hf | 0.95 | - | yes |
| [MLV701](MLV701.md) | high | nn.Module.__init__ never calls super().__init__() | torch, lightning | 0.97 | - | yes |
| [MLV702](MLV702.md) | high | Submodules held in a plain list are never registered | torch | 0.95 | - | yes |

## Reading a page

- **How it is detected** is the real algorithm, not a restatement of the title.
- **False positives it avoids** is traceable: each bullet is a case the `_good.py` fixture or the rule body actually handles.
- **Example that fires / does not** are the two shipped fixtures verbatim, so the page cannot drift from the test suite.

Regenerate with:

```bash
PYTHONUTF8=1 python analyzer/tools/gen_rule_docs.py
```

`--check` exits 1 when anything on disk is out of date.

