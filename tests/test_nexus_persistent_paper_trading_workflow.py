from __future__ import annotations

import base64
import textwrap
from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_persistent_paper_trading_loop.yml")


def _paper_job(text: str) -> str:
    return text.split("  paper-loop:", 1)[1].split("  persist-state:", 1)[0]


def _embedded_python_blocks(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    blocks: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        if "<<'PY'" not in lines[index]:
            index += 1
            continue
        start_line = index + 2
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index].strip() != "PY":
            body.append(lines[index])
            index += 1
        assert index < len(lines), f"unterminated Python heredoc at line {start_line}"
        blocks.append((start_line, textwrap.dedent("\n".join(body))))
        index += 1
    return blocks


def test_persistent_loop_runs_on_closed_candle_cadence_and_restores_state() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "7,22,37,52 * * * *"' in text
    assert "workflow_dispatch:" in text
    assert "STATE_ARTIFACT: nexus-persistent-paper-trading-state" in text
    assert "Restore newest persistent Paper state" in text
    assert "actions/artifacts?{query}" in text
    assert "Advance public closed-candle Paper portfolio loop" in text
    assert "nexus_persistent_paper_trading_loop.py" in text
    assert "nexus-persistent-paper-trading-state" in text
    assert "if: always()" in text


def test_pr_contract_isolated_and_new_main_push_supersedes_stale_runtime() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    concurrency = text.split("concurrency:", 1)[1].split("jobs:", 1)[0]
    assert "github.event_name == 'pull_request'" in concurrency
    assert "github.event.pull_request.number" in concurrency
    assert "|| 'main'" in concurrency
    assert "cancel-in-progress: ${{ github.event_name == 'push' }}" in concurrency

    paper = _paper_job(text)
    assert "timeout-minutes: 45" in paper
    assert "timeout-minutes: 50" not in paper


def test_persistent_loop_is_public_data_not_historical_archive_replay() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "8867026863",
        "5f1173467c2296201940c3b7786b7cc3e5442244e07289769ab4867ace41d668",
        "BYBIT_full_history_2022-12-01_to_2026-07-31.zip",
        "--replay-archive-root",
        "--archive-sha256",
        "NEXUS_OFFLINE_COURIER_KEY",
    ):
        assert forbidden not in text
    assert 'assert snapshot["data_mode"] == "public_bybit_closed_candles"' in text


def test_public_bybit_collector_changes_retrigger_and_are_contract_tested() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count('"bybit_public_klines.py"') >= 2
    assert text.count('"nexus_bybit_same_interval_chunk_fallback.py"') >= 2
    assert text.count('"tests/test_bybit_public_klines.py"') >= 2
    assert text.count('"tests/test_nexus_bybit_same_interval_chunk_fallback.py"') >= 2
    contract = text.split("Verify persistent Trading Engine contracts", 1)[1]
    assert "tests/test_bybit_public_klines.py" in contract
    assert "tests/test_nexus_bybit_same_interval_chunk_fallback.py" in contract


def test_network_eligible_runner_is_pinned_and_fail_closed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    paper = _paper_job(text)
    assert "runs-on: nexus-bybit-network" in paper
    assert "vars.NEXUS_BYBIT_NETWORK_RUNNER_ENABLED" not in paper
    assert "ubuntu-latest" not in paper
    assert "Enforce eligible Bybit network execution plane" in paper
    assert "runner.environment" in paper
    assert "self-hosted" in paper
    assert "runner.os" in paper
    assert "Linux" in paper
    assert "bybit_network_execution_plane=self-hosted:nexus-bybit-network" in paper
    assert "proxy" not in paper.lower()
    assert "vpn" not in paper.lower()


def test_physical_wsl_job_uses_hosted_exact_source_artifact_without_javascript_actions() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    contract, _ = text.split("  paper-loop:", 1)
    paper = _paper_job(text)
    persist = text.split("  persist-state:", 1)[1]

    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in contract
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in contract
    upload_action = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    assert upload_action in contract
    assert upload_action in persist
    assert "Pack exact commit source for the Node-free physical Paper job" in contract
    assert 'git archive --format=zip --output "$archive" "$GITHUB_SHA"' in contract
    assert "nexus-persistent-paper-source-${{ github.sha }}" in contract
    assert "source_archive_sha256" in contract

    assert "uses:" not in paper
    assert "actions/checkout@" not in paper
    assert "actions/setup-python@" not in paper
    assert "actions/upload-artifact@" not in paper
    assert "ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION" not in paper
    assert "Prepare exact source artifact and pre-provisioned Python 3.12 without JavaScript actions" in paper
    assert "SOURCE_ARTIFACT: nexus-persistent-paper-source-${{ github.sha }}" in paper
    assert "SOURCE_ARCHIVE_SHA256: ${{ needs.runtime-wheelhouse.outputs.source_archive_sha256 }}" in paper
    assert "physical_exact_source_artifact_restore=PASS" in paper
    assert "physical_source_transport=digest-pinned-current-run-artifact" in paper
    assert "git init ." not in paper
    assert "git fetch" not in paper
    assert "git checkout" not in paper


def test_physical_source_download_has_bounded_transport_and_extraction_budgets() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    paper = _paper_job(text)
    prepare = paper.split(
        "Prepare exact source artifact and pre-provisioned Python 3.12 without JavaScript actions", 1
    )[1].split("Enforce eligible Bybit network execution plane", 1)[0]

    assert "--retry 3 --retry-all-errors" in prepare
    assert "--connect-timeout 20 --max-time 900" in prepare
    assert "--max-filesize 104857600" in prepare
    assert "source artifact size is outside bounds" in prepare
    assert "row.file_size > 50 * 1024 * 1024" in prepare
    assert "total > 250 * 1024 * 1024" in prepare
    assert "duplicate source archive member" in prepare
    assert "unsafe source archive path" in prepare


def test_physical_source_handoff_is_exact_sha_digest_pinned_and_token_safe() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    paper = _paper_job(text)
    prepare = paper.split(
        "Prepare exact source artifact and pre-provisioned Python 3.12 without JavaScript actions", 1
    )[1].split("Enforce eligible Bybit network execution plane", 1)[0]

    assert 'str(run.get("id")) != os.environ["GITHUB_RUN_ID"]' in prepare
    assert 'run.get("head_sha") != os.environ["GITHUB_SHA"]' in prepare
    assert 'run.get("head_branch") != "main"' in prepare
    assert 'run.get("event") not in {"push", "schedule", "workflow_dispatch"}' in prepare
    assert "expected one exact source artifact" in prepare
    assert "source artifact has no valid GitHub SHA-256 digest" in prepare
    assert "source artifact commit identity mismatch" in prepare
    assert "source archive digest mismatch" in prepare
    assert 'test "$source_sha" = "$GITHUB_SHA"' in prepare

    assert '-H "Authorization: Bearer $GH_TOKEN"' in prepare
    storage_download = prepare.split(
        "# Never send the GitHub bearer token to the signed artifact-storage URL.", 1
    )[1].split('test "$(stat -c', 1)[0]
    assert "Authorization" not in storage_download
    assert "GH_TOKEN" not in storage_download
    assert '"$artifact_url" > "$outer_archive"' in storage_download


def test_every_embedded_python_block_is_syntax_valid() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    blocks = _embedded_python_blocks(text)
    assert len(blocks) == 11
    for start_line, source in blocks:
        compile(source, f"{WORKFLOW}:heredoc:{start_line}", "exec")


def test_failed_prepare_cleanup_uses_only_isolated_physical_roots() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    paper = _paper_job(text)
    header = paper.split("    steps:", 1)[0]
    cleanup = paper.split("Cleanup isolated physical source and state", 1)[1]

    assert "STATE_ROOT:" not in header
    assert '${STATE_ROOT:-$HOME/.local/share/nexus/persistent-paper-state/$GITHUB_RUN_ID}' in cleanup
    assert 'case "$state_root" in "$HOME"/.local/share/nexus/persistent-paper-state/*)' in cleanup


def test_wsl1_python_selection_is_preprovisioned_and_checks_version() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    contract, _ = text.split("  paper-loop:", 1)
    paper = _paper_job(text)
    assert "cache: pip" in contract
    assert "RUNNER_TOOL_CACHE" in paper
    assert "No pre-provisioned CPython 3.12 exists on the physical runner." in paper
    assert "sys.version_info[:2] == (3, 12)" in paper
    assert "cache: pip" not in paper


def test_hosted_wheelhouse_is_digest_pinned_and_physical_install_is_offline() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    hosted = text.split("  runtime-wheelhouse:", 1)[1].split("  paper-loop:", 1)[0]
    paper = _paper_job(text)
    restore = paper.split(
        "Restore digest-pinned current-run runtime wheelhouse without JavaScript actions", 1
    )[1].split("Provision locked runtime dependencies from verified hosted wheelhouse", 1)[0]
    provision = paper.split(
        "Provision locked runtime dependencies from verified hosted wheelhouse", 1
    )[1].split('      - run: \'"$PYTHON_BIN" -m pip check\'', 1)[0]

    assert "runs-on: ubuntu-latest" in hosted
    assert "python -m pip download" in hosted
    assert "--only-binary=:all:" in hosted
    assert "-r requirements.lock" in hosted
    assert "hosted_runtime_wheelhouse_smoke=PASS" in hosted
    assert "scripts/nexus_runtime_wheelhouse.py pack" in hosted
    assert "archive_sha256" in hosted
    assert "compression-level: 0" in hosted

    assert "needs: [contract-test, runtime-wheelhouse]" in paper
    assert "WHEELHOUSE_ARCHIVE_SHA256: ${{ needs.runtime-wheelhouse.outputs.archive_sha256 }}" in paper
    assert "scripts/nexus_runtime_wheelhouse.py restore-current-run" in restore
    assert '--run-id "$GITHUB_RUN_ID"' in restore
    assert '--expected-sha256 "$WHEELHOUSE_ARCHIVE_SHA256"' in restore
    assert 'cache_root="$HOME/.cache/nexus-paper-runtime-wheelhouse-verified"' in paper
    assert "scripts/nexus_runtime_wheelhouse.py pack" in restore
    assert 'find "$cache_dir" -type l' in restore
    assert 'cmp requirements.lock "$cache_dir/requirements.lock"' in restore
    assert "runtime_wheelhouse_verified_cache=HIT" in restore
    assert "runtime_wheelhouse_verified_cache=MISS_POPULATED" in restore
    assert "--no-index" in provision
    assert '--find-links "$wheelhouse"' in provision
    assert "--no-cache-dir" in provision
    assert '--target "$runtime_site"' in provision
    assert "-r requirements.lock" in provision
    assert "--timeout" not in provision
    assert "--retries" not in provision
    assert "--index-url" not in provision
    assert "--extra-index-url" not in provision
    assert "--trusted-host" not in provision
    assert "offline_wheelhouse_bootstrap=PASS" in provision


def test_wsl1_state_restore_uses_python_stdlib_not_unprovisioned_cli_tools() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    paper = _paper_job(text)
    restore = paper.split("Restore newest persistent Paper state", 1)[1].split(
        "Advance public closed-candle Paper portfolio loop", 1
    )[0]
    assert "urllib.request" in restore
    assert "zipfile.ZipFile" in restore
    assert "Authorization" in restore
    assert "unsafe artifact path" in restore
    assert "gh api" not in restore
    assert "unzip -q" not in restore


def test_state_restore_never_forwards_github_token_to_artifact_storage_redirect() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    paper = _paper_job(text)
    restore = paper.split("Restore newest persistent Paper state", 1)[1].split(
        "Advance public closed-candle Paper portfolio loop", 1
    )[0]
    assert "class NoRedirect" in restore
    assert "urllib.request.build_opener(NoRedirect)" in restore
    assert "artifact redirect missing Location" in restore
    assert 'parsed.scheme != "https"' in restore
    assert "Never" in restore and "GitHub bearer token" in restore
    storage_block = restore.split("storage_request =", 1)[1].split(
        "with urllib.request.urlopen(storage_request", 1
    )[0]
    assert "User-Agent" in storage_block
    assert "Authorization" not in storage_block
    assert "token" not in storage_block


def test_physical_state_handoff_is_bounded_chunked_digest_checked_and_hosted_persisted() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    paper = _paper_job(text)
    persist = text.split("  persist-state:", 1)[1]

    assert "Package Paper state for hosted artifact persistence" in paper
    assert "state_archive_chunk_count" in paper
    assert "state_archive_b85_len" in paper
    for index in range(18):
        assert f"state_archive_chunk_{index}" in paper
        assert f"needs.paper-loop.outputs.state_archive_chunk_{index}" in persist
    assert "state_archive_sha256" in paper
    assert "persistent-state-handoff.tar.xz" in paper
    assert "base64.b85encode" in paper
    assert "estimated_output_utf16_bytes = len(compact) * 2 + 16_384" in paper
    assert "estimated_output_utf16_bytes > 1_048_576" in paper
    assert "chunk_size = 30_000" in paper
    assert "1 <= len(chunks) <= 18" in paper
    assert "800_000" in paper
    assert "state_archive_codec=b85-pairs-v1" in paper
    assert "import lzma" in paper
    assert 'tarfile.open(output, "w:xz", preset=9 | lzma.PRESET_EXTREME)' in paper
    assert "zipfile.ZIP_LZMA" not in paper
    assert "zipfile.ZIP_DEFLATED" not in paper

    assert "STATE_ARCHIVE_B64" not in persist
    assert "STATE_ARCHIVE_CHUNK_COUNT" in persist
    assert "STATE_ARCHIVE_B85_LEN" in persist
    assert "len(compact) != (length + 1) // 2" in persist
    assert "base64.b85decode" in persist
    assert "Paper state handoff chunk exceeds bound or is missing" in persist
    assert "Unexpected trailing Paper state handoff chunk" in persist
    assert "STATE_ARCHIVE_SHA256" in persist
    assert 'hashlib.sha256(raw).hexdigest() != os.environ["STATE_ARCHIVE_SHA256"]' in persist
    assert "unsafe state handoff path" in persist
    assert 'tarfile.open(archive_path, "r:xz")' in persist
    assert "hosted_state_handoff_verification=PASS" in persist
    assert "nexus-persistent-paper-trading-state" in persist


def test_legacy_base85_handoff_boundary_documents_previous_failure() -> None:
    # With the 4 KiB metadata reserve used by the workflow, Base85 payloads
    # remain safe through 417,792 compressed bytes. The live state is packed
    # with XZ preset 9 + EXTREME before this guard is evaluated.
    bounded_archive_bytes = 417_792
    payload = (bytes(range(251)) * 1_665)[:bounded_archive_bytes]
    encoded_b85 = base64.b85encode(payload)

    assert len(payload) == bounded_archive_bytes
    assert len(encoded_b85) * 2 + 4_096 <= 1_048_576
    assert base64.b85decode(encoded_b85) == payload

    overflow = payload + b"x"
    assert len(base64.b85encode(overflow)) * 2 + 4_096 > 1_048_576


def test_persistent_loop_permissions_are_read_only_and_authority_is_fail_closed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    permission_block = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permission_block
    assert "actions: read" in permission_block
    assert "write" not in permission_block
    for marker in (
        'assert snapshot["paper_only"] is True',
        'assert snapshot["live_trading_authority"] is False',
        'assert snapshot["private_credentials_used"] is False',
        'assert snapshot["automatic_strategy_promotion"] is False',
        'assert snapshot["deterministic_risk_final_authority"] is True',
        'assert snapshot["trading_engine_complete"] is False',
        'assert isinstance(snapshot["regime_selected_rebalance_operational"], bool)',
        'assert isinstance(snapshot["performance_health_feedback_operational"], bool)',
        'assert isinstance(snapshot["strategy_discovery_health_trigger_requested"], bool)',
    ):
        assert marker in text


def test_persistent_loop_contract_suite_covers_full_lifecycle_risk_health_and_discovery() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for test_path in (
        "tests/test_bybit_public_klines.py",
        "tests/test_nexus_bybit_same_interval_chunk_fallback.py",
        "tests/test_nexus_persistent_paper_trading_loop.py",
        "tests/test_nexus_runtime_wheelhouse.py",
        "tests/test_nexus_regime_selected_position_rebalance.py",
        "tests/test_nexus_regime_selected_exposure_increase.py",
        "tests/test_nexus_strategy_discovery_health_trigger.py",
        "tests/test_nexus_demo_strategy_matrix.py",
        "tests/test_nexus_demo_paper_position_maintenance.py",
        "tests/test_nexus_demo_paper_lifecycle_persistence.py",
        "tests/test_nexus_paper_performance_pipeline.py",
        "tests/test_nexus_demo_regime_cycle.py",
        "tests/test_nexus_regime_paper_lane.py",
        "tests/test_nexus_regime_strategy_selector.py",
        "tests/test_nexus_regime_strategy_runtime.py",
        "tests/test_nexus_strategy_paper_supervisor.py",
        "tests/test_nexus_strategy_discovery_controller.py",
    ):
        assert test_path in text


def test_lifecycle_implementation_paths_retrigger_the_persistent_runtime() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for path in (
        '"bybit_public_klines.py"',
        '"nexus_bybit_same_interval_chunk_fallback.py"',
        '"nexus_regime_selected_position_rebalance.py"',
        '"nexus_regime_selected_exposure_increase.py"',
        '"nexus_strategy_discovery_health_trigger.py"',
    ):
        assert text.count(path) >= 2


# Semantic no-op: exact-main physical Paper trigger after user-context WSL recovery.
# Semantic no-op: exact-main physical Paper trigger after watchdog generation 2 recovery.
# Semantic no-op: exact-main physical Paper trigger after watchdog-managed child generation 3 recovery.
# Semantic no-op: exact-main physical Paper trigger after managed-child liveness generation 4 recovery.
