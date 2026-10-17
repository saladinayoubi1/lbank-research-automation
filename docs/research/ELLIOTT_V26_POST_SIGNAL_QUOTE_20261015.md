# Elliott V26 — post-signal quote admission QA

**2026-10-15 | Research-only.** This is a prospective-only *quote diagnostic*, not a new backtest, a broker fill or a profitable strategy result.

## Completed

The separate `nexus_elliott_post_signal_quote_v26.py` does **not** read future closed OHLC or modify frozen V17/V24/V25 outcomes. It requires a valid predeclared closed-breakout observation, source-receipt and signal-commit times, and a strictly defined Bybit Spot quote envelope: symbol, venue, category, best bid, best ask, market timestamp and client receipt timestamp.

The causal sequence is: closed 15m decision → source received → signal committed → market quote timestamp → quote received → review. The quote must be inside the **next** 15m candle, independently of future OHLC. A fixed, not history-tuned **two-second delivery-age limit** rejects stale book quotes. Crossed/locked/nonpositive bids and asks, incorrect symbols or non-Bybit Spot markets, missing fields and injected future bars or purported fills are rejected.

For a bullish breakout, the **best bid** must remain strictly above the certified fifth-pivot high. A spread where only the ask is higher is rejected. After this screen, the module reports quote spread and a **conditional, not observed** 2R structural-risk and cost calculation for the two original frozen fee/slippage profiles. Rejected quotes cannot emit a projected target reward. Quote data and event certification are **caller supplied, not provider-attested**; best ask is **not** an actual trade fill and no order-book size/queue execution is proven.

All outputs explicitly keep `observed_trade_pnl=null`, `actual_position_filled=false`, `paper_eligible=false`, `promotable_to_demo=false`, `live_enabled=false`, and `orders_placed=0`. Source identification and full recursive 5-3-5-3-5 Elliott proof remain open; no parameter has been tuned on historical winners.

## Native QA

On research Laptop2 `DESKTOP-F4SA4VL`:
- V26 tests: **27/27 PASS**, including late and stale quotes, invalid chronology, spoofed venues, false ask-only breakouts, future input injection, economic cost ordering, and no invented PNL.
- Entire Elliott-focused suite: **258/258 PASS**, run with `python -m unittest discover -s tests -p test_nexus_elliott_*.py -q` (6.188 seconds).
- GitHub exact HEAD cross-platform CI status is tracked separately; native tests are not represented as full CI certification.

## Next scientific gate

Collect *authenticated* future Bybit source/quote receipts; preregister a separate **post-signal actual-fill** contract including bid/ask depth, queue/market-impact assumptions and exit evidence. Test on genuinely unseen events without retroactively rewriting V17 returns. Preserve Laptop1 demo, original archives, 500 USDT paper reference and paused VPS.
