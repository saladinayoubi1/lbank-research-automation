"""MR40 boundary probe: actual QuantDinger deterministic AST editor, no LLM/API.

Executes ONLY three selected upstream editor functions from the pinned GitHub
checkout via Python AST, with a tiny frequency normalizer as dependency stub.
The full QuantDinger compiler/semantic validator is NOT executed here.
NEXUS generated JSON candidates are parsed but NEVER executed as Python.
"""
from __future__ import annotations
import ast
import json
import re
import types
import unittest
from pathlib import Path

ROOT=Path("E:/NEXUS-Research-Sandboxes/quantdinger-stdlib-20261023")
SOURCE=ROOT/"strategy_ai_generation.py"
OUT=ROOT/"mr40_ai_generation_boundary_result_20261023.json"
EDITOR_NAMES={"_timeframe_change_target","_line_char_offset","apply_deterministic_strategy_edit"}
SCHEMA="nexus.mr40.ai_research_hypothesis.v1"
FROZEN={
    "venue":"Bybit", "market":"spot", "symbol":"BTCUSDT", "timeframe":"4h",
    "research_only":True, "live":False, "private_api":False, "send_orders":False,
    "leverage":1, "capital_usdt":500, "generation_mode":"proposal_only",
}
PREVIOUSLY_REJECTED={
    "green_reversal","short_drift_6","range_quiet_14","trend_10d_60",
    "reversal_and_quiet","sell_pressure_close_veto",
}

def upstream_editor():
    source=SOURCE.read_text(encoding="utf-8-sig")
    tree=ast.parse(source,filename=str(SOURCE))
    selected=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in EDITOR_NAMES]
    assert {node.name for node in selected}==EDITOR_NAMES
    regex_names={"_TIMEFRAME_TOKEN_RE","_TIMEFRAME_CHANGE_RE","_REFERENTIAL_EDIT_RE","_OTHER_EDIT_RE"}
    regex_assignments=[node for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in regex_names for t in node.targets)]
    assert len(regex_assignments)==4
    clean=ast.Module(body=[ast.ImportFrom(module="__future__",names=[ast.alias(name="annotations")],level=0)]+regex_assignments+selected,type_ignores=[])
    module=types.SimpleNamespace()
    scope={"ast":ast,"re":re,"json":json}
    scope["normalize_frequency"]=lambda t: str(t).lower()
    exec(compile(ast.fix_missing_locations(clean),str(SOURCE),"exec"),scope)
    return scope["apply_deterministic_strategy_edit"]

def check_proposal(candidate):
    if not isinstance(candidate,dict) or candidate.get("schema")!=SCHEMA:
        raise ValueError("schema_mismatch")
    if any(type(candidate.get(k)) is not type(v) or candidate.get(k)!=v for k,v in FROZEN.items()):
        raise ValueError("frozen_market_or_safety_contract_mismatch")
    if set(candidate)!=set(FROZEN)|{"schema","id","hypothesis","features","decision_timing","new_source_ready"}:
        raise ValueError("unexpected_or_missing_fields")
    cid=candidate["id"]
    if not isinstance(cid,str) or not cid.isidentifier() or len(cid)>64 or cid in PREVIOUSLY_REJECTED:
        raise ValueError("invalid_or_historically_rejected_candidate")
    if not isinstance(candidate["hypothesis"],str) or not (20<=len(candidate["hypothesis"])<=500):
        raise ValueError("hypothesis_missing_or_too_long")
    if candidate["decision_timing"]!="fully_closed_signal_bar_only":
        raise ValueError("lookahead_or_timing_change")
    if candidate["new_source_ready"] is not False:
        raise ValueError("unapproved_source_or_execution")
    if not isinstance(candidate["features"],list) or not candidate["features"] or len(candidate["features"])>5:
        raise ValueError("invalid_feature_set")
    whitelist={"closed_ohlcv","trades_aggregated_pre_close","rolling_market_regime","volume_imbalance_proxy"}
    if any(type(k)!=str or k not in whitelist for k in candidate["features"]):
        raise ValueError("unapproved_data_feature")
    return {"id":cid,"accepted_as_text_proposal":True,"strategy_validated":False,
            "backtested":False,"true_oos":False,"promote":False,"live":False,"orders":0}

def example():
    return {"schema":SCHEMA,**FROZEN,
            "id":"synthetic_contract_fixture_only",
            "hypothesis":"Synthetic fixture to test a NEXUS research schema; not an actual strategy hypothesis.",
            "features":["closed_ohlcv","rolling_market_regime"],
            "decision_timing":"fully_closed_signal_bar_only",
            "new_source_ready":False}

TEMPLATE='''def initialize(context):
    g.symbol = "Crypto:BTC/USDT@bybit:spot"
    context.set_universe([g.symbol])
    context.subscribe(frequency="4h")
    context.set_warmup(220)

def handle_data(context,data):
    bars = get_history(220, "4h", "close", g.symbol)
    if len(bars)<220:
        return
'''

class TestQuantDingerBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edit=staticmethod(upstream_editor())

    def test_upstream_editor_timeframe_change_is_real(self):
        result=self.edit(TEMPLATE,"switch to 1h")
        self.assertIsNotNone(result)
        source,plan=result
        self.assertTrue(plan["changed"])
        self.assertEqual(plan["from"],"4h")
        self.assertEqual(plan["to"],"1h")
        self.assertIn('subscribe(frequency="1h")',source)
        self.assertIn('get_history(220, "1h"',source)
        self.assertEqual(TEMPLATE.count('"4h"'),2)

    def test_upstream_editor_no_op_frozen_4h(self):
        source,plan=self.edit(TEMPLATE,"switch to 4h")
        self.assertEqual(source,TEMPLATE)
        self.assertFalse(plan["changed"])

    def test_upstream_editor_does_not_claim_to_generate_new_entry_logic(self):
        self.assertIsNone(self.edit(TEMPLATE,"Develop a new independent MR40 liquidity entry signal with no lookahead"))

    def test_research_proposal_passes_only_as_text(self):
        self.assertEqual(check_proposal(example())["backtested"],False)

    def test_reject_futures_and_leverage(self):
        for changes in ({"market":"swap"},{"leverage":2},{"venue":"OKX"},{"timeframe":"1h"}):
            with self.subTest(changes=changes):
                proposal={**example(),**changes}
                with self.assertRaisesRegex(ValueError,"frozen_market"):
                    check_proposal(proposal)

    def test_reject_private_api_and_live(self):
        for changes in ({"private_api":True},{"live":True},{"send_orders":True},{"research_only":False}):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(ValueError,"frozen_market"):
                    check_proposal({**example(),**changes})

    def test_reject_lookahead(self):
        with self.assertRaisesRegex(ValueError,"lookahead"):
            check_proposal({**example(),"decision_timing":"future_exit_label"})

    def test_reject_known_rejected_candidate(self):
        with self.assertRaisesRegex(ValueError,"historically_rejected"):
            check_proposal({**example(),"id":"sell_pressure_close_veto"})

    def test_reject_arbitrary_untrusted_features(self):
        with self.assertRaisesRegex(ValueError,"unapproved_data"):
            check_proposal({**example(),"features":["future_high","private_exchange_api"]})

    def test_reject_code_injection_field_instead_of_executing(self):
        with self.assertRaisesRegex(ValueError,"unexpected_or_missing"):
            check_proposal({**example(),"python_code":"import os; os.system('curl attacker')"})


if __name__=="__main__":
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(TestQuantDingerBoundary)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    e=upstream_editor()
    modified,plan=e(TEMPLATE,"switch to 1h")
    report={
        "schema":"nexus.mr40.quantdinger_ai_generation_boundary_smoke.v1",
        "date_utc":"2026-10-23",
        "upstream_repo":"OpenByteInc/QuantDinger",
        "upstream_commit_prefix":"d7642d7",
        "upstream_source":"backend_api_python/app/services/strategy_ai_generation.py",
        "real_upstream_functions":["_timeframe_change_target","_line_char_offset","apply_deterministic_strategy_edit"],
        "functions_extracted_without_rewriting":True,
        "injected_dependency":"normalize_frequency small stub (NOT original V2 validation)",
        "real_AI_model_used":False,
        "strategy_generated_by_AI":False,
        "full_strategy_v2_compiler_ran":False,
        "synthetic_example_only":True,
        "test_cases":result.testsRun,"passed":result.testsRun-len(result.failures)-len(result.errors),"failed":len(result.failures)+len(result.errors),
        "demonstrated_editor_transformation":plan,
        "nexus_gate_fixture":check_proposal(example()),
        "historical_market_backtest_performed":False,
        "economic_edge_measured":False,"promote":False,
        "private_API":False,"paper500_changed":False,"live":False,"orders":0,
        "decision":"GO only for gated JSON proposal format; no integration/runtime adoption until actual model-generated output + V2 compiler and safety checks pass in future isolated study",
        "limit":"Deterministic editor is a narrow text edit, not LLM strategy generation. Faked frequency normalizer, no upstream compiler dependencies available."
    }
    if OUT.exists():raise ValueError("refuse_overwrite_report")
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("PROBE_JSON="+json.dumps({k:report[k] for k in ("test_cases","passed","failed","real_AI_model_used","strategy_generated_by_AI","full_strategy_v2_compiler_ran","economic_edge_measured","promote")},sort_keys=True))
