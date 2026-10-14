"""Authenticated observational receipts for the existing VPS observer.

SSH must bind --authenticated-node through a server-owned forced command.
This module cannot authenticate an arbitrary caller, fence a writer or run work.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys

SCHEMA = "nexus.laptop-observation.v1"
PROJECTION = "nexus.laptop-visibility.v1"
NODES = {"DESKTOP-1R1081M":"runtime_paper_primary", "DESKTOP-F4SA4VL":"research_primary"}
TTL = 90
MAX_BYTES = 65536
SHA = re.compile(r"^[0-9a-f]{40}$")
STAGE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
AUTHORITY = {"paper_writer_grants_enabled":False, "live_trading_authority":False}


def utc(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must be aware")
    return result.astimezone(timezone.utc)


def now_utc():
    return datetime.now(timezone.utc)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def decode(data):
    if len(data) > MAX_BYTES:
        raise ValueError("payload too large")
    def bad_constant(value):
        raise ValueError("nonfinite JSON")
    return json.loads(data, object_pairs_hook=_pairs, parse_constant=bad_constant)


def _shape(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("observation schema mismatch")


def validate(payload, authenticated_node):
    _shape(payload, ("schema","node_id","observed_at_utc","reporter_source_sha",
                     "runner","coordinator","research", *AUTHORITY))
    if authenticated_node not in NODES or payload["node_id"] != authenticated_node:
        raise ValueError("node transport identity mismatch")
    if payload["schema"] != SCHEMA or not isinstance(payload["reporter_source_sha"], str) or not SHA.fullmatch(payload["reporter_source_sha"]):
        raise ValueError("unbound reporter source")
    if any(payload[key] is not False for key in AUTHORITY):
        raise ValueError("observation cannot grant authority")
    observed = utc(payload["observed_at_utc"])
    for name, keys in {
        "runner":("observed_at_utc","listener_count"),
        "coordinator":("observed_at_utc","local_process_alive","internet_reachable"),
        "research":("observed_at_utc","stage","completed_cells","source_sha"),
    }.items():
        item = payload[name]
        _shape(item, keys)
        stamp = item["observed_at_utc"]
        if stamp is not None and utc(stamp) > observed:
            raise ValueError("component observation follows reporter")
        for key, value in item.items():
            if key in ("listener_count","completed_cells") and value is not None:
                limit = 64 if key == "listener_count" else 1000000
                if type(value) is not int or not 0 <= value <= limit:
                    raise ValueError("invalid observation counter")
            if key in ("local_process_alive","internet_reachable") and value is not None and type(value) is not bool:
                raise ValueError("invalid observation flag")
            if key == "stage" and value is not None and (not isinstance(value,str) or not STAGE.fullmatch(value)):
                raise ValueError("invalid progress stage")
            if key == "source_sha" and value is not None and (not isinstance(value,str) or not SHA.fullmatch(value)):
                raise ValueError("invalid workload source")
        if stamp is None and any(value is not None for key,value in item.items() if key != "observed_at_utc"):
            raise ValueError("unbound component observation")
    return observed


@contextmanager
def _connect(path, writable=False):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("missing or unsafe telemetry state")
    db = sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro"),
                         uri=True, timeout=2)
    try:
        # The SQLite transaction context commits/rolls back but does not close.
        with db:
            yield db
    finally:
        db.close()


def initialize(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path.parent, *path.parent.parents)):
        raise ValueError("unsafe telemetry parent")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with _connect(path, True) as db:
        db.execute("CREATE TABLE receipts(node_id TEXT PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL, received_at TEXT NOT NULL)")


def receive(path, payload, authenticated_node, *, now=None):
    now = now or now_utc()
    observed = validate(payload, authenticated_node)
    age = (now - observed).total_seconds()
    if not -5 <= age <= TTL:
        raise ValueError("stale or future heartbeat")
    stamp, hashed = now.isoformat(), digest(payload)
    with _connect(path, True) as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT payload,digest,received_at FROM receipts WHERE node_id=?", (authenticated_node,)).fetchone()
        if old:
            prior = decode(old[0])
            prior_time = validate(prior, authenticated_node)
            if digest(prior) != old[1] or now < utc(old[2]):
                raise ValueError("corrupt state or receiver clock rollback")
            if old[1] == hashed:
                return {"status":"ALREADY_ACCEPTED","received_at_utc":old[2],"payload_digest":hashed, **AUTHORITY}
            if observed <= prior_time:
                raise ValueError("heartbeat replay")
        db.execute("INSERT OR REPLACE INTO receipts VALUES(?,?,?,?)",
                   (authenticated_node,canonical(payload),hashed,stamp))
    return {"status":"ACCEPTED","received_at_utc":stamp,"payload_digest":hashed, **AUTHORITY}


def _component(item, now, contact_fresh):
    stamp = item["observed_at_utc"]
    age = None if stamp is None else (now-utc(stamp)).total_seconds()
    fresh = contact_fresh and age is not None and 0 <= age <= TTL
    return {"freshness":"FRESH" if fresh else "UNAVAILABLE" if stamp is None else "STALE",
            "age_seconds":age, "current":item if fresh else None, "last_observation":item}


def snapshot(path=None, *, now=None):
    now = now or now_utc()
    result = {"schema":PROJECTION,"checked_at_utc":now.isoformat(),"nodes":{},
              "scope":"authenticated_reports_not_fencing_or_independent_execution_proof", **AUTHORITY}
    rows, unavailable = {}, path is None
    if path is not None:
        try:
            with _connect(path) as db:
                rows = {row[0]:row[1:] for row in db.execute("SELECT node_id,payload,digest,received_at FROM receipts")}
            if set(rows) - set(NODES):
                raise ValueError("unknown stored node")
        except (OSError, ValueError, sqlite3.Error):
            unavailable = True
    for node, role in NODES.items():
        item = {"role":role,"contact":"STATE_UNAVAILABLE" if unavailable else "NOT_SEEN",
                "last_received_at_utc":None,"age_seconds":None,"runner":None,"coordinator":None,"research":None}
        if not unavailable and node in rows:
            try:
                raw, hashed, received = rows[node]
                payload = decode(raw)
                observed = validate(payload,node)
                if digest(payload) != hashed or (utc(received)-observed).total_seconds() < -5:
                    raise ValueError("corrupt receipt")
                age = (now-utc(received)).total_seconds()
                report_age = (now-observed).total_seconds()
                item.update(last_received_at_utc=received,age_seconds=max(age,report_age))
                item["contact"] = "CLOCK_ANOMALY" if min(age,report_age) < 0 else "FRESH" if max(age,report_age) <= TTL else "NO_RECENT_HEARTBEAT"
                for part in ("runner","coordinator","research"):
                    item[part] = _component(payload[part], now, item["contact"] == "FRESH")
            except (OSError, ValueError, TypeError, KeyError):
                item["contact"] = "STATE_UNAVAILABLE"
        result["nodes"][node] = item
    return result


def _read_optional(path):
    if path is None:
        return None
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        result = decode(data)
        return result if isinstance(result,dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def listener_count():
    if os.name != "nt":
        return None
    try:
        proc = subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",
            "(Get-Process -Name Runner.Listener -ErrorAction SilentlyContinue | Measure-Object).Count"],
            capture_output=True,text=True,timeout=3,check=False)
        value = int(proc.stdout.strip())
        return value if proc.returncode == 0 and 0 <= value <= 64 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def collect(source_sha, *, heartbeat_file=None, research_status=None, host=None, probe=listener_count, now=None):
    now = now or now_utc()
    host = (host or socket.gethostname()).split(".")[0].upper()
    if host not in NODES or not SHA.fullmatch(source_sha):
        raise ValueError("export must run on a known node with an exact source")
    count = probe()
    runner = {"observed_at_utc":now.isoformat() if count is not None else None,"listener_count":count}
    coordinator = {"observed_at_utc":None,"local_process_alive":None,"internet_reachable":None}
    heartbeat = _read_optional(heartbeat_file)
    if heartbeat is not None:
        try:
            utc(heartbeat["generated_at"])
            if type(heartbeat["local_process_alive"]) is bool and type(heartbeat["internet_reachable"]) is bool:
                coordinator.update(observed_at_utc=heartbeat["generated_at"],
                    local_process_alive=heartbeat["local_process_alive"],internet_reachable=heartbeat["internet_reachable"])
        except (KeyError,ValueError,TypeError):
            pass
    research = {"observed_at_utc":None,"stage":None,"completed_cells":None,"source_sha":None}
    progress = _read_optional(research_status)
    if progress is not None:
        try:
            candidate = {"observed_at_utc":progress["checked_at_utc"],"stage":progress["status"],
                         "completed_cells":progress.get("completed_cells"),"source_sha":progress.get("source_sha")}
            trial = {"schema":SCHEMA,"node_id":host,"observed_at_utc":now.isoformat(),"reporter_source_sha":source_sha,
                     "runner":runner,"coordinator":coordinator,"research":candidate, **AUTHORITY}
            validate(trial,host)
            research = candidate
        except (KeyError, ValueError, TypeError):
            pass
    payload = {"schema":SCHEMA,"node_id":host,"observed_at_utc":now.isoformat(),"reporter_source_sha":source_sha,
               "runner":runner,"coordinator":coordinator,"research":research, **AUTHORITY}
    try:
        validate(payload,host)
    except ValueError:
        payload["coordinator"] = {"observed_at_utc":None,"local_process_alive":None,"internet_reachable":None}
        validate(payload,host)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command",required=True)
    init = commands.add_parser("init"); init.add_argument("--db",type=Path,required=True)
    ingest = commands.add_parser("receive")
    ingest.add_argument("--db",type=Path,required=True)
    ingest.add_argument("--authenticated-node",choices=tuple(NODES),required=True)
    view = commands.add_parser("snapshot"); view.add_argument("--db",type=Path,required=True)
    export = commands.add_parser("export")
    export.add_argument("--source-sha",required=True)
    export.add_argument("--heartbeat-file",type=Path)
    export.add_argument("--research-status",type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            initialize(args.db); result = {"status":"INITIALIZED", **AUTHORITY}
        elif args.command == "receive":
            result = receive(args.db,decode(sys.stdin.buffer.read(MAX_BYTES+1)),args.authenticated_node)
        elif args.command == "snapshot":
            result = snapshot(args.db)
        else:
            result = collect(args.source_sha,heartbeat_file=args.heartbeat_file,research_status=args.research_status)
        print(canonical(result))
        return 0
    except (OSError, ValueError, TypeError, sqlite3.Error):
        print(canonical({"status":"REJECTED", **AUTHORITY}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

