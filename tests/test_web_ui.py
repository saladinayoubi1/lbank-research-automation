import json
from http import HTTPStatus
from pathlib import Path

from web_ui_server import dispatch


def write_ui(root: Path) -> None:
    root.mkdir()
    (root / "index.html").write_text("<main>dashboard integration-cards zotero-items research-evidence</main>", encoding="utf-8")
    (root / "app.js").write_text("/api/integrations/zotero /api/integrations/research loading error empty success", encoding="utf-8")
    (root / "styles.css").write_text("body{}", encoding="utf-8")
    (root / "phase4.css").write_text(".view{}", encoding="utf-8")


def write_reports(root: Path, rows: str = "symbol,timeframe,ready_for_research,readiness_reason\n") -> None:
    root.mkdir()
    (root / "_data_readiness.json").write_text(json.dumps({"total_series": 0, "ready_series": 0, "blocked_series": 0, "all_ready": False}), encoding="utf-8")
    (root / "_data_readiness.csv").write_text(rows, encoding="utf-8")
    integrations = root.parent / "integrations"
    integrations.mkdir()
    (integrations / "zotero_metadata_report_v2.json").write_text(json.dumps({
        "schema_version": "2.0", "mode": "read-only-offline", "item_count": 3,
        "finding_count": 1, "items": [], "duplicates": {"doi": [], "title_year": []},
    }), encoding="utf-8")
    (integrations / "research_evidence_summary.json").write_text(json.dumps({
        "schema_version": "1.1.0", "status": "research-only", "paper_trading_only": True,
        "claims": [{"id": "c1"}], "evidence": [{"domain": "market-structure"}],
        "next_review_due": "2099-01-01",
    }), encoding="utf-8")


def test_ui_shell_is_served(tmp_path: Path):
    ui = tmp_path / "ui"
    write_ui(ui)
    response = dispatch("/", tmp_path / "data", ui)
    assert response.status == HTTPStatus.OK
    assert b"dashboard" in response.body


def test_phase4_stylesheet_is_served_from_explicit_allowlist(tmp_path: Path):
    ui = tmp_path / "ui"
    write_ui(ui)
    response = dispatch("/ui/phase4.css", tmp_path / "data", ui)
    assert response.status == HTTPStatus.OK
    assert response.content_type == "text/css"


def test_success_api_response_is_delegated(tmp_path: Path):
    data = tmp_path / "data"
    write_reports(data, "symbol,timeframe,ready_for_research,readiness_reason\nbtc_usdt,hour1,True,ready\n")
    response = dispatch("/api/readiness/series", data, tmp_path)
    payload = json.loads(response.body)
    assert response.status == HTTPStatus.OK
    assert payload["count"] == 1


def test_browser_contract_exposes_both_integration_summaries(tmp_path: Path):
    data = tmp_path / "data"
    ui = tmp_path / "ui"
    write_reports(data)
    write_ui(ui)
    html = dispatch("/", data, ui)
    script = dispatch("/ui/app.js", data, ui)
    zotero = dispatch("/api/integrations/zotero", data, ui)
    research = dispatch("/api/integrations/research", data, ui)
    assert b"zotero-items" in html.body and b"research-evidence" in html.body
    assert b"/api/integrations/zotero" in script.body and b"/api/integrations/research" in script.body
    assert json.loads(zotero.body)["summary"]["item_count"] == 3
    assert json.loads(research.body)["summary"]["evidence_count"] == 1


def test_empty_api_response_is_preserved(tmp_path: Path):
    data = tmp_path / "data"
    write_reports(data)
    response = dispatch("/api/readiness/series", data, tmp_path)
    assert json.loads(response.body)["series"] == []


def test_phase4_shell_exposes_all_required_read_only_surfaces():
    html = Path("web_ui/index.html").read_text(encoding="utf-8")
    script = Path("web_ui/app.js").read_text(encoding="utf-8")
    surfaces = {"mission", "ai", "research", "strategies", "paper", "portfolio", "risk", "data", "agents", "events", "system"}
    for surface in surfaces:
        assert f'data-view="{surface}"' in html
        assert f'data-surface="{surface}"' in html
    assert "NO LIVE EXECUTION" in html
    assert "Mutation API</span><strong>DISABLED" in html
    assert "selectSurface" in script


def test_phase4_shell_has_explicit_blocked_degraded_and_empty_states():
    html = Path("web_ui/index.html").read_text(encoding="utf-8")
    assert 'status-chip blocked' in html
    assert 'status-chip degraded' in html
    assert 'class="empty-state' in html
    assert "Fail closed" in html


def test_phase4_navigation_fails_safe_for_untrusted_url_fragments():
    script = Path("web_ui/app.js").read_text(encoding="utf-8")
    assert "surfaces.has(name) ? name : 'mission'" in script
    assert 'document.querySelector(`[data-surface=' not in script
    assert "window.addEventListener('popstate'" in script


def test_malformed_api_response_fails_closed(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "_data_readiness.json").write_text("not-json", encoding="utf-8")
    response = dispatch("/api/readiness/summary", data, tmp_path)
    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
    assert json.loads(response.body)["error"] == "report_unavailable"


def test_unavailable_api_response_fails_closed(tmp_path: Path):
    response = dispatch("/api/readiness/summary", tmp_path / "missing", tmp_path)
    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE


def test_missing_ui_asset_is_controlled(tmp_path: Path):
    response = dispatch("/", tmp_path / "data", tmp_path / "missing")
    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
