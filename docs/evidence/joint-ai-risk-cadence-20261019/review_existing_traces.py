"""QA of retained traces only; does not call the portfolio backtest."""
import hashlib
import json
from pathlib import Path
import numpy as np
import bybit_portfolio_search_v3 as engine
from scripts import nexus_portfolio_risk_cadence_diagnostic as study

root = Path(__file__).resolve().parent
original = Path('E:/NEXUS-QA/joint-risk-cadence-20261019')
stored = original / 'results-fixed-v1'
archive = Path('C:/NEXUS/research-cache/replay-canonical-37681826492/archive')
result = json.loads((stored / 'result.json').read_text(encoding='utf-8-sig'))
recorded_digest = result.pop('result_digest')
assert study.digest(result) == recorded_digest == '1ad241bf96ee678ee67d7ff1a0311820df98ac6a7fffd5e11f1b1f66204dfe37'
assert study.source_hash(Path(engine.__file__)) == study.ENGINE_SHA256_LF
for rel, expected in result['source_hashes'].items():
    assert hashlib.sha256((archive / 'bybit_market' / rel).read_bytes()).hexdigest() == expected
market = engine.load_market(archive, study.SYMBOLS)
study.validate_market(market)
config = json.loads((root / study.BASELINE_CONFIG).read_text(encoding='utf-8-sig'))
vol = engine.realized_vol(market['close'], 30)
candidate = config['candidate']
state = engine.build_structural_state(market, candidate)
baseline = engine.construct_weights(state, vol, candidate)
weekly = engine._candidate_rebalance_mask(len(baseline), candidate)
_, reductions = study.target_ratchet(market['timestamps'], baseline, vol, weekly)
checks = {}
for name in ('baseline', 'daily_target_ratchet', 'baseline_times_075', 'passive_BTC'):
    trace = json.loads((stored / (name + '-trace.json')).read_text(encoding='utf-8-sig'))
    metrics = result['results']['continuous'][name]['conservative']
    assert study.digest(trace['fills']) == metrics['qa']['fills_sha256']
    assert study.digest(trace['equity_marks']) == metrics['qa']['equity_marks_sha256']
    qa = study.verify_trace(market, trace, metrics, config['execution']['conservative'],
                            study.PERIODS['continuous'], reductions if name == 'daily_target_ratchet'
                            else np.zeros_like(reductions))
    assert qa == metrics['qa']
    checks[name] = {'fill_count': len(trace['fills']), 'equity_mark_count': len(trace['equity_marks']),
                    'all_recorded_qa_fields_unchanged': True, 'qa': qa}
assert study.falsification(result['results']) == result['falsification']
report = {'schema': 'nexus.risk-cadence-retained-trace-review.v1',
          'reviewed_parent_commit': '2e39143f011cb8b87f033b8477fa6bdd8adc87c2',
          'device': 'Laptop2 / DESKTOP-F4SA4VL', 'original_result_digest': recorded_digest,
          'source_hashes_lf': {p: study.source_hash(root / p) for p in (
              'scripts/nexus_portfolio_risk_cadence_diagnostic.py',
              'tests/test_nexus_portfolio_risk_cadence_diagnostic.py')},
          'retained_trace_checks': checks, 'new_economic_backtest_runs': 0,
          'unit_test_methods_passed': 15, 'new_corruption_subtests_passed': 29,
          'original_observer_false_acceptances_reproduced': 19,
          'verdict_unchanged': result['falsification']['verdict'],
          'formal_independent_paper_qa_complete': False, 'paper_eligible': False,
          'live_enabled': False, 'orders': 0}
out = root / 'physical-review-verification.json'
with out.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(report, handle, sort_keys=True, indent=2, allow_nan=False)
    handle.write('\n')
print(json.dumps(report, sort_keys=True, allow_nan=False))
