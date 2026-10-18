"""Read-only projection of the unchanged, rejected V119 completed study.

No engine import, signal generation, worker dispatch or qualification authority.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from nexus_elliott_v119_accounting_qa import (
    ENGINE_SHA256, LEDGER_SHA256, PARTS, PROFILES, RESULT_DIGEST, SOURCE_SHAS, digest,
)

REPORT_ID = "ELLIOTT-V119"
WORKSPACE_ID = "research:elliott_wave2_support_v119"
LEDGER_FILE = "elliott-v119-completed-study.json"
QA_FILE = "elliott-v119-fixed-path-accounting-qa.json"
QA_DIGEST = "4b3f45e619c1e3814a9b60400e58127673af3ffb6b69a30589bbeda1c967dd0a"
ENTRY_QA_FILE = "elliott-v119-entry-witness-qa.json"
ENTRY_QA_DIGEST = "9770c358544cfb53430306bba92e48816c4f2380b2a3ab208225e8ea1f7ce6ae"
ENTRY_CHECKER_SHA256 = "22d8b83982ee5248628a009209e84cd8039207ad8438fed8e43794b520d6c2cf"
SOURCE_COMMIT = "1b8066939d3790cb3dd558946e5f19b25a96d646"
DISPOSITION = "HISTORICAL_NEGATIVE_DO_NOT_RETUNE"
EVIDENCE_URL = (
    "https://github.com/saladinayoubi1/lbank-research-automation/blob/" + SOURCE_COMMIT
    + "/docs/research/ELLIOTT_V119_BYBIT_WAVE2_RETEST_PHYSICAL_REJECTION_20261018.md"
)


def workspace_entry():
    return {
        "id": WORKSPACE_ID, "name": "Elliott V119 · Wave2 support retest",
        "mechanism": "causal_wave2_support_retest", "kind": "frozen_research_system",
        "required_data": ["closed_ohlcv"], "symbols": ["BTCUSDT", "ETHUSDT"],
        "timeframes": ["15m"], "reference_capital_usdt": 500,
        "execution": "historically_rejected_read_only", "report_id": REPORT_ID,
        "disposition": DISPOSITION, "paper_admission": False, "live_enabled": False,
        "hypothesis": "بازآزمایی حمایت موج ۲ پس از تأیید پیوت، بازپس‌گیری صعودی و ورود در بازشدن کندل بعد؛ یک الگوی جزئی، بدون شمارش کامل الیوت.",
        "invalidation": "آزمون تاریخی ثابت در هر سه بازه و هر دو سناریوی هزینه منفی است؛ پژوهش رد شده و تنظیم مجدد روی همین داده‌ها انجام نمی‌شود.",
    }


def entry_prefix_qa(root, load_json, ledger):
    proof = load_json(root / ENTRY_QA_FILE)
    if (proof.get("entry_witness_qa_digest") != ENTRY_QA_DIGEST
            or digest({k: v for k, v in proof.items() if k != "entry_witness_qa_digest"}) != ENTRY_QA_DIGEST):
        raise ValueError("V119 entry-prefix QA digest mismatch")
    if (proof.get("schema") != "nexus.elliott-v119-recorded-entry-prefix-witness-qa.v1"
            or proof.get("audit_completed") is not True
            or proof.get("fixed_recorded_entry_prefixes_checked") is not True
            or proof.get("source_shas") != SOURCE_SHAS
            or proof.get("ledger_raw_sha256") != LEDGER_SHA256
            or proof.get("result_digest") != RESULT_DIGEST
            or proof.get("engine_raw_sha256") != ENGINE_SHA256
            or proof.get("entry_checker_raw_sha256") != ENTRY_CHECKER_SHA256
            or proof.get("recorded_unique_entries_checked") != 77
            or proof.get("costed_ledger_rows_represented") != 154):
        raise ValueError("V119 entry-prefix source/coverage mismatch")
    if (any(proof.get(k) is not False for k in (
        "all_source_signal_universe_regenerated", "new_entry_selection_performed",
        "historical_backtest_reexecuted", "economic_result_recomputed",
        "original_signal_event_identity_verified", "signal_to_entry_causality_independently_verified",
        "full_elliott_wave_count_verified", "independent_future_holdout",
        "paper_eligible", "automatic_demo_promotion", "live_enabled",
    )) or proof.get("orders") != 0 or proof.get("disposition") != DISPOSITION
            or proof.get("evidence_kind") != "retrospectively_reconstructed_closed_prefix_compatibility"):
        raise ValueError("V119 entry-prefix evidence scope/authority mismatch")
    expected = {(part, trade["symbol"], trade["entry_index"], trade["exit_index"])
                for part in PARTS for trade in ledger["results"][part]["profiles"]["conservative"]["trades"]}
    entries = proof.get("entries")
    if not isinstance(entries, list) or len(entries) != 77:
        raise ValueError("V119 entry-prefix rows incomplete")
    actual = {(e["part"], e["symbol"], e["entry_index"], e["exit_index"]) for e in entries}
    if actual != expected or len(actual) != 77:
        raise ValueError("V119 entry-prefix ledger correspondence mismatch")
    counts = Counter()
    for entry in entries:
        witnesses = entry["witnesses"]
        status = "incompatible" if not witnesses else "unique_compatible_witness" if len(witnesses) == 1 else "multiple_compatible_witnesses"
        if entry["compatible_witness_count"] != len(witnesses) or entry["status"] != status:
            raise ValueError("V119 entry-prefix ambiguity coverage mismatch")
        counts[status] += 1
        for w in witnesses:
            if (digest({k: v for k, v in w.items() if k != "reconstructed_witness_sha256"}) != w["reconstructed_witness_sha256"]
                    or not 0 <= w["pivot_w0_center"] < w["pivot_w1_center"] < w["pivot_w2_center"]
                    or w["w2_known_after_closed_index"] != w["pivot_w2_center"] + 3
                    or not w["w2_known_after_closed_index"] < w["retest_completed_index"] < w["reclaim_completed_index"]
                    or w["retest_completed_index"] != entry["entry_index"] - 2
                    or w["reclaim_completed_index"] != w["prefix_last_index"]
                    or w["entry_index"] != entry["entry_index"]
                    or w["reclaim_completed_index"] != entry["entry_index"] - 1):
                raise ValueError("V119 entry-prefix chronology/digest mismatch")
    if proof["counts"] != dict(counts) or proof["all_recorded_entries_compatible"] is not (counts["incompatible"] == 0):
        raise ValueError("V119 entry-prefix summary mismatch")
    return proof


def completed_study(root: Path, load_json):
    ledger = load_json(root / LEDGER_FILE)
    qa = load_json(root / QA_FILE)
    core = {k: v for k, v in ledger.items() if k != "result_digest"}
    if (ledger.get("result_digest") != RESULT_DIGEST or digest(core) != RESULT_DIGEST
            or hashlib.sha256((root / LEDGER_FILE).read_bytes()).hexdigest() != LEDGER_SHA256):
        raise ValueError("V119 frozen ledger digest mismatch")
    if qa.get("qa_digest") != QA_DIGEST or digest({k: v for k, v in qa.items() if k != "qa_digest"}) != QA_DIGEST:
        raise ValueError("V119 independent accounting QA digest mismatch")
    if (ledger.get("source_shas") != SOURCE_SHAS or qa.get("source_shas") != SOURCE_SHAS
            or qa.get("result_digest") != RESULT_DIGEST or qa.get("ledger_raw_sha256") != LEDGER_SHA256
            or qa.get("engine_raw_sha256") != ENGINE_SHA256 or qa.get("passed") is not True
            or qa.get("fixed_recorded_trade_paths_checked") is not True
            or qa.get("recorded_trade_rows_checked") != 154
            or qa.get("partition_cost_cells_checked") != 6
            or qa.get("source_bars_per_asset_checked") != 128544
            or qa.get("monthly_rows_checked") != 74):
        raise ValueError("V119 accounting QA coverage/source mismatch")
    for value in (ledger, qa):
        if any(value.get(k) is not False for k in (
            "paper_eligible", "live_enabled", "automatic_demo_promotion", "independent_future_holdout"
        )) or value.get("orders") != 0:
            raise ValueError("V119 research authority mismatch")
    if (qa.get("backtest_reexecuted") is not False or qa.get("signal_generation_replayed") is not False
            or qa.get("full_elliott_wave_count_verified") is not False
            or qa.get("signal_to_entry_causality_independently_verified") is not False
            or ledger.get("historical_test_already_inspected") is not True
            or ledger.get("not_full_elliott_wave_certification") is not True):
        raise ValueError("V119 evidence scope mismatch")
    cells = {(r["part"], r["profile"]): r for r in qa["rows"]}
    if len(cells) != 6:
        raise ValueError("V119 accounting cells incomplete")
    rows = []
    for part in PARTS:
        partition = ledger["results"][part]
        for profile in PROFILES:
            recorded = partition["profiles"][profile]
            accounting = cells[part, profile]
            if (recorded["initial_shared_cash_usdt"] != 500 or recorded["net_pnl_usdt"] >= 0
                    or recorded["round_trips"] != accounting["round_trips"]
                    or recorded["net_pnl_usdt"] != accounting["net_pnl_usdt"]):
                raise ValueError("V119 original negative outcome/capital changed")
            rows.append({**accounting, "symbol": "BTCUSDT + ETHUSDT (shared cash)",
                         "first_decision_utc": partition["start_utc"],
                         "last_decision_utc": partition["end_utc"],
                         "closed_round_trips": recorded["round_trips"],
                         "max_drawdown_pct": None, "monthly": recorded["monthly"],
                         "source_causal_signals": partition["source_causal_signals"],
                         "denied_after_signal": recorded["denied_after_signal"]})
    rules = {
        "context": "Bybit Spot؛ BTC و ETH؛ کندل‌های بستهٔ ۱۵ دقیقه؛ سه پیوت متوالی کف، سقف، کف با تأیید سه کندل بعد؛ بدون بازنویسی پیوت قبلی.",
        "pattern": "دامنهٔ الگو حداکثر ۱۲۸ کندل؛ حرکت موج ۱ حداقل ۰٫۶٪؛ اصلاح موج ۲ بین ۰٫۳۸۲ و ۰٫۸۸۶ و بالاتر از کف موج صفر.",
        "entry": "در ۴۸ کندل پس از تأیید موج ۲، حفظ کف واقعی، بازآزمایی نزدیک حمایت و سپس یک کندل صعودی مجزا بالای سقف بازآزمایی؛ ورود در بازشدن کندل بعد.",
        "exit": "حد ضرر ۰٫۲٪ پایین‌تر از کف موج ۲ و بالاتر از کف موج صفر؛ هدف کوچک‌ترِ سقف موج ۱ و ۲R؛ حداقل نسبت سود به زیان ۱٫۵. در برخورد همزمان، ضرر مقدم است؛ شکاف نزولی با قیمت بازشدن خروج می‌شود.",
        "timeout": "خروج در بازشدن کندل ۹۶ پس از ورود یا آخرین کندل بازه؛ این خروجِ از پیش مقرر بر برخوردهای درون همان کندل مقدم است.",
        "sizing": "حساب مشترک ۵۰۰ USDT، فقط یک موقعیت Spot خرید؛ حداکثر ارزش موقعیت ۲۵۰ و ریسک اسمی بدون شکاف ۲٫۵ USDT با احتساب هزینه؛ مقدار تا ۸ رقم اعشار رو به پایین.",
        "no_trade": "شکستن کف موج ۲ پیش از ورود، بازشدن نامعتبر، نسبت سود به زیان ناکافی، هدف غیرقابل‌دسترس پس از لغزش، اشغال حساب یا کمبود موجودی باعث عدم ورود می‌شود.",
        "costs": "محافظه‌کارانه: کارمزد ۱۰ و لغزش ۵ واحد پایه در هر سمت؛ سخت: کارمزد ۲۵ و لغزش ۱۵ واحد پایه در هر سمت.",
    }
    entry_proof = entry_prefix_qa(root, load_json, ledger)
    return {
        "id": REPORT_ID, "status": "verified", "provider": "Bybit",
        "reference_capital_usdt": 500, "report_sha256": RESULT_DIGEST,
        "source_sha": SOURCE_COMMIT, "engine_raw_sha256": ENGINE_SHA256,
        "ledger_raw_sha256": LEDGER_SHA256, "accounting_qa_digest": QA_DIGEST,
        "entry_prefix_qa_digest": ENTRY_QA_DIGEST,
        "original_verdict": DISPOSITION, "evidence_kind": "fixed_recorded_path_accounting_qa",
        "evidence_url": EVIDENCE_URL, "run_url": None, "verified_data": None,
        "execution_eligible": False,
        "report": {"schema": "nexus.elliott-v119-completed-study-view.v1", "rows": rows,
                   "system_rules": rules, "frozen_config": ledger["input_frozen_config"],
                   "full_elliott_wave_count_verified": False, "independent_future_holdout": False,
                   "signal_to_entry_causality_independently_verified": False,
                   "entry_prefix_qa": entry_proof,
                   "backtest_reexecuted": False, "cash_resets_per_partition_and_profile": True,
                   "unique_recorded_trade_paths": 77, "recorded_costed_trade_rows": 154,
                   "paper_eligible": False, "live_enabled": False},
    }
