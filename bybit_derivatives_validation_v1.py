from __future__ import annotations

import argparse
import dataclasses
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import pandas as pd

from bybit_derivatives_core_v1 import (
    Client,
    InstrumentSpec,
    Position,
    RiskTier,
    ValidationError,
    adverse_fill_price,
    apply_trade,
    choose_risk_tier,
    expected_funding_count,
    fetch_funding,
    fetch_instrument,
    fetch_klines,
    fetch_risk_tiers,
    funding_cashflow,
    margin_requirements,
    milliseconds,
    minute_vwap,
    normalized_target_quantity,
    unrealized,
)

BARS_PER_YEAR = 365.25 * 6


def frozen_weights(spot: dict[str, Any], frozen: dict[str, Any]) -> np.ndarray:
    import bybit_consensus_search_v5 as consensus
    import bybit_regime_search_v6 as regime

    signal = frozen['signal_contract']
    execution = frozen['execution_contract']
    long_vol = consensus.realized_vol(spot['close'], execution['volatility_lookback_days'])
    fast_vol = consensus.realized_vol(spot['close'], 14)
    components = []
    for component in frozen['ensemble_components']:
        params = {
            'lookbacks': signal['asset_momentum_lookbacks_days'],
            'long_vote': signal['long_vote_threshold'],
            'short_vote': signal['short_vote_threshold'],
            'ema_fast_days': signal['asset_ema_fast_days'],
            'ema_slow_days': signal['asset_ema_slow_days'],
            'deadband': signal['momentum_deadband'],
            'short_scale': component['short_scale'],
            'fast_reversal': signal['fast_reversal_limit'],
            'regime_fast_days': signal['regime_fast_days'],
            'regime_slow_days': signal['regime_slow_days'],
            'regime_threshold': component['regime_threshold'],
            'transition_scale': signal['transition_long_scale'],
            'vol_days': execution['volatility_lookback_days'],
            'target_vol': execution['target_volatility'],
            'rebalance_days': execution['rebalance_days'],
            'vol_ratio_trigger': execution['high_volatility_ratio_trigger'],
            'high_vol_scale': execution['high_volatility_scale'],
            'quantum': execution['weight_quantum'],
        }
        candidate = {'family': 'explicit_regime_consensus', 'params': params}
        state = regime.structural_signal(spot, candidate)
        components.append(consensus.construct_weights(state, long_vol, fast_vol, candidate))
    return np.median(np.stack(components, axis=2), axis=2)


def period_indices(timestamps: pd.Series, period: dict[str, str]) -> np.ndarray:
    start = pd.Timestamp(period['start'], tz='UTC')
    end = pd.Timestamp(period['end'], tz='UTC')
    result = np.flatnonzero(((timestamps >= start) & (timestamps < end)).to_numpy())
    if len(result) < 2:
        raise ValidationError(f'insufficient period rows: {period}')
    return result


def align_frames(
    timestamps: pd.Series,
    symbols: list[str],
    frames: dict[str, pd.DataFrame],
    prefix: str,
    columns: list[str],
) -> dict[str, np.ndarray]:
    target = pd.DatetimeIndex(timestamps)
    output: dict[str, np.ndarray] = {}
    for column in columns:
        values = np.column_stack([
            frames[symbol].set_index('timestamp').reindex(target)[column].to_numpy(float)
            for symbol in symbols
        ])
        if np.isnan(values).any():
            raise ValidationError(f'missing aligned {prefix}_{column}')
        output[f'{prefix}_{column}'] = values
    return output


def execution_window(client: Client, symbol: str, timestamp: pd.Timestamp, minutes: int) -> pd.DataFrame:
    start = int(timestamp.timestamp() * 1000)
    batch = client.get('/v5/market/kline', {
        'category': 'linear',
        'symbol': symbol,
        'interval': '1',
        'start': start,
        'end': start + minutes * 60_000 - 1,
        'limit': minutes,
    })['result'].get('list', [])
    items = sorted(batch, key=lambda x: int(x[0]))
    return pd.DataFrame({
        'timestamp': pd.to_datetime([int(x[0]) for x in items], unit='ms', utc=True),
        'volume': [float(x[5]) for x in items],
        'turnover': [float(x[6]) for x in items],
    })


def account_margin(
    positions: list[Position],
    marks: np.ndarray,
    tiers: list[list[RiskTier]],
    leverage: float,
    close_fee: float,
) -> tuple[float, float, float]:
    initial, maintenance, details = margin_requirements(
        positions, marks, tiers, leverage, close_fee
    )
    tier_utilization = max(
        (x['notional'] / x['tier_limit'] for x in details if x['tier_limit'] > 0.0),
        default=0.0,
    )
    return initial, maintenance, float(tier_utilization)


def backtest(
    market: dict[str, Any],
    weights: np.ndarray,
    period: dict[str, str],
    profile: dict[str, float],
    specs: list[InstrumentSpec],
    tiers: list[list[RiskTier]],
    funding: list[pd.DataFrame],
    client: Client,
    execution_cache: dict[tuple[str, int, int], pd.DataFrame],
) -> dict[str, Any]:
    source_rows = period_indices(market['timestamps'], period)
    selected = weights[source_rows]
    timestamps = market['timestamps'].iloc[source_rows].reset_index(drop=True)
    timestamp_ns = pd.DatetimeIndex(market['timestamps']).asi8
    wallet = float(profile['initial_cash'])
    positions = [Position() for _ in specs]
    fee_rate = float(profile['fee_bps']) / 10000.0
    fallback = float(profile['fallback_slippage_bps']) / 10000.0
    fills = np.zeros(len(specs), dtype=int)
    equity_rows: list[float] = []
    fees = funding_total = traded_notional = 0.0
    orders = execution_hits = margin_rejections = liquidations = 0
    max_margin = max_tier = max_participation = 0.0
    start = pd.Timestamp(period['start'], tz='UTC')
    end = pd.Timestamp(period['end'], tz='UTC')
    funding_rows = [x[(x.timestamp > start) & (x.timestamp < end)] for x in funding]
    actual_funding = sum(len(x) for x in funding_rows)
    expected_funding = sum(expected_funding_count(start, end, x.funding_interval_minutes) for x in specs)
    funding_cursor = [0 for _ in specs]
    previous = start

    for local_row, source_row in enumerate(source_rows):
        now = pd.Timestamp(timestamps.iloc[local_row])
        for asset, frame in enumerate(funding_rows):
            while funding_cursor[asset] < len(frame):
                event = frame.iloc[funding_cursor[asset]]
                event_time = pd.Timestamp(event['timestamp'])
                if event_time > now:
                    break
                if event_time > previous:
                    mark_row = max(0, int(np.searchsorted(timestamp_ns, event_time.value, side='left')) - 1)
                    cashflow = funding_cashflow(
                        positions[asset].quantity,
                        market['mark_close'][mark_row, asset],
                        float(event['funding_rate']),
                    )
                    wallet += cashflow
                    funding_total += cashflow
                funding_cursor[asset] += 1

        target_changed = local_row == 1 or (
            local_row > 1
            and not np.allclose(selected[local_row - 1], selected[local_row - 2], atol=1e-12, rtol=0.0)
        )
        if local_row > 0 and target_changed:
            marks = market['mark_open'][source_row]
            equity_at_open = wallet + sum(unrealized(x, marks[i]) for i, x in enumerate(positions))
            desired = [
                normalized_target_quantity(equity_at_open * selected[local_row - 1, i], marks[i], specs[i])
                for i in range(len(specs))
            ]
            for asset, spec in enumerate(specs):
                delta = desired[asset] - positions[asset].quantity
                if abs(delta) <= 1e-15:
                    continue
                orders += 1
                key = (spec.symbol, int(now.timestamp()), int(profile['execution_window_minutes']))
                if key not in execution_cache:
                    execution_cache[key] = execution_window(client, spec.symbol, now, key[2])
                minute_frame = execution_cache[key]
                vwap = minute_vwap(minute_frame)
                if vwap is None:
                    fill = market['trade_open'][source_row, asset] * (1.0 + math.copysign(fallback, delta))
                else:
                    execution_hits += 1
                    turnover = float(minute_frame['turnover'].sum())
                    fill, _ = adverse_fill_price(delta, vwap, abs(delta) * vwap, turnover, profile)
                    max_participation = max(max_participation, abs(delta) * vwap / max(turnover, 1.0))
                wallet += apply_trade(positions[asset], delta, fill)
                fee = abs(delta * fill) * fee_rate
                wallet -= fee
                fees += fee
                traded_notional += abs(delta * fill)
                fills[asset] += 1
                initial, _, tier_util = account_margin(
                    positions, marks, tiers, profile['account_leverage'], fee_rate
                )
                equity_at_open = wallet + sum(unrealized(x, marks[i]) for i, x in enumerate(positions))
                max_margin = max(max_margin, initial / max(equity_at_open, 1e-12))
                max_tier = max(max_tier, tier_util)
                margin_rejections += int(initial > equity_at_open + 1e-8)

        close_marks = market['mark_close'][source_row]
        adverse_marks = np.array([
            market['mark_low'][source_row, i] if position.quantity >= 0.0
            else market['mark_high'][source_row, i]
            for i, position in enumerate(positions)
        ])
        close_equity = wallet + sum(unrealized(x, close_marks[i]) for i, x in enumerate(positions))
        adverse_equity = wallet + sum(unrealized(x, adverse_marks[i]) for i, x in enumerate(positions))
        initial, _, tier_util = account_margin(
            positions, close_marks, tiers, profile['account_leverage'], fee_rate
        )
        _, maintenance, _ = account_margin(
            positions, adverse_marks, tiers, profile['account_leverage'], fee_rate
        )
        max_margin = max(max_margin, initial / max(close_equity, 1e-12))
        max_tier = max(max_tier, tier_util)
        if maintenance > 0.0 and adverse_equity <= maintenance:
            liquidations += 1
            liquidation_rate = float(profile['liquidation_fee_bps']) / 10000.0
            for asset, position in enumerate(positions):
                if abs(position.quantity) <= 1e-15:
                    continue
                delta = -position.quantity
                fill = adverse_marks[asset] * (1.0 + math.copysign(liquidation_rate, delta))
                wallet += apply_trade(position, delta, fill)
                wallet -= abs(delta * fill) * liquidation_rate
                fills[asset] += 1
            close_equity = wallet
        if close_equity <= 0.0 or not np.isfinite(close_equity):
            raise ValidationError('non-positive derivatives equity')
        equity_rows.append(close_equity)
        previous = now

    final_marks = market['mark_close'][source_rows[-1]]
    for asset, position in enumerate(positions):
        if abs(position.quantity) <= 1e-15:
            continue
        delta = -position.quantity
        fill = final_marks[asset] * (1.0 + math.copysign(fallback, delta))
        wallet += apply_trade(position, delta, fill)
        fee = abs(delta * fill) * fee_rate
        wallet -= fee
        fees += fee
        traded_notional += abs(delta * fill)
        fills[asset] += 1
    equity_rows[-1] = wallet
    equity = np.asarray(equity_rows, dtype=float)
    returns = pd.Series(equity).pct_change().replace([np.inf, -np.inf], np.nan).dropna().to_numpy(float)
    drawdown = equity / np.maximum.accumulate(equity) - 1.0
    deviation = float(np.std(returns, ddof=0)) if len(returns) else 0.0
    return {
        'total_return': float(wallet / profile['initial_cash'] - 1.0),
        'max_drawdown': float(-drawdown.min()),
        'sharpe': float(np.mean(returns) / deviation * math.sqrt(BARS_PER_YEAR)) if deviation > 0.0 else 0.0,
        'fill_count': int(fills.sum()),
        'asset_fill_counts': fills.tolist(),
        'turnover': float(traded_notional / profile['initial_cash']),
        'total_fees': float(fees),
        'net_funding_cashflow': float(funding_total),
        'funding_coverage': float(actual_funding / expected_funding) if expected_funding else 1.0,
        'execution_coverage': float(execution_hits / orders) if orders else 1.0,
        'largest_window_participation': float(max_participation),
        'maximum_initial_margin_utilization': float(max_margin),
        'maximum_risk_tier_utilization': float(max_tier),
        'margin_rejections': int(margin_rejections),
        'liquidations': int(liquidations),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(x['total_return']) for x in rows]
    drawdowns = [float(x['max_drawdown']) for x in rows]
    sharpes = [float(x['sharpe']) for x in rows]
    return {
        'positive_ratio': sum(x > 0.0 for x in returns) / len(rows),
        'median_return': float(median(returns)),
        'worst_return': float(min(returns)),
        'worst_drawdown': float(max(drawdowns)),
        'median_sharpe': float(median(sharpes)),
        'minimum_sharpe': float(min(sharpes)),
        'minimum_fill_count': min(int(x['fill_count']) for x in rows),
        'minimum_asset_fill_count': min(min(x['asset_fill_counts']) for x in rows),
        'minimum_funding_coverage': min(float(x['funding_coverage']) for x in rows),
        'minimum_execution_coverage': min(float(x['execution_coverage']) for x in rows),
        'maximum_margin_utilization': max(float(x['maximum_initial_margin_utilization']) for x in rows),
        'maximum_risk_tier_utilization': max(float(x['maximum_risk_tier_utilization']) for x in rows),
        'total_margin_rejections': sum(int(x['margin_rejections']) for x in rows),
        'total_liquidations': sum(int(x['liquidations']) for x in rows),
    }


def gate_checks(summary: dict[str, Any], gate: dict[str, Any]) -> dict[str, bool]:
    return {
        'positive_ratio': summary['positive_ratio'] >= gate['minimum_positive_ratio'],
        'median_return': summary['median_return'] >= gate['minimum_median_return'],
        'worst_return': summary['worst_return'] >= gate['minimum_worst_return'],
        'drawdown': summary['worst_drawdown'] <= gate['maximum_drawdown'],
        'median_sharpe': summary['median_sharpe'] >= gate['minimum_median_sharpe'],
        'minimum_sharpe': summary['minimum_sharpe'] >= gate['minimum_sharpe'],
        'fills': summary['minimum_fill_count'] >= gate['minimum_fill_count'],
        'both_assets_used': summary['minimum_asset_fill_count'] >= gate['minimum_asset_fill_count'],
        'funding_coverage': summary['minimum_funding_coverage'] >= gate['minimum_funding_coverage'],
        'execution_coverage': summary['minimum_execution_coverage'] >= gate['minimum_execution_coverage'],
        'margin_utilization': summary['maximum_margin_utilization'] <= gate['maximum_margin_utilization'],
        'risk_tier_utilization': summary['maximum_risk_tier_utilization'] <= gate['maximum_risk_tier_utilization'],
        'no_margin_rejections': summary['total_margin_rejections'] == 0,
        'no_liquidations': summary['total_liquidations'] == 0,
    }


def run(manifest_path: Path, output_root: Path) -> dict[str, Any]:
    import bybit_portfolio_search_v3 as common

    config = json.loads(manifest_path.read_text(encoding='utf-8'))
    frozen = json.loads(Path(config['frozen_strategy_manifest']).read_text(encoding='utf-8'))
    spot = common.load_market(Path(config['spot_dataset_root']), config['spot_symbols'])
    weights = frozen_weights(spot, frozen)
    symbols = config['linear_symbols']
    client = Client(
        config['api_base_urls'],
        config['timeout_seconds'],
        config['maximum_attempts'],
        config['request_pause_seconds'],
    )
    start_ms = milliseconds(config['history_start_utc'])
    end_ms = milliseconds(config['history_end_exclusive_utc'])
    specs = [fetch_instrument(client, symbol) for symbol in symbols]
    tiers = [fetch_risk_tiers(client, symbol) for symbol in symbols]
    trade = {
        symbol: fetch_klines(client, '/v5/market/kline', symbol, '240', start_ms, end_ms, True)
        for symbol in symbols
    }
    mark = {
        symbol: fetch_klines(client, '/v5/market/mark-price-kline', symbol, '240', start_ms, end_ms)
        for symbol in symbols
    }
    index = {
        symbol: fetch_klines(client, '/v5/market/index-price-kline', symbol, '240', start_ms, end_ms)
        for symbol in symbols
    }
    funding = [fetch_funding(client, symbol, start_ms, end_ms) for symbol in symbols]
    market: dict[str, Any] = {'timestamps': spot['timestamps'], 'symbols': symbols}
    market.update(align_frames(spot['timestamps'], symbols, trade, 'trade', ['open', 'close']))
    market.update(align_frames(spot['timestamps'], symbols, mark, 'mark', ['open', 'high', 'low', 'close']))
    market.update(align_frames(spot['timestamps'], symbols, index, 'index', ['close']))

    execution_cache: dict[tuple[str, int, int], pd.DataFrame] = {}
    profiles: dict[str, Any] = {}
    fold_rows: list[dict[str, Any]] = []
    for name, profile in config['execution_profiles'].items():
        rows = []
        for fold_number, period in enumerate(config['folds'], 1):
            metrics = backtest(
                market, weights, period, profile, specs, tiers, funding, client, execution_cache
            )
            row = {
                'profile': name,
                'fold': fold_number,
                'start': period['start'],
                'end': period['end'],
                **metrics,
            }
            rows.append(row)
            fold_rows.append(row)
        summary = summarize(rows)
        checks = gate_checks(summary, config['gates'][name])
        profiles[name] = {'summary': summary, 'checks': checks, 'passes': all(checks.values())}

    qualified = all(x['passes'] for x in profiles.values())
    mark_basis = market['mark_close'] / market['index_close'] - 1.0
    trade_basis = market['trade_close'] / market['index_close'] - 1.0
    report = {
        'schema_version': 1,
        'validation_id': config['validation_id'],
        'frozen_strategy_id': frozen['strategy_id'],
        'frozen_parameters_changed': False,
        'data': {
            'venue': 'bybit_usdt_linear_perpetual_public_v5',
            'symbols': symbols,
            'instrument_specs': [dataclasses.asdict(x) for x in specs],
            'risk_tier_snapshots': [[dataclasses.asdict(x) for x in group] for group in tiers],
            'risk_tier_snapshot_is_current_not_historical': True,
        },
        'execution_model': {
            'signal_source': 'frozen Spot 4h completed-close signals',
            'pnl_source': 'USDT linear perpetual trade prices',
            'valuation_and_liquidation_source': 'Mark Price OHLC',
            'funding_source': 'historical funding settlements',
            'execution_proxy': 'official 1-minute turnover/volume VWAP plus adverse spread and participation impact',
            'historical_l2_orderbook_available': False,
        },
        'basis': {
            'median_absolute_mark_index_bps': float(np.median(np.abs(mark_basis)) * 10000.0),
            'maximum_absolute_mark_index_bps': float(np.max(np.abs(mark_basis)) * 10000.0),
            'median_absolute_trade_index_bps': float(np.median(np.abs(trade_basis)) * 10000.0),
            'maximum_absolute_trade_index_bps': float(np.max(np.abs(trade_basis)) * 10000.0),
        },
        'profiles': profiles,
        'summary': {
            'qualifies_for_prospective_paper_forward': qualified,
            'all_profiles_pass': qualified,
            'automatic_paper_forward_started': False,
            'live_trading_enabled': False,
        },
        'decision': (
            'eligible_for_prospective_paper_forward_with_frozen_parameters'
            if qualified else 'derivatives_validation_failed_no_promotion'
        ),
        'limitations': [
            'Historical L2 snapshots are unavailable through public V5 historical REST endpoints.',
            'Risk tiers are current public snapshots, not historical snapshots.',
            'Historical evidence is not prospective evidence.',
        ],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / 'derivatives_validation_v1.json').write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8'
    )
    pd.DataFrame(fold_rows).to_csv(output_root / 'derivatives_fold_results.csv', index=False)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--manifest',
        type=Path,
        default=Path('experiments/bybit_derivatives_validation_v1.json'),
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('build/bybit_derivatives_validation_v1'),
    )
    parser.add_argument('--require-qualified', action='store_true')
    args = parser.parse_args()
    report = run(args.manifest, args.output)
    print(json.dumps(report['summary'], sort_keys=True))
    return int(args.require_qualified and not report['summary']['all_profiles_pass'])


if __name__ == '__main__':
    raise SystemExit(main())
