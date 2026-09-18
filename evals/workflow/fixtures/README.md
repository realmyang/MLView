# Workflow evaluation fixtures

This directory contains the small, redistributable ML examples used by the
workflow evaluation suite. Seventeen example files were moved here from the
legacy analyzer fixture tree when the static analyzer was removed: sixteen
Python files and one notebook across the six example projects and the notebook
case.

[`historical-paths.json`](historical-paths.json) records each former path, its
current path, its SHA-256 digest, and the source commit. This makes old review
records and evaluation logs traceable without keeping the retired analyzer
tree.

The eight larger held-out projects are not redistributed. Their URLs, exact
commit pins, sparse paths, licenses, and evaluation targets live in
[`../repositories.json`](../repositories.json). Fetch them into the ignored
`.public-corpus/` directory with:

```bash
python tools/fetch_workflow_repos.py
python tools/fetch_workflow_repos.py --repo nanoGPT
```

Set `MLVIEW_PUBLIC_CORPUS_DIR` to use another destination. Existing checkouts
must be clean and already at the pinned commit; the fetcher refuses to reset or
otherwise alter a changed or mismatched checkout.
