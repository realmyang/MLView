# Changelog

Every dated entry below was moved here from `docs/STATUS.md`, which is now a
short current-state page. This file is the history: newest first, each entry
condensed to what changed and the numbers that were measured at the time. The
long-form reasoning for anything normative lives in `docs/CONTRACTS.md`; the
acceptance clause each item was measured against lives in `docs/ROADMAP.md`.

Figures in a dated entry are **historical**. They were true on their date and
are deliberately not rewritten when the tree moves on — `docs/STATUS.md`,
`docs/ACCURACY.md` and `analyzer/tests/accuracy/baseline*.json` say what is true
today.

**Most entries below were written before CI could confirm them.** GitHub Actions
billing was blocked at the account level for the hardening rounds, the
consolidation and the recall campaign, so every job came back unstarted and each
of those entries is a measurement from one machine. The block went with the
repository going public on 2026-09-15: the matrix has since run green over the
tree the Unreleased entry describes — thirteen jobs, run 34986234828 and run
34986239243. Where an older entry quotes a CI run id, that run predates the
block.

---

## Unreleased — consolidation and recall (2026-09-15)

One campaign, three strands: make the tree say one true thing about itself
(**C1–C9**), close the largest known recall families (**R1–R5**), and fix what
the campaign's own review confirmed. It is built on the hardening base — the
158-program labelled corpus, the pinned public corpus and PR #4's 92 fixes are
underneath everything here, which is why several figures below are *lower* than
the ones the same items measured against a smaller corpus.

### Consolidation

- **C1 · Contracts v1.1.** `docs/CONTRACTS.md` is rewritten as one coherent
  document rather than a v1.0 body with a hundred-odd amendments bolted to the
  end of it: every amendment is folded into the section that owns its clause,
  including the hardening rounds' §11.50–§11.61, and an amendment index says
  where each numbered item went. The amended v1.0 is archived verbatim under
  `docs/archive/` so no decision record is erased.
- **C2 · The VSIX analyzer copy is a build artifact.** `vscode-extension/core`
  is gitignored and written by `vscode-extension/tools/sync-core.mjs`, which
  `compile`, `pretest` and `vscode:prepublish` all run. `claude-plugin/vendor`
  stays **tracked**, and for a reason rather than by omission: a marketplace
  install copies the plugin directory verbatim off a git ref, so for that host
  what git holds is what the user runs, while a VSIX is built from a working
  tree. `tools/sync-core.py` gained a `generated` flag, `tools/verify.py`'s
  `vsix` row is strict, and a test asserts the directory is untracked.
- **C3 · No source file over 750 lines.** Every one that was is split into
  cohesive modules under 600, with re-exports so no importer changed and
  **byte-identical outputs**: `tools/perf_equiv.py --expect-same` against a
  reference tree of `origin/sprint5` after each of the thirteen analyzer splits,
  an AST comparison finding all 451 definitions byte-for-byte the reference's,
  and — for the viewer's five CSS layers — the minified concatenation identical
  at 73 127 B before and after. That proof was taken **at the split**, against a
  tree recall had not yet touched; recall then re-based the graph deliberately,
  so `--expect-same` is no longer the right question to ask of this commit and
  `--demo` byte parity, the two accuracy ratchets and the public-corpus gate are.
- **C4 · The docs say one thing each.** `docs/STATUS.md` is a short
  current-state page; this file is the history it used to carry; `README.md` is
  trimmed to what a reader needs before they trust an answer.
- **C5 · `.workflows/` leaves the index** and is gitignored: a scratch directory
  for this project's own agent runs is not part of the product.
- **C6 · CI in two tiers**, because the repository is private and minutes are
  metered. A branch push runs the analyzer on Python 3.10 and 3.13, the viewer on
  Node 20, both host suites, the accuracy corpus and the Linux e2e table; a pull
  request and a push to `main` add Python 3.11 and 3.12, Node 22, the Windows
  e2e table, a macOS smoke job and packaging. A push that touches only Markdown
  and `docs/` runs nothing. The public-corpus nightly is unchanged.
- **C7 · `LICENSE`** — MIT, Copyright (c) 2026 realmyang. The VS Code
  Marketplace pre-flight requires one and this repository had none.
- **C8 · Four honesty fixes.** The `--framework` caveat reaches **both** hosts'
  coverage blocks, so a narrowed rule set can never be read as a cleaner project;
  `Escape` closes the legend, which needed a rung on the dismissal cascade
  §11.13 freezes rather than a line of code; the parse cache defaults to the
  **user's** cache directory rather than `.mlview/cache` inside the folder being
  analyzed (`MLVIEW_CACHE_DIR` overrides it, `MLVIEW_NO_CACHE=1` disables it);
  and SARIF output carries `fixes[]`.
- **C9 · Two runbooks.** `docs/VALIDATION.md` is the step-by-step for validating
  MLView by hand on a second machine and then publishing it — every command in
  both a POSIX and a PowerShell form — and `docs/DEMO_LOG.md` is the template the
  validator fills in as they go.

### Recall

- **R1 · `--dataflow ip` is the default.** `local` stays as the narrower
  opt-out; `--demo` output is byte-identical either way, so the frozen golden did
  not move.
- **R2 · Five more knowledge tables** — pandas, `evaluate`, Keras,
  statsmodels/Prophet and torchmetrics — so the graph stops losing the ops those
  libraries name.
- **R3 · Calls through workspace objects**, which has been the largest single
  recall family since ANA-1: construction nodes, `__call__` → `forward`,
  workspace loss classes, factory returns, carriage through dicts, tuples and
  dataclasses, `self.<attr>` across methods, and identity through
  `accelerator.prepare` / `fabric.setup` / `torch.compile`. The first two of
  those three keep their types through `ir/bindings_values._self_wrapped` rather
  than through a knowledge row asserting *position i out is argument i in* — the
  narrower claim, and the reason `WRAP_PREPARE` is deliberately absent
  (`docs/CONTRACTS.md` §19 A2).
- **R4 · Value typing.** `LOGITS` / `PROBS` / `PREDS` flow into MLV305, MLV306,
  MLV401 and MLV402, with confidence de-rated per hop.
- **R5 · The rule shapes that were missing.** Three interprocedural leakage
  walks — MLV101 through a `return`, MLV102 through a fold index, MLV103 through
  a callee, all `ip`-only — plus MLV208 learning to find its `GradScaler` by
  identity as well as by proximity. **MLV114 needed nothing**: this base's rule
  was already a strict superset of what the campaign had written for it, and the
  honest entry says so rather than claiming a fix that was not made.

### Review fixes

Confirmed by the campaign's own review, one fix each:

- **A marketplace entry that installed a directory with no plugin in it.** The
  `github` source form takes `repo` / `ref` / `sha` and **no `path`**: the
  fetched tree's root becomes the plugin root, and this repository's root holds a
  marketplace manifest and no `plugin.json`. The hosted entry is `git-subdir` at
  `path: "claude-plugin"`, and `claude-plugin/tests/test_plugin_manifest.py` now
  asserts that **every** entry's resolved directory really contains
  `.claude-plugin/plugin.json` — the class, not the instance.
- **R13 / R15 read a `return` only when it bound a name first**, so
  `return scaler.fit_transform(frame)` missed while `out = …; return out` hit.
- **R3's carriage did not compose with a parameter boundary**, which is the
  GradScaler-in-a-parameter-dict the campaign named.
- **A `file://` report click killed the keyboard.** Handing a URL to the OS
  protocol handler costs the *launching* browsing context its keyboard,
  permanently, so a hand validation of the viewer read as broken from its second
  step. The launch now goes through one named transient context, and a refused
  launch is answered at once rather than after a silence that read as success.
- **R18's MLV205 widening produced three public-corpus false positives.** The
  guard is kept; the widening is not. A high-severity claim about correct code is
  the worst outcome this product has, and the public corpus is the only gate that
  can see one nobody thought to label.
- **The `--framework` caveat did not reach the hosts' coverage blocks** —
  C8's first clause, listed here too because it was found by review rather than
  planned.

### Review round 2 — the rebuild's own review, process and docs

The rebuild was reviewed again on its real base. Five findings were confirmed
against the process-and-docs surfaces; each is fixed at its cause and, where a
check could have seen it, a check now does. The doc gate is **twenty-three
checks**, up from twenty-one.

- **The doc gate's check 22 was cited by the contract and absent from the
  tree.** `scripts/doc_claims.py` — the gate that forbids a green claim and the
  CI matrix in one breath without saying whether the matrix ran — was written
  during the first campaign and never carried onto this base, while
  `docs/CONTRACTS.md` §16.4 and §17 E28 both asserted it was running (**no CI
  job has started on this line of work at all**, which is the whole reason the
  check exists). It is back
  as **check 22** (it collided with `doc_surfaces`' check 16 before), wired into
  `check_docs.run`, and `scripts/test_doc_claims.py` now pins two things the
  first round could not: that the module is *wired in* rather than merely
  present, and that `docs/CONTRACTS.md` names no `scripts/*.py` missing from the
  tree — CONTRACTS is in `check_docs.SKIP` by design, which is exactly how a
  contract came to name a file that did not exist.
- **§7's `mlview diff` figures were three mutually inconsistent sets.** The
  prose said 25 / 15 / 8 / 31 and named `python -m mlview diff` as the authority;
  the authority says **26 / 15 / 8 / 36**, edges **27 / 22 / 1 / 28**, headline
  `+26 nodes · −15 nodes · 0 new findings · 15 fixed`, and both pinning tests had
  already been updated to say so. The section's own JSONC sketch carried a third
  set again. All three are corrected, §17 E36 stops restating a live figure, and
  new **check 23** holds §7 to `analyzer/tests/core/test_diff.py` — the one place
  the doc gate reads CONTRACTS, anchored on the `## 7.` heading so §17's errata
  keep quoting the superseded figures they exist to record.
- **`docs/VALIDATION.md` C5 named a coverage row that never appears.** A
  `--framework` run emits one coverage row and its kind is `framework_filter`;
  `framework_suppressed` appears only in the bare `diagnostics` tally, the same
  cost stated twice (§11.4 C3). A validator checking the kind would have recorded
  a fail against correct behaviour on the one row that exercises C8 end to end.
- **§4.0 prescribed `python tools/wheel_check.py --sdist`, a flag that does not
  exist.** The tool takes `--no-build` and nothing else. The line is gone and the
  gap it papered over is stated instead: **the sdist is published untested** —
  nothing in the repo or in CI builds or smoke-tests one — with the by-hand
  equivalent written out, because a version can never be re-uploaded.
- **B2 told the validator the standalone report "cannot open your editor".** It
  can, and for exactly the report Session B produces: `deepLinkPlan` returns
  `launch` for a top-level `file:` document and hands the `vscode://` URL to the
  OS through a transient window it closes after ~700 ms. Only an embedded or
  `http(s)` report copies. The row now describes both outcomes and says which one
  is the fail (silence).

Four minors went with them: §18's amendment index is total again (§7.1–§7.5 and
§10 had no rows), §2.6 C9's gate citations name the three tests that exist — two of
which read the analyzer's own declaration, while the extension's is a hardcoded
transcription and is recorded as a stated gap — §14.2 R19 says where its negative fixtures actually live, and the five
clauses §19.1 corrects now say so where a reader meets them. The stale counts
that no check reads — "24 third-party repositories with 26 shell scripts", the
VSIX row's 162 files / 110 core files — are replaced by the constant or the
command that settles them rather than by newer numbers.

### Review round 3 — the analyzer and the viewer, read against the contract

The same review read the build against `docs/CONTRACTS.md` rather than against
its own diff, and confirmed ten more. **Eight of the ten are the contract being
right and the code being wrong**: the clause was written, folded and shipped as
prose, and nothing in the tree ever asserted it — which is §16.4's stated gap
(no gate compares the contract to the build) arriving as ten defects at once.
Every one is now gated by a test that reads the analyzer's **own declaration**
rather than a transcription of it, and the clauses are folded as
`docs/CONTRACTS.md` **§19.4 A9–A19**.

- **A `--framework`-narrowed run still returned a flat clean bill of health.**
  C8 put `framework_filter` in the core and in two hosts' coverage blocks and
  never in `emit/answers_text`, the tuple the Answer Card, the MCP `answers`
  payload and the CLI `verdict:` row are all built from. On
  `samples/vision_pipeline_clean` the verdict under `--framework torch` was
  byte-identical to the verdict under `--framework auto` — *"No findings: no
  rule fired on this workspace."* — with a coverage block one screen below it
  naming five rules that did not run. The verdict now carries both admissions in
  one sentence and counts a filter in **rules**, never folded into a blind-spot
  total.
- **The viewer read two of the core's three coverage kinds**, and its own extra
  as the third. On the same project the rail said *"nothing to flag"*, drew zero
  banners, and put the whole caveat into one **287-character** generic chip. It
  now draws a 38-character chip, a clause in the coverage banner and the rail's
  clean-state caveat, and `webview/test/hardening_coverage_kinds.test.mjs`
  **parses** `core/coverage.py` so the next kind the core adds cannot drift out
  of the viewer silently.
- **Both slash-command prompts told the model to read a coverage row this host
  never renders** — `framework_suppressed` where a `--framework` run emits
  `framework_filter`.
- **A criterion reached through a dataclass field or a constructor parameter
  never earned the LOSS role**, so MLV201 / MLV202 / MLV203 / MLV205 — two of
  them high — all skipped the training step behind a coverage note. §5.3 A11 (c)
  and (d) were contractual and unimplemented; what travels is now the field's
  **identity**, not only its tag. Deliberately **not** extended to a plain
  parameter: doing so made `x.size()` resolve to `torch.nn.LayerNorm.size` and
  cost `nlp_gpt_pretrain` two dataflow edges `local` draws, and `ip` must never
  report less than `local`.
- **A dict returned from a factory did not carry its entries**, though the same
  dict written in the caller's own scope did, because the inferred half of
  `unresolved_callee` was written once instead of recomputed each IR round —
  which A12′ already said in as many words. MLV208 was the finding lost.
- **R4's value tags died at a tuple-position `return`, and its three hops were
  being spent on things that cross no object.** A per-batch helper, a collector
  and a `.detach().cpu().numpy()` tail spend four between them, so MLV305 went
  silent two *object* hops from a value that reaches `accuracy_score` with no
  argmax. A hop is now **crossing an object**; the free links have their own
  bound.
- **MLV103 fired or stayed silent on whether the caller happened to reuse the
  callee's argument name**, and a bare `return pca.fit_transform(X)` was silent
  where the two-line spelling fired — R13's third form, which R15 claims to read
  as well. A returned call contributes its operands and not its callee text, and
  §19.1 A5's ambiguity guard is narrowed to the tuple-or-list returns it was
  measured on. The precision case it exists for is pinned by name.
- **MLV111 still read `call.var`** where MLV110 had been given the one-hop name
  lookup, so a program that inverts both shuffle flags behind two factories
  reported only its MLV110 half. MLV111 requires **every** name the construction
  is bound to to read as an evaluation loader; a name may reinforce and never
  create.
- **C3's split of `analyzer/tools/gen_rule_docs.py` was lost** — 850 lines,
  while two documents claimed the 750-line inequality. Split along the line the
  rule codes already draw (253 / 333 / 323) with byte-identical output.
- **`analyzer/LICENSE` was the third copy C7 never landed**, and
  `analyzer/pyproject.toml` named no `license-files`, so the wheel a validator is
  walked into publishing carried **no licence file at all**.

**What moved on the corpus**, both readings up and both ratcheted: visible recall
72.3% → **72.5%** (`ip`) and 70.5% → **70.7%** (`local`), with MLV110's `visible`
column 21 → 22 — all of it earned by §5.3 A11 (d), measured by disabling that one
fallback and watching both numbers go back. The other fixes move no corpus number,
because the 158 programs do not spell those shapes; each is gated instead by
`analyzer/tests/core/test_campaign_review_fixes.py` — 23 tests, one per confirmed
finding, each a **pair** of programs differing only in the thing MLView should not
have cared about.

### What it measured

Over the 158-program labelled corpus, **precision stayed at 100.0% with zero
forbidden and zero unlabelled findings in both dataflow modes** — which is the
number that had to hold, because every point of recall below was bought without
one false positive.

| | before | after |
|---|---|---|
| Recall, `ip` (546 labels) | 79.1% | **80.4%** |
| Recall, `local` (546 labels) | 77.8% | **78.2%** |
| Recall, `ip`, the 515 unseen labels | 77.8% | **79.2%** |
| Graph fidelity (1166 hand-labelled ops) | 84.5% | **91.9%** |

Per rule, `ip`: MLV103 22.2% → **44.4%**, MLV208 14.3% → **28.6%**, MLV305
14.3% → **20.0%**, MLV402 27.3% → **36.4%**, MLV101 71.0% → **77.4%**, MLV102
60.0% → **70.0%**. The shipped sample pair moved together — `vision_pipeline`
54 → 59 nodes and `vision_pipeline_clean` 64 → 70 — with **no finding moved**:
all 15 keep their code, line, severity and confidence.

The cost is stated rather than hidden: the interprocedural summary pass now runs
on every unflagged run, and `tools/perf_equiv.py --bench` measures 0.76–0.84×
against an `origin/sprint5` reference on 4-, 50- and 200-file corpora. Roughly a
fifth of that is the `ip` default and the rest is R3's extra graph pass.

### Public readiness

The repository went public on 2026-09-15, and this is what that took. **No
machine is named in the tree any more**: the golden document's workspace root
moved from a real Windows home directory to the neutral `/home/mlview/MLView`,
and every artifact derived from it was regenerated with the repository's own
generators, so the golden, its two mirrors, `contracts/scope.expected.json`, the
plugin vendor copy and the webview dev page still agree and `analyze --demo` is
still byte-identical — at **45 588** bytes now rather than 46 078, because the
shorter root shortens every absolute path the document carries. Notes dated
before this round, here and in `docs/CONTRACTS.md`, quote the larger figure and
were true when written. Two path-traversal test payloads that carried the author's
username now use the `Users/someone` convention. The frozen v1.0 spec keeps its
historical path on purpose; `docs/archive/README.md` says why. A scan of every
commit on every ref found no secret and no email but git author metadata.

`THIRD_PARTY_NOTICES.md` is new and records the whole redistribution surface —
`@dagrejs/dagre` 3.1.1 and `@dagrejs/graphlib` 4.0.5, MIT, verbatim, and which of
the four artifacts carries them. The wheel is not exempt: it declares no Python
dependency but ships `emit/assets/mlview.js` with dagre inlined. `CONTRIBUTING.md`,
`CODE_OF_CONDUCT.md`, `SECURITY.md`, four issue forms, a pull-request template,
`.editorconfig`, `docs/README.md` and `docs/CONTRIBUTING-RULES.md` landed with
it, each written from the tools rather than from a template. `README.md` became a
landing page — badges, three screenshots of the shipped sample under
`docs/media/`, a quick start per host, the rule families, the measured accuracy
table and the known gaps.

`.gitattributes` gained a `diff` attribute for source extensions, which fixes a
real defect rather than a preference: `webview/src/diff/adopt.ts` embeds literal
NUL bytes as string-join separators inside git's 8000-byte binary-detection
window, so `git diff` printed *"Binary files … differ"* for a TypeScript module.
`.gitignore` gained `/.mlview.toml`, which MLView writes into its own checkout on
every e2e pass.

Six documents were corrected because the matrix finally ran: `README.md`,
`docs/STATUS.md`, `CONTRIBUTING.md`, `docs/VALIDATION.md`, the pull-request
template and this file all said, in their own words, that the CI matrix had never
run on this line of work. That was true when written and false once thirteen jobs
came back green, and the doc gate could not catch it because *"the matrix has not
run"* was the one escape check 22 implemented — so the check now also accepts a
cited `run <id>`, and the documents cite one. `docs/ACCURACY.md` §1 still opened
on the 92-program corpus; it holds 158.

**Gates, local first and then on CI.** Every figure here was measured on this
Mac (macOS 26.6, Python 3.13, Node 26) while Actions billing was blocked at the
account level; the matrix confirmed the tree afterwards, on the `public` → `main`
pull request — thirteen green jobs over Ubuntu, Windows and macOS, Python 3.10
through 3.13 and Node 20/22 (run 34986234828 and run 34986239243), both green on
their first attempt; the one fix iteration belongs to the branch's first
pull-request run, 34974162339, whose four failures were all one test-side
assumption about Windows drive letters. `sh scripts/e2e.sh` 20 steps, all green;
`python tools/verify.py --all` 10 rows; `python tools/verify.py --scopes --fuzz
200` 5 rows; `python tools/accuracy.py` and `--dataflow local` over the
158-program corpus, both PASS; `python tools/public_corpus.py run` then
`check --strict` over the 37 pinned repositories — 260 runs, 260 clean,
49 high / 276 medium / 381 low, **no new high-severity finding**; `mlview analyze --demo` byte-identical to
`contracts/graph.sample.json` at 45 588 bytes; `python scripts/check_docs.py`
**DOC CHECK OK**. Suites: analyzer 2654 passed / 9 skipped / 24 xfail, webview
599 (598 pass, 1 todo), vscode-extension 415, claude-plugin 479 passed / 7
skipped, scripts 146. Every row was run once at the rebuild and again after
the review fixes below; the figures are the second run.

### Public review round — the documented setup, the gate table, the CI claims

The first review of the tree as a stranger meets it: a clone built by following
`CONTRIBUTING.md` line by line, and every CI and accuracy claim re-measured.

**The documented setup did not run the gates it promised.** `analyzer` declares
`dependencies = []` and puts pytest and jsonschema behind a `dev` extra, so a
venv built exactly as §1 said — `pip install -e analyzer` — had no pytest, no
jsonschema, no `mcp` SDK and no `build`, and `sh scripts/e2e.sh`, the next
command on the page, answered `20 steps · 3 failed` on a correct tree. CI never
hit it because the e2e jobs install those packages by name. Every setup block in
`README.md`, `CONTRIBUTING.md`, `docs/STATUS.md` and `docs/VALIDATION.md` now
reads `pip install -e "analyzer[dev]" mcp build`, with the reason next to it, and
each names `python3 --version` first because macOS's `/usr/bin/python3` is 3.9
and the package refuses it.

**Two gate rows lied in opposite directions.** `tools/verify.py --all` turned a
missing optional SDK into `FAIL parity: CLI vs MCP — No module named 'anyio'`
and exit 1 — the one red row a newcomer saw was the one that meant nothing — so
a gate that cannot run now reports **SKIP** with the one-line fix and does not
set the exit status. `vendor: synced core` was built only on that gate's success
path, so any parity failure served **nine** rows where four documents promise
ten, with the row `CONTRIBUTING.md` sends plugin contributors to read simply
absent; it is computed first now and printed on every path. In the other
direction, `tools/wheel_check.py` exited 0 when there was no wheel to test and
both e2e drivers recorded `PASS wheel installs and runs` over a check that had
done nothing — in every e2e job this project has ever run, including the green
ones the README cites, because neither e2e job installed `build`. The tool exits
**3** for that case, both drivers record `SKIP` with the reason, both e2e CI jobs
install `build`, and `scripts/build.{sh,ps1}` says `BUILD OK — 5 of 6 steps
(wheel skipped)` rather than claiming six.

**The docs contradicted each other about CI and about accuracy.**
`docs/STATUS.md` still said, in the present tense, that Actions was
billing-blocked and that *"no claim of a green CI run is made anywhere in this
repository"* — eighty lines above its own paragraph naming thirteen green jobs,
and while four other documents named the runs. `docs/README.md`, the index every
document link goes through, ended its description of the doc gate with *"which,
on this line of work, it has not run at all"*. `docs/VALIDATION.md` told the next
validator both scheduled workflows had never run and that billing was blocked;
both are on `main` and each has been proved by dispatch (nightly run
34984606964, public corpus run 34982508080 at 260 runs, 260 clean). §16.4 of the
contract still carried *"not yet by measurement"* as live normative text. And
`docs/STATUS.md` said the public corpus had caught **four** false positives where
`adjudication.json` holds eleven and `README.md` says eleven — a factor of nearly
three on the number that is the whole argument for that gate.

**Both halves are now gated, because prose that drifts once drifts again.** The
doc gate is **twenty-five checks**. Check 22 gained its mirror: once a living
document names a run that was green, no living document may assert the matrix has
not run. Check **24** holds any prose count of the public corpus's false
positives to `analyzer/tests/public_corpus/adjudication.json`, reading
spelled-out numbers and the shape that states the figure without repeating the
noun. Check **25** holds the versions in `THIRD_PARTY_NOTICES.md` — until now the
one public-facing file no check read at all — to the packages under
`webview/node_modules`, abstaining where they are not installed. Both new checks
carry the meta-escape check 22 needed: a paragraph that documents the rule is not
a claim about the tree.

Smaller: the Python badge said 3.11+ against a `requires-python = ">=3.10"` that
CI exercises on 3.10; the hero screenshot's alt text described eight stage bands
where seven are drawn and the eighth is the one the sample does not have (which
is a feature of the viewer, so it says so now); the README credited a fix
iteration to two runs that were green first time; `docs/ROADMAP.md`, linked as
the backlog a contributor picks work from, sized that work in agent-days;
`project.md` was indexed nowhere and is now in `docs/README.md` as what it is;
`SECURITY.md`'s preferred route was GitHub private vulnerability reporting, which
is **disabled on the repository**, so step 1 is conditional on the button being
there until the setting is turned on; and `docs/STATUS.md` records, as a standing
gap, that the git history still carries the old orchestration scripts with their
absolute paths — a decision taken rather than an oversight, since rewriting
history on a public repository breaks every clone.

**Gates after this round**, on this Mac: `python scripts/check_docs.py`
**DOC CHECK OK (21 files)**; `python -m pytest scripts -q` **146 passed**;
`python tools/verify.py --all` **10 of 10**; `sh scripts/e2e.sh` **20 steps, 0
failed, 0 skipped**; `python tools/accuracy.py` PASS in both dataflow modes;
`python tools/public_corpus.py check --strict` gate OK over the 37 pinned
repositories. The matrix has not run on this round's commits yet.

---

## Hardening rounds 1 and 2 (2026-09-14)

Not a sprint. The brief both times was *"test the current implementation
extensively and carefully; besides fixing bugs, focus on coverage over all
possible ML/DL code — test against public repos, construct code that mimics real
ML/DL applications"*, and the product's standing rule decided what counted as a
failure: **a high-severity false positive on correct code is the worst outcome,
and silently misrepresenting code — a stage claimed absent, a call dropped, a
crash swallowed — is the second worst.** Both happened, repeatedly.
**104 findings fixed** across the two rounds, and fourteen contract amendments,
§11.50–§11.61.

**What the two rounds built, and left behind as gates:**

| Surface | Round 1 | Round 2 |
|---|---|---|
| Public repositories | **24 pinned repos** at exact SHAs, 90 targets × 2 dataflow modes = 180 runs; `tools/public_corpus.py` (`fetch` / `run` / `check`) and `analyzer/tests/public_corpus/` | **37 pinned repos** — the round-1 set plus thirteen, none removed — 112 targets × 3 modes (`local`, `ip`, `--include-notebooks`) = **260 runs** |
| Written ML/DL code | **77 new labelled programs, 188 source files**; the corpus goes 15 → **92** programs, 78 → **312** expected labels, 125 → **1229** forbidden labels | **66 more**; 92 → **158** programs, 312 → **545** expected, 1229 → **2327** forbidden, 614 → **1166** hand-drawn graph ops |
| Robustness | a deep-but-legal AST, a FIFO named `*.py`, a symlink to `/dev/zero`, an unreadable directory, `from x import *`, duplicate `Issue.id`s | binding shapes (tuple parameters, dict literals, `functools.partial`, factory returns), notebook magics, package walking, report escaping — `test_round2_analyzer.py` + `test_round2_core.py`, 64 cases |
| Hosts and the renderer | 16 real repositories rendered in all three hosts; every MCP argument driven out of range | the **built** viewer mounted in jsdom over 260 public-corpus documents and 158 corpus documents; every accepted `framework=` value against the rule registry (26 cases) |
| The tree itself | which selectors are advertised, which directories a tool writes into, which test files `npm test` runs — doc-gate checks 16–18 | the command lines CI generates, the exclusive rule lists a document asserts, a known gap that names its own retirement condition — checks 19–21 |

**The worst class was the largest, both times.** Round 1 opened with **five
forbidden findings** — high-severity claims about correct code that the labelled
corpus explicitly forbids — and precision **97.6%**; round 2 opened with
**eight** and **97.9%**. It closes at zero forbidden, zero unlabelled and
**100% precision in both dataflow modes**.

**Two findings were made by the integration itself, and they are why the
public-corpus gate exists.** With every round-1 fix in the tree,
`public_corpus.py check` refused the build on two NEW high findings, neither
reachable from 312 labels: **PUB-15**, MLV101 reporting a `certain` leak in a
scikit-learn example because the rebinding guard read assignment targets through
`dotted_text`, which is empty for an `ast.Tuple` — so `X, y = load_iris(...)`,
the way scikit-learn binds data, was invisible to it; and **PUB-14**, MLV102
calling a `KNeighborsClassifier` "the transformer" on a notebook cell that is
*teaching* two-fold cross-validation. Both cost nothing: every accuracy figure
identical to four decimal places in both modes.

**Round 2's own integration arrived with a red test file**, which is an honest
hand-off and a blocking one. The four it named: a `pointerdown` on the legend
started a canvas pan and took pointer capture, so the panel's close button worked
from the keyboard and not from the mouse; an unwrapped workspace-relative path
painted one answer over the answer beside it on 7 of 90 real reports; the scope
picker's unit and group rows promised the match set while the click delivered the
projection (`unit:train.train` offered 4 nodes and drew 9), fixed by running the
same `project()` the click runs — 819 ms → 101 ms on a 222-row picker over a
400-node repository; and the Issues rail saying *"No issues found — nothing to
flag"* over a run whose own banners said it had been blind. Measured over the 260
pinned documents: **122 draw the clean state, and 118 of them were drawing it
over a blind run.**

**Recall fell, then rose, and both readings are the honest ones.** Round 1 had to
report a fall — 73.1% → **72.4%** raw — because 77 of its 92 programs were new,
unseen and harder than the fifteen the rules were developed against; scored over
those original fifteen alone the same build reads **75.6%** and the whole
previous gate passes. Round 2's 66 new programs are just as unseen and every
aggregate rose anyway: `local` **72.4% → 77.8%**, visible 66.7% → 70.1%,
high+medium 64.5% → 70.7%, unseen 69.4% → **76.5%**; `ip` 76.3% → **79.1%** with
unseen 73.7% → 77.8%. Both baselines were re-recorded with `--allow-regression`
and the reason written into each file's own `note`, never by deleting a label.
No rule carries a tuned `*` any more: all 36 have at least one label in a program
nobody wrote for them.

**Round 2's closing gates, on this Mac.** `sh scripts/e2e.sh` **20 steps, 0
failed, 0 skipped**; analyzer **2574 passed / 9 skipped** (2405 / 7 at round 1's
close, 2087 / 4 at the Sprint-5 close); webview **585 tests** (561, 534);
vscode-extension **404** (401, 377); claude-plugin **460 passed / 7 skipped**
(434, 373); `pytest scripts` **119 passed** (99, 74); `npx tsc --noEmit` clean in
both TypeScript packages; `tools/verify.py --all` **10 of 10**;
`tools/verify.py --scopes --fuzz 200` **5 of 5**; `tools/accuracy.py` **PASS** —
precision **100.0%** on 36 rules over **158 programs and 545 labels**, recall
**77.8%**, unseen **76.5%**, graph fidelity **84.5%** (985 of 1166), zero
forbidden and zero unlabelled; `--dataflow ip` **PASS** at **79.1%** / unseen
**77.8%**; `public_corpus.py fetch && run && check --strict` **gate OK** — **260
runs, 260 clean**, 36 s of wall at `--jobs 8`, slowest single run 17.9 s against
a 60 s budget, 50 high / 276 medium / 376 low, zero tracebacks, zero schema
errors. CI run 34815166539 (round 2's last push before the billing block): all 12
branch jobs green, 15m39s wall, ~87 billable minutes.

**What the two rounds did not close**, named rather than averaged away: a model,
criterion and optimizer arriving as parameters still cost a training step its
forward, loss and backward nodes; `--dataflow ip` still reports a strict subset
of `local` on one mlflow example, so `local ⊆ ip` is not yet true; Escape still
did not close the legend, because `dismissTopmost` runs the cascade §11.13
freezes; and twenty-two points of recall were still missing, largest first —
MLV208's `GradScaler` through a parameter dict, MLV305 needing a prediction to
carry `LOGITS` or `PROBS`, and a model built by a registry
(`build_from_cfg("model", cfg)`) still being untyped. The campaign above is the
answer to that list.

---

## Sprint 5 — the LATER tier of the roadmap (2026-09-10)

Interprocedural dataflow, structured fixes, one configuration surface, analysis
comparison, node-budget rollup, pipelines, cross-lane bundling, and the process
work around them. `docs/CONTRACTS.md` §11.35–§11.47 are the amendments.
`schemaVersion` stayed `"1.0"`, `contracts/graph.sample.json` never moved, and
`python -m mlview analyze --demo --json -` stayed byte-identical to it at
46 078 bytes through every wave.

**Analyzer and viewer**

- **DATAFLOW-IP** (§11.36) — `analyzer/src/mlview/ir/summaries.py` adds a
  fixed-point interprocedural pass (constructor, return, method-argument
  intersection and subscript projection summaries) behind `--dataflow {local,ip}`
  with `local` the shipped default. `local` is byte-identical *by construction*:
  every new path is reached only from `workspace.dataflow == "ip"` or from a
  non-empty `ValueRef.provenance`. Confidence is arithmetic, not a promise —
  `rules/confidence.py` weights one `cross_file` evidence `0.8 ** hops`, so
  MLV101's 0.95 prior reads 0.760 at one hop and 0.486 at three. Measured:
  recall 71.8% → **78.2%** overall and 53.2% → **63.8%** unseen, precision 100%
  in both modes, zero forbidden findings.
- **PERF-03 / CACHE become the default** (§11.39) — `DEFAULT_RELEVANCE` is
  `"ml"`, which turns the fact cache on with it. `tools/perf_equiv.py
  --expect-same` re-proved byte-identity on all three corpora. On a 501-file
  mixed corpus: 2 920 ms (`--relevance all`) → 1 237 ms cold → **547 ms warm**,
  same 148 findings. The honest cost: a default run now writes
  `<root>/.mlview/cache/`.
- **CFG-ONE** (§11.37, §11.45) — `core/config.py` is the only parser:
  `--config FILE`, else `<root>/.mlview.toml`, else `[tool.mlview]` in
  `pyproject.toml`; first match wins outright and is named in
  `workspace.configPath`. TOML wins for `disable`/`exclude`, flags win for
  `[analysis]` and `min_confidence`, every mistake is one `config_warning`.
  `mlview init` writes a commented file listing all 36 rules from the registry.
- **ANA-10** — in-Python config resolution: module-level dict literals,
  dataclass field defaults, `argparse` defaults and the chains rooted at them
  resolve to literals. Measured A/B: overall recall **71.8% → 73.1%**, unseen
  **53.2% → 55.3%**, graph fidelity 126 → **127 of 139**; in `ip`,
  78.2% → **79.5%** and unseen 63.8% → **66.0%**.
- **H5, structured fixes** (§11.42) — `analyzer/src/mlview/rules/fixes.py` is the
  only module that constructs a `TextEdit`; 31 of 36 rules are byte-identical.
  Rules opt in, every position comes from an `ast` node, nothing below the
  `likely` bucket is offered an edit, and nothing in the analyzer writes to a
  file. Finding-neutral by construction: `tools/accuracy.py` identical to the
  character with and without the field.
- **VIEW-08, `mlview diff`** (§11.38) — a separate `mlview-diff` overlay keyed on
  the §0 stable ids: per-node/edge `added|removed|changed|unchanged`, per-issue
  `new|fixed|persisting`, and a `notes[]` block naming every reason a `removed`
  might not mean "deleted". A move is not a change. Over the sample pair:
  **+26 / −16 nodes, 11 changed, 27 unchanged, 0 new findings, 15 fixed**.
- **PERF-04, rollup** (§11.46) — `core/rollup.py` makes `--max-nodes` a zoom
  level instead of a guillotine: a unit absorbs its ops, a file folds, then a
  directory, and only then the old deletion order. `samples/vision_pipeline` at
  `--max-nodes` 400 / 40 / 20 / 8 gives **54/51, 38/40, 12/18 and 7/4**
  nodes/edges with **15 issues (5 high / 6 medium / 4 low) in all four**.
- **MLV-P12, pipelines** (§11.47) — the root `pipelines[]` block plus a
  `pipeline:<entrypoint>` selector. A single-entrypoint workspace is
  byte-identical to before.
- **VIEW-04, cross-lane bundling** — `layout/channel.ts` plans one trunk per lane
  pair and nests rather than braids; `layout/bundles.ts` draws the common run
  once with a member count. Crossings per edge **3.82 → 1.96** on the 54-node
  demo and **44.55 → 30.47** on a 300-node synthetic. A bundled cable's severity
  marker is never faded.
- **HEALTH-02 grows** — `analyzer/tools/scope_gen_projections.py` generates
  rolled-up and multi-pipeline documents. It found two real divergences within an
  hour, including `exclusiveCount` disagreeing on 17 of 40 graphs; §11.47 D is
  the normative reading, and two counterexamples were promoted into
  `contracts/scope.cases.json` (three → five).

**Hosts**

- H10 multi-root: one graph per open folder (`vscode-extension/src/folders.ts`),
  the Problems panel publishing the union, `MLView: Select Active Folder`.
- The three language-model tools take the whole selector grammar, described in
  the MCP docstring's own words and asserted against it.
- H5's fix preview, VIEW-08's three comparison commands
  (`vscode-extension/src/compare.ts`), and `mlview_graph {scope: "diff"}` — a
  sixth *value*, not a sixth tool. Still exactly five MCP tools.
- H8: `PostToolUse` / `Stop` hooks under `claude-plugin/hooks/` that speak only
  when the issue set grew, at most 5 rows, under a 3-second budget.

**Process**

- CI-MACOS-01: `smoke (macos)` was red on a wall-clock *ratio* assertion that
  read 1.15x–2.50x across runs of the same commit. The delta test now asserts
  what the cache controls, as counts — `("none", 0, 501)`, `("partial", 500, 1)`,
  `("full", 501, 0)` — with wall clock held to a ceiling.
- PROC-12: `webview/test/export_svg.mjs` became the e2e table's 20th step;
  `scripts/doc_numbers.py` check 11 holds every "N steps" claim to what the two
  drivers print.
- §11.35 is an erratum, not an edit: §11.19's "54 nodes and 52 edges" predates
  REV-06 dropping the one backwards data edge. §11 is append-only.
- Review round: three new doc-gate checks in `scripts/doc_figures.py` — the
  `docs/STATUS.md` Components table against that file's own newest `**Gates`
  paragraph, any scope-battery size claim against `contracts/scope.cases.json`,
  and two documents naming different runs as "the last full green push".

**Review fixes (19 findings).** Five were high-severity false positives — MLV101
matching a split by *name* across two functions, MLV121 taking the *absent*
branch for a `reshuffle_each_iteration` it could not read, and three more — each
fixed at its source with no assertion weakened. Three defects were reachable only
from CI: a stray `.mlview` sidecar copied into both vendored cores (now skipped
by `tools/sync-core.py`), two `analyzer (py3.10)` tests asserting behaviour the
CFG-ONE fix removed, and a plugin test that was a race rather than a test.

**Sprint 5 final gates, on this Mac.** `sh scripts/e2e.sh` **20 steps, 0 failed,
0 skipped**; analyzer **2087 passed / 4 skipped** (1722 / 3 at the sprint
baseline); webview **534**; vscode-extension **377**; claude-plugin **373 passed
/ 7 skipped**; `pytest scripts` **74 passed**; `tools/verify.py --all` **10 of
10**; `tools/verify.py --scopes --fuzz 200` **5 of 5**; `tools/accuracy.py`
**PASS** — precision **100.0%** on 36 rules, recall **73.1%**, unseen **55.3%**,
graph fidelity **91.4%** (127 of 139), zero forbidden findings — and
`--dataflow ip` **PASS** at **79.5%** / unseen **66.0%**;
`contracts/validate_sample.py` green at four budgets;
`analyzer/tools/gen_gallery.py` renders **90 reports plus an index**;
`scripts/check_docs.py` **DOC CHECK OK**. CI run 34454599867: **all 12 branch
jobs green**, 7m57s wall, ~44 billable minutes.

---

## Sprint 4 — the NEXT tier of the roadmap (2026-09-09)

Adoption, the answer card, framework recognition, three rule tiers, export,
packaging and notebooks. `docs/CONTRACTS.md` §11.21–§11.34 are the amendments.

- **Sixteen new rules** (ANA-7 / ANA-8 / ANA-9, §11.26) take the registry from
  **20 to 36**: framework misconfiguration (MLV705–MLV711), training mechanics
  (MLV207, MLV208, MLV209, MLV502, MLV803) and held-out integrity (MLV106,
  MLV114, MLV121, MLV305, MLV306). The labelled corpus grew 10 → 14 programs and
  77 labels; precision stayed **100% on all 36 rules**, overall recall
  62.9% → **71.4%**, unseen 51.1% → **53.2%**. `samples/vision_pipeline` kept
  exactly its fifteen findings, so no golden was regenerated.
- **FW-RECOG** (§11.23) — four framework knowledge tables (`knowledge/tf_tbl.py`,
  `hf_tbl.py`, `gbm_tbl.py`, `hooks_tbl.py`) and Lightning hook units in
  `core/hooks.py`. Graph fidelity **86.3% → 90.6%** (120 → 126 of 139).
- **ANA-5a** (§11.23) — a call the analyzer cannot resolve is never silently
  dropped: `CallSite.unresolved_callee` mints an `unknown` op and one diagnostic
  per scope, and no emitter may claim a stage is absent without the qualification
  *"(unverified: N calls could not be resolved…)"*.
- **CI-ADOPT** — the `mlview.adopt` package stamps each finding `new` /
  `touched` / `existing` from `git diff`, `mlview baseline write` plus
  `--baseline FILE`, `--sarif FILE` (SARIF 2.1.0 against the OASIS schema),
  `tools/action/action.yml` and `.pre-commit-hooks.yaml`. Every attribution
  failure degrades to "showing everything" with a diagnostic.
- **MLV-P1** — the deterministic Pipeline Answer Card (`emit/answers.py`), first
  block of `--format summary`, four sentences in `api.digest`, a card in every
  host.
- **VIEW-07** (§11.24, §11.33) — SVG/PNG export. The mitigation landed first:
  `webview/src/render/plan.ts` returns one scene plan that both
  `render/scene.ts` and `export/svg.ts` consume, so the gate can assert one
  `<path data-edge-id>` per routed edge with byte-identical `d`. The SVG
  references nothing outside itself.
- **NB** (§11.29) — `.ipynb` ingest behind `--include-notebooks`. One notebook
  becomes one generated module under `.mlview/notebooks/`, 1:1 line counts inside
  every cell, the cell map on `Node.attrs`, and a non-monotonic `execution_count`
  de-rates MLV101 / MLV203 / MLV209 by 0.75 and says so. The VS Code host
  re-anchors squiggles onto `vscode-notebook-cell:` URIs.
- **PACKAGING** — `tools/sync-core.py` vendors the analyzer into the VSIX as well
  as the plugin, `tools/verify.py` grew a tenth row, `scripts/vsix_check.py`
  re-derives the ceiling and the bundled-core count from the tree, and
  `tools/wheel_check.py` builds the wheel and runs it from a throwaway venv.
- **PERF-03 + CACHE** (§11.28) — the relevance prefilter and the content-keyed
  fact cache, both opt-in at this point. On a 500-file synthetic
  `build_workspace` dropped **1 087 ms → 76 ms** and the whole analysis
  **2 228 ms → 693 ms**, reporting the same 51 findings; a warm run 319 ms.
  Pickling the AST or the IR was measured and **rejected** — both slower than
  recomputing.
- **HEALTH-02** — the differential fuzzer over the two `project()` ports found a
  real divergence on its first 200 cases; §11.30 made the Python behaviour
  normative and three counterexamples were frozen into the battery.
- **Process** — PROC-01 put a `**Landed` measurement note on every shipped
  roadmap item and `scripts/check_docs.py` check 12 keeps it that way; HOST-8
  moved the VSIX figures out of two documents and into `scripts/vsix_check.py`;
  PROC-10 replaced an estimated CI bill with a measured one and stated the
  rounding rule; PROC-12 wrote down that pushes go over SSH because the stored
  PAT has no `workflow` scope.
- **Review fixes (23 findings).** Two rules were judging the wrong thing (MLV709
  paired a loss with any same-file activation; MLV121 fired on
  `train_ds.take(1)`), and a whole binding style was unanalyzed —
  `ds = ds.map(...)` resolved its right-hand side against the store the same
  statement was about to write, so three semantically identical `tf.data`
  pipelines measured 7/5, 7/5 and **2 nodes / 0 edges with `diagnostics: []`**.
  All three now measure 7/5, gated per style.

**Sprint 4 final gates.** `sh scripts/e2e.sh` **19 steps, 0 failed**; analyzer
**1748 passed / 3 skipped**; webview **404**; vscode-extension **308**;
claude-plugin **324 passed / 7 skipped**; `tools/verify.py --all` **10/10**;
`tools/accuracy.py` precision **100.0%**, recall **71.8%**, unseen 53.2%, graph
fidelity **90.6%**, zero forbidden findings; VSIX **128 files, 604.57 KB**.
CI run 34320075813: 12 jobs green, 6m30s wall, ~38 billable minutes.

---

## Sprint 3 — the NOW tier of the roadmap (2026-09-08)

**The re-baseline (§11.19).** Four items landed as one graph change, because one
golden regeneration has to cover all of them.

- **ANA-1** — ops written inside a class method were dropped: `CallSite.class_ir`
  carried two different facts and `core/build.py` read the wrong one. They are
  now `class_ir` (what the call resolves to) and `enclosing_class` (what class it
  is written in).
- **ANA-2** — `self.<attr>(...)` resolved to a symbol nobody declared; it now
  resolves through the binding.
- **ANA-3** — a package `__init__` re-export resolved to nothing.
- **VIEW-01** — lane boxes are no longer normalised to the widest lane. On the
  demo the world went 2636×2484 → 1576×2630 and `fit()` **0.322 → 0.532**; worst
  lane emptiness **91% → 32%**.

`samples/vision_pipeline` grew from 45 nodes / 45 edges to 54 nodes (52 edges at
the time; 51 since REV-01 dropped one backwards data edge) carrying **exactly the
same fifteen findings** at the same lines, so `expected_issues.json` was
unchanged. Precision stayed **100%** and every recall reading was unchanged to
four decimals; graph fidelity ratcheted **66.2% → 86.3%** (92 → 120 of 139).

Also in Sprint 3: PERF-01/PERF-02 (memoised knowledge lookup, a role index and a
convergence loop, byte-identical on three corpora), **ANA-12** — the labelled
accuracy corpus, `tools/accuracy.py` and `docs/ACCURACY.md` — BUILD-01 (−38% on
the report CSS), CI-01 (`.github/workflows/ci.yml`), COVERAGE (the
`single_file_analysis` / `untagged_dataflow` diagnostics and
`mlview.currentFileAnalysisScope`), RAIL-GROUP (`mlview_issues` `groupBy`) and
CLEANUP (`mlview.showSpeculative` and `mlview.followCursor` deleted).

**The pre-sprint audit, for the record.** Five auditors measured the shipped
prototype on 2026-09-08: **0 false positives on unseen code but roughly 26%
recall**, because class-method ops were dropped; the first screen opened a real
repo at 20% zoom; and the tool could not say "I could not check this". Those
three headlines are what Sprint 3 moved, and `docs/ROADMAP.md` (42 ranked items,
11 declined) is what came out of it.

---

## Feature pass and review rounds (2026-09-07)

**Two features on top of the first prototype**, both additive —
`schemaVersion` stayed `"1.0"` and an unscoped run emitted the bytes it emitted
before (§11.13 and the `docs/FEATURES_FLOW_AND_SCOPE.md` design).

- **Flow visibility.** Hovering a connection runs a charge along it from outlet
  to inlet; hovering a node streams its lineage, staggered 90 ms per hop.
  Direction is never decided — every router emits `points` source → target.
  `prefers-reduced-motion`, or more than `FLOW_MAX_EDGES = 120` lit edges, flips
  the canvas to a static chevron plus outlet and inlet dots.
- **Scoped views.** One selector string — `unit:` / `stage:` / `file:` /
  `concern:` / `node:` / `all`, with `depth` 0–2 — projects the whole-workspace
  document in every surface: `--scope` on the CLI, `data-mlview-scope` on the
  report, `Alt+Shift+M` in VS Code, `scope`/`depth` on the MCP tools. A scope is
  a **view, not a filter**: `stage.present`, `workspace` and `diagnostics` still
  describe the full analysis and the VS Code Problems panel is byte-identical
  while scoped. One algorithm, two languages
  (`analyzer/src/mlview/core/project.py` and `webview/src/scope/project.ts`),
  gated against each other by `contracts/scope.cases.json`.

**Integration and review fixes.** Three components that hid themselves never
actually hid (an author `display` outranks `[hidden]`); the drawn hierarchy and
the lexical hierarchy had diverged in `webview/src/layout/model.ts`, so
collapsing one group erased six nodes from another lane and the demo drew 19 of
its 46 cards; `scripts/e2e.sh` had been rewritten LF → CRLF, which is unrunnable
under dash (MLV-R2-H02); and two documents disagreed about the size of the demo
graph (MLV-R2-H05). The doc gate `scripts/check_docs.py` was created in this
pass and grew to eight checks by the end of it, each one the regression gate for
a specific incident.

---

## First build (2026-09-07)

The multi-agent build of the prototype: analyzer, viewer, VS Code extension and
Claude Code plugin, finished with two review → verify → fix rounds (48 confirmed
findings fixed) and a final verification pass. Twenty rules, the frozen
`contracts/graph.schema.json` and `contracts/graph.sample.json`, the
self-contained HTML report, the five MCP tools, and `scripts/build` +
`scripts/e2e` as the two drivers.
