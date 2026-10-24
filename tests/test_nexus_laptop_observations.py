from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

import nexus_laptop_observations as nodes
import nexus_vps_arbiter_observer as observer

T = datetime(2026,10,13,20,0,tzinfo=timezone.utc)
FIRST, SECOND = tuple(nodes.NODES)


def payload(host=FIRST, at=T):
    return nodes.collect("a"*40,host=host,probe=lambda:1,now=at)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name).resolve()/"nodes.sqlite3"
        nodes.initialize(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_two_nodes_roles_and_restart_persistence(self):
        nodes.receive(self.db,payload(),FIRST,now=T)
        nodes.receive(self.db,payload(SECOND),SECOND,now=T)
        view = nodes.snapshot(self.db,now=T+timedelta(seconds=10))
        self.assertEqual({x["contact"] for x in view["nodes"].values()},{"FRESH"})
        self.assertEqual(view["nodes"][FIRST]["role"],"runtime_paper_primary")
        self.assertEqual(view["nodes"][SECOND]["role"],"research_primary")
        self.assertFalse(view["paper_writer_grants_enabled"])
        self.assertFalse(view["live_trading_authority"])
        # A new process/store instance retains receipt watermarks.
        self.assertEqual(nodes.snapshot(self.db,now=T)["nodes"][FIRST]["contact"],"FRESH")
        with self.assertRaises(FileExistsError):
            nodes.initialize(self.db)

    def test_transport_identity_role_and_extra_field_spoofing_rejected(self):
        with self.assertRaises(ValueError):
            nodes.receive(self.db,payload(SECOND),FIRST,now=T)
        with self.assertRaises(ValueError):
            nodes.receive(self.db,payload(),"OTHER",now=T)
        for field,value in (("role","runtime_paper_primary"),("live_trading_authority",True),
                            ("paper_writer_grants_enabled",True),("reporter_source_sha","invalid")):
            data = payload(); data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                nodes.receive(self.db,data,FIRST,now=T)

    def test_stale_future_naive_and_reordered_heartbeats_rejected(self):
        for at in (T-timedelta(seconds=91),T+timedelta(seconds=6)):
            with self.subTest(at=at),self.assertRaises(ValueError):
                nodes.receive(self.db,payload(at=at),FIRST,now=T)
        data=payload();data["observed_at_utc"]="2026-10-13T20:00:00"
        with self.assertRaises(ValueError):
            nodes.receive(self.db,data,FIRST,now=T)
        nodes.receive(self.db,payload(at=T+timedelta(seconds=2)),FIRST,now=T+timedelta(seconds=2))
        with self.assertRaises(ValueError):
            nodes.receive(self.db,payload(),FIRST,now=T+timedelta(seconds=3))

    def test_duplicate_does_not_refresh_contact_and_delayed_input_does_not_extend_ttl(self):
        initial=nodes.receive(self.db,payload(),FIRST,now=T)
        duplicate=nodes.receive(self.db,payload(),FIRST,now=T+timedelta(seconds=80))
        self.assertEqual(duplicate["status"],"ALREADY_ACCEPTED")
        self.assertEqual(initial["received_at_utc"],duplicate["received_at_utc"])
        self.assertEqual(nodes.snapshot(self.db,now=T+timedelta(seconds=91))["nodes"][FIRST]["contact"],"NO_RECENT_HEARTBEAT")
        self.assertIsNone(nodes.snapshot(self.db,now=T+timedelta(seconds=91))["nodes"][FIRST]["runner"]["current"])
        nodes.receive(self.db,payload(SECOND,at=T),SECOND,now=T+timedelta(seconds=89))
        self.assertEqual(nodes.snapshot(self.db,now=T+timedelta(seconds=91))["nodes"][SECOND]["contact"],"NO_RECENT_HEARTBEAT")

    def test_same_timestamp_changed_content_is_replay(self):
        nodes.receive(self.db,payload(),FIRST,now=T)
        data=payload();data["runner"]["listener_count"]=2
        with self.assertRaises(ValueError):
            nodes.receive(self.db,data,FIRST,now=T+timedelta(seconds=1))

    def test_clock_rollback_cannot_accept_or_project_fresh(self):
        nodes.receive(self.db,payload(),FIRST,now=T)
        self.assertEqual(nodes.snapshot(self.db,now=T-timedelta(seconds=1))["nodes"][FIRST]["contact"],"CLOCK_ANOMALY")
        self.assertIsNone(nodes.snapshot(self.db,now=T-timedelta(seconds=1))["nodes"][FIRST]["runner"]["current"])
        with self.assertRaises(ValueError):
            nodes.receive(self.db,payload(at=T+timedelta(seconds=1)),FIRST,now=T-timedelta(seconds=1))

    def test_component_freshness_is_independent_of_laptop_contact(self):
        data=payload()
        data["research"]={"observed_at_utc":(T-timedelta(seconds=200)).isoformat(),
            "stage":"AUDITING_DECIMAL_ACCOUNTING","completed_cells":3,"source_sha":"b"*40}
        nodes.receive(self.db,data,FIRST,now=T)
        view=nodes.snapshot(self.db,now=T)["nodes"][FIRST]
        self.assertEqual(view["contact"],"FRESH")
        self.assertEqual(view["research"]["freshness"],"STALE")
        self.assertIsNone(view["research"]["current"])
        self.assertEqual(view["research"]["last_observation"]["completed_cells"],3)
        self.assertEqual(view["runner"]["freshness"],"FRESH")
        self.assertEqual(view["coordinator"]["freshness"],"UNAVAILABLE")

    def test_missing_corrupt_and_tampered_state_never_claims_fresh(self):
        missing=nodes.snapshot(self.db.parent/"missing.db",now=T)
        self.assertEqual({x["contact"] for x in missing["nodes"].values()},{"STATE_UNAVAILABLE"})
        nodes.receive(self.db,payload(),FIRST,now=T)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE receipts SET digest='bad' WHERE node_id=?",(FIRST,))
        self.assertEqual(nodes.snapshot(self.db,now=T)["nodes"][FIRST]["contact"],"STATE_UNAVAILABLE")
        bad=self.db.parent/"bad.db";bad.write_bytes(b"not sqlite")
        self.assertEqual(nodes.snapshot(bad,now=T)["nodes"][SECOND]["contact"],"STATE_UNAVAILABLE")

    def test_new_store_and_unconfigured_observer_have_truthful_unknowns(self):
        self.assertEqual(nodes.snapshot(self.db,now=T)["nodes"][FIRST]["contact"],"NOT_SEEN")
        self.assertEqual(nodes.snapshot(now=T)["nodes"][FIRST]["contact"],"STATE_UNAVAILABLE")

    def test_counter_flags_timestamp_and_progress_payloads_fail_closed(self):
        mutations = [
            lambda p:p["runner"].update(listener_count=True),
            lambda p:p["runner"].update(listener_count=-1),
            lambda p:p["coordinator"].update(observed_at_utc=T.isoformat(),local_process_alive="yes"),
            lambda p:p["research"].update(observed_at_utc=T.isoformat(),stage="secret error /path"),
            lambda p:p["runner"].update(observed_at_utc=(T+timedelta(seconds=1)).isoformat()),
            lambda p:p["runner"].update(observed_at_utc=None),
        ]
        for mutate in mutations:
            data=payload();mutate(data)
            with self.subTest(data=data),self.assertRaises(ValueError):
                nodes.receive(self.db,data,FIRST,now=T)

    def test_duplicate_json_keys_nonfinite_and_oversize_rejected(self):
        for data in ('{"node_id":"a","node_id":"b"}','{"x":NaN}',b" "*65537):
            with self.subTest(data=str(data)[:40]),self.assertRaises(ValueError):
                nodes.decode(data)

    def test_concurrent_nodes_do_not_overwrite_each_other(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda host:nodes.receive(self.db,payload(host),host,now=T),nodes.NODES))
        self.assertEqual({x["contact"] for x in nodes.snapshot(self.db,now=T)["nodes"].values()},{"FRESH"})

    def test_retained_connections_are_closed_on_all_receipt_paths(self):
        # Retain real connections so GC cannot hide handles that lock Windows DBs.
        connect = sqlite3.connect
        retained = []

        def retain(*args, **kwargs):
            db = connect(*args, **kwargs)
            retained.append(db)
            return db

        db_path = self.db.parent / "retained.db"
        corrupt_path = self.db.parent / "retained-corrupt.db"
        try:
            with patch.object(nodes.sqlite3, "connect", side_effect=retain):
                nodes.initialize(db_path)
                nodes.receive(db_path, payload(), FIRST, now=T)
                duplicate = nodes.receive(db_path, payload(), FIRST, now=T)
                self.assertEqual(duplicate["status"], "ALREADY_ACCEPTED")
                replay = payload()
                replay["runner"]["listener_count"] = 2
                with self.assertRaises(ValueError):
                    nodes.receive(db_path, replay, FIRST, now=T)
                self.assertEqual(nodes.snapshot(db_path, now=T)["nodes"][FIRST]["contact"], "FRESH")
                corrupt_path.write_bytes(b"not sqlite")
                self.assertEqual(nodes.snapshot(corrupt_path, now=T)["nodes"][FIRST]["contact"], "STATE_UNAVAILABLE")
            self.assertEqual(len(retained), 6)
            for db in retained:
                with self.subTest(connection=db), self.assertRaises(sqlite3.ProgrammingError):
                    db.execute("SELECT 1")
            db_path.unlink()
            corrupt_path.unlink()
        finally:
            for db in retained:
                db.close()

    def test_cli_identity_rejection_is_sanitized(self):
        proc=subprocess.run([sys.executable,nodes.__file__,"receive","--db",str(self.db),
            "--authenticated-node",FIRST],input=nodes.canonical(payload(SECOND)),
            capture_output=True,text=True,timeout=5)
        self.assertEqual(proc.returncode,2)
        self.assertEqual(json.loads(proc.stdout)["status"],"REJECTED")
        self.assertNotIn("Traceback",proc.stderr)


class ExportTests(unittest.TestCase):
    def test_reads_existing_heartbeat_and_progress_without_exporting_error_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            heartbeat=Path(tmp)/"heartbeat.json";progress=Path(tmp)/"status.json"
            heartbeat.write_text(json.dumps({"generated_at":T.isoformat(),"local_process_alive":True,
                "internet_reachable":False,"network_error":"TOKEN_MUST_NOT_BE_EXPORTED",
                "pid":999,"unrelated_private_field":"PRIVATE"}))
            progress.write_text(json.dumps({"checked_at_utc":T.isoformat(),"status":"BUILDING_FEATURES",
                "completed_cells":0,"source_sha":"b"*40,"error":"PASSWORD_MUST_NOT_BE_EXPORTED"}))
            result=nodes.collect("a"*40,host=SECOND,probe=lambda:2,now=T,
                heartbeat_file=heartbeat,research_status=progress)
            self.assertEqual(result["runner"]["listener_count"],2)
            self.assertEqual(result["research"]["stage"],"BUILDING_FEATURES")
            self.assertFalse(result["coordinator"]["internet_reachable"])
            self.assertNotIn("MUST_NOT",nodes.canonical(result))
            self.assertNotIn("PRIVATE",nodes.canonical(result))

    def test_bad_missing_and_future_local_inputs_remain_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad=Path(tmp)/"bad";bad.write_text("{bad json")
            result=nodes.collect("a"*40,host=FIRST,probe=lambda:None,now=T,heartbeat_file=bad,research_status=bad)
            self.assertIsNone(result["runner"]["observed_at_utc"])
            self.assertIsNone(result["research"]["stage"])
            future=Path(tmp)/"future";future.write_text(json.dumps({"generated_at":(T+timedelta(seconds=10)).isoformat(),
                "local_process_alive":True,"internet_reachable":True}))
            result=nodes.collect("a"*40,host=FIRST,probe=lambda:None,now=T,heartbeat_file=future)
            self.assertIsNone(result["coordinator"]["local_process_alive"])
        with self.assertRaises(ValueError):
            nodes.collect("a"*40,host="OTHER",probe=lambda:None,now=T)

    def test_export_is_single_shot_and_has_no_scheduler_or_authority(self):
        result=nodes.collect("a"*40,host=FIRST,probe=lambda:0,now=T)
        self.assertFalse(result["paper_writer_grants_enabled"])
        self.assertFalse(result["live_trading_authority"])
        self.assertEqual(result["runner"]["listener_count"],0)


class ObserverNodeHTTPTests(unittest.TestCase):
    def test_projection_uses_existing_service_and_preserves_denials(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp).resolve()/"nodes.db";nodes.initialize(db)
            nodes.receive(db,payload(),FIRST,now=T)
            server=ThreadingHTTPServer(("127.0.0.1",0),observer.Handler)
            server.node_state=db
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with patch.object(nodes,"now_utc",return_value=T):
                    con=HTTPConnection("127.0.0.1",server.server_port,timeout=3)
                    con.request("GET","/nodes")
                    response=con.getresponse();body=json.loads(response.read())
                    self.assertEqual(response.status,200)
                    self.assertEqual(body["nodes"][FIRST]["contact"],"FRESH")
                    self.assertEqual(body["nodes"][SECOND]["contact"],"NOT_SEEN")
                    con.close()
                for method,path,expected in (("POST","/nodes",403),("GET","/permit",503),("GET","/readyz",503)):
                    con=HTTPConnection("127.0.0.1",server.server_port,timeout=3)
                    con.request(method,path,body=b"{}" if method=="POST" else None)
                    response=con.getresponse();body=json.loads(response.read())
                    self.assertEqual(response.status,expected)
                    self.assertFalse(body["paper_writer_grants_enabled"])
                    self.assertFalse(body["live_trading_authority"])
                    con.close()
            finally:
                server.shutdown();server.server_close();thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()

