"""Finite-grid, lagged shock proxies for Research; not a jump significance test."""

import numpy as np
import pandas as pd


WINDOW = 96


def build_lagged_jump_features(close: pd.Series) -> pd.DataFrame:
    """Context ends at i-1; shock normalization ends before that event at i-2.

    Bipower-inspired variation is a proxy on 15m closes. It cannot establish
    statistically significant discontinuities or authenticated trade flow.
    """
    prices = pd.to_numeric(close, errors="raise").astype(float)
    if not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any():
        raise ValueError("jump feature prices must be finite and positive")
    returns = np.log(prices).diff()
    adjacent = returns.abs() * returns.shift(1).abs()
    # Exclude r[i-1] from the continuous-volatility baseline of that same shock.
    sigma = np.sqrt((np.pi / 2.0) * adjacent.shift(2).rolling(WINDOW, min_periods=WINDOW).mean())
    lagged = returns.shift(1)
    realized = lagged.pow(2).rolling(WINDOW, min_periods=WINDOW).sum()
    bipower = (
        (np.pi / 2.0)
        * (lagged.abs() * lagged.shift(1).abs()).rolling(WINDOW - 1, min_periods=WINDOW - 1).sum()
        * WINDOW / (WINDOW - 1)
    )
    return pd.DataFrame({
        "lagged_bipower_sigma_96": sigma,
        "lagged_standardized_shock_96": lagged / sigma.replace(0.0, np.nan),
        "lagged_jump_proxy_share_96": (realized - bipower).clip(lower=0.0) / realized.replace(0.0, np.nan),
        "previous_close": prices.shift(1),
    }, index=close.index).replace([np.inf, -np.inf], np.nan)
