# Releasing

A release of MLView is made by hand. `.github/workflows/` holds the CI
workflow and no workflow that builds or publishes a release. This page lists
the steps in order. [development.md](development.md) describes the build and
the full check.

## Version

The version stands in five places, and `python tools/verify.py --all` fails
when they differ:

- `version` in `webview/package.json`, in `vscode-extension/package.json` and
  in `claude-plugin/.claude-plugin/plugin.json`
- `metadata.version` in `.claude-plugin/marketplace.json`
- the line `export const version = '...';` in `webview/src/main.ts`

Other places repeat it:

- `webview/package-lock.json` and `vscode-extension/package-lock.json` hold
  their package's version as `version` and as `packages[""].version`.
  Change both fields in each lock file to the new version. No check
  compares the lock files with the five places.
- The built viewer holds the literal of `main.ts`. Rebuild
  `webview/dist/mlview.js` and its copy in `vscode-extension/media/` as
  [Generated copies](development.md#generated-copies) says. CI fails when the
  committed files are not what its build writes.
- `vscode-extension/README.md` and `CHANGELOG.md` are the page and the
  changelog that the VSIX carries. A link from one of them to a file of this
  repository names the tag `v<version>`. A test in
  `scripts/test_check_docs.py` fails until every such link names the tag of
  the manifest's version, a path that the tree holds and, where it names a
  heading, a heading of that file.

After the change, search the tracked files for the number that you replaced
with `git grep -n -F`, leaving out the lock files, to find a place that still
holds it.

## Changelog

`CHANGELOG.md` collects the changes of the next version in its top section.
For a release, give that section the heading `## [<version>] - <date>`, with
the day of the release in UTC as the date, and start a new, empty top section
above it under the heading `## [Unreleased]`. Then run
`node vscode-extension/tools/sync-notices.mjs`, which rewrites
`vscode-extension/CHANGELOG.md`, the copy that the VSIX carries. Commit the
version, the changelog and the rebuilt files.

## Build the packages

Build in a clean checkout of the commit of the version and the changelog,
after `sh scripts/e2e.sh` has passed there:

```sh
cd vscode-extension && npm run package && cd ..
python tools/package_skill.py --host shared
python tools/package_skill.py --host claude-code
python scripts/vsix_check.py
shasum -a 256 vscode-extension/*.vsix .mlview/dist/*.zip | sed 's#  .*/#  #' > .mlview/dist/SHA256SUMS
```

`npm run package` writes the `.vsix` file into `vscode-extension/`. The two
ZIPs are `.mlview/dist/mlview-skill-shared.zip` and
`.mlview/dist/mlview-skill-claude-code.zip`. Without an argument,
`scripts/vsix_check.py` checks the newest `.vsix` file in
`vscode-extension/`. Keep `.mlview/dist/SHA256SUMS`, which the last command
writes with the folder taken off each file name, as the checksum file of the
release. In a folder that holds the three downloaded files and `SHA256SUMS`,
`shasum -a 256 -c SHA256SUMS` checks each file and prints `OK` after the name
of each one that matches.

## Check by hand

No automated check opens VS Code or starts a session of an assistant. A
person does these steps with the files that were just built:

1. Install the `.vsix` file in VS Code, and extract a skill ZIP at the root of
   a project that has no checkout of this repository. Follow the guide's
   steps for installing and for a first diagram as they are written.
2. In each assistant that you will report on, start the skill, ask for a
   diagram of a small project and wait for the published file.
3. Open the diagram. Select a step, a connection and a finding, and open
   their cited lines.
4. Right-click a cited line in the editor and choose **Reveal in Diagram**.
   Check that the menu of a file that the diagram does not cite does not
   offer the command.
5. Open a diagram that cites a notebook cell, and open that cell.
6. Copy a refinement prompt for each intent and paste it to the assistant.
   Look for a new revision in the panel when the assistant publishes one,
   and for none after `explain`.
7. Change and save a cited file. Look for the banner and the stale marks, and
   try to open a quote of that file.
8. Leave an unsaved change in a cited file and try to open its quotes.
9. Save the document with broken JSON, and then with a revision that the
   diagram has already seen replaced. Check that the panel keeps the diagram
   it showed.
10. Reload the window while a diagram is open.

Write down the versions of VS Code and of each assistant that you used, the
operating system, the SHA-256 of each file you checked, and what you checked
and what you did not. The record goes into
[docs/validation.md](validation.md), under "Checked by hand for this version",
with the version and the date.

## Publish

1. Commit the record of the hand check. That commit changes
   `docs/validation.md` and nothing else.
2. Wait until CI has passed on that commit.
3. Tag that commit `v<version>`.
4. Create a draft release for the tag on GitHub. Attach the `.vsix` file, the
   two ZIPs and the checksum file. Attach the files that were checked by
   hand. The one exception is a `.vsix` file built again only because the
   date line of the changelog changed after the check; the record of the
   hand check then says so.
5. Download each attached file and compare its SHA-256 with the checksum
   file.
6. Publish the release.
7. Open the release's page from another machine and download a file.

Nothing in the tree publishes the extension to a marketplace.

## The Claude Code plugin

The entry `mlview-github` in `.claude-plugin/marketplace.json` names this
repository on GitHub and names no tag or commit. Claude Code is expected to
fetch the default branch for that entry, so a change that reaches `main` can
reach its users between two releases, under the same version number. This
depends on the version of Claude Code.

## Sentences to refresh

Some sentences in the documents repeat a value that has its home elsewhere.
Before a release, compare each:

| Sentence | Source |
|---|---|
| The limits table in `docs/format.md` | `tools/test_format_limits.py` compares it with the schema, the helper and the extension |
| The code table in `docs/format.md` | `tools/test_error_catalogue.py` compares it with the helper |
| The versions in the headings of `THIRD_PARTY_NOTICES.md` | `tools/test_notices.py` compares them with `webview/package-lock.json` |
| "Node 20.18.1 or newer" in `README.md`, in `CONTRIBUTING.md` and in `docs/development.md` | `engines.node` in `vscode-extension/package.json` |
| "Python 3.10 or newer" in `README.md`, in `CONTRIBUTING.md` and in `docs/development.md` | The version test in `scripts/check.py` |
| The CI sentences in `docs/validation.md` | The matrix in `.github/workflows/ci.yml` |
| The record under "Checked by hand for this version" in `docs/validation.md` | The hand check of this release, as [Check by hand](#check-by-hand) describes it |
| "at most 1 MiB" in `docs/development.md` | `CEILING_BYTES` in `scripts/vsix_check.py` |
| The pattern of a `requestId` and "1 to 500 characters" in `docs/architecture.md` | `REQUEST_ID` and the test of `customText` in `vscode-extension/src/authoredPanel.ts` |
| The two tables of files in `docs/architecture.md` | `git ls-files vscode-extension/src webview/src` |
| "VS Code 1.100.0 or newer" in `docs/user-guide.md` and in `vscode-extension/README.md` | `engines.vscode` in `vscode-extension/package.json` |
| "Python 3.10 or newer" in `docs/user-guide.md`, in `vscode-extension/README.md` and in `claude-plugin/README.md` | The version tests in `skills/mlview/scripts/artifact.py` and in `tools/install_skill.py` |
| The command table in `vscode-extension/README.md` | `contributes.commands` and `contributes.menus` in `vscode-extension/package.json` |
| "1 to 500 characters" in `docs/user-guide.md` | The test of `customText` in `vscode-extension/src/authoredPanel.ts` |
| `workflowVersion` `"1.0"` in `docs/user-guide.md` | The constant in `contracts/workflow.schema.json` |
| The key table in `docs/user-guide.md` | `KEYMAP` in `webview/src/ui/keymap.ts`; `node webview/tools/keys-table.mjs --check` compares the two, and without `--check` the command prints the table |
