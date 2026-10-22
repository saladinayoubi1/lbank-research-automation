"""Synthetic tests of fixed two-day Bybit Spot archival bridge, no REST or orders."""
import unittest
from research.nexus_mr40_bybit_archive_bridge_v1 import DAY_NAMES,epoch,rollup,STEP1


def csv_data(date, skip=None, duplicate=False, scramble=False):
    start=epoch(date)
    lines=["id,timestamp,price,volume,side,rpi"]
    points=[(i,str(i+1)) for i in range(1440) if i!=skip]
    if duplicate:
        points[-1]=(points[-1][0],points[0][1])
    if scramble:
        points[1],points[2]=points[2],points[1]
    for index,ident in points:
        p="100.11" if index%2 else "100.05"
        lines.append(f"{ident},{start+index*STEP1},{p},0.05,buy,0")
    return ("\n".join(lines)+"\n").encode()


class TestMR40SpotBridge(unittest.TestCase):
    def test_exact_1440_minutes_six_4h(self):
        for date in DAY_NAMES:
            rows,detail=rollup(csv_data(date),date)
            self.assertEqual(len(rows),6)
            self.assertEqual(detail["minutes_verified"],1440)
            self.assertEqual(detail["number_of_trades"],1440)
            self.assertTrue(detail["exact_1m_to_4h"])
            self.assertEqual(rows[0][0],epoch(date))
            self.assertEqual(rows[-1][0],epoch(date)+5*14400000)

    def test_minute_gap_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"missing_or_extra_minute"):
            rollup(csv_data(DAY_NAMES[0],skip=500),DAY_NAMES[0])

    def test_archive_trade_id_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError,"duplicate_or_missing_trade_id"):
            rollup(csv_data(DAY_NAMES[0],duplicate=True),DAY_NAMES[0])

    def test_archive_timestamp_out_of_order_rejected(self):
        with self.assertRaisesRegex(ValueError,"nonmonotonic"):
            rollup(csv_data(DAY_NAMES[0],scramble=True),DAY_NAMES[0])

    def test_other_day_cannot_be_spliced(self):
        with self.assertRaisesRegex(ValueError,"wrong_utc_archive_day"):
            rollup(csv_data(DAY_NAMES[0]),DAY_NAMES[1])


if __name__=="__main__":
    unittest.main()
