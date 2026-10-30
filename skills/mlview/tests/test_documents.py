"""The sample diagrams and the test documents keep passing the helper's checks.

The documents are every sample diagram `samples/*.mlview.json`, at least one, and the eight
generated test documents of contracts/conformance/documents/workspace, which are listed by
name. A helper rule change must not make one of them structurally invalid. Each test document
is also validated in full against its workspace (paths, quotes, hashes); tools/test_samples.py
pins the full validation of each sample diagram.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HELPER = Path(__file__).resolve().parents[1] / "scripts" / "artifact.py"
SPEC = importlib.util.spec_from_file_location("mlview_artifact_documents", HELPER)
artifact = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(artifact)

WORKSPACE = ROOT / "contracts" / "conformance" / "documents" / "workspace"
TEST_DOCUMENTS = (
    "d01-minimal", "d02-notebook", "d03-two-files", "d04-loop",
    "d05-groups", "d06-refinement", "d07-multi-file", "d08-dense",
)


def sample_diagrams():
    """Every sample diagram, as paths."""
    return sorted((ROOT / "samples").glob("*.mlview.json"))


def listed_documents():
    """The sample diagrams and the eight test documents, as paths."""
    return sample_diagrams() + [WORKSPACE / f"{name}.mlview.json" for name in TEST_DOCUMENTS]


class DocumentTests(unittest.TestCase):
    def test_workspace_holds_exactly_the_listed_test_documents(self):
        found = sorted(path.name for path in WORKSPACE.glob("*.mlview.json"))
        self.assertEqual([f"{name}.mlview.json" for name in TEST_DOCUMENTS], found)

    def test_each_sample_diagram_and_test_document_passes_shape_and_reference_checks(self):
        self.assertGreaterEqual(len(sample_diagrams()), 1)
        paths = listed_documents()
        for path in paths:
            with self.subTest(document=path.relative_to(ROOT).as_posix()):
                doc = artifact._parse(path.read_bytes())
                problems = artifact.Problems()
                artifact._basic_shape(doc, problems)
                artifact._references(doc, problems)
                self.assertEqual([], problems.items)

    def test_each_test_document_validates_in_full_against_its_workspace(self):
        for name in TEST_DOCUMENTS:
            with self.subTest(document=name):
                doc = artifact._parse((WORKSPACE / f"{name}.mlview.json").read_bytes())
                warnings = []
                errors, hashes = artifact.validate(doc, WORKSPACE, warnings=warnings)
                self.assertEqual([], errors)
                self.assertEqual([], warnings)
                self.assertEqual(doc["verification"]["files"], hashes)


if __name__ == "__main__":
    unittest.main()
