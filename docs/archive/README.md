# docs/archive/

Superseded specifications, kept **verbatim**. Nothing in this directory is normative, and nothing in
it is held to the documentation gate (`scripts/check_docs.py` collects no file two directories deep,
and both files here are in its `SKIP` set for the same reason `docs/CONTRACTS.md` is). An archived
document records what was true on the day it was written; rewriting one to match today's tree would
destroy the only reason to keep it.

| File | What it is |
|---|---|
| `CONTRACTS-v1.0-amended.md` | **MLView Contracts v1.0**, 6316 lines: the frozen prototype spec (§0–§9), the thirteen prototype amendments (§10 A1–A13) and the sixty-two feature amendments (§11.1–§11.61, including 11.13.1, 11.13.2 and 11.17.1; 11.48 and 11.49 were never issued), exactly as they stood on 2026-09-14 — after both hardening rounds and before the consolidation. Superseded by `docs/CONTRACTS.md` (v1.1). |

## How to use it

**To implement something, read `docs/CONTRACTS.md`.** v1.1 carries every normative clause of this
archive, folded into the section that owns it; its §18 is an index from every old amendment number to
the v1.1 section that now carries it, and its §17 lists the forty-three statements that were
contradicted by a later amendment, with the resolution.

**Read the archive when you need the reasoning.** v1.1 kept the rules and dropped the narrative: the
measurement that motivated a clause, the defect it repairs, the audit that found it, the alternatives
that were rejected and why. Every amendment here opens with that story. If you are about to change a
clause and cannot see why it exists, its amendment is where the answer is — find the amendment number
in v1.1 §18, then search this file for `### 11.<n>` or `**A<n> —`.

**The machine paths in an archived document are history too.** `CONTRACTS-v1.0-amended.md` quotes
two example documents that were produced on the author's own Windows machine, so its `workspace.root`
and its `loc.absFile` are a `C:\Users\<name>\Desktop\...` path, written verbatim and still there.
The living tree carries a neutral `/home/mlview/MLView` root everywhere instead -
`contracts/graph.sample.json` and everything generated from it - and nothing outside this directory
names a real machine. The archive keeps what it printed on the day it was written, because a
byte-for-byte copy that has been edited is no longer evidence of anything.

**A figure in an archived amendment is a dated measurement, not a current fact.** The demo's node and
edge counts, corpus recall numbers, bundle sizes and timings were all true when written. §11.35 is an
erratum correcting one of them in place of an edit, §11.53 B restates the `mlview diff` table it
moved, and v1.1 §17 carries both corrections; the rest are simply history. The command named beside a
figure — usually `python -m mlview analyze samples/vision_pipeline --format summary`,
`tools/verify.py --all` or `tools/accuracy.py` — is the authority for what is true now.

## Adding to this directory

Archive a document when it is replaced by a coherent successor, not when it merely goes stale.
Copy it **byte for byte** (`cp`, then `shasum -a 256` both paths and record the match in the commit
message), add a row to the table above saying what superseded it, add it to `check_docs.SKIP`, and
leave it read-only from then on. An archived file is never edited again.
