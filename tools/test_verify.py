import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("verify.py")
SPEC = importlib.util.spec_from_file_location("mlview_verify", SCRIPT)
verify = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(verify)

# The files check_metadata reads; copied into a scratch root so each test can change one.
INPUTS = (
    *verify.MANIFESTS, verify.MARKETPLACE, verify.VIEWER_ENTRY,
    "contracts/workflow.schema.json", "skills/mlview/references/workflow-example.json",
)


class ScratchRoot(unittest.TestCase):
    """A scratch root that holds copies of the files a check reads."""

    FILES = ()

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        for rel in self.FILES:
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(verify.ROOT / rel, target)

    def tearDown(self):
        self._temp.cleanup()

    def edit_json(self, rel, change):
        path = self.root / rel
        value = json.loads(path.read_text(encoding="utf-8"))
        change(value)
        path.write_text(json.dumps(value), encoding="utf-8")


class MetadataTests(ScratchRoot):
    FILES = INPUTS

    def test_repository_versions_agree(self):
        self.assertEqual([], verify.check_metadata())
        versions = verify.product_versions()
        self.assertEqual(1, len(set(versions.values())), versions)
        self.assertEqual(len(verify.MANIFESTS) + 2, len(versions))

    def test_scratch_copy_passes(self):
        self.assertEqual([], verify.check_metadata(self.root))

    def test_marketplace_metadata_version_must_match(self):
        self.edit_json(verify.MARKETPLACE, lambda value: value["metadata"].update(version="9.9.9"))
        problems = verify.check_metadata(self.root)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("component versions differ", problems[0])
        self.assertIn("marketplace.json metadata.version=9.9.9", problems[0])

    def test_marketplace_metadata_version_must_exist(self):
        self.edit_json(verify.MARKETPLACE, lambda value: value["metadata"].pop("version"))
        problems = verify.check_metadata(self.root)
        self.assertEqual(["product version missing or ambiguous: .claude-plugin/marketplace.json metadata.version"], problems)

    def test_viewer_version_literal_must_match(self):
        path = self.root / verify.VIEWER_ENTRY
        text = path.read_text(encoding="utf-8")
        version = verify.product_versions(self.root)[verify.MANIFESTS[0]]
        path.write_text(text.replace(f"export const version = '{version}';", "export const version = '9.9.9';"), encoding="utf-8")
        problems = verify.check_metadata(self.root)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("webview/src/main.ts version literal=9.9.9", problems[0])

    def test_viewer_version_literal_must_be_unique(self):
        path = self.root / verify.VIEWER_ENTRY
        path.write_text(path.read_text(encoding="utf-8") + "\nexport const version = '0.0.1';\n", encoding="utf-8")
        problems = verify.check_metadata(self.root)
        self.assertIn("product version missing or ambiguous: webview/src/main.ts version literal", problems)

    def test_manifest_version_must_match(self):
        self.edit_json("claude-plugin/.claude-plugin/plugin.json", lambda value: value.update(version="0.0.0"))
        problems = verify.check_metadata(self.root)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("claude-plugin/.claude-plugin/plugin.json=0.0.0", problems[0])


class ContentsTests(ScratchRoot):
    FILES = (*sorted(verify.PLUGIN_FILES), verify.EXTENSION_MANIFEST)

    def contribute(self, change):
        self.edit_json(verify.EXTENSION_MANIFEST, lambda value: change(value["contributes"]))
        return verify.check_contents(self.root)

    def test_repository_contents_pass(self):
        self.assertEqual([], verify.check_contents())

    def test_scratch_copy_of_the_listed_files_passes(self):
        self.assertEqual([], verify.check_contents(self.root))

    def test_extra_plugin_file_is_reported(self):
        for rel in ("claude-plugin/notes.txt", "claude-plugin/skills/mlview/references/extra.md",
                    "claude-plugin/tests/test_plugin.py"):
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("extra\n", encoding="utf-8")
        self.assertEqual([
            "unexpected plugin file: claude-plugin/notes.txt",
            "unexpected plugin file: claude-plugin/skills/mlview/references/extra.md",
            "unexpected plugin file: claude-plugin/tests/test_plugin.py",
        ], verify.check_contents(self.root))

    def test_missing_plugin_file_is_reported(self):
        (self.root / "claude-plugin/LICENSE").unlink()
        (self.root / "claude-plugin/skills/mlview/scripts/artifact.py").unlink()
        self.assertEqual([
            "missing plugin file: claude-plugin/LICENSE",
            "missing plugin file: claude-plugin/skills/mlview/scripts/artifact.py",
        ], verify.check_contents(self.root))

    def test_bytecode_cache_folder_is_not_a_plugin_file(self):
        cache = self.root / "claude-plugin/skills/mlview/scripts/__pycache__"
        cache.mkdir()
        (cache / "artifact.cpython-313.pyc").write_bytes(b"cache")
        self.assertEqual([], verify.check_contents(self.root))

    def test_any_other_file_in_a_bytecode_cache_folder_is_reported(self):
        for rel in ("claude-plugin/skills/mlview/scripts/__pycache__/hooks.json", "claude-plugin/__pycache__/server/main.pyc",
                    "claude-plugin/skills/mlview/scripts/__pycache__/artifact.cpython-313.pyc"):
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"cache")
        self.assertEqual([
            "unexpected plugin file: claude-plugin/__pycache__/server/main.pyc",
            "unexpected plugin file: claude-plugin/skills/mlview/scripts/__pycache__/hooks.json",
        ], verify.check_contents(self.root))

    def test_linked_folder_is_reported_as_a_plugin_file(self):
        outside = self.root / "outside"
        outside.mkdir()
        try:
            os.symlink(outside, self.root / "claude-plugin/linked", target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"this platform cannot create a symbolic link: {error}")
        self.assertEqual(["unexpected plugin file: claude-plugin/linked"], verify.check_contents(self.root))

    def test_extra_contribution_is_reported(self):
        problems = self.contribute(lambda contributes: contributes.update(keybindings=[{"command": "mlview.revealInDiagram", "key": "f9"}]))
        self.assertEqual(["unexpected extension contribution: keybindings"], problems)

    def test_missing_contribution_is_reported(self):
        problems = self.contribute(lambda contributes: contributes.pop("menus"))
        self.assertEqual(["missing extension contribution: menus"], problems)

    def test_extra_command_is_reported(self):
        problems = self.contribute(lambda contributes: contributes["commands"].append({"command": "mlview.other", "title": "Other"}))
        self.assertEqual(["unexpected extension contribution: commands mlview.other"], problems)

    def test_missing_command_is_reported(self):
        problems = self.contribute(lambda contributes: contributes["commands"].pop())
        self.assertEqual(["missing extension contribution: commands mlview.revealInDiagram"], problems)

    def test_another_custom_editor_is_reported(self):
        problems = self.contribute(lambda contributes: contributes["customEditors"][0].update(viewType="mlview.other"))
        self.assertEqual([
            "unexpected extension contribution: customEditors mlview.other",
            "missing extension contribution: customEditors mlview.diagram",
        ], problems)


class CommandTests(unittest.TestCase):
    """The command runs every check, prints each problem and exits 1 when there is one."""

    def run_command(self, metadata=(), contents=(), failing_copy_check=None):
        """Run main() with each check replaced by its given result: (exit status, stdout, stderr, the copy checks run)."""
        def copy_check(command, **_):
            return subprocess.CompletedProcess(command, int(Path(command[1]).name == failing_copy_check))

        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(verify, "check_metadata", return_value=list(metadata)))
            stack.enter_context(mock.patch.object(verify, "check_contents", return_value=list(contents)))
            run = stack.enter_context(mock.patch.object(verify.subprocess, "run", side_effect=copy_check))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            code = verify.main([])
        return code, out.getvalue(), err.getvalue(), [Path(call.args[0][1]).name for call in run.call_args_list]

    def test_no_problem_prints_the_success_line_and_exits_0(self):
        code, out, err, copy_checks = self.run_command()
        self.assertEqual((0, ""), (code, err))
        self.assertTrue(out.startswith("VERIFY OK: "), out)
        self.assertEqual(["sync-assets.py", "sync-skill.py"], copy_checks)

    def test_a_problem_of_any_check_is_printed_and_exits_1(self):
        for found, line in (
            ({"metadata": ["component versions differ: a=1, b=2"]}, "FAIL: component versions differ: a=1, b=2\n"),
            ({"contents": ["unexpected plugin file: claude-plugin/notes.txt"]}, "FAIL: unexpected plugin file: claude-plugin/notes.txt\n"),
            ({"failing_copy_check": "sync-assets.py"}, "FAIL: tools/sync-assets.py --check failed\n"),
            ({"failing_copy_check": "sync-skill.py"}, "FAIL: tools/sync-skill.py --check failed\n"),
        ):
            code, out, err, _ = self.run_command(**found)
            self.assertEqual((1, "", line), (code, out, err), found)


if __name__ == "__main__":
    unittest.main()
