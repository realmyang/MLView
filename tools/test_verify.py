import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

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


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        for rel in INPUTS:
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


if __name__ == "__main__":
    unittest.main()
