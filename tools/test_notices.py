"""THIRD_PARTY_NOTICES.md names the packages that the viewer bundle carries, at the locked versions.

A heading of the form ``## <package> <version> — <licence>`` opens the notice of one package.
The packages that the bundle can carry are the entries of webview/package-lock.json that are not
marked ``dev``: the viewer's runtime dependency and what that depends on. Each of them must have
a notice with the version that the lock file holds, and each notice must name one of them.

A notice names the licence that LICENCES lists for its package and holds the licence's text in a
fenced block. Where the package is installed at the locked version, the licence and the text are
compared with the installed package's own. The extension declares no runtime package, so its lock
file holds none. What a bundle really inlines is not read here: a development package that a source
file imports would be inlined without a notice.
"""
from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
LOCK = ROOT / "webview" / "package-lock.json"
EXTENSION = ROOT / "vscode-extension"
NOTICE = re.compile(r"^## (\S+) (\d+(?:\.\d+)+\S*) — (\S.*?)\s*$")
INSTALLED = "node_modules/"
# The licence that the heading of each notice names. A package that joins the bundle is added here.
LICENCES = {"@dagrejs/dagre": "MIT", "@dagrejs/graphlib": "MIT"}
# A licence text is longer than this many words; the MIT text has about 170.
FEWEST_WORDS = 100


def noticed(text: str) -> dict[str, str]:
    """Package name to version, for every notice heading of the text."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = NOTICE.match(line)
        if match is None:
            continue
        if match[1] in found:
            raise ValueError(f"two notices for {match[1]}")
        found[match[1]] = match[2]
    return found


def notices(text: str) -> dict[str, tuple[str, str]]:
    """Package name to the licence that its heading names and the text under the heading, up to the next heading of that level."""
    found: dict[str, tuple[str, str]] = {}
    name = None
    for line in text.splitlines():
        match = NOTICE.match(line)
        if match is not None:
            name = match[1]
            found[name] = (match[3], "")
        elif line.startswith("## "):
            name = None
        elif name is not None:
            found[name] = (found[name][0], found[name][1] + line + "\n")
    return found


def licence_text(body: str) -> str:
    """What the first fenced block of a notice holds, or nothing."""
    match = re.search(r"^```[^\n]*\n(.*?)^```[ \t]*$", body, re.S | re.M)
    return match[1] if match else ""


def notice_problems(text: str, licences: dict[str, str] = LICENCES) -> list[str]:
    """A notice whose heading names another licence than the list, or which holds no licence text."""
    out = []
    for name, (licence, body) in sorted(notices(text).items()):
        if licences.get(name) != licence:
            out.append(f"{name}: the heading says {licence}, the list says {licences.get(name, 'nothing')}")
        words = licence_text(body)
        if "Copyright" not in words or len(words.split()) < FEWEST_WORDS:
            out.append(f"{name}: the notice holds no licence text")
    return out


def bundled(lock: dict) -> dict[str, str]:
    """Package name to version, for every entry of the lock file that is not a development package."""
    found: dict[str, str] = {}
    for path, entry in lock["packages"].items():
        if not path.startswith(INSTALLED) or entry.get("dev"):
            continue
        name = path.rsplit(INSTALLED, 1)[1]
        if found.setdefault(name, entry["version"]) != entry["version"]:
            raise ValueError(f"the lock file holds two versions of {name}")
    return found


def problems(text: str, lock: dict) -> list[str]:
    notices, packages = noticed(text), bundled(lock)
    out = [f"no notice for {name} {packages[name]}, which the viewer bundle can carry" for name in sorted(packages.keys() - notices.keys())]
    out += [f"a notice for {name}, which the lock file does not hold as a runtime package" for name in sorted(notices.keys() - packages.keys())]
    out += [
        f"{name}: the notice says {notices[name]}, the lock file holds {packages[name]}"
        for name in sorted(notices.keys() & packages.keys()) if notices[name] != packages[name]
    ]
    return out


class NoticesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = NOTICES.read_text(encoding="utf-8")
        cls.lock = json.loads(LOCK.read_text(encoding="utf-8"))

    def test_the_notices_name_the_bundled_packages_at_the_locked_versions(self):
        self.assertEqual(problems(self.text, self.lock), [])
        # The comparison is not empty: the viewer has a runtime dependency, and it is noticed.
        dependencies = self.lock["packages"][""]["dependencies"]
        self.assertTrue(dependencies)
        self.assertLessEqual(set(dependencies), set(noticed(self.text)))

    def test_a_changed_version_in_the_notices_is_reported(self):
        name, version = sorted(noticed(self.text).items())[0]
        text = self.text.replace(f"## {name} {version} ", f"## {name} 0.0.1 ")
        self.assertEqual(problems(text, self.lock), [f"{name}: the notice says 0.0.1, the lock file holds {version}"])

    def test_a_changed_version_in_the_lock_file_is_reported(self):
        name, version = sorted(noticed(self.text).items())[-1]
        lock = copy.deepcopy(self.lock)
        lock["packages"][INSTALLED + name]["version"] = "99.0.0"
        self.assertEqual(problems(self.text, lock), [f"{name}: the notice says {version}, the lock file holds 99.0.0"])

    def test_a_runtime_package_without_a_notice_is_reported(self):
        lock = copy.deepcopy(self.lock)
        lock["packages"][INSTALLED + "example-package"] = {"version": "1.2.3"}
        lock["packages"][INSTALLED + "example-tool"] = {"version": "4.5.6", "dev": True}
        self.assertEqual(problems(self.text, lock), ["no notice for example-package 1.2.3, which the viewer bundle can carry"])

    def test_a_notice_for_a_package_that_is_not_bundled_is_reported(self):
        development = sorted(path[len(INSTALLED):] for path, entry in self.lock["packages"].items() if entry.get("dev"))[0]
        version = self.lock["packages"][INSTALLED + development]["version"]
        text = self.text + f"\n## {development} {version} — MIT\n"
        self.assertEqual(problems(text, self.lock), [f"a notice for {development}, which the lock file does not hold as a runtime package"])
        self.assertEqual(problems(self.text + "\n## example-package 1.2.3 — MIT\n", self.lock),
                         ["a notice for example-package, which the lock file does not hold as a runtime package"])

    def test_each_notice_names_the_listed_licence_and_holds_its_text(self):
        self.assertEqual(notice_problems(self.text), [])
        self.assertEqual(set(notices(self.text)), set(LICENCES))

    def test_a_notice_with_another_licence_or_without_its_text_is_reported(self):
        name, version = sorted(noticed(self.text).items())[-1]
        licence, body = notices(self.text)[name]
        heading = f"## {name} {version} — {licence}"
        self.assertEqual(notice_problems(self.text.replace(heading, f"## {name} {version} — ISC")),
                         [f"{name}: the heading says ISC, the list says {licence}"])
        without = [f"{name}: the notice holds no licence text"]
        # The heading alone, the notice without its fenced block, and a block that holds one line.
        words = licence_text(body)
        self.assertEqual(self.text.count(body), 1)
        self.assertEqual(notice_problems(self.text.replace(body, "\n")), without)
        for other in ("", "Copyright (c) Someone\n", words.replace("Copyright", "Rights")):
            self.assertEqual(notice_problems(self.text.replace(body, body.replace(words, other))), without, other)
        self.assertEqual(notice_problems(self.text + "\n## example-package 1.2.3 — MIT\n\nNo text.\n"),
                         ["example-package: the heading says MIT, the list says nothing", "example-package: the notice holds no licence text"])

    def test_each_notice_holds_the_licence_of_the_installed_package(self):
        compared = []
        for name, (licence, body) in notices(self.text).items():
            folder = ROOT / "webview" / "node_modules" / name
            if not (folder / "package.json").is_file() or not (folder / "LICENSE").is_file():
                continue
            package = json.loads((folder / "package.json").read_text(encoding="utf-8"))
            if package.get("version") != bundled(self.lock).get(name):
                # Another version is installed than the lock file holds: it says nothing about the notice.
                continue
            self.assertEqual(package.get("license"), licence, name)
            self.assertEqual(licence_text(body).split(), (folder / "LICENSE").read_text(encoding="utf-8").split(), name)
            compared.append(name)
        if not compared:
            self.skipTest("the viewer's packages are not installed at the locked versions, so their licence files are not read")

    def test_the_extension_declares_no_runtime_package(self):
        manifest = json.loads((EXTENSION / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((EXTENSION / "package-lock.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest.get("dependencies"))
        self.assertFalse(lock["packages"][""].get("dependencies"))
        self.assertEqual(bundled(lock), {})
        # The rule is not empty: the same reading finds the viewer's runtime packages.
        self.assertEqual(set(bundled(self.lock)), set(LICENCES))
        runtime = copy.deepcopy(lock)
        runtime["packages"][INSTALLED + "example-package"] = {"version": "1.2.3"}
        self.assertEqual(bundled(runtime), {"example-package": "1.2.3"})

    def test_a_heading_without_a_version_is_not_a_notice(self):
        self.assertEqual(noticed("# Third-party notices\n\n## Build and test dependencies\n\n## a 1.0.0 — MIT\n### b 2.0.0 — MIT\n"), {"a": "1.0.0"})
        with self.assertRaises(ValueError):
            noticed("## a 1.0.0 — MIT\n## a 1.0.1 — MIT\n")


if __name__ == "__main__":
    unittest.main()
