# MLView — Frozen Contracts

**Status:** FROZEN at T+10 min. Read-only for all agents thereafter.
A needed change to a contract you do not own is **reported, not made**.
An agent must be able to implement its component from this document alone.

**Owners:** §1 §2 §3 §9 — A1 (core). §4 — A4 (vscode). §5 §6 §7 — A5 (hosts). §8 — A3 (viewer).

---

## 0. Universal conventions

These four are the classic bug sources in a tool of this shape. They are frozen here and asserted by tests.

| Convention | Value | Why |
|---|---|---|
| **Line numbers** | **1-based**, inclusive. Matches `ast.lineno` and every editor. |
| **Column numbers** | **0-based**. Matches `ast.col_offset` and `vscode.Position.character`. The line/column asymmetry is deliberate and is documented on every `Loc`. |
| **Boundary conversion** | Convert **exactly once, at the host boundary**: `new vscode.Position(loc.line - 1, loc.col)`. The standalone HTML builds `vscode://file/{absFile}:{line}:{col + 1}`. Nothing else converts. |
| **Paths** | `file` is **workspace-relative with forward slashes** (`models/net.py`). `absFile` is the absolute path, also forward-slashed. Golden tests compare only `file`. |
| **Edge locations** | An edge's `loc` is the **call site** — the statement that created the dependency — not either endpoint's definition. This is what makes "click a connection" land somewhere useful. |
| **Ids** | **Content-addressed, never line-derived**, so ids survive edits above a node: `nodeId = "n:" + sha1("<file>|<qualname>|<kind>")[:12]`, `edgeId = "e:" + sha1("<sourceId>|<kind>|<targetId>|<label>")[:12]`, `issueId = "i:" + sha1("<code>|<file>|<qualname>|<symbol>")[:12]`. Asserted by `test_node_id_stability.py`. |
| **Ordering** | `stages` by `order`; `nodes` by `(stage order, file, line, col)`; `edges` by `(source, kind, target)`; `issues` by `(severity desc, file, line, code)`; every other array by its natural key. Required for byte-determinism. |
| **Volatile fields** | `generator.generatedAt` and `stats.durationMs` are the **only** fields excluded from equality comparisons. Nothing else may be non-deterministic. |

---

## 1. The graph document — JSON Schema

`contracts/graph.schema.json`, mirrored at `analyzer/src/mlview/schema/graph.schema.json` (asserted equal by `test_schema_current.py`). Emitted by `python -m mlview schema`.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://mlview.dev/schema/mlgraph-1.0.json",
  "title": "MLGraph",
  "description": "The MLView workflow graph document. Produced by `python -m mlview analyze`; consumed identically by the Claude Code plugin and the VS Code extension.",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "generator", "workspace", "stages", "nodes", "edges", "issues", "diagnostics", "stats"],
  "properties": {
    "schemaVersion": { "const": "1.0", "description": "Hosts check the MAJOR component and refuse a mismatch." },
    "generator": { "$ref": "#/$defs/Generator" },
    "workspace": { "$ref": "#/$defs/Workspace" },
    "stages": {
      "type": "array", "minItems": 8, "maxItems": 8,
      "description": "Always all eight canonical stages, sorted by order, including absent ones.",
      "items": { "$ref": "#/$defs/Stage" }
    },
    "nodes":       { "type": "array", "items": { "$ref": "#/$defs/Node" } },
    "edges":       { "type": "array", "items": { "$ref": "#/$defs/Edge" } },
    "issues":      { "type": "array", "items": { "$ref": "#/$defs/Issue" } },
    "diagnostics": { "type": "array", "items": { "$ref": "#/$defs/Diagnostic" } },
    "stats":       { "$ref": "#/$defs/Stats" }
  },
  "$defs": {
    "Severity":         { "enum": ["low", "medium", "high"] },
    "ConfidenceBucket": { "enum": ["certain", "likely", "possible", "speculative"] },
    "Confidence":       { "type": "number", "minimum": 0, "maximum": 1 },
    "RuleCode":         { "type": "string", "pattern": "^MLV[0-9]{3}$" },
    "NodeId":           { "type": "string", "pattern": "^n:[0-9a-f]{12}$" },
    "EdgeId":           { "type": "string", "pattern": "^e:[0-9a-f]{12}$" },
    "IssueId":          { "type": "string", "pattern": "^i:[0-9a-f]{12}$" },
    "StageId": {
      "enum": ["config", "data", "preprocess", "model", "objective", "train", "eval", "deliver"],
      "description": "Canonical pipeline stages, rendered top-to-bottom in this order."
    },
    "Framework": { "enum": ["torch", "sklearn", "pandas", "numpy", "keras", "tf", "hf", "lightning", "imblearn", "torchvision", "torchmetrics", "albumentations", "xgboost", "lightgbm", "other"] },
    "NodeKind": {
      "enum": ["entrypoint", "config", "dataset", "dataloader", "split", "transform", "augment",
               "model", "layer", "loss", "optimizer", "scheduler", "scaler", "train_loop",
               "eval_loop", "metric", "checkpoint", "tracker", "predict", "function", "class",
               "artifact", "external", "unknown"]
    },
    "NodeLevel": {
      "enum": ["stage", "unit", "op"],
      "description": "Three-level hierarchy: stage lane > unit (class/function/loop) > op (call/artifact)."
    },
    "EdgeKind": {
      "enum": ["data", "call", "control", "config"],
      "description": "Containment is expressed by Node.parent, not by an edge."
    },
    "EdgeSubkind": { "enum": ["enter", "back", "branch"], "description": "Only meaningful for kind=control." },
    "ValueTag": {
      "enum": ["RAW_DATA", "FEATURES", "TARGET", "TRAIN_SPLIT", "VAL_SPLIT", "TEST_SPLIT",
               "FITTED_TRANSFORMER", "MODEL", "LOADER", "BATCH", "LOGITS", "PROBS", "PREDS",
               "LOSS", "OPTIMIZER", "DEVICE"]
    },
    "RelatedRole": {
      "enum": ["split_site", "fit_site", "backward_site", "optimizer_site", "step_site",
               "eval_loop", "final_layer", "definition", "call_site", "construction"]
    },
    "Loc": {
      "type": "object",
      "additionalProperties": false,
      "required": ["file", "absFile", "line", "col", "endLine", "endCol"],
      "properties": {
        "file":    { "type": "string", "description": "Workspace-relative, forward slashes." },
        "absFile": { "type": "string", "description": "Absolute, forward slashes." },
        "line":    { "type": "integer", "minimum": 1, "description": "1-based, inclusive (ast.lineno)." },
        "col":     { "type": "integer", "minimum": 0, "description": "0-based (ast.col_offset)." },
        "endLine": { "type": "integer", "minimum": 1 },
        "endCol":  { "type": "integer", "minimum": 0 },
        "symbol":  { "type": "string", "description": "Dotted source text of the target, e.g. scaler.fit_transform. Must occur inside [line..endLine]." },
        "snippet": { "type": "string", "maxLength": 200, "description": "The primary source line, trimmed. Lets the standalone report show code without file access." }
      }
    },
    "RelatedLoc": {
      "type": "object",
      "additionalProperties": false,
      "required": ["role", "file", "absFile", "line", "col", "endLine", "endCol"],
      "properties": {
        "role":    { "$ref": "#/$defs/RelatedRole" },
        "message": { "type": "string", "description": "Shown as DiagnosticRelatedInformation text and as the connector label." },
        "file":    { "type": "string" },
        "absFile": { "type": "string" },
        "line":    { "type": "integer", "minimum": 1 },
        "col":     { "type": "integer", "minimum": 0 },
        "endLine": { "type": "integer", "minimum": 1 },
        "endCol":  { "type": "integer", "minimum": 0 },
        "symbol":  { "type": "string" },
        "snippet": { "type": "string", "maxLength": 200 }
      }
    },
    "Port": {
      "type": "object",
      "additionalProperties": false,
      "required": ["name", "tags"],
      "properties": {
        "name": { "type": "string" },
        "tags": { "type": "array", "items": { "$ref": "#/$defs/ValueTag" } }
      }
    },
    "Evidence": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "detail", "weight"],
      "properties": {
        "kind":   { "enum": ["fqn_resolved", "dataflow_direct", "scope_static", "context_confirmed", "cross_file", "negation_absent", "name_regex", "class_base", "knowledge_table"] },
        "detail": { "type": "string" },
        "weight": { "type": "number", "minimum": 0, "maximum": 1 }
      }
    },
    "IssueCounts": {
      "type": "object",
      "additionalProperties": false,
      "required": ["low", "medium", "high"],
      "properties": {
        "low":    { "type": "integer", "minimum": 0 },
        "medium": { "type": "integer", "minimum": 0 },
        "high":   { "type": "integer", "minimum": 0 }
      }
    },
    "Generator": {
      "type": "object",
      "additionalProperties": false,
      "required": ["name", "version", "rendererSha", "generatedAt"],
      "properties": {
        "name":        { "const": "mlview" },
        "version":     { "type": "string", "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+" },
        "rendererSha": { "type": "string", "pattern": "^[0-9a-f]{64}$", "description": "SHA-256 of the viewer bundle this core ships. A drifted viewer is detectable from the data alone." },
        "generatedAt": { "type": "string", "format": "date-time", "description": "VOLATILE — excluded from every equality comparison." }
      }
    },
    "Workspace": {
      "type": "object",
      "additionalProperties": false,
      "required": ["root", "entrypoints", "filesAnalyzed", "filesFailed", "notebooksSkipped", "frameworks"],
      "properties": {
        "root":             { "type": "string", "description": "Absolute, forward slashes." },
        "entrypoints":      { "type": "array", "items": { "type": "string" }, "description": "Workspace-relative, ranked most-likely-first." },
        "filesAnalyzed":    { "type": "integer", "minimum": 0 },
        "filesFailed":      { "type": "integer", "minimum": 0 },
        "notebooksSkipped": { "type": "integer", "minimum": 0, "description": ".ipynb files detected but not analyzed in this version." },
        "frameworks":       { "type": "array", "items": { "$ref": "#/$defs/Framework" } },
        "configPath":       { "type": "string", "description": "The .mlview.toml that was applied, if any." }
      }
    },
    "Stage": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "label", "order", "present", "nodeCount", "issueCounts", "maxSeverity"],
      "properties": {
        "id":          { "$ref": "#/$defs/StageId" },
        "label":       { "type": "string" },
        "order":       { "type": "integer", "minimum": 0, "maximum": 7 },
        "present":     { "type": "boolean", "description": "False stages are named in the 'not detected' chip row, never drawn as empty bands." },
        "nodeCount":   { "type": "integer", "minimum": 0 },
        "issueCounts": { "$ref": "#/$defs/IssueCounts" },
        "maxSeverity": { "oneOf": [{ "$ref": "#/$defs/Severity" }, { "type": "null" }] }
      }
    },
    "Node": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "kind", "level", "stage", "label", "qualname", "loc", "parent",
                   "attrs", "produces", "consumes", "ghost", "dynamic", "confidence",
                   "confidenceBucket", "issueIds", "collapsedByDefault", "stageEvidence"],
      "properties": {
        "id":       { "$ref": "#/$defs/NodeId" },
        "kind":     { "$ref": "#/$defs/NodeKind" },
        "level":    { "$ref": "#/$defs/NodeLevel" },
        "stage":    { "$ref": "#/$defs/StageId" },
        "label":    { "type": "string", "description": "Primary card title, e.g. 'Adam' or 'for batch in train_loader'." },
        "sublabel": { "type": "string", "description": "Secondary line, e.g. 'lr=1e-3 · wd=0'." },
        "qualname": { "type": "string", "description": "Stable dotted name within the file, e.g. 'train.batch_loop' — an id input, so it must be deterministic." },
        "fqn":      { "type": "string", "description": "Canonical third-party symbol, e.g. 'torch.optim.Adam'." },
        "framework":{ "$ref": "#/$defs/Framework" },
        "var":      { "type": "string", "description": "Source variable this node is bound to, if any." },
        "loc":      { "$ref": "#/$defs/Loc" },
        "defLoc":   { "$ref": "#/$defs/Loc", "description": "The `def`/`class` header line. Used by CodeLens and the reverse cursor lookup." },
        "parent":   { "oneOf": [{ "$ref": "#/$defs/NodeId" }, { "type": "null" }], "description": "Containment. Forms a forest; never cyclic." },
        "attrs":    { "type": "object", "additionalProperties": { "type": "string" }, "description": "Stringified literal keyword arguments only; never evaluated." },
        "produces": { "type": "array", "items": { "$ref": "#/$defs/Port" } },
        "consumes": { "type": "array", "items": { "$ref": "#/$defs/Port" } },
        "ghost":    { "type": "boolean", "description": "True when this node represents a REQUIRED-BUT-ABSENT step (missing zero_grad, missing model.eval()). Rendered as a dashed placeholder in its correct slot carrying the marker." },
        "dynamic":  { "type": "boolean", "description": "True when the enclosing scope contains exec/eval/getattr-on-target/star-import/**kwargs forwarding. Confidence in this scope is multiplied by 0.7." },
        "confidence":       { "$ref": "#/$defs/Confidence" },
        "confidenceBucket": { "$ref": "#/$defs/ConfidenceBucket" },
        "issueIds":         { "type": "array", "items": { "$ref": "#/$defs/IssueId" } },
        "collapsedByDefault": { "type": "boolean" },
        "stageEvidence":      { "type": "array", "items": { "$ref": "#/$defs/Evidence" }, "description": "Backs the inspector's 'why is this node in this stage?' popover." }
      }
    },
    "Edge": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "kind", "source", "target", "loc", "tags", "confidence", "issueIds"],
      "properties": {
        "id":      { "$ref": "#/$defs/EdgeId" },
        "kind":    { "$ref": "#/$defs/EdgeKind" },
        "subkind": { "$ref": "#/$defs/EdgeSubkind" },
        "source":  { "$ref": "#/$defs/NodeId" },
        "target":  { "$ref": "#/$defs/NodeId" },
        "label":   { "type": "string", "description": "Variable name for data edges; 'next batch'/'next epoch' for control back-edges." },
        "loc":     { "$ref": "#/$defs/Loc", "description": "THE CALL SITE — the statement that created the dependency, not either endpoint's definition." },
        "tags":    { "type": "array", "items": { "$ref": "#/$defs/ValueTag" } },
        "confidence": { "$ref": "#/$defs/Confidence" },
        "issueIds":   { "type": "array", "items": { "$ref": "#/$defs/IssueId" } }
      }
    },
    "Issue": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "code", "ruleVersion", "severity", "confidence", "confidenceBucket",
                   "title", "message", "why", "fixHint", "loc", "relatedLocs", "nodeIds",
                   "edgeIds", "stage", "frameworks", "tags", "evidence", "suppressed", "docs"],
      "properties": {
        "id":               { "$ref": "#/$defs/IssueId" },
        "code":             { "$ref": "#/$defs/RuleCode" },
        "ruleVersion":      { "type": "integer", "minimum": 1 },
        "severity":         { "$ref": "#/$defs/Severity" },
        "confidence":       { "$ref": "#/$defs/Confidence" },
        "confidenceBucket": { "$ref": "#/$defs/ConfidenceBucket" },
        "title":            { "type": "string", "description": "One short line, shown in the rail row." },
        "message":          { "type": "string", "description": "Cites concrete evidence — variable names and line numbers — never a restatement of the title." },
        "why":              { "type": "string", "description": "The consequence, in ML terms, in one sentence." },
        "fixHint":          { "type": "string", "minLength": 1, "description": "One actionable sentence naming the actual API." },
        "loc":              { "$ref": "#/$defs/Loc" },
        "relatedLocs":      { "type": "array", "items": { "$ref": "#/$defs/RelatedLoc" }, "description": "Drives the on-canvas connector AND DiagnosticRelatedInformation." },
        "nodeIds":          { "type": "array", "items": { "$ref": "#/$defs/NodeId" }, "description": "nodeIds[0] is the PRIMARY node — that is where the badge is drawn. Others get a 1px severity ring only." },
        "edgeIds":          { "type": "array", "items": { "$ref": "#/$defs/EdgeId" } },
        "stage":            { "$ref": "#/$defs/StageId" },
        "frameworks":       { "type": "array", "items": { "$ref": "#/$defs/Framework" } },
        "tags":             { "type": "array", "items": { "type": "string" } },
        "evidence":         { "type": "array", "items": { "$ref": "#/$defs/Evidence" } },
        "suppressed":       { "type": "boolean", "description": "True when a `# mlview: ignore[CODE]` comment or .mlview.toml matched. Still emitted so the UI can offer 'show suppressed'; never published as a diagnostic." },
        "docs":             { "type": "string", "description": "Relative path to the offline rule doc, e.g. 'docs/rules/MLV101.md'." }
      }
    },
    "Diagnostic": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "message"],
      "properties": {
        "kind": { "enum": ["parse_error", "dynamic_scope", "rule_error", "truncated",
                           "notebook_skipped", "framework_suppressed", "config_warning"] },
        "message":  { "type": "string" },
        "file":     { "type": "string" },
        "line":     { "type": "integer", "minimum": 1 },
        "scope":    { "type": "string" },
        "ruleCode": { "$ref": "#/$defs/RuleCode" },
        "codes":    { "type": "array", "items": { "$ref": "#/$defs/RuleCode" }, "description": "For framework_suppressed: which rules were not applied." },
        "count":    { "type": "integer", "minimum": 0 }
      }
    },
    "Stats": {
      "type": "object",
      "additionalProperties": false,
      "required": ["nodes", "edges", "issues", "durationMs", "truncated"],
      "properties": {
        "nodes":      { "type": "integer", "minimum": 0 },
        "edges":      { "type": "integer", "minimum": 0 },
        "issues":     { "$ref": "#/$defs/IssueCounts" },
        "suppressed": { "type": "integer", "minimum": 0 },
        "durationMs": { "type": "integer", "minimum": 0, "description": "VOLATILE — excluded from every equality comparison." },
        "truncated":  { "type": "boolean", "description": "True when --max-nodes was exceeded; the UI shows a banner." }
      }
    }
  }
}
```

### 1.1 Invariants the renderer relies on

1. All ids are globally unique and stable across runs when the source is unchanged.
2. `parent` forms a forest; no cycles; a node's parent is always a node with a *lower* `level`.
3. `issue.nodeIds[0]` always exists in `nodes[]` and is the primary — that is where the badge is drawn.
4. `stage` is always present on nodes; unclassifiable nodes get `kind: "unknown"` and their best-guess stage.
5. `stages[]` is always all eight, sorted by `order`, including `present: false` entries.
6. **Forward compatibility:** an unknown `kind` / `stage` / `edge.kind` value must still render — the renderer falls back to the `unknown` visual rather than throwing.
7. Every `edge.source` and `edge.target` exists in `nodes[]`.
8. `ghost: true` nodes have `issueIds.length >= 1`.

---

## 2. Example document

`contracts/graph.sample.json` — hand-authored, published at **T+10 min before any analyzer exists**, so the viewer and both host adapters are buildable and testable from minute one. Abridged here to one node of each shape; the real file has 12 nodes, 14 edges and 6 issues.

```json
{
  "schemaVersion": "1.0",
  "generator": {
    "name": "mlview",
    "version": "0.1.0",
    "rendererSha": "274d68d7102444e6e0be5a2438416deb6761c71f2df98ba81cd909fc09d08bd7",
    "generatedAt": "2026-09-06T14:22:11Z"
  },
  "workspace": {
    "root": "C:/Users/realm/Desktop/MLView/samples/vision_pipeline",
    "entrypoints": ["train.py"],
    "filesAnalyzed": 5,
    "filesFailed": 0,
    "notebooksSkipped": 0,
    "frameworks": ["torch", "sklearn", "torchvision"]
  },
  "stages": [
    { "id": "config",     "label": "Configuration", "order": 0, "present": true,
      "nodeCount": 3, "issueCounts": {"low":1,"medium":0,"high":0}, "maxSeverity": "low" },
    { "id": "data",       "label": "Data",          "order": 1, "present": true,
      "nodeCount": 5, "issueCounts": {"low":1,"medium":2,"high":0}, "maxSeverity": "medium" },
    { "id": "preprocess", "label": "Preprocess",    "order": 2, "present": true,
      "nodeCount": 4, "issueCounts": {"low":1,"medium":1,"high":1}, "maxSeverity": "high" },
    { "id": "model",      "label": "Model",         "order": 3, "present": true,
      "nodeCount": 6, "issueCounts": {"low":0,"medium":0,"high":1}, "maxSeverity": "high" },
    { "id": "objective",  "label": "Objective",     "order": 4, "present": true,
      "nodeCount": 3, "issueCounts": {"low":0,"medium":0,"high":1}, "maxSeverity": "high" },
    { "id": "train",      "label": "Train",         "order": 5, "present": true,
      "nodeCount": 7, "issueCounts": {"low":0,"medium":2,"high":1}, "maxSeverity": "high" },
    { "id": "eval",       "label": "Evaluate",      "order": 6, "present": true,
      "nodeCount": 4, "issueCounts": {"low":1,"medium":1,"high":1}, "maxSeverity": "high" },
    { "id": "deliver",    "label": "Save / Deploy", "order": 7, "present": false,
      "nodeCount": 0, "issueCounts": {"low":0,"medium":0,"high":0}, "maxSeverity": null }
  ],
  "nodes": [
    {
      "id": "n:7c1a90b4e2f0",
      "kind": "dataloader", "level": "op", "stage": "data",
      "label": "train_loader", "sublabel": "DataLoader · bs=128",
      "qualname": "data.build_loaders.train_loader",
      "fqn": "torch.utils.data.DataLoader", "framework": "torch", "var": "train_loader",
      "loc": { "file": "data.py", "absFile": "C:/Users/realm/Desktop/MLView/samples/vision_pipeline/data.py",
               "line": 31, "col": 19, "endLine": 36, "endCol": 5,
               "symbol": "DataLoader",
               "snippet": "train_loader = DataLoader(train_ds, batch_size=128, num_workers=4)" },
      "parent": "n:1100aa22bb33",
      "attrs": { "batch_size": "128", "num_workers": "4" },
      "produces": [ { "name": "train_loader", "tags": ["LOADER", "TRAIN_SPLIT"] } ],
      "consumes": [ { "name": "train_ds",     "tags": ["TRAIN_SPLIT"] } ],
      "ghost": false, "dynamic": false,
      "confidence": 0.95, "confidenceBucket": "certain",
      "issueIds": ["i:aa11bb22cc33", "i:dd44ee55ff66"],
      "collapsedByDefault": false,
      "stageEvidence": [
        { "kind": "knowledge_table", "detail": "torch.utils.data.DataLoader -> data", "weight": 1.0 }
      ]
    },
    {
      "id": "n:9c8d7e6f5a4b",
      "kind": "train_loop", "level": "unit", "stage": "train",
      "label": "for images, labels in train_loader", "sublabel": "batch loop · depth 2",
      "qualname": "train.train.batch_loop", "framework": "torch",
      "loc": { "file": "train.py", "absFile": "C:/.../train.py",
               "line": 44, "col": 8, "endLine": 50, "endCol": 34,
               "symbol": "for images, labels in train_loader",
               "snippet": "        for images, labels in train_loader:" },
      "parent": "n:5500cc66dd77",
      "attrs": { "loopKind": "batch", "iterates": "train_loader", "depth": "2",
                 "insideNoGrad": "false", "insideAutocast": "false" },
      "produces": [], "consumes": [ { "name": "train_loader", "tags": ["LOADER", "TRAIN_SPLIT"] } ],
      "ghost": false, "dynamic": false,
      "confidence": 0.95, "confidenceBucket": "certain",
      "issueIds": [], "collapsedByDefault": false,
      "stageEvidence": [
        { "kind": "context_confirmed", "detail": "loop iterates a LOADER-tagged value and contains backward()", "weight": 1.0 }
      ]
    },
    {
      "id": "n:ffee11223344",
      "kind": "optimizer", "level": "op", "stage": "train",
      "label": "zero_grad()", "sublabel": "missing",
      "qualname": "train.train.batch_loop.__ghost_zero_grad",
      "fqn": "torch.optim.Optimizer.zero_grad", "framework": "torch",
      "loc": { "file": "train.py", "absFile": "C:/.../train.py",
               "line": 44, "col": 8, "endLine": 50, "endCol": 34,
               "symbol": "for images, labels in train_loader",
               "snippet": "        for images, labels in train_loader:" },
      "parent": "n:9c8d7e6f5a4b",
      "attrs": {},
      "produces": [], "consumes": [],
      "ghost": true, "dynamic": false,
      "confidence": 0.9, "confidenceBucket": "certain",
      "issueIds": ["i:1234abcd5678"], "collapsedByDefault": false,
      "stageEvidence": [ { "kind": "context_confirmed", "detail": "ghost slot for MLV201", "weight": 1.0 } ]
    }
  ],
  "edges": [
    {
      "id": "e:9f21ab34cd56",
      "kind": "data", "source": "n:7c1a90b4e2f0", "target": "n:9c8d7e6f5a4b",
      "label": "train_loader",
      "loc": { "file": "train.py", "absFile": "C:/.../train.py",
               "line": 44, "col": 30, "endLine": 44, "endCol": 42,
               "symbol": "train_loader", "snippet": "        for images, labels in train_loader:" },
      "tags": ["LOADER", "TRAIN_SPLIT"],
      "confidence": 0.95, "issueIds": []
    },
    {
      "id": "e:00aa11bb22cc",
      "kind": "control", "subkind": "back",
      "source": "n:33dd44ee55ff", "target": "n:9c8d7e6f5a4b", "label": "next batch",
      "loc": { "file": "train.py", "absFile": "C:/.../train.py",
               "line": 44, "col": 8, "endLine": 44, "endCol": 43,
               "symbol": "for", "snippet": "        for images, labels in train_loader:" },
      "tags": [], "confidence": 1.0, "issueIds": []
    }
  ],
  "issues": [
    {
      "id": "i:1234abcd5678",
      "code": "MLV201", "ruleVersion": 1,
      "severity": "high", "confidence": 0.9, "confidenceBucket": "certain",
      "title": "Gradients are never zeroed",
      "message": "The batch loop at train.py:44 calls loss.backward() (line 48) and optimizer.step() (line 49) but never optimizer.zero_grad(). Gradients accumulate across batches.",
      "why": "Accumulated gradients make each update the sum of all previous batches, so training diverges or converges to the wrong place — silently.",
      "fixHint": "Call optimizer.zero_grad(set_to_none=True) as the first statement of the loop body, before the forward pass.",
      "loc": { "file": "train.py", "absFile": "C:/.../train.py",
               "line": 44, "col": 8, "endLine": 50, "endCol": 34,
               "symbol": "for images, labels in train_loader",
               "snippet": "        for images, labels in train_loader:" },
      "relatedLocs": [
        { "role": "optimizer_site", "message": "optimizer created here",
          "file": "train.py", "absFile": "C:/.../train.py",
          "line": 34, "col": 12, "endLine": 34, "endCol": 58,
          "symbol": "optim.Adam", "snippet": "    optimizer = optim.Adam(model.parameters(), lr=0.1)" },
        { "role": "backward_site", "message": "backward here",
          "file": "train.py", "absFile": "C:/.../train.py",
          "line": 48, "col": 12, "endLine": 48, "endCol": 27,
          "symbol": "loss.backward", "snippet": "            loss.backward()" }
      ],
      "nodeIds": ["n:ffee11223344", "n:9c8d7e6f5a4b"],
      "edgeIds": [],
      "stage": "train", "frameworks": ["torch"], "tags": ["correctness", "train-loop"],
      "evidence": [
        { "kind": "fqn_resolved",      "detail": "torch.optim.Adam via `import torch.optim as optim`", "weight": 1.0 },
        { "kind": "context_confirmed", "detail": "loop iterates a LOADER value and contains backward + step", "weight": 1.0 },
        { "kind": "scope_static",      "detail": "no dynamic constructs in train()", "weight": 1.0 },
        { "kind": "negation_absent",   "detail": "no Lightning/HF Trainer/accelerate detected in the workspace", "weight": 1.0 }
      ],
      "suppressed": false,
      "docs": "docs/rules/MLV201.md"
    }
  ],
  "diagnostics": [
    { "kind": "notebook_skipped", "message": "2 notebooks detected but not analyzed in this version.", "count": 2 }
  ],
  "stats": {
    "nodes": 32, "edges": 41,
    "issues": { "low": 4, "medium": 6, "high": 5 },
    "suppressed": 0, "durationMs": 412, "truncated": false
  }
}
```

---

## 3. CLI contract

`contracts/cli.md`. **Both hosts call exactly this.** Nothing else parses Python.

```
python -m mlview analyze <path>... [options]
python -m mlview issues  <path>... [options]
python -m mlview render  [--graph FILE | <path>] [options]
python -m mlview explain (<node-id> | <rule-code>) [--graph FILE] [--json]
python -m mlview rules   [--list | --json | --explain MLV201]
python -m mlview mcp     [--sdk]
python -m mlview schema
python -m mlview --version [--json]
```

### `analyze` options

| Flag | Default | Meaning |
|---|---|---|
| `--json <FILE\|->` | — | Write the graph JSON. `-` means stdout, and then **stdout carries only JSON**. |
| `--html <FILE>` | — | Write a self-contained HTML report (viewer JS + CSS + graph inlined). |
| `--open` | off | Open the HTML afterwards (`os.startfile` on Windows, `webbrowser.open` elsewhere). |
| `--format summary\|json\|mermaid\|text` | `summary` | stdout format when `--json -` is not used. |
| `--include <GLOB>` | — | Repeatable. Restrict discovery. |
| `--exclude <GLOB>` | `**/.venv/**`, `**/site-packages/**`, `**/node_modules/**`, `**/build/**`, `**/.git/**` | Repeatable; **adds to** the defaults. |
| `--min-severity low\|medium\|high` | `low` | Filter emitted issues. |
| `--min-confidence <float>` | `0.0` | Filter emitted issues. |
| `--show-suppressed` | off | Include suppressed issues in `--format summary` output (they are always in the JSON with `suppressed: true`). |
| `--max-files <N>` | `500` | Discovery cap. |
| `--max-nodes <N>` | `400` | Graph cap; sets `stats.truncated`. |
| `--framework auto\|torch\|sklearn\|keras\|hf\|lightning` | `auto` | Restrict framework extractors. |
| `--config <FILE>` | `.mlview.toml` if present | Rule enable/disable and path excludes. |
| `--fail-on none\|low\|medium\|high` | `none` | Exit 2 when an issue at or above the threshold exists. |
| `--strict` | off | Re-raise rule exceptions instead of recording `MLV000`. |
| `--demo` | off | **Emit the golden `contracts/graph.sample.json`.** Exists from T+10 min so downstream agents are never blocked. |
| `--no-color` | off | Plain stderr output. |

`issues` takes `--json`, `--text`, `--min-severity`, `--min-confidence`, `--code MLV201,MLV301`, `--limit N`.
`render` takes `--graph FILE`, `--out FILE`, `--format html|mermaid|text`, `--open`.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Analysis produced a graph — including when `diagnostics[]` is non-empty |
| `1` | Usage or I/O error |
| `2` | `--fail-on` threshold exceeded |
| `3` | Internal error (a JSON error object is written to stdout) |
| `4` | Nothing analyzable found (no `.py` files after filtering) |

### The stdout invariant

**stdout carries only the requested payload.** Every log line, warning, and progress message goes to **stderr**. Enforced by `test_stdout_purity.py`, which greps the core for bare `print(` outside `emit/text_out.py`. A single stray print corrupts a JSON parse or a JSON-RPC frame, and the failure looks like "the tool is broken" rather than "line 40 has a debug print".

### Windows/UTF-8 invariant

Every spawn of the CLI, from either host, must pass `-X utf8` in argv and `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8` in the environment, with `shell: false` and an **absolute** interpreter path. Without them, cp1252 mangles the JSON on a non-ASCII identifier or path.

### The in-process API (`contracts/core_api.md`)

The MCP server imports this rather than shelling out to itself, so argument handling cannot diverge:

```python
# mlview/api.py — FROZEN
from mlview.api import analyze, analyze_to_dict, AnalyzeOptions, MLGraph

@dataclass(frozen=True)
class AnalyzeOptions:
    paths: tuple[str, ...]
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    max_files: int = 500
    max_nodes: int = 400
    framework: str = "auto"
    min_severity: str = "low"
    min_confidence: float = 0.0
    config_path: str | None = None
    strict: bool = False

def analyze(options: AnalyzeOptions) -> MLGraph: ...
def analyze_to_dict(options: AnalyzeOptions) -> dict: ...      # schema-valid, canonically ordered
def render_html(graph: dict, out_path: str) -> str: ...        # returns the absolute path written
def render_mermaid(graph: dict) -> str: ...
def render_text(graph: dict) -> str: ...
def digest(graph: dict, limit_bytes: int = 4096) -> dict: ...  # the ≤4KB model-facing summary
```

### The rule API (`contracts/rule_api.md`)

```python
@rule(code="MLV201", severity="high", base_prior=0.90, frameworks=["torch"],
      rule_version=1, tags=["correctness", "train-loop"], absence=True)
def missing_zero_grad(ctx: GraphContext) -> Iterable[Issue]:
    ...

# GraphContext surface — FROZEN
ctx.graph                      # the partially built MLGraph (nodes/edges/stages)
ctx.frameworks                 # set[Framework] detected in the workspace
ctx.modules                    # dict[relpath, ModuleIR]
ctx.calls_of(fqn) -> list[CallSite]
ctx.loops(kind=None) -> list[LoopIR]           # kind in {"epoch","batch","fold",None}
ctx.values_tagged(tag) -> list[ValueRef]
ctx.binding_of(name, scope) -> ValueRef | None
ctx.class_bases(node) -> list[str]             # resolved canonical base FQNs
ctx.node_for(loc) -> Node | None
ctx.follow_call(call) -> FunctionIR | None      # one level, module-local
ctx.is_dynamic(scope) -> bool
ctx.issue(...) -> Issue                         # builder; applies confidence + severity cap
ctx.ghost(kind, parent_node, label) -> Node     # declares a ghost slot for an absence rule
```

`absence=True` automatically activates the severity cap and the `negation_absent` gate. Rules never construct `Issue` directly — `ctx.issue(...)` computes confidence from the declared evidence and applies the cap.

---

## 4. Webview ↔ host message protocol

`contracts/messages.md`. Every message carries `v: 1`. **Unknown message types are logged and ignored on both sides** — a version skew must degrade, not crash.

### Host → webview

```ts
type HostToUi =
  | { v: 1; type: 'init';            schemaVersion: string; theme: 'light'|'dark'|'hc';
                                     host: 'vscode'|'standalone';
                                     capabilities: { canOpenSource: boolean; canReanalyze: boolean;
                                                     canExport: boolean; canAskAssistant: boolean } }
  | { v: 1; type: 'graph';           requestId: string; graph: MLGraph;
                                     preserve?: { viewport?: Viewport; selection?: Sel;
                                                  collapsed?: string[] } }
  | { v: 1; type: 'analysisStarted'; requestId: string; scope: 'workspace'|'file'; path?: string }
  | { v: 1; type: 'analysisProgress';requestId: string; done: number; total: number; file?: string }
  | { v: 1; type: 'analysisFailed';  requestId: string; message: string; detail?: string;
                                     actions?: { id: string; label: string }[] }
  | { v: 1; type: 'theme';           kind: 'light'|'dark'|'hc' }
  | { v: 1; type: 'revealNode';      nodeId: string; center?: boolean; approximate?: boolean }
  | { v: 1; type: 'revealIssue';     issueId: string }
  | { v: 1; type: 'cursorHint';      file: string; line: number }        // followCursor, P2
  | { v: 1; type: 'setFilter';       severities?: ('low'|'medium'|'high')[]; codes?: string[];
                                     query?: string }
  | { v: 1; type: 'stale';           changedFiles: string[] }
  | { v: 1; type: 'restoreState';    state: ViewState };
```

### Webview → host

```ts
type UiToHost =
  | { v: 1; type: 'ready' }
  | { v: 1; type: 'openLocation';  file: string; absFile: string;
                                   line: number; col: number;
                                   endLine: number; endCol: number; preview?: boolean }
  | { v: 1; type: 'selectNode';    nodeId: string | null }
  | { v: 1; type: 'requestRefresh';scope: 'workspace'|'file'; path?: string }
  | { v: 1; type: 'exportHtml' }
  | { v: 1; type: 'copy';          text: string }
  | { v: 1; type: 'saveState';     state: ViewState }
  | { v: 1; type: 'action';        id: string }                 // error-banner buttons
  | { v: 1; type: 'askAssistant';  nodeId: string; prompt: string }
  | { v: 1; type: 'log';           level: 'debug'|'info'|'warn'|'error'; message: string };
```

### `openLocation` — the host's obligations

```ts
const uri = vscode.Uri.file(path.resolve(workspaceRoot, msg.file));
// SECURITY: node paths originate from parsing arbitrary source. A webview must never be
// able to talk the extension into opening ~/.ssh/id_rsa.
if (!vscode.workspace.getWorkspaceFolder(uri)) {
  log.warn(`refused out-of-workspace open: ${uri.fsPath}`);
  return;
}
const doc = await vscode.workspace.openTextDocument(uri);
// THE ONE AND ONLY boundary conversion: line is 1-based, col is 0-based.
const sel = new vscode.Range(msg.line - 1, msg.col, msg.endLine - 1, msg.endCol);
const ed  = await vscode.window.showTextDocument(doc, {
  viewColumn: vscode.ViewColumn.One, selection: sel, preview: !!msg.preview });
ed.revealRange(sel, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
```

`StandaloneBridge` implements the same message by navigating to `vscode://file/${absFile}:${line}:${col + 1}` and, after 400 ms with no blur event, copying `${file}:${line}` and showing a toast.

### Webview creation (frozen)

```ts
const panel = vscode.window.createWebviewPanel('mlview.diagram', 'MLView', vscode.ViewColumn.Beside, {
  enableScripts: true,
  localResourceRoots: [vscode.Uri.joinPath(ctx.extensionUri, 'media')]
  // NOTE: retainContextWhenHidden is deliberately NOT set. State lives in
  // getState/setState + a WebviewPanelSerializer registered for 'mlview.diagram'.
});
const nonce = randomBytes(24).toString('base64');
panel.webview.html = `<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none';
  img-src ${panel.webview.cspSource} data:;
  style-src ${panel.webview.cspSource} 'unsafe-inline';
  font-src ${panel.webview.cspSource};
  script-src 'nonce-${nonce}';">
<link rel="stylesheet" href="${styleUri}"></head>
<body><div id="mlview-root"></div>
<script nonce="${nonce}" src="${scriptUri}"></script></body></html>`;
```

`'unsafe-inline'` is granted for **styles only** (nodes carry positional styles). Scripts are nonce-locked, and `default-src 'none'` is the CSP-level enforcement of the offline requirement.

---

## 5. MCP tools (Claude Code)

`contracts/mcp.md`. Transport: **stdio, newline-delimited JSON-RPC 2.0**, hand-rolled with stdlib only (`claude-plugin/server/mlview_mcp.py`, ~180 lines). Handles `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping`. It echoes the client's `protocolVersion` back, defaulting to `2025-06-18`, and declares `{"capabilities": {"tools": {}}}`. **stdout carries protocol frames only; every log goes to stderr.**

`.mcp.json` at the plugin root (the default scan location, so `plugin.json` omits the override field entirely):

```json
{
  "mcpServers": {
    "mlview": {
      "type": "stdio",
      "command": "python",
      "args": ["${CLAUDE_PLUGIN_ROOT}/server/mlview_mcp.py"],
      "env": {
        "PYTHONPATH": "${CLAUDE_PLUGIN_ROOT}/vendor",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "MLVIEW_PROJECT_DIR": "${CLAUDE_PROJECT_DIR}",
        "MLVIEW_DATA_DIR": "${CLAUDE_PLUGIN_DATA}"
      }
    }
  }
}
```

`${CLAUDE_PLUGIN_ROOT}/vendor` on `PYTHONPATH` is what makes the plugin work with **no pip install at all**.

### The five prototype tools

Every result is `{ "content": [{"type":"text","text": <json string>}], "structuredContent": <object>, "isError": false }`, and **every model-facing payload is capped at 4 KB** with full detail behind `graphPath`.

| Tool | Input schema | Returns (`structuredContent`) |
|---|---|---|
| **`mlview_analyze`** | `{ path?: string, framework?: string, maxNodes?: integer, includeHtml?: boolean }` | `{ schemaVersion, root, filesAnalyzed, filesFailed, notebooksSkipped, frameworks[], stats{nodes,edges,issues{low,medium,high}}, lanes:[{stage,label,nodeCount,maxSeverity}], topIssues:[{code,severity,confidenceBucket,title,file,line}] (≤10), graphPath, reportPath?, truncated }` |
| **`mlview_issues`** | `{ path?: string, minSeverity?: "low"\|"medium"\|"high", minConfidence?: number, code?: string[], limit?: integer }` | `{ countBySeverity{low,medium,high}, suppressedCount, issues:[{id,code,severity,confidenceBucket,title,message,fixHint,file,line,related:[{role,file,line}]}] }` |
| **`mlview_graph`** | `{ path?: string, format?: "mermaid"\|"text"\|"json", scope?: "stages"\|"stage:<id>"\|"node:<id>", depth?: integer }` | `{ format, content }` — **mermaid is the default**, so Claude gets a compact textual diagram it can reason about in the terminal without ingesting the whole graph |
| **`mlview_explain`** | `{ nodeId?: string, code?: string, graphPath?: string }` | For a node: the node record + in/out edges + its issues + `stageEvidence` + a ≤60-line source segment. For a rule code: the full rule doc (detection rationale, false-positive notes, fix). |
| **`mlview_open_diagram`** | `{ path?: string, graphPath?: string, out?: string }` | `{ reportPath, reportUrl, opened: boolean }` — writes the self-contained HTML and opens it in the default browser |

**Later tier (not in the prototype):** `mlview_locate({query, kind?})` → `[{nodeId,label,file,line,col}]`, letting the agent resolve "the training loop" to a `file:line` before calling `Read`; and `mlview_rule_doc({code})`.

### Slash commands and skills

- `commands/mlview.md` — frontmatter `description`, `argument-hint: "[path]"`, `allowed-tools: [Bash, Read, Glob]`. Body: prefer `mlview_analyze` + `mlview_open_diagram` when the MCP tools are available; **otherwise** run `python -m mlview analyze "$1" --json .mlview/graph.json --html .mlview/report.html --open --format summary` through `Bash`. That fallback is why the demo does not depend on MCP registration succeeding.
- `commands/mlview-issues.md` — headless: prints only the issue table (`--format summary --min-severity …`), for agent loops and PR descriptions.
- `skills/mlview-visualize/SKILL.md` — triggers on "visualize / diagram / map / review the structure of ML code"; instructs the model to call `mlview_analyze` then `mlview_issues` **before** reading files, so the review starts from recovered structure rather than from a linear read.
- `skills/mlview-triage/SKILL.md` — takes the issue list, reads the relevant source, proposes fixes. It explicitly does **not** auto-edit.

### `plugin.json`

```json
{
  "name": "mlview",
  "displayName": "MLView",
  "version": "0.1.0",
  "description": "Visualize and audit Python ML pipelines as an interactive diagram — fully local, static analysis only.",
  "author": { "name": "MLView" },
  "license": "MIT",
  "keywords": ["machine-learning", "pytorch", "visualization", "static-analysis"]
}
```

Component-path fields (`commands`, `skills`, `agents`, `hooks`, `mcpServers`) are **deliberately omitted** — the conventional directories are the defaults. Note the verified asymmetry: `skills` *adds to* the default scan while `commands`/`agents` *replace* it, so setting them by accident silently drops the defaults.

Install paths, in order of preference for today: `claude --plugin-dir <abs>/claude-plugin` (session-only, zero install) · the repo-root `.claude-plugin/marketplace.json` plus `/plugin marketplace add ./` and `/plugin install mlview@mlview-local` · `claude mcp add mlview -- python <abs>/claude-plugin/server/mlview_mcp.py` (MCP only). Run `claude plugin validate ./claude-plugin --strict` first, always.

---

## 6. Copilot / VS Code contributions

### Chat participant

```jsonc
"chatParticipants": [{
  "id": "mlview.chat",
  "name": "mlview",
  "fullName": "MLView",
  "description": "Diagram and audit the ML pipeline in this workspace",
  "isSticky": true,
  "commands": [
    { "name": "diagram", "description": "Open the interactive ML workflow diagram" },
    { "name": "issues",  "description": "List detected ML issues by severity" },
    { "name": "explain", "description": "Explain a stage or a rule code (e.g. MLV201)" }
  ]
}]
```

Registered as `vscode.chat.createChatParticipant('mlview.chat', handler)` — the id **must** match the manifest. `/issues` streams each finding via `stream.markdown(...)` followed by `stream.anchor(new vscode.Location(uri, range), 'train.py:44')`, so every finding in chat is a click into the source; `/diagram` opens the panel and offers `stream.button({ command: 'mlview.showIssues', title: 'Show issues' })`. The free-form path is the only place a cloud model is touched, and the participant says so in its first response.

### Language-model tools

```jsonc
"languageModelTools": [
  {
    "name": "mlview_analyzeWorkspace",
    "toolReferenceName": "mlviewAnalyze",
    "displayName": "Analyze ML Workflow",
    "modelDescription": "Statically analyze the Python ML code in the workspace (or one file) and return the pipeline structure: stages, connections, frameworks, and a summary of detected issues with file and line numbers. Does not execute the user's code. Use before answering questions about how training or evaluation is wired together.",
    "userDescription": "Analyze the ML workflow in this workspace",
    "canBeReferencedInPrompt": true,
    "icon": "$(graph)",
    "tags": ["mlview", "machine-learning", "static-analysis"],
    "inputSchema": { "type": "object", "properties": {
      "path": { "type": "string", "description": "Optional workspace-relative file or folder; defaults to the whole workspace." } } }
  },
  {
    "name": "mlview_listIssues",
    "toolReferenceName": "mlviewIssues",
    "displayName": "List ML Issues",
    "modelDescription": "Return detected machine-learning correctness and hygiene issues (rule code, severity, message, fix hint, file and line). Use when asked what is wrong with the training code, or before proposing fixes.",
    "userDescription": "List detected ML issues",
    "canBeReferencedInPrompt": true,
    "icon": "$(warning)",
    "tags": ["mlview", "machine-learning", "diagnostics"],
    "inputSchema": { "type": "object", "properties": {
      "minSeverity": { "type": "string", "enum": ["low", "medium", "high"] },
      "code": { "type": "string", "description": "Filter to one rule code, e.g. MLV201" } } }
  },
  {
    "name": "mlview_showDiagram",
    "toolReferenceName": "mlviewDiagram",
    "displayName": "Show ML Diagram",
    "modelDescription": "Open the interactive MLView diagram panel for the user, optionally focused on a specific node.",
    "userDescription": "Open the MLView diagram",
    "canBeReferencedInPrompt": true,
    "icon": "$(preview)",
    "tags": ["mlview"],
    "inputSchema": { "type": "object", "properties": { "focusNodeId": { "type": "string" } } }
  }
]
```

**Both `canBeReferencedInPrompt: true` and `toolReferenceName` are required** — with either missing, the tool exists in `vscode.lm.tools` but agent mode never calls it.

Implementation shape (each tool body extracted into a pure, directly-invocable function so it can be smoke-tested with Copilot absent):

```ts
export class AnalyzeWorkspaceTool implements vscode.LanguageModelTool<{ path?: string }> {
  async prepareInvocation(o, _t) { return { invocationMessage: 'Analyzing ML workflow…' }; }
  async invoke(o, token) {
    const text = await runAnalyzeTool(o.input, token);       // exported; ≤4KB digest
    return new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(text)]);
  }
}
ctx.subscriptions.push(vscode.lm.registerTool('mlview_analyzeWorkspace', new AnalyzeWorkspaceTool(core)));
```

`mlview_showDiagram` has a side effect, so its `prepareInvocation` also returns `confirmationMessages: { title: 'Open MLView diagram?', message: … }`.

### Feature detection (mandatory)

```ts
if (typeof vscode.chat?.createChatParticipant === 'function') { try { registerChat(ctx); }
  catch (e) { log.warn(`chat participant not registered: ${e}`); } }
else log.info('chat API unavailable — participant not registered');

if (typeof vscode.lm?.registerTool === 'function') { try { registerLmTools(ctx); }
  catch (e) { log.warn(`LM tools not registered: ${e}`); } }
```

The diagram, diagnostics, reveal and CodeLens register **unconditionally**. A chat-API change can never break activation.

### Manifest essentials

`"engines": { "vscode": "^1.100.0" }` · `@types/vscode@1.100.0` · `typescript@5.9.3` · `esbuild@0.28.2` · `activationEvents: ["onLanguage:python", "workspaceContains:**/*.py"]` · `capabilities.untrustedWorkspaces: { "supported": "limited" }` (analysis is disabled in restricted mode, since it spawns an interpreter).

Commands: `mlview.visualize` · `mlview.visualizeWorkspace` · `mlview.refresh` · `mlview.showIssues` · `mlview.revealInDiagram` (`Alt+M`, `editor/context`) · `mlview.exportHtml` · `mlview.selectInterpreter` · `mlview.showOutput` · `mlview.showRuleDoc` · `mlview.debug.invokeTool` (dev only).

Settings: `mlview.pythonPath` · `mlview.analyzeOnSave` (true) · `mlview.exclude` · `mlview.maxFiles` (500) · `mlview.maxNodes` (400) · `mlview.minSeverity` (`low`) · `mlview.minConfidence` (0.6) · `mlview.showSpeculative` (false) · `mlview.diagnosticsEnabled` (true) · `mlview.diagnosticSeverity` (`warning` — high maps to Warning by default; `error` escalates) · `mlview.disabledRules` (`[]`) · `mlview.codeLens` (true) · `mlview.followCursor` (false) · `mlview.trace` (`off`).

### Diagnostics mapping (frozen)

| Issue severity | `mlview.diagnosticSeverity = "warning"` (default) | `= "error"` |
|---|---|---|
| high | `DiagnosticSeverity.Warning` | `Error` |
| medium | `Warning` | `Warning` |
| low | `Information` | `Information` |

`source: "MLView"` · `code: { value: "MLV201", target: Uri.joinPath(ctx.extensionUri, 'docs', 'rules', 'MLV201.md') }` (a **local** file, so rule docs work offline) · `relatedInformation` from `relatedLocs` · only `confidence >= mlview.minConfidence` and `suppressed === false` are published · per-file `set()`, with files dropping to zero issues explicitly cleared, and `clear()` on workspace-folder change.

---

## 7. Sample project fixtures

### 7.1 `samples/vision_pipeline/` — the demo (dirty)

Five files, ~230 lines of plausible PyTorch + scikit-learn that needs neither library installed to analyse. **Exactly 15 planted issues: 5 high, 6 medium, 4 low**, produced by 14 distinct rule codes (MLV602 fires twice). `expected_issues.json` is the machine-checked contract, and `e2e.ps1` asserts against it — if the sample is edited, that file is edited in the same commit.

| # | File | Planted defect | Code | Sev |
|---|---|---|---|---|
| 1 | `sklearn_baseline.py` | `StandardScaler().fit_transform(X)` on the full `X` **before** `train_test_split` | MLV101 | high |
| 2 | `train.py` | Batch loop with `loss.backward()` and `optimizer.step()` but no `optimizer.zero_grad()` | MLV201 | high |
| 3 | `train.py` | `validate()` runs the model with no `model.eval()` (the model has Dropout **and** BatchNorm) | MLV301 | high |
| 4 | `model.py` | `forward` returns `F.softmax(x, dim=1)` while `train.py` uses `nn.CrossEntropyLoss` | MLV401 | high |
| 5 | `model.py` | `self.blocks = [ConvBlock(...) for _ in range(4)]` — a plain list, not `nn.ModuleList` | MLV702 | high |
| 6 | `sklearn_baseline.py` | Bare estimator passed to `cross_val_score` after external scaling | MLV103 | medium |
| 7 | `data.py` | `DataLoader(train_ds, ...)` with no `shuffle=True` and no sampler | MLV110 | medium |
| 8 | `data.py` | `DataLoader(..., num_workers=4)` at module scope with no `__main__` guard | MLV112 | medium |
| 9 | `train.py` | `running_loss += loss` — no `.item()`, accumulator defined outside the loop | MLV205 | medium |
| 10 | `train.py` | `validate()` not wrapped in `torch.no_grad()` | MLV302 | medium |
| 11 | `train.py` | `model.to(device)` but batches are never moved | MLV501 | medium |
| 12 | `data.py` | `DataLoader(test_ds, shuffle=True)` | MLV111 | low |
| 13 | `config.py` | No seed anywhere in the workspace | MLV601 | low |
| 14 | `sklearn_baseline.py` | `train_test_split(...)` with no `random_state` | MLV602 | low |
| 15 | `data.py` | `random_split(ds, [45000, 5000])` with no `generator` | MLV602 | low |

Issues 2, 3 and 4 are the two absence rules plus a pairing rule reaching `high`: the sample deliberately contains **no framework wrapper** and both loops resolve with no dynamic constructs, which is exactly the precondition the severity cap requires — so the sample also demonstrates *why* the cap exists. `MLV102`, `MLV202`, `MLV203`, `MLV204`, `MLV402` and `MLV701` ship in the prototype but are exercised only by their own fixtures, not by the sample.

The demo therefore shows, on one screen: **all three marker shapes**; **two ghost nodes** (`zero_grad()` in the batch loop, `model.eval()` at the head of the eval loop); **one multi-location leakage connector** (MLV101, `fit_transform` → `train_test_split`); and **one edge-borne marker** (MLV401 on the `model → loss` edge).

### 7.2 `samples/vision_pipeline_clean/` — the trust beat

The *same five files*, same structure, same node/edge shape, every defect corrected. Expected: **0 high, 0 medium, 0 low**. Shown side by side in the demo, this is what earns belief that the findings mean something.

### 7.3 `tests/fixtures/rules/` — per-rule fixtures

For each of the 20 prototype codes, `<CODE>_bad.py` and `<CODE>_good.py`, 10–40 lines each, imports only. Bad fixtures are **self-describing**: `# MLVIEW-EXPECT: MLV201 line=18 confidence>=0.6`. Good fixtures encode the **nearest false-positive trap** from `ISSUE_RULES.md`, not merely correct code — e.g. `MLV201_good.py` contains a gradient-accumulation loop with `zero_grad` under `if step % 4 == 0`, and `MLV301_good.py` contains a Lightning `validation_step`.

### 7.4 `tests/clean/` — the clean-reference corpus (the precision gate)

Six idiomatic, **correct** programs written by hand, none of which may produce a high-severity finding:

| File | Exercises |
|---|---|
| `vanilla_torch.py` | The textbook loop: `zero_grad → forward → loss → backward → step`, `eval()` + `no_grad()` in validation, batches moved to device, seeded |
| `amp_accumulation.py` | `autocast` + `GradScaler` + gradient accumulation with `zero_grad` under a modulo guard — the classic MLV201 trap |
| `lightning_module.py` | A `LightningModule` with `training_step`/`validation_step` — exercises the `negation_absent` gate |
| `hf_trainer.py` | `TrainingArguments` + `Trainer` with `eval_dataset` and `compute_metrics` — gate again |
| `sklearn_pipeline.py` | `Pipeline` + `GridSearchCV` with `random_state` throughout — the correct answer to MLV101/MLV103 |
| `timeseries_split.py` | `TimeSeriesSplit`, chronological cut, no shuffling — the correct answer to MLV106 |

`test_precision.py` asserts **0 high and ≤ 2 medium** across all six.

### 7.5 Other fixtures

`fixtures/multifile/` (4 files, cross-file resolution) · `fixtures/dynamic/registry.py` (`getattr` factory → `unknown` nodes + `dynamic_scope`) · `fixtures/malformed/` (syntax error, empty, non-UTF-8, 3000-line generated) · `fixtures/notebooks/` (3 `.ipynb`) · `fixtures/frameworks/{keras,hf,lightning}_min.py` · `fixtures/synthetic/gen.py` (deterministic 300-node and 900-node generators for the perf and truncation tests).

---

## 8. Renderer API

`contracts/renderer_api.md`. The viewer bundle exposes exactly **one** global.

```ts
window.MLView.mount(root: HTMLElement, graph: MLGraph, bridge: HostBridge): MLViewApp

interface HostBridge {
  host: 'vscode' | 'standalone';
  theme: 'light' | 'dark' | 'hc';
  capabilities: { canOpenSource: boolean; canReanalyze: boolean;
                  canExport: boolean; canAskAssistant: boolean };
  post(msg: UiToHost): void;
  onMessage(cb: (msg: HostToUi) => void): () => void;   // returns an unsubscribe fn
  saveState(s: ViewState): void;
  loadState(): ViewState | null;
}

interface MLViewApp {
  update(graph: MLGraph, preserve?: Partial<ViewState>): void;
  focusNode(id: string, opts?: { center?: boolean; pulse?: boolean }): void;
  focusIssue(id: string): void;
  setFilters(f: Partial<Filters>): void;
  setTheme(kind: 'light' | 'dark' | 'hc'): void;
  getState(): ViewState;
  destroy(): void;
}
```

`VsCodeBridge` wraps `acquireVsCodeApi()` (called **once**), mapping `post` → `postMessage`, `saveState`/`loadState` → `setState`/`getState`. `StandaloneBridge` handles `openLocation` via a `vscode://file` navigation with a clipboard fallback, no-ops `requestRefresh` and `askAssistant`, and hides their buttons via `capabilities`.

**Build:**
```
npx esbuild src/main.ts --bundle --format=iife --global-name=MLView \
  --platform=browser --target=es2020 --minify --outfile=dist/mlview.js
```
Then `tools/sync-assets.py` copies `dist/mlview.js` and `dist/mlview.css` to `vscode-extension/media/` and `analyzer/src/mlview/emit/assets/`, and records the SHA-256 into `mlview/version.py:RENDERER_SHA`. `--check` exits non-zero on drift.

**Non-negotiable build rules:** no `innerHTML` anywhere (lint-enforced); no external font, image, script or stylesheet; no dynamic `import()`; no `eval`. `tests/bundle.test.ts` asserts all four.

---

## 9. Repository layout and directory ownership

| Directory | Owner | Contents |
|---|---|---|
| `contracts/` | **A1** (writes at T+0, then read-only for everyone) | schema, `graph.sample.json`, the six `.md` contracts |
| `analyzer/src/mlview/{__main__,cli,version,api}.py`, `ingest/`, `ir/`, `core/`, `emit/`, `knowledge/`, `schema/` | **A1** | The analyzer skeleton, IR, graph builder, CLI, emitters, `--demo` |
| `analyzer/src/mlview/rules/`, `analyzer/tests/rules/`, `analyzer/tests/fixtures/`, `analyzer/tests/clean/` | **A2** | The 20 prototype rules, confidence engine, suppression, all rule fixtures, the precision corpus |
| `analyzer/tests/core/`, `analyzer/tests/golden/` | **A1** | Pass-level unit tests, invariant tests, golden snapshots |
| `webview/` | **A3** | The viewer: layout, render, markers, states, tokens, interactions, a11y, its own tests, `dev/index.html`, `dev/states.html` |
| `vscode-extension/` | **A4** | The extension: commands, panel, diagnostics, interpreter chain, reveal, chat, LM tools, protocol, its tests |
| `claude-plugin/` | **A5** | `plugin.json`, `.mcp.json`, commands, skills, the MCP server, `vendor/` |
| `samples/`, `tools/`, `scripts/`, `.claude-plugin/marketplace.json`, `README.md` | **A5** | The dirty + clean samples, sync/verify/bench tooling, build/e2e/demo scripts, the marketplace manifest |
| `docs/` | shared, append-only | The five design documents; `docs/rules/MLVxxx.md` is generated by A2's registry |

**Rules of engagement.** No agent writes into another agent's directory. `tools/sync-assets.py` is the only thing that writes `vscode-extension/media/` and `analyzer/src/mlview/emit/assets/`. `tools/sync-core.py` is the only thing that writes `claude-plugin/vendor/`. `webview/dist/mlview.js` ships as a committed placeholder on day 0 so every build path works before any `npm install` completes. A contract change is requested from the lead, never made unilaterally.

### The three parity gates (run by `scripts/e2e.ps1`)

1. **One analyzer** — `tools/verify.py`: CLI graph vs MCP-`tools/call` graph, byte-identical after stripping `generatedAt` and `durationMs`.
2. **One renderer** — SHA-256 equal across `webview/dist/`, `vscode-extension/media/`, `analyzer/.../emit/assets/`, and equal to `generator.rendererSha` in every emitted document.
3. **One version** — `tools/sync-version.py --check`: `mlview.version.__version__` matches the extension `package.json`, the plugin `plugin.json`, and the viewer `package.json`.


---

## 10. Prototype amendments (lead decisions, 2026-09-06) — THESE OVERRIDE ANYTHING ABOVE

**A1 — MCP transport uses the official `mcp` Python SDK v2** (installed and verified: `mcp==2.1.1`). Pattern (verified in-process on this machine):

```python
try:
    from mcp.server.mcpserver import MCPServer          # mcp >= 2
except ImportError:                                      # mcp 1.x fallback
    from mcp.server.fastmcp import FastMCP as MCPServer
server = MCPServer("mlview", instructions="Static ML-workflow analysis. Call mlview_analyze first.")

@server.tool()
def mlview_analyze(path: str | None = None, framework: str = "auto", maxNodes: int = 400, includeHtml: bool = False) -> dict:
    """Analyze the Python ML code under `path` (default: the project dir) ..."""
    ...
    return digest_dict   # plain dict; the SDK serializes it as content text + structuredContent

if __name__ == "__main__":
    server.run("stdio")
```

The hand-rolled JSON-RPC server, the `--sdk` flag, and the `python -m mlview mcp` subcommand are **dropped**. The server entry is `claude-plugin/server/mlview_mcp.py`; before importing `mlview` it prepends `<plugin_root>/vendor` to `sys.path` and, as a dev fallback when that has no `mlview` package, `<repo>/analyzer/src`. Every tool returns a plain `dict` that is ≤ 4096 bytes when JSON-serialized (full detail lives on disk behind `graphPath`). Logging goes to stderr only. `.mcp.json` stays exactly as in §5. `tools/sync-core.py` copies `analyzer/src/mlview` → `claude-plugin/vendor/mlview` (excluding `__pycache__` and tests).

**A2 — `rendererSha` and asset sync.** The analyzer computes SHA-256 of `mlview/emit/assets/mlview.js` at runtime (cached per process) and emits it as `generator.rendererSha`; when the asset is absent it emits 64 zeros. `tools/sync-assets.py` only copies `webview/dist/mlview.js` and `webview/dist/mlview.css` into `vscode-extension/media/` and `analyzer/src/mlview/emit/assets/`; `--check` compares hashes and exits 1 on drift. `tools/sync-version.py` is dropped; `tools/verify.py --versions` checks that `mlview.version.__version__`, `analyzer/pyproject.toml`, `vscode-extension/package.json`, `claude-plugin/.claude-plugin/plugin.json` and `webview/package.json` all carry the same version (`0.1.0`).

**A3 — Renderer global (final shape).**

```ts
window.MLView = {
  version: string,
  mount(root: HTMLElement, graph: MLGraph, bridge: HostBridge): MLViewApp,
  bridges: {
    vscode(): HostBridge,                                                  // wraps acquireVsCodeApi() once
    standalone(opts?: { theme?: 'auto'|'light'|'dark'|'hc' }): HostBridge  // 'auto' = prefers-color-scheme
  }
}
```

The renderer sets `data-theme="light|dark|hc"` on the root element it mounts into; every design token is `var(--vscode-*, <literal>)` so the same CSS works in a webview and in a plain browser. `askAssistant` is posted by the bridge but ignored by both hosts in the prototype (its button is hidden via `capabilities.canAskAssistant=false`).

**A4 — Standalone HTML report** (`analyzer/src/mlview/emit/html_out.py`): one self-contained file: `<style>` with the inlined `assets/mlview.css`, `<div id="mlview-root">`, `<script id="mlview-graph" type="application/json">` holding the graph JSON with every `</` escaped as `<\/` (and `<!--` as `<\!--`), `<script>` with the inlined `assets/mlview.js`, then a 3-line bootstrap: `MLView.mount(document.getElementById('mlview-root'), JSON.parse(document.getElementById('mlview-graph').textContent), MLView.bridges.standalone({theme:'auto'}))`. If the assets are missing (pre-sync), the report still renders a plain-HTML fallback (a table of stages / nodes / issues) with a visible "viewer bundle not synced" banner. Size band: 100 KB – 2 MB when the bundle is present.

**A5 — VS Code webview bootstrap.** The panel HTML (nonce CSP from §4) loads `media/mlview.css` and `media/mlview.js` via `asWebviewUri`, then an inline nonce'd bootstrap script creates the bridge with `MLView.bridges.vscode()`, posts `ready`, and mounts on the first `graph` message (subsequent `graph` messages call `app.update`).

**A6 — Scope trims (do NOT build):** followCursor / `cursorHint`; `mlview.debug.invokeTool`; baseline; `tools/bench.py`; `scripts/demo.ps1`; notebook fixtures and the synthetic 300/900-node generators (a 150-node synthetic graph generated inside the viewer's own tests is enough for the perf assertion); the 3000-line malformed fixture; axe-core; the fuzzy command palette with prefix operators (a plain search box with case-insensitive substring match over node label / qualname / issue title / rule code is enough); the eight-state node machine is reduced to `default, hover, selected, dimmed, ghost, stale`; level-of-detail is one zoom-threshold class toggle (`data-lod="full|compact"`).

**A7 — Test scope (the acceptance gates actually run).**
- `analyzer/tests/core/`: symbols, bindings, scopes, stages, graph invariants (§1.1), determinism (two runs byte-equal after stripping `generatedAt`/`durationMs`), locations (`loc.symbol` occurs within `[line..endLine]`), id stability (insert 20 blank lines → ids unchanged, lines +20), schema (emitted doc validates with `jsonschema` against `contracts/graph.schema.json`; `python -m mlview schema` equals the contracts copy; `--demo` equals `contracts/graph.sample.json`), stdout purity, offline HTML (no `http://`, `https://`, `//cdn`, `@import`, external `<link>` / `<script src>`; size band), robustness (syntax error, empty file, non-UTF-8, no `.py` → exit 4), CLI exit codes and `--json -`.
- `analyzer/tests/rules/`: per-rule `<CODE>_bad.py` / `<CODE>_good.py` (self-describing `# MLVIEW-EXPECT:` headers), `test_no_cross_fire` (union of all good fixtures → 0 issues), `test_precision` (clean corpus: `vanilla_torch`, `amp_accumulation`, `lightning_module`, `hf_trainer`, `sklearn_pipeline` → 0 high, ≤ 2 medium), `test_registry_complete`, `test_suppression`, `test_confidence`, `test_samples` (dirty sample == `samples/vision_pipeline/expected_issues.json`; clean twin == 0/0/0).
- `webview/test/`: layout (deterministic; no sibling bbox overlap; every node inside its lane; < 300 ms for 150 nodes), bundle hygiene (no `innerHTML`, `eval(`, dynamic `import(`, `http://` / `https://` literals in `dist/mlview.js`), parity (sample through both bridges in jsdom → identical `data-node-id` / `data-edge-id` / `data-issue-id` sets), markers (the three severity SVG paths differ), contrast (each declared token fg/bg pair ≥ 4.5:1 for text in light and dark).
- `vscode-extension/test/`: `npx tsc --noEmit` clean; protocol round-trip + unknown-type tolerance; `loc → Range` conversion; workspace-containment guard; digest ≤ 4 KB; CSP builder; interpreter-resolution order; diagnostic severity mapping; `runAnalyzeTool` smoke with a stubbed core.
- `claude-plugin/tests/`: real subprocess handshake over stdio (initialize → initialized → tools/list → tools/call `mlview_analyze` on `samples/vision_pipeline`) asserting exactly the five tool names and a ≤ 4 KB result; digest budget on a 500-node synthetic graph; `claude plugin validate ./claude-plugin --strict` when the CLI is present.
- `scripts/e2e.ps1`: build all → sync assets → run every suite → analyze the sample to JSON + HTML → CLI-vs-MCP graph parity → bundle hash parity → version check.

**A8 — Rules ownership and count.** The core agent creates `rules/__init__.py`, `registry.py`, `context.py` (`GraphContext`), `confidence.py`, `suppress.py` and four seed rules (MLV201, MLV101, MLV401, MLV601) with their fixtures. The rules agent runs strictly after the core agent, adds the remaining sixteen from `ISSUE_RULES.md` §3, and may extend `context.py` and the IR as needed while keeping every existing test green. The prototype passes when ≥ 14 rules pass their fixtures, no-cross-fire holds, the precision corpus yields 0 high, and the dirty sample matches `expected_issues.json` exactly. A rule that cannot be made reliable is registered `enabled=False` with the reason in its doc page.

**A9 — Ghost nodes.** Declared by rules via `ctx.ghost(kind, parent_node, label)`; the graph builder appends them after rules run. `qualname = <parent.qualname>.__ghost_<slug>`, `loc` = the parent's `loc`, `ghost: true`, `issueIds` non-empty, `sublabel: "missing"`.

**A10 — Extension toolchain.** `engines.vscode ^1.100.0`, `@types/vscode 1.100.0`, `typescript 5.9.3`, `esbuild 0.28.2`, `@types/node 20.x` — exact pins in `package.json`. `npm run compile` bundles `src/extension.ts` → `out/extension.js` (cjs, platform node, `--external:vscode`); `npm run check` = `tsc --noEmit`; `npm test` = `node --test test/*.test.js` (pure functions with a mocked `vscode` module). Packaging with `vsce` is documented but not on the acceptance path.

**A11 — Stage bands.** Exactly the eight `StageId`s, in `order`, as horizontal swimlane bands stacked top-to-bottom, each laid out with `@dagrejs/dagre@3.1.1` (`rankdir: LR`) independently; `present: false` stages are not drawn as bands but listed in a "not detected" chip row. dagre compound / `setParent` is never used; groups (units with children) are laid out children-first and placed as sized meta-nodes.

**A12 — Sample ownership.** `samples/` (dirty + clean twin + `expected_issues.json`) is owned by the rules agent, not the hosts agent, because the planted issues must track real rule behaviour.

**A13 — Extension media placeholder.** Until `tools/sync-assets.py` runs, `vscode-extension/media/` contains only a `README.md`; the extension must tolerate a missing bundle by showing a "run scripts/build.ps1" message in the panel instead of throwing.

---

## 11. Feature amendments: flow animation and scoped views (2026-09-07)

**These are ADDITIVE and override §§1–9 where they conflict. §10 stays intact and still overrides §§1–9.**
Everything here is optional: `schemaVersion` stays `"1.0"`, no `required` array grows, no `additionalProperties`
opens, no existing field / message / argument / return shape changes, and an unscoped run emits bytes identical
to today's. Design rationale lives in `docs/FEATURES_FLOW_AND_SCOPE.md`; **this section binds**.

**Owners:** §11.1–11.6 and §11.15's Python gates — A1 (core). §11.8, §11.9, §11.13, §11.14 — A3 (viewer).
§11.7 and §11.11 — A4 (vscode). §11.10, §11.12 and the gate wiring — A5 (hosts).

---

### 11.1 The scope selector grammar (normative)

```
SPEC   := "all" | KIND ":" TARGET
KIND   := "unit" | "stage" | "file" | "concern" | "node" | "symbol"
DEPTH  := integer 0..2                       -- a separate parameter, never packed into SPEC
```

The selector is **one string with exactly one `kind` and one `target`**, split on the **first** `:` only
(a node id contains a colon: `node:n:55662bceebd0`). No comma-unions, no `@depth` suffix, no `~direction`,
no `+pin`. `depth` travels as its own parameter everywhere.

Parsing: trim; lowercase the `kind`; replace `\` with `/` inside a `file:` target; `symbol` **normalizes to
`unit`**; a `concern` alias normalizes to its canonical name **before validation**. The normalized string is what
`view.scope` reports, so two spellings of one scope produce byte-identical documents. An empty or missing spec
means `all` and performs no projection.

| kind | target | seed set | default depth | descendant closure? |
|---|---|---|---|---|
| `unit` | qualname, FQN, bare name, or a node id | tiered resolution (§11.2 step 1) | **1** | **yes** |
| `stage` | one of the eight `StageId`s | `node.stage == target` | **0** | no |
| `file` | workspace-relative path (forward slashes) or a bare basename | `loc.file == target`, else `basename(loc.file) == target` when the target has no `/` | **0** | no |
| `concern` | one of four presets, or an alias | `node.stage` ∈ the preset's stages | **0** | no |
| `node` | a node id (`n:…`) — **legacy pinpoint selector** | that node alone | **1** | **no** |

**Concern presets — FROZEN. The four partition all eight stages.**

| concern | stages | aliases |
|---|---|---|
| `config` | `config` | `setup` |
| `data` | `data`, `preprocess` | `preprocessing`, `dataset` |
| `optimization` | `model`, `objective`, `train` | `training` |
| `evaluation` | `eval`, `deliver` | `inference`, `eval` |

**Error codes.** Only the **code**, the offending **term**, and a **sorted, ≤10-entry candidate list** are
contractual. Message prose is free and may differ between Python and TypeScript.

| code | raised when |
|---|---|
| `bad_selector` | no `:`, or an unknown `kind` |
| `unknown_stage` | `stage:` target is not one of the eight `StageId`s (candidates: the eight) |
| `unknown_concern` | `concern:` target is not a preset or alias (candidates: the four canonical names) |
| `unknown_node` | `node:` target is not a node id in this graph |
| `unknown_file` | `file:` target matched no `loc.file` by either rule (candidates: distinct `loc.file` values) |
| `unknown_unit` | **not raised.** A `unit:` target that resolves to nothing is an *empty scope*, not an error (§11.2 step 9) |
| `bad_depth` | `depth` outside `0..2`, or not an integer |

---

### 11.2 Resolution and projection (normative)

Input: a finalized, schema-valid document `D`, a parsed `Scope(kind, target, depth)`.
Output: a finalized, schema-valid document `D'` carrying `view`.
**Pure**: no filesystem, no IR, no clock, no randomness, no set-iteration-order leak.

1. **Resolve anchors**, in **document order**.
   `stage` / `file` / `concern` / `node`: per the §11.1 table.
   `unit`: strip a trailing `()`; if the target starts with `n:` and names a node, that node alone; otherwise the
   **first non-empty tier** of, in order —
   (1) `qualname == t` · (2) `fqn == t` · (3) `lastSegment(qualname) == t` **and** `level ∈ {stage, unit}` ·
   (4) `lastSegment(qualname) == t` · (5) `label == t` or `label == t + "()"` —
   then tiers 1–5 again ASCII-case-insensitively, emitting a `config_warning` diagnostic naming the canonical
   spelling on a hit. `lastSegment(q)` is the substring after the final `.`, or `q` when there is none.
   **Every node in the winning tier is an anchor.** More than one ⇒ `view.ambiguous: true` plus a `config_warning`
   naming the disambiguating qualnames. Never a silent "best" pick.
2. **`core`** = the anchors, plus — for `kind == "unit"` only — their transitive **descendant** closure over
   `parent` (cycle-guarded).
3. **`boundary`** = BFS over `edges[]` in **both** directions, `depth` rings from `core`, minus `core`.
   Containment is **not** a hop.
4. **`context`** = for every node in `core ∪ boundary`, the transitive `parent` chain, minus anything already kept.
5. **`kept`** = `core ∪ boundary ∪ context`. **Edges** kept iff `source ∈ kept ∧ target ∈ kept`.
6. **Issues.** Retain issue `I` iff `∃ n ∈ I.nodeIds : n ∈ core` **or** `∃ e ∈ I.edgeIds` that is a kept edge with
   **both** endpoints in `core`. Then, for each retained `I`:
   `I.nodeIds ← [n for n in I.nodeIds if n ∈ kept]` (order preserved);
   if `I.nodeIds[0] ∉ core`, **stably rotate** the first core element to index 0, keeping the rest in relative
   order (`nodeIds[k:] + nodeIds[:k]`);
   `I.edgeIds ← [e for e in I.edgeIds if e is a kept edge]`.
   Suppressed issues follow the same rule and keep `suppressed: true`.
7. **Ghost pruning.** Drop every kept node with `ghost: true` whose `issueIds` contain no retained issue; then
   re-filter `edges` and every `I.nodeIds`, and drop any issue whose `nodeIds` became empty. Repeat once; it
   converges (a ghost is never a parent of a non-ghost).
8. **Nodes.** For each kept node, in document order: copy it, set `viewRole` to `core` / `boundary` / `context`,
   and filter `issueIds` to retained issues.
9. **Aggregates.** `stages[]` stays **all eight rows in `order`**. Per row: `nodeCount` = kept nodes of that
   `stage` in **all three roles**; `issueCounts` and `maxSeverity` recomputed over retained **non-suppressed**
   issues; **`present` copied verbatim from `D`**. `stats.nodes` / `stats.edges` = kept counts;
   `stats.issues` = retained non-suppressed counts; `stats.suppressed` = retained suppressed count;
   `stats.truncated` and `stats.durationMs` carried through.
   An anchor set of size 0 is legal: it yields all eight rows at `nodeCount: 0`, empty `nodes`/`edges`/`issues`,
   `view.empty: true`, `view.resolvedTo: []`, and a `config_warning` naming the whole-graph node count.
10. **Carried verbatim:** `schemaVersion`, `generator`, **every** field of `workspace`, and `diagnostics` (scope
    diagnostics appended, then the array re-sorted by its existing key). A projection **never restates
    project-level truth**.
11. **`view`** is appended as the **last key** of the document.

**11.2.1 The ordering invariant (normative, and the reason parity is affordable).**
Steps 1–10 only *remove* elements from arrays that are already canonically sorted (§0 Ordering), and only *filter*
the `nodeIds` / `edgeIds` / `issueIds` lists. **No output array is ever re-sorted.** `nodes`, `edges` and `issues`
in `D'` are therefore **subsequences** of the corresponding arrays in `D`, in the same relative order. The single
non-filter operation in the whole algorithm is the stable rotation in step 6. **A port that sorts anything is
wrong, even when its output happens to match.**

**11.2.2 `--max-nodes` runs BEFORE projection** and is not re-applied. Moving it after would make Python
(project→cap) and TypeScript (already-capped→project) disagree whenever the cap binds. When `stats.truncated` is
true and a scope was given, append `Diagnostic{kind: "truncated"}` saying the graph was capped before scoping;
`view.of.nodes` always reports the pre-projection count.

---

### 11.3 Schema additions — APPLIED to `contracts/graph.schema.json` and its mirror

Both copies are edited byte-identically (asserted by `analyzer/tests/core/test_schema.py`). `schemaVersion` stays
`"1.0"`. Three `$defs` were appended and two optional properties added; **no `required` array changed**.

Root `properties`, after `stats`:

```json
"view": { "$ref": "#/$defs/View" }
```

`$defs/Node.properties`, after `stageEvidence`:

```json
"viewRole": {
  "$ref": "#/$defs/ViewRole",
  "description": "Present only in a projected document (one carrying `view`). Absent means 'this document is not a projection'."
}
```

New `$defs`:

```json
"ViewRole": {
  "enum": ["core", "boundary", "context"],
  "description": "A node's role in a PROJECTION. 'core' is the scope itself and is the only role an issue may be retained through; 'boundary' was pulled in by `view.depth` edge hops and is drawn as a faded stub with no severity badge; 'context' is an ancestor kept so `parent` still forms a forest, drawn as an empty frame."
},
"ViewAnchor": {
  "type": "object",
  "additionalProperties": false,
  "description": "One node a scope selector resolved to.",
  "required": ["id", "qualname", "label", "file", "line"],
  "properties": {
    "id":       { "$ref": "#/$defs/NodeId" },
    "qualname": { "type": "string" },
    "label":    { "type": "string" },
    "file":     { "type": "string", "description": "Workspace-relative, forward slashes." },
    "line":     { "type": "integer", "minimum": 1 }
  }
},
"View": {
  "type": "object",
  "additionalProperties": false,
  "description": "Present ONLY when this document is a PROJECTION of a whole-workspace analysis (`--scope`). Its absence means the document describes the entire analyzed workspace. A projection never restates project-level truth: `workspace`, `generator`, `diagnostics` and every `stage.present` still describe the FULL analysis, while `stats`, `stage.nodeCount`, `stage.issueCounts` and `stage.maxSeverity` describe the projection. `view.of` carries the project-level totals so no surface can claim the project is smaller than it is.",
  "required": ["scope", "label", "depth", "counts", "of", "hidden", "resolvedTo"],
  "properties": {
    "scope":  { "type": "string" },
    "label":  { "type": "string" },
    "depth":  { "type": "integer", "minimum": 0, "maximum": 2 },
    "counts": { "type": "object", "additionalProperties": false,
                "required": ["core", "boundary", "context"],
                "properties": { "core": {"type":"integer","minimum":0},
                                "boundary": {"type":"integer","minimum":0},
                                "context": {"type":"integer","minimum":0} } },
    "of":     { "type": "object", "additionalProperties": false,
                "required": ["nodes", "edges", "issues"],
                "properties": { "nodes": {"type":"integer","minimum":0},
                                "edges": {"type":"integer","minimum":0},
                                "issues": {"$ref":"#/$defs/IssueCounts"} } },
    "hidden": { "type": "object", "additionalProperties": false,
                "required": ["nodes", "edges", "inboundEdges", "outboundEdges"],
                "properties": { "nodes": {"type":"integer","minimum":0},
                                "edges": {"type":"integer","minimum":0},
                                "inboundEdges": {"type":"integer","minimum":0},
                                "outboundEdges": {"type":"integer","minimum":0} } },
    "resolvedTo": { "type": "array", "items": { "$ref": "#/$defs/ViewAnchor" } },
    "ambiguous":  { "type": "boolean" },
    "empty":      { "type": "boolean" }
  }
}
```

`counts.core + counts.boundary + counts.context == stats.nodes`.
`hidden.inboundEdges` / `outboundEdges` count edges of `D` with **exactly one** endpoint kept — what enters and
leaves the scope. `view.of` is always taken from the **unprojected** document.

**`view` is emitted only by a real projection.** An unscoped `analyze` MUST NOT emit the key — that is what keeps
`--demo` byte-identical to the golden, `tools/verify.py --parity` green, and `test_determinism` stable.

---

### 11.4 Invariants — one addition and two conditional relaxations

**§1.1 gains invariant 9:** *A document carrying `view` is a PROJECTION. Its `nodes`, `edges` and `issues` are
subsequences of the unprojected document's arrays in the same relative order; every kept node carries `viewRole`;
`counts.core + counts.boundary + counts.context == stats.nodes`; `stage.present` and every field of `workspace`
and `generator` still describe the FULL analysis; and invariants 1–8 still hold.*

Carrying `present` through is required (the confirmed MLV-R2-103 defect, `claude-plugin/server/mlview_views.py:11-17`
and `:88-96`), and it breaks two consumers that assume otherwise. **Both fixes are mandatory and land in this
change:**

| # | Site | Change |
|---|---|---|
| **F1** | `contracts/validate_sample.py:300-301` — `elif not nodes and not any(counts.values()): "stage %s is present but has neither nodes nor issues"` | Guard the branch with `and doc.get("view") is None`. **Verified failing today:** a real `concern:evaluation` projection reports `stage config is present but has neither nodes nor issues` and `stage objective …`, so every scoped document currently fails the contract validator. |
| **F2** | `analyzer/tests/core/test_graph_invariants.py:151` — `assert stage["present"] == bool(stage["nodeCount"] or any(...))` | Assert the equality only when `"view" not in doc`. For a projection, assert instead: `stage["present"] == unprojected_stage["present"]` and `stage["nodeCount"] == len([n for n in doc["nodes"] if n["stage"] == stage["id"]])`. |
| **F3** | `webview/src/layout/model.ts:87` — `if (s.present \|\| (this.rootsByLane.get(s.id) \|\| []).length > 0) this.lanes.push(s)` | While `graph.view` is present, admit a lane **only** when it has drawn roots. Expose the excluded-but-present stages so `ui/chrome.ts` can render them in a **"not in this scope"** chip row beside the existing "not detected" row (`chrome.ts:236-241`). Without this, `concern:evaluation` draws two empty swimlane bands on the sample and up to seven on a narrow scope. |

---

### 11.5 CLI additions and exit behaviour

On **`analyze`**, **`issues`** and **`render`** (all optional; the defaults reproduce today's behaviour exactly):

| Flag | Default | Meaning |
|---|---|---|
| `--scope <SPEC>` | none (`all`) | Project the built graph before emitting. Not repeatable. Applies to `--json`, `--html` and every `--format`. |
| `--depth <N>` | per-kind (§11.1) | Boundary hops, `0..2`. An explicit value overrides the per-kind default. |

On **`analyze`** only:

| Flag | Default | Meaning |
|---|---|---|
| `--list-scopes` | off | Print the scopable-unit catalogue (`spec`, `label`, `file:line`, `nodeCount`, `issueCounts`) to **stdout** as the requested payload — text, or JSON with `--format json` — then exit 0. Mutually exclusive with `--json`, `--html` and `--scope`. |

`render --graph FILE --scope <SPEC>` applies the projection to an **already-written** document, so a scope can be
taken without re-analysing.

**Exit codes — the §3 table is unchanged; no new code is added.**

| Situation | Exit | stdout | stderr |
|---|---|---|---|
| Valid selector, non-empty result | `0` | the payload | — |
| Valid selector, **empty** result | `0` | the payload (a valid zero-node document carrying `view.empty: true`) | one note naming the selector and the whole-graph size |
| Invalid selector / bad depth (§11.1 codes) | `1` | **nothing** | `code`, the offending term, and ≤10 sorted candidates |
| `--scope` together with `--demo` | `1` | nothing | `bad_selector`: the golden is a fixed artefact |
| `--fail-on` threshold met among the **retained** issues | `2` | the payload | the threshold line, **which also names the active scope** so a narrowed CI gate is visible in the log |

**Emitters.** An **unscoped** run's output is byte-identical to today's. A scoped run adds exactly **one line**
per non-HTML format and nothing else:

- `--format summary` / `--format text`: `scope: <spec> · depth <n> · <inScope> of <total> nodes`
- `--format mermaid`: a leading `%% scope: <spec> — <inScope> of <total> nodes` comment (the `%%` form is already
  used at `mlview_views.py:57`). **No `classDef mlvBoundary`, no role-marker column** — cut.
- `--json` / `--html`: the projected document verbatim, except that `--html` embeds the **full** graph (§11.8).

---

### 11.6 `mlview.api` additions (`analyzer/src/mlview/api.py`) — additive

```python
CONCERNS: dict[str, tuple[str, ...]]          # the frozen preset table of section 11.1
CONCERN_ALIASES: dict[str, str]
SCOPE_KINDS: tuple[str, ...] = ("unit", "stage", "file", "concern", "node")

class ScopeError(ValueError):
    code: str                 # one of the section 11.1 codes
    term: str
    candidates: tuple[str, ...]   # sorted, at most 10

@dataclass(frozen=True)
class Scope:
    kind: str
    target: str
    depth: int
    spec: str                 # the normalized "<kind>:<target>" string

def parse_scope(spec: str, depth: int | None = None) -> Scope: ...     # raises ScopeError
def resolve_scope(graph: dict, scope: Scope) -> ScopeResolution: ...   # anchors + core, no projection
def project(graph: dict, scope: Scope) -> dict: ...                    # pure dict -> dict
def scope_catalog(graph: dict, limit: int = 40) -> list[dict]: ...     # backs --list-scopes and scope="units"
```

`AnalyzeOptions` gains **two fields, appended last, both defaulted**, so positional construction, `frozen=True`
and hashability are unchanged:

```python
    scope: Optional[str] = None
    depth: Optional[int] = None
```

`analyze(options) -> MLGraph` still returns the **full** graph — a scope is a document-level projection, and its
docstring says so. `analyze_to_dict(options)` applies `project()` when `options.scope` is set.
`render_html(graph, out_path, scope: str | None = None, depth: int | None = None)` gains two defaulted
parameters. `digest(graph)` gains an optional `"scope"` block
`{spec, kind, target, depth, nodesInScope, nodesTotal}` (~110 bytes) copied from `graph["view"]` when present; the
existing shedding loop protects the 4 KB budget.

The implementation lives in a new **`analyzer/src/mlview/core/project.py`** — *not* `core/scope.py`, which would
collide with the existing `mlview/ir/scopes.py` where "scope" already means lexical scope. It imports nothing from
`build.py` or `pipeline.py`.

---

### 11.7 Message protocol additions (§4 amended; both sides still ignore unknown types)

```ts
// Host → webview
| { v: 1; type: 'setScope'; spec: string | null; depth?: number }

// Webview → host
| { v: 1; type: 'scopeChanged'; spec: string | null; label: string;
    nodes: number; of: number }
```

The selector field is named **`spec`**, not `scope`: `analysisStarted` and `requestRefresh` already carry a field
literally named `scope` with values `'workspace' | 'file'`, and reusing the word would be a live collision.

`spec: null` clears the scope. `scopeChanged` is posted on **every** scope change including a clear (then
`spec: null`, `label: "Everything"`, `nodes === of`). The host uses it for the panel title and description; it must
**never** trigger a re-analysis. A viewer predating this falls through to `onUnknown` (`webview/src/protocol.ts:65`);
a host predating it drops `scopeChanged` silently.

---

### 11.8 Renderer API additions (§8 and §10 A3/A4 — **NOT amended, deliberately**)

`window.MLView.mount(root, graph, bridge)` **keeps its exact three-argument signature**, and A4's three-line report
bootstrap string is **unchanged**. The initial scope arrives as two optional attributes on the root element the
report already emits, which `mount()` reads from `root` itself:

```html
<div id="mlview-root" data-mlview-scope="concern:evaluation" data-mlview-depth="1"></div>
```

Absent attributes mean no scope. This keeps A3 and A4 frozen, leaves `vscode-extension/src/panel.ts`'s two `mount`
call sites untouched, and — because the report embeds the **full** graph and lets the viewer project it — keeps
`view` meaning exactly one thing: *this document is the projection*.

`MLViewApp` gains two methods (additive to an interface hosts only consume):

```ts
setScope(spec: string | null, opts?: { depth?: number }): void;
getScope(): { spec: string | null; label: string; depth: number; nodes: number; of: number };
```

`setScope` re-projects and relayouts locally. **It never posts `requestRefresh` and never touches the analyzer.**
An unresolvable spec is a no-op plus a toast; it never throws out of `mount` or `setScope`.

`window.MLView.__internal` (already the documented test surface) gains
`scope = { parseScope, resolveScope, project }` so the parity gate can call the algorithm without a DOM.

**`--html` with `--scope` embeds the FULL graph** and sets the two attributes. `render_html` therefore projects
nothing; the viewer does. This is what makes the standalone report and the webview run the identical code path,
and it is where the parity guarantee comes from for free.

---

### 11.9 `ViewState` additions (`webview/src/types.ts`)

```ts
export interface ViewState {
  // ... unchanged ...
  minimapCollapsed?: boolean;
  /** Optional: the active scope, as one canonical selector string. Absent = whole workspace. */
  scope?: { spec: string; depth: number };
  /** Optional: flow animation on/off, like `minimapCollapsed`. Absent = on. */
  flow?: boolean;
}
```

Both optional, both sanitized on restore by a new `sanitizeScope` beside `sanitizeFilters`
(`webview/src/protocol.ts:70-79`). `applyState` already tolerates missing keys, so an older saved state restores to
the defaults (no scope, flow on). A host predating this round-trips both fields untouched.

On a new `graph` message the saved scope is **re-resolved** against the new document; if it now matches nothing it
is dropped with a toast (`"Scope no longer matches — cleared"`).

---

### 11.10 MCP additions (§5 amended) — **still exactly five tools**

`TOOL_NAMES` (`claude-plugin/server/mlview_mcp.py:404-407`) is unchanged, and
`claude-plugin/tests/test_mcp.py`'s exactly-five-names assertion stays green.

| Tool | Addition |
|---|---|
| `mlview_graph` | `scope` accepts the full §11.1 grammar on top of today's `"stages"` / `"stage:<id>"` / `"node:<id>"`, plus one new catalogue value **`"units"`**. `depth` keeps its meaning and is now bounded `0..2`. |
| `mlview_analyze` | `scope?: string`, `depth?: integer` |
| `mlview_issues` | `scope?: string`, `depth?: integer` |
| `mlview_open_diagram` | `scope?: string`, `depth?: integer` — the written report embeds the full graph and opens **at** that scope (§11.8) |
| `mlview_explain` | unchanged |

**`scope: "units"`** returns one row per scopable unit — every node with children, or `level ∈ {stage, unit}` —
as `{nodeId, label, qualname, file, line, nodeCount, maxSeverity}`, rendered as text / json / mermaid, sorted
`(-nodeCount, file, line, qualname)`, and shed to fit the existing 4 KB budget. This is discovery **without a sixth
tool**. `"stages"` stays a non-projecting summary.

`mlview_graph`'s docstring promises an error naming the accepted values (`mlview_mcp.py:290-292`); it is extended
in the **same** edit as the grammar, or a documented contract becomes a lie the model acts on. Errors surface
through the existing `ValueError` path carrying the §11.1 code, term and candidates.

Every scoped result keeps the existing filtered-view `note` (`mlview_payloads.py:295-303`) and adds
`"scope": "<normalized spec>"`.

**The analysis cache is never keyed on scope.** `load_graph` (`mlview_workspace.py:182`) keeps caching on
`(resolved, framework, maxNodes, signature)`; `project()` is applied to the cached dict; `graphPath` keeps pointing
at the **full** document, so a model can always widen for free.

`claude-plugin/server/mlview_views.py` keeps `subgraph`, `stage_scope_ids` and `neighbourhood_ids` as **thin
delegating wrappers** over `mlview.core.project` — wrapped, not deleted — so no other caller moves.
`tools/sync-core.py` copies the whole package, so `core/project.py` reaches `vendor/` with no change.

---

### 11.11 VS Code contributions (`vscode-extension/package.json`)

**Two commands**, both `"category": "MLView"` (asserted by `test/manifest.test.js`):

| id | title | icon | menus / keybinding |
|---|---|---|---|
| `mlview.scopeToSymbol` | `MLView: Scope Diagram to Symbol` | `$(list-tree)` | `editor/context` group `mlview@3`; keybinding `alt+shift+m` when `editorTextFocus && editorLangId == python`; command palette |
| `mlview.clearScope` | `MLView: Clear Diagram Scope` | `$(clear-all)` | command palette |

`scopeToSymbol` resolves the cursor to the **enclosing unit**: `findNodeAtLine`
(`vscode-extension/src/locationIndex.ts:97-135`, which already picks the narrowest containing node), then climb
`parent` to the narrowest ancestor with `level ∈ {unit, stage}`, then post
`{type:'setScope', spec: 'unit:' + qualname}`. When nothing contains the cursor, show the "no node here" toast the
reveal path already uses; do **not** guess.

Both bodies live in a new `vscode-extension/src/scopeCommands.ts` (mirroring `revealInDiagram.ts:29-76`), so
`panel.ts` grows only `postSetScope` and an `onScopeChanged` handler that sets
`panel.title = spec ? 'MLView — ' + label : PANEL_TITLE` (`panel.ts:30`, `:205`) and
`panel.description = nodes + ' of ' + of + ' nodes'`.

**Settings: none added.** The flow preference is renderer-owned via `ViewState.flow`; a `mlview.flowAnimation`
setting would put a field in `Capabilities` for something the webview owns, and the standalone report has no host
to read it from. `mlview.defaultScope` is cut.

**`vscode-extension/src/diagnostics.ts` MUST have no diff in this change.** A scope never changes the Problems
panel, the status-bar count, or the issue quick pick. `chat.ts` and `lmTools.ts` are likewise untouched:
prose-to-scope resolution and a `scope` input on the three language-model tools are cut for v1.

---

### 11.12 Plugin command argument grammar

`claude-plugin/commands/mlview.md` frontmatter:

```
argument-hint: "[path] [--scope <SPEC>] [--depth <0-2>]"
```

Grammar: `$1` is the path (default: the project dir). `--scope` takes one §11.1 selector; `--depth` takes
`0`, `1` or `2`. Both optional, order-free, and each may appear at most once. Anything else is passed through
unchanged.

Step 1 of the body passes `scope` and `depth` to `mlview_analyze` and `mlview_open_diagram`. The Bash fallback
becomes:

```
python -m mlview analyze "$1" --scope "<SPEC>" --json .mlview/graph.json --html .mlview/report.html --open --format summary
```

with the `--scope` fragment omitted entirely when no scope was given, so the unscoped fallback is unchanged.
Step 2's existing warning — that only `scope:"stages"` is a project-level statement — is extended to every new
kind. `claude-plugin/commands/mlview-issues.md` gains the same two arguments.

`claude-plugin/skills/mlview-visualize/SKILL.md` gains a **"When to scope"** section instructing the model to call
`mlview_graph {scope:"units"}` when the user names a part of the pipeline, to scope a question about one concern,
and — explicitly — **not** to scope a request to review the project.

---

### 11.13 Flow rendering contract (DOM, classes and attributes)

A renderer-local contract: **no schema change, no protocol change, no host change.** Feature 1 consumes only
`edges[].kind`, `subkind`, `source`, `target`, `label` and `issueIds`, all of which already exist.

**Two observable attributes on `.mlv-canvas`**, each with one job, so every branch is assertable in a runner that
executes no CSS animations:

| Attribute | Values | Source |
|---|---|---|
| `data-motion` | `full` \| `reduced` | `matchMedia('(prefers-reduced-motion: reduce)')`, re-read on its `change` event |
| `data-flow` | `motion` \| `static` \| `off` | `off` when the user toggled it off; `static` when `data-motion="reduced"` **or** the current trace exceeds `FLOW_MAX_EDGES`; `motion` otherwise |

**Elements**, created lazily inside the existing 400 ms hover callback and destroyed by the next `render()`:

| Class | Element | Position | Built when |
|---|---|---|---|
| `mlv-edge__flow` | `<path pathLength="100">`, `d` **equal to** `.mlv-edge__path`'s `d` | the route | `data-flow="motion"` only |
| `mlv-edge__port mlv-edge__port--out` | `<circle r="3.5">` | `route.points[0]` | `motion` or `static` |
| `mlv-edge__port mlv-edge__port--in` | `<circle r="3.5">` | `route.points[points.length - 1]` | `motion` or `static` |
| `mlv-edge__dir` | `<path>` rotated by `route.midAngle` | `route.mid` | `data-flow="static"` only |

**State classes:** `.is-flowing--pulse` (one charge, single edge) and `.is-flowing` (stream, lineage) on the edge
`<g>`; `.is-flow-source` / `.is-flow-target` on the two endpoint cards; `--mlv-flow-delay` inline per streaming
edge; `--mlv-flow-dur` and `--mlv-flow-len` inline per pulsing edge.

**Constants:** `FLOW_MAX_EDGES = 120`; pulse speed `320 px/s` clamped to `[380, 2200] ms`; stream speed
`220 px/s`; head `12 px`; gaps `34 / 96 / 24 px` for data / call+control:enter / control:back giving periods
`210 / 490 / 165 ms`; hop delay `90 ms` capped at 6 hops. Exported through `__internal` so tests do not hard-code
timings.

**Mandatory rules:**

1. **Length is the polyline length summed from `RoutedEdge.points`. `getTotalLength()` MUST NOT be called** —
   jsdom does not implement it, so measuring the DOM would make the tested path different from the shipped path.
   A source scan of `webview/src` asserts zero occurrences.
2. **Direction is never derived.** Every router already emits `points` source→target (`routing.ts:241-262`);
   animating along `d` is always outlet→inlet. No per-edge direction decision may be reintroduced.
3. **Reduced motion is handled twice:** the element is never built when `data-motion="reduced"`, **and**
   `@media (prefers-reduced-motion: reduce) { .mlv-edge__flow { display: none !important } }` exists in the
   stylesheet. The blanket clamp at `webview/src/styles/base.css:207-213` *freezes* an animation rather than
   removing it, which would park a 12 px stub at every outlet.
4. **Charge colour is order-independent:**
   `.mlv-edge[data-stage]:not(.has-issue) { --mlv-flow-color: var(--mlv-stage) }` and
   `.mlv-edge.has-issue { --mlv-flow-color: var(--mlv-sev) }`. `data-stage` on the edge `<g>` comes from the
   **source** node's stage.
5. **No `will-change`, no `filter: drop-shadow`, no halo, and nothing may animate without a user action.**
6. `config`-kind edges never join a lineage stream; they pulse only on direct hover or selection.
7. Nothing in the flow layer carries a `data-*-id`, so `webview/test/parity.test.mjs` is unaffected by
   construction.

**`ViewState.flow`** persists the toolbar toggle (§11.9). The `Escape` dismiss cascade is, in this exact order:
**shortcut sheet → focus mode → scope → selection → blur**; one owner writes that order once, in
`webview/src/app.ts:505-510`. New `KEYMAP` rows: `e` and `Shift+E` (cycle the selection's connections) — and
because `handleCanvasKey` folds case for `f`/`F` and `p`/`P` (`keymap.ts:100, :120`), the pair **must** branch on
`ev.shiftKey` explicitly. `s` and `Shift+S` (scope to selection / clear) and `[` / `]` (step depth) are the scope
lane's rows. `e`, `s`, `[`, `]` are all unbound today (`keymap.ts:58-141`), and none collides with the `Shift+F`
and `Ctrl+Shift+E` that `UX_DESIGN.md` §9 reserves.

---

### 11.13.1 Charge representation (2026-09-08) — amends 11.13, renderer-local

**Why.** 11.13 shipped the single-cable charge as a moving **dash segment**: a 12 px head sliding along
`stroke-dashoffset` on a 3 px stroke, inside a diagram made of 3 px strokes. What that reads as is a *brighter
piece of cable*, not a thing travelling *through* one — the electron the feature is named after never appeared.
A charge on a hovered or selected connection is therefore a **travelling dot with a halo**. No schema change, no
protocol change, no host change; `webview/**` and this section only.

**Scope of the amendment.** It applies to the **pulse** — `.is-flowing--pulse`, i.e. direct edge hover, edge
focus and the selection latch. The **lineage stream** (`.is-flowing`) keeps the hop-staggered dash train of
11.13 unchanged: on a stream the reading is *density per hop*, which a dash pattern states in one glance and
thirty independent dots do not, and a stream may decorate up to `FLOW_MAX_EDGES` cables at once, where one SMIL
timeline per edge is a cost the dash pattern does not pay.

**Elements** — added to the 11.13 table, built only under `data-flow="motion"` and only for a pulse:

| Class | Element | Built when |
|---|---|---|
| `mlv-edge__charge` | `<g>` holding the three circles below plus one `<animateMotion>` | pulse, `motion`, route length > 0 |
| `mlv-edge__charge-halo` | `<circle cx="0" cy="0" r="9">`, `--mlv-flow-color` at `--mlv-flow-halo-opacity` (0.18) | inside the group |
| `mlv-edge__charge-glow` | `<circle cx="0" cy="0" r="5.5">`, `--mlv-flow-color` at `--mlv-flow-glow-opacity` (0.42) | inside the group |
| `mlv-edge__charge-core` | `<circle cx="0" cy="0" r="2.6">`, `fill: var(--mlv-surface)`, `stroke: var(--mlv-flow-color)` at `--mlv-flow-core-width` | inside the group |

**Motion.** `<animateMotion dur="<pulseDurationMs(polylineLength(route.points))>ms" repeatCount="indefinite"
calcMode="linear" rotate="auto" fill="remove">` containing `<mpath>` that references the edge's **visible**
`.mlv-edge__path`. Both `href` and `xlink:href` are set, the latter **in the XLink namespace** (`setAttributeNS`;
a plain `setAttribute("xlink:href", …)` lands in no namespace and SVG 1.1 renderers ignore it).

**Path identity.** Every `.mlv-edge__path` carries `id="mlv-p-<mount serial>-<edge id, each UTF-16 code unit as
four hex digits>"`. The serial is allocated once per mounted `CanvasView` (`nextMountSerial()` in
`webview/src/render/edges.ts`) because `<mpath href="#…">` is a **document-wide** reference and `dev/states.html`
mounts several apps on one page. The fixed-width hex is injective by construction, so no two edge ids can alias.

**Mandatory rules** (these are additive to 11.13's rules 1–7, all of which still hold):

1. **Two dots on a long cable.** A route longer than `CHARGE_TWIN_PX = 360 px` gets a second `mlv-edge__charge`
   with `begin="-<round(dur/2)>ms"`. The begin is **negative**: that is a phase offset, so the trailing dot is
   half a period behind from the first frame rather than appearing half a second into the hover.
2. **The halo is stacked opacity, never a filter.** No `feGaussianBlur`, `feDropShadow`, `feColorMatrix`,
   `filter:` or `will-change:` anywhere in the flow layer — a filter region on a moving element is
   re-rasterized every frame, which is exactly the cost 11.13 rule 5 and `flow.css`'s header rule out. The
   built bundle is grepped for the primitive names.
3. **`mlv-edge__flow` survives, demoted.** In a pulse it is no longer the moving part: it stays as a **static,
   faint, full-length underlay** (`stroke-dasharray: none`, `stroke-opacity: var(--mlv-flow-underlay-opacity)`,
   no `animation`). It is what carries `--mlv-flow-color` along the *whole* cable, so a severity edge — the
   sample's `softmax` → `CrossEntropyLoss` — still reads red between passes and not only under the dot. The
   `@keyframes mlv-flow-pulse` block of 11.13 is **deleted**; `mlv-flow-stream` is untouched and remains the
   only keyframe animating `stroke-dashoffset`, still with no `calc()` on the animated side.
4. **Colour is unchanged.** 11.13 rule 4 governs the dot exactly as it governed the dash: stage hue on
   `[data-stage]:not(.has-issue)`, severity on `.has-issue`, ink in high contrast through the element-level
   override in `flow.css`.
5. **Reduced motion, and the zero-length route.** No charge group is built when `data-motion="reduced"`, and
   `@media (prefers-reduced-motion: reduce) { .mlv-edge__charge { display: none !important } }` exists in the
   stylesheet as its own rule. This is **not** belt-and-braces: SMIL is not CSS, so the blanket
   `animation-duration: 0.01ms` clamp in `base.css` does not touch `<animateMotion>` at all. A route whose
   polyline length is 0, or whose visible path carries no id, builds **nothing** — `<mpath>` may never point at
   something that is not there.
6. **`stripEdge` removes `.mlv-edge__charge`** with the rest of the set, so unhover, selection change, scope
   change (11.14 C1), the flow toggle and `destroy()` all leave zero charge groups and zero SMIL timelines in
   the document.

**Constants** (`FLOW`, exported through `__internal.flow`): `CHARGE_HALO_R = 9`, `CHARGE_GLOW_R = 5.5`,
`CHARGE_CORE_R = 2.6`, `CHARGE_TWIN_PX = 360`. Duration still comes from `pulseDurationMs` — 320 px/s clamped to
`[380, 2200] ms` — so 11.13's constant-apparent-speed promise is unchanged. New tokens in `tokens.css`:
`--mlv-flow-halo-opacity`, `--mlv-flow-glow-opacity`, `--mlv-flow-core-width`, `--mlv-flow-underlay-opacity`;
none of them is a colour, so the charge follows the existing colour rules for free.

**Gates:** `webview/test/charge.test.mjs` (F1-A12 … F1-A16) plus the amended keyframe gate in
`webview/test/flow.test.mjs`.

---

### 11.13.2 Charge legibility (2026-09-08) — amends 11.13.1, renderer-local

Three findings against the dot of 11.13.1, all measured in Chromium against the shipped report, plus one
correction to a promise 11.13.1 repeated. Additive to 11.13's rules 1–7 and 11.13.1's rules 1–6, all of which
still hold.

7. **The charge begins at the GESTURE.** Every `<animateMotion>` a pulse builds carries an ABSOLUTE `begin`,
   `begin="<t0>s"`, where `t0` is `ownerSVGElement.getCurrentTime()` read ONCE per pulse and shared by both
   dots; the twin's is `t0 - dur/2` s, still a phase offset and still half a period ahead from its first frame.
   A `begin` that is absent resolves to `0s` **on the SVG document timeline** — a clock that started with the
   page and is never stopped — so a dot created inside a hover callback started at phase
   `(uptime mod dur) / dur`: over twelve hovers of one 1269 ms cable the first painted position was scattered
   uniformly across the route (0.05 … 0.99) and never near the outlet, so roughly one hover in four spent its
   whole visible life beside the INLET. Where the renderer exposes no SMIL clock (jsdom, and any host without
   `getCurrentTime`) the pre-amendment form is written instead — no `begin` on the lead dot, `-<dur/2>ms` on the
   twin — through a `typeof` guard, so the fallback is the old behaviour and never a thrown build.
8. **The charge fades at both ends of its cycle.** `@keyframes mlv-charge-ends` in `flow.css` takes
   `.mlv-edge__charge` from `opacity: 0` to 1 over the first 8% of the cycle and back over the last 8%, driven
   by the same `--mlv-flow-dur` the motion carries. `repeatCount="indefinite"` wraps instantaneously, so
   without it the charge did not ARRIVE anywhere: it blinked out at the inlet and in at the outlet one frame
   later at full strength — a ~190 px jump on a short cable, ~640 px on a long one, once per cycle for as long
   as the pointer rested. The trailing dot carries `class="mlv-edge__charge mlv-edge__charge--twin"` and an
   `animation-delay` of `calc(var(--mlv-flow-dur) / -2)`, so its fade stays in phase with its `begin` instead
   of dimming mid-cable. It is `opacity` on an element the compositor already moves: no filter primitive, no
   `will-change`, and 11.13.1 rule 5 is untouched — under `prefers-reduced-motion` the charge is still removed
   outright rather than faded.
9. **High contrast rings the dot in ink.** The hc block forces `--mlv-flow-color: var(--mlv-text)`, which made
   the halo the same white as the cable it rides — a soft ring carrying no information, in the one theme where
   "a dot with some hue around it" cannot be delivered with hue. In hc (`body.vscode-high-contrast`,
   `body.vscode-high-contrast-light`, `[data-theme="hc"]`) the halo is therefore `fill: none` with
   `stroke: var(--mlv-text)` at 1.2 px: an outline circle at `r 9` around the bead, geometry rather than
   colour, legible on both hc grounds. The base rule is unchanged and the override wins on SPECIFICITY, not
   source order, exactly as the `--mlv-flow-color` override above it does.

**A mid-session motion flip REBUILDS what was running.** `FlowController.setMotion` only clears, so
`FlowBinding`'s `MotionWatcher` callback ends with `stop()` — the same line `setEnabled` got for R2-FLOW-08.
Without it a flip to `reduce` stripped a SELECTED or keyboard-FOCUSED connection of its charge *and* of the
ports and chevron that are supposed to replace it, leaving a connection visibly emphasised, holding DOM focus,
with no direction cue at all — the state MLV-R1-FLOW-011 declares cannot exist — and handed it to the one reader
with no animation to fall back on; flipping back restored nothing either. The remembered capped-trace node id is
dropped with it, because `cappedTraceMessage` says something different to each audience.

**Correction to the constants.** 11.13.1 said the duration's move to the dot left "11.13's
constant-apparent-speed promise unchanged". The promise holds for a lineage STREAM, whose period is a constant
per kind. It does not hold for a PULSE at either clamp, and in the shipped sample both bind: a 72 px call edge
is stretched from 225 ms to `PULSE_MIN_MS = 380` (0.59x of 320 px/s) and a 2128 px data edge compressed from
6650 ms to `PULSE_MAX_MS = 2200` (3.02x), a 5.1x spread between two cables hovered with the same gesture. The
constants are unchanged here — they are pinned in three docs and in F1-A3 — but `pulseDurationMs` now documents
the clamp rather than the intent, and widening it is a contract amendment, not a renderer-local change.

**Gates:** `webview/test/charge.test.mjs` (R3-CHG-01, R3-CHG-03, R3-CHG-05) and `webview/test/flow.test.mjs`
(R3-CHG-02, with a `matchMedia` stub whose listeners actually fire).

---

### 11.14 Flow × scope composition (normative)

| # | Rule |
|---|---|
| **C1** | A scope change **clears every flow element and every `--mlv-flow-*` inline property** before rebuilding the scene, and resets the remembered flowing-edge and endpoint ids. `clearFlow` is idempotent; the re-projection path calls it once over the edge map. |
| **C2** | An edge is **flow-eligible in a lineage stream** iff its `kind` is not `config` **and** (the document has no `view` **or** both endpoints carry `viewRole === "core"`). A boundary or context node's other connections are cut, so a charge animating into it would lie about where the value goes. Such edges still take `.is-lit` — they are real and they are drawn — but never `.is-flowing`. |
| **C3** | A **direct** edge hover, focus or selection pulses **any** drawn edge, including one touching a boundary or context node. That edge is fully drawn and fully real; the user pointed at it, not at a path. |
| **C4** | `e` / `Shift+E` iterate **only** routes present in the current projection. They read the live `routes` array; a cached incident list would select a route no longer in the DOM. |
| **C5** | `FLOW_MAX_EDGES` and scoping are complements: the capped-trace copy names scoping as the way to get the animation back, and the two features are cross-referenced in the docs on that point. |

---

### 11.15 New acceptance gates

**Python (`analyzer/tests/core/`)**

- `test_project_parse.py` — the grammar: every valid form, every error code, `node:n:…` colon splitting, alias
  normalization, `symbol:` → `unit:`, depth bounds, `parse → format → parse` round-trip.
- `test_project_resolve.py` — the five tiers on `samples/vision_pipeline`: `unit:train` → `train.train` alone
  (tier 3 beats the tier-4 op `train.train.train`); `unit:train_test_split` → the call-site op (tier 4);
  `unit:batch_loop` → **two** anchors with `ambiguous: true`; `unit:Nope` → empty, exit 0.
- `test_project.py` — the algorithm: role assignment, ancestor closure, ghost pruning, issue retention and the
  stable rotation, `present` carry-through, `workspace` carry-through, subsequence ordering (§11.2.1),
  `--max-nodes` disclosure, depth monotonicity, the empty-but-legal case.
- `test_graph_invariants.py` — parameterized over the battery, with the §11.4 F2 relaxation.
- `test_determinism.py` — two scoped runs byte-identical, in-process twice and once in a subprocess with a
  different `PYTHONHASHSEED`.
- `test_schema.py` — `view` and `viewRole` are absent from every `required` array; the golden still validates;
  `--demo` still byte-equals the golden; `'view' not in analyze_to_dict(unscoped)`.
- `test_cli.py` — the §11.5 exit table, stdout purity on every error path, `--scope` with `--demo` rejected,
  `--list-scopes`, and byte-identity of an unscoped run against a pre-change snapshot.
- `test_api.py` — the new exports, the two new `AnalyzeOptions` fields with defaults, the digest `scope` block.

**Parity gate — the design (F2-A12)**

- `contracts/scope.cases.json` — the 10-case battery, computed over the **frozen** `contracts/graph.sample.json`
  so the gate cannot churn when a rule changes (`samples/` is owned by A2 under §10 A12). Cases:
  `all` · `stage:train`@0 · `unit:train.train`@1 · `unit:batch_loop`@0 (context + ambiguity) ·
  `unit:batch_loop`@2 (monotonicity) · `file:data.py`@0 · `concern:evaluation`@0 · `concern:optimization`@0 ·
  `node:n:8d3e0f7a2b61`@1 (the stable rotation) · `unit:Nope` (empty-but-legal). Plus the six error codes as
  non-projecting cases asserting `(code, term, candidates)` only.
- `contracts/scope.expected.json` — generated by `analyzer/tools/gen_scope_fixtures.py` from the Python
  `project()`; `--check` regenerates and byte-diffs without writing.
- `webview/test/scope_parity.test.mjs` — loads the golden and the two fixtures, runs
  `MLView.__internal.scope.project` on each case, and **deep-compares**: the `nodes` id list **in order**, the
  `edges` id list in order, the `issues` id list in order, `issue.nodeIds` in order (so the rotation is checked),
  every node's `viewRole`, all eight `stage.nodeCount` / `issueCounts` / `maxSeverity`, `stats`, and the **whole**
  `view` object.
- `tools/verify.py --scopes` runs the generator's `--check` and then the viewer test; `--all` includes it;
  `scripts/e2e.ps1` / `e2e.sh` gain the step **between** the CLI-vs-MCP parity gate and the bundle-hash gate.
  A Python-side change the TypeScript port did not follow fails the gate rather than drifting silently.

**Reduced-motion gate — the design (F1-A6)**

`webview/test/flow.test.mjs` stubs `matchMedia` **before** `MLView.mount`, and it must be a full stub because
`ui/theme.ts:83-94` calls `addEventListener` on the result:

```js
const ctx = await loadBundle();
ctx.window.matchMedia = (q) => ({
  media: q, matches: /prefers-reduced-motion/.test(q),
  addEventListener() {}, removeEventListener() {},
  addListener() {}, removeListener() {}, onchange: null,
  dispatchEvent() { return false; },
});
const app = ctx.MLView.mount(root, sample, bridge);   // only now
```

Then assert: `.mlv-canvas` has `data-motion="reduced"`; `document.querySelectorAll('.mlv-edge__flow').length === 0`
after a hover; exactly one `.mlv-edge__dir` with a `rotate(` transform and two `.mlv-edge__port` circles on the
hovered edge; and, as a stylesheet gate in `webview/test/bundle.test.mjs`, that `dist/mlview.css` contains a
`prefers-reduced-motion` block naming `mlv-edge__flow`. The **positive** case is asserted separately with
`matches: false`, so "no flow because reduced motion" and "no flow because it is broken" cannot be confused.

**Composition gate (§11.14)** — one test: apply a scope, relayout, hover an edge inside it and assert the flow
renders; hover a node whose lineage crosses the boundary and assert core-to-core edges take `.is-flowing` while
boundary-touching edges take `.is-lit` but not `.is-flowing`; then clear the scope and assert no flow element or
`--mlv-flow-*` property survives.

**VS Code (`vscode-extension/test/`)** — `findEnclosingUnit` on the sample's real lines; each command body against
a stubbed panel; the title/description formatter; protocol round-trip for `setScope` / `scopeChanged` plus
unknown-type tolerance; and **`diagnostics.test.js` gains a case asserting `DiagnosticsPublisher.publish` output is
byte-identical while scoped**.

**Claude plugin (`claude-plugin/tests/`)** — the stdio handshake still asserts **exactly five** tool names and
≤4 KB results; new cases for `scope:"units"` (budget + shape), a scoped `mlview_analyze` digest, the extended
error text, and CLI-vs-MCP parity on three selectors.

**Two existing plugin tests change, and only these two.** Both because the ancestor closure replaces the
parent-to-null promotion, which makes `stage:<id>` a **one-node superset** (verified on `samples/vision_pipeline`:
`stage:train` gains exactly `sklearn_baseline.baseline` as a `context` node, 9 → 10). Any test asserting an exact
node set or count for `mlview_graph {scope:"stage:<id>"}` must be updated to the superset; `{scope:"node:<id>"}`
at depth 1 is **byte-identical to today** and must not move.

---

### 11.16 Files that must change together

| Group | Files | Why |
|---|---|---|
| Schema | `contracts/graph.schema.json` **and** `analyzer/src/mlview/schema/graph.schema.json` | `test_schema.py` asserts both copies byte-identical, and `python -m mlview schema` prints the shipped copy |
| `present` consumers | `contracts/validate_sample.py`, `analyzer/tests/core/test_graph_invariants.py`, `webview/src/layout/model.ts` | §11.4 F1/F2/F3 — carrying `present` through breaks all three otherwise |
| One projection | `analyzer/src/mlview/core/project.py` **and** `webview/src/scope/project.ts` | §11.2, gated by §11.15 |
| Grammar and its promise | `claude-plugin/server/mlview_payloads.py` **and** `mlview_mcp.py`'s `mlview_graph` docstring | the docstring contractually names the accepted values |
| Assets | `webview/dist/*` → `vscode-extension/media/`, `analyzer/src/mlview/emit/assets/` | **the integrator alone** runs `tools/sync-assets.py`, once per review round; every viewer change moves `generator.rendererSha` |

---

### 11.17 Standalone deep-link safety (2026-09-08) — amends §8 / §10 A3, renderer-local

**The failure.** `standaloneBridge`'s `openLocation` opened a source location by creating a hidden
`<a href="vscode://file/<abs>:<line>:<col+1>">` and calling `.click()` **in its own frame**. On a top-level
`file://` report that hands the URL to the OS and nothing visible happens. Inside a **sandboxed iframe** — which
is how a report is embedded on claude.ai, and how any chat, notebook or docs host embeds one — it is a top-level
navigation to a scheme the sandbox does not allow, so the browser **replaces the frame** with its own
blocked-content page: *"This content is blocked. Contact the site owner to fix the issue."* The whole diagram is
gone, with no way back but a reload. Everything that opens code went through this one function — the Issues
rail's **Go to**, the Inspector's **Open `file:line`**, the related-location links, and every node and edge
click.

**The rule, absolute:** the standalone report **never navigates its own document**. No `.click()` on a same-frame
anchor, no `location.href` assignment, no `location.assign` / `location.replace`, no `window.open`. A source scan
of `webview/src/bridges.ts` gates all five.

**The decision table.** `deepLinkPlan({ embedded, local, absFile, file, line, col })` in
`webview/src/bridges.ts` is a pure, exported function of two booleans, and is the only place the outcome is
decided:

| `embedded` | `local` (`location.protocol === "file:"`) | `mode` | What happens |
|---|---|---|---|
| `true` | either | `copy` | clipboard gets `file:line`; toast reads `Copied <file>:<line> — open the report locally to jump into VS Code` and carries the anchor below |
| `false` | `false` | `copy` | same as above — an `http(s)` report has no OS handler to reach |
| `false` | `true` | `launch` | hidden `<iframe>` at the `vscode://` URL, removed after ~1500 ms; the existing blur detection copies `file:line` and toasts `Copied <file>:<line>` if no blur arrives within 400 ms |

`embedded` is `window.self !== window.top`, read inside `try/catch`; a **throw counts as embedded**, since only a
cross-origin embedding can make that comparison raise — the exact case the bug lives in. `url` is built in both
modes and is always `vscode://file/<absFile>:<line>:<col + 1>` (`col` is 0-based in the protocol, 1-based in the
URL; `line` is not shifted).

**The copy toast carries a way out.** `<a class="mlv-toast__link" target="_blank" rel="noopener noreferrer">Open
in VS Code</a>` with the deep link as its `href`, built with `createElement` + `textContent` like everything else
(§8). `target="_blank"` is what makes it safe: a host that permits the protocol still gets a one-click jump, and
a sandbox **without `allow-popups`** merely drops the click — silently, into a *new* browsing context, leaving
the report exactly where it was. The `launch` fallback toast carries **no** link: that reader can already reach
the handler.

**Unchanged:** the `openLocation` message itself (§4), the honest-copy semantics of `MLV-R1-007` (the toast is
strictly downstream of a confirmed clipboard write, with the `execCommand` fallback and the focus restore of
`MLV-R1-FLOW-007`), the standalone capability set, and the vscode bridge, which posts to the extension host and
never touched this path.

**Gates:** `webview/test/bridges.test.mjs` — the pure table, a **real nested browsing context** (an iframe inside
a jsdom document, with the bundle evaluated in the frame; `window.top` is not configurable in jsdom, so a stub
would be weaker than the real thing), a genuine `file:` document for the launch row, and the source scan.
`webview/test/render_report.mjs` asserts the same on the shipped report: a node click navigates nothing, the
diagram survives, `file:line` is copied and the toast carries the anchor.

---

### 11.17.1 The copy toast is an interface (2026-09-08) — amends 11.17, renderer-local

11.17 made the toast the ONLY outcome of every open-in-editor gesture in an embedded or `http(s)` report, and
its anchor the only affordance. It was still built as a decoration: no `role`, no live region, one card appended
per message, and a hard 3000 ms life. Measured in the shipped report inside
`sandbox="allow-scripts allow-same-origin"`: `role` and `aria-live` both `null`, no live-region ancestor, the
app's announcer byte-identical before and after the click, the `.mlv-toasts` stack empty — a screen-reader user
pressing **Open model.py:34** was told nothing at all — and the anchor 17 Tab presses away from the button that
had just been activated, inside those 3000 ms.

| # | Rule |
|---|---|
| **D1** | Floating toasts live inside ONE persistent host, `div.mlv-toasts--floating` with `role="status"`, created before the message lands (the gesture puts it up; the clipboard write resolves in a later task) so the text is a live-region MUTATION rather than a node that appears already containing it. `aria-live` is left off, so the app's announcer stays the only `[aria-live]` element — the same reasoning as `ui/states.ts` (MLV-R2-W10). The host is mounted in `.mlv-root` when one exists, for the theme tokens, and carries the `position: fixed` the card used to. |
| **D2** | It holds **exactly one card**. A new message replaces the previous one, so two toasts can never occupy identical rectangles and no buried anchor can keep a stale deep link in the tab order. (Two is the natural case, not a contrived one: a node click toasts, and the Inspector it opens carries its own **Open `file:line`**.) |
| **D3** | The 3000 ms timer is **held** while the pointer is over the card or focus is inside it (`mouseenter` / `focusin` clear it, `mouseleave` / `focusout` re-arm it), so the one control the reader is offered cannot expire under a cursor on its way to it. |
| **D4** | When the gesture that raised the toast came from the keyboard, the anchor **takes focus**; when it came from a pointer, focus is not moved. The modality is read in the capture phase from `Enter` / `Space` only, and only within 1000 ms, so a stray keystroke cannot claim a later click. If the toast is dismissed while it holds focus, focus returns to the element the gesture started from — never to `<body>`, which silently kills the canvas keymap (MLV-R1-FLOW-007). |
| **D5** | The deep-link path is **encoded**: `encodeURI`, then `#` → `%23` and `?` → `%3F`, which `encodeURI` deliberately leaves alone. `C:/w/issue#1/a.py` used to produce a URL a handler reads as the file `C:/w/issue` with `#1/a.py:3:1` as a fragment — the wrong file, with the line and column gone — and nothing said so, because the clipboard text and the anchor label were still right. `:<line>:<col + 1>` is appended after the encoding. |
| **D6** | An empty `absFile` yields `url: ""` rather than `vscode://file/:<line>:<col+1>`, and a toast with no `url` carries **no anchor**: a dead link is not an affordance. |
| **D7** | A `launch` never accumulates frames: existing `iframe.mlv-deeplink` elements are removed before a new one is appended, so six "Go to" clicks inside the 1500 ms removal window invoke the OS handler once, for the location last asked for, instead of six times at once. The 1500 ms delay is a lifetime, not the protection — the comment that claimed otherwise is gone. |

**On "silently drops".** 11.17's wording for the sandboxed click describes the safety, not the experience: the
click produces no user-visible effect at all and a console warning (*"Blocked opening 'vscode://…' in a new
window because the request was made in a sandboxed frame whose 'allow-popups' permission is not set."*). D3 is
what keeps the copied `file:line` and its explanatory sentence on screen after such a click instead of vanishing
three seconds later.

**Gates:** `webview/test/bridges.test.mjs` (R3-DL-01 … R3-DL-04), over the same real nested browsing context.

---

### 11.18 Diagnostic kinds and coverage diagnostics (2026-09-08) — amends §2, core-owned

`Diagnostic.kind` was a **closed seven-value enum** (`parse_error`, `dynamic_scope`, `rule_error`, `truncated`,
`notebook_skipped`, `framework_suppressed`, `config_warning`) and five separate proposals in `docs/ROADMAP.md`
want to extend it. Adding one value at a time would mean five amendments, five mirrored edits per §11.16 and
five gate passes, so all five land here at once. **The §2 listing of the enum is superseded by this table.**

| New value | Meaning | Emitted today |
|---|---|---|
| `untagged_dataflow` | A rule reached a value it never traced — no `ValueTag` at all — and stayed silent. Coverage gap, not a finding. | **yes** (`rules/r_leakage.py` → `GraphContext.untraced`) |
| `single_file_analysis` | One file of a larger package was analyzed, so the cross-file rules could not see the sibling definitions they need. | **yes** (`core/coverage.single_file_diagnostic`) |
| `unresolved_callee` | A call the analyzer could not resolve. **Superseded by 11.23 A1/A3:** the call is no longer dropped — it mints an `unknown` op carrying the construct, and one diagnostic is emitted per (file, scope). | **yes** (`core/unresolved.unresolved_callee_diagnostics`) |
| `config_unresolved` | A configuration value referenced by the pipeline could not be resolved to a literal (ANA-10). | no — reserved |
| `notebook_analyzed` | A `.ipynb` **was** analyzed, carrying the execution-order caveat (NB). | no — reserved |

A reserved value is part of the enum from this amendment: every consumer must already accept it, and no consumer
may assume the three unemitted kinds never arrive. Nothing about the existing seven changes.

**The two emitted now.** Both exist because MLView's worst failure mode is that it cannot distinguish *"I checked
and it is fine"* from *"I could not check"*. Neither is an `Issue`, neither changes a rule's gate, and neither
costs precision: `samples/vision_pipeline` still carries exactly its fifteen findings and both clean corpora stay
at zero, with **zero coverage diagnostics on all three** (`tests/core/test_coverage.py`).

| # | Rule |
|---|---|
| **C1** | `untagged_dataflow` is emitted **once per `(file, scope)`**, never once per site: `codes` lists every rule code that gave up in that scope, `count` is the number of untraced values, `line` is the earliest of them, and the message names up to three of them with their lines and says *why* the tag is missing (a parameter, an unresolved binding, a dynamic scope). This is the `framework_suppressed` shape, for the same reason — a rule looping over sites must not emit a diagnostic per iteration. |
| **C2** | A rule declares a coverage gap through `GraphContext.untraced(call, name, reason)` and never by appending a `Diagnostic` itself, exactly as it emits findings only through `ctx.issue()`. The gate a rule bails on is **unchanged**: `r_leakage` still requires `FEATURES` / `RAW_DATA`; the new branch fires only where the value carries *no tags at all*, which is the measured blind spot (a bare function parameter) and cannot be confused with a value that was traced and found innocent. |
| **C3** | `single_file_analysis` fires only when all three hold: exactly one module was analyzed, sibling Python modules exist under the same package root (the nearest ancestor without an `__init__.py`), and the analyzed module **imports at least one of them**. The import is what turns "you asked about one file" into "the answer you got is incomplete"; a standalone script with siblings it never imports is not warned about, because crying wolf costs more than it buys. |
| **C4** | Its `codes` are derived from `RuleSpec.cross_file`, a declared boolean on the spec — never a hand-maintained list in the diagnostic. `cross_file` means *this rule's finding is anchored in the analyzed file but its evidence lives in a sibling module*. Today: **MLV301, MLV302, MLV401, MLV501** — exactly the set `mlview issues samples/vision_pipeline/train.py` loses against `mlview issues samples/vision_pipeline --scope file:train.py` (3 findings against 7), asserted as an equality, not as a literal, in `tests/core/test_coverage.py`. |
| **C5** | `count` is the number of sibling modules **not** analyzed, and the message names up to four of them by relpath plus how many of them the analyzed module imports. |
| **C6** | The summary emitter gives coverage diagnostics **their own block**, `Coverage (N)`, above `Notes (N)` and outside the ten-note clip that `Notes` applies. A coverage gap buried under housekeeping is the failure the block exists to end. |
| **C7** | `RuleSpec.cross_file` is appended **last** and defaults to `False`, so every existing construction of the frozen dataclass — including the one in `tests/core/test_robustness.py` — still works. `rules.cross_file_codes()` is the only supported way to read the set. |

**Two more kinds gain an emitter, both inside the existing seven.** PERF-02 replaced `ir/build_ir.py`'s literal
`range(4)` with a convergence loop (`ir/converge.py`, cap `MAX_ROUNDS = 8`); when the loop stops on the cap
rather than on a fixed point, the pipeline appends a **`truncated`** diagnostic naming the round count, because
resolution that quietly gave up is exactly the "smaller graph with nothing to point at" this contract already
refuses elsewhere. CLEANUP 3 makes a typo'd rule code — in `.mlview.toml` or in a `# mlview: ignore[...]`
comment — a **`config_warning`** carrying up to three near misses; it used to be accepted in total silence, so a
suppression that never took effect looked exactly like one that did.

**Mirrors (§11.16).** `contracts/graph.schema.json` and `analyzer/src/mlview/schema/graph.schema.json` are
byte-identical, and `claude-plugin/vendor/mlview/schema/graph.schema.json` follows through `tools/sync-core.py`.
`webview/src/types.ts` and `webview/src/ui/chrome.ts` carry the TypeScript copy of this enum and are amended in
the same change.

**Gates:** `analyzer/tests/core/test_coverage.py` (14 cases, including the both-mirrors enum check and the
three-corpus negative), `analyzer/tests/core/test_ir_converge.py` (the round-cap diagnostic),
`analyzer/tests/core/test_cleanup.py` (the two `config_warning` paths), and `contracts/validate_sample.py`,
which reads the enum from the schema and therefore needs no edit.

**Alongside, in the same change — three additive surfaces §3 does not yet list.** Recorded here so the §3 table
is not silently out of date; a later amendment may re-home them.

* `--group-by rule|file|none` on `analyze` and on `issues` (RAIL-GROUP), **default `none`**, which prints exactly
  what those commands printed before the flag existed. It is a rendering choice, never a filter: `--json` is
  byte-identical with and without it, and the `N issue(s)` header keeps counting occurrences, not groups.
  `api.render_summary` gains a matching `group_by="none"` third argument, appended last and defaulted, so the
  frozen two-argument call returns exactly what it always returned. `--format text` and `api.render_text` are
  deliberately **not** grouped: that form's `Findings` block is one entry per issue by definition, and
  `render_text`'s one-argument signature is pinned by `tests/core/test_api.py::test_render_signatures`.
* `issues --text` now renders (CLEANUP 1). It was declared with `dest="text_out"` and read by nobody, so the two
  invocations were byte-identical; it reaches `emit/text_out.render_findings`, the same message / why / fix block
  `analyze --format text` prints.
* `GraphContext` gains `ctx.untraced(call, name, reason)`, additive beside the §3 listing exactly as
  `ctx.calls_with_role` already is. It emits no `Issue` and touches no gate.

A4's size band is now enforced inside `emit/html_out.write_html` at runtime (BUILD-01) instead of only over the
demo artifacts in `scripts/e2e`: an out-of-band report is still written, with a warning on **stderr** naming
`--max-nodes` as the lever. The fallback report emitted when the viewer bundle is absent is exempt, because A4
words the band "when the bundle is present".

---

### 11.19 Class-method ops and resolution fixes (2026-09-08) — amends §7.1, analyzer-owned

**This is a re-baseline.** `samples/vision_pipeline` grows from **45 nodes and 45 edges** to **54 nodes and 52
edges** and carries **exactly the same fifteen findings, at the same lines, in the same 5 / 6 / 4 split**. Every
document that quotes the demo's size must be updated in this same change — `scripts/check_docs.py` enforces that
no two docs disagree about it, and the canonical count is whatever
`python -m mlview analyze samples/vision_pipeline --format summary` prints. Three
analyzer fixes land together, deliberately, so one golden regeneration covers all three (ROADMAP §(e), Track A);
`contracts/graph.sample.json` is **hand-authored and unchanged**, so `mlview --demo`, `contracts/scope.cases.json`
and `contracts/scope.expected.json` are byte-identical and §11.15's parity battery is untouched.

| # | Change | Where |
|---|---|---|
| **ANA-1** | `CallSite.class_ir` carried two facts and `core/build.py` read the wrong one, so **every op written inside a class method was dropped**. The two facts are now two fields. | `ir/model.py`, `ir/scopes.py`, `core/build.py` |
| **ANA-2** | `self.loss_fn(...)` resolved to `torch.nn.Module.loss_fn` — a symbol nobody declared — instead of to the value the attribute holds. | `ir/resolve.py` |
| **ANA-3** | `_relative_base` trimmed the last dotted component of a package `__init__`, whose name **is** the package, and a re-exported symbol resolved to nothing. | `ir/symbols.py`, `ir/build_ir.py`, `ir/resolve.py` |

**A1 — the two fields are normative.** `CallSite.class_ir` means *the workspace class this call **resolves to***
and is written **only** by `ir/resolve.py`. `CallSite.enclosing_class` means *the class whose body this call is
**written in*** and is written **only** by `ir/scopes.py`. No reader may use one for the other. `_create_op`'s
early return (a call onto the class's own unit node) fires on `class_ir` alone; `_owning_unit` then parents an op
written in a method onto the enclosing class unit, or onto a method-level `epoch`/`batch`/`fold` loop unit when
one exists. Node ids stay content-addressed (`file`, `qualname`, `kind`) and therefore deterministic.
**Issue anchoring follows for free**, which was the point: on `analyzer/tests/accuracy/corpus/lightning_tabular`
MLV602, MLV110 and MLV111 used to carry the **same** `nodeIds` — the `TabularDataModule` class node, drawn in the
config lane — and now anchor on the `random_split()` and the two `DataLoader()` ops that actually carry them,
with the program's stage line going from four present stages to seven. Receiver resolution stops minting
`datamodule.TabularDataModule.float` / `.long` for torch tensor methods in the same program, because a value
bound inside a method no longer inherits the enclosing class as its `class_ir`.

**A2 — the candidate still comes from a binding, never from a name (iron law 1).** When the callee is
`<recv>.<attr>` and `binding_of("<recv>.<attr>", scope)` yields a `ValueRef` with a producer FQN, a `via_fqns`
or a workspace `class_ir`, that value becomes the receiver and the method becomes `__call__`. A binding with
nothing behind it (`self.threshold = 0.5`) is refused, and a name with no binding at all (`self.encode(x)`, a
real method) resolves exactly as before. This is also what stops `torch.nn.Module.<any attr>` being minted for a
self-held layer: `self.stem(x)` is now `torch.nn.Conv2d.__call__` → role `FORWARD`, which §1 already draws
through its receiver instead of as a second node.

**A3 — the hop is bounded and the bound is stated.** `pkg/__init__.py` publishing `from .net import Net` makes
the class reachable as `pkg.Net`, a name no `ClassIR` carries. `WorkspaceIR.reexports` maps such an alias to the
definition, following at most **3** hops (`ir/build_ir._MAX_REEXPORT_HOPS`), cycle-safe, workspace-internal only.
A chain that outruns the cap is reported as a **`dynamic_scope`** diagnostic naming the symbol and the cap —
the kind `_unresolved_imports` already uses for exactly this failure; **§11.18's enum is not extended.**

**Why 54 and not the 63 the audit measured.** The ANA-1 prototype was measured with the fabrication still in
place: on its own the demo is **61 nodes / 54 edges**, seven of which are FQNs invented under `torch.nn.Module.`
for the forward calls in `ConvBlock.forward` and `SmallCNN.forward` — `torch.nn.Module.conv`, `.norm`, `.drop`,
`.stem`, `.pool`, `.head` and `.pool.flatten`. ANA-2 resolves those seven to the real layer objects
built in `__init__`, where role `FORWARD` is transparent by design (`core/build.TRANSPARENT_ROLES`). 54 is
therefore the same graph with the duplicates removed: `model.py` goes from **2 nodes (its two classes, no
layers)** to **11**, and the Model lane from 3 to 12.

**What is pinned.** `samples/vision_pipeline/expected_issues.json` is **unchanged** — same fifteen rows, same
lines — and `analyzer/tools/gen_expected_issues.py --check`, `gen_scope_fixtures.py --check` and
`gen_rule_docs.py --check` all pass without regeneration. Both clean corpora stay at **0 issues**
(`samples/vision_pipeline_clean` 55 → 64 nodes, `analyzer/tests/clean` 108 → 127), and `analyzer/tests/clean`
keeps **0 high**. `tools/accuracy.py` keeps precision 1.0 and every recall number to four decimals; its
**graph-fidelity ratchet moves 0.6619 → 0.8633** (92 → 120 of 139 labelled human-diagram ops), which is
re-recorded in `analyzer/tests/accuracy/baseline.json` — the one number this change is allowed to move.

**Files that must change together (§11.16 addendum).** A graph-shape change regenerates
`vscode-extension/test/fixtures/vision_pipeline.graph.json` in the **same** commit: it is a real analyzer run
over the sample and `vscode-extension/test/scope.test.js` resolves against the shape the analyzer actually
emits. `contracts/graph.sample.json` is **not** regenerated by anything, ever.

**`tools/perf_equiv.py` is expected to report DIFFERENT on all three corpora for this change and only this
change.** It is the byte-identity gate for optimisations (§PERF-01/02), and a re-baseline is the one thing it
exists to catch; the wall-time is unchanged (0.92x–1.02x, inside noise).

**Gates:** `analyzer/tests/core/test_class_method_ops.py` (12), `analyzer/tests/rules/test_attr_callable.py` (8),
`analyzer/tests/core/test_pkg_reexport.py` (10) with the `analyzer/tests/fixtures/pkgreexport/` package and the
`analyzer/tests/fixtures/rules/MLV401_self_attr_bad.py` fixture, plus the unchanged
`analyzer/tests/rules/test_samples.py` battery and `contracts/validate_sample.py` on the regenerated document.


### 11.20 Host surface drift (2026-09-08) — amends §6 and 11.9, host-owned

Two normative listings fell out of step with the tree during Sprint 3 and are corrected here rather than in
place: overwriting §6 or 11.9 would erase the record of what they used to say, which is the whole reason §11
exists. Both listings are **superseded by this section**; nothing else in either changes.

**A — the extension's contributed settings (§6).** §6's `Settings:` line names `mlview.showSpeculative` and
`mlview.followCursor`, and omits the setting COVERAGE added. CLEANUP deleted the first two in this sprint — both
shipped in the Settings UI reading *"Not implemented in this prototype"*, and A6 cut `followCursor` outright, so
deleting them is the contract-compliant move rather than a reduction in surface. The contributed set is now
**exactly these thirteen**, and `vscode-extension/package.json` is the authority:

| Setting | Type | Default |
|---|---|---|
| `mlview.pythonPath` | string | `""` |
| `mlview.analyzeOnSave` | boolean | `true` |
| `mlview.exclude` | array | `[]` |
| `mlview.maxFiles` | integer | `500` |
| `mlview.maxNodes` | integer | `400` |
| `mlview.minSeverity` | `low` \| `medium` \| `high` | `low` |
| `mlview.minConfidence` | number | `0.6` |
| `mlview.currentFileAnalysisScope` | `file` \| `package` \| `workspace` | `package` |
| `mlview.diagnosticsEnabled` | boolean | `true` |
| `mlview.diagnosticSeverity` | `warning` \| `error` | `warning` |
| `mlview.disabledRules` | array | `[]` |
| `mlview.codeLens` | boolean | `true` |
| `mlview.trace` | `off` \| `messages` \| `verbose` | `off` |

`mlview.currentFileAnalysisScope` is COVERAGE's: it decides what **MLView: Visualize (Current File)** hands the
analyzer before narrowing the diagram back to the file through the existing §11.7 `setScope` path. `package` is
the default because analysing a file alone cannot fire MLV301, MLV302, MLV401 or MLV501 — each needs a sibling
module — so the old single-file path lost four of `train.py`'s seven findings in silence. `file` restores the old
behaviour and earns a `single_file_analysis` diagnostic (§11.18) for doing so. **Nothing removed here may come
back under the same name with different meaning**; a future speculative-findings toggle needs a new name.

**B — `ViewState` (11.9).** Two fields were added by RAIL-GROUP and VIEW-10 and belong in the listing:

```ts
export interface ViewState {
  // ... 11.9, unchanged ...
  /** Optional: the Issues rail's grouping. Absent = 'none'. */
  railGroupBy?: 'none' | 'rule' | 'file';
  /** Optional: the legend panel's open state. Absent = closed. */
  legendOpen?: boolean;
}
```

Both follow 11.9's rule exactly and gain no new one: **optional, absent at their default, sanitized on restore**
(`railGroupBy` through `sanitizeGroupBy` in `webview/src/ui/railgroup.ts`, which folds any unknown value to
`'none'`; `legendOpen` through a `typeof === 'boolean'` guard in `applyState`), and **a host predating them
round-trips them untouched** because the host stores `ViewState` opaquely. An older saved state restores to
`'none'` and closed. `webview/src/types.ts` is the authority for the interface.

**Why an amendment and not an edit.** §6 has been wrong in *both* directions since CLEANUP landed — naming two
settings that do not exist and omitting one that does — and 11.9's listing was incomplete. Editing the two lines
in place would leave no trace that the surface changed, so a reader of a shipped extension could not tell a
deletion from a documentation error. This is the shape §11.18 used for the `Diagnostic.kind` enum, for the same
reason.

---

### 11.21 CI adoption: change attribution, the baseline ratchet, SARIF (2026-09-09) — amends §3 and §10 A6, analyzer-owned

**§10 A6's `"baseline"` trim is lifted, and only that one.** A6 was a correct prototype scope
decision and is now the measured blocker to adoption: a realistic 50-file repository starts at
**111** findings, so `--fail-on high` exits 2 forever and the only way to use MLView on an
existing codebase is never to gate on it. The other three A6 challengers stay refused — fuzzy
search, a third LOD tier, and implementing `followCursor`. Nothing else in A6 changes.

Three additive mechanisms land together because they are one product: attribute the findings a
change is responsible for, forgive the ones that predate the decision to adopt, and hand both to
the review tool the team already reads.

| # | Surface | Where |
|---|---|---|
| **a** | `--changed-since REV`, `--changed-paths FILE`, `--changed-only` on `analyze` and `issues`; optional `Issue.change` | `adopt/gitdiff.py`, `adopt/attribute.py` |
| **b** | `mlview baseline write [PATHS] [--out FILE]`, `--baseline FILE` on `analyze` and `issues`; optional `Issue.baselined` | `adopt/baseline.py` |
| **c** | `--sarif FILE\|-` on `analyze` and `issues` | `emit/sarif_out.py` |

**A0 — the analysis is never narrowed.** Every one of these flags runs after a **whole-workspace**
analysis and edits the finished document. Narrowing the analysis to the changed files is the exact
fidelity loss §11.18 C3 reports (`mlview issues train.py` finds 3 of the 7 findings the directory
finds), and it would be invisible: the output would simply be smaller.

#### A — change attribution

| # | Rule |
|---|---|
| **A1** | The diff is `git -c core.quotepath=false diff -M --unified=0 --no-color <rev> --`, run in the analyzed root. `-M` is normative: without rename detection a moved file reads as entirely new and a refactoring PR inherits every finding in it. `--unified=0` is what makes line attribution possible at all. |
| **A2** | `Issue.change` is a closed three-value enum. **`new`** — the primary `loc` is inside an added hunk. **`touched`** — a `relatedLoc` is inside an added hunk, **or** the primary `loc` is in a changed file outside every hunk. **`existing`** — neither. The field is emitted **only** when attribution succeeded; its absence means *unattributed*, and never *old*. |
| **A3** | **`--changed-only` keeps exactly the findings that intersect an added hunk** — `new`, plus the `touched` whose evidence is inside one — and drops `existing` together with the `touched` that merely share a file with the change. On the audit's PR fixture (7 lines appended to `train.py`) the plain run reports 15 findings and `--changed-since HEAD --changed-only` reports **0**, exit 0; those 7 same-file findings sit on lines the pull request never saw, and failing a gate on them is the adoption blocker this amendment exists to remove. `change` therefore stays a three-value **display** classification — a reviewer wants to know that a file they edited also carries old findings — while `--changed-only` is the **gate** filter. A finding whose `relatedLoc` lands in a hunk is `touched` and is **never** dropped: that is how a leak introduced upstream of an untouched `fit()` site still surfaces on the pull request that caused it. |
| **A4** | `--changed-paths FILE` accepts **either** a unified diff (a runner that already has one does not re-shell git) **or** a newline-separated path list. A path list has no hunks, so nothing can be `new`; the run says so through a `config_warning` rather than under-reporting in silence, and `--changed-only` then keeps every finding in a changed file. |
| **A5** | **Every failure degrades to "unattributed, showing everything" with a `config_warning`, never to an error and never to an empty list.** No `git` on PATH, not a repository, an unknown revision, a git that does not answer within 20 s, a `--changed-paths` file that cannot be read: no issue carries `change`, nothing is dropped, `--changed-only` is inert and says so, and the exit code is whatever the findings themselves justify. A gate that passes because git was missing is worse than no gate. |
| **A6** | Paths are mapped through `git rev-parse --show-toplevel` into **workspace-relative** form, and a changed file outside the analyzed root is discarded — a monorepo diff touching another package never marks this package's findings as changed. |
| **A7** | `--changed-only` may remove the only finding a ghost node carried, so the ghost sweep and `finalize()` re-run afterwards: invariant 1.1.8 and every §0 ordering rule hold on the emitted document exactly as they do without the flag. |

#### B — the baseline ratchet

| # | Rule |
|---|---|
| **B1** | The match key is **`(code, symbol, snippetHash)`**, where `snippetHash` is `sha1(" ".join(snippet.split()))[:12]` — the whitespace-normalised primary snippet. Not the line, because a baseline that dies on an edit above the finding is a baseline nobody keeps; not the file, because a renamed module carries the same finding, which is the same lesson `git diff -M` teaches in part A. |
| **B2** | **Matching is counted, not keyed alone.** A key recorded *n* times forgives the first *n* findings carrying it, in document order; the *n+1*th is reported. Two textually identical findings do share a key, so without the count a copied training loop would arrive pre-forgiven — the one hole a ratchet cannot have. |
| **B3** | A matched finding is **marked, never deleted**: `Issue.baselined` is emitted `true`, the issue stays in `issues[]`, and `--show-suppressed` lists it. It is excluded from the **rendered** counts and from `--fail-on`. `stats.issues` is unchanged and keeps counting every unsuppressed finding — it is the document's project-level truth — and the summary line nets the baselined ones out and prints `· N baselined` so one number never silently stands for two. |
| **B4** | **Unmatched entries are reported**, always: `N baseline entries no longer match: …` as a `config_warning` naming up to three. A baseline that has silently stopped matching is a gate that has silently stopped gating. |
| **B5** | The baseline document is `{"version": 1, "tool": "mlview", "entries": [...]}` , sorted, with **no timestamp and no analyzer version**: it is committed and reviewed, and a byte that changes for no reason is a byte somebody has to read. `file`, `line` and `title` are written for that reviewer and are **never** matched on. |
| **B6** | A baseline that cannot be read, is not JSON, or declares another format version is a `config_warning` and every finding is reported — the safe direction for a gate to fail in. Never an exit code. |
| **B7** | `mlview baseline write` writes the file and nothing to **stdout**; the path goes to stderr like every other written artifact. Default `--out` is `<root>/.mlview/baseline.json`. |

#### C — SARIF 2.1.0

| # | Rule |
|---|---|
| **C1** | `--sarif FILE` writes SARIF 2.1.0; `--sarif -` writes it to stdout, and combining that with a `--json` that also claims stdout is a **usage error** (exit 1, stdout untouched), never two payloads in one stream. On `issues` the SARIF honours `--code` — a statement about which rules were asked for — but not `--limit` and not the suppressed/baselined hiding: a limit is a reading convenience, and a suppressed finding ships as a *suppressed result* (C5) so the consumer never reads it as fixed and then as new again. |
| **C2** | **No absolute path is ever emitted.** Every `artifactLocation.uri` is the workspace-relative `Loc.file` with `uriBaseId: "%SRCROOT%"`, and `originalUriBaseIds["%SRCROOT%"]` carries a `description` and **no `uri`**: the importer supplies the checkout location. GitHub rejects an absolute URI, and a CI log must not leak the runner's layout. |
| **C3** | `partialFingerprints.mlviewIssueId` is `Issue.id`, which §0 defines as `sha1(code\|file\|qualname\|symbol)` — content-addressed, never line-derived. `test_id_stability.py` already gates that; the SARIF test re-asserts it end to end across 20 inserted blank lines, so the consumer's own new/existing agrees with `--changed-since`. |
| **C4** | `tool.driver.rules[]` is the **whole registry**, not the rules that fired, so `ruleIndex` is stable between runs and every `helpUri` (`docs/rules/<CODE>.md`, relative to the same `%SRCROOT%`, restated in `properties.helpUriBaseId` because SARIF has no per-field base) resolves whether or not the rule fired. |
| **C5** | Severity maps `high → error`, `medium → warning`, `low → note`; `rank` is `confidence × 100`. A **suppressed or baselined** finding ships as a result carrying `suppressions[{kind: "external"}]`, not as a missing one — deleting it would make the SARIF disagree with `--show-suppressed`. `change` maps to `baselineState` (`new` → `new`, otherwise `unchanged`). |
| **C6** | The document deliberately declares **no `columnKind`**. `Loc.col` is CPython's `ast.col_offset`, a UTF-8 byte offset, which is neither of SARIF's two enumerations; claiming one would be a false precision on a non-ASCII source line. Columns are `col + 1`, SARIF being 1-based. |
| **C7** | `runs[0].properties.diagnostics` carries every `Diagnostic` kind and message. What the analyzer could **not** see travels with the findings instead of being dropped at the CI boundary. |

**Schema (§11.16 mirrors).** Three optional additions, mirrored byte-identically in
`contracts/graph.schema.json` and `analyzer/src/mlview/schema/graph.schema.json` and carried to
both vendored copies by `tools/sync-core.py`: `Issue.baselined` (boolean) and `Issue.change`
(the three-value enum), neither in `required`; plus §11.22's `answers`.
`contracts/graph.sample.json` is **not** regenerated and `analyze --demo --json -` stays
byte-identical to it — a document that names none of these flags emits exactly the bytes it
emitted before they existed.

**One existing gate is narrowed, not weakened.** `tests/core/test_no_exec.py` banned `subprocess`
outright. `adopt/gitdiff.py` is now the single allowed importer, and the exemption is paid for by
a new assertion that every `subprocess` call in the core is a list literal beginning `"git"` with
no `shell=`. The promise that survives untouched is the one that mattered: **the analyzed program
is never imported, executed or `exec`ed.**

**Gates:** `analyzer/tests/core/test_ci_adopt.py` (25 cases over a real `git init` of
`samples/vision_pipeline`, including all four degradation paths), `analyzer/tests/core/test_sarif.py`
(15 cases, validating against the official OASIS schema vendored at
`analyzer/tests/fixtures/sarif-schema-2.1.0.json`), and the unchanged
`contracts/validate_sample.py` on every attributed and baselined document.

---

### 11.22 The Pipeline Answer Card (2026-09-09) — amends §2 and §3, analyzer-owned

MLView's headline is answering four questions in ninety seconds. The practitioner walkthrough
measured **two of four** answered from the first screen — both by the rail rather than the diagram,
with Q2 and Q3 roughly 1600 px below the fold — and **nothing in any host stating the answers in
words**. This amendment adds the words.

**A new OPTIONAL root-level key, `answers`**, composed by `emit/answers.py` and attached by
`core/graph.MLGraph.to_dict()` to every document the analyzer builds:

```json
"answers": {
  "dataEntry":  {"sentence": "...", "nodeIds": ["n:..."], "locs": [{"file": "data.py", "line": 26}], "confidence": 0.95},
  "objective":  {...}, "evaluation": {...}, "verdict": {...}
}
```

| # | Rule |
|---|---|
| **P1** | **Deterministic and offline.** The four sentences are composed from the finished document by lookups over an already-sorted `nodes[]` — no model, no network, no clock — so all three hosts print the same bytes for the same graph. `compose(doc)` is a pure `dict -> dict`. |
| **P2** | **An absence is stated as an absence.** A workspace with no eval stage gets *"No evaluation stage was detected: nothing computes a metric or runs the model in eval mode, so this pipeline's quality is not measured anywhere MLView can see."* Printing nothing is not an option: not being able to tell *"I checked and it is fine"* from *"I could not check"* is the failure this round exists to end. |
| **P3** | **Nothing under `MIN_CONFIDENCE` (0.6) is asserted as fact.** A candidate below the floor is dropped from the citation and **counted**: the sentence then ends *"N further candidate(s) were below the 0.6 confidence floor and are not asserted."* Silence about a dropped candidate would be the same failure one level down. |
| **P4** | **A ghost node is never cited.** A ghost is the analyzer's marker for something it expected and did **not** find, so citing one as a located fact inverts its meaning. Ghosts are read in exactly one place — the eval guard — and there the absence itself is the answer. |
| **P5** | `confidence` is the **weakest** node the sentence rests on, so a long citation list cannot inflate it, and it is `0.0` exactly when nothing is cited — which is exactly when the sentence states an absence. The `verdict`'s confidence is the weakest **finding** it names, because a verdict is a claim about findings, not about nodes. |
| **P6** | The **guard clause is stated only where a guard was found**, present or missing. A sklearn-only pipeline has no eval mode to guard, and inventing the absence of one would be a finding MLView did not make. On `samples/vision_pipeline` the clause reads *"the eval path is NOT guarded — no `model.eval()` or `torch.no_grad()` covers train.py:44"* (from the MLV301 ghost); on `samples/vision_pipeline_clean` it reads *"the eval path is guarded by eval() at train.py:48"*. |
| **P7** | The `verdict` names the top three findings by **severity × confidence** and appends the coverage caveat when any coverage diagnostic (§11.18) is present: *"MLView also reported N coverage gap(s) (…), so this is not a clean bill of health."* A clean verdict on a blind run is the one sentence this card must never print. |
| **P8** | **Project-level truth.** `core/project.project()` carries unknown root keys through verbatim, so a projection keeps the whole-project answers — exactly as `stages[].present` does (§11.4 F1) — and `view` remains the **last** key of a projected document. |

**Surfaces (§3, additive).**

* `--format summary` and `--format text` gain an **`Answers`** block, printed as the first block
  after the header lines and above `Stages`, wrapped deterministically at 96 columns. A document
  carrying no `answers` key prints no block, which is why `analyze --demo` — the hand-authored
  `contracts/graph.sample.json`, which has no `answers` — is textually unchanged and
  `analyze --demo --json -` stays **byte-identical** to the golden.
* `api.digest()` gains an `answers` key holding the four **sentences** only — **866 B** measured
  on `samples/vision_pipeline`, taking the digest from **2507 B to 3373 B** of the 4096 B budget,
  with nothing shed (`topIssues` stays at 10, `lanes` at 7, no `truncatedDigest`). The
  budget stays a hard cap: after the existing ladder empties `topIssues` and then `lanes`, the
  answers are shed in the stated order **`dataEntry`, `objective`, `evaluation`, `verdict`** —
  the first two are the ones an agent can most cheaply re-derive from `lanes` and `topIssues`.
  At the contractual 4096 B none of the four is dropped on any corpus measured.
* `emit/answers.py` exports `compose`, `render_block` and `digest_answers`. `api.render_summary`
  and `api.render_text` keep their pinned signatures.

**Schema (§11.16 mirrors).** `answers` is added to the root `properties` (never to `required`)
with `$defs/Answers`, `$defs/Answer` and `$defs/AnswerLoc`, byte-identically in
`contracts/graph.schema.json` and `analyzer/src/mlview/schema/graph.schema.json`.
`contracts/graph.sample.json` is not regenerated and does not gain the key.

**Measured on `samples/vision_pipeline`** (54 nodes / 51 edges / 15 findings, the §11.19
re-baseline): the four sentences cite `data.py:26` and `data.py:31` (dataset and split),
`train.py:22` and `train.py:23` (loss and optimizer), `train.py:41` and `train.py:44` (the eval
loop), and `model.py:34`, `sklearn_baseline.py:24`, `train.py:29` (the verdict's three). The four
`file:line` pairs ROADMAP MLV-P1 names — `data.py:26`, `data.py:31`, `train.py:23`, `train.py:44`
— are all among them.

**Gates:** `analyzer/tests/core/test_answers.py` (21 cases: the acceptance lines, the guarded and
unguarded twins, an absent eval stage, an empty workspace answering all four as absences, the
ghost exclusion, the confidence floor, determinism, the summary ordering, the digest budget, and
the projection carrying answers verbatim), plus `contracts/validate_sample.py` on every document.

---

### 11.23 Framework recognition and unresolved callees (2026-09-09) — amends §1, §7.4 and 11.18, analyzer-owned

**This is a framework re-baseline, and it is deliberately *not* a demo re-baseline.**
`samples/vision_pipeline` is **byte-identical**: 54 nodes, 51 edges, the same fifteen findings at the same
lines in the same 5 / 6 / 4 split and — the constraint ANA-5a is designed around — **at the same confidence
values**. `tools/perf_equiv.py` digests `ee5eaeca69ba677e` for the demo and `bc6c4260be410d80` for
`samples/vision_pipeline_clean`, both unchanged; `samples/vision_pipeline/expected_issues.json`,
`contracts/graph.sample.json`, `contracts/scope.cases.json`, `contracts/scope.expected.json` and
`vscode-extension/test/fixtures/vision_pipeline.graph.json` are **not regenerated by this change**, and no
document that quotes the demo's size needs an edit. What moves is the *framework* corpora, and only upward:
`analyzer/tests/clean` **137 → 142 nodes / 123 → 135 edges, still 0 issues**.

There is **no schema change**. Every node kind, edge kind, stage id and diagnostic kind this amendment uses
already exists; `analyzer/src/mlview/schema/graph.schema.json` and `contracts/graph.schema.json` stay
byte-identical to each other and to their previous contents, so `--demo` byte parity and §11.15's parity
battery are untouched.

| # | Change | Where |
|---|---|---|
| **FW-RECOG** | tf.data, HuggingFace `datasets`, the missing Keras families, gradient boosting, and the Lightning hook table with its `Trainer` control edges. | `knowledge/tf_tbl.py`, `knowledge/hf_tbl.py`, `knowledge/gbm_tbl.py`, `knowledge/hooks_tbl.py`, `core/hooks.py`, `core/build.py`, `ir/resolve.py` |
| **ANA-5a** | A **per-call** `unresolved_callee` signal, its `unknown` op and its diagnostic; the scope-wide dynamic flag is never widened. | `ir/model.py`, `ir/scopes.py`, `ir/bindings.py`, `ir/resolve.py`, `core/unresolved.py`, `core/build.py`, `core/pipeline.py`, `emit/text_out.py`, `emit/mermaid_out.py` |

---

#### F — framework recognition (normative)

**F1 — knowledge entries are data, and the tables are the contract.** tf.data lives in
`knowledge/tf_tbl.py`, HuggingFace `datasets` in `knowledge/hf_tbl.py`, boosting in `knowledge/gbm_tbl.py`
and the Lightning surface in `knowledge/hooks_tbl.py`. `knowledge/other_tbl.py` keeps everything it already
held. A row is an `entries.E`, and a *family* on a row is what carries a chain: `tf_dataset`, `hf_dataset`,
`keras_model`, `lightning_module` and `dmatrix` join the families `ir/resolve._FAMILY_BASE` maps to a base
FQN. `keras_dataset` is an alias of `tf_dataset`, because `keras.utils.image_dataset_from_directory` really
does return a `tf.data.Dataset`.

**F2 — `take` and `skip` are NOT `SPLIT`.** They are the tf.data holdout idiom, and the ordering check that
makes such a holdout judgeable is ANA-9's MLV121. Their role is `TFDATA_SUBSET`, which no rule keys on today.
Giving them the split role before MLV121 exists would fire MLV602 on every tf.data pipeline;
`test_take_and_skip_are_not_split_nodes` is the guard, and it may not be relaxed by anything short of MLV121
landing.

**F3 — `batch` and `prefetch` carry the LOADER *tag* and not the `LOADER` *role*.** `core/coverage`'s
`UNTRACED_ROLES` sweep reads argument 0 of every `LOADER` site, and argument 0 of `.batch(128)` is an
integer, so the role would put a "could not trace this value" coverage note on every correct tf.data
pipeline. The tag is what carries the meaning downstream; the role exists to be swept.

**F4 — a `LightningModule` is a model class.** `knowledge.MODEL_BASES` is `torch.nn.Module` plus
`{pytorch_lightning,lightning,lightning.pytorch}.LightningModule`, and `ClassIR.is_model_module` is the
question the graph asks: node kind, `self`'s MODEL tag, `call_output_tags`, `seed_annotations` and
`_mark_forward` all read it. **`ClassIR.is_nn_module` keeps its exact torch meaning** — literally
`torch.nn.Module in resolved_bases` — because it also gates whether `torch.nn.Module.<method>` may be
proposed, and widening *that* is how a phantom `torch` framework lands on a Keras file.

**F5 — a framework hook is a unit, and its lane is declared, not voted on.** `knowledge/hooks_tbl.HOOK_STAGES`
maps a hook method name to `(stage, role, why)`; `core/hooks.model_hooks(cls)` returns them in source order
for any class whose `resolved_bases` meet `HOOK_OWNER_BASES` (`LightningModule` and `LightningDataModule`
under all three roots). `core/build.py` mints one **unit** node per hook, parented to the class node, and
`_assign_stages` takes the declared stage rather than the op vote — a `training_step` whose only recognised
call is `self.log(...)` is still the train body. The class node is then promoted to `level: "stage"` by the
existing `_promote_levels` rule, exactly as a class containing a loop already was.

**F6 — `on_*_epoch_*` is control, and control is an edge, not a ninth lane.** ROADMAP FW-RECOG maps the
lifecycle hooks to *control*. `StageId` is a frozen eight-value enum and this amendment does not extend it:
a lifecycle hook is staged by the **phase word in its own name** (`on_train_epoch_end` → train,
`on_validation_epoch_end` → eval) and carries the role `LIGHTNING_HOOK_CONTROL`, while *control* is expressed
the way §1 already expresses it — by the `control` edge `Trainer` draws into it.

**F7 — `Trainer.fit` / `.validate` / `.test` draw a `control` edge (`subkind: "enter"`) into the hooks they
actually run.** The owning class is found through the **binding** behind the call's model / datamodule
argument (iron law 1: never a name). `fit` does not enter `test_step` and `test` does not enter
`training_step`; drawing those would be a false statement about control flow. `core/hooks.MAX_CONTROL_EDGES`
caps one call at **12** targets.

**F8 — `configure_optimizers()` returns an OPTIMIZER by contract.** `ir/build_ir._tag_hook_returns` adds the
tag to the hook's `ReturnSummary` after every `infer_returns` pass, keeping whatever FQNs and workspace class
the inference recovered. The hook's contract *is* its return type — Lightning steps whatever comes back — so
this is a framework fact, not an inference.

**F9 — recognised is not the same as drawn, and the difference is deliberate.** `LIGHTNING_LOG`,
`LIGHTNING_HPARAMS`, `LIGHTNING_CTL`, `MODEL_SUMMARY`, `TFDATA_CARD` and every `LIGHTNING_HOOK_*` role are
**absent from `knowledge.OP_ROLES`**. They exist so that nothing is fabricated for those methods — before
this, `self.log("train_loss", loss)` resolved through `torch.nn.` to role `LAYER` and drew a layer node in the
Model lane for a logging call — and they are not drawn, because five metric cards per training step is noise,
not recognition. `manual_backward` **is** drawn: it is a real gradient update and ANA-7 will need it.

**F10 — a class that declares a method may not have a framework base symbol invented for it.**
`ir/resolve._canonical_for_receiver` proposes a family-base candidate for a method the receiver's own
workspace class defines **only when that candidate is an exact knowledge row**. `torch.nn.Module.forward`
survives; `torch.nn.Module.encode` does not. This is 11.19 A2's iron law one level up.

**F11 — a call whose callee is a call resolves through the value.** `layers.Dense(64)(x)` is the Keras
functional API: `ir/resolve._called_value` builds a `ValueRef` for the inner call and resolves `__call__` on
it, which the `keras_model` family answers as `keras.Model.__call__`, role `FORWARD` — already drawn through
its receiver by §1. Without this, ANA-5a's syntactic check correctly flagged four unresolvable callees in a
fifteen-line model. A callee that still resolves to nothing **keeps** its ANA-5a flag.

**F12 — an annotation that names a known third-party class carries its family.** `def fit(model:
keras.Model, ...)` gives `model` `via_fqns = ("keras.Model",)` as well as its tags, so `model.fit(...)` is
`keras.Model.fit` instead of falling through the MODEL tag to `torch.nn.Module.fit`. The FQN is set only when
`knowledge.lookup` recognises the annotation; a workspace-local annotation is unchanged.

**F13 — a multi-line method chain is anchored on the method name.** `ast` gives a method call the position of
the *start of its receiver*, so every link of a parenthesised tf.data chain reported the first line: seven
nodes stacked on one line and click-to-code that never lands on the call you clicked. `ir/locs.call_loc`
anchors on `func.attr` **only when `func.end_lineno != node.lineno`**, so every single-line call keeps the
`Loc` it had. No file in `samples/vision_pipeline`, `samples/vision_pipeline_clean`,
`analyzer/tests/clean` or `analyzer/tests/fixtures/rules` contains such a chain, which is why the two sample
corpora are byte-identical; R2.1's re-slice guarantee (`tests/core/test_locations.py`) is unchanged.

**F14 — MLV602 gains one FQN and one framework.** `datasets.Dataset.train_test_split` joins `_ALWAYS_RANDOM`
under the keyword `seed`, and the rule's `frameworks` list gains `hf`. It shuffles by default, so an unseeded
call really is a different split on every run. `docs/rules/MLV602.md` and `docs/rules/README.md` are
regenerated by `analyzer/tools/gen_rule_docs.py` in the same change.

**F15 — a framework hook body is not an eval region.** `rules/r_eval.framework_hook()` excludes a hook of a
hook-owning class from `eval_regions()`, so MLV301 / MLV302 do not fire inside `validation_step`. This is a
**narrowing of two rules and it is stated as one.** Iron law 4's `WRAPPER_FACTOR` de-rate is the right answer
for a hand-written loop in a file that imports a wrapper; it is the wrong answer here, because the region *is*
the wrapper's own hook — Lightning calls `model.eval()` before it calls that method, so "no `model.eval()`
dominates this region" is not weak evidence, it is a statement about code the user does not own. Without this,
FW-RECOG's own recognition (`self(features)` is now a forward pass) re-armed two absence rules on **correct**
Lightning code at confidence 0.34: `analyzer/tests/clean` went to 2 issues, which §7.4's gate forbids.

---

#### A — ANA-5a, never silently drop a call (normative)

**A1 — `unresolved_callee` is emitted from this amendment.** 11.18's table listed it *"no — reserved"*. That
row now reads **yes** (`core/unresolved.unresolved_callee_diagnostics`). Nothing else in 11.18 changes, and
`config_unresolved` and `notebook_analyzed` remain reserved.

**A2 — the signal is per call and is never `ScopeIR.mark_dynamic`.** `CallSite.unresolved_callee` is an
optional string naming the construct. `rules/confidence.DYNAMIC_FACTOR` is 0.7 and applies to every finding in
a scope, so widening the scope-wide flag to cover one lambda would silently drop unrelated findings a
confidence bucket. The demo's fifteen findings keep their exact confidence values, pinned in
`analyzer/tests/core/test_unresolved_callee.DEMO_FINDINGS` — `expected_issues.json` records code / file / line
/ severity and deliberately not confidence, so the pin lives where the constraint does.

**A3 — two halves, and both require a real binding.** The **syntactic** half
(`ir/scopes.callee_construct`) fires when the callee expression is not a `Name` or an `Attribute` chain: the
result of another call, a subscript, a lambda, a conditional expression, an awaited value, a computed callee.
The **binding** half (`ir/resolve._note_unresolved`) fires when a name or attribute chain resolved to nothing
the knowledge tables recognise **and a binding for it exists with nothing behind it** — no producer, no
workspace class, no `via_fqns`. The binding is the guard and it is what keeps this narrow: a builtin such as
`len` or `range` has no binding in scope, so it is never flagged and no `unknown` node is minted for it. Iron
law 1 is unchanged: this invents no FQN and asserts nothing about what the value is.

**A4 — `ValueRef.opaque` names the construct behind a binding.** Set by `ir/bindings._opaque_kind` to *a
lambda*, *a value assigned in a match case*, *a conditional expression*, *a subscript* or *a dataclass
default_factory*. It is read only by the diagnostic; no rule may gate on it.

**A5 — `ast.Match` case bodies are walked.** `ast.Match`'s children are its subject plus `match_case` nodes,
which are neither `stmt` nor `expr`, so `ir/scopes` walked straight past every case body and a
`match`-dispatched model, criterion and optimizer produced **no call sites at all**. The bodies are now
visited under a `#match<line>.<case>` block id, and `AssignRecord.in_match` records that only one arm runs.

**A6 — the `unknown` op tells the truth about `dynamic`.** A node minted for an unresolved callee carries
`dynamic = call.scope.is_dynamic`, not `True`: the callee is unresolved, the scope may be perfectly static,
and `dynamic_scope`'s own definition would be contradicted otherwise. The pre-existing dynamic-scope path is
unchanged. Both carry `confidence: 0.35` and `kind: "unknown"`, which §8 already renders.

**A7 — one diagnostic per `(file, scope)`, never one per site.** 11.18 C1's shape, for 11.18 C1's reason. The
message names up to three sites and then, for the rest, the **distinct constructs** that are not already
named, so a reader sees that a `match` and a `default_factory` were among them without opening the file.
`count` is the number of sites, `line` the earliest.

**A8 — no emitter may claim a stage is absent without qualification when a call was unresolved.**
`emit/text_out` and `emit/mermaid_out` append *"(unverified: N call(s) could not be resolved, so a stage may
be present but undetected)"* to the `not detected:` line, and `emit/answers._COVERAGE_KINDS` gains
`unresolved_callee` so the MLV-P1 verdict appends *"so this is not a clean bill of health"*.
`core/coverage.COVERAGE_KINDS` is **not** extended in this change: it is mirrored in `webview/src/ui/chrome.ts`
and `claude-plugin/server/mlview_notes.py`, which are host-owned, so the diagnostic renders in the `Notes`
block beside `dynamic_scope` until a host-owned change promotes it. That is a stated gap, not an oversight.

---

#### What this could not analyze

* **A hook reached through a `Trainer` built elsewhere** has no binding to resolve, so no control edge is
  drawn for it. The hook units still exist and the class is still read correctly; the arrow is what is
  missing, and a missing edge is visible in a way a missing lane is not.
* **`take` / `skip` holdouts are recognised and not judged.** MLView will draw a tf.data holdout and say
  nothing about whether `reshuffle_each_iteration` makes it leak. That is MLV121's question (ANA-9).
* **`self.log(...)` and `save_hyperparameters()` are recognised and not drawn** (F9). A reader who expects a
  node per logging call will not find one.
* **A `match`-dispatched value is reported, not resolved.** The analyzer knows a factory was called and which
  construct defeated it; it does not know which arm ran, and says so rather than picking one.
* **Seven of the thirteen labelled ops the corpus still misses are inline `criterion(...)` /
  `model(features)` calls whose receiver is an unannotated parameter** — DATAFLOW-IP's territory, untouched
  here. The other six are two `.shift()` time-series ops, `build_from_cfg`, `optimizer.step` behind a
  `getattr` dispatch, and the demo's two `SmallCNN` / `ConvBlock` construction sites.
* **`xgboost.train` / `lightgbm.train` use the role `GBM_TRAIN`, not `FIT`**, so MLV101 does not see a
  leak through the functional boosting API. `FIT` would make `core/coverage`'s sweep read the parameter dict
  as argument 0 and emit a false coverage note on correct code.

---

#### Measurements

| Corpus | Before | After |
|---|---|---|
| `samples/vision_pipeline` | 54 nodes / 51 edges / 15 issues | **unchanged**, digest `ee5eaeca69ba677e` |
| `samples/vision_pipeline_clean` | 64 / 55 / 0 | **unchanged**, digest `bc6c4260be410d80` |
| `analyzer/tests/clean` | 137 / 123 / **0** | 142 / 135 / **0** |
| `analyzer/tests/clean/lightning_module.py` | 20 / 13, 6 stages, `LitClassifier` `kind: class` | 24 / 24, 6 stages, `kind: model`, objective at `F.cross_entropy`, populated eval lane, **0 issues** |
| `analyzer/tests/clean/hf_trainer.py` | 15 / 7 / **0** | 16 / 8 / **0** |
| `accuracy/corpus/keras_tfdata` | 22 / 19, graph fidelity 66.7% | 34 / 32, **100.0%** |
| `accuracy/corpus/lightning_tabular` | 25 / 19, 100.0% | 32 / 36, 100.0% |
| `accuracy/corpus/hf_trainer_finetune` | 29 / 20, 83.3% | 31 / 23, **91.7%** |
| `accuracy/corpus/hydra_research` | 46 / 43, 2 diagnostics | 47 / 44, 3 — the new one is `registry[name](...)` |
| `tools/accuracy.py` | precision 1.0, recall 0.629, fidelity 0.8633 | precision **1.0**, recall **0.629**, fidelity **0.9065** |

`tools/perf_equiv.py` legitimately reports **DIFFERENT on `tests_clean` and identical on both sample
corpora**: this is a re-baseline of the framework corpora and the byte-identity harness exists to catch
exactly that. `analyzer/tests/accuracy/baseline.json` is re-recorded with graph fidelity **0.8633 → 0.9065**
and its `note` says which change earned it; every recall and precision number is unchanged, and
`docs/ACCURACY.md` §3 is updated in the same change because `scripts/doc_numbers.py` requires the two to
agree.

**Gates:** `analyzer/tests/core/test_framework_recognition.py` (24 cases — one positive fixture per family
under `analyzer/tests/fixtures/frameworks/`, each asserting `kind` **and** `stage`),
`analyzer/tests/core/test_unresolved_callee.py` (13 cases over
`analyzer/tests/fixtures/oddsyntax/unresolved_callee.py`), plus the unchanged
`analyzer/tests/rules/test_precision.py`, `analyzer/tools/gen_expected_issues.py --check`,
`gen_scope_fixtures.py --check`, `gen_rule_docs.py --check` and `tools/verify.py --all`.

**Files that must change together (§11.16 addendum).** `tools/sync-core.py` re-syncs
`claude-plugin/vendor/mlview` and `vscode-extension/core/mlview` in the same commit — both `vendor: synced
core` and `vsix: synced core` are gates. `docs/rules/MLV602.md` and `docs/rules/README.md` are regenerated
output, never hand-edited. `vscode-extension/test/fixtures/vision_pipeline.graph.json` is **not** regenerated,
because the demo did not move.

---

### 11.24 Diagram export: SVG, PNG, clipboard and print (2026-09-09) — amends §4 and §8, renderer-local

`grep` over `webview/src` found **no `toDataURL`, no SVG serialization and no `@media print`**: the diagram was a
transformed `div` stack over an SVG edge layer, so Ctrl+P produced the current viewport at the current zoom with
the fixed toolbar, rail, minimap and zoom cluster painted over it, and there was no way at all to get the picture
into a PR, a design doc or an incident writeup. VIEW-07 adds four outputs and one new message. Everything here is
**additive**: a host that ignores the message keeps a viewer that still copies and still prints.

**The one hard rule this amendment exists to enforce.** There are now **two renderers of one picture**, and they
may not be able to disagree. `webview/src/render/plan.ts` owns the decision — `planScene(index, frame, routes,
labels, keep, staleFiles, isFilteredOut)` returns the lanes, the `NodeVisual`s (shallowest first) and the
`EdgeVisual`s — and **both** `render/scene.ts` (DOM) and `export/svg.ts` (SVG) walk that one object. Nothing else
may decide what is drawn. The gate is `webview/test/export.test.mjs`:

| # | Rule |
|---|---|
| **E1** | The SVG carries **exactly one `<g data-node-id>` per planned box** and **exactly one `<path data-edge-id>` per planned route**, in plan order, with the same id sets — not merely the same counts. |
| **E2** | Each such path's `d` is the `RoutedEdge.d` string **verbatim**. The export may never re-derive geometry; a single recomputed curve is the drift this rule exists to catch. |
| **E3** | Every document edge a route stands for is listed in that path's `data-edge-ids`, so a merged route loses none of them. Measured on the flagship: **54 `<g>`, 51 `<path>`, all 51 document edge ids covered**. |
| **E4** | An edge label is drawn **iff** VIEW-03 planned one that is neither `hidden` (declutter exhausted) nor hover-only (`placement.always === false`). That is exactly the set `styles/edge.css` reveals at `data-lod="full"`, so the export shows what the diagram shows. |

**The SVG is standalone, and "standalone" is enumerated.** No `url(...)` — therefore no `<marker>`, no
`clip-path`, no gradient and no filter; the arrowheads are inline `<path>`s reproducing the `<marker>` transform
(`refX 8.5, refY 5`, `markerUnits="userSpaceOnUse"`, 9/10 = 0.9 scale). No `foreignObject`, no `<image>`, no
`<use>`, no `xlink:href`, no `<script>`, no `@import` and no `@font-face`. **The only `http` in the file is the
`xmlns` declaration**, which a standalone SVG cannot legally omit, and the gate asserts that literally: one
occurrence, and it is the namespace. Text is real `<text>` in a generic stack
(`ui-sans-serif, …, sans-serif` / `ui-monospace, …, monospace`); geometry is real `<rect>` and `<path>`.

**Colours are literals, resolved from the live theme.** `export/palette.ts` reads each `--mlv-*` token off the
**mounted root** with `getComputedStyle`, so a VS Code user exports their own theme's colours, and falls back
**per token** to the literal fallback chain of `styles/tokens.css`, transcribed once. A value that still contains
`var(` or `color-mix(` is refused rather than emitted. The transcription is gated: the test parses
`dist/mlview.dev.css` and asserts every entry is the last literal in that token's declaration, for light, dark and
high contrast, following a one-token alias (`--mlv-fg-boundary: var(--mlv-text)` in the hc block) — **87 token
checks**. `color-mix()` washes become `fill-opacity` over the emitted background rectangle, which is the same
picture; `contracts/graph.sample.json` and the schema are untouched.

**PNG.** Drawn **from that SVG** — never from a second traversal — onto an offscreen canvas at **2×**
(`export/raster.ts`). The source is a `data:` URI, not a `blob:` one, because a webview CSP is written per scheme
and a data URI needs no revocation. The no-external-reference rule above is what keeps the canvas untainted, so
`toDataURL` returns bytes instead of throwing. Where there is no canvas (jsdom, a host without one) the result is
`null` and the viewer **says so** rather than claiming a file: *"Could not draw the PNG here — save the SVG
instead."*

**Clipboard.** The async clipboard API is attempted in the viewer, because it is the one path that behaves the
same in both hosts: `navigator.clipboard.write([ClipboardItem])` for the PNG, `writeText` for the markup. Every
failure — no API, a denied permission, an image type the host refuses — falls back to posting the existing
`copy` message, which each host already implements and which the standalone report answers with the copy toast
of **11.17.1**. Copy PNG falls back to Copy SVG before it falls back to the toast.

**§4 addition — `UiToHost` gains one message.** Nothing else in the protocol changes.

```ts
{ v: 1; type: 'exportFile'; kind: 'svg' | 'png'; name: string; base64: string }
```

```ts
// ui -> host, always with BOTH field spellings (see the interop note below)
{ v: 1; type: 'exportFile'; kind: 'svg' | 'png';
  name: string; base64: string;              // this amendment's spelling
  suggestedName: string; data: string;       // 11.33's spelling, byte-identical
  scope: 'view' | 'all' | 'scope' }          // the region, in the host's words

// host -> ui
{ v: 1; type: 'requestExport'; kind: 'svg' | 'png'; scope?: 'view' | 'all' | 'scope' }
```

The payload carries the file itself — UTF-8 SVG markup, or PNG bytes — because the webview↔host channel is a
structured clone that a `Blob` does not reliably survive, and base64 makes the frame one plain string for every
reader. It is pure base64: no whitespace, no `data:` prefix, length a multiple of four. The filename is a
**suggestion** (`mlview-<workspace>-<scope>-<region>.svg`, slugged to `[a-z0-9._-]`, no separator and no `..`);
a host may rename it and **must** sanitise it before touching a filesystem. The VS Code extension owns the save
dialog and must list `exportFile` in `UI_TO_HOST_TYPES` and accept it in `isUiToHost`
(`vscode-extension/src/protocol.ts`), or its guard rejects the frame. The standalone bridge answers it with a
download.

`requestExport` is the host's two commands asking for a picture they cannot draw: the lane bands, the card
rectangles and the routed paths exist only inside the viewer, once it has laid the graph out. The viewer sets the
menu's checked region from `scope` — so a command and the toolbar leave each other in the same state — renders,
and answers with exactly one `exportFile`, or with a toast when nothing is drawn. `all` is the host's word for
this renderer's `diagram`; the mapping lives in one place (`hostRegionWord` / `regionFromHostWord`). §4's rule
that an unknown type is logged and ignored is untouched, so a host that never sends `requestExport` and a viewer
that never receives one still interoperate.

**INTEROP NOTE — two amendments, one message, and why the frame says everything twice.** The viewer half and the
host half of VIEW-07 were specified in the same sprint with different field names: this amendment was briefed
`{kind, name, base64}` and the host-side amendment **11.33** validates `{kind, data, suggestedName?, scope?}` and
**rejects a frame without `data`**. Rather than ship two halves that cannot talk, the viewer writes **both**
spellings on every frame, with `name === suggestedName` and `base64 === data` **always**, so either validator
accepts it and either reader decodes the same bytes. This is a deliberate, gated redundancy
(`test/export.test.mjs` asserts the equality and the base64 shape), not an accident, and it is **the one thing in
VIEW-07 a reviewer should collapse**: pick one spelling, drop the other from `types.ts`, `export/actions.ts` and
`bridges.ts`, and delete this note. Until then nothing is broken in either direction. 11.33's E2 (base64 shape,
32 MiB cap, format-signature check), E3 (the save dialog is the host's) and E5 (MCP gains no export) are the
host's rules and are not restated here.

**The standalone download, and why it is not a §11.17 violation.** `export/download.ts` — a module of its own,
and that is deliberate: `test/bridges.test.mjs` greps `bridges.ts` for `.click()`, `location.href =` and
`window.open` because 11.17 turns on that file containing no way to move the document, and that grep must stay
blunt. The one anchor click in the viewer therefore lives in a file whose whole job is that click, under four
stated rules: it is reached only from an explicit export gesture; the href is always an object URL of bytes the
page just produced; the anchor always carries `download`, and the function **refuses to click one that cannot**
(an engine that ignores the attribute would navigate); and the anchor is created, clicked and removed inside one
call. A sandbox without `allow-downloads` drops the click without touching the frame, and the failure path copies
the SVG to the clipboard (or, for a PNG, says plainly that it could not).

**Print — the fourth output.** `webview/src/styles/export.css` is a new, **last** stylesheet layer
(`build.mjs` `CSS_FILES`, so its `!important` overrides win over every layer above it). Its `@media print` block
hides `.mlv-chromebar`, `.mlv-chiprow`, `.mlv-banners`, `.mlv-status`, `.mlv-rail`, `.mlv-minimap`, `.mlv-zoom`,
`.mlv-statehost`, `.mlv-tooltip`, the toasts, the legend, the shortcut sheet, the scope picker, the answers card,
the theme switch and this menu; releases the page-fill chain (`html.mlv-fills-page`, `body`, `.mlv-root`,
`.mlv-body`, `.mlv-main`, `.mlv-canvas` → `display: block`, `height: auto`, `overflow: visible`); and drops the
canvas transform (`.mlv-world { transform: none; position: static }`) so the world prints at the **natural pixel
size the layout already wrote onto it**. `print-color-adjust: exact` keeps the lane washes and stage rails, which
are meaning rather than decoration, and the compact-LOD rules are lifted, because level of detail is a zoom
decision and print has just thrown the zoom away — without that a document opened at 0.548 would print
title-only cards at natural size, which is neither picture. Measured in Chromium on the emitted report: on
screen `.mlv-world` is `matrix(0.5, …)` at 788×1315 inside an `overflow: hidden` canvas with
`document.body.scrollHeight = 900`; under `print` media it is `transform: none`, `position: static`, **1576×2630**,
canvas `overflow: visible`, `scrollHeight = 2630`, toolbar / rail / minimap / zoom all `display: none` — and
Chromium's own PDF of it is **2 A3 pages** of diagram with no chrome.

**The three regions (`export/actions.ts`).** `diagram` is the whole world. `view` is the visible canvas converted
to world coordinates and clamped to it. `scope` is the **bounding box of the `viewRole === 'core'` nodes**, padded
24 px — the scope's actual subject, not the projection, which also carries boundary stubs and context frames the
reader did not ask to share. With no projection there is no core, the offer degrades to `diagram`, and the menu
entry is **disabled** with a title saying why: an entry that can only ever export the whole diagram under another
name is a lie about what the tool did. Elements that do not intersect the region are not emitted at all, so a
"current view" file does not secretly contain the rest of the document.

**The menu.** One trigger beside Fit (`Chrome.exportSlot`), `aria-haspopup="menu"` / `aria-expanded`; the popup
is mounted on the **app root, not in the toolbar**, because the chrome is one roving `role="toolbar"` (VIEW-12)
and eight more controls under its arrow keys is the flattening that group exists to undo. The popup is a
`role="menu"` with three `menuitemradio` regions and five `menuitem` outputs, its own arrow keys, Home/End,
Escape-closes-and-returns-focus, Tab-closes and outside-click-closes.

**Gates.** `webview/test/export.test.mjs` — **18 cases**: E1–E4 on `contracts/graph.sample.json` (always) and on
`.mlview/graph.json` (when `scripts/e2e` has produced it, asserting **54 cards and all 51 edges**);
well-formed-XML through a real parser; the no-external-reference enumeration; the font stack; the per-lane stage
colours in light and dark; the three regions; the file name; the VIEW-03 label parity; the 78-check palette drift
gate; the print block's hidden chrome and released transform; the menu's ARIA and keyboard; the `exportFile`
message shape with its base64 decoded and re-counted; the standalone download; and the honest PNG degradation.
`webview/test/export_svg.mjs` is the twin of `test/render_report.mjs` — `npm run export-svg` writes
`.mlview/diagram.svg` from a real analyzer document and re-checks all of it outside the unit suite, which is what
the Chromium screenshot in the measurement note was taken from.

**BUILD-01’s size ratchet moves once, here (TB-14).** A second renderer costs bytes: `dist/mlview.js`
237 749 -> **266 398 B** (+28.0 KB: svg + svgprim 10.5, menu 4.7, actions 3.6, palette 3.2,
raster + plan + download 2.6, and 3.4 across app / bridges / canvasview / protocol / demo) and
`dist/mlview.css` 57 243 -> **60 234 B** (+2.9 KB, the new layer). The caps are re-set to **268 KB** and
**61 KB**, leaving 8 034 B (2.9 %) and 2 230 B (3.6 %) of headroom, and the recorded figures are asserted
against the built files with a 2 KB tolerance exactly as before.

**What this could not render.** The SVG is faithful, not pixel-identical, and the differences are stated rather
than discovered: CSS `box-shadow` is not reproduced (a card is a stroked rect, not an elevated one); CSS text
ellipsis is replaced by an **average-advance** estimate per face (0.51 em sans, 0.55 em semibold, 0.60 em mono,
0.72 em for the all-caps lane header), so a string of unusually wide glyphs can ellipsise one character early or
late; the `color-mix` washes are `fill-opacity` over the emitted background, which matches only because the
background is emitted; a collapsed group's severity **cluster** is drawn where the DOM draws a pill; and the flow
animation, the hover card, the selection ring and the issue connectors are states, not content, and are never
exported. An edge label can still be crossed by a **later** edge's stroke — VIEW-03 guarantees no label-label and
no label-over-card overlap, not that nothing is drawn over a label afterwards — and the export reproduces that
faithfully, because it is the same picture. PNG and clipboard both depend on host capability and both report
failure in words; **print quality depends on the browser**, and nothing here can gate a real printer.

---

### 11.25 Packaging: the bundled core, the wheel and the precedence chain (2026-09-09) — amends §3, §6 and §9, host-owned

A marketplace install **could not work**. The VSIX was 30 entries of `media/`, `out/` and 20 rule
docs with **no analyzer**; `package.json` carried `private: true` (vsce refuses to publish), no
`repository`, no `icon`, no `extensionKind`, and its package script carried
`--allow-missing-repository`; `installCore()` offered `pip install -e <repo>/analyzer`, naming a
checkout a marketplace user does not have; and there was no wheel at all — `analyzer/dist` did not
exist. Two audits then asked for opposite things: *bundle the analyzer so no pip is needed*, and
*pip install from PyPI*. Shipping both as first-class produces two support stories, so this
amendment makes them **one precedence chain**.

**P1 — a third copy of the analyzer is authorised, and only under its gate.** `tools/sync-core.py`
now vendors `analyzer/src/mlview` into **both** `claude-plugin/vendor/mlview` and
`vscode-extension/core/mlview`, byte-exactly and under the same skip rules (`__pycache__`,
`*.pyc`, any `tests` directory). `tools/verify.py` grows a **`vsix: synced core`** row beside
`vendor: synced core`, and that row additionally fails when `.vscodeignore` would exclude `core/`
from the package — a VSIX that ships without its analyzer is green in every other gate and broken
on install. The gate is not optional here; it is the whole safety story for the third copy, and it
was the condition attached to authorising one.

**P2 — the precedence chain, stated once.** `vscode-extension/src/bundledCore.ts` decides, purely:

| Order | Chosen | When |
|---|---|---|
| 1 | the **installed** core | it is present, `schemaMajor(installed) == schemaMajor(extension)`, and `compareVersions(installed, bundled) >= 0` |
| 2 | the **bundled** core at `<extension>/core` | there is no installed core, or its schema major differs, or it is older |
| 3 | neither — the install prompt | no bundled copy in this build **and** no installed core |

`compareVersions` is numeric per dotted component (`0.10.0` is newer than `0.9.0`) and sorts any
pre-release suffix **below** the same release, so a release candidate installed for testing never
silently outranks the bundled stable core.

**P3 — the bundled core runs through `PYTHONPATH`, never through a copied interpreter.** When the
chain chooses the bundled core, `CoreClient` prepends `<extension>/core` to `PYTHONPATH` for that
spawn and sets `PYTHONDONTWRITEBYTECODE=1`; it prepends rather than replaces, so a user's own
`PYTHONPATH` still works, and the bytecode flag keeps a read-only install free of `__pycache__`
trees inside the VSIX's own directory. This is exactly how `.mcp.json` already runs the plugin's
`vendor/` copy (§6.2, A1). Nothing else about the spawn changes: same argv, same `-X utf8`, same
`shell: false`, same absolute interpreter.

**P4 — a schema-major mismatch stops being fatal.** It used to be a hard failure with an install
prompt. With a bundled core present the extension uses the copy it shipped and reports the
mismatch as a **warning**, because a working diagram plus a warning is strictly better than a
banner. With no bundled core the old fatal path is unchanged.

**P5 — the host says which core answered.** `pythonEnv.coreDescription()` returns one line
(`core: mlview 0.1.0 bundled with the extension (no mlview installed in the interpreter) · /usr/bin/python3`)
and the status-bar tooltip carries it under the issue counts. A user who pip-installs a newer core
and sees no change must be able to find out which analyzer produced the number they are reading,
without opening the output channel.

**P6 — `installCore()` offers the published wheel.** `python -m pip install --upgrade mlview`, in
a terminal, on the interpreter MLView actually resolved — never a checkout path. With a bundled
core the prompt is an upgrade path rather than a rescue.

**P7 — the manifest is publishable.** `private` is dropped; `repository` (with
`directory: "vscode-extension"`), `bugs`, `homepage`, `icon` (`media/icon.png`, 128×128),
`galleryBanner`, `preview: true` and `extensionKind: ["workspace"]` are added.
`extensionKind` is now **declared** rather than relied upon, so Remote-SSH, WSL and
Dev-Container installs land on the machine that owns the files and the interpreter. `npm run
package` succeeds with **no `--allow-missing-repository`**, and the VSIX stays **under 1 MB**
(measured: 464 KB, 99 files). `preview: true` de-risks a publish that cannot be undone.

**P8 — the icon is source, not a binary somebody once drew.**
`vscode-extension/tools/make_icon.py` renders `media/icon.png` from thirty lines of arithmetic
using only `zlib` and `struct`, and its `--check` mode re-renders into memory and byte-compares,
so an edited PNG that no longer matches the script fails instead of drifting.

**P9 — the wheel is built and proved, every run.** `scripts/build.sh` / `build.ps1` gain step
**6/6**, `python -m build --wheel analyzer` into `analyzer/dist` (gitignored); the step **skips
with a message** when `build` is not installed, because a missing publishing tool must never
redden a developer's build. `tools/wheel_check.py` is the acceptance, and both e2e drivers run it
as the row **`wheel installs and runs`**: a fresh venv, `pip install` of the wheel, `mlview
--version --json` through the **console script** (a broken entry point is invisible to `python -m
mlview`), and then one real analysis on a planted leak — because a wheel missing `schema/*.json`
or `emit/assets/*` installs perfectly and fails on first use.

**P10 — the plugin gains a hosted source.** `.claude-plugin/marketplace.json` keeps its local
`./claude-plugin` entry (a checkout is not an install channel, but it is how this repo's own
tests install) and adds `mlview-github`, using the github source object
(`{"source": "github", "repo": "realmyang/MLView"}`). Two entries may never share a name.

**Gates.** `tools/verify.py --all` is **10 rows** (the new `vsix: synced core`);
`vscode-extension/test/packaging.test.js` (16 cases: the chain, the manifest, the icon's IHDR,
`.vscodeignore`, and the bundled core's own byte-identity);
`claude-plugin/tests/test_plugin_manifest.py` (the two marketplace entries); the `wheel installs
and runs` e2e row; and a new `packaging (wheel + vsix)` CI job that builds both artifacts,
re-checks the icon and the synced core, and fails if the VSIX crosses 1 MB.

**Nothing about the document changes.** No schema field, no graph key, no exit code, and
`contracts/graph.sample.json` is untouched. A user with an installed core that is current sees
exactly the behaviour they saw before this amendment.

---

### 11.27 Suppression as an action: `suppressRule` and the quick fixes (2026-09-09) — amends §4, host-owned

Suppression works exactly as documented on the CLI — `# mlview: ignore[MLV201]` and
`[rules] disable = [...]` both behave, and `--show-suppressed` restores the row — and is
**unreachable from any UI**. Rail rows expose only "Open file:line", and the comment syntax lives
only in rule docs the report cannot reach. So the workflow for *"this one is a false positive"* is:
find a doc in the repo, memorise the syntax, switch to the editor, type it.

**S0 — this stays inside `REQUIREMENTS.md` §5 non-goal 5.** That non-goal bars quick fixes that
edit the user's ML logic. A suppression comment and a config key edit neither, and §5 already
notes the diagnostic `code` field is shaped so quick fixes can be added later. Nothing here writes
a line of Python that changes what a program does.

**S1 — one new `UiToHost` message, additive.** `HOST_TO_UI_TYPES` is unchanged; `UI_TO_HOST_TYPES`
gains `suppressRule`:

```ts
{ v: 1; type: 'suppressRule'; code: string;
  action: 'copy' | 'insert' | 'disable';
  absFile?: string;      // required by `insert`
  line?: number }        // 1-based, like every Loc.line in the document
```

`isUiToHost` accepts it only when `code` matches `^MLV[0-9]{3}$` and `action` is one of the three
words; anything else is rejected by the guard, not by the handler, and a viewer that never sends
the message is unaffected. §4's rule that an unknown message type is logged and ignored is
unchanged, so an older host and a newer viewer still interoperate.

**S2 — three actions, one implementation.** The VS Code `CodeActionProvider`
(`src/codeActions.ts`, `QuickFix` kind, `python` selector) and the `suppressRule` message both
call `runSuppression`, so the confirm dialog, the containment check and the "already ignored"
message cannot differ between the lightbulb and the diagram rail.

| Action | Title | Effect |
|---|---|---|
| `copy` | `Copy ignore comment for MLV201` | `# mlview: ignore[MLV201]` to the clipboard, with the existing copy toast |
| `insert` | `Add ignore comment on this line (MLV201)` | a `WorkspaceEdit` replacing the diagnostic's own line; **preferred** |
| `disable` | `Disable rule MLV201 in .mlview.toml` | `[rules] disable` at the workspace root, behind a modal confirm |

**S3 — the comment MERGES, it never stacks.** The analyzer reads the **first**
`# mlview: ignore[...]` on a line, so a second comment appended after the first is dead text.
`withIgnoreComment` adds the code to the existing bracket list
(`# mlview: ignore[MLV101, MLV301]`), refuses to edit a line already covered by a blanket
`ignore` / `ignore-file`, and reports "already listed" rather than writing a duplicate.

**S4 — the config write is confirmed, contained and conservative.** The dialog is **modal**, names
the file it will write, says the rule stops being reported for everyone who opens the repo and for
CI, and points at the narrower gesture. The path is always `<workspace root>/.mlview.toml`,
checked with the same containment rule every other write path in this repo uses; with no folder
open the action refuses and says so. The edit is a **line transform**, never a TOML round-trip: an
existing `[rules]` section keeps its comments, its key order and its CRLF, and an unterminated
array is refused rather than half-written.

**S5 — the boundary conversion stays where §0 put it.** `suppressRule.line` is 1-based like every
`Loc.line`; `src/location.ts` is still the only module that converts to the editor's 0-based
lines (`toEditorLine` / `toGraphLine`), and `test/invariants.test.js` enforces it.

**S6 — three commands, registered but not contributed.** `mlview.copyIgnoreComment`,
`mlview.addIgnoreComment` and `mlview.disableRule` register unconditionally at activation and are
deliberately **absent from `contributes.commands`**: they take arguments and would be broken if
invoked from the palette. The eleven contributed commands are unchanged.

**Gates.** `vscode-extension/test/suppression.test.js` (23 cases: the byte-exact comment against
the analyzer's own `IGNORE_RE`, the TOML transforms, containment, the lightbulb's menu, the
confirm dialog's two answers, and the 1-based conversion through `runSuppression`),
`vscode-extension/test/protocol.test.js` (the message has a sample and survives a JSON round
trip), and one host-level test driving the message through a real panel.

**Nothing about the document changes.** No schema field, no graph key, no analyzer flag — a
suppression takes effect the next time the analyzer runs, exactly as it does from the CLI.

---

### 11.30 The edge-retained issue, and differential fuzzing of the two projections (2026-09-09) — amends §11.2 step 6 and §11.15, contracts-owned

HEALTH-02 asked for a fuzzer over the two `project()` implementations. Building it found a **real divergence on
its first two-hundred cases**, in the one branch §11.2 step 6 does not spell out, so this amendment does two
things: it closes the specification gap, and it makes the fuzzer a gate so the next gap is found by a machine
rather than by a reader.

---

#### A. The edge-retained issue (amends §11.2 step 6)

Step 6 retains an issue when **any** `nodeIds` entry or **any** `edgeIds` entry is in `core`, and then filters
both lists to what survived. It does not say what happens when an issue is retained **through the edge rule**
and every one of its `nodeIds` fell outside `kept`. The two ports answered differently and both answers were
defensible from the text:

| | Python `core/project.py` | TypeScript `webview/src/scope/project.ts` (before this amendment) |
|---|---|---|
| `issue.nodeIds` | the retaining edge's `source`, promoted in | `[]` |
| that node's `issueIds` | gains the issue — the link stays two-way | unchanged |
| no live core edge either | the issue is dropped | kept, with `nodeIds: []` |

`nodeIds: []` breaks graph invariant **1.1.3** (`issue.nodeIds[0]` always names a node in `nodes[]`) and leaves
the renderer with nowhere to draw the badge. The schema cannot catch it, because `Issue.nodeIds` carries no
`minItems`. **The Python behaviour is now normative**, and it is normative in three parts:

| # | Rule |
|---|---|
| **F1** | An issue retained through the edge rule whose `nodeIds` all fell outside `kept` **promotes** the first live retaining edge's `source` — a `core` node by construction, so it is a legal `nodeIds[0]` and needs no rotation — and becomes that issue's whole `nodeIds`. |
| **F2** | The promotion is the one place a projection *adds* an id, so the **reverse link travels with it**: the promoted node's `issueIds` gains the issue id, appended after the filtered ones, and only if the issue survived step 7. A one-way link would break `contracts/validate_sample.py`'s node ↔ issue check in place of invariant 1.1.3, which is not an improvement. |
| **F3** | If there is no live retaining core edge after all, the issue is **dropped**. A retained issue always ends with at least one node. |

No shipped rule can reach this branch today — every rule that cites an edge also cites its two endpoints — but
§11.2 contracts the projection as **total over any schema-valid document**, and `contracts/graph.schema.json`
permits the shape. This is a port fix, not a behaviour change: no document any emitter produces today changes
by one byte, `contracts/graph.sample.json` and `contracts/scope.expected.json`'s sixteen `cases` are untouched,
and `--demo` byte parity is unaffected.

**Mirrors (§11.16).** `webview/src/scope/project.ts` moves in the same change as this file, and
`webview/dist/mlview.js` plus its two synced copies (`tools/sync-assets.py`) are rebuilt with it.

---

#### B. The differential fuzz gate (amends §11.15)

§11.15's battery is 16 selectors over **one** frozen 45-node document. It has never seen a ghost-heavy
document, a disconnected component, a cross-stage parent, an issue anchored on four nodes, an issue anchored on
an edge, or a 400-node graph — which is exactly why A above survived two implementations, a schema, a
ten-group validator and a parity gate. §11.15 is extended with a second, generated battery.

| # | Rule |
|---|---|
| **G1** | `analyzer/tools/scope_fuzz.py` generates documents from a **seed**: node counts 5–500, hierarchy depth, cross-stage parents, ghost density, orphan density, issue arity 1–4, issues anchored on an edge whose nodes sit elsewhere, and 1–3 disconnected components. The same seed reproduces the same run byte for byte, so a failure is replayable from its printed seed. |
| **G2** | Every generated document is checked by `contracts/validate_sample.py` — the schema **and** all ten invariant groups — *before* it is projected. A document that does not validate **fails the run as a generator bug**: the harness must never compare two projections of garbage, and the generator is held to the same standard as the analyzer. |
| **G3** | Selectors are drawn across **every** kind in §11.1 (`all`, `stage:`, `concern:` including its aliases, `file:` exact / basename / case-folded, `unit:` by qualname / bare name / label / case-folded / unmatched, `node:`) at every legal depth (unset, 0, 1, 2), plus the rejected forms — so `ScopeError` parity is fuzzed too, on its contractual triple `{code, term, candidates}` and never on its prose. |
| **G4** | The comparison is the **digest**: the `nodes` / `edges` / `issues` id lists in order, every `issue.nodeIds` and `edgeIds` (so the stable rotation of step 6 is checked), every node's `viewRole` and filtered `issueIds`, each edge's filtered `issueIds`, all eight stage rows, `stats`, and the whole `view`. Written exactly twice — `digest_of` in `analyzer/tools/gen_scope_fixtures.py` and `digestOf` in `webview/test/scope_fuzz.test.mjs` — and those two functions move together. `diagnostics` is deliberately excluded: step 10 appends resolution warnings whose wording §11.1 leaves free. |
| **G5** | Every counterexample is **promoted, not merely reported**: `--promote` minimizes it by delta debugging (each pass proposes random subsets *and* every one-element deletion, and one node process answers them all, so the shrink is geometric: the three promoted so far came from 79-, 115- and 300-node documents and are **3 nodes / 1 edge** each) and appends it to `contracts/scope.cases.json` under a new **`fuzzCases`** array, carrying its own graph inline because it is not the frozen golden. `contracts/scope.expected.json` gains the matching array of digests, generated from the Python side by `gen_scope_fixtures.py` like everything else. The fixture battery **grows**; the fuzzer never replaces it. |
| **G6** | `cases` in both files is untouched by G5, so `webview/test/scope_parity.test.mjs`, `analyzer/tests/core/scope_support.py` and the gate row's "10 projections + 6 error cases" all keep their exact shape. `webview/test/scope_fuzz.test.mjs` replays `fuzzCases` with no Python in the loop. |
| **G7** | The gate is `python tools/verify.py --scopes --fuzz N`, which adds **two** rows: `scopes: promoted` (replay the `fuzzCases`) and `scopes: fuzz` (N fresh graphs). **200 locally** — measured **4.9 s** for both rows on this tree against a 60 s budget — and **2000 nightly**, measured 14.8–17.7 s over five seeds, in `.github/workflows/nightly.yml`. `--fuzz` is inert unless asked for, so `--all` and `--scopes` cost exactly what they cost today. |
| **G8** | The fuzzer must be **proved to bite** whenever its comparison changes: build the viewer from a copy of `webview/src` with one line of `project.ts` removed and aim `MLVIEW_FUZZ_BUNDLE` at it. Dropping the `rotateToCore` call is the reference injection: measured over eight seeds it is caught by **every** one inside 50 cases — earliest at the 2nd generated case, latest at the 28th. This is why the harness takes a bundle path at all — never edit the repository to test the tester. |

**Gates:** `tools/verify.py --scopes --fuzz 200` (new rows `scopes: promoted` and `scopes: fuzz`), `webview/test/scope_fuzz.test.mjs`
(both modes), `analyzer/tools/gen_scope_fixtures.py --check` (now also byte-diffs the promoted expectations),
and `.github/workflows/nightly.yml`. Nothing in `contracts/graph.sample.json`, `contracts/graph.schema.json` or
its mirror changes.

---

### 11.31 `--progress-json` frames (2026-09-09) — amends §3, analyzer-owned

`analysisProgress` is fully specified in `vscode-extension/src/protocol.ts`, listed in
`HOST_TO_UI_TYPES`, and rendered by a working `done / total` bar with a per-file label in
`webview/src/ui/states.ts` — and **no host had ever sent one**, while a 445-file workspace showed
an indeterminate spinner for 5.64 s. This is the core half.

**`--progress-json` on `analyze` and `issues`** writes NDJSON frames to **stderr**, one per
analyzed file:

```
{"t":"progress","done":3,"total":45,"file":"src/train.py"}
```

| # | Rule |
|---|---|
| **H1** | **stdout is never touched.** Progress is a log, and §3's stdout-purity gate (`tests/core/test_stdout_purity.py`) is frozen. The frame is exactly the object above — no spaces, key order `t, done, total, file`, one trailing newline, `file` workspace-relative with forward slashes. |
| **H2** | **The library never opens the sink.** `AnalyzeOptions.progress` is an optional `(done, total, relpath)` callable, **appended last and defaulted to `None`** under the same rule §11.6 used for `scope` and `depth`, so the frozen surface, `frozen=True` and hashability are unchanged. `core/progress.ProgressWriter` is what the CLI passes for `--progress-json`; an in-process host passes its own function and no bytes are written anywhere. `api.analyze()` performs no I/O of its own. |
| **H3** | **Throttled to one frame per 50 ms (`INTERVAL_MS`), with a guaranteed final frame** at `done == total` that the throttle never suppresses — a consumer sees 100% exactly once even when the whole analysis fits inside one interval. |
| **H4** | **A frame can never break an analysis.** A sink that raises is dropped for the rest of the run, silently: one bad frame costs one frame, never an exit code. A progress bar is not worth an exit code. |
| **H5** | `done` counts files whose **parse has completed**, so it is work finished rather than work started, and `total` is the discovered file count after `--max-files`. Frames are emitted only for Python files that reach the parser; a skipped notebook is not a frame (it is already a `notebook_skipped` diagnostic). |

**Nothing else changes.** No schema field, no document key, no exit code, and a run without the
flag emits the bytes it emitted before the flag existed — asserted, not assumed
(`test_without_the_flag_stderr_carries_no_frames`).

**The host half is separate and optional.** `CoreClient.spawn` already buffers stderr line by
line, so a host parses the lines prefixed `{"t":"progress"`, forwards them as
`postAnalysisProgress`, leaves every other stderr line going to the log exactly as today, and
ignores frames arriving after `analysisFailed` for that `requestId`. Passing the flag only when a
panel is live keeps the headless and export paths byte-identical.

**Gates:** `analyzer/tests/core/test_progress.py` (9 cases: the exact frame text, the throttle
driven by a hand-cranked clock, the guaranteed final frame, the raising sink, one call per file,
silence without the flag, and stdout purity under `--json -` with the flag on).

---

### 11.32 Viewer: label placement, accessibility scaffolding, answers and suppression (2026-09-09) — amends §4, §8 and 11.9, renderer-local

Five NEXT-tier items land in `webview/` together — VIEW-03, VIEW-12, MLV-P1, MLV-P10 and CI-ADOPT's rendering
half. Nothing here changes the graph document's *required* shape: every schema field named below is **optional**,
every message is **additive**, and a document, host or saved state predating this amendment renders exactly as it
did before. `contracts/graph.sample.json` is unchanged.

**One message is added to §4 (webview → host).** Both sides still ignore unknown types.

```ts
// Webview → host
| { v: 1; type: 'suppressRule'; code: string; scope: 'workspace';
    action?: 'copy' | 'insert' | 'disable' }
```

| # | Rule |
|---|---|
| **V1** | `suppressRule` is a **request, never an edit**. The viewer writes no file, ever. The host decides: VS Code runs the same `runSuppression` path its lightbulb runs, behind an explicit confirm and never outside the workspace; the standalone report, which has no workspace, answers with the existing copy toast (11.17.1) carrying the `.mlview.toml` snippet. A host predating the message drops it, which leaves the viewer exactly as it was. |
| **V2** | The message carries **both** `scope` and `action`, and both are always sent. `scope` is what the viewer means — workspace-wide, never one file. `action` is the discriminator `vscode-extension/src/protocol.ts` validates against; its `isUiToHost` **rejects** a `suppressRule` without one. The viewer only ever sends `action: 'disable'`: "Copy ignore comment" goes through the generic `copy` message that already owns the clipboard path, and `insert` belongs to the editor's own lightbulb, which has a cursor to insert at. |
| **V3** | The two suppression strings have exactly one definition, `webview/src/ui/suppress.ts`: `ignoreComment(code)` is `# mlview: ignore[<code>]` and `disableSnippet(code)` is `[rules]\n<code> = "off"`. The rail, the Inspector, the group headers and the standalone bridge all read them from there, so no surface can teach a user a syntax the analyzer does not accept. |

**Three optional document fields, and two optional state fields.** The schema mirror for `Issue.change` /
`Issue.baselined` / `answers` belongs to the amendments that emit them (CI-ADOPT, MLV-P1); this clause fixes what
the renderer does with them.

| # | Rule |
|---|---|
| **V4** | `Issue.change` is typed `string` in `webview/src/types.ts`, never narrowed — invariant 1.1/6. `new`, `touched` and `existing` draw a chip; anything else renders unchipped rather than throwing. **Absent means the run was not attributed**, and an unattributed finding is never hidden: the `only changed` filter drops an explicit `existing` and nothing else, which is the documented degradation ("unattributed, showing everything") expressed in the viewer. |
| **V5** | `Issue.baselined` is treated exactly as `suppressed`: **marked, not deleted**. Both are removed from the severity sections by `FilterModel.keep` and both are listed in the rail's collapsed `N suppressed` section, each row carrying its own chip. `FilterModel.keepBase` is `keep` without the suppression and baseline tests, so that section still honours the severity chips, the stage chips and a host's `setFilter` codes. |
| **V6** | `MLGraph.answers` is optional and every field inside it is optional. **Absent means absent**: no card is drawn, never an empty one, and a block carrying two of the four answers draws two rows in the fixed order `dataEntry, objective, evaluation, verdict`. A row whose `confidence` is under **0.6** is marked as low confidence rather than dropped, matching the emitter's own guard. |
| **V7** | An `answers` citation is `{file, line}` — an answer cites a place to look, not a range to select. The viewer completes it into the six fields §4's `openLocation` requires, rebuilding `absFile` from `workspace.root` when the emitter did not write one, so a citation reaches VS Code instead of posting `absFile: undefined`. |
| **V8** | `ViewState` gains `answersOpen?: boolean` and `Filters` gains `changedOnly?: boolean`, both **absent at their defaults** (open, off) exactly as `flow` is absent while on (11.9). `getState()`'s key set is therefore unchanged for a document that uses neither, and an older host round-trips both untouched. |

**VIEW-03 — edge labels are placed, not centred.** `render/edges.ts` drew every label at the route midpoint;
since ~70 % of edges cross a lane, that midpoint *is* the lane seam.

| # | Rule |
|---|---|
| **V9** | A label is anchored to the **longest axis-aligned run of its own route that lies strictly inside one lane band**, where a band is the lane box inset by `LANE_PAD` at the top and the bottom. Horizontal runs are preferred over vertical ones; when no run survives the clip the **outlet-adjacent segment** (the leg leaving the source card) is used and the placement is marked `fallback`. |
| **V10** | **No drawn label may sit within `LANE_PAD` of a lane boundary, overlap a node card, or overlap another drawn label.** One greedy declutter pass, in **document order**, with a **fixed** cap of 20 candidate positions — 10 per run (on the spot, pushed two thirds of the way to each end, pushed all the way to each end, each flipped across the stroke) over the route's runs longest-first. When the cap is reached the label is **hidden**, and its `<g class="mlv-edge">` carries `data-label-hidden="1"` so the drop is auditable rather than silent. |
| **V11** | Only labels drawn **without hovering** — data and control labels at LOD `full`, plus back-edges and merged routes at every zoom, exactly as `styles/edge.css` decides — participate in the collision set and can be hidden by it. A call or config label appears one at a time under the pointer, where it cannot collide with a sibling that is not drawn; it obeys V9 and V10's band and card rules and is never dropped. |
| **V12** | The pass is **pure geometry over (frame, routes)**: no DOM, no text measurement, no randomness, every collection walked in document order. Two runs over the same bytes place every label identically — the parity and golden-render gates depend on it. The label box model is calibrated against Chromium's measured ink (13.68 px tall, sitting ~1 px above the declared `y` at 10 px), because a model smaller than the ink enforces `LANE_PAD` against a box nobody draws. |
| **V13** | The severity marker is walked **along its own polyline** until its disc clears the label box, instead of being centred on the same point. The label keeps the anchor it earned; a glyph anywhere on its own stroke still reads as belonging to that edge. |

**VIEW-12 — the scaffolding around the diagram.** The keyboard model *inside* the canvas is unchanged: one focus
stop, `aria-activedescendant` roving, a polite live region.

| # | Rule |
|---|---|
| **V14** | The **skip link is the document's first tab stop** and lands focus on the canvas. It is a real anchor (`href="#<canvas id>"`) whose click is `preventDefault`ed: the report never navigates its own document, not even to a fragment (11.17). |
| **V15** | The canvas is reachable in **≤ 3 presses via the skip link and ≤ 4 without it**. That budget is what fixes the chrome's shape: the toolbar row and the stage-filter row are ONE `role="toolbar"` with arrow-key roving (one tab stop), the search input keeps its own stop because its own arrow keys drive the caret and the results listbox, and **nothing else may be added between them and the canvas**. Anything new that would take a stop there goes *after* the canvas in DOM order — which is why MLV-P1's card is lifted above the canvas with `order: -1` instead of preceding it. |
| **V16** | Exactly **one `h1`**, carrying the workspace name, and a monotonic outline below it: `h2` for the `<main>` diagram region and for the rail, `h3` per rail panel, `h4` for the severity sections and the inspected node, `h5` for that node's subsections. No level is skipped. |
| **V17** | The canvas sits inside a **`<main>`** landmark; the rail stays a sibling `<aside>`. |
| **V18** | The minimap is **`aria-hidden="true"`** — it duplicates a canvas that is already fully navigable — and it moves out of the canvas element to sit **before** it inside `<main>`. An `aria-hidden` subtree may not hold a tab stop, so its in-panel chevron becomes pointer-only (`tabindex="-1"`) and the keyboard's copy of it is a labelled `Minimap` toggle in the toolbar, before the canvas in DOM order. The two stay in step in both directions. |
| **V19** | Node cards carry their own `:focus-visible` ring, at the card's radius. |

**One new empty state.** The rail already told four zeros apart (nothing analysed, nothing wrong, filtered out,
out of scope). A fifth is added: **every finding suppressed**. "No issues match these filters" would be false — no
filter is doing it — and "No issues found" would be a clean bill of health over N suppressions, which is exactly
the failure mode this product is trying to end.

**Mirrors (§11.16).** `webview/src/types.ts` carries the TypeScript copy of `Issue.change`, `Issue.baselined` and
`answers`; the JSON Schema copy belongs to the amendments that emit them, and the two must land in the same
release. `vscode-extension/src/protocol.ts` already validates `suppressRule` and is unchanged by this amendment.

**Gates added** (`webview/npm test`, 300 → 341):

| New gate | Command | Asserts |
|---|---|---|
| Label placement | `node --test test/labels.test.mjs` | On the demo graph: **0** label-label overlaps, **0** labels over cards, **0** labels within `LANE_PAD` of a boundary, 0 hidden — each re-derived by the test from the boxes and rectangles, not self-reported. On a 300-node synthetic: 0 label-label overlaps among the labels drawn at zoom ≥ 0.62. Plus determinism over the same bytes, the marker nudge, and the placement cost against the relayout it rides on. |
| Accessibility scaffolding | `node --test test/a11y.test.mjs` | The tab order to the canvas, the skip link, one `h1`, a monotonic outline, the `main` landmark, the roving toolbar (including that the search box keeps its keys and the stage chips still filter), the `aria-hidden` minimap with its labelled toolbar toggle, and the card focus ring. |
| Suppression, answers and attribution | `node --test test/adopt.test.mjs` | Both actions on every row, on rule group headers and in the Inspector; the exact `copy` text and `suppressRule` shape; the standalone bridge's snippet toast; the collapsed `N suppressed` section including baselined rows; the change chips and the `only changed` filter including the unattributed degradation; the answer card's rows, citations, low-confidence marking, collapse state and its DOM position after the canvas. |

---

### 11.33 Exporting the diagram as a picture: `requestExport` and `exportFile` (2026-09-09) — amends §4 and §5, host-owned

VIEW-07. The diagram cannot leave the tool. There is no SVG, no PNG, no clipboard image and no
print stylesheet, so the picture people actually want — in a PR description, a design doc, an
incident writeup — does not exist. The host cannot fix this alone: the geometry (lane bands, card
rectangles, routed edge paths, resolved theme colours) exists only inside the viewer, once it has
laid the graph out. And a VS Code webview cannot save a file of its own — an `<a download>` in the
sandbox is inert. So the export is **two messages**: the host asks, the viewer renders, the host
writes.

**E1 — two new message types, both additive.** `HOST_TO_UI_TYPES` gains `requestExport`;
`UI_TO_HOST_TYPES` gains `exportFile`:

```ts
// host -> ui
{ v: 1; type: 'requestExport'; kind: 'svg' | 'png'; scope: 'view' | 'all' | 'scope' }

// ui -> host
{ v: 1; type: 'exportFile'; kind: 'svg' | 'png';
  data: string;              // base64 of the FILE's bytes (SVG = base64 of the UTF-8 text)
  suggestedName?: string;    // a BASENAME hint, never a path
  scope?: 'view' | 'all' | 'scope' }   // echoed from requestExport
```

`scope: 'view'` is the current viewport, `'all'` the whole diagram, `'scope'` the active §11.1
scope. §4's rule that an unknown message type is logged and ignored on both sides is unchanged, so
a viewer that implements neither message and a host that implements both still interoperate: the
commands post a request nothing answers, and nothing is written. `exportFile` does **not**
require a preceding `requestExport`: the viewer's own export menu is the primary trigger and the
two commands are the second one, so the host treats both identically. What protects the user is
not provenance but E2 and E3 — every `exportFile` is validated, and every write goes through a
save dialog the user confirms.

**E2 — the host decides what reaches the disk.** `isUiToHost` accepts `exportFile` only when
`kind` is one of the two words, `data` is pure base64 (`^[A-Za-z0-9+/]+={0,2}$`, length a multiple
of 4, no whitespace, no `data:` prefix) of at most **32 MiB decoded** — checked as a character
count, before anything is allocated — and `suggestedName`, when present, is 1–128 characters with
no path separator and no `..`. The writer then refuses bytes that are not the format that was
asked for: the eight-byte PNG signature for `png`, and `<?xml` / `<!DOCTYPE svg` / `<svg` for
`svg`. That check is normative, not defensive tidying: a `.svg` is executable content in a
browser, and the host must never write one it did not recognise. A refused payload never opens a
save dialog.

**E3 — the save is the host's, and it is a dialog.** The host writes only through
`vscode.window.showSaveDialog` (defaulting to the workspace folder, filtered to the one
extension) followed by `vscode.workspace.fs.writeFile`. No path from the viewer is ever written
to: `suggestedName` names the file the dialog OPENS on and nothing else. The bytes written are
byte-identical to the decoded payload — the host never re-encodes a picture it cannot draw.

**E4 — two commands, and they never open a panel.** `mlview.exportSvg` and `mlview.exportPng`
(contributed as `MLView: Export Diagram as SVG` / `... as PNG`) act on the **live** panel: with no
diagram open the command says so. Each asks which projection to draw — whole diagram, current
view, and current scope only while the viewer has reported one — and takes that choice as an
optional command argument so a keybinding can skip the pick. Asking for `'scope'` with no scope
set falls back to `'all'` rather than requesting a picture the viewer would have to refuse.
`requestExport` is **deferrable and needs a graph** (§11.7's queue, like `revealNode` and
`setScope`): a request reaching a webview that has not been given a graph would draw nothing.

**E5 — MCP gains no export, and says so.** §5's `mlview_open_diagram` still takes
`{ path?, graphPath?, out?, scope?, depth? }` and still writes HTML: an MCP server has no
renderer, and inventing one in Python would be a second geometry to keep in step with the viewer —
exactly the drift VIEW-07's own mitigation forbids. The tool result gains one **constant, always
present** optional field:

```
exportHint: "SVG/PNG export is a viewer feature: open reportPath and use the report's
             export menu, or run 'MLView: Export Diagram as SVG'/'... as PNG' in VS Code.
             This tool writes HTML only."
```

and the docstring says the same, so a terminal host asked for "an image of the pipeline" answers
with a path and an instruction rather than a file it did not write. Still **exactly five tools**.

**E6 — what is NOT amended.** `schemaVersion` stays `"1.0"`; nothing in §2 changes;
`contracts/graph.schema.json` and `contracts/graph.sample.json` are untouched — an exported
picture is not a document. §8's renderer API is unchanged here: the SVG serializer, the clipboard
copy and the `@media print` stylesheet are the viewer's half of VIEW-07 and are contracted with
the renderer, including VIEW-07's mandatory mitigation that the SVG and the DOM be driven from
one `LayoutFrame` + `NodeVisual` source. The host asserts nothing about what the picture LOOKS
like — it cannot see it.
