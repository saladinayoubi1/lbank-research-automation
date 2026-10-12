from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, os, pathlib, re, subprocess, time, urllib.request
D = pathlib.Path('/var/lib/nexus-vps-commissioning/soak-20261013-kernel146')
SCHEMA = 'nexus.vps-host-soak.v1'
DANGER = re.compile(r'soft\s+lockup|rcu.{0,80}stall|blocked\s+for\s+more\s+than|(?:buffer\s+)?i/o\s+error|ext4-fs\s+error|xfs.*corrupt', re.I)
CHECKS = {'cpu','memory','disk','uptime','ssh','ntp','kernel'}
def utc():
    return datetime.now(timezone.utc).isoformat()
def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def status(x):
    p = D/'status.tmp'
    with p.open('w') as f:
        json.dump(x,f,sort_keys=True,allow_nan=False)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(p,D/'status.json')
def sample(manifest):
    if pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=manifest['boot_id']:
        raise RuntimeError('boot identity changed')
    for path,expected in manifest['bound_sources'].items():
        if hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()!=expected:
            raise RuntimeError('bound commissioning source changed')
    unit=subprocess.check_output(['systemctl','show','nexus-arbiter-observer','-p','ActiveState','-p','MainPID','-p','NRestarts'],text=True,timeout=10)
    fields=dict(line.split('=',1) for line in unit.splitlines())
    if fields!={'ActiveState':'active','MainPID':manifest['observer_pid'],'NRestarts':manifest['observer_restarts']}:
        raise RuntimeError('observer stopped or restarted')
    with urllib.request.urlopen('http://127.0.0.1:8765/healthz',timeout=15) as response:
        health=json.load(response)
    if health.get('schema')!='nexus.vps-arbiter-observer.v1' or health.get('host_preflight')!='pass':
        raise RuntimeError('observer health is not pass')
    if set(health.get('checks',{}))!=CHECKS or any(v.get('ok') is not True for v in health['checks'].values()):
        raise RuntimeError('host checks incomplete or failed')
    if health.get('writer_authority')!='DISABLED' or health.get('paper_writer_grants_enabled') is not False or health.get('live_trading_authority') is not False or health.get('external_fencing_verified') is not False:
        raise RuntimeError('observer authority boundary changed')
    age=abs((datetime.now(timezone.utc)-datetime.fromisoformat(health['checked_at_utc'])).total_seconds())
    if age>30:
        raise RuntimeError('stale observer response')
    log=subprocess.check_output(['journalctl','-k','-b','--no-pager','--output=cat'],text=True,timeout=10)
    if not log.strip() or DANGER.search(log):
        raise RuntimeError('kernel log unavailable or danger detected')
    return {'health':health,'observer':fields,'kernel_danger_matches':0,'kernel_journal_sha256':hashlib.sha256(log.encode()).hexdigest()}
def main():
    manifest=json.loads((D/'manifest.json').read_text())
    start=time.clock_gettime(time.CLOCK_BOOTTIME)
    started=utc(); seq=0; previous='0'*64; last=None; max_gap=0.0
    base={'schema':SCHEMA,'scope':'local host and existing observer continuity','started_at_utc':started,'duration_required_seconds':86400,'interval_seconds':60,'maximum_allowed_sample_gap_seconds':90,'boot_id':manifest['boot_id'],'worker_sha256':manifest['worker_sha256'],'paper_writer_grants_enabled':False,'live_trading_authority':False,'external_fencing_verified':False}
    try:
        while True:
            observed=sample(manifest)
            now=time.clock_gettime(time.CLOCK_BOOTTIME)
            gap=0.0 if last is None else now-last
            max_gap=max(max_gap,gap)
            if gap>90:
                raise RuntimeError('observation coverage gap exceeded 90 seconds')
            seq+=1
            row={'sequence':seq,'checked_at_utc':utc(),'elapsed_seconds':now-start,'previous_digest':previous,'observation':observed}
            row['sample_digest']=digest(row)
            with (D/'samples.jsonl').open('a') as f:
                f.write(json.dumps(row,sort_keys=True,allow_nan=False)+'\n'); f.flush(); os.fsync(f.fileno())
            previous=row['sample_digest']; last=now
            done=now-start>=86400 and seq>=1441
            current={**base,'status':'COMPLETE' if done else 'RUNNING','last_checked_at_utc':row['checked_at_utc'],'elapsed_seconds':now-start,'sample_count':seq,'maximum_observed_sample_gap_seconds':max_gap,'last_digest':previous}
            status(current)
            if seq==1 or done:
                print(json.dumps(current,sort_keys=True),flush=True)
            if done:
                return 0
            time.sleep(max(0.0,start+seq*60-time.clock_gettime(time.CLOCK_BOOTTIME)))
    except Exception as exc:
        status({**base,'status':'FAILED','last_checked_at_utc':utc(),'elapsed_seconds':time.clock_gettime(time.CLOCK_BOOTTIME)-start,'sample_count':seq,'last_digest':previous,'reason':type(exc).__name__+': '+str(exc)[:240]})
        raise
if __name__=='__main__':
    raise SystemExit(main())
