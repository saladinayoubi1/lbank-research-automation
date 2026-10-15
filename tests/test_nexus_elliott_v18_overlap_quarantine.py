"""V18 quarantined source overlap forensic QA, not a provider verification."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"docs"/"evidence"/"elliott-v18-overlap-20261015"
sys.path.insert(0,str(EVIDENCE))

from audit_transcribed_overlap import (
    AUTO_DEMO,LIVE_ENABLED,REPAIRS_APPLIED,RESEARCH_ONLY,
    validate_observed_snapshot,compare_observed_with_frozen,
)
from nexus_elliott_forward_bridge_v18 import FROZEN_SHA, digest_file,PAIR_DIR

SNAPSHOT=json.loads((EVIDENCE/"OBSERVED_PUBLIC_API_TRANSCRIPTION.json").read_text(encoding="utf-8"))


def temp_source(snapshot,folder):
    root=Path(folder)
    observed=validate_observed_snapshot(snapshot)
    expected={}
    for sym,rows in observed.items():
        path=root/"bybit_market"/PAIR_DIR[sym]/"minute15.parquet"
        path.parent.mkdir(parents=True,exist_ok=True)
        frame=pd.DataFrame([
            {"timestamp":pd.Timestamp(ms,unit="ms",tz="UTC"),
             "open":float(vals[0]),"high":float(vals[1]),
             "low":float(vals[2]),"close":float(vals[3]),
             "volume":float(vals[4])}
            for ms,vals in sorted(rows)
        ])
        frame.to_parquet(path,index=False)
        expected[sym]=digest_file(path)
    return root,expected


class V18QuarantinedOverlapTests(unittest.TestCase):
    def test_no_live_mutation_authority(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(AUTO_DEMO)
        self.assertFalse(LIVE_ENABLED)
        self.assertEqual(REPAIRS_APPLIED,0)

    def test_previously_observed_stdout_rows_have_strict_timestamps(self):
        decoded=validate_observed_snapshot(SNAPSHOT)
        self.assertEqual(len(decoded["BTCUSDT"]),8)
        self.assertEqual(len(decoded["ETHUSDT"]),8)

    def test_missing_record_rejected(self):
        snap=copy.deepcopy(SNAPSHOT)
        snap["symbols"]["BTCUSDT"]["list"].pop()
        with self.assertRaisesRegex(ValueError,"exactly 8"):
            validate_observed_snapshot(snap)

    def test_duplicate_and_unsorted_observed_bars_rejected(self):
        for mode in ("duplicate","unsorted"):
            with self.subTest(mode=mode):
                snap=copy.deepcopy(SNAPSHOT)
                rows=snap["symbols"]["BTCUSDT"]["list"]
                if mode=="duplicate":
                    rows[0][0]=rows[1][0]
                else:
                    rows[0],rows[1]=rows[1],rows[0]
                with self.assertRaisesRegex(ValueError,"grid"):
                    validate_observed_snapshot(snap)

    def test_bad_price_rejected(self):
        snap=copy.deepcopy(SNAPSHOT)
        snap["symbols"]["ETHUSDT"]["list"][0][2]="1"
        with self.assertRaisesRegex(ValueError,"OHLC"):
            validate_observed_snapshot(snap)

    def test_zero_or_negative_volume_constraints(self):
        snap=copy.deepcopy(SNAPSHOT)
        snap["symbols"]["ETHUSDT"]["list"][0][5]="0"
        validate_observed_snapshot(snap)
        snap["symbols"]["ETHUSDT"]["list"][0][5]="-1"
        with self.assertRaisesRegex(ValueError,"invalid"):
            validate_observed_snapshot(snap)

    def test_unattested_matching_snapshot_not_promoted_to_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root,hashes=temp_source(SNAPSHOT,temp)
            with patch.dict(FROZEN_SHA,hashes):
                answer=compare_observed_with_frozen(SNAPSHOT,root)
            self.assertEqual(answer["total_ohlcv_field_mismatches"],0)
            self.assertTrue(answer["not_exchange_authenticity_proof"])
            self.assertIn("UNATTESTED",answer["disposition"])
            self.assertFalse(answer["repair_performed"])

    def test_single_price_conflict_detected_and_original_unmodified(self):
        changed=copy.deepcopy(SNAPSHOT)
        changed["symbols"]["BTCUSDT"]["list"][0][1]="62950.9"
        with tempfile.TemporaryDirectory() as temp:
            root,hashes=temp_source(SNAPSHOT,temp)
            before={s:digest_file(root/"bybit_market"/PAIR_DIR[s]/"minute15.parquet")
                    for s in hashes}
            with patch.dict(FROZEN_SHA,hashes):
                outcome=compare_observed_with_frozen(changed,root)
            self.assertEqual(outcome["total_ohlcv_field_mismatches"],1)
            self.assertEqual(outcome["symbols"]["BTCUSDT"]["field_mismatch_counts"]["open"],1)
            self.assertEqual(outcome["disposition"],
                             "BLOCKED_UNRESOLVED_OBSERVED_SOURCE_CONFLICT")
            self.assertFalse(outcome["repair_performed"])
            self.assertEqual(before,{
                s:digest_file(root/"bybit_market"/PAIR_DIR[s]/"minute15.parquet")
                for s in hashes
            })

    def test_frozen_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root,hashes=temp_source(SNAPSHOT,temp)
            fake={**hashes,"BTCUSDT":"0"*64}
            with patch.dict(FROZEN_SHA,fake):
                with self.assertRaisesRegex(AssertionError,"sha mismatch"):
                    compare_observed_with_frozen(SNAPSHOT,root)

    def test_wrong_symbol_or_category_rejected(self):
        snap=copy.deepcopy(SNAPSHOT)
        snap["symbols"]["BTCUSDT"]["category"]="linear"
        with self.assertRaisesRegex(ValueError,"status or category"):
            validate_observed_snapshot(snap)


if __name__=="__main__":
    unittest.main()
