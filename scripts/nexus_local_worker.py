"""Bounded persistent worker for the NEXUS self-hosted runner.

The worker repeatedly executes only repository-defined, allow-listed local tasks.
It never accepts arbitrary shell commands and never performs live-trading,
production, signing, billing or credential-management actions.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

QUEUE = pathlib.Path('.nexus/autonomous-queue.json')
HEARTBEAT = pathlib.Path('build/autonomy/worker-heartbeat.json')

COMMANDS = {
    'health': [sys.executable, '-m', 'pytest', '-q', 'tests/test_nexus_architecture_validator.py', 'tests/test_web_dashboard.py'],
    'tests': [sys.executable, '-m', 'pytest', '-q'],
    'readiness': [sys.executable, 'data_readiness.py', '--status-path', r'data\market\_backfill_status.csv'],
    'zotero-status': [sys.executable, '-c', "import urllib.request; urllib.request.urlopen('http://127.0.0.1:23119/connector/ping',timeout=5); print('zotero=ok')"],
    'ai-council-health': ['node', 'scripts/nexus_ai_council.js'],
}


def load_queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    data = json.loads(QUEUE.read_text(encoding='utf-8'))
    if not isinstance(data, list):
        raise RuntimeError('autonomous queue must be a list')
    return data


def save_queue(queue: list[dict]) -> None:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(queue, indent=2, sort_keys=True), encoding='utf-8')
    tmp.replace(QUEUE)


def write_heartbeat(**extra: object) -> None:
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    payload = {'pid': os.getpid(), 'time': time.time(), **extra}
    HEARTBEAT.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')


def next_task(queue: list[dict]) -> tuple[int, dict] | None:
    for index, task in enumerate(queue):
        if task.get('status', 'pending') != 'pending':
            continue
        name = str(task.get('task', '')).strip()
        if name not in COMMANDS:
            task['status'] = 'blocked'
            task['block_reason'] = 'task_not_allowlisted'
            continue
        return index, task
    return None


def run_once() -> bool:
    queue = load_queue()
    selected = next_task(queue)
    if selected is None:
        save_queue(queue)
        write_heartbeat(state='idle')
        return False
    index, task = selected
    name = str(task['task'])
    queue[index]['status'] = 'running'
    queue[index]['started_at'] = time.time()
    save_queue(queue)
    write_heartbeat(state='running', task=name, task_id=task.get('id'))
    result = subprocess.run(COMMANDS[name], check=False)
    queue = load_queue()
    if index >= len(queue):
        raise RuntimeError('queue changed incompatibly during task execution')
    queue[index]['finished_at'] = time.time()
    queue[index]['exit_code'] = result.returncode
    queue[index]['status'] = 'completed' if result.returncode == 0 else 'failed'
    save_queue(queue)
    write_heartbeat(state=queue[index]['status'], task=name, task_id=task.get('id'), exit_code=result.returncode)
    return True


def main() -> None:
    max_seconds = int(os.environ.get('NEXUS_WORKER_MAX_SECONDS', '3300'))
    idle_sleep = int(os.environ.get('NEXUS_WORKER_IDLE_SLEEP', '60'))
    started = time.monotonic()
    while time.monotonic() - started < max_seconds:
        did_work = run_once()
        if not did_work:
            time.sleep(idle_sleep)
    write_heartbeat(state='cycle_complete')


if __name__ == '__main__':
    main()
