"""V89 deterministic source-intake and fail-closed QA; no network in tests."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from research.elliott_v89_source_intake import intake_v89 as v89


def daily_csv(day="2024-07-01"):
    ms=int(datetime.strptime(day,"%Y-%m-%d")
           .replace(tzinfo=timezone.utc).timestamp()*1000)
    return "".join(
        f"{ms+i*60000},100,102,99,101,1,{ms+i*60000+59999},100,2,0,0,0\n"
        for i in range(1440)).encode("utf-8")


def make_zip(csv_member, body):
    output=io.BytesIO()
    with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(csv_member,body)
    return output.getvalue()


def official_pair(entry, csv_body=None):
    body=daily_csv(entry["utc_day"]) if csv_body is None else csv_body
    z=make_zip(entry["csv_member"],body)
    check=(hashlib.sha256(z).hexdigest()+"  "+entry["zip_file"]+"\n").encode()
    return z,check


class V89OfficialSourceIntakeTests(unittest.TestCase):
    def test_preregistration_hash_exact(self):
        manifest=v89.locked_manifest()
        self.assertEqual(len(manifest["scheduled_inputs"]),28)

    def test_committed_lock_in_ancestry(self):
        v89.verify_committed_lock()

    def test_decimal_type_and_nonfinite(self):
        self.assertEqual(v89.strict_decimal("1.025"),Decimal("1.025"))
        for source in ("NaN","Infinity","-Infinity","bad",""):
            with self.subTest(raw=source):
                with self.assertRaises(ValueError):
                    v89.strict_decimal(source)

    def test_complete_1440_source_rows(self):
        got=v89.validate_csv(daily_csv(),"2024-07-01")
        self.assertEqual(got["row_count"],1440)
        self.assertEqual(got["minimum_low"],"99")
        self.assertEqual(got["maximum_high"],"102")

    def test_missing_closing_bar_rejected(self):
        with self.assertRaisesRegex(ValueError,"1440"):
            v89.validate_csv(daily_csv().splitlines(keepends=True)[0],"2024-07-01")

    def test_timestamp_gap_and_duplicate_rejected(self):
        rows=daily_csv().decode().splitlines()
        rows[500]=rows[499]
        with self.assertRaisesRegex(ValueError,"missing, duplicated"):
            v89.validate_csv(("\n".join(rows)+"\n").encode(),"2024-07-01")

    def test_close_time_mismatch_rejected(self):
        rows=daily_csv().decode().splitlines()
        parts=rows[25].split(",")
        parts[6]=str(int(parts[6])-1)
        rows[25]=",".join(parts)
        with self.assertRaisesRegex(ValueError,"ill-closed"):
            v89.validate_csv(("\n".join(rows)+"\n").encode(),"2024-07-01")

    def test_extra_column_rejected(self):
        rows=daily_csv().decode().splitlines()
        rows[6]+=",1"
        with self.assertRaisesRegex(ValueError,"12-column"):
            v89.validate_csv(("\n".join(rows)+"\n").encode(),"2024-07-01")

    def test_nan_ohlc_rejected(self):
        rows=daily_csv().decode().splitlines()
        parts=rows[8].split(","); parts[2]="NaN"; rows[8]=",".join(parts)
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            v89.validate_csv(("\n".join(rows)+"\n").encode(),"2024-07-01")

    def test_negative_base_volume_rejected(self):
        rows=daily_csv().decode().splitlines()
        cols=rows[5].split(","); cols[5]="-1"; rows[5]=",".join(cols)
        with self.assertRaisesRegex(ValueError,"negative base volume"):
            v89.validate_csv(("\n".join(rows)+"\n").encode(),"2024-07-01")

    def test_checksum_filename_checked_exactly(self):
        entry=v89.locked_manifest()["scheduled_inputs"][0]
        raw=("a"*64+"  "+entry["zip_file"]+"\n").encode()
        self.assertEqual(v89.checksum_name_body(raw,entry["zip_file"]),"a"*64)
        with self.assertRaisesRegex(ValueError,"filename"):
            v89.checksum_name_body(raw,"ETHUSDT-1m-2024-07-01.zip")

    def test_zip_checksum_and_csv_member_positive(self):
        entry=v89.locked_manifest()["scheduled_inputs"][0]
        body,manifest=official_pair(entry)
        result=v89.verify_archive(entry,body,manifest)
        self.assertTrue(result["verified"])
        self.assertEqual(result["rows_1m"],1440)
        self.assertEqual(result["csv_member_name"],entry["csv_member"])

    def test_zip_tamper_rejected(self):
        entry=v89.locked_manifest()["scheduled_inputs"][0]
        body,manifest=official_pair(entry)
        with self.assertRaisesRegex(ValueError,"CHECKSUM"):
            v89.verify_archive(entry,body+b"x",manifest)

    def test_unexpected_archive_member_rejected(self):
        entry=v89.locked_manifest()["scheduled_inputs"][0]
        body=make_zip("forged.csv",daily_csv())
        check=(hashlib.sha256(body).hexdigest()+"  "+entry["zip_file"]).encode()
        with self.assertRaisesRegex(ValueError,"unexpected ZIP member"):
            v89.verify_archive(entry,body,check)

    def test_zip_with_extra_member_rejected(self):
        entry=v89.locked_manifest()["scheduled_inputs"][0]
        out=io.BytesIO()
        with zipfile.ZipFile(out,"w") as archive:
            archive.writestr(entry["csv_member"],daily_csv())
            archive.writestr("EXTRA.csv",b"more")
        content=out.getvalue()
        check=(hashlib.sha256(content).hexdigest()+"  "+entry["zip_file"]).encode()
        with self.assertRaisesRegex(ValueError,"unexpected ZIP member"):
            v89.verify_archive(entry,content,check)

    def test_exact_local_cache_reused_after_validation(self):
        entry=v89.locked_manifest()["scheduled_inputs"][0]
        body,manifest=official_pair(entry)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/entry["zip_file"]).write_bytes(body)
            (root/entry["official_checksum_file"]).write_bytes(manifest)
            with patch.object(v89,"BASE",root),patch.object(v89,"fetch_bytes",
                                                             side_effect=AssertionError("network forbidden")):
                result=v89.retrieve_one(entry)
                self.assertTrue(result["cached_after_verification"])

    def test_partial_cached_pair_fails_closed(self):
        entry=v89.locked_manifest()["scheduled_inputs"][0]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/entry["zip_file"]).write_bytes(b"partial")
            with patch.object(v89,"BASE",root):
                with self.assertRaisesRegex(ValueError,"partial archived day"):
                    v89.retrieve_one(entry)

    def test_cached_different_source_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"source.bin"
            file.write_bytes(b"before")
            with self.assertRaisesRegex(ValueError,"no overwrite"):
                v89.write_exact(file,b"after")
            self.assertEqual(file.read_bytes(),b"before")

    def test_no_source_outside_28_frozen_names(self):
        entry=copy.deepcopy(v89.locked_manifest()["scheduled_inputs"][0])
        entry["zip_file"]="BTCUSDT-1m-2024-07-15.zip"
        with self.assertRaisesRegex(ValueError,"outside exact"):
            v89.retrieve_one(entry)
