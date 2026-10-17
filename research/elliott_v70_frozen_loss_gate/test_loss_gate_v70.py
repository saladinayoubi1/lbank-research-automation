"""V70 legacy research economics admission and provenance invariants."""
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from loss_gate_v70 import (
    assess_legacy_economics,audit_files,
    RESEARCH_ONLY,ENTRY_SIGNAL,PAPER_ELIGIBLE,LIVE_ENABLED
)

PARTS=("train","validation","historically_inspected_test")
PROFILES=("conservative","stress")
def rows(value):
    return {p+"|"+s:{"net":Decimal(str(value))}
            for p in PARTS for s in PROFILES}
def total(cheap="3",stress="2"):
    return {"conservative":{"net":Decimal(cheap),"friction":Decimal("2")},
            "stress":{"net":Decimal(stress),"friction":Decimal("4")}}

class V70LegacyLossGateTests(unittest.TestCase):
    def test_train_winner_cannot_overrule_bad_validation(self):
        p=rows(2)
        p["train|conservative"]["net"]=Decimal(40)
        p["validation|conservative"]["net"]=Decimal(-1)
        r=assess_legacy_economics(p,total("50","35"),3)
        self.assertEqual(r["status"],"REJECT_PROMOTION_OUT_OF_SAMPLE_HISTORICAL_LOSSES")
    def test_bad_historical_test_blocks_promotion(self):
        p=rows(2)
        p["historically_inspected_test|conservative"]["net"]=Decimal(-1)
        r=assess_legacy_economics(p,total(),3)
        self.assertEqual(r["status"],"REJECT_PROMOTION_OUT_OF_SAMPLE_HISTORICAL_LOSSES")
    def test_cost_stress_blocks_promotion(self):
        p=rows(2)
        r=assess_legacy_economics(p,total("4","-2"),3)
        self.assertEqual(r["status"],"REJECT_PROMOTION_AFTER_MODELED_COSTS")
    def test_historically_positive_still_not_unseen_validation(self):
        r=assess_legacy_economics(rows(2),total("4","2"),3)
        self.assertEqual(r["status"],"REQUIRES_UNSEEN_PROSPECTIVE_VALIDATION_NOT_ELIGIBLE")
    def test_bad_frozen_v37_report_bytes_rejected(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            paths=[]
            for name in ("trace","result","qa","receipt"):
                path=root/(name+".json")
                path.write_text('{"forged":true}',encoding="utf8")
                paths.append(path)
            with self.assertRaisesRegex(ValueError,"IMMUTABLE_V37_REPORT_HASH_MISMATCH"):
                audit_files(*paths)
    def test_no_order_authority(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or LIVE_ENABLED)

if __name__=="__main__":unittest.main()
