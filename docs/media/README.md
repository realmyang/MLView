# docs/media

The three screenshots the root `README.md` embeds. All of them are one browser
run over the shipped sample, at 1600x1000, light theme, device scale factor 1 —
no retouching, no composited mock-ups, no cropping other than the one clip noted
below.

| File | What it shows |
|---|---|
| `hero.png` | The whole workspace graph with the answer card folded away: stage bands, typed edges, severity markers, the issue rail. |
| `scoped.png` | The same report scoped to the evaluation concern at depth 1 — the breadcrumb reads `19 of 59 nodes` and the rail `3 of 15 findings shown · 12 outside this scope`, which is what makes a scope a view rather than a filter. |
| `issues.png` | The four-answer card and the issue rail, clipped to the top 600 px of the window. |

## Regenerating them

The report is analyzed from a copy of `samples/vision_pipeline` placed outside a
home directory, because the viewer's title bar shows the analyzed root and these
images are published:

```sh
mkdir -p /tmp/mlview-demo && cp -R samples/vision_pipeline /tmp/mlview-demo/
python -m mlview analyze /tmp/mlview-demo/vision_pipeline --html /tmp/report.html
```

That run prints `59 nodes · 51 edges · 5 high / 6 medium / 4 low`, the same
figures as `python -m mlview analyze samples/vision_pipeline` — the analysis does
not depend on where the copy sits.

Then drive the report with Playwright (`chromium.launch({ channel: 'chrome' })`
against a locally installed Chrome), in a **fresh browser context per shot**:
the report remembers the collapsed answer card, the theme and the active scope
in the viewer's own storage, so a second `page.goto()` in the same context
inherits the first shot's state.

Per shot: open the file URL, wait for the layout, click `Light` in the theme
switch, then

* `hero.png` — click `.mlv-answers__head`, click `[aria-label="Fit to view"]`,
  full-viewport screenshot;
* `scoped.png` — open the scope picker (`.mlv-btn--scope`), click
  **Evaluation & inference**, reopen the picker, click **1 hop**, close the
  picker with its own `Close the scope picker` button (`Escape` clears the
  scope rather than closing the picker), fit, full-viewport screenshot;
* `issues.png` — screenshot with `clip: { x: 0, y: 128, width: 1600, height: 600 }`.

Keep each file under 300 KB and the directory under 1 MB; at this viewport a
PNG lands around 130-190 KB, so downscaling has not been needed.
