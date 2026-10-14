"""Training-only accounting decomposition of existing closed-path aggregates.

No market replay, fee-free simulation, candidate tuning or independent QA claim.
"""
from pathlib import Path
from decimal import Decimal, localcontext
import argparse, ast, hashlib, json

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--report',type=Path,required=True)
parser.add_argument('--freeze',type=Path,required=True)
parser.add_argument('--engine-source',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
out=args.output;out.mkdir(parents=True,exist_ok=True)
report_path=args.report
report_raw=report_path.read_bytes()
report=json.loads(report_raw,parse_float=Decimal)
freeze=json.loads(args.freeze.read_bytes(),parse_float=Decimal)
source_path=args.engine_source
source_raw=source_path.read_bytes()
sha=lambda raw:hashlib.sha256(raw).hexdigest()
assert sha(report_raw)=='26bd16779f583d43c8407c65f0830fcccd4700c8b09a0f1cd1e00c5fd087f53d'
assert sha(source_raw)==freeze['source_component_sha256']['nexus_composite_strategy_research.py']
node=next(n for n in ast.parse(source_raw).body if isinstance(n,ast.FunctionDef) and n.name=='backtest')
backtest_hash=sha(ast.get_source_segment(source_raw.decode(),node).encode())
assert backtest_hash=='e44e2bada1efbf2427edfee224d75e96067bfcf1e3fa07b79fa39a09782b9bfb'
assert report['source_sha']==freeze['source_sha']=='8c06ca692a06611431730e4aeb822b1d9f47f30d'

def decompose(net,turnover,fee_fraction,slip_fraction):
    assert turnover>=0 and 0<=fee_fraction<1 and 0<=slip_fraction<1
    with localcontext() as ctx:
        ctx.prec=50
        fees=fee_fraction*turnover
        executed_gross=net+fees
        entry=(turnover-executed_gross)/2
        exit_quote=(turnover+executed_gross)/2
        assert entry>=0 and exit_quote>=0
        reconstructed_base_gross=exit_quote/(1-slip_fraction)-entry/(1+slip_fraction)
        slip=entry*slip_fraction/(1+slip_fraction)+exit_quote*slip_fraction/(1-slip_fraction)
        alternative=(net+(fee_fraction+slip_fraction)*turnover)/(1-slip_fraction**2)
        tolerance=Decimal('1e-35')
        assert abs(reconstructed_base_gross-alternative)<tolerance
        assert abs(net-(reconstructed_base_gross-slip-fees))<tolerance
        return {'fee_quote':fees,'executed_price_gross_quote':executed_gross,
                'aggregate_executed_entry_quote':entry,'aggregate_executed_exit_quote':exit_quote,
                'fixed_path_entry_exit_slippage_quote':slip,
                'fixed_path_pre_multiplier_price_gross_quote':reconstructed_base_gross,
                'fixed_path_total_cost_quote':fees+slip}

# Two hand-specified closed fills, including a loss, check the aggregate inverse
# against direct fill arithmetic at both preregistered cost profiles.
synthetic=[]
for fee_bps,slip_bps in [(10,5),(25,15)]:
    with localcontext() as ctx:
        ctx.prec=50
        f=Decimal(fee_bps)/10000;s=Decimal(slip_bps)/10000
        fills=[(Decimal('1.25'),Decimal('60000'),Decimal('60300')),
               (Decimal('.4'),Decimal('61000'),Decimal('60000'))]
        entry=sum(q*price*(1+s) for q,price,_ in fills)
        exit_quote=sum(q*price*(1-s) for q,_,price in fills)
        v=entry+exit_quote;n=exit_quote-entry-f*v
        exact_raw_gross=sum(q*(b-a) for q,a,b in fills)
        x=decompose(n,v,f,s)
        assert abs(x['fixed_path_pre_multiplier_price_gross_quote']-exact_raw_gross)<Decimal('1e-35')
        assert abs(x['aggregate_executed_entry_quote']-entry)<Decimal('1e-35')
        assert abs(x['aggregate_executed_exit_quote']-exit_quote)<Decimal('1e-35')
        synthetic.append({'fee_bps':fee_bps,'slippage_bps':slip_bps,'hand_fill_path_gross':str(exact_raw_gross),'passed':True})

training=[r for r in report['rows'] if r['part']=='train']
assert len(training)==4 and {(r['symbol'],r['profile']) for r in training}=={
 ('BTCUSDT','conservative'),('BTCUSDT','stress'),('ETHUSDT','conservative'),('ETHUSDT','stress')}
rows=[]
for r in training:
    f=r['fee_bps']/10000;s=r['slippage_bps']/10000
    profile=freeze['costs_per_leg_bps'][r['profile']]
    assert r['fee_bps']==profile['fee'] and r['slippage_bps']==profile['slippage']
    assert r['trade_count_limit'] is None and r['closed_round_trips']>0
    x=decompose(r['net_pnl_usdt'],r['turnover_usdt'],f,s)
    with localcontext() as ctx:
        ctx.prec=50
        count=Decimal(r['closed_round_trips'])
        # This describes only serialized-display rounding sensitivity. It does
        # not bound the engine's unverified floating-point accumulation error.
        display_only_bound=(Decimal('5e-9')+(f+s)*Decimal('5e-7'))/(1-s**2)
        row={'symbol':r['symbol'],'part':'train','profile':r['profile'],'closed_round_trips':r['closed_round_trips'],
             'first_closed_utc':r['first_closed_utc'],'last_closed_utc':r['last_closed_utc'],
             'net_pnl_usdt':str(r['net_pnl_usdt']),'turnover_usdt':str(r['turnover_usdt']),
             'fee_bps':str(r['fee_bps']),'slippage_bps':str(r['slippage_bps']),
             'max_drawdown_pct':str(r['max_drawdown_pct']),'halted_on_drawdown':r['halted_on_drawdown'],
             **{k:str(v) for k,v in x.items()},
             'net_pnl_per_closed_trip':str(r['net_pnl_usdt']/count),
             'fixed_path_base_price_gross_per_closed_trip':str(x['fixed_path_pre_multiplier_price_gross_quote']/count),
             'fixed_path_total_cost_per_closed_trip':str(x['fixed_path_total_cost_quote']/count),
             'serialized_display_rounding_sensitivity_bound':str(display_only_bound)}
        rows.append(row)

receipt={'schema':'nexus.elliott-v9-training-accounting-diagnosis.v1','computational_source_sha':report['source_sha'],
 'existing_market_result_head':'92f6b4639f5cbc6883683bd184f8d69b52f910eb',
 'existing_report_file_sha256':sha(report_raw),'existing_report_digest':str(report['report_digest']),
 'shared_backtest_ast_source_sha256':backtest_hash,'training_rows_used':4,'validation_rows_used':0,
 'historically_inspected_final_rows_used':0,'new_market_runs':0,'parameter_sweeps':0,
 'terminal_predecessor_file_sha256':'14cc329d8acd02fbc3a13268826446f44d05dcf9eb299a6c13738558342f401c',
 'terminal_predecessor_ledger_digest':'b784b409c16b77fa5d6dd5d65b7f8ed67e13e65aa6d230a74e843f9e63720e8f',
 'formula':{'V':'aggregate executed entry + exit quote turnover',
            'N':'aggregate net closed P/L','f':'fee_bps / 10000','s':'slippage_bps / 10000',
            'F':'f * V','G':'N + F','E':'(V - G) / 2','X':'(V + G) / 2',
            'H':'X/(1-s) - E/(1+s) = (N + (f+s)*V)/(1-s*s)',
            'S':'H - G','identity':'N = H - S - F'},
 'interpretation':'Fixed executed quantities, decision path and execution-reference levels only. H strips price multipliers algebraically; it is not the outcome of running the strategy without costs. Stops/targets, fills, quantities, cash and guard timing can change in another simulation.',
 'synthetic_hand_fill_checks':synthetic,'rows':rows,
 'finding':'Conservative Training fixed-path price contribution is about -0.20 BTC and +0.02 ETH USDT per trip; fee+slippage about 2.88 per trip. Cost burden overwhelms the observed fixed-path price contribution. Stress paths hit the drawdown guard, so counts differ; do not pair or pool the two scenarios.',
 'causal_limit':'Aggregates do not identify stop/target/time exits, entry delay, wave scale, adverse excursion or regime errors. No causal attribution of those mechanisms is established.',
 'independent_trade_ledger_numeric_decimal_leakage_qa_complete':False,
 'decimal_used_for_summary_accounting_only':True,'owner_demo_admission':False,
 'research_only':True,'auto_demo_promotion':False,'live_enabled':False,
 'next_work':'Define one distinct hypothesis with an explicit pre-entry cost budget and larger structural move; perform prior-inventory duplicate checks and freeze causal lifecycle before implementation. Add prospective fill-level training diagnostics to that new run without replaying v9. No Validation/final-fold retuning, stop/risk/cost relaxation, or Demo admission.'}
raw=(json.dumps(receipt,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
(out/'accounting-diagnosis.json').write_bytes(raw)
print(json.dumps({'synthetic_hand_fill_profiles_passed':len(synthetic),'training_rows':len(rows),
                 'source_hash_verified':True,'report_hash_verified':True,'new_market_runs':0,
                 'rows':[{k:r[k] for k in ['symbol','profile','fee_quote',
                      'fixed_path_pre_multiplier_price_gross_quote','fixed_path_total_cost_per_closed_trip',
                      'fixed_path_base_price_gross_per_closed_trip','halted_on_drawdown']} for r in rows]},indent=2))
