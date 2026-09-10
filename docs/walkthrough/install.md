# Install the MLView analyzer

MLView is two halves. This extension **transports and draws**; it contains no analysis of its
own. Everything it knows about your Python comes out of one command:

```
python -X utf8 -m mlview analyze <paths> --json -
```

So the first thing to get right is *which interpreter runs that*.

**Run `MLView: Select Python Interpreter`** and pick an environment that has the analyzer. If
you have none yet:

```
pip install mlview
```

You do not have to. A copy of the analyzer ships inside the extension, and MLView falls back to
it when the chosen interpreter has no `mlview` on its path — the status-bar tooltip always says
which of the two produced the numbers you are looking at, so the two can never be confused.

Nothing is imported, executed or sent anywhere. The analysis is `ast`-level static analysis of
files on disk, in a subprocess, on your machine.

> **Restricted Mode.** Analysis spawns an interpreter, so it is disabled until you trust the
> folder. That refusal is enforced at the one place in the extension that starts a process, not
> at a caller — there is no code path that analyses an untrusted workspace.
