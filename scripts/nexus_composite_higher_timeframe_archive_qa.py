"""Feature-only QA of fixed archive rows; never regenerate signals or trades."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import nexus_composite_higher_timeframe_audit as audit
import nexus_composite_strategy_research as composite
from nexus_multitimeframe_verified_archive_discovery import load_verified_archive_frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    if (request.get("schema_version") != "nexus.composite-higher-timeframe-archive-request.v1"
            or not re.fullmatch(r"[0-9a-f]{40}", args.source_sha)
            or request.get("signal_generation_permitted") is not False
            or request.get("financial_replay_permitted") is not False):
        raise ValueError("feature-only request identity/scope rejected")
    for name, expected in request["code_sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError("feature source bytes differ from frozen request: " + name)
    if args.output.exists():
        raise ValueError("refuse to overwrite an existing feature-only audit")
    args.output.mkdir(parents=True)
    def prohibited(*args, **kwargs):
        raise RuntimeError("signals and financial replay are outside feature-only QA")
    composite.signal_for = prohibited
    composite.backtest = prohibited
    rows = []
    identity = audit.digest(request)
    for symbol, directory in (("BTCUSDT", "btc_usdt"), ("ETHUSDT", "eth_usdt")):
        frames, datasets, hashes = {}, {}, {}
        for tf in ("minute15", "hour1", "hour4"):
            relative = f"bybit_market/{directory}/{tf}.parquet"
            path = args.archive_root / relative
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if sha != request["input_sha256"][relative]:
                raise ValueError("archive raw identity differs from frozen request: " + relative)
            f = load_verified_archive_frame(args.archive_root, symbol, tf)
            if not 160 <= len(f) <= 150_000:
                raise ValueError("archive series exceeds fixed QA bounds")
            f["timestamp"] = pd.to_datetime(f["timestamp"], utc=True)
            frames[tf] = f
            hashes[relative] = sha
            datasets[tf] = {"timeframe": tf, "binding_sha256": sha, "row_count": len(f),
                            "first_open_time_ms": int(f.timestamp.iloc[0].value // 1_000_000),
                            "last_open_time_ms": int(f.timestamp.iloc[-1].value // 1_000_000)}
        features = composite.build_features(frames)
        proof = audit.audit_features(frames, features, candidate_digest=identity,
                                     source_sha=args.source_sha, symbol=symbol, datasets=datasets,
                                     source_kind="pinned_archive_parquet_rows")
        # identity is the fixed QA request, never a new strategy/frontier proposal.
        filename = symbol.lower() + "-higher-timeframe-feature-audit.json"
        (args.output / filename).write_text(json.dumps(proof, separators=(",", ":"),
                                                        sort_keys=True, allow_nan=False), encoding="utf-8")
        rows.append({"symbol": symbol, "datasets": datasets, "input_file_sha256": hashes,
                     "audited_15m_decisions": len(features), "audited_context_cells": len(features)*4,
                     "first_decision_utc": features.decision_at.iloc[0].isoformat(),
                     "last_decision_utc": features.decision_at.iloc[-1].isoformat(),
                     "mismatched_context_cells": 0, "audit_digest": proof["audit_digest"],
                     "proof_file": filename, "proof_file_sha256": hashlib.sha256((args.output/filename).read_bytes()).hexdigest(),
                     "observed_values_sha256": proof["observed_values_sha256"]})
        print(symbol + ": all four raw-source contexts verified; decisions=" + str(len(features)), flush=True)
    core = {"schema_version": "nexus.composite-higher-timeframe-archive-result.v1",
            "execution_source_sha": args.source_sha, "request_digest": identity,
            "request": request, "rows": rows, "decision": "PASS_FEATURE_ONLY_QA",
            "feature_reconstruction_performed": True, "already_inspected_history": True,
            "signal_generation_performed": False, "financial_replay_performed": False,
            "frozen_strategy_execution_performed": False, "economic_qualification": False,
            "paper_execution_authority": False, "live_trading_authority": False}
    result = {**core, "result_digest": audit.digest(core)}
    (args.output / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print("result_digest=" + result["result_digest"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
