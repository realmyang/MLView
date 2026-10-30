"""Checks of the VSIX payload check: incomplete, stale and unexpected packages."""
import importlib.util
import json
import warnings
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("vsix_check", Path(__file__).with_name("vsix_check.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


# The two XML files of a package, cut down to the lines that the check reads.
ASSETS = (
    '<PackageManifest><Assets>\n'
    '<Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/readme.md" Addressable="true" />\n'
    '<Asset Type="Microsoft.VisualStudio.Services.Content.Changelog" Path="extension/changelog.md" Addressable="true" />\n'
    '</Assets></PackageManifest>\n'
).encode()
TYPES = b'<Types><Default Extension=".json" ContentType="application/json"/><Default Extension=".md" ContentType="text/markdown"/></Types>\n'


def manifest(commands=None, contributions=None):
    return json.dumps({"contributes": {**(contributions or {}), "commands": [
        {"command": command} for command in (commands or ["mlview.openGeneratedDiagram"])
    ]}}).encode()


def package(tmp_path, missing=None, extra=None, commands=None, contributions=None, bundle=b"asset", assets=ASSETS, types=TYPES):
    path = tmp_path / "test.vsix"
    with zipfile.ZipFile(path, "w") as archive:
        for name in sorted(module.ENTRIES - {missing}):
            value = bundle if name == module.BUNDLE else b"asset"
            if name.endswith("package.json"):
                value = manifest(commands, contributions)
            if name == "extension.vsixmanifest":
                value = assets
            if name == "[Content_Types].xml":
                value = types
            archive.writestr(name, value)
        if extra:
            archive.writestr(extra, "extra")
    return path


def test_package_with_exactly_the_listed_entries_passes(tmp_path):
    result = module.check(tmp_path, package(tmp_path), payload_only=True)
    assert not result.problems
    assert result.skipped == [f"SKIP: bundle freshness not compared (--payload-only): {label}"
                              for _, _, _, label in module.FRESHNESS]


def write_sources(root, **overrides):
    for _, relative, _, label in module.FRESHNESS:
        source = root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(overrides.get(label, manifest() if label == "package.json" else b"asset"))


def test_current_sources_pass_with_every_comparison_made(tmp_path):
    write_sources(tmp_path)
    result = module.check(tmp_path, package(tmp_path))
    assert result.problems == [] and result.skipped == []


def test_missing_working_tree_source_is_a_problem_not_a_silent_skip(tmp_path):
    write_sources(tmp_path)
    (tmp_path / "vscode-extension/out/extension.js").unlink()
    (tmp_path / "LICENSE").unlink()
    assert module.check(tmp_path, package(tmp_path)).problems == [
        "cannot compare LICENSE: LICENSE is missing (pass --payload-only to check the package alone)",
        "cannot compare out/extension.js: vscode-extension/out/extension.js is missing "
        "(run npm run package first, or pass --payload-only)"]


def test_an_unminified_working_tree_bundle_is_named_as_the_reason_it_cannot_be_compared(tmp_path):
    for unminified in (b'"use strict";\nvar a=1;\n//# sourceMappingURL=extension.js.map\n',
                       b'"use strict";\n// src/extension.ts\nvar a=1;\n'):
        write_sources(tmp_path, **{"out/extension.js": unminified})
        assert module.check(tmp_path, package(tmp_path)).problems == [
            "cannot compare out/extension.js: vscode-extension/out/extension.js is the unminified build that "
            "npm run compile and npm test write (run npm run package again, or pass --payload-only)"]
        assert module.check(tmp_path, package(tmp_path), payload_only=True).problems == []


def test_payload_only_never_reports_stale_bundles(tmp_path):
    write_sources(tmp_path, **{"out/extension.js": b"newer bundle"})
    assert module.check(tmp_path, package(tmp_path)).problems == ["stale packaged payload: out/extension.js"]
    assert module.check(tmp_path, package(tmp_path), payload_only=True).problems == []


def test_missing_renderer_fails(tmp_path):
    vsix = package(tmp_path, missing="extension/media/mlview.js")
    assert module.check(tmp_path, vsix, payload_only=True).problems == ["missing entry: extension/media/mlview.js"]


def test_every_listed_entry_is_required(tmp_path):
    assert len(module.ENTRIES) == 11
    for name in sorted(module.ENTRIES):
        vsix = package(tmp_path, missing=name)
        assert module.check(tmp_path, vsix, payload_only=True).problems == [f"missing entry: {name}"]


def test_an_entry_outside_the_list_fails(tmp_path):
    for extra in ("extension/notes.txt", "extension/out/extension.js.map", "extension/node_modules/dependency/index.js", "notes.txt"):
        vsix = package(tmp_path, extra=extra)
        assert module.check(tmp_path, vsix, payload_only=True).problems == [f"unexpected entry: {extra}"]


def test_a_repeated_entry_fails(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # zipfile warns about the name it is asked to repeat
        vsix = package(tmp_path, extra="extension/readme.md")
    result = module.check(tmp_path, vsix, payload_only=True)
    assert result.problems == ["repeated entry: extension/readme.md"]
    assert result.measured.startswith("12 files, ")


def test_reveal_in_diagram_command_passes(tmp_path):
    vsix = package(tmp_path, commands=["mlview.openGeneratedDiagram", "mlview.revealInDiagram"])
    assert module.check(tmp_path, vsix, payload_only=True).problems == []


def test_reveal_without_the_open_command_fails(tmp_path):
    vsix = package(tmp_path, commands=["mlview.revealInDiagram"])
    assert any("commands" in p for p in module.check(tmp_path, vsix, payload_only=True)[0])


def test_a_command_outside_the_list_fails(tmp_path):
    vsix = package(tmp_path, commands=["mlview.openGeneratedDiagram", "mlview.other"])
    assert module.check(tmp_path, vsix, payload_only=True).problems == ["unexpected or missing extension commands"]


def test_the_diagram_editor_passes(tmp_path):
    editors = [{"viewType": "mlview.diagram", "selector": [{"filenamePattern": "*.mlview.json"}], "priority": "default"}]
    vsix = package(tmp_path, contributions={"customEditors": editors})
    assert module.check(tmp_path, vsix, payload_only=True).problems == []


def test_another_custom_editor_or_pattern_fails(tmp_path):
    for editors in (
        [{"viewType": "mlview.other", "selector": [{"filenamePattern": "*.mlview.json"}]}],
        [{"viewType": "mlview.diagram", "selector": [{"filenamePattern": "*.json"}]}],
        [{"viewType": "mlview.diagram", "selector": [{"filenamePattern": "*.mlview.json"}, {"filenamePattern": "*.py"}]}],
        "mlview.diagram",
    ):
        vsix = package(tmp_path, contributions={"customEditors": editors})
        assert module.check(tmp_path, vsix, payload_only=True).problems == ["unexpected custom editors"], editors


def test_stale_renderer_fails(tmp_path):
    write_sources(tmp_path, **{"media/mlview.js": b"new renderer"})
    assert module.check(tmp_path, package(tmp_path))[0] == ["stale packaged payload: media/mlview.js"]


def test_stale_notice_fails(tmp_path):
    write_sources(tmp_path, LICENSE=b"new license")
    assert module.check(tmp_path, package(tmp_path))[0] == ["stale packaged notice: LICENSE"]


def test_stale_changelog_fails(tmp_path):
    write_sources(tmp_path, **{"CHANGELOG.md": b"new changelog"})
    assert module.check(tmp_path, package(tmp_path))[0] == ["stale packaged changelog: CHANGELOG.md"]


def test_a_stale_page_manifest_or_icon_fails(tmp_path):
    # The page and the manifest that a person reads before installing, and the icon beside them.
    write_sources(tmp_path, **{"vscode-extension/README.md": b"another page"})
    assert module.check(tmp_path, package(tmp_path))[0] == ["stale packaged page: vscode-extension/README.md"]
    write_sources(tmp_path, **{"package.json": manifest() + b"\n"})
    assert module.check(tmp_path, package(tmp_path))[0] == ["stale packaged manifest: package.json"]
    write_sources(tmp_path, **{"media/icon.png": b"another icon"})
    assert module.check(tmp_path, package(tmp_path))[0] == ["stale packaged payload: media/icon.png"]
    write_sources(tmp_path)
    (tmp_path / "vscode-extension" / "README.md").unlink()
    assert module.check(tmp_path, package(tmp_path))[0] == [
        "cannot compare vscode-extension/README.md: vscode-extension/README.md is missing "
        "(pass --payload-only to check the package alone)"]


def test_a_package_whose_manifest_offers_no_changelog_fails(tmp_path):
    changelog = b'<Asset Type="Microsoft.VisualStudio.Services.Content.Changelog" Path="extension/changelog.md" Addressable="true" />\n'
    assert changelog in ASSETS
    problem = ["extension.vsixmanifest offers no changelog asset at extension/changelog.md"]
    for assets in (
        ASSETS.replace(changelog, b""),
        # The asset must name the entry that the package holds, under its type.
        ASSETS.replace(b'Path="extension/changelog.md"', b'Path="extension/CHANGELOG.md"'),
        ASSETS.replace(b"Content.Changelog", b"Content.Details"),
        b"",
    ):
        assert module.check(tmp_path, package(tmp_path, assets=assets), payload_only=True).problems == problem, assets
    # The check reads the attributes, not the line: another order of them names the same asset.
    turned = ASSETS.replace(changelog, b'<Asset Addressable="true" Path="extension/changelog.md"\n  Type="Microsoft.VisualStudio.Services.Content.Changelog"/>\n')
    assert module.check(tmp_path, package(tmp_path, assets=turned), payload_only=True).problems == []


def test_a_package_without_a_content_type_for_markdown_fails(tmp_path):
    problem = ["[Content_Types].xml names no content type for .md"]
    for types in (TYPES.replace(b'<Default Extension=".md" ContentType="text/markdown"/>', b""),
                  TYPES.replace(b'ContentType="text/markdown"', b'ContentType=""'), b""):
        assert module.check(tmp_path, package(tmp_path, types=types), payload_only=True).problems == problem, types
    assert module.check(tmp_path, package(tmp_path, types=TYPES.replace(b'".md"', b'".MD"')), payload_only=True).problems == []


def test_the_changelog_is_one_of_the_eleven_entries(tmp_path):
    assert "extension/changelog.md" in module.ENTRIES
    without = module.check(tmp_path, package(tmp_path, missing="extension/changelog.md"), payload_only=True)
    assert without.problems == ["missing entry: extension/changelog.md"]
    assert without.measured.startswith("10 files, ")
    twelfth = module.check(tmp_path, package(tmp_path, extra="extension/CHANGELOG.md"), payload_only=True)
    assert twelfth.problems == ["unexpected entry: extension/CHANGELOG.md"]
    assert twelfth.measured.startswith("12 files, ")


def test_a_contribution_outside_the_list_fails(tmp_path):
    vsix = package(tmp_path, contributions={"keybindings": [{"command": "mlview.revealInDiagram", "key": "f9"}]})
    assert module.check(tmp_path, vsix, payload_only=True).problems == ["unexpected contribution: keybindings"]


def test_the_measured_line_gives_the_entry_count_and_the_size(tmp_path):
    vsix = package(tmp_path)
    assert module.check(tmp_path, vsix, payload_only=True).measured == f"11 files, {vsix.stat().st_size} bytes"


def test_bundle_with_a_source_map_link_fails(tmp_path):
    vsix = package(tmp_path, bundle=b'"use strict";var a=1;\n//# sourceMappingURL=extension.js.map\n')
    assert module.check(tmp_path, vsix, payload_only=True).problems == [
        "packaged bundle is not the production build: it links a source map",
        "packaged bundle is not the production build: line 2 is a comment"]


def test_bundle_with_a_comment_line_fails(tmp_path):
    for bundle, line in (
        (b'"use strict";\n// src/extension.ts\nvar a=1;\n', 2),
        (b'var a=1;\nvar b=2;\n  /**\n   * A note.\n   */\nvar c=3;\n// end\n', 3),
    ):
        vsix = package(tmp_path, bundle=bundle)
        assert module.check(tmp_path, vsix, payload_only=True).problems == [
            f"packaged bundle is not the production build: line {line} is a comment"]


def test_bundle_with_comment_marks_inside_a_line_passes(tmp_path):
    vsix = package(tmp_path, bundle=b'"use strict";var glob="**/*.mlview.json",url="https://example.invalid";\nvar b=1;\n')
    assert module.check(tmp_path, vsix, payload_only=True).problems == []


def test_the_command_exits_0_without_a_problem_and_prints_each_problem_and_exits_1(tmp_path, capsys):
    assert module.main([str(package(tmp_path)), "--payload-only"]) == 0
    assert "FAIL" not in capsys.readouterr().out
    assert module.main([str(package(tmp_path, extra="notes.txt")), "--payload-only"]) == 1
    assert "FAIL: unexpected entry: notes.txt\n" in capsys.readouterr().out
