"""Forward-data eligibility gate for the one preregistered V13 experiment.

The optional public-time probe retrieves ONLY /v5/market/time. It does NOT
retrieve OHLCV, use API keys, write files, submit orders, or schedule a task.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import json

from nexus_v13_compression_detector import FUTURE_START, FUTURE_END_EXCLUSIVE

PUBLIC_TIME_URL="https://api.bybit.com/v5/market/time"
FIRST_ELIGIBLE_CLOSE=FUTURE_START+__import__("pandas").Timedelta(minutes=15)
RESEARCH_ONLY=True
LIVE_ENABLED=False
FETCHES_MARKET_BARS=False
ORDERS_ENABLED=False


def eligibility(server_now:datetime)->dict:
    """Return embargo/capture eligibility from UTC server time, never device guess."""
    if server_now.tzinfo is None:
        raise ValueError("Server UTC time must be timezone aware")
    from pandas import Timestamp
    at=Timestamp(server_now).tz_convert("UTC")
    first=FIRST_ELIGIBLE_CLOSE
    return {
        "schema":"nexus.v13-prospective-readiness/v1",
        "checked_server_time_utc":at.isoformat(),
        "first_eligible_closed_15m_utc":first.isoformat(),
        "window_end_exclusive_utc":FUTURE_END_EXCLUSIVE.isoformat(),
        "status":("BEFORE_PROSPECTIVE_WINDOW" if at<first else
                  "PROSPECTIVE_WINDOW_OPEN" if at<FUTURE_END_EXCLUSIVE else
                  "PROSPECTIVE_WINDOW_ENDED"),
        "eligible_to_capture_only_closed_future_bars":
            bool(first<=at<FUTURE_END_EXCLUSIVE),
        "market_bars_retrieved":0,
        "forward_bars_scored":0,
        "market_backtests":0,
        "paper_orders":0,
        "live_orders":0,
        "research_only":True,
    }


def fetch_public_server_time(timeout_seconds:float=8)->datetime:
    """Exactly one unauthenticated Bybit server-time GET. Never requests candles."""
    req=Request(PUBLIC_TIME_URL,headers={"User-Agent":"NEXUS-v13-forward-research-readonly"})
    with urlopen(req,timeout=timeout_seconds) as response:
        body=response.read(4096)
    data=json.loads(body.decode("utf-8"))
    if data.get("retCode")!=0:
        raise RuntimeError("Public Bybit time endpoint refused the request")
    sec=data.get("result",{}).get("timeSecond")
    if sec is None:raise ValueError("Bybit time response missing seconds")
    return datetime.fromtimestamp(int(sec),tz=timezone.utc)


if __name__=="__main__":
    import argparse
    a=argparse.ArgumentParser()
    a.add_argument("--public-time-check",action="store_true")
    args=a.parse_args()
    if not args.public_time_check:
        raise SystemExit("No action. Pass --public-time-check for read-only time probe.")
    print(json.dumps(eligibility(fetch_public_server_time()),sort_keys=True))
