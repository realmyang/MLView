export const meta = {
  name: 'mlview-hardening',
  description: 'Test MLView extensively against public ML repos, labelled realistic applications across every ML/DL domain, all host surfaces and robustness fuzzing; verify findings; fix by component; integrate with CI; repeat until dry',
  phases: [
    { title: 'Test', detail: '8 testers: public repos, 5 domains, hosts/UX, robustness', model: 'opus' },
    { title: 'Verify', detail: '3 verifiers per critical/major finding', model: 'opus' },
    { title: 'Fix', detail: 'fixers per component', model: 'opus' },
    { title: 'Integrate', detail: 'gates, corpus ratchets, commit, push, CI', model: 'opus' },
  ],
}

const ROOT = '/Users/minghaoyang/Documents/MLView'
const SCRATCH = '/private/tmp/claude-501/-Users-minghaoyang-Documents-MLView/2ebc6c0c-4dab-49ea-a032-c99b4c9f286e/scratchpad'
const PW = SCRATCH + '/pw'
const PUB = SCRATCH + '/public'

const PREAMBLE = `
You are part of a hardening campaign for MLView, a static analyzer for Python ML/DL code (PyTorch, scikit-learn, Keras/TF, HuggingFace, Lightning, plus config resolution, interprocedural dataflow behind --dataflow ip, notebooks behind --include-notebooks, 36 rules MLV1xx-8xx) that renders the workflow as an interactive diagram with severity-marked issues in three hosts (standalone HTML report, VS Code extension, Claude Code plugin with 5 MCP tools). The user asked: "Test the current implementation extensively and carefully. Besides fixing bugs, focus on a coverage over all possible ML/DL code as comprehensive as possible: test against public repos, construct code that mimics real ML/DL applications." The product's credibility rule: a high-severity false positive on correct code is the worst failure; the second worst is silently misrepresenting code (a stage claimed absent, a call dropped, a crash swallowed). Precision is gated at 100% with zero forbidden findings on the labelled corpus (tools/accuracy.py); recall may only ratchet up.
READ FIRST: README.md, docs/STATUS.md, docs/ISSUE_RULES.md (sections 3-4: every rule's detection and false-positive guards), docs/ACCURACY.md, tools/accuracy_corpus.py (the label format: expected / forbidden rows with file, line, symbol, severity, why; tuned flag), an existing corpus program under analyzer/tests/accuracy/corpus/, and docs/CONTRACTS.md sections 0, 10, 11 (amendments run to 11.47).
ENVIRONMENT (macOS): repo root ${ROOT} (git; branch hardening from sprint5 ef4fb71, PR #3 still open; pushes go over SSH: 'git push git@github.com:realmyang/MLView.git HEAD:hardening'). START EVERY SHELL COMMAND WITH: export PATH="${ROOT}/.venv/bin:$PATH" PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 (venv Python 3.13 with the analyzer editable plus mcp, pytest, pytest-xdist, jsonschema, build; never the system python3). Node 26 / npm 11 (CI runs Node 20/22). 'sh scripts/e2e.sh' is the full gate (20 steps); 'python tools/verify.py --all' (10 rows); 'python tools/accuracy.py' and '--dataflow ip'; Playwright + Chromium at ${PW}/node_modules (run node from that dir or NODE_PATH=${PW}/node_modules); gh CLI: per command export GH_TOKEN=$(printf 'protocol=https\\nhost=github.com\\n' | git credential fill 2>/dev/null | sed -n 's/^password=//p') (never print it). Scratch: ${SCRATCH}. Network is available for git clone.
BASELINE (green on this Mac at hardening ef4fb71): e2e 20 steps; analyzer 2024 passed; webview 521; vscode-extension 372; claude-plugin 370; verify 10/10; accuracy precision 100% / recall 73.1% local, 79.5% ip.
GIT RULES: only the integrator runs git. Commits: imperative subject, body, trailer 'Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>'. Never force-push, never touch main or sprint5.
CONTRACT AMENDMENTS: never edit docs/CONTRACTS.md directly; write docs/contracts/11.<NN>-<slug>.md using the next free number at or above 11.50 (check docs/contracts/ for siblings first); the integrator appends them.
QUALITY BAR: real evidence only (commands, outputs, file:line); every finding has an exact repro and observed vs expected; no innerHTML; no getTotalLength; library code never prints to stdout; write each new file completely in one Write call.
FINAL ANSWER: return ONLY the structured report.
`

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    area: { type: 'string' },
    coverage: { type: 'string', description: 'what was exercised: repos/programs/flags/hosts, with counts and timings' },
    corpus_added: { type: 'array', items: { type: 'string' }, description: 'files added under the repo (labelled programs, public-corpus manifests, tests)' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          component: { enum: ['analyzer', 'webview', 'vscode-extension', 'claude-plugin', 'process-docs'] },
          kind: { enum: ['false-positive', 'false-negative', 'crash', 'misrepresentation', 'host-bug', 'ux', 'performance', 'docs'] },
          severity: { enum: ['critical', 'major', 'minor'] },
          file: { type: 'string' },
          title: { type: 'string' },
          detail: { type: 'string' },
          repro: { type: 'string' },
          suggested_fix: { type: 'string' },
        },
        required: ['id', 'component', 'kind', 'severity', 'file', 'title', 'detail', 'repro', 'suggested_fix'],
      },
    },
    what_works: { type: 'string' },
  },
  required: ['area', 'coverage', 'corpus_added', 'findings', 'what_works'],
}

const TESTERS = [
  { key: 'public-repos', own: 'analyzer/tests/public_corpus/** (new), tools/public_corpus.py (new), .github/workflows/public-corpus.yml (new; schedule + workflow_dispatch only)', prompt: `AREA: public repositories. Curate 18-25 real, popular, permissively licensed Python ML/DL repositories spanning frameworks and domains - e.g. pytorch/examples (all subdirs), karpathy/nanoGPT, karpathy/minGPT, huggingface/transformers (examples/pytorch subset via sparse checkout), Lightning-AI/pytorch-lightning (examples subset), ultralytics/yolov5, huggingface/pytorch-image-models (train.py, validate.py), scikit-learn/scikit-learn (examples/ gallery via sparse checkout - hundreds of sklearn scripts), keras-team/keras-io (examples/ subset), google/flax (examples; JAX - MLView must degrade honestly), DLR-RM/stable-baselines3, pyg-team/pytorch_geometric (examples), lucidrains/vit-pytorch, lucidrains/denoising-diffusion-pytorch, openai/CLIP, facebookresearch/detectron2 (tools/ + a config-driven trainer), CompVis/stable-diffusion (ldm), fastai/fastai (examples/nbs subset incl. notebooks), jakevdp/PythonDataScienceHandbook (notebooks), mlflow/mlflow (examples), wandb/examples, tensorflow/models (official/vision subset), NVIDIA/DeepLearningExamples (a PyTorch subset). Use 'git clone --depth 1' (or sparse-checkout for the huge ones) into ${PUB}/<name>, record the exact commit SHA and the sparse paths in analyzer/tests/public_corpus/repos.json, and keep the total under ~3 GB. For each repo run the analyzer three ways (default; --dataflow ip; --include-notebooks where notebooks exist), with '--json' to a scratch file and '--format summary', capturing exit code, stderr, wall time, node/edge/issue counts, diagnostics, unknown/dynamic counts. ANY traceback, non-zero exit other than 4, schema-invalid document (contracts/validate_sample.py), or >60 s wall time is a finding. Then ADJUDICATE every high finding and a sample of mediums by reading the cited code: true-positive (a real defect or a defensible warning), false-positive (with the exact reason and the rule's guard that should have caught it), or unsure; record them in analyzer/tests/public_corpus/adjudication.json keyed by a stable key (repo, code, file, symbol). Judge graph fidelity on five repos you know well (does the diagram show the real training pipeline? which stages are missing? are entrypoints right?). Build tools/public_corpus.py with 'fetch' (clones pinned SHAs into MLVIEW_PUBLIC_CORPUS_DIR), 'run' (analyzes all, writes a report), and 'check' (asserts: no crash, exit 0/4 only, schema-valid, no NEW high finding beyond adjudication.json, and every adjudicated false-positive is ABSENT - so the file doubles as a regression ratchet), plus analyzer/tests/public_corpus/test_public_corpus.py that skips when the corpus dir is absent, and a nightly/manual workflow that fetches and checks. Report every false positive, crash, misrepresentation and slow repo as a finding with the repo, SHA, file:line and repro.` },
  { key: 'domain-vision', own: 'analyzer/tests/accuracy/corpus/vision_*/** (new programs only)', prompt: `AREA: computer vision applications. Write 8-12 realistic, multi-file programs (200-600 lines each, imports only, never executed) mimicking real projects: an ImageNet-style classifier with DDP + AMP + gradient accumulation + EMA + LR warmup; a YOLO-like detector with a custom collate, anchors, NMS post-processing and mAP eval; a U-Net segmentation trainer with albumentations and Dice/IoU; a ViT fine-tune with timm and mixup/cutmix; a GAN (DCGAN and a WGAN-GP with two optimizers); a VAE; a diffusion (DDPM) trainer with EMA and a sampler; a contrastive/self-supervised SimCLR with two views; a Keras/TF CNN with tf.data augmentation; a Lightning image module with a DataModule; a video/3D model with temporal loaders; an inference-only service (ONNX export + FastAPI). Each program pair: a CORRECT version (must be 0 high, ideally 0 issues - every hit is a forbidden label with why) and a DEFECTIVE twin with 3-8 planted, realistic defects from docs/ISSUE_RULES.md plus the kinds of mistakes practitioners actually make in this domain (train-mode eval, augmentation on val, BN under no_grad, wrong loss/activation pairing, leaking the test split via a shared transform fit, etc.), labelled as expected rows (some may be defects MLView has no rule for - label them verdict 'unsupported' so the gap is visible, not silent). Run the analyzer on each in both dataflow modes; every unexpected high/medium, every missed expected label, every crash, and every graph misrepresentation (missing training loop, missing loss/optimizer, wrong stage, dropped class-method ops, 'not detected' claims that are false) is a finding with repro. Add the programs to the corpus with labels.json (tuned: false, unseen).` },
  { key: 'domain-nlp', own: 'analyzer/tests/accuracy/corpus/nlp_*/** (new programs only)', prompt: `AREA: NLP and LLM applications. Write 8-12 realistic multi-file programs (imports only, never executed): HF Trainer fine-tune for classification with a datasets pipeline and a custom compute_metrics; a token-classification (NER) script with label alignment; a seq2seq (T5) summarizer with generation metrics; a from-scratch GPT training loop (nanoGPT-style) with gradient accumulation, cosine schedule, torch.compile and checkpoint resume; a LoRA/PEFT fine-tune; a sentence-embedding contrastive trainer; a classic sklearn text pipeline (TfidfVectorizer + LogisticRegression in a Pipeline with GridSearchCV, and a defective twin fitting the vectorizer before the split); a tokenizer-training script; an RNN/LSTM tagger with packed sequences; an evaluation-only script computing BLEU/ROUGE over saved predictions; an inference server with batching. CORRECT versions must be 0 high; DEFECTIVE twins carry 3-8 realistic planted defects (eval without model.eval(), missing no_grad in generation loops, shuffling the eval loader, tokenizer fitted on test, label leakage via a feature built from the target, metrics on logits, etc.), labelled per tools/accuracy_corpus.py with 'unsupported' where no rule exists. Run both dataflow modes; report every false positive, missed label, crash and misrepresentation with repro. Add the programs to the corpus (tuned: false).` },
  { key: 'domain-tabular', own: 'analyzer/tests/accuracy/corpus/tabular_*/** (new programs only)', prompt: `AREA: classical ML, tabular and time series. Write 8-12 realistic programs (imports only): a Kaggle-style tabular pipeline with pandas feature engineering, ColumnTransformer, Pipeline, StratifiedKFold CV, XGBoost/LightGBM/CatBoost with early stopping on a validation fold; a defective twin with target encoding fitted on the full frame, imputation before the split, SMOTE applied to the test fold, early stopping on the test set, and a feature derived from the target; a time-series forecaster with lag features and TimeSeriesSplit (correct) and its shuffled-split twin; a Prophet/statsmodels script; a clustering + PCA + t-SNE exploration script; a recommender (matrix factorization in torch, implicit feedback) with a leaky negative sampler twin; an AutoML-style loop over estimators with cross_val_score; a calibration + threshold-tuning script; a feature-store style multi-module package where the split happens in one module and the fit in another (exercises --dataflow ip); a scikit-learn Pipeline with FunctionTransformer and custom estimators (BaseEstimator subclasses); an MLflow-tracked experiment. Label correct versions (0 high; forbidden rows with why) and defective twins (expected rows; 'unsupported' where no rule exists). Run both dataflow modes; report every false positive, missed label, crash and graph misrepresentation with repro; add the programs to the corpus.` },
  { key: 'domain-generative-rl-graph', own: 'analyzer/tests/accuracy/corpus/adv_*/** (new programs only)', prompt: `AREA: reinforcement learning, graph learning, audio, multimodal and advanced training patterns. Write 8-12 realistic programs (imports only): a PPO agent with a rollout buffer, GAE, clipped objective, two heads and an entropy bonus (gymnasium); a DQN with a replay buffer and target-network sync; a stable-baselines3 training script; a PyTorch Geometric GCN node-classification trainer with masks; a GNN link predictor with negative sampling; an audio classifier with torchaudio spectrograms; a CLIP-style multimodal contrastive trainer; a knowledge-distillation loop (teacher in eval, student in train, KL loss with temperature); a meta-learning (MAML-style) inner/outer loop with higher-order grads; a quantization-aware training + export script; a mixed multi-task loss with uncertainty weighting; a curriculum/active-learning loop that re-splits data every round (a legitimate re-split - must not be a leak finding). Correct versions 0 high; defective twins with 3-8 planted defects (target net never synced, teacher not in eval, replay sampling from the test episodes, GNN test mask used in training loss, missing detach on targets, missing zero_grad in the inner loop, etc.). Label per the corpus format ('unsupported' where no rule exists). Run both dataflow modes; report every false positive, missed label, crash and misrepresentation; add the programs to the corpus.` },
  { key: 'domain-infra', own: 'analyzer/tests/accuracy/corpus/infra_*/** (new programs only)', prompt: `AREA: frameworks, infrastructure and project shapes. Write 10-14 realistic programs (imports only): a Lightning project with LightningModule + LightningDataModule + callbacks + a CLI (LightningCLI / YAML); an HF accelerate script; a torchrun DDP script with DistributedSampler and rank-0 checkpointing (a correct one and a twin that forgets sampler.set_epoch and saves on every rank); an FSDP script; a DeepSpeed config-driven trainer; a fastai learner script; an Ignite engine script; a Keras functional model with tf.data, callbacks and a custom training step (train_step override); a JAX/Flax/optax trainer (unsupported framework: MLView must recognise nothing falsely and say so); a Hydra-configured research repo (conf/ YAML + a registry + getattr dispatch); an argparse + dataclass config package with the training loop split across data/, models/, engine/, utils/ packages and relative imports (exercises cross-file resolution and --relevance ml with non-ML utility modules present); a monorepo with a tests/ folder and a notebooks/ folder (.ipynb with magics, an out-of-order execution_count, and a notebook that fits before the split); a script using torch.compile, channels_last, bf16 autocast, gradient checkpointing and EMA; a serving package (TorchServe handler / FastAPI) with no training at all (must not claim a training loop); a package whose entrypoint is a __main__.py and a setup.py/pyproject with a console script. Label correct/defective per the corpus format; run all three modes (default, --dataflow ip, --include-notebooks) and also --relevance all vs ml (must be identical findings); report every false positive, missed label, crash, misrepresentation and any 'not detected' claim that is false; add the programs to the corpus.` },
  { key: 'hosts-ux', own: 'nothing in the repo (scratch only) except webview/test/hardening_*.mjs, vscode-extension/test/hardening_*.test.js and claude-plugin/tests/test_hardening_*.py for regression tests you write for real bugs', prompt: `AREA: every host surface over many real graphs. Take the graphs produced by the other testers as they land under analyzer/tests/accuracy/corpus/ (poll; also analyze samples/, analyzer/tests/clean and any public repo clones under ${PUB}) and exercise: (1) the standalone report in Chromium (Playwright): for at least 25 distinct graphs open the report at 1600x1000 and 1280x800, light and dark, assert zero console/page errors, take screenshots and VIEW them with Read for overlaps, unreadable first paint, empty lanes, broken labels, clipped cards, the answer card, chips/banners; exercise hover flow, click-to-copy, scope picker (unit/stage/concern/file/pipeline), search, filters, group-by, legend, export (SVG/PNG validity), print media, diff overlay (via mlview diff over a correct/defective pair spliced into the report), reduced motion, keyboard-only navigation; (2) the CLI flag matrix: every documented flag and subcommand (analyze/issues/render/explain/rules/schema/baseline/diff/init/--list-scopes/--scope/--depth/--group-by/--changed-since/--changed-paths/--changed-only/--baseline/--sarif/--relevance/--dataflow/--include-notebooks/--max-nodes/--fail-on/--config/--progress-json/--format all values) on several corpora, including error paths, exit codes, stdout purity (stdout must be only the payload) and determinism (two runs byte-identical after stripping generatedAt/durationMs, cold vs warm cache, ml vs all); (3) the MCP server end to end with the SDK client over 5+ corpora: every tool with every parameter combination, payload <= 4 KB, error text quality, cache behaviour, the hooks scripts with fake payloads; (4) the VS Code extension through its mocked-vscode test harness with real graphs (multi-root, code actions applying fixes then re-analysis, diagnostics counts vs CLI counts, notebook cell URIs, scope commands); (5) the Claude Code plugin manifest and commands text. Every defect is a finding with repro; add a regression test under your ownership for each real bug you can pin.` },
  { key: 'robustness', own: 'analyzer/tests/fixtures/robustness/** (new), analyzer/tests/core/test_hardening_robustness.py (new), analyzer/tests/core/test_hardening_perf.py (new)', prompt: `AREA: robustness, adversarial inputs and performance. Feed the analyzer: every Python syntax feature (match, walrus, PEP 695 generics, async/await, decorators with arguments, metaclasses, dataclasses with slots, TypedDict, Protocol, overloads, f-strings with nested quotes, star-args forwarding, lambda-bound callables, exec/eval, conditional imports, try/except ImportError fallbacks, __all__, from x import * chains, circular imports, relative imports beyond the top package, namespace packages, shadowed stdlib names (a module called torch.py or random.py), files with BOM/CRLF/tabs/mixed indentation, non-UTF-8 bytes, very long lines, 5k-line generated files, 2000-file synthetic repos, deeply nested loops, classes with 300 methods, symlinked dirs and symlink loops, unreadable files, binary files with .py extension, zero-byte files, a notebook with malformed JSON, a notebook with a string source, huge notebooks); mutate real corpus files randomly (delete lines, duplicate blocks, rename identifiers) 500 times and check for tracebacks; run under '--max-nodes 20/45/100/400', '--relevance ml', '--dataflow ip', the cache warm/cold, and with a read-only .mlview dir; measure wall time and peak RSS (/usr/bin/time -l) on the biggest inputs and on the largest public clones under ${PUB} if present; run 'python tools/verify.py --scopes --fuzz 1000'. Any traceback, hang (>120 s), non-deterministic output, schema-invalid document, memory blow-up (>2 GB), or silent misrepresentation (a dropped training loop, a stage claimed absent) is a finding. Turn every reproducible input into a fixture + a test under your ownership (the test may be marked xfail with the finding id if the fix is another component's).` },
]

const VERDICT_SCHEMA = { type: 'object', properties: { confirmed: { type: 'boolean' }, reasoning: { type: 'string' } }, required: ['confirmed', 'reasoning'] }
const REPORT_SCHEMA = {
  type: 'object',
  properties: {
    component: { type: 'string' }, files_created: { type: 'array', items: { type: 'string' } }, files_modified: { type: 'array', items: { type: 'string' } },
    what_changed: { type: 'string' }, tests_run: { type: 'string' }, test_results: { type: 'string' }, all_tests_passing: { type: 'boolean' },
    known_gaps: { type: 'array', items: { type: 'string' } }, notes_for_integrator: { type: 'string' },
  },
  required: ['component', 'files_created', 'files_modified', 'what_changed', 'tests_run', 'test_results', 'all_tests_passing', 'known_gaps', 'notes_for_integrator'],
}
const GATES_SCHEMA = {
  type: 'object',
  properties: {
    gates: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, passed: { type: 'boolean' }, output_tail: { type: 'string' } }, required: ['name', 'passed', 'output_tail'] } },
    all_passed: { type: 'boolean' }, commits: { type: 'array', items: { type: 'string' } }, ci: { type: 'string' }, ci_green: { type: 'boolean' },
    accuracy: { type: 'string', description: 'the accuracy table headline in both modes, unseen recall included' },
    fixes_applied: { type: 'array', items: { type: 'string' } }, remaining_problems: { type: 'array', items: { type: 'string' } },
  },
  required: ['gates', 'all_passed', 'commits', 'ci', 'ci_green', 'accuracy', 'fixes_applied', 'remaining_problems'],
}

const fixedSoFar = []
const summary = []
for (let round = 1; round <= 2; round++) {
  phase('Test')
  log(`Round ${round}: 8 testers`)
  const tests = (await parallel(TESTERS.map(t => () =>
    agent(`${PREAMBLE}
ROLE: tester '${t.key}' (round ${round}). You do NOT run git and you do NOT modify product code; your repo writes are limited to: ${t.own}. Testers in other areas write elsewhere concurrently.
${t.prompt}
${round > 1 ? `THIS IS ROUND 2: the round-1 findings below were fixed and integrated; re-run your coverage on the current tree, confirm each fix holds (a regression is a critical finding), extend coverage into shapes you did not reach in round 1, and report only NEW or still-open defects. Previously fixed: ${JSON.stringify(fixedSoFar.map(f => f.title))}` : ''}
Return findings sorted by severity (critical: false positives at high severity, crashes, silent misrepresentation; major: other wrong results, missed labels a rule should catch, host bugs; minor: polish), plus what_works.`,
      { label: `test:${t.key}:r${round}`, phase: 'Test', schema: FINDINGS_SCHEMA, model: 'opus', effort: 'xhigh' })))).filter(Boolean)
  const raw = tests.flatMap(t => t.findings)
  log(`Round ${round}: ${raw.length} raw findings from ${tests.length} testers`)
  summary.push({ round, testers: tests.map(t => ({ area: t.area, coverage: t.coverage.slice(0, 600), corpus_added: t.corpus_added.length, findings: t.findings.length })) })
  if (!raw.length) break

  phase('Verify')
  const order = { critical: 0, major: 1, minor: 2 }
  const toVerify = raw.filter(f => f.severity !== 'minor').sort((a, b) => order[a.severity] - order[b.severity]).slice(0, 48)
  const minors = raw.filter(f => f.severity === 'minor')
  log(`Round ${round}: verifying ${toVerify.length} (${minors.length} minors pass to fixers as optional)`)
  const verified = await parallel(toVerify.map(f => () =>
    parallel([0, 1, 2].map(i => () =>
      agent(`${PREAMBLE}
ROLE: independent verifier #${i + 1}. Reproduce the claim yourself on the current tree (run the repro; read the cited code and the rule's documented guards in docs/ISSUE_RULES.md). Confirm ONLY if it is real at the stated severity; a finding that is by documented design (docs/CONTRACTS.md, docs/ISSUE_RULES.md, docs/ROADMAP.md 'Considered and not recommended') or a stylistic preference is not confirmed. For a claimed false positive, state whether the flagged code is genuinely correct. Do not modify repo files.
CLAIM: ${JSON.stringify(f, null, 2)}`,
        { label: `verify:${f.id}:${i + 1}`, phase: 'Verify', schema: VERDICT_SCHEMA, model: 'opus', effort: 'medium' })))
      .then(vs => ({ ...f, confirmed: vs.filter(Boolean).filter(v => v.confirmed).length >= 2 }))))
  const confirmed = verified.filter(Boolean).filter(v => v.confirmed)
  log(`Round ${round}: ${confirmed.length}/${toVerify.length} confirmed`)
  fixedSoFar.push(...confirmed)
  summary[summary.length - 1].confirmed = confirmed.map(f => ({ id: f.id, component: f.component, kind: f.kind, severity: f.severity, title: f.title }))
  if (!confirmed.length && !minors.length) break

  phase('Fix')
  const by = {}, minorsBy = {}
  for (const f of confirmed) (by[f.component] = by[f.component] || []).push(f)
  for (const f of minors) (minorsBy[f.component] = minorsBy[f.component] || []).push(f)
  const DIRS = {
    analyzer: 'analyzer/** (including the corpus labels ONLY to correct a wrong label, with the reason in the label), samples/**, contracts/validate_sample.py, contracts/scope.*.json, tools/accuracy.py, tools/accuracy_corpus.py, tools/perf_equiv.py, docs/rules/**, docs/ISSUE_RULES.md (guard text), docs/ACCURACY.md',
    webview: 'webview/**',
    'vscode-extension': 'vscode-extension/** (not media/ or core/)',
    'claude-plugin': 'claude-plugin/** (not vendor/), tools/action/**',
    'process-docs': '.github/**, scripts/**, tools/verify.py, tools/sync-core.py, tools/public_corpus.py, README.md, docs/STATUS.md, docs/CONTRACTS.md (integration of amendments only), scripts/README.md',
  }
  const TESTS = {
    analyzer: "'python -m pytest analyzer/tests -q -n 4', 'python tools/accuracy.py' and 'python tools/accuracy.py --dataflow ip' (precision must stay 100% with zero forbidden findings in both modes; recall may only rise), '--demo' byte parity, and tools/public_corpus.py check if the public corpus is fetched",
    webview: "'npm run build && npm run check && npm test' in webview",
    'vscode-extension': "'npm run check && npm run compile && npm test' in vscode-extension",
    'claude-plugin': "'python -m pytest claude-plugin/tests -q'",
    'process-docs': "'python scripts/check_docs.py' and 'python -m pytest scripts -q'",
  }
  await parallel(Object.keys({ ...by, ...minorsBy }).map(c => () =>
    agent(`${PREAMBLE}
ROLE: fixer for '${c}' (round ${round}; you do NOT run git). Fix every CONFIRMED finding at its root cause - for a false positive that means the rule's guard, never a per-corpus exception; for a false negative, the detection, with its negative fixture; for a crash, the ingest/IR path plus a regression fixture. Fix the OPTIONAL minors when cheap. OWNERSHIP: ${DIRS[c] || c}. Every fix gets a regression test. Run ${TESTS[c] || 'the relevant tests'} and paste the tail. If a fix would need a contract change, write the amendment fragment as instructed.
CONFIRMED (${(by[c] || []).length}):
${JSON.stringify(by[c] || [], null, 2)}
OPTIONAL MINORS (${(minorsBy[c] || []).length}):
${JSON.stringify(minorsBy[c] || [], null, 2)}`,
      { label: `fix:${c}:r${round}`, phase: 'Fix', schema: REPORT_SCHEMA, model: 'opus', effort: 'xhigh' })))

  phase('Integrate')
  const g = await agent(`${PREAMBLE}
ROLE: integrator (you run git; round ${round}). STEPS: 1) Append any docs/contracts/11.*.md fragments to docs/CONTRACTS.md in order and delete them; make schema mirrors byte-identical. 2) 'python tools/sync-assets.py' and 'python tools/sync-core.py'. 3) Run and fix until green (root-cause, minimal): 'sh scripts/e2e.sh'; 'python tools/verify.py --all'; 'python tools/verify.py --scopes --fuzz 200'; 'python tools/accuracy.py' and '--dataflow ip' (precision 100%, zero forbidden, in both modes; the new corpus programs are unseen and may LOWER the recall headline - that is honest and allowed: update the recall baselines to the new measured values with a dated note in docs/ACCURACY.md explaining the corpus grew from N to M programs, never by deleting labels); 'python tools/public_corpus.py check' if ${PUB} is populated; 'npx tsc --noEmit' in webview and vscode-extension. 4) Update docs/STATUS.md (a 'Hardening round ${round}' section: coverage, findings fixed, corpus growth, new gates) and scripts/README.md; keep check_docs and doc_numbers green. 5) git status; never add scratch, clones, __pycache__, .mlview, .venv, node_modules; git add -A; commit as 'Hardening round ${round}: <one-line summary> (see body)' with the fixed finding ids in the body; push with 'git push git@github.com:realmyang/MLView.git HEAD:hardening'; watch CI (gh with GH_TOKEN); fix failures (at most 5 iterations). Report gates, the accuracy headline in both modes, commits, CI.
FIXED THIS ROUND: ${JSON.stringify(confirmed.map(f => ({ id: f.id, component: f.component, title: f.title })))}`,
    { label: `integrate:r${round}`, phase: 'Integrate', schema: GATES_SCHEMA, model: 'opus', effort: 'xhigh' })
  summary[summary.length - 1].integration = g && { all_passed: g.all_passed, ci_green: g.ci_green, commits: g.commits, accuracy: g.accuracy, remaining: g.remaining_problems }
  log(`Round ${round} integration: gates=${g && g.all_passed} ci=${g && g.ci_green}`)
  if (!confirmed.length) break
}
return { rounds: summary, fixed_total: fixedSoFar.length }
