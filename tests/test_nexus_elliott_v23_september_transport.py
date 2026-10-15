"""V23 September 2026 isolated public archive transport safety checks; no GET."""
import gzip
import sys
import tempfile
import unittest
from pathlib import Path

P=Path(__file__).resolve().parents[1]/"docs"/"evidence"/"elliott-v23-september-20261015"
sys.path.insert(0,str(P))
import capture_september_monthly as v23


class TestV23SeptemberTransport(unittest.TestCase):
    def test_fixed_market_scope_and_authority(self):
        self.assertEqual(v23.MONTH,"2026-09")
        self.assertEqual(v23.PAIR,("BTCUSDT","ETHUSDT"))
        self.assertEqual(v23.ROOT_URL,"https://public.bybit.com/spot")
        self.assertTrue(v23.RESEARCH_ONLY)
        self.assertFalse(v23.LIVE_ENABLED)
        self.assertFalse(v23.AUTO_DEMO)
        self.assertEqual(v23.ORDERS_PLACED,0)

    def test_existing_root_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname)/"exists"
            root.mkdir()
            marker=root/"keep.txt"
            marker.write_text("protected")
            with self.assertRaises(FileExistsError):
                v23.capture(root)
            self.assertEqual(marker.read_text(),"protected")

    def test_valid_stream_integrity_and_counts(self):
        with tempfile.TemporaryDirectory() as dirname:
            source=Path(dirname)/"synthetic.gz"
            with gzip.open(source,"wb") as stream:
                stream.write(b"id,timestamp,price,volume,side\n")
                stream.write(b"t,1785600000000,100,0.1,Buy\n"*2000)
            result=v23.verify_gzip_stream(source)
            self.assertEqual(result["newline_count"],2001)
            self.assertTrue(result["full_gzip_crc_and_footer_checked"])

    def test_truncated_footer_rejected(self):
        with tempfile.TemporaryDirectory() as dirname:
            source=Path(dirname)/"incomplete.gz"
            with gzip.open(source,"wb") as stream:
                stream.write(b"id,timestamp,price,volume,side\n")
                stream.write(b"t,1785600000000,100,0.1,Buy\n"*2000)
            source.write_bytes(source.read_bytes()[:-8])
            with self.assertRaises((EOFError,OSError)):
                v23.verify_gzip_stream(source)

if __name__=="__main__":
    unittest.main()
