"""The link check reads every tracked Markdown file and reports each dead relative link.

It also reports a link to a heading that the file does not have, and an address in an issue form
that leads to a path which the repository does not hold. The two Markdown files that the extension
package carries keep rules of their own, tested here.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

spec = importlib.util.spec_from_file_location("check_docs", Path(__file__).with_name("check_docs.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Documents that must exist and be checked. A change that renames or removes one edits this list.
REQUIRED = (
    "README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
    "THIRD_PARTY_NOTICES.md", ".github/PULL_REQUEST_TEMPLATE.md",
    "docs/user-guide.md", "docs/format.md", "docs/architecture.md", "docs/development.md",
    "docs/releasing.md", "docs/validation.md",
    "contracts/README.md", "contracts/conformance/README.md",
    "webview/README.md", "vscode-extension/README.md", "claude-plugin/README.md", "samples/README.md",
    "skills/mlview/SKILL.md", "skills/mlview/references/WORKFLOW_CONTRACT.md",
    "skills/mlview/references/coverage-obligations.md",
    "skills/mlview/references/notebooks-and-configuration.md",
    "skills/mlview/references/training-state.md",
)
# Every other Markdown file that the repository tracks: the copies that a command writes, and two pages
# that stand beside the files they describe. A new page is added to one of the two lists.
OTHER = (
    "claude-plugin/skills/mlview/SKILL.md", "claude-plugin/skills/mlview/references/WORKFLOW_CONTRACT.md",
    "claude-plugin/skills/mlview/references/coverage-obligations.md",
    "claude-plugin/skills/mlview/references/notebooks-and-configuration.md",
    "claude-plugin/skills/mlview/references/training-state.md",
    "vscode-extension/CHANGELOG.md", "vscode-extension/THIRD_PARTY_NOTICES.md",
    "contracts/conformance/documents/README.md", "samples/configured_training/README.md",
)
# GitHub shows this page under the title of a pull request, so its headings start at the second level.
UNTITLED = ".github/PULL_REQUEST_TEMPLATE.md"
# What the check reports when it found no Markdown file.
NOTHING = "no Markdown file to check (in a git checkout only tracked files are checked)"


def checked_markdown():
    return {path.relative_to(module.ROOT).as_posix() for path in module.run()[1] if path.suffix == ".md"}


def git(*arguments, cwd):
    """Run git in cwd, as the check does: no variable in the environment sends it to another repository."""
    return module.git(*arguments, cwd=cwd)


def test_current_tree_links():
    assert not module.run()[0]


def tracked_markdown_or_skip():
    try:
        top = git("rev-parse", "--show-toplevel", cwd=module.ROOT).strip()
        tracked = {path for path in git("ls-files", "-z", "--", "*.md", cwd=module.ROOT).split("\0") if path}
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("the tree is not a git checkout")
    if not os.path.samefile(top, module.ROOT):
        # git answers for the checkout around the copy, and lists nothing here. The check walks such a copy.
        pytest.skip("the tree is a copy inside another git checkout")
    return tracked


def document_problem(text, titled=True):
    """What a document lacks: a heading of the first level (of any level when titled is false), or text that is not a heading."""
    if text.startswith("---\n"):
        # A front matter, as the skill's page has one, is neither a heading nor text.
        text = text.partition("\n---\n")[2]
    lines = [line for line in module.unfenced_both(text).splitlines() if line.strip()]
    headings = [line for line in lines if module.HEADING.match(line)]
    if not any(re.match(r" {0,3}#[ \t]", line) for line in headings) and (titled or not headings):
        return "has no heading of the first level" if titled else "has no heading"
    if len(lines) == len(headings):
        return "has no text besides its headings"
    return None


def test_required_documents_exist_and_are_checked():
    assert set(REQUIRED) <= checked_markdown()


def test_each_required_document_has_a_title_and_text():
    problems = []
    for name in REQUIRED:
        problem = document_problem((module.ROOT / name).read_text(encoding="utf-8"), titled=name != UNTITLED)
        if problem:
            problems.append(f"{name} {problem}")
    assert not problems, "\n".join(problems)


def test_what_a_required_document_must_hold():
    assert document_problem("# Title\n\nA sentence.\n") is None
    assert document_problem("---\nname: page\n---\n\n# Title\n\nA sentence.\n") is None
    assert document_problem("## Change\n\n- An item.\n", titled=False) is None
    for empty in ("", "\n\n", "A sentence without a heading.\n", "## Only a second level\n\nA sentence.\n",
                  "```md\n# A heading in a fenced block\n```\n\nA sentence.\n", "---\nname: page\n---\n",
                  # A fenced block of a list item, where the fence stands after five spaces.
                  "- An item.\n     ```md\n  # A heading in a fenced block\n     ```\n\nA sentence.\n"):
        assert document_problem(empty) == "has no heading of the first level", empty
    assert document_problem("A sentence without a heading.\n", titled=False) == "has no heading"
    for bare in ("# Title\n", "# Title\n\n## Part\n\n### Detail\n", "# Title\n\n```sh\nls\n```\n",
                 "---\nname: page\n---\n# Title\n"):
        assert document_problem(bare) == "has no text besides its headings", bare
    assert document_problem("## Change\n\n## Checks\n", titled=False) == "has no text besides its headings"


def test_every_tracked_markdown_file_is_checked():
    assert checked_markdown() == tracked_markdown_or_skip()


def test_the_tracked_markdown_files_are_the_listed_ones():
    # A page that nobody listed fails here, and so does a listed page that the tree does not hold.
    assert not set(REQUIRED) & set(OTHER)
    assert sorted(tracked_markdown_or_skip()) == sorted(REQUIRED + OTHER)


def test_broken_link_and_shell_crlf_are_rejected(tmp_path):
    (tmp_path / "README.md").write_text("[missing](missing.md)\n[web](https://example.com)\n")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "test.sh").write_bytes(b"#!/bin/sh\r\n")
    problems, _ = module.run(tmp_path)
    assert len(problems) == 2
    assert any("dead local link" in p for p in problems)
    assert any("LF" in p for p in problems)


def test_relative_encoded_link_resolves_and_every_document_in_the_folder_is_checked(tmp_path):
    (tmp_path / "README.md").write_text("[file](a%20file.md#part)\n")
    (tmp_path / "a file.md").write_text("# Part\n")
    assert not module.run(tmp_path)[0]
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "guide.md").write_text("[guide](missing.py)\n")
    assert module.run(tmp_path)[0] == ["notes/guide.md: dead local link missing.py"]


def test_a_link_to_a_heading_that_the_file_does_not_have_is_reported(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n\n## Install\n\n```sh\n# not a heading\n```\n\n## Install\n", encoding="utf-8")
    (tmp_path / "script.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text("# Page\n\n[up](../guide.md#guide) [gone](../guide.md#upgrade)\n", encoding="utf-8")
    held = "[guide](guide.md#install) [again](guide.md#install-1) [here](#title) [line](script.py#L1) [folder](docs#readme)\n"
    (tmp_path / "README.md").write_text("# Title\n\n" + held, encoding="utf-8")
    assert module.run(tmp_path)[0] == ["docs/page.md: no heading for ../guide.md#upgrade"]
    # The spelling of an anchor counts, a line of a fenced block is no heading, and a link without a path
    # names a heading of the file it stands in.
    missing = "[a](guide.md#Install) [b](guide.md#install-2) [c](guide.md#not-a-heading) [d](#nowhere) [e](guide.md#)\n"
    (tmp_path / "README.md").write_text("# Title\n\n" + held + missing, encoding="utf-8")
    assert module.run(tmp_path)[0] == [
        "README.md: no heading for guide.md#Install", "README.md: no heading for guide.md#install-2",
        "README.md: no heading for guide.md#not-a-heading", "README.md: no heading for #nowhere",
        "docs/page.md: no heading for ../guide.md#upgrade",
    ]
    # A link inside a fenced block is not read.
    (tmp_path / "README.md").write_text("# Title\n\n```md\n[gone](guide.md#upgrade)\n```\n", encoding="utf-8")
    assert module.run(tmp_path)[0] == ["docs/page.md: no heading for ../guide.md#upgrade"]


def test_a_link_spelled_in_another_case_is_reported(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n\n## Install\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Title\n\n[a](docs/guide.md) [b](docs/Guide.md) [c](Docs/guide.md#install) [d](docs) [e](DOCS)\n",
        encoding="utf-8")
    # GitHub serves a path under one spelling. A file system that ignores case does not decide.
    readme = [
        "README.md: dead local link docs/Guide.md", "README.md: dead local link Docs/guide.md#install",
        "README.md: dead local link DOCS",
    ]
    assert module.run(tmp_path)[0] == readme
    (tmp_path / "docs" / "page.md").write_text(
        "[up](../README.md) [wrong](../Readme.md) [here](./guide.md) [root](..)\n", encoding="utf-8")
    assert module.run(tmp_path)[0] == readme + ["docs/page.md: dead local link ../Readme.md"]


def test_every_form_of_a_link_is_read(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    forms = [
        "[![A picture](docs/guide.md)](docs/gone-1.md)",
        "[another page][old]\n\n[old]: docs/gone-2.md#nowhere",
        '<a href="docs/gone-3.md">old</a> and <a href="docs/guide.md">new</a>',
        "<img alt='old' src='docs/gone-4.png'>",
        '<picture><source srcset="docs/guide.md 1x, docs/gone-5.png 2x"></picture>',
        "[another page]( docs/gone-6.md )",
        "[the list `a[0]`](docs/gone-7.md)",
        '[another page](docs/gone-8.md "Old")',
        # A footnote is not a reference definition, and an address with a host is not a relative link.
        "A note.[^1]\n\n[^1]: docs/gone-9.md is text, not a target.",
        '<a href="//example.com/docs/gone-10.md">elsewhere</a>',
        # HTML allows a value without quotes.
        "<a href=docs/gone-11.md>gone</a> and <img alt=held src=docs/guide.md>",
        "<img alt=old src=docs/gone-12.png> and <source srcset=docs/gone-13.png>",
    ]
    (tmp_path / "README.md").write_text("# Title\n\n" + "\n\n".join(forms) + "\n", encoding="utf-8")
    assert module.run(tmp_path)[0] == [
        # Inline links in their order, then reference definitions, then the attributes of HTML.
        "README.md: dead local link docs/gone-1.md", "README.md: dead local link docs/gone-6.md",
        "README.md: dead local link docs/gone-7.md", "README.md: dead local link docs/gone-8.md",
        "README.md: dead local link docs/gone-2.md#nowhere", "README.md: dead local link docs/gone-3.md",
        "README.md: dead local link docs/gone-4.png", "README.md: dead local link docs/gone-5.png",
        "README.md: dead local link docs/gone-11.md", "README.md: dead local link docs/gone-12.png",
        "README.md: dead local link docs/gone-13.png",
    ]


def test_a_fence_of_tildes_or_of_more_backticks_hides_links_and_headings(tmp_path):
    (tmp_path / "guide.md").write_text(
        "# Guide\n\n~~~md\n## Not a heading\n[gone](gone-1.md)\n~~~\n\n"
        "````md\n```\n## Nor this\n```\n[gone](gone-2.md)\n````\n\n## After the fences\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "[a](guide.md#not-a-heading) [b](guide.md#nor-this) [c](guide.md#after-the-fences)\n", encoding="utf-8")
    assert module.run(tmp_path)[0] == [
        "README.md: no heading for guide.md#not-a-heading", "README.md: no heading for guide.md#nor-this",
    ]
    # Backticks that open a line and close in it are a code span, not a fence.
    assert module.targets("```like these``` open nothing: [a](one.md)\n\n[b](two.md)\n") == ["one.md", "two.md"]


def test_an_indented_line_of_backticks_or_a_fence_left_open_does_not_hide_the_rest_of_a_page(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n", encoding="utf-8")
    # A line of backticks after four spaces or more, or after a tab, does not hide the links after it. It is
    # indented code, or the fence of a list item, and a fenced block of a list item ends with the item at the latest.
    for indent in ("    ", "      ", "\t"):
        page = f"# Title\n\n- An item.\n\n{indent}```\n\n[gone](docs/gone.md)\n"
        (tmp_path / "README.md").write_text(page, encoding="utf-8")
        assert module.run(tmp_path)[0] == ["README.md: dead local link docs/gone.md"], repr(indent)
    # Up to three spaces open a fence and close it.
    assert module.targets("   ```\n[a](one.md)\n   ```\n[b](two.md)\n") == ["two.md"]
    # A line that is indented further closes a fence of a list item and none outside one. The check does not
    # follow list items, so the link after such a line is read too: it comes last, from the second reading.
    assert module.targets("```\n[a](one.md)\n    ```\n[b](two.md)\n```\n[c](three.md)\n") == ["three.md", "two.md"]
    # In a list item a line that is indented further than the fence can close it, and a link between two such
    # blocks is a link of the page. The first reading takes the two blocks and the link for one block.
    for marker, closing in (("1. ", "    "), ("- ", "    "), ("1. ", "      "), ("- ", "\t")):
        inside = " " * len(marker)
        item = f"{marker}Step\n{inside}```sh\n{inside}code\n{closing}```\n{inside}See [gone](docs/gone.md)\n"
        (tmp_path / "README.md").write_text(f"# Title\n\n{item}{inside}```sh\n{inside}more\n{inside}```\n", encoding="utf-8")
        assert module.run(tmp_path)[0] == ["README.md: dead local link docs/gone.md"], (marker, closing)
    # A target that both readings find is listed once.
    assert module.targets("[a](one.md)\n\n    ```\n[b](two.md)\n") == ["one.md", "two.md"]
    # A fence that no line closes hides its opening line only, so a missing closing line cannot hide the links after it.
    assert module.targets("[a](one.md)\n\n~~~\n[b](two.md)\n") == ["one.md", "two.md"]
    (tmp_path / "README.md").write_text("# Title\n\n```sh\n\n[gone](docs/gone.md)\n", encoding="utf-8")
    assert module.run(tmp_path)[0] == ["README.md: dead local link docs/gone.md"]
    # A block that is closed after such a fence still hides its own links.
    assert module.targets("```sh\n[a](one.md)\n\n~~~\n[b](two.md)\n~~~\n[c](three.md)\n") == ["one.md", "three.md"]
    # Headings are read as Markdown reads them: a fence left open hides them to the end of the text.
    (tmp_path / "guide.md").write_text("# Guide\n\n~~~\n## Not a heading\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("[a](guide.md#guide) [b](guide.md#not-a-heading)\n", encoding="utf-8")
    assert module.run(tmp_path)[0] == ["README.md: no heading for guide.md#not-a-heading"]


def test_a_line_that_one_reading_of_the_fences_takes_for_code_is_no_heading(tmp_path):
    # A line of a fenced block of a list item is no heading, also where the fence stands after four spaces or
    # more and the first reading does not take it for a fence.
    for item in ("- Step\n     ```sh\n  # Not a heading\n     ```\n", "1. Step\n    ```sh\n   # Not a heading\n    ```\n"):
        (tmp_path / "guide.md").write_text("# Guide\n\n" + item + "\n## After the item\n", encoding="utf-8")
        (tmp_path / "README.md").write_text(
            "[a](guide.md#guide) [b](guide.md#not-a-heading) [c](guide.md#after-the-item)\n", encoding="utf-8")
        assert module.run(tmp_path)[0] == ["README.md: no heading for guide.md#not-a-heading"], item
    # Where the two readings differ, the check cannot tell which one is right without following list items. A
    # line that only one of them leaves outside a fenced block is no heading, so a link to it is reported.
    assert module.anchors("# One\n\n```\n# Two\n    ```\n# Three\n```\n# Four\n") == {"one"}
    assert module.unfenced_both("# One\n    ```\ntext\n    ```\n# Two\n") == "# One\n\n\n\n# Two\n"


FORM_PROJECT = "https://github.com/example/project"


def form_tree(root, addresses, url=FORM_PROJECT + ".git"):
    """A small tree with one page, the extension's manifest and an issue-form configuration that holds the addresses."""
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# Guide\n\n## Install\n", encoding="utf-8")
    (root / "README.md").write_text("# Title\n", encoding="utf-8")
    if url is not None:
        (root / "vscode-extension").mkdir()
        (root / "vscode-extension" / "package.json").write_text(
            json.dumps({"repository": {"type": "git", "url": url}}), encoding="utf-8")
    forms = root / ".github" / "ISSUE_TEMPLATE"
    forms.mkdir(parents=True)
    lines = "".join(f"  - name: A page\n    url: {address}\n    about: Where to read more.\n" for address in addresses)
    (forms / "config.yml").write_text("blank_issues_enabled: true\ncontact_links:\n" + lines, encoding="utf-8")
    return root


def test_the_issue_forms_name_paths_that_the_tree_holds():
    assert module.form_problems(module.ROOT) == []
    # The check is not empty: the configuration holds an address of a file of the project.
    project = module.repository(module.ROOT)
    assert project == "https://github.com/realmyang/MLView"
    assert f"{project}/blob/" in (module.ROOT / module.FORMS / "config.yml").read_text(encoding="utf-8")


def test_addresses_that_an_issue_form_may_hold(tmp_path):
    root = form_tree(tmp_path, [
        f"{FORM_PROJECT}/blob/main/docs/guide.md", f"{FORM_PROJECT}/blob/v1.2.3/docs/guide.md#install",
        f"{FORM_PROJECT}/tree/main/docs", f"{FORM_PROJECT}/security/policy", f"{FORM_PROJECT}/issues", FORM_PROJECT,
        # Another repository is not the project's, also when its address begins with the same letters.
        f"{FORM_PROJECT}-two/blob/main/docs/missing.md", "https://example.com/blob/main/missing.md",
    ])
    assert module.repository(root) == FORM_PROJECT
    assert module.form_problems(root) == []
    assert module.run(root)[0] == []


def test_a_wrong_path_in_an_issue_form_is_reported(tmp_path):
    addresses = [
        f"{FORM_PROJECT}/blob/main/docs/missing.md", f"{FORM_PROJECT}/blob/main/docs/Guide.md",
        f"{FORM_PROJECT}/blob/main/docs", f"{FORM_PROJECT}/tree/main/docs/guide.md", f"{FORM_PROJECT}/tree/main/missing",
        f"{FORM_PROJECT}/blob/main", f"{FORM_PROJECT}/blob/main/docs/guide.md#upgrade",
    ]
    root = form_tree(tmp_path, addresses)
    form = ".github/ISSUE_TEMPLATE/config.yml"
    expected = sorted([
        f"{form}: {addresses[0]} names a path that is not in the tree: docs/missing.md",
        # The spelling counts, also where the file system ignores case.
        f"{form}: {addresses[1]} names a path that is not in the tree: docs/Guide.md",
        # A file is not a folder, and a folder is not a file.
        f"{form}: {addresses[2]} names a path that is not in the tree: docs",
        f"{form}: {addresses[3]} names a path that is not in the tree: docs/guide.md",
        f"{form}: {addresses[4]} names a path that is not in the tree: missing",
        f"{form}: {addresses[5]} names a path that is not in the tree: ",
        f"{form}: {addresses[6]} names a heading that docs/guide.md does not have: #upgrade",
    ])
    assert sorted(module.form_problems(root)) == expected
    # The command reports them with the links of the Markdown files.
    assert sorted(module.run(root)[0]) == expected


def test_an_issue_form_address_is_read_in_every_spelling_of_the_repository(tmp_path):
    wrong = {
        # GitHub reads the host and the repository's owner and name without regard to case.
        "https://github.com/Example/PROJECT/blob/main/docs/missing-1.md": "docs/missing-1.md",
        "https://GitHub.com/example/project/tree/main/docs/missing-2": "docs/missing-2",
        "http://github.com/example/project/blob/main/docs/missing-3.md": "docs/missing-3.md",
        # The same file as GitHub serves it raw, from either host.
        "https://raw.githubusercontent.com/example/Project/main/docs/missing-4.md": "docs/missing-4.md",
        "https://github.com/example/project/raw/main/docs/missing-5.md": "docs/missing-5.md",
        # The path keeps its spelling.
        "https://github.com/EXAMPLE/project/blob/main/docs/GUIDE.md": "docs/GUIDE.md",
    }
    right = [
        "https://raw.githubusercontent.com/Example/project/main/docs/guide.md",
        "https://github.com/EXAMPLE/project/blob/main/docs/guide.md#install",
        # Another owner's repository of the same name is not the project's.
        "https://raw.githubusercontent.com/other/project/main/docs/missing.md",
        "https://github.com/other/project/blob/main/docs/missing.md",
    ]
    root = form_tree(tmp_path, list(wrong) + right)
    form = ".github/ISSUE_TEMPLATE/config.yml"
    assert module.form_problems(root) == [
        f"{form}: {address} names a path that is not in the tree: {path}" for address, path in sorted(wrong.items())]


def test_an_issue_form_with_the_long_file_extension_is_read(tmp_path):
    address = f"{FORM_PROJECT}/blob/main/docs/missing.md"
    root = form_tree(tmp_path, [])
    (root / ".github" / "ISSUE_TEMPLATE" / "question.yaml").write_text(f"name: Question\nabout: {address}\n", encoding="utf-8")
    assert module.form_problems(root) == [
        f".github/ISSUE_TEMPLATE/question.yaml: {address} names a path that is not in the tree: docs/missing.md"]


def test_every_issue_form_is_read_and_a_tree_without_a_manifest_has_no_project_address(tmp_path):
    address = f"{FORM_PROJECT}/blob/main/docs/missing.md"
    root = form_tree(tmp_path, [])
    (root / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").write_text(
        f"name: Bug\nbody:\n  - type: markdown\n    attributes:\n      value: See {address}.\n", encoding="utf-8")
    assert module.form_problems(root) == [
        f".github/ISSUE_TEMPLATE/bug_report.yml: {address} names a path that is not in the tree: docs/missing.md"]
    # Without the manifest nothing says which repository is the project's, so no address is checked.
    shutil.rmtree(root / "vscode-extension")
    assert module.repository(root) is None
    assert module.form_problems(root) == []
    (root / "vscode-extension").mkdir()
    (root / "vscode-extension" / "package.json").write_text("{}", encoding="utf-8")
    assert module.repository(root) is None


def test_walk_outside_a_checkout_skips_dependency_and_git_folders(tmp_path):
    (tmp_path / "README.md").write_text("[guide](docs/guide.md)\n")
    for folder in ("docs", "node_modules/package", ".git", ".venv/lib"):
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "guide.md").write_text("[gone](gone.md)\n")
    assert module.documents(tmp_path) == ["README.md", "docs/guide.md"]
    assert module.run(tmp_path)[0] == ["docs/guide.md: dead local link gone.md"]


def test_in_a_checkout_only_tracked_files_are_checked_and_a_missing_one_is_reported(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    git("init", "--quiet", cwd=tmp_path)
    (tmp_path / "README.md").write_text("[guide](guide.md)\n")
    (tmp_path / "guide.md").write_text("# Guide\n")
    (tmp_path / "gone.md").write_text("# Gone\n")
    git("add", "README.md", "guide.md", "gone.md", cwd=tmp_path)
    (tmp_path / "gone.md").unlink()
    (tmp_path / "untracked.md").write_text("[dead](nowhere.md)\n")
    assert module.documents(tmp_path) == ["README.md", "gone.md", "guide.md"]
    assert module.run(tmp_path)[0] == ["missing document: gone.md"]
    # A folder inside the checkout is not its top: it is walked, so the untracked file counts there.
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "note.md").write_text("[dead](nowhere.md)\n")
    assert module.run(inner)[0] == ["note.md: dead local link nowhere.md"]


def test_a_folder_without_a_markdown_file_fails(tmp_path):
    (tmp_path / "notes.txt").write_text("[dead](nowhere.md)\n")
    assert module.run(tmp_path) == ([NOTHING], [])
    assert module.run(tmp_path / "missing") == ([NOTHING], [])


def test_a_checkout_that_tracks_no_markdown_file_fails(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    git("init", "--quiet", cwd=tmp_path)
    (tmp_path / "README.md").write_text("[dead](nowhere.md)\n")
    assert module.documents(tmp_path) == []
    assert module.run(tmp_path)[0] == [NOTHING]


def test_the_command_exits_1_when_there_is_nothing_to_check(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_docs.py", "--root", str(tmp_path)])
    assert module.main() == 1
    assert capsys.readouterr().out == f"FAIL: {NOTHING}\n"
    (tmp_path / "README.md").write_text("# Title\n")
    assert module.main() == 0
    assert capsys.readouterr().out == "DOC CHECK OK: 1 Markdown files and 0 shell scripts\n"


def test_git_variables_in_the_environment_do_not_send_the_check_to_another_repository(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    other, tree = tmp_path / "other", tmp_path / "tree"
    for folder in (other, tree):
        folder.mkdir()
        git("init", "--quiet", cwd=folder)
    (other / "seed.md").write_text("# Seed\n")
    git("add", "seed.md", cwd=other)
    assert module.GIT_REDIRECTS == {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_PREFIX",
    }
    # Git sets such variables for a hook; a caller may have set them too. They name the other repository.
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_COMMON_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(other / ".git" / "objects"))
    monkeypatch.setenv("GIT_PREFIX", "elsewhere/")
    (tree / "README.md").write_text("[guide](guide.md)\n")
    (tree / "guide.md").write_text("# Guide\n")
    git("add", "README.md", "guide.md", cwd=tree)
    assert module.documents(tree) == ["README.md", "guide.md"]
    assert module.run(tree)[0] == []
    # The other repository is as it was: one tracked file, and no object of the tree in its store.
    for name in module.GIT_REDIRECTS:
        monkeypatch.delenv(name, raising=False)

    def plain(*arguments, cwd):
        return subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, check=True).stdout.decode("utf-8")

    assert plain("ls-files", cwd=other) == "seed.md\n"
    assert plain("count-objects", cwd=other).startswith("1 objects")
    assert plain("ls-files", cwd=tree) == "README.md\nguide.md\n"


# The two Markdown files that the extension package carries. VS Code and a marketplace show them
# away from the repository, where a relative link leads somewhere else, and the packaging tool
# turns white space, "#" and digits into a link to an issue. So each address in them is absolute,
# and an address into the project's own repository names the tag of the manifest's version.
# The packaging tool rewrites a link wherever it stands, so a link in a fenced block is read too.
PACKAGED = ("vscode-extension/README.md", "CHANGELOG.md")
MANIFEST = "vscode-extension/package.json"
# The pictures of the documents. Every file under this folder is named by a document, and every picture
# that a document names here is in the tree.
IMAGES = "docs/images/"
ADDRESS = re.compile(r"https?://[^\s<>()\[\]\"']+")
ISSUE = re.compile(r"\s(?:[\w-]+/[\w-]+)?#\d+\b")
RAW_HOST = "raw.githubusercontent.com"


def project_address_problem(address, repository, tag, root):
    """What is wrong with an address into the project's own repository. None for none, and for an address elsewhere.

    GitHub reads the host and the repository's owner and name without regard to case, so they are compared that way.
    """
    home, there = urlsplit(repository), urlsplit(address)
    base = [part.lower() for part in home.path.strip("/").split("/")]
    parts = there.path.split("/")[1:]
    host = there.netloc.lower()
    if host not in (home.netloc.lower(), RAW_HOST) or [part.lower() for part in parts[:len(base)]] != base:
        return None
    if there.scheme != "https":
        return "is not an https address"
    rest = parts[len(base):]
    if host == RAW_HOST:
        kind = "raw"
    else:
        if rest in ([], ["issues"]) and not there.query and not there.fragment:
            return None
        if not rest or rest[0] not in ("blob", "tree", "raw"):
            return "is not the repository, its issues, or a file or a folder at a tag"
        kind, rest = rest[0], rest[1:]
    if rest[:1] != [tag]:
        return f"does not name the tag {tag}"
    path, fragment = unquote("/".join(rest[1:])), there.fragment
    if not path or not module.in_tree(root, path, kind == "tree"):
        return f"names a path that is not in the tree: {path}"
    if fragment and (kind != "blob" or fragment not in module.anchors((root / path).read_text(encoding="utf-8"))):
        return f"names a heading that {path} does not have: #{fragment}"
    return None


def packaged_problems(name, text, repository, tag, root):
    """What breaks the rules for a Markdown file that the extension package carries."""
    problems = []
    for target in module.links(text):
        if not target.startswith("https://"):
            problems.append(f"{name}: {target} is not an https address")
    for match in ISSUE.finditer(text):
        problems.append(f"{name}: {match[0].strip()} would become a link to an issue in the package")
    for address in sorted({found.rstrip(".,;:") for found in ADDRESS.findall(text)}):
        problem = project_address_problem(address, repository, tag, root)
        if problem and f"{name}: {address} {problem}" not in problems:
            problems.append(f"{name}: {address} {problem}")
    return problems


def manifest_repository_and_tag():
    manifest = json.loads((module.ROOT / MANIFEST).read_text(encoding="utf-8"))
    return manifest["repository"]["url"].removesuffix(".git"), "v" + manifest["version"]


def test_the_packaged_markdown_files_hold_only_addresses_that_work_outside_the_repository():
    repository, tag = manifest_repository_and_tag()
    problems = []
    for name in PACKAGED:
        problems += packaged_problems(name, (module.ROOT / name).read_text(encoding="utf-8"), repository, tag, module.ROOT)
    assert not problems, "\n".join(problems)
    # The rule is not empty: the extension's page links the user guide at the tag.
    assert f"{repository}/blob/{tag}/docs/user-guide.md" in (module.ROOT / PACKAGED[0]).read_text(encoding="utf-8")


REPOSITORY, TAG = "https://github.com/example/project", "v1.2.3"


def small_tree(root):
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# Guide\n\n## Install\n\n## Install\n", encoding="utf-8")
    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (root / "docs" / "images").mkdir()
    (root / "docs" / "images" / "overview.png").write_bytes(b"")
    return root


def reported(text, root):
    return packaged_problems("page.md", text, REPOSITORY, TAG, root)


def test_addresses_that_a_packaged_file_may_hold(tmp_path):
    root = small_tree(tmp_path)
    page = (
        f"[home]({REPOSITORY}) [issues]({REPOSITORY}/issues) [guide]({REPOSITORY}/blob/{TAG}/docs/guide.md)\n"
        f"[install]({REPOSITORY}/blob/{TAG}/docs/guide.md#install) [again]({REPOSITORY}/blob/{TAG}/docs/guide.md#install-1)\n"
        f"[folder]({REPOSITORY}/tree/{TAG}/docs) [licence]({REPOSITORY}/blob/{TAG}/LICENSE).\n"
        f"![picture](https://raw.githubusercontent.com/example/project/{TAG}/docs/images/overview.png)\n"
        "[elsewhere](https://example.com/a/b#12) <https://example.com/issues/3> Version 1.2.3, C#7, key #, and # 5.\n"
    )
    assert reported(page, root) == []


def test_a_relative_link_in_a_packaged_file_is_reported(tmp_path):
    root = small_tree(tmp_path)
    assert reported("[guide](docs/guide.md)\n", root) == ["page.md: docs/guide.md is not an https address"]
    assert reported("[install](#install)\n", root) == ["page.md: #install is not an https address"]
    assert reported("![picture](docs/images/overview.png)\n", root) == ["page.md: docs/images/overview.png is not an https address"]
    assert reported("[guide][g]\n\n[g]: docs/guide.md\n", root) == ["page.md: docs/guide.md is not an https address"]
    assert reported("[plain](http://example.com/)\n", root) == ["page.md: http://example.com/ is not an https address"]
    assert reported('<img alt="picture" src="docs/images/overview.png">\n', root) == ["page.md: docs/images/overview.png is not an https address"]


def test_every_form_of_a_link_in_a_packaged_file_is_read(tmp_path):
    root = small_tree(tmp_path)
    guide = f"{REPOSITORY}/blob/{TAG}/docs/guide.md"
    not_https = "page.md: docs/guide.md is not an https address"
    # The outer link of a linked picture, which the packaging tool would point at a branch.
    assert reported(f"[![A picture]({guide})](docs/guide.md)\n", root) == [not_https]
    assert reported("[the guide]( docs/guide.md )\n", root) == [not_https]
    assert reported("[the list `a[0]`](docs/guide.md)\n", root) == [not_https]
    assert reported('<a href="docs/guide.md">the guide</a>\n', root) == [not_https]
    # HTML allows a value without quotes.
    assert reported("<a href=docs/guide.md>the guide</a>\n", root) == [not_https]
    assert reported("<img alt=picture src=docs/guide.md>\n", root) == [not_https]
    assert reported(f'<picture><source srcset="{guide} 1x, docs/guide.md 2x"></picture>\n', root) == [not_https]
    # The packaging tool rewrites a link in a fenced block as it does any other.
    assert reported("```md\n[the guide](docs/guide.md)\n```\n", root) == [not_https]
    assert reported(f'[the guide]({guide}) <a href="{guide}#install">install</a> <img src="{guide}">\n', root) == []
    assert reported(f"<a href={guide}#install>install</a> <img src={guide}>\n", root) == []


def test_a_project_address_is_known_in_every_spelling(tmp_path):
    root = small_tree(tmp_path)
    # GitHub reads the host and the repository's owner and name without regard to case; the path keeps its spelling.
    for address, problem in (
        ("https://github.com/Example/PROJECT/blob/main/docs/guide.md", "does not name the tag v1.2.3"),
        (f"https://GitHub.com/example/project/blob/{TAG}/docs/missing.md", "names a path that is not in the tree: docs/missing.md"),
        (f"https://github.com/EXAMPLE/project/blob/{TAG}/docs/GUIDE.md", "names a path that is not in the tree: docs/GUIDE.md"),
        ("https://RAW.githubusercontent.com/Example/project/main/docs/guide.md", "does not name the tag v1.2.3"),
        ("https://github.com/Example/Project/pulls", "is not the repository, its issues, or a file or a folder at a tag"),
        (f"http://github.com/example/project/blob/{TAG}/docs/guide.md", "is not an https address"),
    ):
        assert reported(f"A bare address: {address}\n", root) == [f"page.md: {address} {problem}"]
    # The same fault in a link is reported once.
    address = f"http://github.com/example/project/blob/{TAG}/docs/guide.md"
    assert reported(f"[the guide]({address})\n", root) == [f"page.md: {address} is not an https address"]
    assert reported(f"[the guide](https://github.com/Example/PROJECT/blob/{TAG}/docs/guide.md#install)\n", root) == []
    assert reported("[other](https://raw.githubusercontent.com/other/project/main/docs/missing.md)\n", root) == []


def test_an_issue_number_in_a_packaged_file_is_reported(tmp_path):
    root = small_tree(tmp_path)
    assert reported("Fixed in #12.\n", root) == ["page.md: #12 would become a link to an issue in the package"]
    assert reported("- Search.\n  #7 is closed.\n", root) == ["page.md: #7 would become a link to an issue in the package"]
    assert reported("See example/project#3.\n", root) == ["page.md: example/project#3 would become a link to an issue in the package"]


def test_a_project_address_with_another_tag_is_reported(tmp_path):
    root = small_tree(tmp_path)
    for named in ("main", "v1.2.2", "HEAD"):
        address = f"{REPOSITORY}/blob/{named}/docs/guide.md"
        assert reported(f"[guide]({address})\n", root) == [f"page.md: {address} does not name the tag v1.2.3"]
    address = "https://raw.githubusercontent.com/example/project/main/docs/images/overview.png"
    assert reported(f"![picture]({address})\n", root) == [f"page.md: {address} does not name the tag v1.2.3"]


def test_a_project_address_to_a_missing_path_is_reported(tmp_path):
    root = small_tree(tmp_path)
    address = f"{REPOSITORY}/blob/{TAG}/docs/missing.md"
    assert reported(f"[page]({address})\n", root) == [f"page.md: {address} names a path that is not in the tree: docs/missing.md"]
    address = f"{REPOSITORY}/tree/{TAG}/missing"
    assert reported(f"A bare address: {address}.\n", root) == [f"page.md: {address} names a path that is not in the tree: missing"]
    # A file is not a folder, and a folder is not a file.
    address = f"{REPOSITORY}/blob/{TAG}/docs"
    assert reported(f"[docs]({address})\n", root) == [f"page.md: {address} names a path that is not in the tree: docs"]
    # The spelling counts, also where the file system ignores case.
    for path in ("docs/Guide.md", "Docs/guide.md", "docs/../LICENSE"):
        address = f"{REPOSITORY}/blob/{TAG}/{path}"
        assert reported(f"[page]({address})\n", root) == [f"page.md: {address} names a path that is not in the tree: {path}"]


def test_a_project_address_to_a_missing_picture_is_reported(tmp_path):
    root = small_tree(tmp_path)
    address = f"https://raw.githubusercontent.com/example/project/{TAG}/docs/images/missing.png"
    assert reported(f"![picture]({address})\n", root) == [f"page.md: {address} names a path that is not in the tree: docs/images/missing.png"]


def pictures_in_tree(root):
    """The files under docs/images/: those that git tracks, or every file there outside a git checkout."""
    if module.tracked_markdown(root) is not None:
        listed = module.git("ls-files", "-z", "--", IMAGES, cwd=root)
        return {path for path in listed.split("\0") if path}
    folder = root / IMAGES
    return {path.relative_to(root).as_posix() for path in folder.rglob("*") if path.is_file()} if folder.is_dir() else set()


def pictures_named(root, repository, tag):
    """The paths under docs/images/ that the Markdown files name: by a relative link, or by an address at the tag."""
    home = urlsplit(repository)
    base = [part.lower() for part in home.path.strip("/").split("/")]
    named = set()
    for name in module.documents(root):
        for target in module.targets((root / name).read_text(encoding="utf-8")):
            there = urlsplit(target)
            if there.scheme in ("http", "https"):
                parts = there.path.split("/")[1:]
                host = there.netloc.lower()
                if host not in (home.netloc.lower(), RAW_HOST) or [part.lower() for part in parts[:len(base)]] != base:
                    continue
                rest = parts[len(base):]
                if host != RAW_HOST:
                    if rest[:1] not in (["blob"], ["raw"]):
                        continue
                    rest = rest[1:]
                if rest[:1] != [tag]:
                    continue
                path = unquote("/".join(rest[1:]))
            elif there.scheme or there.netloc or not there.path:
                continue
            else:
                path = os.path.normpath(os.path.join(os.path.dirname(name), unquote(there.path))).replace(os.sep, "/")
            if path.startswith(IMAGES):
                named.add(path)
    return named


def test_every_picture_that_a_document_names_is_in_the_tree_and_every_picture_is_named():
    repository, tag = manifest_repository_and_tag()
    held, named = pictures_in_tree(module.ROOT), pictures_named(module.ROOT, repository, tag)
    assert sorted(named - held) == [], "named by a document, not in the tree"
    assert sorted(held - named) == [], "in the tree, named by no document"
    # The rule is not empty: the README and the extension's page show the overview.
    assert f"{IMAGES}overview.png" in held


def test_a_missing_picture_and_a_picture_that_no_document_names_are_found(tmp_path):
    root = small_tree(tmp_path)
    (root / "README.md").write_text("![a](docs/images/overview.png) ![b](docs/images/missing.png)\n", encoding="utf-8")
    (root / "docs" / "page.md").write_text(
        f"![c](https://raw.githubusercontent.com/example/project/{TAG}/docs/images/overview.png) ![d](images/overview.png)\n",
        encoding="utf-8")
    (root / "docs" / "images" / "unnamed.png").write_bytes(b"")
    held, named = pictures_in_tree(root), pictures_named(root, REPOSITORY, TAG)
    assert sorted(named - held) == ["docs/images/missing.png"]
    assert sorted(held - named) == ["docs/images/unnamed.png"]


def test_a_project_address_to_a_missing_heading_is_reported(tmp_path):
    root = small_tree(tmp_path)
    for fragment in ("upgrade", "Install", "install-2"):
        address = f"{REPOSITORY}/blob/{TAG}/docs/guide.md#{fragment}"
        assert reported(f"[part]({address})\n", root) == [f"page.md: {address} names a heading that docs/guide.md does not have: #{fragment}"]


def test_another_page_of_the_project_is_reported(tmp_path):
    root = small_tree(tmp_path)
    for rest in ("/pull/9", "/actions", "/releases", "#readme"):
        address = REPOSITORY + rest
        assert reported(f"[it]({address})\n", root) == [
            f"page.md: {address} is not the repository, its issues, or a file or a folder at a tag"]
    # Another repository whose address begins with the same letters is not the project's.
    assert reported(f"[other]({REPOSITORY}-two/blob/main/README.md)\n", root) == []


def test_heading_anchors():
    text = (
        "# A Title\n\n## What leaves your machine, and what a diagram file holds\n\n```sh\n# not a heading\n```\n\n"
        "## Install\n\n### Install\n\n## `code` and **bold**: a [link](x.md)\n\n#no space\n\n## The `snake_case` name\n\n"
        "## The _fast_ path and my_own name\n\n## `__init__` and __bold__\n"
    )
    assert module.anchors(text) == {
        "a-title", "what-leaves-your-machine-and-what-a-diagram-file-holds", "install", "install-1",
        "code-and-bold-a-link", "the-snake_case-name",
        # Underscores around words are emphasis; inside a word or a code span they are text.
        "the-fast-path-and-my_own-name", "__init__-and-bold",
    }
