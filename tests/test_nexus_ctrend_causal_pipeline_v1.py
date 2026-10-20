"""Full raw-synthetic-daily -> learned H -> quantized account integration.

Training labels below are manufactured from feature ranks; they carry no
information about cryptocurrency returns and cannot qualify a strategy.
"""
from dataclasses import replace
from decimal import Decimal, localcontext
import json
from pathlib import Path
import unittest
import numpy as np
from scipy.stats import rankdata
from research.nexus_ctrend_causal_features_v1 import feature_snapshot, latest_closed_period, DAY_MS
from research.nexus_ctrend_causal_wallet_v1 import LotSpec, WalletError
from research.nexus_ctrend_causal_pipeline_v1 import (
    AdmissionError, HistoricalReturns, PaperResearchSession, QuoteBatch, COSTS,learn_decision,
)
from test_nexus_ctrend_causal_features_v1 import panel,stamp

class CausalPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=panel(800,40)
        current_end=latest_closed_period(stamp("2020-08-05"))[2]
        ends=[current_end]
        for _ in range(52): ends.append(latest_closed_period(ends[-1]-1)[2])
        ends.reverse()
        snapshots=[feature_snapshot(cls.p,end) for end in ends]
        cls.history=snapshots[:-1];cls.current=snapshots[-1]
        cls.labels=[]
        rng=np.random.default_rng(2172026)
        for s,end in zip(cls.history,ends[1:]):
            # Fabricated relationship to verify learning and pipeline plumbing.
            ranks=(rankdata(s.values[:,0])-1)/39-.5
            values=.04*ranks+rng.normal(scale=.0001,size=40)
            cls.labels.append(HistoricalReturns(s.asset_ids,s.snapshot_sha256,
                s.period_end_ms,end,np.full(40,end,dtype=np.int64),values,
                "synthetic:manufactured-rank-labels-v1"))
        cls.decision=learn_decision(cls.history,cls.labels,cls.current)
        cls.execution=cls.current.decision_time_ms+1000

    def quote(self,offset=0,prices=None):
        prices=prices or {s:"100" for s in self.current.asset_ids}
        return QuoteBatch(self.execution+offset,self.execution+offset,prices,
                          "synthetic:observed-bybit-quotes-v1")

    def specs(self,when=None,minimum="5"):
        return {s:LotSpec("0.0001","0.0001",minimum,self.execution if when is None else when)
                for s in self.current.asset_ids}

    def test_raw_daily_inputs_learn_high_quintile_then_reconcile_account(self):
        d=self.decision
        self.assertEqual(len(d.target_weights),8)
        self.assertIn(0,d.forecast.selected_features)
        with localcontext() as ctx:
            ctx.prec=50
            self.assertEqual(sum(d.target_weights.values()),Decimal(1))
        session=PaperResearchSession()
        report=session.execute(d,self.quote(),self.specs())
        a=report["account"]
        with localcontext() as ctx:
            ctx.prec=200
            self.assertEqual(Decimal(a["post_nav"]),Decimal(500)-Decimal(a["fees"])-Decimal(a["slippage"]))
            # Independent fill and cash arithmetic, without wallet helper calls.
            cash=Decimal(500)
            holdings={}
            for fill in a["fills"]:
                q,p=Decimal(fill["quantity"]),Decimal(fill["fill_price"])
                gross=q*p;fee=gross*Decimal(".001")
                self.assertEqual(gross,Decimal(fill["gross"]))
                self.assertEqual(fee,Decimal(fill["fee"]))
                cash-=gross+fee
                holdings[fill["symbol"]]=q
            self.assertEqual(cash,session.wallet.cash)
            self.assertEqual(holdings,session.wallet.positions)
            self.assertEqual(cash+sum(q*100 for q in holdings.values()),Decimal(a["post_nav"]))
        self.assertGreater(Decimal(a["max_drawdown"]),0)
        self.assertFalse(report["demo_admitted"])
        self.assertFalse(report["financial_backtest_allowed"])
        self.assertEqual(a["orders"],0)
        self.assertFalse(a["live_enabled"])

    def test_no_current_or_future_label_parameter_and_no_real_admission(self):
        with self.assertRaises(TypeError):
            learn_decision(self.history,self.labels,self.current,current_returns=np.ones(40))
        with self.assertRaises(AdmissionError):
            learn_decision(self.history,self.labels,replace(self.current,evidence_class="unverified_real"))
        with self.assertRaises(AdmissionError):
            QuoteBatch(self.execution,self.execution,{"BTCUSDT":"100"},"actual",evidence_class="unverified_real")

    def test_calendar_gaps_stale_histories_and_asset_identity_reject_before_fit(self):
        bad=list(self.history);bad[1]=bad[0]
        with self.assertRaises(AdmissionError): learn_decision(bad,self.labels,self.current)
        with self.assertRaises(AdmissionError): learn_decision(self.history[:-1],self.labels[:-1],self.current)
        badlabels=list(self.labels);badlabels[0]=replace(badlabels[0],feature_snapshot_sha256="0"*64)
        with self.assertRaises(AdmissionError): learn_decision(self.history,badlabels,self.current)
        badlabels=list(self.labels);badlabels[-1]=replace(badlabels[-1],asset_ids=tuple(reversed(self.current.asset_ids)))
        with self.assertRaises(AdmissionError): learn_decision(self.history,badlabels,self.current)

    def test_snapshot_value_tampering_is_detected(self):
        values=self.current.values.copy();values[0,0]+=.01
        with self.assertRaises(AdmissionError):
            learn_decision(self.history,self.labels,replace(self.current,values=values))

    def test_unreleased_past_label_values_are_ignored_without_reranking(self):
        labels=list(self.labels)
        a=labels[-1].available_at_ms.copy();a[0]=self.current.decision_time_ms+DAY_MS
        labels[-1]=replace(labels[-1],available_at_ms=a)
        first=learn_decision(self.history,labels,self.current)
        v=labels[-1].values.copy();v[0]=.99
        labels[-1]=replace(labels[-1],values=v)
        second=learn_decision(self.history,labels,self.current)
        self.assertEqual(first.decision_sha256,second.decision_sha256)
        self.assertEqual(first.forecast.diagnostics["training_rank_digest"],self.decision.forecast.diagnostics["training_rank_digest"])
        self.assertEqual(first.forecast.diagnostics["current_rank_digest"],self.decision.forecast.diagnostics["current_rank_digest"])

    def test_old_quote_replay_and_minimum_order_block_atomically(self):
        session=PaperResearchSession();before=session.wallet.__dict__.copy()
        old=QuoteBatch(self.current.decision_time_ms,self.execution,self.quote().prices,"synthetic:old-quote")
        with self.assertRaises(AdmissionError): session.execute(self.decision,old,self.specs())
        with self.assertRaises(WalletError): session.execute(self.decision,self.quote(),self.specs(minimum="1000"))
        self.assertEqual(session.wallet.__dict__,before)
        self.assertEqual(session.journal,[])
        session.execute(self.decision,self.quote(),self.specs())
        after=session.wallet.journal
        with self.assertRaises(AdmissionError): session.execute(self.decision,self.quote(),self.specs())
        self.assertEqual(session.wallet.journal,after)

    def test_missing_held_mark_and_stale_event_withhold_nav(self):
        session=PaperResearchSession();session.execute(self.decision,self.quote(),self.specs())
        before=session.wallet.journal
        missing=dict(self.quote().prices);del missing[next(iter(session.wallet.positions))]
        with self.assertRaises(WalletError): session.mark(self.quote(1000,missing))
        stale=QuoteBatch(self.execution-1,self.execution+1000,self.quote().prices,"synthetic:stale-event")
        with self.assertRaises(AdmissionError): session.mark(stale)
        self.assertEqual(session.wallet.journal,before)

    def test_compounded_nav_drawdown_and_fixed_cost_profiles(self):
        fees=[]
        for name in COSTS:
            session=PaperResearchSession()
            report=session.execute(self.decision,self.quote(),self.specs(),scenario=name)
            fees.append(Decimal(report["account"]["fees"])+Decimal(report["account"]["slippage"]))
        self.assertTrue(fees[0]<fees[1]<fees[2])
        contract=json.loads((Path(__file__).resolve().parents[1]/"research/ctrend_causal_h_technical_v1.json").read_text())
        for name,(fee,slip) in COSTS.items():
            self.assertEqual(contract["accounting"]["cost_profiles"][name],dict(fee_rate=fee,slippage_rate=slip))
        session=PaperResearchSession();session.execute(self.decision,self.quote(),self.specs())
        peak=session.mark(self.quote(1000,{s:"110" for s in self.current.asset_ids}))
        session.mark(self.quote(2000,{s:"99" for s in self.current.asset_ids}))
        low=session.mark(self.quote(3000,{s:"89.1" for s in self.current.asset_ids}))
        with localcontext() as ctx:
            ctx.prec=50
            expected=1-Decimal(low["nav"])/Decimal(peak["nav"])
        self.assertAlmostEqual(float(low["max_drawdown"]),float(expected),14)
        self.assertGreater(float(low["max_drawdown"]),.189)
        self.assertLessEqual(float(low["max_drawdown"]),.19)

if __name__=="__main__":unittest.main()
