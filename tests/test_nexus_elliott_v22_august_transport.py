"""V22 August raw-gzip streaming validation safety tests; no HTTP requests."""
import gzip
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]/"docs"/"evidence"/"elliott-v22-august-20261015"
sys.path.insert(0,str(HERE))
import capture_august_monthly as cap


class ElliottV22AugustArchiveTests(unittest.TestCase):
    def test_authority_fixed_pairs_month_and_host(self):
        self.assertTrue(cap.RESEARCH_ONLY)
        self.assertFalse(cap.LIVE_ENABLED)
        self.assertFalse(cap.AUTO_DEMO)
        self.assertEqual(cap.ORDERS_PLACED,0)
        self.assertEqual(cap.PAIR,("BTCUSDT","ETHUSDT"))
        self.assertEqual(cap.MONTH,"2026-08")
        self.assertEqual(cap.ROOT_URL,"https://public.bybit.com/spot")

    def test_refuses_existing_folder_before_network(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"existing"
            root.mkdir()
            (root/"keep").write_text("untouched")
            with patch.object(cap.requests,"Session") as fake:
                with self.assertRaisesRegex(FileExistsError,"already exists"):
                    cap.capture(root)
                fake.assert_not_called()
            self.assertEqual((root/"keep").read_text(),"untouched")

    def test_streaming_gzip_crc_valid_and_rows_counted(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"fake.gz"
            with gzip.open(p,"wb") as f:
                f.write(b"id,timestamp,price,size,side\n")
                for i in range(1200):
                    f.write(f"{i},1785542400000,100,1,Buy\n".encode())
            receipt=cap.verify_gzip_stream(p)
            self.assertEqual(receipt["newline_count"],1201)
            self.assertTrue(receipt["full_gzip_crc_and_footer_checked"])
            self.assertIn("timestamp",receipt["first_row_preview"])

    def test_truncated_gzip_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"cut.gz"
            with gzip.open(p,"wb") as f:
                f.write(b"a,b,c\n"+b"1,2,3\n"*3000)
            p.write_bytes(p.read_bytes()[:-8])
            with self.assertRaises((OSError,EOFError)):
                cap.verify_gzip_stream(p)


if __name__=="__main__":
    unittest.main()
