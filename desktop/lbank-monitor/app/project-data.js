window.NEXUS_PROJECT = Object.freeze({
  status: 'complete',
  phase: 6,
  gates: '0–6',
  pipeline_status: 'complete',
  authority: 'research_backtest_paper_only',
  paper_only: true,
  live_trading_authority: false,
  deterministic_risk_final_authority: true,
  canonical_source: 'Bybit',
  secondary_source: 'Binance',
  tertiary_source: 'LBank',
  strategy_families: ['momentum','trend_breakout','mean_reversion'],
  robustness_evidence: ['stress','out_of_sample','regime','benchmark'],
  profitability_claim: false,
  delivery_version: '3.5.0'
});
