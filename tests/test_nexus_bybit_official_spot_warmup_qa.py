import csv
from datetime import datetime, timezone
from decimal import Decimal
import gzip

import pytest

from scripts.nexus_bybit_official_spot_warmup_qa import decimal_day


def write_day(path, change=None):
    start = int(datetime(2026, 10, 18, tzinfo=timezone.utc).timestamp() * 1000)
    rows = []
    for i in range(6):
        rows.extend([[2*i+1, start+i*14_400_000, "100.1", "0.1", "buy", "0"],
                     [2*i+2, start+i*14_400_000+1, "99.9", "0.2", "sell", "1"]])
    if change:
        change(rows)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "timestamp", "price", "volume", "side", "rpi"])
        writer.writerows(rows)


def test_independent_exact_decimal_volume_and_utc_bucket_edges(tmp_path):
    p = tmp_path / "ticks.csv.gz"
    write_day(p)
    bars, count = decimal_day(p, "2026-10-18")
    assert count == 12 and len(bars) == 6
    for bar in bars:
        assert bar["open"] == bar["high"] == Decimal("100.1")
        assert bar["close"] == bar["low"] == Decimal("99.9")
        assert bar["volume"] == Decimal("0.3") and bar["trades"] == 2


@pytest.mark.parametrize("mutation", [
    lambda r: r[1].__setitem__(0, r[0][0]),
    lambda r: r[0].__setitem__(1, r[0][1]-1),
    lambda r: r[0].__setitem__(2, "NaN"),
    lambda r: r[0].__setitem__(3, "-0.1"),
    lambda r: r[0].__setitem__(4, "unknown"),
])
def test_independent_invalid_ticks_rejected(tmp_path, mutation):
    p = tmp_path / "ticks.csv.gz"
    write_day(p, mutation)
    with pytest.raises((AssertionError, ValueError, ArithmeticError)):
        decimal_day(p, "2026-10-18")


def test_independent_missing_bucket_is_not_imputed(tmp_path):
    p = tmp_path / "ticks.csv.gz"
    write_day(p, lambda r: r.__delitem__(slice(-2, None)))
    with pytest.raises(AssertionError):
        decimal_day(p, "2026-10-18")
