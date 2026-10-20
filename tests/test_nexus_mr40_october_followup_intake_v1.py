import gzip,hashlib,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import nexus_mr40_october_followup_intake_v1 as intake

class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.start=1790812800000
    def tearDown(self):self.tmp.cleanup()
    def source(self,rows=None,header=None):
        if rows is None:rows=[f"{i+1},{self.start+i*intake.STEP},100,1,buy,0" for i in range(6)]
        path=self.root/"BTCUSDT_2026-10-01.csv.gz"
        with gzip.open(path,"wt",encoding="utf-8",newline="") as out:
            out.write(",".join(header or intake.HEADER)+"\n"+"\n".join(rows)+"\n")
        return path,hashlib.sha256(path.read_bytes()).hexdigest()
    def test_full_day_six_observed_bars(self):
        path,sha=self.source();result=intake.aggregate(path,"2026-10-01",sha)
        self.assertEqual(result["rows_validated"],6);self.assertEqual(len(result["rows"]),6)
        self.assertEqual(result["rows"][0],[self.start,"100.0","100.0","100.0","100.0","1.0"])
    def test_documented_five_name_header_preserves_rpi_field(self):
        path,sha=self.source(header=intake.HEADER[:-1])
        self.assertEqual(intake.aggregate(path,"2026-10-01",sha)["rows_validated"],6)
    def test_missing_bucket_is_not_imputed(self):
        path,sha=self.source(rows=[f"{i+1},{self.start+i*intake.STEP},100,1,buy,0" for i in range(5)])
        with self.assertRaises(ValueError):intake.aggregate(path,"2026-10-01",sha)
    def test_sha_substitution_is_rejected(self):
        path,_=self.source()
        with self.assertRaises(ValueError):intake.aggregate(path,"2026-10-01","0"*64)
    def test_duplicate_trade_is_rejected(self):
        rows=[f"1,{self.start+i*intake.STEP},100,1,buy,0" for i in range(6)]
        path,sha=self.source(rows)
        with self.assertRaises(ValueError):intake.aggregate(path,"2026-10-01",sha)
    def test_wrong_day_is_rejected(self):
        path,sha=self.source()
        with self.assertRaises(ValueError):intake.aggregate(path,"2026-10-02",sha)
    def test_malformed_rpi_is_rejected(self):
        rows=[f"{i+1},{self.start+i*intake.STEP},100,1,buy,2" for i in range(6)]
        path,sha=self.source(rows)
        with self.assertRaises(ValueError):intake.aggregate(path,"2026-10-01",sha)
    def test_corrupt_gzip_crc_is_rejected(self):
        path,_=self.source();raw=bytearray(path.read_bytes());raw[-8]^=1;path.write_bytes(raw)
        with self.assertRaises((OSError,EOFError)):
            intake.aggregate(path,"2026-10-01",hashlib.sha256(raw).hexdigest())

if __name__=="__main__":unittest.main()
