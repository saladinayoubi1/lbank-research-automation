"""Bounded execution/source regressions for the fixed MR40 research replay."""
from __future__ import annotations
import gzip,hashlib,json,math,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"))
import nexus_mean_reversion_40_m2_retest_v1 as m
import prepare_mean_reversion_40_m2_retest_v1 as p
def sample(n=80,start=None):
    start=m.ms("2026-07-01") if start is None else start
    return [[start+i*m.STEP,"100","102","98","100","1"] for i in range(n)]
class ExecutionTests(unittest.TestCase):
    def test_two_sided_fee_formula_and_independent_marks(self):
        rows=sample();sig=[int(2<=i<12) for i in range(80)]
        got=m.simulate(rows,sig,0,80,10,5)
        expected=10000*(1-.0005)/(1+.0005)*(1-.001)/(1+.001)
        self.assertAlmostEqual(got["metrics"]["final_usdt"],expected,places=8)
        ref=m.independent_accounting(rows,sig,0,80,10,5)
        self.assertLess(max(abs(a["equity"]-b) for a,b in zip(got["equity_curve"],ref["equity"])),1e-7)
        self.assertEqual(got["metrics"]["closed_positions"],1)
    def test_close_signal_waits_for_next_open(self):
        rows=sample();sig=[int(i>=3) for i in range(80)]
        out=m.simulate(rows,sig,0,80,10,5)
        self.assertEqual(out["fills"][0]["fill_ms"],rows[4][0])
        self.assertEqual(out["fills"][0]["signal_available_ms"],rows[4][0])
        self.assertEqual(out["fills"][0]["reference"],100)
    def test_no_repeated_dust_orders(self):
        rows=sample();sig=[1]*80
        out=m.simulate(rows,sig,0,80,10,5)
        self.assertEqual(out["metrics"]["fills"],2)
        self.assertEqual(out["metrics"]["terminal_exits"],1)
    def test_terminal_close_costs_and_time_are_explicit(self):
        rows=sample();sig=[1]*80
        result=m.simulate(rows,sig,40,80,10,5)
        exit_=result["fills"][-1]
        self.assertEqual(exit_["reason"],"terminal_close")
        self.assertEqual(exit_["fill_ms"],rows[-1][0]+m.STEP)
        self.assertGreater(exit_["fee_usdt"],0)
        self.assertLess(result["metrics"]["final_usdt"],result["metrics"]["pre_terminal_mark_equity"])
    def test_warm_boundary_and_legacy_first_bar_are_distinct(self):
        rows=sample();sig=[1]*80
        warm=m.simulate(rows,sig,40,80,10,5)
        old=m.simulate(rows,sig,40,80,10,5,skip_first=True)
        self.assertEqual(warm["fills"][0]["bar_index"],40)
        self.assertEqual(old["fills"][0]["bar_index"],41)
    def test_additional_latency_uses_an_older_signal(self):
        rows=sample();sig=[int(i>=3) for i in range(80)]
        out=m.simulate(rows,sig,0,80,10,5,lag=2)
        self.assertEqual(out["fills"][0]["bar_index"],5)
        self.assertEqual(out["fills"][0]["signal_index"],3)
    def test_continuous_monthly_attribution_does_not_flatten(self):
        rows=sample(24,m.ms("2026-07-30"));sig=[1]*24
        out=m.simulate(rows,sig,0,24,10,5)
        self.assertEqual(len(out["monthly_attribution"]),2)
        self.assertEqual(out["metrics"]["closed_positions"],1)
        self.assertEqual(out["metrics"]["terminal_exits"],1)
        self.assertAlmostEqual(sum(x["pnl_usdt"] for x in out["monthly_attribution"]),out["metrics"]["net_pnl_usdt"])
    def test_future_prices_cannot_change_past_target(self):
        rows=sample(180)
        for i,row in enumerate(rows):
            price=100+math.sin(i/3)
            row[1:5]=map(str,(price,price+2,price-2,price))
        first=m.targets(rows);cut=120
        for row in rows[cut:]:
            row[1:5]=[str(float(x)*1.7) for x in row[1:5]]
        self.assertEqual(first[:cut],m.targets(rows)[:cut])
        self.assertEqual(m.targets(rows),m.decimal_targets(rows))
    def test_gap_and_invalid_envelope_are_rejected(self):
        rows=sample()
        with self.assertRaises(ValueError):m.validate_frame(rows[:4]+rows[5:])
        rows[4][2]="99"
        with self.assertRaises(ValueError):m.validate_frame(rows)
class SourceTests(unittest.TestCase):
    def fixture(self,root,mutate=None,truncate=False):
        rows=[[str(i+1),str(m.ms("2026-09-01")+i*m.STEP),"100","1","buy","0"] for i in range(180)]
        if mutate:mutate(rows)
        path=root/"BTCUSDT-2026-09.csv.gz"
        payload="id,timestamp,price,volume,side\n"+"\n".join(",".join(x) for x in rows)+"\n"
        path.write_bytes(gzip.compress(payload.encode(),mtime=0))
        if truncate:path.write_bytes(path.read_bytes()[:-5])
        receipt={"bytes":path.stat().st_size,"sha256":p.sha_file(path),"rows":180}
        return path,receipt
    def test_full_original_six_field_rows_under_five_name_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,receipt=self.fixture(Path(tmp));rows,evidence=p.aggregate_month(path,receipt,"2026-09")
            self.assertEqual(len(rows),180);self.assertEqual(evidence["raw_rows"],180)
    def test_duplicate_ids_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,receipt=self.fixture(Path(tmp),lambda rows:rows[8].__setitem__(0,rows[7][0]))
            with self.assertRaisesRegex(ValueError,"IDs"):p.aggregate_month(path,receipt,"2026-09")
    def test_out_of_month_trade_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,receipt=self.fixture(Path(tmp),lambda rows:rows[-1].__setitem__(1,str(m.ms("2026-10-01"))))
            with self.assertRaisesRegex(ValueError,"month"):p.aggregate_month(path,receipt,"2026-09")
    def test_original_gzip_corruption_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,receipt=self.fixture(Path(tmp),truncate=True)
            with self.assertRaises((EOFError,OSError)):p.aggregate_month(path,receipt,"2026-09")
    def test_digest_tampering_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,receipt=self.fixture(Path(tmp));receipt["sha256"]="0"*64
            with self.assertRaisesRegex(ValueError,"digest"):p.aggregate_month(path,receipt,"2026-09")
if __name__=="__main__":unittest.main()
