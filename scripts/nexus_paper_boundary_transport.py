"""Strict Paper boundary transport selector; no private Paper state leaves owner volume."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

STATE_NAME = "nexus-persistent-paper-trading-state"
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_REQUIRED_STEPS = (
    "Restore owner-controlled Paper checkpoint in primary mode",
    "Independently enforce Paper authority and mission truth",
    "Package Paper state for hosted artifact persistence",
    "Commit owner-controlled Paper checkpoint when enabled",
)


class TransportError(ValueError):
    """Fail-closed error: do not dispatch unverified Paper feedback."""


def choose(artifacts: dict, jobs: dict, run_id: str, source_sha: str,
           requested_id: str = "", requested_digest: str = "") -> dict:
    if not re.fullmatch(r"[1-9][0-9]{5,19}", run_id):
        raise TransportError("invalid exact Paper run id")
    if not _SHA40.fullmatch(source_sha):
        raise TransportError("invalid exact Paper source SHA")

    if requested_id and not re.fullmatch(r"[1-9][0-9]{5,19}", requested_id):
        raise TransportError("invalid recovery artifact id")
    if requested_digest and not _SHA64.fullmatch(requested_digest):
        raise TransportError("invalid recovery artifact digest")
    if bool(requested_id) != bool(requested_digest):
        raise TransportError("incomplete recovery artifact binding")
    rows = artifacts.get("artifacts")
    if (not isinstance(rows, list) or
            not isinstance(artifacts.get("total_count"), int) or
            artifacts["total_count"] > 100 or artifacts["total_count"] != len(rows)):
        raise TransportError("artifact enumeration missing, paginated, or invalid")
    matches = [x for x in rows if x.get("name") == STATE_NAME]
    if len(matches) > 1:
        raise TransportError("ambiguous Paper state artifacts in exact run")
    if matches:
        row = matches[0]
        binding = row.get("workflow_run") or {}
        digest = row.get("digest")
        if (row.get("expired") is not False or
                str(binding.get("id")) != run_id or
                binding.get("head_branch") != "main" or
                binding.get("head_sha") != source_sha or
                not isinstance(digest, str) or
                not digest.startswith("sha256:") or
                not _SHA64.fullmatch(digest[7:])):
            raise TransportError("Paper state artifact provenance is invalid")
        artifact_id = str(row.get("id"))
        if requested_id and (artifact_id != requested_id or
                             digest[7:] != requested_digest):
            raise TransportError("recovery artifact id or digest mismatch")
        return {"mode": "public_artifact", "artifact_id": artifact_id,
                "artifact_sha256": digest[7:], "run_id": run_id,
                "source_sha": source_sha}

    if requested_id:
        raise TransportError("requested Paper state artifact is missing")
    entries = jobs.get("jobs")
    if (not isinstance(entries, list) or
            not isinstance(jobs.get("total_count"), int) or
            jobs["total_count"] > 100 or jobs["total_count"] != len(entries)):
        raise TransportError("job enumeration missing, paginated, or invalid")
    paper = [j for j in entries if j.get("name") == "paper-loop" and
             str(j.get("run_id")) == run_id and j.get("conclusion") == "success"]
    persist = [j for j in entries if j.get("name") == "persist-state" and
               str(j.get("run_id")) == run_id and
               j.get("conclusion") in {"skipped", "success"}]
    if len(paper) != 1 or len(persist) != 1:
        raise TransportError("no verified owner-primary checkpoint job transition")
    persist_job = persist[0]
    if persist_job.get("conclusion") == "success":
        persist_steps = persist_job.get("steps") or []
        private_restore = [
            s for s in persist_steps
            if s.get("name") == "Rehydrate physical Paper state handoff"
        ]
        public_proof = [
            s for s in persist_steps
            if s.get("name") == "Rehydrate and independently verify public Paper boundary proof"
        ]
        if (len(private_restore) != 1 or private_restore[0].get("conclusion") != "skipped" or
                len(public_proof) != 1 or public_proof[0].get("conclusion") != "success"):
            raise TransportError("owner-primary public boundary persistence is not verified")
    steps = paper[0].get("steps") or []
    for name in _REQUIRED_STEPS:
        found = [s for s in steps if s.get("name") == name]
        if len(found) != 1 or found[0].get("conclusion") != "success":
            raise TransportError("owner-primary checkpoint step is not verified: " + name)
    legacy = [s for s in steps if s.get("name") == "Restore newest persistent Paper state"]
    if len(legacy) != 1 or legacy[0].get("conclusion") != "skipped":
        raise TransportError("owner-primary restore exclusivity is not verified")
    return {"mode": "owner_checkpoint_primary_no_public_artifact",
            "artifact_id": "", "artifact_sha256": "", "run_id": run_id,
            "source_sha": source_sha,
            "discovery_dispatch": False,
            "reason": "private owner checkpoint is verified but cannot be read by hosted gate"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--requested-id", default="")
    parser.add_argument("--requested-digest", default="")
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    result = choose(
        json.loads(options.artifacts.read_text(encoding="utf-8")),
        json.loads(options.jobs.read_text(encoding="utf-8")),
        options.run_id, options.source_sha,
        options.requested_id, options.requested_digest,
    )
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print("paper_boundary_transport=" + result["mode"])


if __name__ == "__main__":
    main()
