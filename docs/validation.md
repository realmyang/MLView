# What is checked, and what is not

This page says what MLView's automated checks cover and what they do not show.
Every statement here about the checks can be checked against the files of this
repository. The exceptions are two records of the maintainer, each with a
date: what the maintainer checked by hand for this version, and the checks
that each sample diagram's session passed.

## What the automated checks cover

[docs/development.md](development.md) has the commands. In short:

- **The helper.** The tests under `skills/mlview/tests/` run the helper on
  drafts and documents in temporary folders, and on the sample diagrams and
  the test documents that this repository holds. They cover its rules for
  structure, paths, quotes, file hashes and notebooks, and its commands.
- **The three validators.** The schema, the helper and the extension each
  state the rules of the format. Every case under
  `contracts/conformance/cases/` records what each of the three must say
  about one document, and a test fails when one of them says something else.
- **The viewer.** Its tests load the built viewer into jsdom, which is not a
  browser, with a stand-in for the extension that records the messages.
- **The extension.** Its tests run in Node, outside VS Code, with
  `vscode-extension/test/mock-vscode.js` in place of the `vscode` module.
- **The packages.** The extension package and the Claude Code plugin folder
  are each compared with an exact list of files, and each skill ZIP is
  compared with the files of the skill.
- **Continuous integration.** `.github/workflows/ci.yml` runs the Python tests
  on Python 3.10 to 3.14. It runs the full check on Linux with Node 20.18.1,
  22, 24 and 26, and on Windows and macOS with Node 22. A third job checks the
  plugin's files with the Claude Code command-line tool.

## What they do not show

- No check calls a model. The product's source holds no model interface, and
  CI reads no secret.
- No check judges whether a diagram is right. The helper and the extension
  compare each quote with the cited lines. A match shows that the lines exist
  and have not changed. It does not show that they support the claim.
- No check in CI or in the full check opens VS Code or a browser.
- No check installs the extension in an editor.
- No check starts a session of an assistant, or asks an assistant to find or
  use the skill. The plugin job runs the `plugin validate` command of the
  command-line tool on the plugin folder and on the marketplace file.

## Checked by hand for this version

The maintainer checked version 0.4.0 by hand on 29 October 2026, on macOS
26.6.2 with VS Code 1.139.0 and Claude Code 2.1.312, with these files:

| File | SHA-256 |
|---|---|
| `mlview-0.4.0.vsix` | `81f831b0da72fc33affb3b997611c3e46c4a0ced234d5054588d00c94ce68e5a` |
| `mlview-skill-shared.zip` | `4af6323b34d53607226e0028e8cb27fa8b75696517b1a9e84c0eca9639382431` |
| `mlview-skill-claude-code.zip` | `21fbed7aef95e76ff0c27108f52d81ff792e6255aa404ac17320809708212c10` |

The released `.vsix` file differs from the checked one only in the date line
of its changelog. The two ZIPs are the checked files.

| Case | |
|---|---|
| macOS | Checked |
| Windows | Not checked |
| Linux | Not checked |
| A remote workspace | Not checked |
| A screen reader | Not checked |
| The `.vsix` file | Checked |
| The shared skill ZIP | Checked |
| The Claude Code skill ZIP | Checked |
| The Claude Code plugin | Checked |
| A session in Claude Code | Checked |
| A session in GitHub Copilot | Not checked |
| A session in Codex | Not checked |
| An update with a diagram open | Checked |

## The sample diagrams

Every sample diagram in [`samples/`](../samples/README.md) records Claude
Code as the assistant that wrote it: its `producer` has
`"host": "claude-code"`. No sample diagram records GitHub Copilot or Codex.

The tests in `tools/test_samples.py` and the extension's tests check that the
schema, the helper and the extension accept each sample diagram, and that the
file hashes it records equal the hashes of the files.

### From the maintainer, 29 October 2026

Before a sample diagram was put in `samples/`, the session that wrote it
passed these checks:

- The helper accepts the diagram in full, and the file hashes it records equal
  a fresh computation.
- Every file that it cites, lists as inspected, names as an entrypoint or
  records a hash of lies inside the sample's folder.
- Its `producer` names the assistant that ran the session, and the one model
  identifier that every turn of the assistant in the session carries. The
  session started no other agent.
- Its `request.question` is the request that was sent to the session.
- The session published it, and any earlier revision that it names was
  published in the same session.
- Its `verification.publishedAt` lies between the start and the end of the
  session.
- It holds neither the path of the folder the session ran in nor the name or
  home folder of the user who ran it.
- The session called no web tool and no connector. Every path that it gave a
  tool for reading, searching or editing files lay inside its workspace, and
  every shell command that ran was the helper or one of a short fixed list.
  The installed skill was the same after the session as before.
- The files of the sample's folder were the same after the session as before
  it.

No sample diagram was edited after its session published it.

## Whether a diagram is right

This repository holds no measurement of how often a diagram is right. Treat a
diagram as the assistant's reading of the code and check it against the cited
lines.

## Report a wrong diagram

A diagram can say something that the code does not do, or leave out something
that it does. To report one:

1. Ask the assistant first. Select the claim in the diagram, choose
   **Challenge this claim** in the Selection tab, and then **Copy prompt**.
   The prompt asks your assistant to check the claim against the code again.
   Paste it into the same conversation.
2. If the answer does not settle it, open an issue with the bug report form
   and choose the area "Interpretation or model-authored finding".
3. Include the claim's title and the quote it cites. Include the request,
   which the About tab shows under **Asked**, and the assistant and the model,
   which it shows under **Provenance**.
4. A diagram file holds quoted lines of your code and the paths of your
   files. Attach the file only when the code is public. Otherwise paste the
   one claim.

A report can lead to a change in the skill's instructions or in the helper's
checks. It cannot change your assistant's model.
