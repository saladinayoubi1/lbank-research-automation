import copy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import nexus_portfolio_v3_forward_executor as e


def artificial_market():
    ts = pd.Series(pd.date_range("2022-12-01", "2027-01-17", freq="4h", tz="UTC", inclusive="left"))
    k = np.arange(len(ts), dtype=float)
    close = np.column_stack([100*np.exp(.00012*k+.08*np.sin(k/71)),
                             50*np.exp(.00010*k+.10*np.sin(k/59))])
    close[8800:] *= .55
    opens = np.vstack([close[:1], close[:-1]]) * (1+.0003*np.sin(k[:, None]))
    return {"symbols": ["btc_usdt", "eth_usdt"], "timestamps": ts,
            "open": opens, "close": close, "high": np.maximum(opens, close)*1.001,
            "low": np.minimum(opens, close)*.999}


@contextmanager
def elapsed():
    with patch.object(e.source, "now_utc", return_value=datetime(2027, 1, 18, tzinfo=timezone.utc)):
        yield


class ForwardExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market = artificial_market()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.inputs = (self.root/"context", self.root/"archive", self.root/"capture", self.root/"source-qa.json")
        self.binding = {"synthetic_fixture_only": True}

    def produce(self):
        with elapsed(), patch.object(e, "load_inputs", return_value=(self.market, self.binding)):
            return e.run(*self.inputs, self.root/"producer.json")

    def audit(self, obj, suffix="qa"):
        path = self.root/(suffix+"-receipt.json")
        obj = copy.deepcopy(obj)
        obj["digest"] = e.source.digest({k:v for k,v in obj.items() if k != "digest"})
        path.write_text(json.dumps(obj, allow_nan=False), encoding="utf-8")
        with elapsed(), patch.object(e, "load_inputs", return_value=(self.market, self.binding)):
            return e.verify(*self.inputs, path, self.root/(suffix+".json"))

    def test_closed_horizon_precedes_all_input_io_and_output_creation(self):
        with patch.object(e.source, "now_utc", return_value=datetime(2026,10,20,tzinfo=timezone.utc)), \
             patch.object(e.source, "read_json", side_effect=AssertionError("input read")), \
             patch.object(e, "load_inputs", side_effect=AssertionError("source read")):
            for operation in (
                lambda: e.run(*self.inputs, self.root/"a.json"),
                lambda: e.verify(*self.inputs, self.root/"receipt.json", self.root/"b.json"),
                lambda: e.future_source(self.inputs[2], self.inputs[3], {}),
            ):
                with self.assertRaises(e.source.FutureRawSourceError):
                    operation()
        with patch.object(e.source, "now_utc", return_value=datetime(2026,10,20,tzinfo=timezone.utc)), \
             patch.object(e.source, "read_json", side_effect=AssertionError("source read")):
            with self.assertRaises(e.source.FutureRawSourceError):
                e.load_inputs(*self.inputs, {})
        self.assertEqual(list(self.root.iterdir()), [])

    def test_fixed_contract_rejects_edited_contract_and_executable(self):
        plan, spec = e.checked_contract()
        self.assertEqual(plan["candidate_id"], "b4e4a2c33304aec1")
        self.assertEqual(len(spec["comparators"]), 6)
        for name in (e.CONTRACT, *plan["code_and_contract_sha256_lf"]):
            p = self.root/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((e.ROOT/name).read_bytes())
        path = self.root/e.CONTRACT
        changed = copy.deepcopy(plan); changed["candidate_id"] = "other"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaises(e.ForwardExecutorError):
            e.checked_contract(self.root)
        path.write_bytes((e.ROOT/e.CONTRACT).read_bytes())
        with (self.root/"bybit_portfolio_search_v3.py").open("ab") as f:
            f.write(b"\n# altered\n")
        with self.assertRaises(e.ForwardExecutorError):
            e.checked_contract(self.root)

    def test_full_matrix_and_independent_qa_without_original_functions(self):
        result = self.produce()
        self.assertEqual(sum(map(len, result["cells"].values())), 18)
        self.assertEqual(len(result["targets"]), 9048)
        self.assertFalse(result["independent_financial_qa_complete"])
        original_calls = ("build_structural_state", "construct_weights", "realized_vol", "exact_backtest")
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name in original_calls:
                stack.enter_context(patch.object(e.engine, name, side_effect=AssertionError("producer reused")))
            qa = self.audit(result)
        self.assertEqual(qa["cells_checked"], 18)
        self.assertTrue(qa["independent_signal_qa_complete"])
        self.assertTrue(qa["independent_financial_qa_complete"])
        for key in ("economic_edge_established", "paper_eligible", "live_enabled", "financial_dispatch_authorized"):
            self.assertIs(qa[key], False)
        self.assertEqual(qa["orders"], 0)
        self.assertIs(qa["independent_worker_lease_verified"], False)
        for rows in result["cells"].values():
            self.assertEqual(len(rows["cash_only"]["trace"]["fills"]), 0)
            self.assertGreater(rows["passive_BTC_Spot"]["metrics"]["fill_count"], 0)
            self.assertTrue(rows["existing_dual_rotation_dd20"]["metrics"]["causal_risk_audit"]["no_reentry_after_exit"])

    def test_rehashed_incomplete_or_extra_matrix_and_cost_substitution_fail(self):
        original = self.produce()
        variants = []
        a=copy.deepcopy(original); del a["cells"]["conservative"]; variants.append(a)
        a=copy.deepcopy(original); del a["cells"]["conservative"]["cash_only"]; variants.append(a)
        a=copy.deepcopy(original); a["cells"]["conservative"]["extra"]={}; variants.append(a)
        a=copy.deepcopy(original); a["cost_profiles"]["conservative"]["fee_bps"]=0; variants.append(a)
        a=copy.deepcopy(original); a["paper_eligible"]=True; variants.append(a)
        a=copy.deepcopy(original); a["orders"]=False; variants.append(a)
        a=copy.deepcopy(original); a["producer_sha256_lf"]="0"*64; variants.append(a)
        a=copy.deepcopy(original); a["source_bindings"]={"detached":True}; variants.append(a)
        for number, obj in enumerate(variants):
            with self.subTest(number=number), self.assertRaises(e.ForwardExecutorError):
                self.audit(obj, "bad"+str(number))

    def test_rehashed_target_and_global_phase_mutation_fail(self):
        original = self.produce()
        a=copy.deepcopy(original); a["targets"][8508][0]=.123
        b=copy.deepcopy(original); b["review_mask"]=np.roll(b["review_mask"], 1).tolist()
        c=copy.deepcopy(original); c["review_mask"][0]=1
        d=copy.deepcopy(original); d["targets"][0]=[False,False]
        f=copy.deepcopy(original); f["targets"][0]=["0.0","0.0"]
        for number,obj in enumerate((a,b,c,d,f)):
            with self.subTest(number=number), self.assertRaises(e.ForwardExecutorError):
                self.audit(obj, "signal"+str(number))

    def test_rehashed_fill_and_mark_corruption_reaches_independent_rejection(self):
        original = self.produce()
        from research.portfolio_v3_forward_independent_qa import IndependentQAError
        for number, kind in enumerate(("price", "time", "mark")):
            obj=copy.deepcopy(original)
            row=obj["cells"]["conservative"]["existing_dual_rotation_unmodified"]
            self.assertTrue(row["trace"]["fills"])
            if kind=="price": row["trace"]["fills"][0]["price_usdt"]*=1.01
            if kind=="time": row["trace"]["fills"][0]["executed_at_utc"]="2026-10-18T00:00:00+00:00"
            if kind=="mark": row["trace"]["equity_marks"][3]["cash_usdt"]+=1
            with self.subTest(kind=kind), self.assertRaises(IndependentQAError):
                self.audit(obj, "money"+str(number))

    def test_output_is_write_once(self):
        self.produce()
        with elapsed(), patch.object(e, "load_inputs", side_effect=AssertionError("source reopened")):
            with self.assertRaises(e.ForwardExecutorError):
                e.run(*self.inputs, self.root/"producer.json")

    def test_join_preserves_prefix_and_rejects_missing_shifted_or_invalid_tail(self):
        n=8508
        historical={k:(v.iloc[:n].copy() if k=="timestamps" else v[:n].copy())
                    for k,v in self.market.items() if k!="symbols"}
        historical["symbols"]=list(self.market["symbols"])
        bars={}
        for j,symbol in enumerate(e.source.SYMBOLS):
            bars[symbol]=[{"timestamp":self.market["timestamps"].iloc[k].isoformat(),
                           **{f:str(self.market[f][k,j]) for f in e.context.PRICE_KEYS}}
                          for k in range(n,9048)]
        joined=e.join_future(historical,bars)
        for name in e.context.PRICE_KEYS:
            np.testing.assert_array_equal(joined[name],self.market[name])
        variants=[]
        a=copy.deepcopy(bars); a["BTCUSDT"].pop(); variants.append(a)
        a=copy.deepcopy(bars); a["ETHUSDT"][0]["timestamp"]=a["ETHUSDT"][1]["timestamp"]; variants.append(a)
        a=copy.deepcopy(bars); a["BTCUSDT"][0]["low"]="1e10"; variants.append(a)
        for number,changed in enumerate(variants):
            with self.subTest(number=number), self.assertRaises((e.ForwardExecutorError,e.context.ContextError)):
                e.join_future(historical,changed)

    def source_fixture(self):
        identity=e.source.request_identity()
        files=[];cells={};bars={s:[] for s in e.source.SYMBOLS}
        for number,(symbol,day) in enumerate(e.source.jobs()):
            item={"symbol":symbol,"date":day,"raw_gzip_bytes":1024,"raw_trade_rows":12,
                  "raw_file_sha256":format(number+1,"064x"),"receipt_sha256":format(number+1000,"064x")}
            files.append(item)
            produced=[]
            for k in range(6):
                stamp=(datetime.fromisoformat(day+"T00:00:00+00:00")+timedelta(hours=4*k)).isoformat()
                values={f:100. for f in e.context.PRICE_KEYS};values["volume"]=1.
                produced.append({"timestamp":stamp,**values})
                bars[symbol].append({"timestamp":stamp,**{f:str(v) for f,v in values.items()},
                                     "raw_file_sha256":item["raw_file_sha256"],"receipt_sha256":item["receipt_sha256"]})
            cells[(symbol,day)]=({"fully_observed_4h_bars":produced},item)
        summary={**identity,"request_digest":e.source.digest(identity),"files":files,
                 "completed_files":180,"independent_full_tick_qa_complete":False,
                 "provider_payload_exchange_signed":False,"external_host_attestation_verified":False,
                 "raw_gzip_bytes":180*1024,"raw_trade_rows":180*12}
        summary["digest"]=e.source.digest(summary)
        qa={"schema":"nexus.portfolio-v3-forward-official-raw-independent-qa.v1",
            "policy_digest":e.source.POLICY_DIGEST,"capture_digest":summary["digest"],
            "collector_and_qa_wrapper_sha256_lf":identity["collector_sha256_lf"],
            "independent_decimal_code_sha256_lf":e.source.sha_file(Path(e.source.independent.__file__),lf=True),
            "candidate_id":"b4e4a2c33304aec1","source_route":identity["source_route"],
            "start_utc":identity["start_utc"],"end_exclusive_utc":identity["end_exclusive_utc"],
            "verified_files":180,"verified_4h_bars_per_asset":540,"orders":0,
            "all_ticks_independently_reconstructed":True,"source_eligible_for_separate_research_handoff":True,
            "provider_payload_exchange_signed":False,"external_host_attestation_verified":False,
            "financial_executor_handoff_still_required":True,"strategy_backtest_performed":False,
            "financial_dispatch_authorized":False,"ready_for_strategy_result_or_paper":False,
            "paper_eligible":False,"live_enabled":False,"files":files,"bars":bars,
            "raw_gzip_bytes":180*1024,"raw_trade_rows":180*12}
        qa["digest"]=e.source.digest(qa)
        return identity,summary,qa,cells

    def test_source_consumer_rechecks_all_days_and_rejects_rehashed_bar_authority(self):
        identity,summary,qa,cells=self.source_fixture()
        plan,_=e.checked_contract()
        def read(path,*args): return qa if path==self.inputs[3] else summary
        def cell(root,symbol,day,request,now):
            self.assertEqual(request,identity)
            return cells[(symbol,day)]
        with elapsed(), patch.object(e.source,"checked_digest",side_effect=read), \
             patch.object(e.source,"read_json",return_value=identity), \
             patch.object(e.source,"check_cell",side_effect=cell) as checks:
            bars,binding=e.future_source(self.inputs[2],self.inputs[3],plan)
            self.assertEqual(checks.call_count,180)
            self.assertEqual(binding["future_daily_files_rehashed"],180)
            self.assertEqual(len(bars["BTCUSDT"]),540)
            qa["bars"]["BTCUSDT"][0]["close"]="101"
            qa["digest"]=e.source.digest({k:v for k,v in qa.items() if k!="digest"})
            with self.assertRaises(e.ForwardExecutorError):
                e.future_source(self.inputs[2],self.inputs[3],plan)
            qa["bars"]["BTCUSDT"][0]["close"]="100.0"
            qa["paper_eligible"]=True
            qa["digest"]=e.source.digest({k:v for k,v in qa.items() if k!="digest"})
            with self.assertRaises(e.ForwardExecutorError):
                e.future_source(self.inputs[2],self.inputs[3],plan)

    def test_historical_receipt_must_be_the_pinned_preparation(self):
        plan,_=e.checked_contract()
        with patch.object(e.source,"checked_digest",return_value={"digest":"0"*64}), \
             patch.object(e.context,"load_market_bundle",side_effect=AssertionError("unsealed bundle opened")):
            with self.assertRaises(e.ForwardExecutorError):
                e.historical_context(self.inputs[0],self.inputs[1],plan)


if __name__=="__main__":
    unittest.main()
