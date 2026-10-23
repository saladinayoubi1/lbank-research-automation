"""Read-only temporal parity with an existing frozen MR40 baseline ledger.

Not a signal backtest: input episode/exit signal indices are read from PRIOR
ledger decisions. Proves only scheduling and no spurious entry/exit intents.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path

from research.nexus_mr40_entry_event_contract_v1 import (
    EntryEventCoordinator, Position,
)

LEDGER_SHA = "2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"
ROWS_SHA = "a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
KEY = {"venue": "Bybit", "capital": 10000, "profile": "normal", "case": "baseline"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for block in iter(lambda: fp.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def frozen_rows(folder):
    a = json.loads((folder / "bybit_prepared_inputs.json").read_bytes())["rows"]
    b = json.loads((folder / "bybit_october_input_extension.json").read_bytes())["rows"]
    rows = a + b
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if hashlib.sha256(canonical).hexdigest() != ROWS_SHA:
        raise ValueError("frozen_candle_digest_mismatch")
    return rows


def frozen_ledger(path):
    if sha256_file(path) != LEDGER_SHA:
        raise ValueError("frozen_baseline_ledger_sha256_mismatch")
    out = {}
    with gzip.open(path, "rt", encoding="utf-8") as fp:
        for line in fp:
            item = json.loads(line)
            k = item["key"]
            if all(k.get(a) == b for a, b in KEY.items()) and k["window"] in ("train", "evaluation"):
                if k["window"] in out:
                    raise ValueError("duplicate_baseline_window")
                out[k["window"]] = item
    if set(out) != {"train", "evaluation"}:
        raise ValueError("missing_baseline_window")
    return out


def replay(rows, item, window):
    positions = item["positions"]
    decisions = item["decisions"]
    entry_signals = set()
    first_signals = set()
    for decision in decisions:
        if not decision["allowed"]:
            raise ValueError("unexpected_baseline_veto")
        first = decision["signal_index"]
        last = decision["episode_last_index"]
        if first > last or first in first_signals:
            raise ValueError("bad_episode_indices")
        first_signals.add(first)
        entry_signals.update(range(first, last + 1))
    entries = {}
    exits = {}
    exit_signals = set()
    for item in positions:
        ent, ex = item["entry"], item["exit"]
        i, j = ent["bar_index"], ex["bar_index"]
        if ent["reason"] != "episode_entry" or ex["reason"] != "natural_exit":
            raise ValueError("baseline_has_other_exit_semantics")
        if i != ent["signal_index"] + 1 or j != ex["signal_index"] + 1 or i >= j:
            raise ValueError("non_next_open_ledger_event")
        if i in entries or j in exits:
            raise ValueError("duplicate_position_timestamp")
        if ent["fill_ms"] != rows[i][0] or ex["fill_ms"] != rows[j][0]:
            raise ValueError("ledger_and_frozen_OHLC_bar_time_mismatch")
        entries[i] = item
        exits[j] = item
        exit_signals.add(ex["signal_index"])
    if len(positions) != len(first_signals):
        raise ValueError("missing_episode_to_position_baseline_parity")

    def p_at(index, at_open):
        for pos in positions:
            ei = pos["entry"]["bar_index"]
            xo = pos["exit"]["bar_index"]
            if (ei < index <= xo) if at_open else (ei <= index < xo):
                return Position(D(pos["entry"]["price"]), D(pos["entry"]["quantity"]))
        return None

    c = EntryEventCoordinator(arm2_gross_entry_stop=False)
    got_entries, got_exits = [], []
    start = min(first_signals) - 1
    end = max(exits)
    if start < 0:
        raise ValueError("missing_pre_signal_bar")
    for i in range(start, end + 1):
        if i > start and rows[i][0] - rows[i - 1][0] != 14_400_000:
            raise ValueError("missing_or_irregular_4h_bar_in_selected_window")
        stamp, op, hi, lo, cl = rows[i][:5]
        event = c.open(i, D(str(op)), position=p_at(i, True))
        if event.kind == "DATA_BLOCK":
            raise ValueError("coordinator_blocked_verified_baseline")
        if event.kind == "ENTRY_NEXT_OPEN":
            got_entries.append(i)
        elif event.kind == "NATURAL_EXIT_NEXT_OPEN":
            got_exits.append(i)
        elif event.kind not in ("HOLD", "FLAT", "AWAIT_ENTRY_ACK", "AWAIT_EXIT_ACK"):
            raise ValueError("unexpected_baseline_event_" + event.kind)
        result = c.close(
            i, D(str(cl)), i in entry_signals, i in exit_signals,
            position=p_at(i, False), high_price=D(str(hi)),
            low_price=D(str(lo)), confirmed=True, source_ok=True,
            quality_allowed=True,
        )
        if result.kind != "CLOSE_CONFIRMED":
            raise ValueError("invalid_closed_baseline_ohlc")
    if set(got_entries) != set(entries):
        raise ValueError("entry_intent_parity_failed")
    if set(got_exits) != set(exits):
        raise ValueError("natural_exit_intent_parity_failed")
    return {
        "window": window, "frozen_expected_entries": len(entries),
        "offline_entry_intents_matched": len(got_entries),
        "frozen_expected_natural_exits": len(exits),
        "offline_natural_exit_intents_matched": len(got_exits),
        "no_unexpected_intent": True,
        "from_prior_outcomes": True,
        "not_strategy_or_equity_parity": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    ns = parser.parse_args()
    if ns.output.exists():
        raise ValueError("refuse_overwrite")
    rows = frozen_rows(ns.inputs)
    reference = frozen_ledger(ns.ledger)
    results = [replay(rows, reference[k], k) for k in ("train", "evaluation")]
    report = {
        "schema": "mr40.entry-event-ledger-timing-parity.v1",
        "proof_scope": "Only timing and count of entry/exit intents from PREVIOUSLY FROZEN episode/exit indices; not indicator, execution, pnl or DD parity.",
        "historically_seen": True, "paper_changed": False,
        "real_orders": False, "private_api": False,
        "no_promote": True, "no_merge": True,
        "source_sha256": {"ledger": LEDGER_SHA, "rows": ROWS_SHA},
        "results": results,
    }
    report["digest"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    ns.output.parent.mkdir(parents=True, exist_ok=True)
    ns.output.write_text(json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
