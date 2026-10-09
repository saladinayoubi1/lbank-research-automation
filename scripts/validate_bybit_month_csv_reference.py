"""Independent bounded CSV/Decimal OHLCV QA for a source-bound symbol-month."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import itertools
import json
import sys
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def verify(output_root: Path, archive: Path) -> dict:
    import pandas as pd
    manifest = json.loads((output_root / "_source_manifest.json").read_text())
    if len(manifest) != 1:
        raise ValueError("one source-bound symbol-month required")
    source = manifest[0]
    sha = hashlib.sha256()
    with archive.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(block)
    if sha.hexdigest() != source["sha256"]:
        raise ValueError("official source archive digest mismatch")
    buckets = {900: {}, 3600: {}, 14400: {}}
    rows = 0
    previous = None
    with localcontext() as ctx:
        ctx.prec = 50
        with gzip.open(archive, "rt", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            first = next(reader)
            aliases = {"timestamp": "time", "time": "time", "trdtime": "time",
                       "price": "price", "execprice": "price", "size": "size",
                       "volume": "size", "qty": "size", "quantity": "size", "side": "side"}
            names = [aliases.get("".join(c for c in x.lower() if c.isalnum())) for x in first]
            named = all(x in names for x in ("time", "price", "size", "side"))
            positions = ({x: names.index(x) for x in names if x} if named
                         else {"time": 1, "price": 2, "size": 3, "side": 4})
            trades = reader if named else itertools.chain([first], reader)
            for row in trades:
                if not row:
                    continue
                at = Decimal(row[positions["time"]])
                seconds = at / 1000 if abs(at) >= Decimal("1e11") else at
                price, size = Decimal(row[positions["price"]]), Decimal(row[positions["size"]])
                if (not seconds.is_finite() or not price.is_finite() or not size.is_finite()
                        or price <= 0 or size < 0 or row[positions["side"]].strip().title() not in ("Buy", "Sell")):
                    raise ValueError("invalid independent source row")
                if previous is not None and seconds < previous:
                    raise ValueError("independent source order is not chronological")
                previous = seconds
                rows += 1
                for step, values in buckets.items():
                    stamp = int(seconds // step) * step
                    if stamp not in values:
                        values[stamp] = [price, price, price, price, size]
                    else:
                        candle = values[stamp]
                        candle[1] = max(candle[1], price)
                        candle[2] = min(candle[2], price)
                        candle[3] = price
                        candle[4] += size
        if rows != source["valid_trade_rows"] or rows != source["source_rows"]:
            raise ValueError("independent raw source row count mismatch")
        checks, maximum = 0, Decimal(0)
        for timeframe, step in (("minute15", 900), ("hour1", 3600), ("hour4", 14400)):
            paths = list((output_root / "bybit_market").glob(f"*/{timeframe}.parquet"))
            if len(paths) != 1:
                raise ValueError("missing or duplicate output timeframe")
            frame = pd.read_parquet(paths[0])
            if len(frame) != len(buckets[step]):
                raise ValueError("independent candle count mismatch")
            seen = set()
            for candle in frame.itertuples(index=False):
                stamp = int(pd.Timestamp(candle.timestamp).timestamp())
                if stamp not in buckets[step] or stamp in seen:
                    raise ValueError("independent UTC bucket identity mismatch")
                seen.add(stamp)
                for name, expected in zip(("open", "high", "low", "close", "volume"), buckets[step][stamp]):
                    actual = Decimal(str(getattr(candle, name)))
                    error = abs(actual - expected)
                    tolerance = Decimal("1e-10") + abs(expected) * Decimal("1e-11")
                    if not actual.is_finite() or error > tolerance:
                        raise ValueError(f"independent OHLCV mismatch: {timeframe} {stamp} {name}")
                    maximum = max(maximum, error)
                    checks += 1
    return {"schema": "nexus.independent-bybit-month-csv-qa.v1", "passed": True,
            "source_archive_sha256": sha.hexdigest(), "source_rows": rows,
            "numeric_comparisons": checks, "maximum_absolute_error": str(maximum),
            "output_parquet_sha256": {
                str(p.relative_to(output_root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((output_root / "bybit_market").glob("*/*.parquet"))},
            "parser": "stdlib_csv_gzip_decimal50", "timestamp_ties": "original_source_row_order",
            "live_trading_authority": False, "automatic_strategy_promotion": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads((args.output_root / "_source_manifest.json").read_text())[0]
    result = verify(args.output_root, Path(source["path"]))
    args.receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
