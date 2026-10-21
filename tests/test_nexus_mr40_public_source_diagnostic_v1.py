import importlib.util
from io import BytesIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("source_diagnostic_test", ROOT / "research/nexus_mr40_public_source_diagnostic_v1.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class Raw(BytesIO):
    def read(self, amount, decode_content=True):
        return super().read(amount)


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self.headers = {"Content-Type": "application/json", "Server": "CloudFront"}
        self.raw = Raw(body)
        self.request = SimpleNamespace(body=None)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def content(self):
        return self._content

    def json(self):
        return json.loads(self.content)


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


class DiagnosticTests(unittest.TestCase):
    def invoke(self, responses, now=None):
        session = Session(responses)
        with tempfile.TemporaryDirectory() as tmp, patch.object(probe.requests, "Session", return_value=session), patch.object(probe, "spot_stream_probe", return_value={"attempted": True, "fresh_quote": False}) as stream, patch.object(probe.time, "time", return_value=now or 1792569601):
            report = probe.run(ROOT / "bybit_public_klines.py", Path(tmp) / "out.json")
            return report, session.calls, stream.call_count

    def test_country_restriction_stops_before_alternate_host_or_stream(self):
        body = b'{\n error:The Amazon CloudFront distribution is configured to block access from your country\n}'
        report, calls, streams = self.invoke([Response(403, body)])
        self.assertTrue(report["explicit_restriction"])
        self.assertEqual(report["http_observations"][0]["classification"], "edge_country_restricted")
        self.assertEqual(len(calls), 1)
        self.assertEqual(streams, 0)
        self.assertFalse(report["source_ready"])
        self.assertFalse(report["actual_demo_started"])
        self.assertNotIn("data", calls[0][1])
        self.assertNotIn("json", calls[0][1])

    def test_unclassified_rejection_is_bounded_to_two_official_hosts(self):
        report, calls, streams = self.invoke([Response(403, b"opaque denial"), Response(403, b"opaque denial")])
        self.assertEqual([c[0] for c in calls], ["https://api.bybit.com/v5/market/kline", "https://api.bytick.com/v5/market/kline"])
        self.assertFalse(report["source_ready"])
        self.assertEqual(streams, 1)

    def test_valid_response_discards_forming_bar_and_still_does_not_start_demo(self):
        now = 1792569601
        current = int(now * 1000) // probe.STEP * probe.STEP
        rows = [[str(t), "100", "101", "99", "100", "1", "100"] for t in reversed(range(current - 181 * probe.STEP, current + probe.STEP, probe.STEP))]
        payload = {"retCode": 0, "time": int(now * 1000), "result": {"category": "spot", "symbol": "BTCUSDT", "list": rows}}
        report, calls, _ = self.invoke([Response(200, json.dumps(payload).encode())], now)
        self.assertTrue(report["source_ready"])
        self.assertEqual(report["http_observations"][0]["closed_bars"], 181)
        self.assertEqual(len(calls), 1)
        self.assertFalse(report["actual_demo_started"])
        self.assertEqual(report["exchange_orders"], 0)

    def test_rate_rejection_stops_without_stream(self):
        report, calls, streams = self.invoke([Response(429, b"rate limited")])
        self.assertFalse(report["source_ready"])
        self.assertTrue(report["explicit_restriction"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(streams, 0)

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(probe.requests, "Session") as session:
            output = Path(tmp) / "out.json"
            output.write_text("preserved")
            with self.assertRaisesRegex(ValueError, "overwrite"):
                probe.run(ROOT / "bybit_public_klines.py", output)
            self.assertEqual(output.read_text(), "preserved")
            session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
