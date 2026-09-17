# Native development artifact snapshots

These five files are byte-identical snapshots published by native assistants
during the September 17, 2026 development exercise. They are checked in so
reviewers can inspect concrete WorkflowDocument outputs without relying on the
ignored run directories. [`manifest.json`](manifest.json) records their hashes
and provenance.

This is artifact publication only. The snapshots are model-authored outputs,
not semantic ground truth, human-approved references, accuracy measurements, or
proof of a complete native UI workflow. Human semantic review remains pending.
Raw assistant and UI logs remain ignored. In particular, the final native UI
response for the Codex notebook run was not observed.

The recorded source bytes match repository commit
`36dbbe5597de496b9807b0e52ef232ceca1df89e` and installed skill SHA-256
`fbbdf1aa3d203b925fe9068a58e98ebfe60780db1ab3c36c5ce384ac6bc5f6a7`.
The notebook artifact records the original installed skill layout under
`.agents/skills/mlview/`; reconstructing that layout is required to revalidate
all of its recorded file hashes. The snapshot itself remains reviewable here.
Reconstructing each artifact's recorded files from that commit, together with
its frozen helper, passed all five validations in clean temporary workspaces.

Provisional source review found that the Codex GAN artifact can imply that its
running loss sums are periodically printed. The source instead prints current
batch losses while the accumulated variables are never read. The artifact is
preserved unchanged; this is a future challenge case for semantic evaluation.
