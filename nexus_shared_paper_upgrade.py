"""Explicit pre-first-fill upgrade; preserve old account evidence, never reset used funds."""
from copy import deepcopy
import json
from pathlib import Path
import nexus_owner_multistrategy_demo_v3 as multi


def migrate(old_root: Path, new_root: Path, source_sha: str, expected_old_engine: str):
    if len(source_sha) != 40 or any(c not in '0123456789abcdef' for c in source_sha):
        raise ValueError('exact source required')
    if new_root.exists():
        raise ValueError('upgrade destination already exists')
    if not (old_root/'STOP').exists():
        raise ValueError('prior runtime must stop before upgrade')
    with multi.prior.writer_lock(old_root):
        a_bytes = (old_root/'activation.json').read_bytes()
        s_bytes = (old_root/'state.json').read_bytes()
        a = multi.verified(json.loads(a_bytes)); s = multi.verified(json.loads(s_bytes))
        if a['engine_digest'] != expected_old_engine or a['source_sha'] != '9d905d052b5c2970ff4f089a6e4c29132c240e7a':
            raise ValueError('prior source binding mismatch')
        multi.verify_state(s, a)
        if s['last_execution_utc'] is not None or s['events']:
            raise ValueError('used account requires full historical migration; refusing reset')
        for lane in s['lanes'].values():
            if lane['events'] or lane['completed_bar_count']:
                raise ValueError('prior observations present')
            for p in lane['profiles'].values():
                if (p['wallet'] != 125 or p['equity'] != 125 or p['fees'] or p['funding_cashflow']
                        or p['fill_count'] or p['orders'] or any(x['quantity'] for x in p['positions'])):
                    raise ValueError('used account; refusing balance reset')
        na = deepcopy(a); ns = deepcopy(s)
        na.update(source_sha=source_sha, engine_digest=multi.engine_digest(),
            upgrade_from_activation=a['digest'], upgrade_from_state=s['digest'],
            upgrade_reason='owner_requested_execution_journal_and_terminal')
        na = multi.seal(na)
        ns['activation_digest'] = na['digest']
        for lane in ns['lanes'].values():
            lane['engine_sha256'] = na['engine_digest']
            lane['latest_source_sha'] = source_sha
            lane.pop('state_digest')
            lane['state_digest'] = multi.forward._digest(lane)
        ns = multi.seal(ns)
        multi.verify_state(ns, na)
        new_root.mkdir(parents=True)
        (new_root/'before-upgrade-activation.json').write_bytes(a_bytes)
        (new_root/'before-upgrade-state.json').write_bytes(s_bytes)
        multi.forward.save_state(new_root/'state.json', ns)
        multi.forward.save_state(new_root/'activation.json', na)
    return {'old_state_digest': s['digest'], 'new_state_digest': ns['digest'], 'capital': 500}
