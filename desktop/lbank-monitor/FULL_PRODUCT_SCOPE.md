# NEXUS Personal Pro Windows 4.0.0 — Full Product Scope

Windows 4.0.0 is the integrated desktop delivery for the currently authorized NEXUS product scope.

Included product surfaces:
- Command Center
- bounded read-only public Bybit closed-candle market
- deterministic local Paper/Demo execution with fee, slippage, stop/target, PnL, session and kill switch
- Research/Strategy preview for momentum, trend breakout and mean reversion using next-bar-open evaluation
- bounded AI Room with local deterministic fallback and optional secure-gateway POST
- Mission Control local projection and optional secure-gateway read projection
- tamper-evident SHA-256 Paper event chain and replay projection
- secure gateway token storage
- visible Live surface with explicit Owner L4 lock

Authority boundary:
- live_trading_authority = false
- no exchange order endpoint
- no withdrawal path
- no signing path
- no private exchange credential input
- deterministic Risk remains final authority
- no profitability claim

The desktop does not embed the Python backend. Its Paper/Risk engine is a deterministic local simulator that mirrors the repository authority boundaries; formal research qualification remains in the repository pipeline.
