import json
from http import HTTPStatus
from pathlib import Path

from web_dashboard import (
    GatewayConfig,
    dispatch_get,
    load_mission_control,
    load_series,
    load_summary,
)


def write_reports(root: Path, count: int = 2) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "_data_readiness.json").write_text(
        json.dumps({"total_series": count, "ready_series": 1, "blocked_series": max(0, count - 1), "all_ready": count == 1}),
        encoding="utf-8",
    )
    rows = ["symbol,timeframe,ready_for_research,readiness_reason"]
    for index in range(count):
        rows.append(f"asset_{index},hour1,{'True' if index == 0 else 'False'},{'ready' if index == 0 else 'integrity_failed'}")
    (root / "_data_readiness.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_mission_control(data_root: Path) -> dict:
    payload = {
        "contract_version": "nexus.mission-control.read.v1",
        "mission": {"mission_id": "m1", "title": "Mission", "status": "RUNNING", "priority": 90, "deadline_at": "2026-08-17T10:00:00Z", "state_digest": "a" * 64},
        "queue": {"counts": {"RUNNING": 1, "READY": 2}, "total": 3},
        "agents": ["agent-a", "agent-b"],
        "runners": ["runner-1"],
        "local_node": "online",
        "data": "ready",
        "providers": "ready",
        "paper": "paper-only",
        "circuits": {"provider": False, "data": False, "strategy": False, "risk": False},
        "limits": {"resource_limited": False, "budget_limited": False},
        "notifications": [],
    }
    root = data_root.parent / "mission_control"
    root.mkdir(parents=True, exist_ok=True)
    (root / "_mission_control.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_health_discloses_local_read_only_gateway_mode(tmp_path: Path):
    response = dispatch_get("/health", tmp_path)
    assert response.status == HTTPStatus.OK
    assert response.payload["contract_version"] == "nexus.dashboard.read.v1"
    assert response.payload["mode"] == "read-only"
    assert response.payload["gateway"] == {
        "contract_version": "nexus.gateway.v1",
        "access_mode": "local",
        "remote_access_enabled": False,
        "auth_required": False,
        "read_only": True,
    }


def test_health_discloses_remote_without_exposing_token(tmp_path: Path):
    config = GatewayConfig(
        mode="remote",
        host="0.0.0.0",
        port=8443,
        allowed_hosts=("nexus.example.test",),
        allowed_origins=("https://nexus.example.test",),
        access_token="x" * 32,
        tls_cert=Path("cert.pem"),
        tls_key=Path("key.pem"),
    )
    payload = dispatch_get("/health", tmp_path, config).payload
    assert payload["gateway"]["access_mode"] == "remote"
    assert payload["gateway"]["remote_access_enabled"] is True
    assert payload["gateway"]["auth_required"] is True
    assert "x" * 32 not in json.dumps(payload)


def test_summary_returns_generated_json_and_metadata(tmp_path: Path):
    write_reports(tmp_path)
    payload = load_summary(tmp_path)
    assert payload["summary"]["total_series"] == 2
    assert payload["metadata"]["source"] == "_data_readiness.json"
    assert payload["metadata"]["stale_possible"] is True


def test_missing_and_malformed_summary_fail_closed(tmp_path: Path):
    assert dispatch_get("/api/readiness/summary", tmp_path).status == HTTPStatus.SERVICE_UNAVAILABLE
    (tmp_path / "_data_readiness.json").write_text("not-json", encoding="utf-8")
    response = dispatch_get("/api/readiness/summary", tmp_path)
    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.payload["error"] == "report_unavailable"


def test_series_is_paginated_and_filterable(tmp_path: Path):
    write_reports(tmp_path, 5)
    payload = load_series(tmp_path, limit=2, offset=1)
    assert payload["count"] == 2
    assert payload["total"] == 5
    assert payload["series"][0]["symbol"] == "asset_1"
    assert payload["pagination"] == {"limit": 2, "offset": 1, "total": 5, "next_offset": 3}

    filtered = dispatch_get("/api/readiness/series?symbol=asset_0&timeframe=hour1&limit=1&offset=0", tmp_path)
    assert filtered.status == HTTPStatus.OK
    assert filtered.payload["count"] == 1
    assert filtered.payload["series"][0]["readiness_reason"] == "ready"


def test_unknown_empty_repeated_or_out_of_range_query_fails_closed(tmp_path: Path):
    write_reports(tmp_path)
    routes = (
        "/api/readiness/series?path=secret.txt",
        "/api/readiness/series?symbol=",
        "/api/readiness/series?symbol=a&symbol=b",
        "/api/readiness/series?limit=201",
        "/api/readiness/series?offset=100001",
        "/api/readiness/summary?symbol=a",
    )
    for route in routes:
        response = dispatch_get(route, tmp_path)
        assert response.status == HTTPStatus.BAD_REQUEST, route
        assert response.payload["error"] == "invalid_query"


def test_request_target_size_is_bounded(tmp_path: Path):
    config = GatewayConfig(max_request_target_bytes=256)
    response = dispatch_get("/api/readiness/series?symbol=" + "a" * 400, tmp_path, config)
    assert response.status == HTTPStatus.REQUEST_URI_TOO_LONG
    assert response.payload["error"] == "request_target_too_long"


def test_unknown_filter_value_returns_empty_collection(tmp_path: Path):
    write_reports(tmp_path)
    response = dispatch_get("/api/readiness/series?symbol=missing", tmp_path)
    assert response.status == HTTPStatus.OK
    assert response.payload["count"] == 0
    assert response.payload["total"] == 0
    assert response.payload["series"] == []


def test_mission_control_projection_is_served_read_only(tmp_path: Path):
    data_root = tmp_path / "market"
    data_root.mkdir()
    expected = write_mission_control(data_root)
    loaded = load_mission_control(data_root)
    assert loaded["mission_control"] == expected
    response = dispatch_get("/api/mission-control", data_root)
    assert response.status == HTTPStatus.OK
    assert response.payload["mission_control"]["contract_version"] == "nexus.mission-control.read.v1"
    assert response.payload["mission_control"]["queue"]["total"] == 3
    assert response.payload["gateway"]["read_only"] is True


def test_mission_control_missing_incompatible_or_oversized_report_fails_closed(tmp_path: Path):
    data_root = tmp_path / "market"
    data_root.mkdir()
    assert dispatch_get("/api/mission-control", data_root).status == HTTPStatus.SERVICE_UNAVAILABLE

    payload = write_mission_control(data_root)
    payload["contract_version"] = "wrong"
    report = data_root.parent / "mission_control" / "_mission_control.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    response = dispatch_get("/api/mission-control", data_root)
    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
    assert "incompatible" in response.payload["detail"]

    report.write_text("x" * 1_000_001, encoding="utf-8")
    response = dispatch_get("/api/mission-control", data_root)
    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
    assert "bounded size" in response.payload["detail"]


def test_unknown_route_returns_versioned_json_404(tmp_path: Path):
    response = dispatch_get("/api/unknown", tmp_path)
    assert response.status == HTTPStatus.NOT_FOUND
    assert response.payload["contract_version"] == "nexus.dashboard.read.v1"
    assert response.payload["error"] == "not_found"
    assert response.payload["path"] == "/api/unknown"
    assert response.payload["gateway"]["read_only"] is True


def test_every_api_response_declares_read_contract(tmp_path: Path):
    write_reports(tmp_path)
    for route in ("/health", "/api/readiness/summary", "/api/readiness/series", "/api/unknown"):
        assert dispatch_get(route, tmp_path).payload["contract_version"] == "nexus.dashboard.read.v1"
