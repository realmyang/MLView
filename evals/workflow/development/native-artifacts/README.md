# Native development artifact snapshots

These files are byte-identical snapshots published by native assistants
during the September 17, 2026 development exercise. They are checked in so
reviewers can inspect concrete WorkflowDocument outputs without relying on the
ignored run directories. [`manifest.json`](manifest.json) records their hashes
and provenance. Initial outputs remain immutable; challenged revisions are
stored separately under [`refinements/`](refinements/) with explicit parents.

This is artifact publication only. The snapshots are model-authored outputs,
not semantic ground truth, human-approved references, accuracy measurements, or
proof of a complete native UI workflow. Human semantic review remains pending.
Raw assistant and UI logs remain ignored. Final native UI responses for the
Codex notebook and Claude Code GAN runs were initially unavailable after a
desktop-control failure, then recovered and observed in their completed native
sessions. This recovery does not establish diagram UI acceptance.

The recorded source bytes match repository commit
`36dbbe5597de496b9807b0e52ef232ceca1df89e` and installed skill SHA-256
`fbbdf1aa3d203b925fe9068a58e98ebfe60780db1ab3c36c5ce384ac6bc5f6a7`.
The notebook artifact records the original installed skill layout under
`.agents/skills/mlview/`; reconstructing that layout is required to revalidate
all of its recorded file hashes. The snapshot itself remains reviewable here.
Reconstructing each artifact's recorded files from that commit, together with
its frozen helper, passed all ten validations in clean temporary workspaces.

Provisional source review found that the initial Codex GAN artifact can imply that its
running loss sums are periodically printed. The source instead prints current
batch losses while the accumulated variables are never read. The initial
artifact is preserved unchanged as the challenge case. The actual challenge
child, `codex-dev-gan-r2.mlview.json`, corrects the explanation while retaining
all node, edge, finding, evidence, and phase IDs. Its semantics still await
human review and carry no accuracy score.

Provisional source review of the Claude Code GAN snapshot found its core control
order, optimizer ownership, detach/attached paths, alternating cycle, and two
findings materially source-supported. Several framework and gradient statements
are labelled observed where the available evidence supports inferred; the
`.item()` synchronization cost is conditional on CUDA, and a few inventory and
parameter-set claims are broader than the supplied source proves. The snapshot
is preserved unchanged, passed publication-safety review, and still awaits
human semantic review.

The Copilot grouped-CV snapshot supports the visible call-site flow. Its
`observed` labels overstate what the supplied source establishes about
StratifiedGroupKFold library behavior and conditional class balance. Missing
custom encoder and feature modules also leave their internal fitting and
preprocessing behavior unverified. These are provisional review notes; the
original output remains unchanged pending human review.
