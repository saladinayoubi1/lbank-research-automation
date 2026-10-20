# Fixed MR40 Momentum30 October follow-up — 2026-10-21

Historical follow-up, not pristine OOS or prospective. October sources were previously used in other NEXUS studies. No tuning, no auto Demo, no orders.

Fresh October cohort: [2026-10-01,2026-10-20) UTC, 19 complete days, 114 appended 4h bars; fresh 10000 USDT account.
Continuous cohort: [2026-08-01,2026-10-20), 80 days, no monthly reset.
Original and unchanged momentum30 candidate, each under four fixed cost/latency profiles: 16 reported calculations.

October has two trades: +119.36417952189004 USDT normal and +18.674584803682592 stress. Original and filtered results are identical: no October entry was rejected. This does not add evidence of filter advantage.
Frozen candidate commit: 764d544af246769ffae0c6aca00d02c00fb34078
Code/data commit before score: 5fec4eea4937d86ea38f92af413c49f25539ae86
Protocol: 9372f82aa690232f42e7bc026799078e5f28e55d
Result digest: 3209320f841a694f7711a365e93a0fd1e6777f31b1dd250c0c44f3ab630ca7ac
Extension digest: 17f3101579ebd301cda074174ed4154e772d15d6b2ef2e17513d73b1dc31798c

Python 3.11+ standard library only. Extract to a fresh directory and run:

    python verify_replay.py

This checks every inventory file, runs 13 new boundary/source tests, replays all 16 calculations in a temporary directory, compares semantic results and six CSV files byte-for-byte. Timestamp, worker hostname and derived digest may differ. Network/source re-ingestion is not required.

frozen/ preserves the previous full 21-file candidate package, including all original inputs, modules, result ledgers and curves.
source_manifest.json records official HTTPS headers, sizes, MD5/ETag equality, SHA256 and cache reuse for all 19 gzip sources.
october_input_extension.json contains the 114 observed bars and complete per-day raw audits.
recorded_results/ contains every original/candidate follow-up ledger, full equity curve and admission decision.
The original raw gzips remain in the research cache; they are not bundled.
Read MR40_MOMENTUM30_OCTOBER_20261021_FA.md for complete results and limits.
