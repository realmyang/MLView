# MLView improvement research — 2026-09-18

Research baseline: [`5319777`](https://github.com/realmyang/MLView/commit/53197771e57182800c8aae1e9c23da40d059d7ed), after removal of the static analyzer. This report proposes work; it does not implement or claim validation of the proposals. Repository inspection and primary-source research were performed independently across quality, UX and host integration, then reconciled here.

**Recommendation:** make MLView easier to trust and use on a selected real workflow before increasing its advertised breadth. Keep interpretation in the user's active native model. Local code should handle retrieval of verbatim source selected by the model, evidence validation, artifact integrity, display, navigation and evaluation bookkeeping.

Both the [push CI](https://github.com/realmyang/MLView/actions/runs/35329824132) and [PR CI](https://github.com/realmyang/MLView/actions/runs/35329828241) passed for the baseline. Each ran eight jobs across Python 3.10–3.13 and Linux/Windows/macOS package checks. Those tests establish implementation and packaging behavior, not semantic accuracy or live native-host compatibility on every platform.

**What the current evidence establishes**

The [12 original native review ledgers](../evals/workflow/development/native-reviews/README.md) contain 108 provisional claim judgments: 77 supported, 20 qualified, 3 unsupported and 8 omitted. Every human review field remains empty. These counts locate failure patterns; they are not measured accuracy, representative error rates, or a ranking of hosts. The hosts used different models/settings, and only four development tasks supplied these ledgers.

The [focused follow-ups](../evals/workflow/development/quality-followups/README.md) produced five valid artifacts and one failed publication. Their provisional [comparison record](../evals/workflow/development/quality-followups/comparison.json) identifies corrections alongside regressions: accumulated GAN losses were confused with printed losses; framework implications were labeled observed; one notebook output denied execution-count metadata that actually contains `1,3,2,4`. The failed GAN attempt exhausted the allowed JSON repair budget. Exact source quotations alone did not prevent these problems.

The [held-out pilot](../evals/workflow/PILOT_READINESS.md) still has zero completed runs and zero human-reviewed runs. Its 93 candidate facts and 106 source anchors await human review. “Held out” here means reserved from skill tuning, not proven absent from a model's training data. The eight public projects provide useful breadth but limited statistical generalization.

The viewer already has search, scope, collapse, source navigation, evidence, refinement prompts, revision watching and SVG/PNG export. Recommendations below extend that work. A visual redesign would be premature without task-based evidence.

**Prioritized portfolio**

Effort is relative engineering scope, not a delivery estimate. P0 means the next focused campaign; P1 follows or proceeds independently; P2 needs evidence from earlier work.

| Priority | Initiative | Main benefit | Effort | Main dependency |
|---|---|---|---|---|
| P0 | Correct authored legend and uncertainty semantics | Prevent misleading interpretation of the diagram | Small | Existing contract |
| P0 | Evidence inspector and complete textual relations | Make claims reviewable and accessible | Medium | Existing evidence/topology |
| P0 | Source-grounded semantic checks and reliable authoring | Reduce known omissions, overclaims and publication failures | Medium | Development cases and matched baselines |
| P0 | Human adjudication and frozen pilot | Establish whether skill changes actually help | Human work + medium tooling | Named reviewers and frozen run policy |
| P1 | Explicit coverage obligations and small domain guides | Improve recall without speculative findings | Medium | Development reference facts |
| P1 | Task-focused views and change impact | Answer useful ML questions with fewer navigation steps | Medium | Existing scope plus authored semantics |
| P1 | Validation coalescing and size/performance budgets | Keep editing and large diagrams responsive | Small/medium, then measured | Profiling in actual VS Code |
| P1 | Skill distribution and platform capability matrix | Reduce installation friction and unsupported assumptions | Medium | Host version probes |
| P2 | Atomic claims, metadata citations and scenario structure | Represent distinctions that prose currently blurs | Medium/large | Prototype evidence and versioned migration |
| P2 | Scenario comparison and reviewable sharing | Support code review and collaborative understanding | Medium/large | Stable identity and privacy design |

**1. Make the visible semantics match the native workflow**

This is an observed UI gap. [workflow.ts](../webview/src/workflow.ts) maps an unresolved node to `ghost`, while [legend.ts](../webview/src/ui/legend.ts) describes that state as a missing stage. The legend also retains static call-resolution and rule-confidence language. Its high-severity description mixes impact with likelihood. An unresolved step can exist and simply lack enough evidence; severity is also distinct from certainty.

Give the authored viewer its own legend and accessible descriptions: observed, inferred, unresolved, source freshness, finding severity, evidence and counter-evidence. Show basis as text, keep severity independent, and never fabricate a probability from these categories. Audit help, search hints, empty states, tooltips, exports and accessible names, rather than fixing only the main tab label.

Acceptance: no authored surface explains a model claim using retired rule-engine semantics; unresolved is never described as proof of absence; every state has a non-color cue. Add regression cases for these visible and accessible strings. This work fits WorkflowDocument 1.0 and should precede more visual styling.

**2. Make the diagram a practical evidence-review interface**

Selecting an item should expose the claim, its basis, each supporting quote, counter-evidence, and relevant limitations together. Existing evidence plumbing in [workflow.ts](../webview/src/workflow.ts) and the [authored panel](../vscode-extension/src/authoredPanel.ts) supports much of this. Add next/previous evidence, a clear reason when navigation is unavailable, and a focused Challenge action using the current revision and item.

Extend the [Outline](../webview/src/ui/outline.ts) with a complete textual relationship view. It currently represents phases and nodes; the essential edge semantics deserve an equally usable HTML path. A row could read “Training batch → Loss — compute objective — inferred,” followed by evidence and source actions. Include incoming, outgoing and all-relations views, with cycle-safe navigation and return focus.

Acceptance: keyboard-only users can enumerate every node and edge, discover direction and basis, inspect all evidence, and return to the selected item. Test actual screen readers as well as DOM behavior. Audit pointer targets, focus visibility, high contrast and reduced motion against [WCAG 2.2](https://www.w3.org/TR/WCAG22/); the target-size criterion uses 24 CSS pixels with specified exceptions, not an unconditional requirement for every glyph. [W3C target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html).

A small formative study should compare current and proposed UI on concrete tasks: identify which parameters update, locate a split boundary, explain a conditional finding, and trace a saved checkpoint. Measure correct answers, time, navigation errors and misplaced certainty. A small study can reveal usability failures; it cannot prove broad accuracy gains.

**3. Improve the interpretation process with checkable evidence operations**

The skill already includes critique. Make that critique more specific: re-read output expressions; separate accumulated values from printed values; inspect raw notebook metadata; check optimizer membership separately from gradient paths; follow consumers of held-out data; inspect lifecycle helpers; and state missing imports, runtime prerequisites and selected configuration.

For example, these are different assertions:

| Assertion | Appropriate basis |
|---|---|
| The optimizer is constructed from `netG.parameters()` | Observed, with source evidence |
| Gradients can flow through the discriminator to generated inputs | Inferred, with framework and trainability assumptions |
| Generator parameters changed during an actual run | Unresolved without execution evidence |

The project can make these distinctions in existing prose immediately. A new schema is not necessary to test whether the authoring instructions improve them. Require scope for absence claims: “no consumer was found in these inspected files,” with unresolved external behavior retained.

Research on intrinsic self-correction found that models can fail to improve, or worsen, without external feedback. That motivates source re-reading and explicit checks; it does not establish failure rates for today's native models. [Huang et al., 2023](https://arxiv.org/abs/2310.01798).

Also prototype a bounded artifact builder that accepts small records or edits to a draft, performs ordinary JSON serialization, and validates at explicit checkpoints. The model still chooses every node, relation and claim. Compare this with the current whole-document authoring path on publication rate, repair rounds, time and semantic omissions. Smaller writes may prevent malformed long JSON, but extra tool calls may erase the benefit. Preserve atomic publication, last-valid revisions and the existing repair budget.

Acceptance: recover the known development failures without new unsupported claims as a regression check. Measure improvement in matched fresh sessions on separate development fixtures chosen before inspecting outputs. Track publication rate, repair count and semantic omissions. The already-tuned GAN/notebook cases cannot establish general improvement, and one successful rerun is insufficient.

**4. Complete the semantic measurement system**

Use the existing [review-packet tooling](../tools/workflow_eval.py) to obtain named, dated human decisions for reference facts, scenarios, severity and essential-fact denominators. If a second reviewer is available, independently review high-severity cases and a stratified sample of other facts; retain disagreements and their resolution.

Freeze the actual candidate's source, skill bundle, helper, viewer, host/model settings, prompt, scenario and budget. The current tree differs from the older four-file candidate; its old bundle hash must not identify a new run. Generate a new manifest using the recorded sorted-relative-path-plus-bytes bundle algorithm, including all current distributed skill files, and record separate viewer/VSIX identities. Treat `5319777` as the research baseline until a pilot candidate and settings are explicitly frozen. Keep immutable artifacts and fresh sessions, failed attempts, timeouts, cancellations and missing publications in the record.

Run the existing Stage 1 matrix of 24 cases only after its reference and run-policy gate is satisfied. The existing targets remain 100% valid structure and exact anchors, at least 95% supported claims and 85% essential-fact recall, qualification of known unknowns, and zero high-severity false accusations. These are decision targets, not guarantees. Advance to the remaining 48 runs only according to the frozen policy.

A proposed Stage 1 comparison adds 24 no-skill sessions matched by task, host, model/settings and budget; this is additional work beyond the existing 72 skill runs. The existing baseline material covers only three development `dev-config` responses. Freeze whether further baseline repetitions are justified before scheduling them. Compare prose baselines on semantic claims and task usefulness; publication validity and artifact navigation are skill-specific measures. Separate invocation, publication, citation fidelity, interpretation, usefulness and efficiency metrics. This distinction follows the outcome/process/style/efficiency approach in [OpenAI's skill-evaluation guidance](https://developers.openai.com/blog/eval-skills); its CLI examples are useful for auxiliary experiments but do not substitute for the project's VS Code host acceptance runs.

Before scoring, freeze claim atomicity and verdict mapping. A conditional claim should count as supported only when a human reviewer confirms both its stated conditions and conclusion; report such qualified claims separately as well. Count omissions through essential-fact recall, not claim precision. Report end-to-end success over all assigned runs, including failed publications, alongside semantic metrics for published artifacts; otherwise filtering to valid outputs creates survivorship bias.

Freeze capture privacy before any pilot session: raw native transcripts stay ignored, public records contain only approved sanitized fields and capture hashes, and reproduced source excerpts retain required attribution. Record whether a raw capture hash was independently verified or merely supplied.

Report per-task and per-host numerators/denominators, paired changes and instability. Repeated runs on eight tasks do not create 72 independent task samples. Any uncertainty estimates should respect task clustering and acknowledge the small task count. Broad scenario coverage and multiple metrics are consistent with [HELM](https://arxiv.org/abs/2211.09110); that benchmark is methodological background, not evidence that MLView passes.

**5. Make coverage explicit and broaden it along semantic dimensions**

Current [coverage fields](../contracts/workflow.schema.json) contain a status, summary, inspected files and free-text limitations. They cannot reliably distinguish “inspected and absent,” “not applicable,” “not inspected,” and “unresolved.” Prototype a small obligation matrix covering data origin, fitted/updated state, objectives, evaluation boundaries, outputs and uncertainty. Link each answer to graph/evidence items and the selected scenario. Do not infer coverage from file count or number of nodes.

Start as an evaluation/authoring aid. Only promote it into the public artifact after it proves useful and reliable. A checklist must permit “not applicable” and justified absence, so it does not pressure the model to invent findings.

The [task matrix](../evals/workflow/tasks.json) has useful supervised-training variety, but domain names alone overstate tested coverage:

| Area | Current evidence | Next development case |
|---|---|---|
| PyTorch, sklearn/CV | Development plus planned held-out tasks | Split/fit state, clean/buggy twins, conditional output semantics |
| HF, Lightning, Keras, JAX | Development tasks; held-out HF/Flax planned | Custom lifecycle overrides, functional state and hidden framework boundaries |
| GAN/alternating updates | Native development examples and recorded errors | Multiple optimizers, detach/freeze distinctions, nested loops |
| Notebooks | Native development plus planned held-out notebook | Cell metadata, stale outputs, reordered cells, unresolved kernel history |
| LLM, diffusion, RL | Held-out tasks planned; no completed scored pilot | Small independent development fixtures before broader claims |
| Configuration/registry/inference | Config and train/infer examples; MMDetection planned | Composed config, launcher overrides, batching/cache and checkpoint compatibility |
| Distributed training, PEFT, quantization, serving | No dedicated task in the matrix | Prioritize by intended users after the first pilot |
| Retrieval/tool pipelines, multimodal and streaming | No dedicated task in the matrix | Later expansion with separate task definitions |

Use compact domain references loaded when relevant: gradient accumulation/AMP/PEFT, RL collection-update cycles, diffusion conditioning/noise/frozen components, inference caches, and config composition. Keep the universal skill short. Both [OpenAI](https://learn.chatgpt.com/docs/build-skills) and [Claude](https://code.claude.com/docs/en/skills) document selective skill loading and supporting resources. The expected quality benefit of these specific guides still needs measurement.

For larger repositories, maintain a concise factual working set: selected scenario, inspected files, unresolved dependencies, provisional claims and next source questions. Re-open exact source before publication. Studies of long-context retrieval and multi-hop reasoning motivate these experiments, but are not measurements of MLView's current models. [Lost in the Middle](https://arxiv.org/abs/2307.03172), [RULER](https://arxiv.org/abs/2404.06654).

**6. Add features organized around ML questions**

Expose existing topology and scope through actions such as Trace inputs, Trace downstream effects, Show evaluation boundary, Show update targets, Show unresolved claims and Restore whole workflow. Keep a persistent breadcrumb and shown/hidden counts. Basic upstream/downstream views can use existing edges; ML-specific views require consistent model-authored relation labels before the UI can promise their meaning.

Two subsequent features have substantial potential:

- **Change impact and targeted refinement.** Map changed evidence to affected items, explain what became stale and prepare a focused request for the native assistant. Keep full validation on publication. File hashes establish changed inputs, not a complete dependency graph, so unrelated-looking source edits may still require broader inspection.
- **Scenario and revision comparison.** Compare training versus inference, two configs, or two revisions. Preserve stable IDs where meaning is unchanged; separate source change, scenario change and interpretation change. When identities cannot be aligned reliably, expose the uncertainty or ask the native model during an explicit comparison request. A textual difference must not automatically become a semantic defect.

Acceptance: users answer a concrete workflow question faster with equal or better correctness; filters never hide that they are projections; comparisons make the selected source revisions/configurations explicit. Keep these as user-controlled operations.

**7. Measure responsiveness and platform behavior before promising scale**

The contract permits 2,000 nodes, 4,000 edges and 5,000 evidence records. The main [renderer regression fixture](../webview/test/renderer-regression.test.mjs) has 48 nodes. Neither fact establishes interactive performance at the limits.

Benchmark 100/500/1,000/2,000-node graphs in actual VS Code, with cycles, long labels, deep groups and many findings. Measure normalization, layout, first interactive paint, selection, scope/reset, export and memory after repeated updates. Initial engineering targets could be sub-100 ms selection feedback and a usable 500-node overview within roughly one second on specified reference hardware; these are proposed budgets to validate, not present performance claims. Profile before choosing viewport virtualization, workers, chunked scene construction or more aggressive grouping. Any reduced initial view must disclose hidden items.

[AuthoredPanel](../vscode-extension/src/authoredPanel.ts) immediately revalidates dependent panels on text/save/filesystem changes. Generation counters prevent old results from winning, but do not avoid repeated work. Add per-panel coalescing and cancellation/one queued rerun; mark evidence stale promptly, retain the last valid view and revalidate before navigation. Test typing bursts, disposal and overlapping source/artifact changes with fake timers.

For remote work, distinguish extension-host locality from virtual filesystems. The extension is a workspace extension; Node filesystem access does not by itself establish failure under SSH or containers. Test local OSes, Remote SSH, containers and Codespaces, recording URI schemes and host placement. Virtual GitHub repositories are explicitly unsupported today; supporting them requires URI-aware I/O and bounded validation through the appropriate filesystem provider. [VS Code virtual workspace guidance](https://code.visualstudio.com/api/extension-guides/virtual-workspaces).

**8. Reduce setup friction while preserving the native-host boundary**

VS Code now documents extension-contributed skills through `chatSkills`. Prototype shipping the canonical skill in the VSIX for Copilot, alongside the existing workspace installer/ZIP for Codex and the Claude skill plugin. First verify the minimum compatible VS Code/host versions: the existing `^1.100.0` engine declaration cannot be assumed sufficient for every new contribution point. Test manifest/package acceptance on the chosen minimum version, clean-profile discovery and canonical hashes. Define a doctor result and remediation for duplicate installations. [VS Code skill distribution](https://code.visualstudio.com/docs/agent-customization/agent-skills).

This changes the package boundary: the current VSIX check rejects every Python file. A bundled skill would need an exact allowlist for its canonical artifact helper, with byte-equality tests and continued rejection of analyzer code. The viewer would still make no Python calls; Python would be used only when the native assistant invokes the helper.

Extend the existing doctor with installed skill identity, version mismatch, package integrity and clearer remediation. Measure time and user actions from installation to the first valid diagram. Ship versioned release artifacts with explicit checksums and a small current example; current CI package artifacts are not themselves a marketplace release.

Retain Copy prompt as a portable refinement path. Public host APIs can open chat UI; context attachment is host-specific and must be separately proven. The inspected documentation does not establish a universal API to submit a draft into the exact conversation that authored the artifact. Treat Open assistant as navigation only, unless a host-specific public contract is proven. [Codex IDE commands](https://learn.chatgpt.com/docs/developer-commands?surface=ide), [VS Code command reference](https://code.visualstudio.com/api/references/commands). Avoid private command arguments, session scraping and automatic approval changes.

**9. Incubate richer evidence and privacy controls with an explicit migration**

The public schema currently has exact line/cell quotes and one basis per graph item. Evaluation tooling already handles JSON Pointer evidence, but the product format does not. A useful first prototype is typed notebook/config metadata evidence, so claims about execution counts can be checked against the actual value. This proves a recorded value exists; it still does not prove a successful runtime history.

A second prototype attaches bounded atomic assertions, assumptions and their supporting/counter-evidence to an item. A third represents mutually exclusive scenarios and state effects explicitly. Prototype them against existing reviewer pain before enlarging the schema. Both boundary validators reject unknown fields today, so additions need a negotiated document version, legacy-reader behavior, migration fixtures and matching Python/TypeScript validation. Preserve raw native evaluation outputs rather than rewriting them for the new format.

Add a reviewable sharing path: clearly distinguish an exact local artifact from a deliberately redacted export. Source quotes, filenames and configuration can be sensitive; redaction should never retain a misleading claim of exact citation validity. A portable HTML viewer may be useful later, but adds maintenance and security surface beyond the current SVG/PNG exports.

Test prompt-injection resilience separately from JSON safety. Source comments, notebooks and artifact text are data; the skill and copied refinement prompt should preserve that boundary. Include benign adversarial fixtures asking the assistant to abandon the user's workflow, execute target code or change permissions. Measure and retain native-host successes and failures across sessions. Separately assert that artifact strings remain inert in the deterministic viewer/helper. Native permission controls remain necessary; skill wording cannot guarantee isolation. [Claude security guidance](https://code.claude.com/docs/en/security).

**Suggested execution order and decision gates**

1. **Trust and usability campaign:** fix authored legend/help semantics; consolidate evidence review; add textual relations; coalesce reloads; define usability/performance baselines. This can stay in format 1.0 and proceed while humans review references.
2. **Interpretation campaign:** test targeted source checks, a bounded builder, coverage obligations and a few independent domain fixtures against matched development baselines. Preserve the held-out set. Freeze a candidate only after its known failures and new regressions have been reviewed.
3. **Pilot:** complete reference/run-policy approval, collect Stage 1 and adjudicate it. Continue only under the existing stop/go policy. No polished UI or green CI substitutes for this gate.
4. **Expansion:** use pilot evidence to choose distribution/platform work, scenario comparison, and the smallest justified schema revision. Publish host/domain capability claims only at the level actually demonstrated.

Defer a custom LLM service, automatic background model runs, numeric confidence badges, a general-purpose workflow language, runtime tensor tracing, and training/fine-tuning a separate model. Each adds a substantial product or trust boundary before the core interpretation quality has a measured baseline. The immediate differentiator should be a useful, source-auditable explanation in the assistant and editor the user already uses.
