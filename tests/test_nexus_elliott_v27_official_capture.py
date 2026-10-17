"""V27 official public Spot capture safety boundaries, synthetic network mocks only."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]/"docs"/"evidence"/"elliott-v27-oct09-20261016"
sys.path.insert(0,str(HERE))
import capture_oct09_raw as gate


class Fake403:
    status_code=403
    def __enter__(self): return self
    def __exit__(self,*args): return None


class FakeSession:
    def __init__(self): self.calls=0;self.last=None
    def __enter__(self): return self
    def __exit__(self,*args): return None
    def get(self,url,**kw):
        self.calls+=1
        self.last=(url,kw)
        return Fake403()


class V27PublicSourceCaptureTests(unittest.TestCase):
    def test_research_only_and_fixed_public_source(self):
        self.assertTrue(gate.RESEARCH_ONLY)
        self.assertFalse(gate.AUTO_DEMO)
        self.assertFalse(gate.LIVE_ENABLED)
        self.assertFalse(gate.ORDER_ACCESS)
        self.assertEqual(gate.SOURCE_BASE,"https://public.bybit.com/spot")
        self.assertEqual(gate.SYMBOLS,("BTCUSDT","ETHUSDT"))
        self.assertEqual(gate.DATE,"2026-10-09")

    def test_no_existing_output_mutation_or_http(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/"existing"
            root.mkdir()
            prior=root/"untouched.txt"
            prior.write_text("unchanged")
            with patch.object(gate.requests,"Session") as session:
                with self.assertRaisesRegex(FileExistsError,"fresh"):
                    gate.fetch_into_fresh_dir(root)
                session.assert_not_called()
            self.assertEqual(prior.read_text(),"unchanged")

    def test_provider_403_not_retried_or_redirected(self):
        with tempfile.TemporaryDirectory() as folder:
            session=FakeSession()
            root=Path(folder)/"new"
            with patch.object(gate.requests,"Session",return_value=session):
                with self.assertRaisesRegex(RuntimeError,"HTTP 403"):
                    gate.fetch_into_fresh_dir(root)
            self.assertEqual(session.calls,1)
            self.assertEqual(session.last[0],
                "https://public.bybit.com/spot/BTCUSDT/BTCUSDT_2026-10-09.csv.gz")
            self.assertIs(session.last[1]["allow_redirects"],False)
            self.assertFalse((root/"CAPTURE_RECEIPT.json").exists())
            self.assertEqual(list(root.iterdir()),[])


if __name__=="__main__":
    unittest.main()
