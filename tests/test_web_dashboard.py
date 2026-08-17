import json
from http import HTTPStatus
from pathlib import Path

from web_dashboard import dispatch_get, load_series, load_summary


def write_reports(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "_data_readiness.json").write_text(
        json.dumps(
            {
                "total_series": 2,
                "ready_series": 1,
                "blocked_series": 1,
                "all_ready": False,
            }
        ),
        encoding="utf-8",
    )
    (root / "_data_readiness.csv").write_text(
        "symbol,timeframe,ready_for_research,readiness_reason\n"
        "btc_usdt,hour1,True,ready\n"
        "eth_usdt,hour4,False,integrity_failed\n",
        encoding="utf-8",
    )


def test_health_is_stable_and_read_only(tmp_path: Path):
    response = dispatch_get("/health", tmp_path)

    assert response.status == HTTPStatus.OK
    assert response.payload == {
        "status": "ok",
        "service": "lbank-research-readiness-dashboard",
        "mode": "read-only",
        "contract_version": "nexus.dashboard.read.v1",
    }


def test_summary_returns_generated_json_and_metadata(tmp_path: Path):
    write_reports(tmp_path)

    payload = load_summary(tmp_path)

    assert payload["summary"]["total_series"] == 2
    assert payload["metadata"]["source"] == "_data_readiness.json"
    assert payload["metadata"]["stale_possible"] is True


def test_missing_summary_fails_closed(tmp_path: Path):
    response = dispatch_get("/api/readiness/summary", tmp_path)

    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.payload["error"] == "report_unavailable"


def test_malformed_summary_fails_closed(tmp_path: Path):
    (tmp_path / "_data_readiness.json").write_text("not-json", encoding="utf-8")

    response = dispatch_get("/api/readiness/summary", tmp_path)

    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.payload["error"] == "report_unavailable"


def test_series_csv_is_exposed_as_json_rows(tmp_path: Path):
    write_reports(tmp_path)

    payload = load_series(tmp_path)

    assert payload["count"] == 2
    assert payload["series"][0]["symbol"] == "btc_usdt"
    assert payload["metadata"]["source"] == "_data_readiness.csv"


def test_series_filters_are_exact_and_combined(tmp_path: Path):
    write_reports(tmp_path)

    response = dispatch_get(
        "/api/readiness/series?symbol=btc_usdt&timeframe=hour1",
        tmp_path,
    )

    assert response.status == HTTPStatus.OK
    assert response.payload["count"] == 1
    assert response.payload["series"][0]["readiness_reason"] == "ready"


def test_unknown_filter_value_returns_empty_collection(tmp_path: Path):
    write_reports(tmp_path)

    response = dispatch_get("/api/readiness/series?symbol=missing", tmp_path)

    assert response.status == HTTPStatus.OK
    assert response.payload["count"] == 0
    assert response.payload["series"] == []


def test_query_cannot_select_an_arbitrary_file(tmp_path: Path):
    write_reports(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("do-not-expose", encoding="utf-8")

    response = dispatch_get(
        "/api/readiness/series?path=secret.txt&symbol=btc_usdt",
        tmp_path,
    )

    assert response.status == HTTPStatus.OK
    assert "do-not-expose" not in json.dumps(response.payload)


def test_unknown_route_returns_json_404(tmp_path: Path):
    response = dispatch_get("/api/unknown", tmp_path)

    assert response.status == HTTPStatus.NOT_FOUND
    assert response.payload == {"contract_version": "nexus.dashboard.read.v1", "error": "not_found", "path": "/api/unknown"}


def test_every_api_response_declares_read_contract(tmp_path: Path):
    write_reports(tmp_path)
    for route in ("/health", "/api/readiness/summary", "/api/readiness/series", "/api/unknown"):
        assert dispatch_get(route, tmp_path).payload["contract_version"] == "nexus.dashboard.read.v1"
