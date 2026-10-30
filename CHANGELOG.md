# Changelog

Changes that users will notice are listed here, newest first.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.4.0] - 2026-10-30

### Added

- The `mlview` skill for GitHub Copilot, Codex and Claude Code. Your assistant
  reads an ML project and writes a diagram of its workflow: steps, connections
  and findings, with quotes from the files it read.
- The skill's helper checks a draft's structure, cited paths and exact quotes,
  records file hashes, and publishes a `*.mlview.json` file.
- The viewer, a VS Code extension that opens a `*.mlview.json` file as a
  diagram.
- In the viewer, Enter opens the cited lines beside the diagram.
- A review walk that goes through a diagram claim by claim, a phase overview,
  and a search over steps, findings, IDs and cited text.
- In the review walk, a mark on the line of a connection that has an end out
  of view, and the key `o`, which brings that end into view.
- **Reveal in Diagram**, a command for a file that an open diagram cites.
- A banner on the diagram when a cited file changed after the revision was
  published.
- A prompt for your assistant that the viewer copies when you ask for a
  refinement, and a list of the changes since the previous revision.
- Export of the diagram as an SVG or a PNG image.
- A Claude Code plugin that holds the skill.
- An installer that copies the skill into a project. Its `--doctor` option
  inspects the skill locations of a project without writing.

0.4.0 is the first release. Earlier version numbers were development builds;
none was published as a GitHub release, on the VS Code Marketplace or on Open
VSX. The Claude Code plugin could be installed from this repository during
development.
