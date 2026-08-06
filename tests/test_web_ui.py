import json
from http import HTTPStatus
from pathlib import Path

from web_ui_server import dispatch


def write_ui(root: Path) -> None:
    root.mkdir()
    (root / "index.html").write_text("<main>dashboard</main>", encoding="utf-8")
    (root / "app.js").write_text("loading error empty success", encoding="utf-8")
    (root / "styles.css").write_text("body{}", encoding="utf-8")


def write_reports(root: Path, rows: str = "symbol,timeframe,ready_for_research,readiness_reason\n") -> None:
    root.mkdir()
    (root / "_data_readiness.json").write_text(json.dumps({"total_series": 0, "ready_series": 0, "blocked_series": 0, "all_ready": False}), encoding="utf-8")
    (root / "_data_readiness.csv").write_text(rows, encoding="utf-8")


def test_ui_shell_is_served(tmp_path: Path):
    ui = tmp_path / "ui"
    write_ui(ui)
    response = dispatch("/", tmp_path / "data", ui)
    assert response.status == HTTPStatus.OK
    assert b"dashboard" in response.body


def test_success_api_response_is_delegated(tmp_path: Path):
    data = tmp_path / "data"
    write_reports(data, "symbol,timeframe,ready_for_research,readiness_reason\nbtc_usdt,hour1,True,ready\n")
    response = dispatch("/api/readiness/series", data, tmp_path)
    payload = json.loads(response.body)
    assert response.status == HTTPStatus.OK
    assert payload["count"] == 1


def test_empty_api_response_is_preserved(tmp_path: Path):
    data = tmp_path / "data"
    write_reports(data)
    response = dispatch("/api/readiness/series", data, tmp_path)
    assert json.loads(response.body)["series"] == []


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
