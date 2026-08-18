window.NEXUS_PROJECT = Object.freeze({
  name: 'NEXUS Personal Pro',
  product_surface: 'integrated_desktop',
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
  delivery_version: '4.0.0',
  full_product_modules: [
    'public_market', 'research_lab', 'strategy_factory', 'deterministic_risk',
    'paper_execution', 'ai_room', 'mission_control', 'audit_replay', 'settings', 'locked_live_surface'
  ],
  backend_contracts: {
    research: 'phase6_research_pipeline.py',
    strategy_factory: 'phase5_strategy_factory.py',
    risk: 'deterministic_risk.py',
    paper_execution: 'paper_execution.py',
    paper_event_store: 'paper_event_store.py / nexus.paper-event.v1',
    ai_room: 'ai_room.py / nexus.ai-room.v2',
    mission_control: 'mission_control.py'
  },
  desktop_delivery: {
    paper: 'local deterministic simulator mirroring backend risk/paper boundaries',
    market: 'bounded main-process Bybit closed-candle bridge',
    ai_room: 'local bounded Ops Room with optional secure-gateway POST',
    mission_control: 'local projection with optional secure-gateway GET',
    audit: 'local SHA-256 chained Paper ledger and replay projection',
    live: 'visible but locked; no exchange order, withdrawal, signing or private exchange credential path'
  }
});
