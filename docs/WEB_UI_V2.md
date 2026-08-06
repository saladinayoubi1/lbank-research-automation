# Web dashboard UI v2

## Scope

This browser interface is local, read-only, and research-only. It consumes only:

- `GET /api/readiness/summary`
- `GET /api/readiness/series`
- `GET /health`

It has no authentication secrets, private exchange API calls, write actions, order handling, or production-readiness claim.

## Run

Generate readiness reports, then run:

```bash
python web_ui_server.py --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`.

## States

The UI explicitly displays loading, success, empty, malformed-response, and unavailable-API states. API and UI responses use `Cache-Control: no-store`.

## Tests

```bash
python -m pytest -q tests/test_web_ui.py
```

The test module is dependency-free beyond the repository test environment and is intended to run unchanged on Linux, Windows, and macOS.

## Rollback

Rollback is file-isolated and does not require a data migration:

1. Stop `web_ui_server.py`.
2. Revert the commits from PR #84 or remove `web_ui/`, `web_ui_server.py`, `tests/test_web_ui.py`, and this document.
3. Continue using the original `web_dashboard.py` API directly.
4. Regenerate no data; this change never mutates readiness reports or pipeline state.

Rollback success is confirmed when `python web_dashboard.py` serves the original read-only API and the UI route is no longer present.
