from copy import deepcopy
import json
from datetime import datetime, timezone, timedelta
import pytest
import pandas as pd
import product_shared_paper as terminal
import nexus_owner_multistrategy_demo_v3 as multi
from test_owner_multistrategy_demo_v3 import initialized
from test_bybit_prospective_paper_forward_v1 import observation


def snapshot(a,s):
    return terminal.build_snapshot(s,a,{'checked_at':'2026-09-26T18:00:00Z',
        'status':'running_waiting_for_closed_bar','start_not_before_utc':'2026-09-26T20:00:00Z'})


def step(a,s,when,weight=.95,funding=False):
    obs=observation(when)
    obs['target_weights']=[weight,0]
    if funding: obs['funding_rates']=[[.001],[]]; obs['expected_funding_events']=[1,0]
    signals={n:[weight if sym=='BTCUSDT' else 0,weight if sym=='ETHUSDT' else 0] for n,sym in multi.SELECTED.items()}
    return multi.step(s,a,obs,signals,None)


def test_flat_account_not_duplicated_by_stress(initialized):
    a,s,*_=initialized
    x=snapshot(a,s)
    assert x['account']['equity']==500
    assert x['positions']==x['orders']==x['history']==[]
    assert sum(r['allocation'] for r in x['strategies'])==500


def test_open_partial_close_full_exit_and_funding_reconcile(initialized):
    a,s,*_=initialized
    s=step(a,s,'2026-09-26T20:00:00Z')
    x=snapshot(a,s)
    assert len(x['positions'])==4
    assert len({p['id'] for p in x['positions']})==4
    assert all(p['stop_loss'] is None and p['take_profit'] is None for p in x['positions'])
    s=step(a,s,'2026-09-27T00:00:00Z',.2,True)
    x=snapshot(a,s)
    assert any(t['partial'] for t in x['history'])
    s=step(a,s,'2026-09-27T04:00:00Z',0)
    x=snapshot(a,s)
    assert not x['positions']
    assert sum(t['net_pnl'] for t in x['history'])==pytest.approx(x['account']['net_pnl'])
    assert sum(c['amount'] for c in x['cashflows'])==pytest.approx(x['account']['balance']-500)
    assert x['account']['initial_margin']==0
    assert all('stress' not in o['id'] for o in x['orders'])


def test_reversal_has_two_distinct_position_ids(initialized):
    a,s,*_=initialized
    s=step(a,s,'2026-09-26T20:00:00Z')
    ids={p['id'] for p in snapshot(a,s)['positions']}
    s=step(a,s,'2026-09-27T00:00:00Z',-.8)
    x=snapshot(a,s)
    assert all(p['side']=='short' for p in x['positions'])
    assert not ids.intersection(p['id'] for p in x['positions'])
    assert all(not t['partial'] for t in x['history'])
    assert {t['position_id'] for t in x['history']}==ids


def test_optional_audit_does_not_change_trading_results(initialized):
    a,s,*_=initialized
    cfg=a['configs']['consensus']['execution_profiles']['conservative']
    obs=observation('2026-09-26T20:00:00Z')
    p=s['lanes']['consensus']['profiles']['conservative']
    plain=multi.forward._profile_step(p,obs,cfg,'conservative')
    audited=multi.forward._profile_step(p,obs,cfg,'conservative',capture_execution=True)
    assert {k:audited[k] for k in plain}==plain


def test_missing_history_is_rejected_even_when_resealed(initialized):
    a,s,*_=initialized
    s=step(a,s,'2026-09-26T20:00:00Z')
    s['lanes']['consensus']['profiles']['conservative']['execution_journal']=[]
    with pytest.raises(ValueError,match='history incomplete'): snapshot(a,multi.seal(s))


def test_staleness_and_tamper_fail_closed(initialized,tmp_path):
    a,s,*_=initialized
    path=tmp_path/'shared_paper'/'terminal.json';path.parent.mkdir()
    x=snapshot(a,s);path.write_text(json.dumps(x))
    now=datetime(2026,9,26,18,0,tzinfo=timezone.utc)
    assert terminal.load_snapshot(tmp_path,now=now)['stale'] is False
    assert terminal.load_snapshot(tmp_path,now=now+timedelta(minutes=5))['stale'] is True
    x['account']['balance']=999;path.write_text(json.dumps(x))
    assert terminal.load_snapshot(tmp_path,now=now)['available'] is False


def test_csv_formula_safety_and_unicode():
    b=terminal.export_csv({'history':[{'strategy':'=HYPERLINK("x")','symbol':'بیت','net_pnl':-1.2}]})
    assert b.startswith(b'\xef\xbb\xbf')
    assert "'=HYPERLINK" in b.decode('utf-8-sig')
    assert '-1.2' in b.decode('utf-8-sig')


def test_upgrade_preserves_evidence_and_rejects_nonempty_account(initialized,tmp_path):
    import nexus_shared_paper_upgrade as upgrade
    a,s,*_=initialized
    a['source_sha']='9d905d052b5c2970ff4f089a6e4c29132c240e7a';a=multi.seal(a)
    s['activation_digest']=a['digest'];s=multi.seal(s)
    old=tmp_path/'old-multi';old.mkdir()
    (old/'STOP').write_text('upgrade')
    for filename,obj in [('activation.json',a),('state.json',s)]:
        (old/filename).write_text(json.dumps(obj))
    before=(old/'state.json').read_bytes()
    new=tmp_path/'new-multi'
    upgrade.migrate(old,new,'c'*40,a['engine_digest'])
    assert (new/'before-upgrade-state.json').read_bytes()==before==(old/'state.json').read_bytes()
    na=json.loads((new/'activation.json').read_text());ns=json.loads((new/'state.json').read_text())
    assert snapshot(na,ns)['account']['equity']==500
    with pytest.raises(ValueError,match='destination already exists'):
        upgrade.migrate(old,new,'c'*40,a['engine_digest'])
    used=step(a,s,'2026-09-26T20:00:00Z')
    (old/'state.json').write_text(json.dumps(used))
    with pytest.raises(ValueError,match='used account'):
        upgrade.migrate(old,tmp_path/'reject','c'*40,a['engine_digest'])


def test_public_marks_are_display_only_and_stale_quotes_fail_closed(initialized):
    a,s,*_=initialized;s=step(a,s,'2026-09-26T20:00:00Z');x=snapshot(a,s)
    before=deepcopy(s);now=datetime(2026,9,27,0,0,tzinfo=timezone.utc)
    class Quotes:
        stale=False
        def get(self,path,params):
            assert path=='/v5/market/tickers' and params['category']=='linear'
            return {'time':(now.timestamp()-(200 if self.stale else 0))*1000,
                'result':{'category':'linear','list':[{'symbol':params['symbol'],'markPrice':'11000'}]}}
    client=Quotes();y=terminal.with_public_marks(x,client,now)
    assert y['valuation']=='public_mark_snapshot'
    assert y['account']['equity']>x['account']['equity']
    assert y['account']['free_margin'] is None
    assert y['history']==x['history'] and before==s
    client.stale=True;z=terminal.with_public_marks(x,client,now)
    assert z['account']==x['account']
    assert z['quote_status']=='unavailable_using_closed_bar'
