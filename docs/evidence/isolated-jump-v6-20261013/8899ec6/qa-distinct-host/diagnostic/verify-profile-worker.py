"""Bounded one-cell diagnostic for an expired v6 numerical verification."""
from __future__ import annotations
import cProfile
from datetime import datetime, timezone
import faulthandler
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import pstats
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(r'E:\NEXUS-QA\jump-v6-qa-profile-20261013')
QA = Path(r'E:\NEXUS-QA\jump-v6-independent-20261013-verify8899')
BASE = Path(r'E:\NEXUS-QA\native-v5-independent-20261012-1604')
SOURCE = QA / 'source'
SOURCE_SHA = '8899ec6bec4927fc39795f2867be91e2431178c6'
REPORT_SHA = '8386ada0f818e5c43461193c9f19d981ab648efa65374d02525905437eb62afc'
START = time.monotonic()
STEPS = []

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(name, value):
    target = ROOT / name
    tmp = target.with_name(target.name+'.tmp')
    with tmp.open('w',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,sort_keys=True,indent=2,allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp,target)

def status(state, **extra):
    value={'schema':'nexus.jump-verification-diagnostic.v1','status':state,
           'source_sha':SOURCE_SHA,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
           'elapsed_seconds':round(time.monotonic()-START,3),'steps':STEPS,
           'independent_full_numeric_qa_complete':False,'independent_decimal_accounting_complete':False,
           'research_only':True,'auto_demo_promotion':False,'live_enabled':False,
           'official_coordinator_advanced':False,**extra}
    save('status.json',value)
    print(json.dumps(value,sort_keys=True),flush=True)

def check(condition, reason):
    if not condition:
        raise ValueError(reason)

def timed(name, function):
    status(name)
    wall=time.monotonic()
    cpu=time.process_time()
    result=function()
    STEPS.append({'phase':name,'wall_seconds':round(time.monotonic()-wall,6),
                  'cpu_seconds':round(time.process_time()-cpu,6)})
    status(name+'_COMPLETE')
    return result

def git(*args):
    result=subprocess.run([r'C:\Program Files\Git\cmd\git.exe','--no-optional-locks','-C',str(SOURCE),*args],
                          capture_output=True,text=True,check=True,timeout=20)
    return result.stdout.strip()

def main():
    check(socket.gethostname().split('.')[0].upper()=='DESKTOP-1R1081M','wrong diagnostic host')
    ROOT.mkdir(parents=True,exist_ok=False)
    with (ROOT/'execution.lock').open('x',encoding='utf-8') as f:
        f.write(str(os.getpid())+'\n')
    save('launch-receipt.json',{'pid':os.getpid(),'worker_sha256':sha(Path(__file__)),
                              'source_sha':SOURCE_SHA,'wall_seconds':120,'scope':'one diagnostic cell only'})
    trace=(ROOT/'deadline-stack.txt').open('w',encoding='utf-8')
    def deadline():
        status('DIAGNOSTIC_DEADLINE',reason='120-second bounded diagnostic deadline')
        faulthandler.dump_traceback(file=trace,all_threads=True)
        trace.flush()
        os._exit(124)
    watchdog=threading.Timer(120,deadline)
    watchdog.daemon=True
    watchdog.start()
    exit_code=1
    profile=cProfile.Profile()
    try:
        status('VERIFYING_DIAGNOSTIC_INPUTS')
        check(git('rev-parse','HEAD')==SOURCE_SHA,'source identity mismatch')
        check(not git('status','--porcelain'),'source is dirty')
        report_path=QA/'producer'/'research-report.json'
        check(sha(report_path)==REPORT_SHA,'native producer report bytes changed')
        report=json.loads(report_path.read_text(encoding='utf-8-sig'))
        check(report['report_digest']==digest({k:v for k,v in report.items() if k!='report_digest'}),
              'report canonical digest changed')
        versions={n:importlib.metadata.version(n) for n in ('numpy','pandas','pyarrow')}
        check(versions=={'numpy':'2.3.5','pandas':'2.3.3','pyarrow':'21.0.0'},'runtime pins changed')
        def offline(*args,**kwargs):
            raise RuntimeError('diagnostic is archive-only')
        class OfflineSocket(socket.socket):
            connect=offline
            connect_ex=offline
        socket.socket=OfflineSocket
        socket.create_connection=offline
        sys.dont_write_bytecode=True
        sys.path.insert(0,str(SOURCE))
        def import_research():
            import nexus_composite_strategy_research as research
            return research
        research=timed('IMPORT_EXISTING_SOURCE',import_research)
        def prohibited(*args,**kwargs):
            raise RuntimeError('full producer/tournament/replay prohibited in diagnostic')
        research.run=research._screen_frontier=prohibited
        archive=BASE/'dataset'/'canonical'
        profile.enable()
        frames=timed('DECODE_BTC_TIMEFRAMES',lambda:{tf:research.load_verified_archive_frame(archive,'BTCUSDT',tf)
                                                  for tf in ('minute15','hour1','hour4')})
        peer=timed('DECODE_ETH_PEER_15M',lambda:research.load_verified_archive_frame(archive,'ETHUSDT','minute15'))
        frame=timed('BUILD_BTC_CAUSAL_FEATURES',lambda:research.build_features(frames,peer_15m=peer))
        selected=report['selected']
        signals=timed('BUILD_FROZEN_BTC_SIGNAL',lambda:research.signal_for(frame,selected))
        n=len(frame)
        lo,hi=int(n*research.TRAIN_FRAC),int(n*(research.TRAIN_FRAC+research.VALID_FRAC))
        piece=frame.iloc[lo:hi].reset_index(drop=True)
        observed=next(r for r in report['rows'] if (r['symbol'],r['part'],r['profile'])==('BTCUSDT','validation','stress'))
        check(len(piece)==observed['bars'] and str(piece['decision_at'].iloc[0])==observed['first_closed_utc']
              and str(piece['decision_at'].iloc[-1])==observed['last_closed_utc'],'validation slice changed')
        result=timed('BACKTEST_ONE_BTC_VALIDATION_STRESS_CELL',lambda:research.backtest(
            piece,signals[lo:hi],fee_bps=research.STRESS_FEE_BPS,slip_bps=research.STRESS_SLIP_BPS,
            risk_variant=selected['risk_variant']))
        profile.disable()
        check(all(observed[k]==v for k,v in result.items()),'one-cell numerical result differs')
        check(not git('status','--porcelain'),'source changed during diagnostic')
        stream=io.StringIO()
        pstats.Stats(profile,stream=stream).strip_dirs().sort_stats('cumulative').print_stats(25)
        (ROOT/'profile-top.txt').write_text(stream.getvalue(),encoding='utf-8')
        profile.dump_stats(str(ROOT/'diagnostic.pstats'))
        core={'schema':'nexus.jump-one-cell-performance-diagnostic.v1','source_sha':SOURCE_SHA,
              'producer_report_digest':report['report_digest'],'steps':STEPS,'runtime_versions':versions,
              'symbol':'BTCUSDT','part':'validation','profile':'stress','bars':len(piece),
              'observed_result':result,'one_cell_matches':True,'independent_full_numeric_qa_complete':False,
              'independent_decimal_accounting_complete':False,'research_only':True,'auto_demo_promotion':False,
              'live_enabled':False,'official_coordinator_advanced':False}
        save('diagnostic-receipt.json',{**core,'diagnostic_digest':digest(core)})
        status('ONE_CELL_MATCHED_DIAGNOSTIC_ONLY',one_cell_matches=True)
        exit_code=0
    except Exception as exc:
        status('FAILED_DIAGNOSTIC',reason=type(exc).__name__+': '+str(exc))
        raise
    finally:
        profile.disable()
        watchdog.cancel()
        trace.close()
        (ROOT/'process-exit.txt').write_text('NATIVE_EXIT='+str(exit_code)+'\n',encoding='utf-8')

if __name__=='__main__':
    main()
