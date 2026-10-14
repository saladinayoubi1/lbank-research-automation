import importlib.util
from pathlib import Path

path = Path(__file__).parents[1] / "scripts" / "probe_nexus_rdc_l1_preflight.py"
spec = importlib.util.spec_from_file_location("nexus_preflight", path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
CLI = r"C:\Program Files\nodejs\node_modules\npm\bin\npx-cli.js"


def test_npx_is_classified_only_with_approved_path_package_and_remote():
    assert probe.classify(["node", CLI, "--yes", "@wonderwhy-er/desktop-commander@latest", "remote"])["role"] == "approved_npm_rdc_remote_launcher"


def test_same_cli_basename_in_unapproved_directory_has_no_ownership():
    assert probe.classify(["node", r"C:\unrelated\npx-cli.js", "@wonderwhy-er/desktop-commander", "remote"])["role"] == "unclassified"


def test_partial_or_multiple_package_argument_has_no_ownership():
    for packages in (["prefix@wonderwhy-er/desktop-commander"], ["@wonderwhy-er/desktop-commander", "@wonderwhy-er/desktop-commander@latest"]):
        assert probe.classify(["node", CLI, *packages, "remote"])["role"] == "unclassified"


def test_remote_mode_is_required_for_launcher():
    assert probe.classify(["node", CLI, "@wonderwhy-er/desktop-commander"])["role"] == "unclassified"


def test_mixed_cli_and_sdk_does_not_classify_as_a_launcher():
    assert probe.classify(["node", CLI, "@wonderwhy-er/desktop-commander", probe.ENTRY, "remote"])["role"] == "unclassified"


def test_sdk_dot_segments_resolve_to_exact_public_cache_entry():
    alias = probe.ENTRY.replace(r"node_modules\@wonderwhy-er", r"node_modules\.bin\\..\@wonderwhy-er")
    observed = probe.classify(["node", alias, "remote"])
    assert observed["role"] == "sdk_remote_candidate"
    assert observed["sdk_entry"] == probe.norm(probe.ENTRY)


def test_duplicate_remote_arguments_remain_unclassified():
    result = probe.classify(["node", probe.ENTRY, "remote", "remote"])
    assert result["role"] == "unclassified"
    assert result["remote_argument_present"] is True
