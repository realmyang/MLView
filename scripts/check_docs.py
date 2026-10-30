#!/usr/bin/env python3
"""Check relative links in every tracked Markdown file, and LF in the shell scripts.

Every Markdown file that git tracks is checked; no document is exempt. A relative
link outside a fenced code block must point at a file or folder that exists
under the name the link gives, also on a file system that ignores case. A
fence is a line of three or more backticks or tildes. Markdown allows at most
three spaces before it, counted from where the text of a list item starts.
The check does not follow list items, so it reads a page twice: with a fence
after at most three spaces from the start of the line, and with a fence at
any indentation. A link is checked when one of the two readings finds it
outside a fenced code block. A link after a fence that no line closes is
read. The
links that are read are inline links and pictures, the outer link of a linked
picture, reference definitions, and the href, src and srcset attributes of
HTML, with or without quotes around the value. A link that names a heading of a Markdown file, as file.md#heading or as
#heading, must name a heading that the file has. A line is a heading only
when neither reading takes it for a line of a fenced code block. An address in an issue form
under .github/ISSUE_TEMPLATE that leads to a file or a folder of this
repository must name a path that exists; the repository is the one that the
manifest vscode-extension/package.json names, and its owner and name are
compared without regard to case. scripts/*.sh must use LF line endings. Outside a git checkout the Markdown files
are found by walking the folder instead. Finding no Markdown file to check is a
failure.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
# Folders the walk outside a git checkout does not enter.
SKIPPED = frozenset({".git", "node_modules", ".mlview", ".venv", ".pytest_cache"})
# The end of a link's text and its target: `](target)` or `](target "title")`. Read from the closing
# bracket, so the outer link of a linked picture and a text that holds brackets are read too.
LINK = re.compile(r"\]\(\s*<?([^\s)>]+)>?(?:\s+[^)]*)?\)")
# A reference definition, `[name]: target`. A footnote, `[^name]: text`, is not one.
REFERENCE = re.compile(r"^ {0,3}\[(?!\^)[^\]]+\]:\s*<?([^\s>]+)", re.M)
# An address in an attribute of HTML: a value in double quotes, in single quotes or without quotes.
# `srcset` holds several, each with an optional size after it.
ATTRIBUTE = re.compile(r"""\b(href|src|srcset)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""", re.I)
# A line that opens or closes a fenced code block: three or more backticks or tildes, then the rest.
# Markdown allows at most three spaces before a fence, counted from where the text of a list item
# starts, and the check does not follow list items. FENCE counts the spaces from the start of the line:
# it is right outside a list item. DEEP_FENCE takes a fence at any indentation: it sees the fences of a
# list item, and a line that closes one further in than three spaces.
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)$")
DEEP_FENCE = re.compile(r"\s*(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r" {0,3}#{1,6}[ \t]+(.*?)[ \t]*$")
# Emphasis written with underscores. An underscore inside a word is part of the word.
EMPHASIS = re.compile(r"(?<![\w\\])_+([^_\s](?:[^_]*[^_\s])?)_+(?!\w)")
ADDRESS = re.compile(r"https?://[^\s<>()\[\]\"']+")
# The issue forms, and the manifest that names the project's repository.
FORMS = ".github/ISSUE_TEMPLATE"
MANIFEST = "vscode-extension/package.json"
NOTHING_TO_CHECK = "no Markdown file to check (in a git checkout only tracked files are checked)"
# Variables that point git at another repository, index, object store or work tree. Git sets
# some of them when it runs a hook. The check reads the folder it is given, so it drops them.
GIT_REDIRECTS = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_PREFIX",
})


def git(*arguments: str, cwd: Path) -> str:
    """Run git in cwd and return what it printed. GIT_REDIRECTS are taken out of its environment."""
    environment = {name: value for name, value in os.environ.items() if name not in GIT_REDIRECTS}
    done = subprocess.run(["git", *arguments], cwd=cwd, env=environment, capture_output=True, check=True)
    return done.stdout.decode("utf-8")


def tracked_markdown(root: Path) -> list[str] | None:
    """The Markdown files git tracks under root, or None when root is not the top of a work tree."""
    try:
        # A folder inside some other checkout is not that checkout: it is walked.
        if not os.path.samefile(git("rev-parse", "--show-toplevel", cwd=root).strip(), root):
            return None
        listed = git("ls-files", "-z", "--", "*.md", cwd=root)
    except (OSError, subprocess.CalledProcessError):
        return None
    return sorted(path for path in listed.split("\0") if path)


def walked_markdown(root: Path) -> list[str]:
    """Every Markdown file under root, found by a walk that skips SKIPPED."""
    found = []
    for folder, folders, files in os.walk(root):
        folders[:] = [name for name in folders if name not in SKIPPED]
        found.extend((Path(folder) / name).relative_to(root).as_posix() for name in files if name.endswith(".md"))
    return sorted(found)


def documents(root: Path = ROOT) -> list[str]:
    """The Markdown files to check, as paths relative to root."""
    tracked = tracked_markdown(root)
    return walked_markdown(root) if tracked is None else tracked


def unfenced(text: str, to_the_end: bool = True, pattern: re.Pattern[str] = FENCE) -> str:
    """The text with the lines of every fenced code block emptied.

    A fence opens with three or more backticks or tildes after at most three spaces, or at any
    indentation when the pattern is DEEP_FENCE. It closes with at least as many of the same character
    on a line that holds nothing else. A fence that no line closes runs to the end of the text, as
    Markdown reads it. With to_the_end false such a fence hides its opening line only, and the lines
    after it are read as the text was read before it.
    """
    source = text.split("\n")
    lines: list[str] = []
    start = 0
    while start < len(source):
        fence, opened = "", start
        read = []
        for number in range(start, len(source)):
            match = pattern.match(source[number])
            if fence:
                if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                    fence = ""
                read.append("")
            elif match and not (match[1][0] == "`" and "`" in match[2]):
                fence, opened = match[1], number
                read.append("")
            else:
                read.append(source[number])
        if not fence or to_the_end:
            lines += read
            break
        # No line closes this fence: keep what was read up to its opening line, and read on after it.
        lines += read[:opened - start + 1]
        start = opened + 1
    return "\n".join(lines)


def unfenced_both(text: str) -> str:
    """The text with every line emptied that one of the two readings takes for a line of a fenced code block.

    What is left stands outside a fenced block in both readings. Headings are read from it, so that a
    line of a fenced block of a list item does not give a page a heading that it does not have. Where the
    readings differ, a heading that only one of them leaves is not read, and a link to it is reported.
    """
    shallow, deep = unfenced(text).split("\n"), unfenced(text, pattern=DEEP_FENCE).split("\n")
    return "\n".join(line if line == other else "" for line, other in zip(shallow, deep))


def targets(text: str) -> list[str]:
    """Every link target that one of two readings of a Markdown text finds outside a fenced code block.

    The first reading takes a fence after at most three spaces, and a fence that no line closes hides
    its opening line only: a missing closing line must not hide the links of the rest of a page. The
    second reading takes a fence at any indentation, as a list item can hold one. The check does not
    follow list items and cannot tell which reading is right, so a link is left out only when both
    readings hide it. Neither reading is right where a list item ends inside a fenced block: Markdown
    ends the block with the item, and both readings go on to the next fence. The targets of the first
    reading come first, then those that only the second finds.
    """
    found = links(unfenced(text, to_the_end=False))
    for target in links(unfenced(text, pattern=DEEP_FENCE)):
        if target not in found:
            found.append(target)
    return found


def links(text: str) -> list[str]:
    """Every link target of a text, fenced code blocks included.

    Inline links and pictures come first, in their order, then reference definitions, then the href, src
    and srcset attributes of HTML.
    """
    found = [match[1] for match in LINK.finditer(text)] + REFERENCE.findall(text)
    for match in ATTRIBUTE.finditer(text):
        value = next(group for group in match.groups()[1:] if group is not None)
        if match[1].lower() == "srcset":
            found += [candidate.split()[0] for candidate in value.split(",") if candidate.split()]
        else:
            found.append(value.strip())
    return [target for target in found if target]


def anchors(text: str) -> set[str]:
    """The anchors that GitHub gives the headings of a Markdown text.

    A line is a heading only when neither reading of the fences takes it for a line of a fenced code block.
    """
    found: set[str] = set()
    counts: dict[str, int] = {}
    for line in unfenced_both(text).splitlines():
        match = HEADING.match(line)
        if not match:
            continue
        # A link counts by its text; code and emphasis marks are not part of the title.
        title = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", match[1])
        # Text in a code span keeps its underscores; elsewhere a pair of them is emphasis.
        spans = re.split(r"(`[^`]*`)", title)
        title = "".join(span if span.startswith("`") else EMPHASIS.sub(r"\1", span) for span in spans)
        title = re.sub(r"[`*]", "", title).strip().lower()
        slug = re.sub(r"[^\w\- ]", "", title).replace(" ", "-")
        seen = counts.get(slug, 0)
        counts[slug] = seen + 1
        found.add(f"{slug}-{seen}" if seen else slug)
    return found


def in_tree(root: Path, path: str, folder: bool) -> bool:
    """Whether root holds the path, spelled as it is given: a file system that ignores case does not decide."""
    current = root
    for part in PurePosixPath(path).parts:
        if not current.is_dir() or part not in os.listdir(current):
            return False
        current = current / part
    return current.is_dir() if folder else current.is_file()


def held(root: Path, target: Path) -> bool:
    """Whether a link's target exists under the name the link gives.

    Under root the spelling decides, also on a file system that ignores case. A target outside root is
    looked up as the file system answers.
    """
    try:
        inside = Path(os.path.normpath(target)).relative_to(Path(os.path.normpath(root))).as_posix()
    except ValueError:
        return target.exists()
    return in_tree(root, inside, False) or in_tree(root, inside, True)


def repository(root: Path) -> str | None:
    """The address of the project's repository, as the extension's manifest gives it."""
    try:
        url = json.loads((root / MANIFEST).read_text(encoding="utf-8"))["repository"]["url"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(url, str) or not url:
        return None
    return url[:-len(".git")] if url.endswith(".git") else url


def project_file(address: str, project: str) -> tuple[str, str, str] | None:
    """For an address of a file or a folder of the project: its kind, its path and the heading it names.

    The kind is blob, tree or raw. The host and the repository's owner and name are compared without regard to case,
    as GitHub reads them. raw.githubusercontent.com serves the files of a repository on github.com.
    Any other address gives None.
    """
    home, there = urlsplit(project), urlsplit(address)
    base = [part.lower() for part in home.path.strip("/").split("/")]
    parts = there.path.split("/")[1:]
    if [part.lower() for part in parts[:len(base)]] != base:
        return None
    rest = parts[len(base):]
    host = there.netloc.lower()
    if host == home.netloc.lower() and rest[:1] and rest[0] in ("blob", "tree", "raw"):
        kind, rest = rest[0], rest[1:]
    elif host == "raw.githubusercontent.com" and home.netloc.lower() == "github.com":
        kind = "raw"
    else:
        return None
    # The branch or tag comes first, then the path.
    return kind, unquote("/".join(rest[1:])), there.fragment


def form_problems(root: Path) -> list[str]:
    """Addresses of the issue forms that lead to a file or a folder of this repository which the tree does not hold."""
    project = repository(root)
    folder = root / FORMS
    problems: list[str] = []
    if project is None or not folder.is_dir():
        return problems
    for form in sorted(path for pattern in ("*.yml", "*.yaml") for path in folder.glob(pattern)):
        relative = form.relative_to(root).as_posix()
        # A full stop or a comma after an address ends the sentence, not the address.
        for address in sorted({found.rstrip(".,;:") for found in ADDRESS.findall(form.read_text(encoding="utf-8"))}):
            found = project_file(address, project)
            if found is None:
                continue
            kind, named, fragment = found
            if not in_tree(root, named, kind == "tree"):
                problems.append(f"{relative}: {address} names a path that is not in the tree: {named}")
            elif kind == "blob" and fragment and named.endswith(".md") \
                    and fragment not in anchors((root / named).read_text(encoding="utf-8")):
                problems.append(f"{relative}: {address} names a heading that {named} does not have: #{fragment}")
    return problems


def run(root: Path = ROOT) -> tuple[list[str], list[Path]]:
    problems = []
    files = []
    headings: dict[Path, set[str]] = {}
    relatives = documents(root)
    if not relatives:
        # A run that checked nothing must not read as a pass.
        problems.append(NOTHING_TO_CHECK)
    for relative in relatives:
        path = root / relative
        if not path.is_file():
            problems.append(f"missing document: {relative}")
            continue
        files.append(path)
        # Fenced examples may intentionally show placeholders, not live links.
        for target in targets(path.read_text(encoding="utf-8")):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                continue
            # A link without a path names a heading of the file it stands in.
            resolved = path.parent / unquote(parsed.path) if parsed.path else path
            if not held(root, resolved):
                problems.append(f"{relative}: dead local link {target}")
                continue
            if not parsed.fragment or resolved.suffix != ".md" or not resolved.is_file():
                continue
            if resolved not in headings:
                headings[resolved] = anchors(resolved.read_text(encoding="utf-8"))
            if unquote(parsed.fragment) not in headings[resolved]:
                problems.append(f"{relative}: no heading for {target}")
    problems += form_problems(root)
    for path in sorted((root / "scripts").glob("*.sh")):
        files.append(path)
        if b"\r" in path.read_bytes():
            problems.append(f"{path.relative_to(root)}: shell script must use LF")
    return problems, files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    problems, files = run(args.root)
    for problem in problems:
        print("FAIL: " + problem)
    if not problems and not args.quiet:
        scripts = sum(path.suffix == ".sh" for path in files)
        print(f"DOC CHECK OK: {len(files) - scripts} Markdown files and {scripts} shell scripts")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
