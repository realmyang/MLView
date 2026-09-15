# Security Policy

MLView reads Python source code you point it at and draws a picture of it. The
first half of this page is what that costs you, in detail, because a static
analyzer that people run over unfamiliar repositories has to be explicit about
it. The second half is how to report something.

## What MLView does with your code

**It never runs it.** The analyzed program is never imported, executed,
`exec`ed, `eval`ed or `compile`d. This is the first clause of the contract
(`docs/CONTRACTS.md` §1, *No execution*) and it is not a promise in prose: the
core is parsed with `ast` by `analyzer/tests/core/test_no_exec.py`, which walks
every module under `analyzer/src/mlview/` and fails on a call to `exec`,
`eval`, `compile` or `__import__`, on `importlib.import_module` outside
`analyzer/src/mlview/rules/registry.py` (which imports *our* rule modules,
never yours), and on an import of `socket`, `urllib`, `requests`, `http`,
`ftplib`, `subprocess`, `telnetlib` or `smtplib`. Your code is text that gets
parsed, and nothing else. Analysing a repository with no ML framework installed
works exactly as well as analysing one with torch installed — which is also why
a machine with neither is a *better* test of MLView, not a worse one.

**It makes no network connection.** The same test forbids the modules that
could. The standalone HTML report is one self-contained file with the CSS, the
script and the graph JSON inlined; opening it issues no network request. The
one place in the repository that reaches the network is the developer gate
`tools/public_corpus.py fetch`, which clones third-party repositories pinned to
exact commits in `analyzer/tests/public_corpus/repos.json` into a git-ignored
directory outside the package. It is not part of the analyzer and nothing a
user runs invokes it.

**It launches one program, and only one.** `analyzer/src/mlview/adopt/gitdiff.py`
runs `git diff` so that `--changed-since` can attribute findings to a revision
range. That is the single module in the core allowed to import `subprocess`,
and `test_no_exec.py` asserts the argv literally begins with `"git"`, never
interpolates analyzed source, and never uses a shell.

**It reads configuration with `tomllib` and nothing else.** `.mlview.toml` (or
`[tool.mlview]` in your `pyproject.toml`) is parsed by the standard library's
TOML reader. No YAML file, no Hydra config and no `.py` settings module is ever
opened as configuration, however clearly the analyzed project treats it as one
(`docs/CONTRACTS.md` §3.7, §5.5).

**It does not write into the project you analyzed.** The parse cache is on by
default and lives in *your* cache directory (`$XDG_CACHE_HOME/mlview` or the
platform equivalent; `MLVIEW_CACHE_DIR` overrides it, `MLVIEW_NO_CACHE=1` or
`--no-cache` turns it off). `git status` in the repository you analyzed should
be unchanged after a run; if it is not, that is a bug worth reporting under the
heading below. Cache sidecars are JSON, never executable, and are authenticated
with an HMAC over a secret stored in your home directory
(`~/.mlview/cache.key`, mode 0600) and never in the analyzed project — so a
repository that ships a crafted sidecar cannot forge one, and a payload whose
MAC does not verify is discarded rather than trusted. Without that, a
hand-written sidecar could mark a file as uninteresting and quietly delete
findings.

**The analyzer has no runtime dependencies.** `pyproject.toml` declares
`dependencies = []`; the wheel is the standard library plus MLView. The MCP
server in `claude-plugin/` is the exception and needs the official `mcp` SDK,
which it does not vendor.

**Where a link can leave the sandbox.** The standalone report offers to jump
into your editor by handing a `vscode://file/...` URL to the operating system.
That is a deliberate handoff to a locally installed editor, it happens only on
a click, and a report opened over `http(s)` or inside the VS Code panel never
launches at all — it copies `file:line` to the clipboard and says so.

## Threat model, stated plainly

MLView's inputs are untrusted by construction: source files, notebooks and one
TOML file, all parsed and none executed. The failure modes worth reporting are
therefore (a) anything that makes MLView execute, import or shell out to
analyzed content, (b) anything that makes it write outside its cache directory
or the output path you named, (c) anything that makes it open a network
connection, (d) a crafted input that makes it consume unbounded memory or time
rather than failing with a diagnostic, and (e) anything in the emitted HTML
report that executes attacker-controlled content from the analyzed repository —
a filename, a docstring or a code snippet that escapes the JSON block or the
DOM text it is written into. The report escapes `</` as `<\/` inside its
embedded graph for exactly this reason (`docs/CONTRACTS.md` §9); a way around
that is a real vulnerability.

What is **not** a vulnerability: a wrong finding, a missed finding, or a
finding MLView reports on code you consider correct. Those are accuracy bugs
and they matter a great deal — please file a *false positive report* or a *bug
report* issue instead, which is where they will actually get fixed.

## Supported versions

| Version | Supported |
|---|---|
| `main` (the tip) | Yes — fixes land here |
| 0.1.0, pre-release | Yes, through `main` |
| Anything older | No |

MLView is pre-1.0 and has not been published to PyPI, the VS Code Marketplace,
Open VSX or any plugin marketplace; the only distribution is this repository.
There are no release branches to backport to, so a fix goes to `main` and the
next tag carries it.

## Reporting a vulnerability

Please report privately first, and give the maintainer a reasonable window to
fix it before disclosing.

1. **If the repository's Security tab offers *Report a vulnerability*,** use it:
   GitHub private vulnerability reporting creates a draft advisory only the
   maintainer can see, and it is the best route there is. It is a per-repository
   setting rather than something this file can turn on, so check for the button
   before relying on it — if it is not there, it is not enabled yet and step 2
   is the route.
2. **Otherwise:** open a normal issue on
   <https://github.com/realmyang/MLView/issues> saying *only* that you have a
   security report and how you would like to be contacted. **Do not put the
   details, the proof of concept or the affected input in a public issue.** The
   maintainer will open a private channel from there.

There is no security email address for this project, and inventing one here
would be worse than saying so.

**What helps.** The MLView version (`python -m mlview --version`), the host
(CLI, standalone report, VS Code extension, Claude Code plugin), your OS and
Python version, the smallest input that reproduces it, and what you expected to
happen instead. A minimal reproducer that is itself harmless — a file that
*would* have been executed rather than one that does damage — is ideal.

**What to expect.** This is a single-maintainer project with no service-level
agreement. You should get an acknowledgement, a fix or a clear "this is not
something I can fix, and here is why", and credit in the advisory and the
changelog unless you ask not to be named.
