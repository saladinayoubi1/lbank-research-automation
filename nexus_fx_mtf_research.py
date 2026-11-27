"""Research-only synchronized closed-bar inputs, not a trading signal."""
from dataclasses import dataclass
from nexus_fx_quote_research import QuoteWindow, _require, _integer
from nexus_fx_bars_research import BarGrid, build_closed_bars, contiguous_suffix


@dataclass(frozen=True)
class FrameRequest:
    name: str
    grid: BarGrid
    count: int

    def __post_init__(self):
        _require(type(self.name) is str and bool(self.name.strip()) and
                 self.name == self.name.strip(), "explicit frame name required")
        _require(type(self.grid) is BarGrid, "explicit grid required")
        _require(type(self.count) is int and 0 < self.count <= 100000,
                 "invalid frame lookback")


@dataclass(frozen=True)
class FrameSlice:
    request: FrameRequest
    bars: tuple


@dataclass(frozen=True)
class MultiFrameSnapshot:
    decision_ms: int
    observed_through_ms: int
    source_id: str
    source_revision: str
    instrument: object
    prefix_sha256: str
    frames: tuple
    research_only: bool = True


def build_snapshot(window, requests, decision_ms):
    """Build all requested contiguous lookbacks from one observed quote prefix.

    No partial frame result, forward fill, clock-only close, or future data.
    An incomplete/gapped requested frame rejects the whole snapshot.
    Explicit grids/bases are caller inputs, not course or broker conventions.
    """
    _require(type(window) is QuoteWindow, "bound quote window required")
    _integer(decision_ms, "decision time")
    _require(type(requests) is tuple and 0 < len(requests) <= 16 and
             all(type(r) is FrameRequest for r in requests),
             "explicit immutable frame requests required")
    _require(len({r.name for r in requests}) == len(requests), "duplicate frame name")
    frames = []
    provenance = None
    for request in requests:
        series = build_closed_bars(window, request.grid, decision_ms)
        identity = (series.observed_through_ms, series.source_id,
                    series.source_revision, series.instrument, series.prefix_sha256)
        if provenance is None:
            provenance = identity
        else:
            _require(identity == provenance, "inconsistent causal prefix")
        bars = contiguous_suffix(series, request.count)
        _require(all(b.end_ms <= b.available_ms <= decision_ms for b in bars),
                 "unavailable frame bar")
        frames.append(FrameSlice(request, bars))
    return MultiFrameSnapshot(decision_ms, *provenance, tuple(frames))
