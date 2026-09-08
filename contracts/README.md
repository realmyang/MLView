# contracts/

Frozen interfaces every MLView component codes against.

- `graph.schema.json` - the MLGraph JSON Schema (Draft 2020-12). Mirrored at `analyzer/src/mlview/schema/graph.schema.json`.
- `graph.sample.json` - the hand-authored golden document (`python -m mlview analyze --demo` emits exactly this).
- The textual contracts (CLI, in-process API, rule API, webview message protocol, MCP tools, Copilot contributions, renderer API, repository layout) live in `../docs/CONTRACTS.md`. Section 10 "Prototype amendments" overrides everything above it.
