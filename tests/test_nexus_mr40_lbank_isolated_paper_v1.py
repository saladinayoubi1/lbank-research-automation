import copy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT/relative)
    result = importlib.util.module_from_spec(spec); sys.modules[name] = result; spec.loader.exec_module(result)
    return result


paper = module("isolated_paper_test", "research/nexus_mr40_lbank_isolated_paper_v1.py")
study = module("isolated_paper_study_test", "research/nexus_mr40_lbank_exact30_v1.py")
book = module("isolated_paper_book_test", "research/nexus_lbank_spot_cost_snapshot_v1.py")
sim = module("isolated_paper_sim_test", "paper_exchange_simulator.py")


class IsolatedMR40PaperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = study.load_sources(ROOT)

    def setUp(self):
        self.first = paper.POLICY["history_start_ms"]+240*paper.STEP
        self.source, self.manifest = "a"*40, "b"*64
        self.instrument = {"quantity_step":"0.00001","minimum_quantity":"0.00001","minimum_notional_usdt":"1"}
        self.state = paper.new_state(self.first-paper.STEP+1000,self.source,self.manifest,self.instrument)
        self.books = {"asks":[(Decimal("110.01"),Decimal("1000"))],
                      "bids":[(Decimal("109.99"),Decimal("1000"))]}

    def rows(self, count, exit=False):
        closes = [Decimal(80)+Decimal(i)*40/238 for i in range(239)]
        closes += [Decimal(110) if not exit else Decimal(110)]
        closes += [Decimal(130) if exit else Decimal(110)]*max(0,count-240)
        return [[paper.POLICY["history_start_ms"]+i*paper.STEP,str(c),str(c*Decimal("1.01")),
                 str(c*Decimal("0.99")),str(c),"1"] for i,c in enumerate(closes[:count])]

    def tick(self, state=None, count=240, offset=1000, exit=False):
        when = paper.POLICY["history_start_ms"]+count*paper.STEP+offset
        return paper.advance(state or self.state,self.rows(count,exit),self.books,self.code,book,sim,when,{"fixture":"public-data-test"})

    def test_activation_waits_for_next_future_boundary(self):
        state, status = self.tick(count=239)
        self.assertEqual(status,"waiting_first_boundary")
        self.assertEqual(state["cash"],"500")
        self.assertEqual(state["fills"],[])
        self.assertEqual(state["events"],[])

    def test_real_frozen_signal_enters_once_with_lot_rounding(self):
        state, status = self.tick()
        self.assertEqual(status,"paper_buy")
        self.assertGreater(Decimal(state["quantity"]),0)
        self.assertGreaterEqual(Decimal(state["cash"]),0)
        self.assertEqual(Decimal(state["quantity"])%Decimal("0.00001"),0)
        repeat,_ = self.tick(state,offset=61000)
        self.assertEqual(repeat["fills"],state["fills"])
        self.assertEqual(repeat["events"],state["events"])
        paper.verify(repeat,self.source,self.manifest)

    def test_late_entry_stays_rejected_through_original_episode(self):
        state,action = self.tick(offset=paper.POLICY["max_entry_delay_ms"]+1)
        self.assertEqual(action,"entry_skipped_no_late_entry")
        later,action = self.tick(state,count=241)
        self.assertEqual(action,"entry_skipped_no_late_entry")
        self.assertFalse(later["fills"])

    def test_delayed_natural_exit_uses_current_time_not_backdated_time(self):
        state,_ = self.tick()
        later,action = self.tick(state,count=243,offset=500000,exit=True)
        self.assertEqual(action,"paper_sell")
        self.assertEqual(later["fills"][-1]["reason"],"delayed_signal_exit")
        self.assertEqual(later["fills"][-1]["filled_ms"],self.first+3*paper.STEP+500000)
        self.assertEqual(later["events"][-1]["skipped_prior_boundaries"],2)
        self.assertEqual(len(later["closed_positions"]),1)
        self.assertEqual(Decimal(later["cash"])-500,Decimal(later["realized_pnl"]))
        paper.verify(later,self.source,self.manifest)

    def test_revised_accepted_history_rejects_without_mutating_account(self):
        state,_ = self.tick()
        original = copy.deepcopy(state)
        rows = self.rows(241)
        rows[0][4] = "80.001"
        with self.assertRaisesRegex(ValueError,"history_revised"):
            paper.advance(state,rows,self.books,self.code,book,sim,self.first+paper.STEP+1000,{})
        self.assertEqual(state,original)

    def test_missing_closed_bar_rejected(self):
        rows=self.rows(240);del rows[20]
        with self.assertRaisesRegex(ValueError,"non-contiguous"):
            paper.advance(self.state,rows,self.books,self.code,book,sim,self.first+1000,{})

    def test_unavailable_depth_never_creates_a_fill(self):
        self.books["asks"]=[(Decimal("110.01"),Decimal("0.00001"))]
        with self.assertRaisesRegex(ValueError,"insufficient_visible_depth"):
            self.tick()
        self.assertEqual(self.state["fills"],[])

    def test_balance_and_authority_edits_are_rejected(self):
        state,_=self.tick()
        state["cash"]="500"
        with self.assertRaisesRegex(ValueError,"digest_changed"):
            paper.verify(state,self.source,self.manifest)
        state=paper.seal(state)
        with self.assertRaisesRegex(ValueError,"cashflow_replay"):
            paper.verify(state,self.source,self.manifest)

    def test_source_bundle_hash_change_prevents_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            files={}
            for name in paper.BUNDLE_FILES:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/name,target)
                files[name]=hashlib.sha256(target.read_bytes()).hexdigest()
            raw=paper.canonical({"files":files})
            (root/"SOURCE_MANIFEST.json").write_bytes(raw)
            expected=hashlib.sha256(raw).hexdigest()
            paper.sources(root,expected)
            with (root/paper.BUNDLE_FILES[3]).open("ab") as out:out.write(b"\n")
            with self.assertRaisesRegex(ValueError,"source_file_changed"):
                paper.sources(root,expected)

    def test_persisted_state_roundtrip_keeps_cash_and_event_identity(self):
        state,_=self.tick()
        restored=json.loads(paper.canonical(state))
        paper.verify(restored,self.source,self.manifest)
        later,_=self.tick(restored,count=241)
        self.assertEqual(len(later["fills"]),1)

    def test_missing_state_never_resets_an_existing_activation_to_500(self):
        with tempfile.TemporaryDirectory() as tmp:
            # macOS exposes its temporary directory through /var -> /private/var.
            # Use the real fixture path so the writer reaches the account guard.
            root=Path(tmp).resolve();(root/"activation.json").write_text('{}')
            with mock.patch.object(paper,"sources",return_value=(self.code,book,sim)):
                with self.assertRaisesRegex(ValueError,"no_capital_reset"):
                    paper.run_once(ROOT,root,self.source,self.manifest)
            self.assertFalse((root/"state.json").exists())

    def test_owner_stop_performs_no_public_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/"STOP").write_text('owner request')
            with mock.patch.object(paper,"sources",return_value=(self.code,book,sim)), mock.patch.object(book,"fetch") as fetch:
                result=paper.run_once(ROOT,root,self.source,self.manifest)
            self.assertEqual(result["status"],"stopped_by_owner")
            self.assertFalse(result["activated"])
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
