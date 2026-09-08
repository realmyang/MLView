'use strict';
/**
 * End-to-end exercise of the process seam with a REAL Python child process.
 *
 * The MLView analyzer is built by another component and may not be installed yet, so this test
 * stands up a fake `mlview` package on PYTHONPATH that speaks the frozen CLI contract (§3):
 * `--json -` on stdout, logs on stderr, and exit codes 0 / 1 / 3 / 4. That proves the spawn,
 * streaming, parsing, exit-code and cancellation machinery works on this machine, independently
 * of the analyzer's progress. It skips itself when no Python is on PATH.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { api, readSampleGraph } = require('./harness.js');

const { CoreClient, CoreError } = api;

function findPython() {
  for (const candidate of ['python', 'py', 'python3']) {
    try {
      const args = candidate === 'py' ? ['-3', '-c', 'import sys;print(sys.executable)'] : ['-c', 'import sys;print(sys.executable)'];
      const out = execFileSync(candidate, args, { encoding: 'utf8', shell: false, timeout: 15000 });
      const exe = out.trim();
      if (exe) {
        return exe;
      }
    } catch {
      /* try the next one */
    }
  }
  return undefined;
}

const PYTHON = findPython();

const FAKE_MAIN = `import json, os, sys

argv = sys.argv[1:]
sys.stderr.write("fake-analyzer utf8_mode=%d argv=%s\\n" % (sys.flags.utf8_mode, " ".join(argv)))

if "--version" in argv:
    sys.stdout.write(json.dumps({"name": "mlview", "version": "0.1.0", "schemaVersion": "1.0"}))
    raise SystemExit(0)

mode = os.environ.get("MLVIEW_FAKE_MODE", "ok")
if mode == "empty":
    sys.stderr.write("no python files found\\n")
    raise SystemExit(4)
if mode == "internal":
    sys.stdout.write(json.dumps({"error": "boom"}))
    raise SystemExit(3)
if mode == "usage":
    sys.stderr.write("bad option\\n")
    raise SystemExit(1)
if mode == "badjson":
    sys.stdout.write("this is not json")
    raise SystemExit(0)
if mode == "sleep":
    import time
    time.sleep(30)
    raise SystemExit(0)

graph = json.load(open(os.environ["MLVIEW_FAKE_GRAPH"], encoding="utf-8"))
if mode == "badschema":
    graph["schemaVersion"] = "2.0"
if "--html" in argv:
    out = argv[argv.index("--html") + 1]
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("<!DOCTYPE html><html><body>fake report</body></html>")
    sys.stdout.write("wrote report\\n")
    raise SystemExit(0)
sys.stdout.write(json.dumps(graph))
raise SystemExit(0)
`;

let tmpDir;
let graphFile;
const logLines = [];

const log = {
  channel: { appendLine() {} },
  info: (m) => logLines.push(['info', m]),
  warn: (m) => logLines.push(['warn', m]),
  error: (m) => logLines.push(['error', m]),
  debug: (m) => logLines.push(['debug', m]),
  trace: (m) => logLines.push(['trace', m]),
  raw: (m) => logLines.push(['raw', m]),
  show() {},
  dispose() {}
};

function stubEnv(executable) {
  return {
    resolve: async () => ({
      ok: true,
      interpreter: { executable, args: [], source: 'path', version: [3, 13], hasCore: true }
    })
  };
}

function setup() {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mlview-spawn-'));
  const pkg = path.join(tmpDir, 'pypath', 'mlview');
  fs.mkdirSync(pkg, { recursive: true });
  fs.writeFileSync(path.join(pkg, '__init__.py'), '', 'utf8');
  fs.writeFileSync(path.join(pkg, '__main__.py'), FAKE_MAIN, 'utf8');
  graphFile = path.join(tmpDir, 'graph.json');
  fs.writeFileSync(graphFile, JSON.stringify(readSampleGraph()), 'utf8');
  process.env.PYTHONPATH = path.join(tmpDir, 'pypath');
  process.env.MLVIEW_FAKE_GRAPH = graphFile;
}

function teardown() {
  delete process.env.PYTHONPATH;
  delete process.env.MLVIEW_FAKE_GRAPH;
  delete process.env.MLVIEW_FAKE_MODE;
  if (tmpDir) {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

const settings = { maxFiles: 500, maxNodes: 400, exclude: ['**/legacy/**'] };

test('the analyzer spawn path works end to end against a fake mlview CLI', async (t) => {
  if (!PYTHON) {
    t.skip('no Python interpreter on PATH');
    return;
  }
  setup();
  try {
    const client = new CoreClient(stubEnv(PYTHON), log);
    const request = { scope: 'workspace', paths: [tmpDir], cwd: tmpDir, settings };

    process.env.MLVIEW_FAKE_MODE = 'ok';
    const result = await client.analyze(request);
    assert.equal(result.empty, false);
    assert.equal(result.graph.schemaVersion, '1.0');
    assert.ok(result.graph.nodes.length > 0);
    assert.ok(result.durationMs >= 0);

    // stderr was streamed to the output channel, and -X utf8 really reached the interpreter.
    const streamed = logLines.filter(([level]) => level === 'raw').map(([, m]) => m).join('');
    assert.match(streamed, /fake-analyzer utf8_mode=1/);
    assert.match(streamed, /--json -/);
    assert.match(streamed, /--max-files 500 --max-nodes 400/);
    assert.match(streamed, /--exclude \*\*\/legacy\/\*\*/);

    // exit 4 -> the designed empty state, not an error.
    process.env.MLVIEW_FAKE_MODE = 'empty';
    const empty = await client.analyze(request);
    assert.equal(empty.empty, true);
    assert.equal(empty.graph.nodes.length, 0);
    assert.equal(empty.graph.stages.length, 8);

    // exit 3 -> internal error, surfaced with actions.
    process.env.MLVIEW_FAKE_MODE = 'internal';
    await assert.rejects(
      () => client.analyze(request),
      (err) => {
        assert.ok(err instanceof CoreError);
        assert.equal(err.kind, 'internal');
        assert.ok(err.actions.some((a) => a.id === 'retry'));
        return true;
      }
    );

    // exit 1 -> usage/IO error.
    process.env.MLVIEW_FAKE_MODE = 'usage';
    await assert.rejects(
      () => client.analyze(request),
      (err) => err.kind === 'usage'
    );

    // non-JSON stdout is reported as a parse failure, never as a silent empty diagram.
    process.env.MLVIEW_FAKE_MODE = 'badjson';
    await assert.rejects(
      () => client.analyze(request),
      (err) => err.kind === 'parse'
    );

    // a major schema bump is refused with both versions named.
    process.env.MLVIEW_FAKE_MODE = 'badschema';
    await assert.rejects(
      () => client.analyze(request),
      (err) => {
        assert.equal(err.kind, 'schema');
        assert.match(err.message, /2\.0/);
        assert.match(err.message, /1\.0/);
        return true;
      }
    );

    client.dispose();
  } finally {
    teardown();
  }
});

test('cancellation kills the child process', async (t) => {
  if (!PYTHON) {
    t.skip('no Python interpreter on PATH');
    return;
  }
  setup();
  try {
    const client = new CoreClient(stubEnv(PYTHON), log);
    process.env.MLVIEW_FAKE_MODE = 'sleep';
    const token = {
      isCancellationRequested: false,
      onCancellationRequested: (cb) => {
        const timer = setTimeout(cb, 300);
        return { dispose: () => clearTimeout(timer) };
      }
    };
    const started = Date.now();
    await assert.rejects(
      () =>
        client.analyze({ scope: 'workspace', paths: [tmpDir], cwd: tmpDir, settings, token }),
      (err) => err instanceof CoreError && err.kind === 'cancelled'
    );
    assert.ok(Date.now() - started < 20000, 'the 30 s sleep was actually killed');
    client.dispose();
  } finally {
    teardown();
  }
});

test('exportHtml writes the report through the same CLI', async (t) => {
  if (!PYTHON) {
    t.skip('no Python interpreter on PATH');
    return;
  }
  setup();
  try {
    const client = new CoreClient(stubEnv(PYTHON), log);
    process.env.MLVIEW_FAKE_MODE = 'ok';
    const outFile = path.join(tmpDir, 'report.html');
    const written = await client.exportHtml({
      scope: 'workspace',
      paths: [tmpDir],
      cwd: tmpDir,
      settings,
      outFile
    });
    assert.equal(written, outFile);
    assert.match(fs.readFileSync(outFile, 'utf8'), /fake report/);
    client.dispose();
  } finally {
    teardown();
  }
});
