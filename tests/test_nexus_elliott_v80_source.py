"""Synthetic fail-closed QA for official independent Binance source intake."""
import csv
import io
import unittest
import zipfile
from datetime import datetime, timezone
from research.elliott_v80_independent_binance_source import source_audit_v80 as v

DAY = "2024-03-01"
NAME = "BTCUSDT-1m-2024-03-01.csv"

def sample_rows():
    start=int(datetime(2024,3,1,tzinfo=timezone.utc).timestamp()*1000)
    return [[str(start+i*60000),"10","12","9","11","1",str(start+i*60000+59999),
             "11","2","0.5","5.5","0"] for i in range(1440)]

def packed(rows, name=NAME):
    buff=io.BytesIO()
    with zipfile.ZipFile(buff,"w",compression=zipfile.ZIP_DEFLATED) as z:
        txt=io.StringIO()
        csv.writer(txt,lineterminator="\n").writerows(rows)
        z.writestr(name,txt.getvalue())
    return buff.getvalue()

class SourceAuditV80Test(unittest.TestCase):
    def test_valid_source(self):
        rows,digest=v.read_rows(packed(sample_rows()),NAME,DAY)
        self.assertEqual(len(rows),1440)
        self.assertEqual(len(digest),64)

    def test_minute_gap_rejected(self):
        rows=sample_rows()
        rows[20][0]=str(int(rows[20][0])+60000)
        with self.assertRaises(AssertionError):
            v.read_rows(packed(rows),NAME,DAY)

    def test_invalid_high_low_rejected(self):
        rows=sample_rows()
        rows[12][2]="8"
        with self.assertRaises(AssertionError):
            v.read_rows(packed(rows),NAME,DAY)

    def test_zip_member_name_rejected(self):
        with self.assertRaises(AssertionError):
            v.read_rows(packed(sample_rows(),"wrong.csv"),NAME,DAY)

    def test_microseconds_rejected(self):
        rows=sample_rows()
        rows[0][0]=str(int(rows[0][0])*1000)
        with self.assertRaises(AssertionError):
            v.read_rows(packed(rows),NAME,DAY)

    def test_aggregated_3m_and_15m(self):
        rows=sample_rows()
        self.assertEqual(len(v.aggregate(rows,3)),480)
        self.assertEqual(len(v.aggregate(rows,15)),96)
        a=v.aggregate(rows,15)[0]
        self.assertEqual(int(a[0]),int(rows[0][0]))
        self.assertEqual(a[1],"10")
        self.assertEqual(float(a[2]),12)
        self.assertEqual(float(a[3]),9)
        self.assertEqual(a[4],"11")
