"""Checkpointed distinct-host comparison of frozen v6 cells with a reviewed day cache."""
from __future__ import annotations
import base64
from datetime import datetime, timezone
import faulthandler
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import unittest
import zlib

CONFIG = {'verification_source_sha': '9144f888306e12a86fb4812896b137c13a6adeb9', 'original_engine_blob_sha': '918c886570040712f3b7aa83f7fa812720c927b2', 'engine_blob_sha': '4c4fc599bf5dabe6c67136dcb4d711f6f47d2610', 'test_blobs': {'tests/fixtures/nexus_backtest_scalar_day_floor_v1.json': '3455b55e4a182906504ae76e334ca303fb7975d5', 'tests/test_nexus_composite_backtest_day_cache.py': '8965ccec2624b555cea2690d89441b2f0c812403'}, 'root': 'E:\\NEXUS-QA\\jump-v6-day-cache-qa-resume-20261013', 'baseline_source': 'E:\\NEXUS-QA\\jump-v6-independent-20261013-verify8899\\source', 'producer_root': 'E:\\NEXUS-QA\\jump-v6-independent-20261013-verify8899\\producer', 'archive_root': 'E:\\NEXUS-QA\\native-v5-independent-20261012-1604\\dataset\\canonical', 'qa_host': 'DESKTOP-1R1081M', 'producer_host': 'DESKTOP-F4SA4VL', 'producer_source_sha': '8899ec6bec4927fc39795f2867be91e2431178c6', 'git_executable': 'C:\\Program Files\\Git\\cmd\\git.exe', 'runtime_pins': {'numpy': '2.3.5', 'pandas': '2.3.3', 'pyarrow': '21.0.0'}, 'raw_frame_sha256': ['f8f2236785c036fe40808809397d47729b3add4c8f0b9e19c77d3b771f8e6847', 'e0d019a76882a02dc463a34d1d9375841f81d412b9a3310d9e21c2d7b2738dc6', 'c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226', 'ba0743588c5089e6a6b250b4ebb029a43fea57d0a020df5ab1316c34efdcd88a', '292005e091d914fbb9d108c3d8d65e93785cc32b9c73e07ea02e0d44cf7da65b', 'ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1'], 'input_file_sha256': {'research-report.json': '8386ada0f818e5c43461193c9f19d981ab648efa65374d02525905437eb62afc', 'agent-receipt.json': '17ea3ed91e32eb31146ad53e874220381af05cc351d2156c9155c954cf713ecd', 'novelty-ledger.json': '937741211cfccbbcd2a278f7b501679cb82c1caae10801fd419127dcb10c395f', 'previous-ledger.json': 'f2024e077df1eae89a3534dcc7055d4dd7900d9d3983c3600074dd81f1fe5e32'}, 'test_files': {'tests/fixtures/nexus_backtest_scalar_day_floor_v1.json': {'git_blob_sha': '3455b55e4a182906504ae76e334ca303fb7975d5', 'zlib_base64': 'eNrtlk2P2jAQhu/8CpRzsbDz6fa0lXqotOdeqsoyjgPpOnZkOyyr1f732mFZpftZVSAgmEMQmdeTmczL6LmfTKcRo4ab6PP0p/sxnd73V3ebb1rOLC9dZHfPi4UyvCRadbIkVtetP4k+DQRKsk5rLi3RtbkhjSq5cJpISU6YEoJarqkgC8puXCLJLRFKLknLNTF3zUKJL3DeMktaZWpbK0kWXbnkNho8w5WmTKe5S6KJpk7lHjAH8yJ2n4Gu4k7SVwhddBBYUeE6Iy55qeltqW6l01jd8YGmoZunKHEF+SwQZNk8K5Jk+BTfQisF6UzpRTMIswz0KoSf6zS3nd6lm72er9Wqqi2pKLNKbxt7K0qMpbbzDUZXP66+X199vf42fFFG1G1Ll7u3kP6VyWpa+pF0blSibmpfkuyEGEpcsWrtJvPYG0xQDGCW4yQdqG5r6afAH9ty9T7GHnaiNyYR9Q5ZU11T2Z98CrxdeGTrhru2m7a3lm+9syyaDJ43TgujdF8Wxiks5nH6voUx6FUJ/tDBL9MdzsFwHxZOAMQ5RNn/Wng4iX+2MDy8h+PT8DBE6SF3MAIYJbDAMXrPwAgjsFXFHzj41XynvIPTPAdxnuXz+BA7GB5vB5+4f/e0gJ3fMljExfsMgXAGtqok/dC/L/Od9AZO8wIkSYbmB9nA8IgbOIBwAOEjgrDlK01lYOHAwmfNwnuyccDhgMPHwuHLsHAg4lET8cXgRIDiEUOxpPWaByYOTHzWTLwfFwckDkh8LCS+CAcHIh41EV8KSwQgHjEQG+dDuTQBiQMSnzUS78vHAYoDFB8Lii/EwwGLR43Fl0MUAYxHDMZNvfHDXPx2fg14HPD4vPF4v24OkBwg+ViQfFFODqg8alR+zcvu+ssfiTSvuDMj40R2TXvn9QjEII2eRVsqS2q2YSd4Hjaq0/5rRb2kKDDmLFtwlmCUVyzGOU4rVGT5gmPIURJDmBcs22YxbMWb/pzkm84Aw6igelbSu1kllNIz/1ewrqnZUomSS7CG0eRh8gcAxrKV'}, 'tests/test_nexus_composite_backtest_day_cache.py': {'git_blob_sha': '8965ccec2624b555cea2690d89441b2f0c812403', 'zlib_base64': 'eNq1V0lv4zYUvvtXEAQKSKii2I6zAj5Mk5njoJimh8IwCFp6sjmhSA1JJbGL/vc+ipL3sdNDhSwW+fbte6aUfjF6BYrYjEtuLgwUYEBlQAzMDVgrtCKFNgSvQeVIkfMlmfHsxYF1RFdOlGLFHZKllNKeKCttHPluteoVRpek4m4hxYy0F7/ja0dUK+G8lEDYvXWUpc5eeh2pqstqSbglquqOKo7mWH9W5b0gQsF7bVmmkcAKB8w6wx3MlwwdAW6yRSeb5ZAJ7xpDb9gLLG2y9qnX6+VQEKmtZRWvLbDC8BKiUucQP/QIPjlKtWSMilP/kRmu5hDRYX94fdEfXFwNyLD/0Pc/NCEVGKFzOx7dJaQw8GNMB9elUHjjVmP65/MjjRuhoiBeBRmPCXWwQJk0aNvW2PxP3QqdVK9gXEQ/WcEvnwN9EARyW5Ti4hVOSZIaUytWEH3VCo5JwCgKNbdHZExeuawhFVZjhZTcRXFTKs0pESrQTY+ILMU75EzPvkPmjgnGwP6BYQMbTdZ3/mklF0SQX8jQi+qjZAvh4kxcusebKJKNlYDFBb5Qokb9hniakNwtKxgHQ8NFZUTW2KiqtKiljHxeB/1+2t++n0yG/hR/8XZ4k5CrUUJGw+kUGQdI25A2dRW8feKOf2nK7O+1erouUu7oQ4hNQqiuACuj1YPvCzFfrN/JryQdJhsRUr9t7i5I2r9GjgxrG7ZFcGfwFR3CCrDoUBwk/BM8smKuuGxdXoHRtvE5hGamtdwhm0zQax8SdHqITl9hIEb9xvFnU0NDasDVRgX/k44R+y6T3Fry2E6aJ778re3Jb+tZFHVjIn3GP4/crnsSe9afMy4lKwFrNrMMazJbYP/6Cce0EXOBmlgYdaxr+MiCLOJNERbiHc3zifFTLJWa5zaK/OCKGCuEBMbitOI4JR25JLQlt5Rc7pTZ4UPDfOr0dnb4EVRIrQ17HaReJY1TAzxnDt6xpTb16O1MMUJY359/1FxGreoJXU9tZnVt/L8Fp9Pk5/bQu7v7e8huZpCN7oe3RXZ1f3t/XQzvbm5ncD+A4ehqMLi9y27oCfWYpo0JGabC0mmMWe9veAJy2KbP9kkfdsx7E24RVNh65nPbDNyxp51QBBk84WXF/CF6RoywL+2l/8heuRFcuZNOB4ugE4qf2KzyNj8c8OyWJpbCARwcNyw+kMQzh7FCCety25WdkNaOfavOOdKkRIpqi9e/VnzeCSDbkTkarENzD5Ic7E9IYIf3Cich5GdYfae3nBO64NL5aY9ga/hbrt+U595tWh/HFU4fhqDOcjzAprAMvAVdm3QLSHO137OnEHkwQFA+hsg3o9OI3KCyqmrXYN0GkwJMJGTvZBd+EFJExi+/whv7S5sXGsfHEnpSxDaCHVe3i91nNHwMrT8kZAPB/xl9DxvyDBzvo/C0d4zT7rKGtMXnRsymfX1IxuLIJOgqvi2B544jatTGaTO5I/pE96IZrJqebzAp0JDDhTTItz7xnQn7TZNxpRUWmWQ+Ut4X5rdtpgCT4PtF2q55thxt7N2HvLPjjtYu28pkE0q/oSMQIsSmITfRdoBwr2h0US83BwZFgSTjT43r6OlnY3zggoEkkMZ7CUBYraX7yPDEpSrZjMPrdG/49U/AWFAyCWtRzoyucQbh/hBm6HA/6lBWbhmigt8rHBfKMr8VIQvP/ZGXxnyAdO22Ap9pWZdqP/KHHu5sg5h9XLq4MXwZTaY7S9cpfPjfo/IRTgWOVUqy2uau4Uk/yBTWQ1ZlH2cr+fsaXc4wfsG6gTXjT8CphwOOMeVzzJpvLAx3SaEYa7+srLdQfxrFvX8BLpe/YQ=='}}, 'retry_of_root': 'E:\\NEXUS-QA\\jump-v6-day-cache-qa-20261013', 'retry_reason': 'Previous child-unit gate expired before any comparison cells; use same-process tests, live per-test logs and a bounded test stack trace', 'resume_from': 'E:\\NEXUS-QA\\jump-v6-day-cache-qa-inline-20261013', 'reused_cells_expected': 6, 'wall_seconds': 420}
ROOT = Path(CONFIG['root'])
START = time.monotonic()
COMPLETED = []
REUSED = {}

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git_blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def check(ok, why):
    if not ok:
        raise ValueError(why)

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def save(name, value):
    path=ROOT/name
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,sort_keys=True,indent=2,allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp,path)

def status(state, **extra):
    value={'schema':'nexus.day-cache-comparison-status.v1','status':state,
           'producer_source_sha':CONFIG['producer_source_sha'],
           'verification_source_sha':CONFIG['verification_source_sha'],
           'checked_at_utc':datetime.now(timezone.utc).isoformat(),
           'elapsed_seconds':round(time.monotonic()-START,3),'completed_cells':len(COMPLETED),
           'independent_decimal_accounting_complete':False,'research_only':True,
           'auto_demo_promotion':False,'live_enabled':False,'official_coordinator_advanced':False,**extra}
    save('status.json',value)
    print(json.dumps(value,sort_keys=True),flush=True)

def git(source, *args):
    p=subprocess.run([CONFIG['git_executable'],'--no-optional-locks','-C',str(source),*args],
                     capture_output=True,text=True,check=True,timeout=20)
    return p.stdout.strip()

def main():
    check(socket.gethostname().split('.')[0].upper()==CONFIG['qa_host'],'wrong QA host')
    check(CONFIG['qa_host']!=CONFIG['producer_host'],'same producer/QA physical host')
    ROOT.mkdir(parents=True,exist_ok=False)
    with (ROOT/'execution.lock').open('x',encoding='utf-8') as f:
        f.write(str(os.getpid())+'\n')
    save('launch-receipt.json',{'pid':os.getpid(),'worker_sha256':sha(Path(__file__)),
                              'config_digest':digest(CONFIG),'wall_seconds':CONFIG['wall_seconds'],
                              'producer_source_sha':CONFIG['producer_source_sha'],
                              'verification_source_sha':CONFIG['verification_source_sha']})
    def deadline():
        status('FAILED_CLOSED_DEADLINE',reason=str(CONFIG['wall_seconds'])+'-second continuation deadline; retain completed cells')
        os._exit(124)
    timer=threading.Timer(CONFIG['wall_seconds'],deadline)
    timer.daemon=True
    timer.start()
    exit_code=1
    try:
        status('VERIFYING_FROZEN_INPUTS')
        source=Path(CONFIG['baseline_source'])
        producer=Path(CONFIG['producer_root'])
        archive=Path(CONFIG['archive_root'])
        check(git(source,'rev-parse','HEAD')==CONFIG['producer_source_sha'],'baseline Git HEAD changed')
        check(not git(source,'status','--porcelain'),'baseline source is dirty')
        for name, expected in CONFIG['input_file_sha256'].items():
            check(sha(producer/name)==expected,'producer file changed: '+name)
        report=read(producer/'research-report.json')
        receipt=read(producer/'agent-receipt.json')
        ledger=read(producer/'novelty-ledger.json')
        previous=read(producer/'previous-ledger.json')
        for value,key in ((report,'report_digest'),(receipt,'receipt_digest'),(ledger,'ledger_digest'),(previous,'ledger_digest')):
            check(value[key]==digest({k:v for k,v in value.items() if k!=key}),'canonical digest mismatch: '+key)
        check(report['source_sha']==receipt['source_sha']==CONFIG['producer_source_sha'],'producer identity mismatch')
        for value in (report,receipt):
            check(value['research_only'] is True and value['auto_demo_promotion'] is False
                  and value['live_enabled'] is False,'authority mismatch')
        versions={k:importlib.metadata.version(k) for k in CONFIG['runtime_pins']}
        check(versions==CONFIG['runtime_pins'],'native runtime changed')
        raw=list(archive.rglob('*.parquet'))
        check(len(raw)==6 and {sha(p) for p in raw}==set(CONFIG['raw_frame_sha256']),'raw archive changed')
        overlay=ROOT/'source-overlay'
        overlay.mkdir()
        old_text=(source/'nexus_composite_strategy_research.py').read_text(encoding='utf-8')
        check(git_blob(old_text.encode())==CONFIG['original_engine_blob_sha'],'original engine blob mismatch')
        helper='def _decision_day_keys(values: pd.Series) -> Any:\n    """Cache timezone calendar days without per-candle scalar floor calls."""\n    if pd.api.types.is_datetime64_any_dtype(values.dtype):\n        return values.dt.floor("D").array\n    # Preserve scalar conversion for noncanonical object/string timestamps.\n    return tuple(pd.Timestamp(value).floor("D") for value in values)\n\n\n'
        anchor='def backtest(frame: pd.DataFrame, signals: np.ndarray, *, fee_bps: float,'
        old_loop='    exposure_bars = 0\n    for i, row in enumerate(frame.itertuples(index=False)):\n        at = pd.Timestamp(row.decision_at)\n        if day != at.floor("D"):\n            day = at.floor("D")\n'
        new_loop='    exposure_bars = 0\n    decision_days = _decision_day_keys(frame["decision_at"]) if len(frame) else ()\n    for i, row in enumerate(frame.itertuples(index=False)):\n        if day != decision_days[i]:\n            day = decision_days[i]\n'
        check(old_text.count(anchor)==old_text.count(old_loop)==1,'day patch anchors changed')
        patched=old_text.replace(anchor,helper+anchor,1).replace(old_loop,new_loop,1).encode()
        check(git_blob(patched)==CONFIG['engine_blob_sha'],'patched engine does not match reviewed Git blob')
        (overlay/'nexus_composite_strategy_research.py').write_bytes(patched)
        (overlay/'research').mkdir()
        for name in ('mechanism_factory_v5.json','mechanism_factory_v6.json'):
            raw=(source/'research'/name).read_text(encoding='utf-8').encode()
            expected=git(source,'rev-parse','HEAD:research/'+name)
            check(git_blob(raw)==expected,'baseline declarative contract changed: '+name)
            (overlay/'research'/name).write_bytes(raw)
        for name,payload in CONFIG['test_files'].items():
            value=zlib.decompress(base64.b64decode(payload['zlib_base64'],validate=True))
            check(git_blob(value)==payload['git_blob_sha'],'test source blob mismatch: '+name)
            target=overlay/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(value)
        save('source-binding.json',{'producer_source_sha':CONFIG['producer_source_sha'],
             'verification_source_sha':CONFIG['verification_source_sha'],'physical_git_head':git(source,'rev-parse','HEAD'),
             'engine_blob_sha':CONFIG['engine_blob_sha'],'source_layout':'exact Git blob overlay over unchanged baseline dependencies',
             'test_file_blobs':{k:v['git_blob_sha'] for k,v in CONFIG['test_files'].items()}})
        resume=Path(CONFIG['resume_from'])
        unit=read(resume/'native-regression-receipt.json')
        check(unit['exit_code']==0 and unit['tests']==4 and unit['golden_cases']==20 and unit['timezone_cases']==6,
              'prior native regression incomplete')
        check(unit['verification_source_sha']==CONFIG['verification_source_sha'] and
              unit['engine_blob_sha']==CONFIG['engine_blob_sha'] and unit['numpy']==versions['numpy'] and
              unit['pandas']==versions['pandas'],'prior native unit identity changed')
        save('native-regression-receipt.json',unit)
        for cell_path in sorted(resume.glob('cell-*.json')):
            cell=read(cell_path)
            check(cell['cell_digest']==digest({k:v for k,v in cell.items() if k!='cell_digest'}),'prior cell digest changed')
            check(cell['producer_source_sha']==CONFIG['producer_source_sha'] and
                  cell['verification_source_sha']==CONFIG['verification_source_sha'] and
                  cell['engine_blob_sha']==CONFIG['engine_blob_sha'] and
                  cell['producer_report_digest']==report['report_digest'] and cell['matches'] is True and
                  cell['research_only'] is True and cell['auto_demo_promotion'] is False and
                  cell['live_enabled'] is False,'prior cell authority/source changed')
            key=(cell['config_fingerprint'],cell['symbol'],cell['part'],cell['profile'])
            check(key not in REUSED,'duplicate prior cell')
            REUSED[key]=cell
        check(len(REUSED)==CONFIG['reused_cells_expected'],'unexpected completed-cell count')
        save('resume-binding.json',{'resume_from':str(resume),'prior_native_unit_file_sha256':sha(resume/'native-regression-receipt.json'),
             'reused_cell_digests':[v['cell_digest'] for v in REUSED.values()],
             'verification_source_sha':CONFIG['verification_source_sha'],'producer_report_digest':report['report_digest'],
             'source_and_metrics_revalidated_before_reuse':True,'planned_new_cells':16-len(REUSED),
             'wall_seconds':CONFIG['wall_seconds'],'deadline_basis':'Previous measured 77k-bar cells ~38s, 26k-bar cells ~13s; remaining10cells ~282s plus imports/features and headroom'})
        status('REUSED_NATIVE_UNIT_PROOF',prior_verified_cells=len(REUSED),native_tests_rerun=False)
        sys.path[:0]=[str(overlay),str(source)]
        sys.dont_write_bytecode=True
        import numpy as np
        import nexus_composite_strategy_research as research
        import nexus_agent_composite_runtime as runtime
        runtime._validate_report(report,ledger,previous,CONFIG['producer_source_sha'])
        def prohibited(*args,**kwargs):
            raise RuntimeError('producer/full-tournament/research run prohibited in cell comparison')
        research.run=research._screen_frontier=runtime.run_lease=runtime.verify_independently=prohibited
        class OfflineSocket(socket.socket):
            def connect(self,*args,**kwargs):
                raise RuntimeError('comparison is archive-only')
            connect_ex=connect
        socket.socket=OfflineSocket
        def offline(*args,**kwargs):
            raise RuntimeError('comparison is archive-only')
        socket.create_connection=offline
        status('BUILDING_IDENTICAL_CAUSAL_FEATURES')
        frames=research._load_frontier_features(archive)
        candidates=research._frontier_configs_to_screen(previous)
        by_id={c['mechanism']:c for c in candidates}
        check(len(candidates)==2 and report['selected']==by_id[report['selected']['mechanism']],
              'reviewed training candidate set changed')
        signals={}
        metrics={}
        selected=report['selected']
        def calculate(config,symbol,part,profile,expected,scope):
            fingerprint=config['fingerprint']
            frame=frames[symbol]
            sig=signals.setdefault((fingerprint,symbol),None)
            if sig is None:
                sig=research.signal_for(frame,config)
                signals[(fingerprint,symbol)]=sig
            n=len(frame)
            a,b=int(n*research.TRAIN_FRAC),int(n*(research.TRAIN_FRAC+research.VALID_FRAC))
            lo,hi={'train':(0,a),'validation':(a,b),'historically_inspected_test':(b,n)}[part]
            piece=frame.iloc[lo:hi].reset_index(drop=True)
            check(len(piece)==expected['bars'],'cell bar count changed')
            if scope=='full_grid':
                check(str(piece['decision_at'].iloc[0])==expected['first_closed_utc'] and
                      str(piece['decision_at'].iloc[-1])==expected['last_closed_utc'],'cell chronology changed')
            fee,slip=((research.ENTRY_FEE_BPS,research.ENTRY_SLIP_BPS) if profile=='conservative'
                      else (research.STRESS_FEE_BPS,research.STRESS_SLIP_BPS))
            key=(fingerprint,symbol,part,profile)
            cached=REUSED.get(key)
            if cached is not None:
                check(cached['scope']==scope and cached['bars']==len(piece),'reused cell identity changed')
                check(cached['signal_digest']==hashlib.sha256(np.asarray(sig[lo:hi],dtype=np.uint8).tobytes()).hexdigest(),
                      'reused decision signal changed')
                actual=cached['actual']
                fields=list(actual) if scope=='full_grid' else ['net_return_pct','max_drawdown_pct',
                         'closed_round_trips','profit_factor','win_rate_pct']
                check(all(actual[k]==expected[k] for k in fields),'reused metrics mismatch')
                metrics[key]=actual
                save('cell-'+str(len(COMPLETED)).zfill(2)+'.json',cached)
                COMPLETED.append(cached)
                status('REUSED_VERIFIED_CELL',last_cell_identity=[symbol,part,profile,config['mechanism']],
                       reused_cell_digest=cached['cell_digest'])
                return
            wall,cpu=time.monotonic(),time.process_time()
            actual=research.backtest(piece,sig[lo:hi],fee_bps=fee,slip_bps=slip,risk_variant=config['risk_variant'])
            elapsed,process=round(time.monotonic()-wall,6),round(time.process_time()-cpu,6)
            fields=list(actual) if scope=='full_grid' else ['net_return_pct','max_drawdown_pct',
                     'closed_round_trips','profit_factor','win_rate_pct']
            check(all(actual[k]==expected[k] for k in fields),'numerical cell mismatch: '+symbol+'/'+part+'/'+profile)
            metrics[(fingerprint,symbol,part,profile)]=actual
            core={'schema':'nexus.optimized-cell-comparison.v1','producer_source_sha':CONFIG['producer_source_sha'],
                  'verification_source_sha':CONFIG['verification_source_sha'],'engine_blob_sha':CONFIG['engine_blob_sha'],
                  'symbol':symbol,'part':part,'profile':profile,'config_fingerprint':fingerprint,'scope':scope,
                  'bars':len(piece),'compared_fields':fields,'actual':actual,'matches':True,
                  'backtest_wall_seconds':elapsed,'backtest_cpu_seconds':process,
                  'signal_digest':hashlib.sha256(np.asarray(sig[lo:hi],dtype=np.uint8).tobytes()).hexdigest(),
                  'producer_report_digest':report['report_digest'],'research_only':True,
                  'auto_demo_promotion':False,'live_enabled':False}
            cell={**core,'cell_digest':digest(core)}
            save('cell-'+str(len(COMPLETED)).zfill(2)+'.json',cell)
            COMPLETED.append(cell)
            status('COMPARING_FROZEN_CELLS',last_cell_identity=[symbol,part,profile,config['mechanism']],
                   last_backtest_wall_seconds=elapsed)
        for row in report['rows']:
            calculate(selected,row['symbol'],row['part'],row['profile'],row,'full_grid')
        original_rank={r['mechanism']:r for r in report['frontier_screening']['ranking']}
        for config in candidates:
            if config['fingerprint']==selected['fingerprint']:
                continue
            for expected in original_rank[config['mechanism']]['cells']:
                calculate(config,expected['symbol'],'train',expected['profile'],expected,'training_screen')
        ranking=[]
        for config in candidates:
            cells=[]
            for symbol in research.SYMBOLS:
                for profile in ('conservative','stress'):
                    actual=metrics[(config['fingerprint'],symbol,'train',profile)]
                    cells.append({'symbol':symbol,'profile':profile,'bars':int(len(frames[symbol])*research.TRAIN_FRAC),
                         **{k:actual[k] for k in ('net_return_pct','max_drawdown_pct','closed_round_trips','profit_factor','win_rate_pct')}})
            returns=[float(c['net_return_pct']) for c in cells]
            stress=[float(c['net_return_pct']) for c in cells if c['profile']=='stress']
            ranking.append({'mechanism':config['mechanism'],'fingerprint':config['fingerprint'],
                'has_activity':sum(c['closed_round_trips'] for c in cells)>0,
                'closed_round_trips':sum(c['closed_round_trips'] for c in cells),
                'positive_cells':sum(v>0 for v in returns),'median_return_pct':round(float(np.median(returns)),8),
                'stress_median_return_pct':round(float(np.median(stress)),8),'worst_return_pct':round(min(returns),8),
                'max_drawdown_pct':round(max(c['max_drawdown_pct'] for c in cells),8),'cells':cells})
        ranking.sort(key=research._frontier_rank_key)
        for i,item in enumerate(ranking,1):
            item['rank']=i
        check(ranking==report['frontier_screening']['ranking'],'training ranking changed')
        check(len(COMPLETED)==16,'comparison grid incomplete')
        for name,expected in CONFIG['input_file_sha256'].items():
            check(sha(producer/name)==expected,'producer changed during comparison: '+name)
        check(not git(source,'status','--porcelain'),'baseline changed during comparison')
        core={'schema':'nexus.optimized-composite-independent-numeric-qa.v1',
              'source_sha':CONFIG['producer_source_sha'],'verification_source_sha':CONFIG['verification_source_sha'],
              'engine_blob_sha':CONFIG['engine_blob_sha'],'source_layout':'exact Git blob overlay',
              'qa_host':CONFIG['qa_host'],'producer_host':CONFIG['producer_host'],'distinct_physical_host':True,
              'producer_report_digest':report['report_digest'],'producer_receipt_digest':receipt['receipt_digest'],
              'full_grid_rows_compared':12,'additional_training_cells_compared':4,'training_ranking_matches':True,'reused_verified_cells':len(REUSED),'new_cells_compared_in_stage':16-len(REUSED),
              'independent_numeric_comparison_complete':True,'original_source_full_replay_complete':False,
              'independent_decimal_accounting_complete':False,'producer_job_rerun':False,'older_v5_jobs_rerun':False,
              'native_day_cache_tests_passed':True,'runtime_versions':versions,'cells':COMPLETED,
              'qualification':report['qualification'],'research_only':True,'auto_demo_promotion':False,
              'owner_demo_admission':False,'live_enabled':False,'official_coordinator_advanced':False,
              'limitation':'Shared source/data with reviewed calendar-day optimization; exact metrics and training ranking comparison, no independent accounting, signal/market source or future-profitability proof.'}
        evidence={**core,'qa_digest':digest(core)}
        save('qa-evidence.json',evidence)
        status('OPTIMIZED_NUMERICAL_COMPARISON_MATCHED_RESEARCH_ONLY',qa_digest=evidence['qa_digest'],
               independent_numeric_comparison_complete=True)
        exit_code=0
    except Exception as exc:
        status('FAILED_CLOSED',reason=type(exc).__name__+': '+str(exc))
        raise
    finally:
        timer.cancel()
        (ROOT/'process-exit.txt').write_text('NATIVE_EXIT='+str(exit_code)+'\n',encoding='utf-8')

if __name__=='__main__':
    main()
