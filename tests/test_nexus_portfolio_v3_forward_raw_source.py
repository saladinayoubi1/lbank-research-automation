"""Synthetic protocol tests; never read or acquire prospective market prices."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import nexus_portfolio_v3_forward_raw_source as source

AFTER = datetime(2027, 1, 18, tzinfo=timezone.utc)
BEFORE = datetime(2026, 10, 20, tzinfo=timezone.utc)


def synthetic_gzip(day):
    midnight = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
    rows = ["id,timestamp,price,volume,side,rpi"]
    for bucket in range(6):
        rows.append(f"{2*bucket+1},{midnight+bucket*14400000},100.1,0.1,buy,0")
        rows.append(f"{2*bucket+2},{midnight+bucket*14400000+1},99.9,0.2,sell,1")
    return gzip.compress(("\n".join(rows) + "\n").encode(), mtime=0)


class Response:
    def __init__(self, url, body, code=200, length=None, history=()):
        self.url, self.body, self.status_code, self.history = url, body, code, history
        self.headers = {"Content-Length": str(len(body) if length is None else length)}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        yield self.body


class Session:
    def __init__(self):
        self.calls, self.headers = [], {}
        self.trust_env = True
        self.mutate_response = lambda response: response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        day = url.rsplit("_", 1)[1].removesuffix(".csv.gz")
        return self.mutate_response(Response(url, synthetic_gzip(day)))


class ForwardRawSourceTests(unittest.TestCase):
    def capture_fixture(self, root, session=None):
        session = session or Session()
        with patch.object(source, "now_utc", return_value=AFTER), \
                patch.object(source, "make_session", return_value=session), \
                patch.object(source.shutil, "disk_usage", return_value=type("Disk", (), {"free": 10**12})()), \
                redirect_stdout(io.StringIO()):
            result = source.capture(root)
        return result, session

    def qa_fixture(self, root, out):
        with patch.object(source, "now_utc", return_value=AFTER):
            return source.verify(root, out)

    def rewrite_json(self, path, mutate, *, hashed=False):
        obj = json.loads(path.read_text(encoding="utf-8"))
        mutate(obj)
        if hashed:
            obj["digest"] = source.digest({k: v for k, v in obj.items() if k != "digest"})
        path.write_text(json.dumps(obj), encoding="utf-8")
        return obj

    def rebind_cell(self, root, mutate):
        path = root / "receipts/BTCUSDT_2026-10-19.json"
        cell = self.rewrite_json(path, mutate, hashed=True)
        receipt_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        def update(summary):
            summary["files"][0]["receipt_sha256"] = receipt_sha
        self.rewrite_json(root / "capture-summary.json", update, hashed=True)
        return cell

    def test_pinned_policy_and_exact_full_horizon(self):
        policy = source.checked_policy()
        jobs = list(source.jobs())
        self.assertEqual(len(jobs), 180)
        self.assertEqual(len(set(jobs)), 180)
        self.assertEqual(jobs[:2], [("BTCUSDT", "2026-10-19"), ("ETHUSDT", "2026-10-19")])
        self.assertEqual(jobs[-2:], [("BTCUSDT", "2027-01-16"), ("ETHUSDT", "2027-01-16")])
        self.assertFalse(policy["financial_dispatch_authorized"])
        self.assertTrue(policy["original_V5_only_preflight_unchanged"])

    def test_current_time_blocks_capture_and_qa_before_any_source_or_network_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(source, "now_utc", return_value=BEFORE), \
                    patch.object(source, "checked_policy") as policy, \
                    patch.object(source, "read_json") as read, \
                    patch.object(source, "make_session") as network:
                for action in (lambda: source.capture(root / "capture"),
                               lambda: source.verify(root / "capture", root / "qa.json")):
                    with self.assertRaisesRegex(source.FutureRawSourceError, "horizon incomplete"):
                        action()
                self.assertEqual(source.status()["status"], "BLOCKED_FULL_HORIZON_INCOMPLETE")
                policy.assert_not_called(); read.assert_not_called(); network.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_full_synthetic_capture_and_independent_decimal_qa_without_financial_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            summary, session = self.capture_fixture(root / "capture")
            result = self.qa_fixture(root / "capture", root / "qa.json")
            self.assertEqual(len(session.calls), 180)
            self.assertFalse(session.trust_env)
            self.assertEqual(result["capture_digest"], summary["digest"])
            self.assertEqual(result["verified_files"], 180)
            self.assertEqual(result["raw_trade_rows"], 2160)
            self.assertTrue(result["all_ticks_independently_reconstructed"])
            for bars in result["bars"].values():
                self.assertEqual(len(bars), 540)
                self.assertTrue(all(b["volume"] == "0.3" for b in bars))
            for field in ("financial_dispatch_authorized", "ready_for_strategy_result_or_paper",
                          "paper_eligible", "live_enabled", "strategy_backtest_performed",
                          "provider_payload_exchange_signed", "external_host_attestation_verified"):
                self.assertIs(result[field], False)
            for _, args in session.calls:
                self.assertIs(args["verify"], True)
                self.assertIs(args["allow_redirects"], False)
            with self.assertRaisesRegex(source.FutureRawSourceError, "write-once"):
                self.qa_fixture(root / "capture", root / "qa.json")

    def test_resume_rehashes_every_day_and_never_repeats_completed_gets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "capture"
            first, _ = self.capture_fixture(root)
            second, session = self.capture_fixture(root)
            self.assertEqual(first, second)
            self.assertEqual(session.calls, [])
            raw = root / "raw/BTCUSDT_2026-10-19.csv.gz"
            raw.write_bytes(raw.read_bytes() + b"changed")
            with self.assertRaisesRegex(source.FutureRawSourceError, "binding"):
                self.capture_fixture(root)

    def test_rehashed_manifest_cannot_omit_duplicate_or_shift_a_day_or_peer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.capture_fixture(root / "capture")
            path = root / "capture/capture-summary.json"
            original = path.read_bytes()
            mutations = [lambda o: o["files"].pop(),
                         lambda o: o["files"].__setitem__(1, o["files"][0]),
                         lambda o: o["files"][0].__setitem__("date", "2026-10-18"),
                         lambda o: o["files"][0].__setitem__("symbol", "XRPUSDT")]
            for mutate in mutations:
                with self.subTest(mutate=mutate):
                    path.write_bytes(original)
                    self.rewrite_json(path, mutate, hashed=True)
                    with self.assertRaisesRegex(source.FutureRawSourceError, "manifest"):
                        self.qa_fixture(root / "capture", root / "qa.json")

    def test_rehashed_http_claims_cannot_replace_exact_tls_source_or_collection_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            capture_root = root / "capture"
            self.capture_fixture(capture_root)
            cell_path = capture_root / "receipts/BTCUSDT_2026-10-19.json"
            summary_path = capture_root / "capture-summary.json"
            cell, summary = cell_path.read_bytes(), summary_path.read_bytes()
            mutations = [lambda o: o["acquisition"].__setitem__("tls_verification_required", False),
                         lambda o: o["acquisition"].__setitem__("final_url", "https://other.test/file"),
                         lambda o: o["acquisition"].__setitem__("redirects_allowed", True),
                         lambda o: o["acquisition"].__setitem__("status_code", 403),
                         lambda o: o["acquisition"].__setitem__("started_utc", BEFORE.isoformat()),
                         lambda o: o["acquisition"].__setitem__("completed_utc", (AFTER+timedelta(days=1)).isoformat()),
                         lambda o: o.__setitem__("live_enabled", True)]
            for mutate in mutations:
                with self.subTest(mutate=mutate):
                    cell_path.write_bytes(cell); summary_path.write_bytes(summary)
                    self.rebind_cell(capture_root, mutate)
                    with self.assertRaises(source.FutureRawSourceError):
                        self.qa_fixture(capture_root, root / "qa.json")

    def test_independent_decimal_rejects_rehashed_price_volume_time_and_count_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            capture_root = root / "capture"
            self.capture_fixture(capture_root)
            cell_path = capture_root / "receipts/BTCUSDT_2026-10-19.json"
            summary_path = capture_root / "capture-summary.json"
            cell, summary = cell_path.read_bytes(), summary_path.read_bytes()
            mutations = [("open", 111), ("volume", 1), ("timestamp", "2026-10-19T04:00:00Z"),
                         ("trades", 3), ("first_trade_ms", 0)]
            for field, value in mutations:
                with self.subTest(field=field):
                    cell_path.write_bytes(cell); summary_path.write_bytes(summary)
                    self.rebind_cell(capture_root, lambda o: o["fully_observed_4h_bars"][0].__setitem__(field, value))
                    with self.assertRaisesRegex(source.FutureRawSourceError, "Independent|bucket"):
                        self.qa_fixture(capture_root, root / "qa.json")

    def test_http_denial_redirect_and_short_body_never_become_complete_source(self):
        mutations = [lambda r: Response(r.url, r.body, code=403),
                     lambda r: Response("https://other.test/file", r.body),
                     lambda r: Response(r.url, r.body, history=[object()]),
                     lambda r: Response(r.url, r.body, length=len(r.body)+1)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for number, mutate in enumerate(mutations):
                with self.subTest(number=number):
                    session = Session(); session.mutate_response = mutate
                    target = root / str(number)
                    with self.assertRaises(source.FutureRawSourceError):
                        self.capture_fixture(target, session)
                    self.assertEqual(len(session.calls), 1)
                    self.assertFalse((target / "capture-summary.json").exists())

    def test_total_raw_byte_budget_is_enforced_before_writing_excess_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "capture"
            with patch.object(source, "MAX_TOTAL", 1000):
                with self.assertRaises(source.FutureRawSourceError):
                    self.capture_fixture(root)
            retained = sum(p.stat().st_size for p in (root / "raw").iterdir())
            self.assertLessEqual(retained, 1000)
            self.assertFalse((root / "capture-summary.json").exists())

    def test_changed_policy_code_or_request_and_existing_unreceipted_raw_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            policy = source.read_json(source.ROOT / source.POLICY)
            policy["end_exclusive_utc"] = "2026-10-20T00:00:00Z"
            with patch.object(source, "read_json", return_value=policy):
                with self.assertRaisesRegex(source.FutureRawSourceError, "policy changed"):
                    source.checked_policy()
            with patch.object(source, "sha_file", return_value="0" * 64):
                with self.assertRaisesRegex(source.FutureRawSourceError, "Pinned source"):
                    source.checked_policy()
            self.capture_fixture(root / "capture")
            request = root / "capture/capture-request.json"
            self.rewrite_json(request, lambda o: o.__setitem__("collector_sha256_lf", "0" * 64))
            with self.assertRaisesRegex(source.FutureRawSourceError, "Resume request"):
                self.capture_fixture(root / "capture")
            with self.assertRaisesRegex(source.FutureRawSourceError, "Captured request"):
                self.qa_fixture(root / "capture", root / "qa.json")
            (root / "capture/receipts/BTCUSDT_2026-10-19.json").unlink()
            source_request = source.request_identity()
            request.write_text(json.dumps(source_request), encoding="utf-8")
            with self.assertRaisesRegex(source.FutureRawSourceError, "explicit recovery"):
                self.capture_fixture(root / "capture")

    def test_duplicate_json_and_nonfinite_numbers_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "receipt.json"
            for content in ('{"digest":"x","digest":"y"}', '{"x":NaN}'):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(source.FutureRawSourceError):
                    source.read_json(path)

    def test_optimized_python_cannot_skip_independent_decimal_assertions(self):
        code = ("from pathlib import Path\n"
                "from scripts import nexus_portfolio_v3_forward_raw_source as s\n"
                "s.now_utc = lambda: s.END\n"
                "try:\n"
                " s.verify(Path('absent-source'), Path('absent-qa.json'))\n"
                "except s.FutureRawSourceError as e:\n"
                " print(str(e))\n"
                "else:\n"
                " raise RuntimeError('optimized QA was accepted')\n")
        result = subprocess.run([sys.executable, "-O", "-c", code], cwd=source.ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("assertions enabled", result.stdout)


if __name__ == "__main__":
    unittest.main()
