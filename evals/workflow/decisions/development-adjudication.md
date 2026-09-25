# Development adjudication

> Human verdicts on the 12 provisional native reviews and 3 baseline notes; the ledgers are never edited.
> Claims: supported | qualified | unsupported | omitted. Usability: clear | partial | missing.
> Baselines: confirmed | corrected | rejected. Add " — <reason>" whenever you differ from the provisional
> label, and for every baseline verdict except confirmed. Source context: the review packet (review-packet).
> Check: python tools/workflow_eval.py check development-adjudication

Reviewer:
Date:
Transcribed by:

## dev-config / copilot
Ledger: native-reviews/copilot/dev-config.json 45d8de50aaa4902f4e09fa9d9616955bcca05535375e87eb746e1f2b06fef4a6
> Artifact: native-artifacts/copilot/dev-config.mlview.json (rev-distill-1)
> config-resolution (provisional: supported): The artifact accurately resolves the selected configuration and registry architectures.
config-resolution: pending
> data-loading (provisional: supported): Both tensor files are loaded into batch-32 DataLoaders with training shuffled and validation ordered.
data-loading: pending
> teacher-freezing (provisional: supported): The teacher is loaded, frozen, put in eval mode, and evaluated without gradients.
teacher-freezing: pending
> loss-separation (provisional: supported): Supervised cross-entropy and scaled KL are shown separately before their 0.4/0.6 combination.
loss-separation: pending
> student-only-update (provisional: supported): Optimizer membership and the update sequence support a student-only update claim.
student-only-update: pending
> validation (provisional: supported): Student accuracy is evaluated and printed after every training epoch.
validation: pending
> checkpoint-output (provisional: supported): Only the final student state_dict is saved after five epochs.
checkpoint-output: pending
> external-unknowns (provisional: qualified): The artifact states that data, checkpoint compatibility, and runtime results remain unknown; it does not convert absence into a proven failure.
external-unknowns: pending
> usability.dataOrigin (provisional: clear): Configured external tensor inputs and their limits are stated.
usability.dataOrigin: pending
> usability.updatedParametersAndFitState (provisional: clear): Teacher freezing and student optimizer ownership are explicit.
usability.updatedParametersAndFitState: pending
> usability.losses (provisional: clear): Both losses and their combination are explicit.
usability.losses: pending
> usability.evaluationBoundaries (provisional: clear): Validation follows each training epoch.
usability.evaluationBoundaries: pending
> usability.outputs (provisional: clear): The final student state output is explicit.
usability.outputs: pending
> usability.uncertainty (provisional: partial): Unknown external facts are in coverage, but there are no dedicated unresolved nodes or findings.
usability.uncertainty: pending

## dev-config / codex
Ledger: native-reviews/codex/dev-config.json 42c68a8da2ae37a5b6a5b46f4ef076fdfbb8c909e0b8612be2f6c4b9a0e41789
> Artifact: native-artifacts/codex/dev-config.mlview.json (rev-distill-configured-training-20260917-01)
> config-resolution (provisional: supported): The selected JSON resolves small student and wide teacher models and the stated hyperparameters.
config-resolution: pending
> teacher-freezing (provisional: supported): The teacher checkpoint is loaded on CPU, parameters are frozen, and its forward pass uses evaluation mode without gradients.
teacher-freezing: pending
> loss-separation (provisional: supported): Cross-entropy and temperature-scaled batch-mean KL are separated and then weighted 0.4/0.6.
loss-separation: pending
> student-only-update (provisional: supported): Adam owns student parameters only, so the shown backward and step path updates only the student.
student-only-update: pending
> validation-boundary (provisional: supported): Validation runs after each epoch without gradients and prints accuracy; it does not select a checkpoint.
validation-boundary: pending
> checkpoint-output (provisional: supported): After the loop, the final student state_dict alone is written to the configured relative path.
checkpoint-output: pending
> external-teacher (provisional: qualified): The artifact correctly leaves teacher checkpoint existence, compatibility, provenance, and quality unresolved.
external-teacher: pending
> external-data (provisional: qualified): The expected keys and loader flow are source-supported, while tensor contents and runtime validation results remain unknown.
external-data: pending
> inference-separation (provisional: supported): Inference is identified as context rather than part of the selected training execution path.
inference-separation: pending
> usability.dataOrigin (provisional: clear): External train and validation tensor paths and their unresolved contents are explicit.
usability.dataOrigin: pending
> usability.updatedParametersAndFitState (provisional: clear): Only student parameters belong to Adam; teacher state is frozen.
usability.updatedParametersAndFitState: pending
> usability.losses (provisional: clear): Both terms, temperature scaling, and weights are explicit.
usability.losses: pending
> usability.evaluationBoundaries (provisional: clear): Per-epoch validation is distinct from training.
usability.evaluationBoundaries: pending
> usability.outputs (provisional: clear): Printed validation records and final student state output are distinguished.
usability.outputs: pending
> usability.uncertainty (provisional: clear): External files and runtime outcomes are represented as unresolved.
usability.uncertainty: pending

## dev-config / claude-code
Ledger: native-reviews/claude-code/dev-config.json e1dc97fc5831895671ce0b29cbf6af4b931afcb0ee08a105cccbe289ccc46242
> Artifact: native-artifacts/claude-code/dev-config.mlview.json (dev-config-distill-r1)
> launch-and-config (provisional: supported): The launch scenario and direct JSON configuration flow are accurately separated from hard-coded settings.
launch-and-config: pending
> registry-resolution (provisional: supported): Small and wide resolve to compatible 10-input, 3-output architectures.
registry-resolution: pending
> teacher-freezing (provisional: supported): Load, freeze, eval-mode, and no-grad steps are all grounded in source.
teacher-freezing: pending
> loss-separation (provisional: supported): The artifact correctly distinguishes hard-label CE, temperature-scaled KL, and the 0.4/0.6 blend.
loss-separation: pending
> student-only-update (provisional: supported): Adam is constructed from student parameters and the shown update therefore applies to student state only.
student-only-update: pending
> validation-and-output (provisional: supported): Per-epoch validation output and the one final student state save are accurately distinguished.
validation-and-output: pending
> teacher-unknowns (provisional: qualified): The external teacher compatibility and quality are correctly unresolved; suggested preflight checks are advice rather than observed behavior.
teacher-unknowns: pending
> data-unknowns (provisional: qualified): The loader contract is supported, while dataset schema, overlap, and quality remain external runtime facts.
data-unknowns: pending
> inference-consumer (provisional: supported): The separate inference consumer is kept outside the selected training run.
inference-consumer: pending
> usability.dataOrigin (provisional: clear): External tensor sources and loading behavior are explicit.
usability.dataOrigin: pending
> usability.updatedParametersAndFitState (provisional: clear): Teacher and student state ownership is explicit.
usability.updatedParametersAndFitState: pending
> usability.losses (provisional: clear): Both terms and weights are explicit.
usability.losses: pending
> usability.evaluationBoundaries (provisional: clear): Training and per-epoch validation are separated.
usability.evaluationBoundaries: pending
> usability.outputs (provisional: clear): Printed metrics and final checkpoint are explicit.
usability.outputs: pending
> usability.uncertainty (provisional: clear): External checkpoint and dataset uncertainty is localized in unresolved nodes and findings.
usability.uncertainty: pending

## dev-sklearn / copilot
Ledger: native-reviews/copilot/dev-sklearn.json 4caea80a80dd85283a82f659a4f3b24da66835c5da19da2b6c2b8cc07e122d6f
> Artifact: native-artifacts/copilot/dev-sklearn.mlview.json (rev-1)
> outer-group-split (provisional: supported): The artifact correctly identifies the account-group outer holdout.
outer-group-split: pending
> inner-group-folds (provisional: supported): The inner splitter preserves groups while stratifying labels across five folds.
inner-group-folds: pending
> fold-local-encoder (provisional: supported): TargetEncoder is newly built and fitted on each inner-training slice.
fold-local-encoder: pending
> validation-transform (provisional: supported): Validation rows use transform rather than fit_transform.
validation-transform: pending
> fold-estimator (provisional: supported): CatBoost fits training Pools and uses validation Pools for early stopping.
fold-estimator: pending
> cv-aggregation (provisional: supported): Validation AUCs and best rounds are aggregated before final fitting.
cv-aggregation: pending
> final-refit (provisional: supported): A new encoder and final booster fit all outer-training rows.
final-refit: pending
> holdout-evaluation (provisional: supported): Outer-test features are transformed once and scored with ROC AUC and average precision.
holdout-evaluation: pending
> missing-import-qualification (provisional: unsupported): The artifact presents the visible fit/apply structure but does not disclose that encoders.py and features.py are absent, so complete leakage safety is not established.
missing-import-qualification: pending
> usability.dataOrigin (provisional: partial): The split flow is clear, but imported feature preparation internals are not surfaced.
usability.dataOrigin: pending
> usability.updatedParametersAndFitState (provisional: clear): Fold-local and final fitted components are easy to identify.
usability.updatedParametersAndFitState: pending
> usability.losses (provisional: missing): No explicit loss explanation is provided.
usability.losses: pending
> usability.evaluationBoundaries (provisional: clear): Inner validation and outer holdout are separated.
usability.evaluationBoundaries: pending
> usability.outputs (provisional: partial): Evaluation metrics are named, but aggregation/report details are compressed.
usability.outputs: pending
> usability.uncertainty (provisional: missing): Absent imported implementations and runtime facts are not disclosed.
usability.uncertainty: pending

## dev-sklearn / codex
Ledger: native-reviews/codex/dev-sklearn.json 13add1d251b4bcc08588c579e93761b73597fc63939041328fe88eeaec80f892
> Artifact: native-artifacts/codex/dev-sklearn.mlview.json (rev-group-cv-clean-1)
> outer-group-split (provisional: supported): The outer holdout uses GroupShuffleSplit with group labels and keeps test rows outside fitting.
outer-group-split: pending
> inner-group-folds (provisional: supported): Five StratifiedGroupKFold splits are generated from the outer-training partition and its groups.
inner-group-folds: pending
> fold-local-encoder (provisional: supported): A fresh encoder is instantiated inside each fold and fitted only on inner-training X and y.
fold-local-encoder: pending
> validation-transform (provisional: supported): Inner-validation features are transformed without validation labels entering the encoder call.
validation-transform: pending
> fold-estimator (provisional: supported): A fresh CatBoost estimator fits the training Pool while the validation Pool controls early stopping.
fold-estimator: pending
> cv-aggregation (provisional: supported): Fold validation AUC and best iteration are aggregated into mean AUC and median rounds.
cv-aggregation: pending
> final-refit (provisional: supported): A new encoder and booster are refit on all outer-training rows using the CV-derived round count.
final-refit: pending
> holdout-evaluation (provisional: supported): The fitted encoder transforms outer-test features, then held-out labels are used for ROC AUC and average precision.
holdout-evaluation: pending
> imported-preprocessing (provisional: qualified): Visible call sites support fold containment, but missing feature and encoder implementations prevent a complete leakage audit.
imported-preprocessing: pending
> usability.dataOrigin (provisional: partial): CSV loading and partition flow are clear, but feature engineering and split_frame internals are unavailable.
usability.dataOrigin: pending
> usability.updatedParametersAndFitState (provisional: clear): Per-fold encoder and booster fitting, then final refit, are explicit.
usability.updatedParametersAndFitState: pending
> usability.losses (provisional: missing): This workflow exposes estimator fitting and metrics but no explicit loss computation beyond CatBoost's configured Logloss.
usability.losses: pending
> usability.evaluationBoundaries (provisional: clear): Inner validation and outer held-out evaluation are distinct.
usability.evaluationBoundaries: pending
> usability.outputs (provisional: clear): Fold aggregation and held-out metrics are represented.
usability.outputs: pending
> usability.uncertainty (provisional: clear): Missing imported preprocessing implementations are explicitly qualified.
usability.uncertainty: pending

## dev-sklearn / claude-code
Ledger: native-reviews/claude-code/dev-sklearn.json 642dce358043c21d5a9d4ef7370f08fe2bd26f95dbb8c459daa954ba48883a72
> Artifact: native-artifacts/claude-code/dev-sklearn.mlview.json (dev-sklearn-r1)
> outer-group-split (provisional: supported): The outer split and development/holdout partitions are traced with the group argument.
outer-group-split: pending
> inner-group-folds (provisional: supported): The five shuffled stratified group folds consume only development rows and groups.
inner-group-folds: pending
> fold-local-encoder (provisional: supported): A new Pipeline is built per fold and fit_transform receives only inner-training rows and labels.
fold-local-encoder: pending
> validation-transform (provisional: supported): Inner-validation features enter transform without validation labels.
validation-transform: pending
> fold-estimator (provisional: supported): Separate Pools preserve train/validation roles and validation controls early stopping.
fold-estimator: pending
> cv-aggregation (provisional: supported): Per-fold AUC and best iterations yield mean AUC and median rounds.
cv-aggregation: pending
> final-refit (provisional: supported): Final encoder and booster fit development data only; holdout does not steer training.
final-refit: pending
> holdout-evaluation (provisional: supported): The holdout is transformed, predicted, and scored after final fitting.
holdout-evaluation: pending
> imported-preprocessing (provisional: qualified): No leakage is visible at call sites, but TargetEncoder and feature engineering internals are correctly unresolved.
imported-preprocessing: pending
> selection-informed-cv (provisional: qualified): The artifact appropriately notes that fold AUC uses the validation set that also chooses the stopping round, while preserving the independent holdout boundary.
selection-informed-cv: pending
> usability.dataOrigin (provisional: partial): CSV flow is clear; feature engineering and column separation internals are unavailable.
usability.dataOrigin: pending
> usability.updatedParametersAndFitState (provisional: clear): Fold-local fits and final refit are fully separated.
usability.updatedParametersAndFitState: pending
> usability.losses (provisional: partial): CatBoost Logloss is configured, but the library implementation is outside inspected source.
usability.losses: pending
> usability.evaluationBoundaries (provisional: clear): Fold validation and final holdout scoring are explicit.
usability.evaluationBoundaries: pending
> usability.outputs (provisional: clear): CV AUC, holdout metrics, and held-out account count are represented.
usability.outputs: pending
> usability.uncertainty (provisional: clear): Missing imports, library behavior, runtime data, and selection-informed CV are disclosed.
usability.uncertainty: pending

## dev-gan / copilot
Ledger: native-reviews/copilot/dev-gan.json 809d84f5f52bacecbec050c5f51c2213e4755275626e37225ac43819281923fd
> Artifact: native-artifacts/copilot/dev-gan.mlview.json (rev-1)
> optimizer-ownership (provisional: supported): Separate optimizers target the generator and discriminator parameter iterables.
optimizer-ownership: pending
> discriminator-objective (provisional: supported): The real-one and detached-fake-zero BCE branches, their sum, backward call, and discriminator step match source order.
discriminator-objective: pending
> detach-boundary (provisional: qualified): The described stop-gradient effect is standard framework inference from detach(), but these nodes label it observed rather than inferred.
detach-boundary: pending
> generator-objective (provisional: qualified): The call sequence and optimizer target are observed; the stated backpropagation path through D into G is framework inference presented as observed.
generator-objective: pending
> alternating-cycle (provisional: supported): The diagram shows discriminator then generator phases and explicit batch and epoch repetition.
alternating-cycle: pending
> running-loss-report (provisional: unsupported): The artifact implies the accumulated values are printed, while stdout uses the current batch losses and the running sums are never read.
running-loss-report: pending
> epoch-outputs (provisional: supported): Fixed-noise image sampling and per-epoch checkpoints with both state dictionaries are represented.
epoch-outputs: pending
> unused-running-sums (provisional: omitted): The dead d_running and g_running accumulators are not identified.
unused-running-sums: pending
> sample-directory-risk (provisional: omitted): The source writes samples/epoch_NNN.png but does not create samples/; this runtime precondition is absent.
sample-directory-risk: pending
> usability.dataOrigin (provisional: clear): The ImageFolder source and preprocessing loader are visible.
usability.dataOrigin: pending
> usability.updatedParametersAndFitState (provisional: clear): Optimizer ownership and D-then-G updates are explicit.
usability.updatedParametersAndFitState: pending
> usability.losses (provisional: clear): Both discriminator terms and generator loss are identifiable.
usability.losses: pending
> usability.evaluationBoundaries (provisional: clear): Sampling is shown as an epoch output rather than held-out evaluation.
usability.evaluationBoundaries: pending
> usability.outputs (provisional: partial): Samples and checkpoints are shown, but metric reporting is misstated and output-directory risk is absent.
usability.outputs: pending
> usability.uncertainty (provisional: partial): Missing model definitions are disclosed, but framework gradient semantics are labeled observed.
usability.uncertainty: pending

## dev-gan / codex
Ledger: native-reviews/codex/dev-gan.json f07af3db3510ca4de0ff3cbb7d70fee5c81ca2e5defe1d674150d9bfe424cfd7
> Artifact: native-artifacts/codex/dev-gan.mlview.json (rev-dcgan-loss-cycle-20260917-1)
> optimizer-ownership (provisional: supported): The artifact correctly binds separate Adam optimizers to netG.parameters() and netD.parameters().
optimizer-ownership: pending
> discriminator-objective (provisional: supported): It correctly shows discriminator BCE terms for real images against ones and detached generated images against zeros, summed before backward and the D step.
discriminator-objective: pending
> detach-boundary (provisional: supported): It correctly distinguishes fake_images.detach() in the discriminator branch from reuse of the original attached fake_images in the generator branch.
detach-boundary: pending
> generator-objective (provisional: supported): It correctly represents BCE on netD(fake_images) against real labels followed by generator backward and opt_g.step().
generator-objective: pending
> alternating-cycle (provisional: supported): The repeated batch path preserves the source order: discriminator update first, generator update second, then the next batch.
alternating-cycle: pending
> discriminator-gradients-during-g (provisional: qualified): The artifact labels the extra discriminator-gradient accumulation as inferred and conditions it on normal autograd and requires_grad behavior, which is the appropriate source-only qualification.
discriminator-gradients-during-g: pending
> running-loss-report (provisional: unsupported): The artifact says accumulated scalar loss values are printed, but the print uses current loss_d.item() and loss_g.item(); d_running and g_running are accumulated and never read.
running-loss-report: pending
> epoch-outputs (provisional: supported): It correctly includes fixed-noise sample images and checkpoints containing both network state dictionaries after every epoch.
epoch-outputs: pending
> output-directory-risk (provisional: omitted): The source writes under samples/ without creating that directory; the artifact does not surface the resulting runtime precondition.
output-directory-risk: pending
> usability.dataOrigin (provisional: clear): ImageFolder at data/celeba and its transform/loader setup are shown.
usability.dataOrigin: pending
> usability.updatedParametersAndFitState (provisional: clear): D and G optimizer ownership and alternating steps are explicit.
usability.updatedParametersAndFitState: pending
> usability.losses (provisional: clear): Both discriminator BCE branches and the generator BCE objective are distinct.
usability.losses: pending
> usability.evaluationBoundaries (provisional: clear): The artifact states there is no held-out evaluation and separates epoch sampling from evaluation.
usability.evaluationBoundaries: pending
> usability.outputs (provisional: partial): Images and checkpoints are clear, but current losses are incorrectly described as accumulated values and the missing sample directory precondition is absent.
usability.outputs: pending
> usability.uncertainty (provisional: clear): Imported model internals, runtime data, device, and framework-derived gradient behavior are qualified.
usability.uncertainty: pending

## dev-gan / claude-code
Ledger: native-reviews/claude-code/dev-gan.json 08131c4918789c8d12b9820a8734f7bcc0d7e4ff3c6abdd09640e2602911c8a3
> Artifact: native-artifacts/claude-code/dev-gan.mlview.json (rev-dev-gan-20260917-1)
> optimizer-ownership (provisional: supported): The optimizer parameter sources and later step ownership match the source.
optimizer-ownership: pending
> discriminator-objective (provisional: supported): The artifact accurately decomposes real and detached-fake BCE terms, sums them, backpropagates, and steps D.
discriminator-objective: pending
> detach-and-generator-path (provisional: qualified): The graph path interpretation is materially correct, but gradient effects are framework semantics and several corresponding nodes and edges are labeled observed.
detach-and-generator-path: pending
> alternating-cycle (provisional: supported): The source order and separate batch and epoch back-edges clearly show the requested repeated D-then-G cycle.
alternating-cycle: pending
> running-sums (provisional: supported): It correctly distinguishes dead running sums from the instantaneous values printed every 100 steps.
running-sums: pending
> item-sync (provisional: qualified): The claim that item() forces host synchronization is conditional on CUDA; on CPU there is no device synchronization of that kind.
item-sync: pending
> generator-gradient-targets (provisional: qualified): The source proves opt_g was constructed from netG.parameters(), but statements about every imported network parameter and autograd traversal depend on unseen model definitions and framework behavior.
generator-gradient-targets: pending
> epoch-outputs (provisional: supported): It accurately reports sample generation, image writing, checkpoint contents, and the discarded script return value.
epoch-outputs: pending
> sample-directory-risk (provisional: qualified): The missing directory creation is source-observed, while failure depends on save_image/PIL behavior; the finding is appropriately inferred but its medium severity is model judgment.
sample-directory-risk: pending
> usability.dataOrigin (provisional: clear): Data path, transforms, and loader settings are detailed.
usability.dataOrigin: pending
> usability.updatedParametersAndFitState (provisional: clear): Optimizer construction, zeroing, backwards, and update sequence are explicit.
usability.updatedParametersAndFitState: pending
> usability.losses (provisional: clear): All three BCE uses and their targets are explicit.
usability.losses: pending
> usability.evaluationBoundaries (provisional: clear): No holdout is claimed; fixed-noise sampling is separated as output.
usability.evaluationBoundaries: pending
> usability.outputs (provisional: clear): Instantaneous logging, dead sums, images, checkpoints, and return behavior are distinguished.
usability.outputs: pending
> usability.uncertainty (provisional: partial): Coverage is extensive, but some framework-derived gradient and synchronization claims are presented as observed or unconditional.
usability.uncertainty: pending

## dev-notebook / copilot
Ledger: native-reviews/copilot/dev-notebook.json 501027a8532c7d21d2973b305a8b6c500cb32a5f2a16e68b2396cfa22e84b030
> Artifact: native-artifacts/copilot/dev-notebook.mlview.json (dev-notebook-rev-1)
> source-flow (provisional: supported): The four coarse nodes preserve the stored source sequence from imports through load, preparation, and training.
source-flow: pending
> recorded-order (provisional: supported): The execution-order finding correctly reports saved counts 1,3,2,4 and qualifies them as metadata rather than proof of runtime history.
recorded-order: pending
> data-load (provisional: supported): The relative features.npz load and X/y extraction are accurately summarized.
data-load: pending
> full-data-scaling (provisional: omitted): The artifact does not state that StandardScaler.fit_transform runs on all X before the holdout split, a material leakage risk.
full-data-scaling: pending
> unused-holdout (provisional: omitted): X_test and y_test are created but never consumed; the artifact does not surface that the holdout is unused.
unused-holdout: pending
> missing-zero-grad (provisional: omitted): No zero_grad call exists in the loop, so standard PyTorch behavior accumulates parameter gradients across batches; this is absent.
missing-zero-grad: pending
> training-loop (provisional: qualified): The forward, cross-entropy, backward, and Adam step sequence is present, but calling it a single gradient-descent loop is loose and omits optimizer state and missing gradient clearing.
training-loop: pending
> absent-evaluation (provisional: omitted): The notebook contains no test prediction, metric, validation, display, or model persistence, and the artifact does not report these absences.
absent-evaluation: pending
> data-contract (provisional: omitted): The artifact does not explain that feature width, dtypes, label range, row count, and file availability are unresolved without features.npz.
data-contract: pending
> usability.dataOrigin (provisional: partial): features.npz is named, but its missing runtime contract is not explained.
usability.dataOrigin: pending
> usability.updatedParametersAndFitState (provisional: partial): Adam stepping is shown, while scaler fit scope and missing gradient clearing are absent.
usability.updatedParametersAndFitState: pending
> usability.losses (provisional: clear): Cross-entropy is named in the training summary.
usability.losses: pending
> usability.evaluationBoundaries (provisional: missing): The artifact does not say the test split is unused or that no evaluation occurs.
usability.evaluationBoundaries: pending
> usability.outputs (provisional: missing): No metric, notebook output, or persistence absence is reported.
usability.outputs: pending
> usability.uncertainty (provisional: partial): Execution-count uncertainty is good, but missing data-contract and training-semantics uncertainty remain.
usability.uncertainty: pending

## dev-notebook / codex
Ledger: native-reviews/codex/dev-notebook.json d461210303df0ff53bddf5f17f658c0fd1cd69bfedf7e2b19792d267f5751d43
> Artifact: native-artifacts/codex/dev-notebook.mlview.json (rev-leak-out-of-order-native-1)
> source-order (provisional: supported): The artifact correctly lays out cells 0, 1, 2, and 3 in stored source order.
source-order: pending
> recorded-order (provisional: supported): It correctly derives the saved-count order 0, 2, 1, 3 and states that these last-saved counters do not prove a fresh-kernel execution history.
recorded-order: pending
> dependency-mismatch (provisional: supported): Cell 2 reads X and y while their only visible assignments are in cell 1, creating an unresolved kernel-state dependency under saved-count order.
dependency-mismatch: pending
> full-data-scaling (provisional: supported): The notebook calls fit_transform(X) before splitting X_scaled, so scaler fitting includes the eventual test rows in any successful execution of cell 2.
full-data-scaling: pending
> gradient-clearing (provisional: qualified): The source omission of zero_grad is directly observable; cross-batch gradient accumulation is a PyTorch semantic inference, and the artifact marks the finding inferred.
gradient-clearing: pending
> optimizer-and-loss (provisional: supported): It correctly identifies the Linear(10,3) model, CrossEntropyLoss, Adam over model.parameters(), and one loader loop with backward then step.
optimizer-and-loss: pending
> unused-holdout (provisional: supported): The artifact notes that X_test and y_test have no later consumer and no evaluation occurs in the notebook.
unused-holdout: pending
> data-contract (provisional: supported): Runtime shape, dtype, label encoding, and file availability remain unresolved because features.npz was not inspected.
data-contract: pending
> outputs (provisional: supported): The artifact correctly indicates no metric, evaluation, display, model save, or checkpoint in the inspected notebook.
outputs: pending
> usability.dataOrigin (provisional: clear): features.npz and its unresolved runtime contract are explicit.
usability.dataOrigin: pending
> usability.updatedParametersAndFitState (provisional: clear): Scaler fitting and Adam updates are both represented, including missing gradient clearing.
usability.updatedParametersAndFitState: pending
> usability.losses (provisional: clear): CrossEntropyLoss and the backward/step loop are identified.
usability.losses: pending
> usability.evaluationBoundaries (provisional: clear): The split is shown and the unused holdout and absent evaluation are explicit.
usability.evaluationBoundaries: pending
> usability.outputs (provisional: clear): The absence of notebook outputs, metrics, and persistence is stated.
usability.outputs: pending
> usability.uncertainty (provisional: clear): Source order, saved-count order, kernel state, and absent data are carefully separated.
usability.uncertainty: pending

## dev-notebook / claude-code
Ledger: native-reviews/claude-code/dev-notebook.json 1c1a2cf5b2fa82dc493e2f81c690a61f5187494d92cf7d6bd9d1b9319e63c611
> Artifact: native-artifacts/claude-code/dev-notebook.mlview.json (rev-20260917-leak-out-of-order-1)
> source-and-recorded-order (provisional: supported): Source order and saved-count order are separately represented, with recorded order explicitly treated as hypothetical metadata rather than executed history.
source-and-recorded-order: pending
> kernel-state-dependency (provisional: supported): The artifact correctly explains that cell 2 reads X/y before their visible load under saved-count order and that success depends on unrecorded kernel state.
kernel-state-dependency: pending
> full-data-scaling (provisional: qualified): The source directly proves fit_transform(X) precedes the split; the interpretation as leakage relies on StandardScaler semantics, which coverage discloses.
full-data-scaling: pending
> unused-holdout (provisional: supported): It correctly identifies X_test/y_test as bound but never read and states that no evaluation, metric, prediction, or saving follows.
unused-holdout: pending
> gradient-accumulation (provisional: qualified): Missing zero_grad is source-observed, while accumulation behavior is framework knowledge; the finding and backward node overstate the behavioral conclusion as observed.
gradient-accumulation: pending
> data-contract (provisional: supported): Absent features.npz leaves shape, dtype, row count, labels, and runtime compatibility unresolved.
data-contract: pending
> single-pass-training (provisional: supported): There is one DataLoader loop with no enclosing epoch loop, and the forward, loss, backward, and step call order is accurately shown.
single-pass-training: pending
> next-batch-edge (provisional: qualified): The loop-back to a next batch is conditional on the loader yielding another batch; row count is unknown, so a second iteration is not source-established.
next-batch-edge: pending
> environment-setup (provisional: supported): The IPython magic, unpinned pip install, and the fact sklearn is imported before that install are accurately described with runtime qualification.
environment-setup: pending
> usability.dataOrigin (provisional: clear): features.npz, relative-path behavior, and missing data contract are explicit.
usability.dataOrigin: pending
> usability.updatedParametersAndFitState (provisional: clear): Scaler fitting, Adam ownership, backward, stepping, and missing zeroing are shown.
usability.updatedParametersAndFitState: pending
> usability.losses (provisional: clear): Cross-entropy on outputs and labels is explicit.
usability.losses: pending
> usability.evaluationBoundaries (provisional: clear): The 80/20 split, unused holdout, and absent evaluation are prominent.
usability.evaluationBoundaries: pending
> usability.outputs (provisional: clear): The artifact states that no metric, display, model, checkpoint, or other persisted result is produced.
usability.outputs: pending
> usability.uncertainty (provisional: clear): Kernel history, saved counters, data contract, and library-semantic assumptions are disclosed; the conditional next-batch edge is the remaining overstatement.
usability.uncertainty: pending

## Baselines
Ledger: native-reviews/baselines.json aef7ee5b2c1d1319af4884bfca67fe416561c70813882ffaa790a2d62f3687e9
> copilot (provisional): The native response covers the requested training flow and most source-supported unknowns in readable prose; the registered Copilot artifact makes the phase sequence explicit but is weaker at localizing uncertainty than the other artifacts.
copilot: pending
> codex (provisional): The native response gives a compact, source-linked account of configured distillation and clearly separates runtime unknowns; the registered Codex artifact adds a navigable execution graph and explicit unresolved nodes.
codex: pending
> claude-code (provisional): The accessibility-transcribed native response is the most detailed baseline, adding useful operational implications and careful runtime caveats; the registered Claude Code artifact preserves those distinctions as explicit nodes, findings, and uncertainty coverage.
claude-code: pending

## Task
Review: pending
