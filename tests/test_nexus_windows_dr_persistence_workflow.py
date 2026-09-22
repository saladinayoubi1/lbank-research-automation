from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus-windows-dr-persistence.yml")


def _persist_job() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    return text.split("\n  persist:\n", 1)[1]


def test_physical_dr_fetch_uses_fresh_runner_temp_source() -> None:
    text = _persist_job()

    assert "runs-on: [self-hosted, Windows, X64, nexus-remote-rescue]" in text
    assert "$sourceRoot = Join-Path $env:RUNNER_TEMP" in text
    assert "^nexus-windows-dr-source-[0-9]+-[0-9]+$" in text
    assert "Exact isolated DR source root already exists" in text
    assert "NEXUS_DR_SOURCE_ROOT=" in text
    assert "git init ." in text
    assert "git remote add origin $repoUrl" in text
    assert "--no-tags --prune --depth=1 origin $env:GITHUB_SHA" in text
    assert "git checkout --detach --force FETCH_HEAD" in text
    assert "exact_trigger_sha=" in text

    for forbidden in (
        "git remote set-url origin",
        "git reset --hard",
        "git clean -ffdx",
        "safe.directory",
    ):
        assert forbidden not in text


def test_physical_dr_uses_unique_evidence_and_bounded_cleanup() -> None:
    text = _persist_job()

    assert (
        '"%RUNNER_TEMP%\\nexus-windows-dr-persistence-%GITHUB_RUN_ID%-%GITHUB_RUN_ATTEMPT%.json"'
        in text
    )
    assert "${{ runner.temp }}\\nexus-windows-dr-persistence-${{ github.run_id }}-${{ github.run_attempt }}.json" in text
    assert "Refusing cleanup outside the exact isolated DR source boundary." in text
    assert "Remove-Item -LiteralPath $sourceRoot -Recurse -Force" in text
    assert "Get-ChildItem -Force | Remove-Item" not in text


def test_physical_dr_preserves_read_only_and_paper_only_boundaries() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in text
    assert "runner_registration_modified" in text
    assert "runner_credentials_modified" in text
    assert "other_runner_paths_modified" in text
    assert "live_trading_authority" in text
