"""
packages/options — Options analytics reference package.

The authoritative Python implementations live in apps/api/src/options/
so they are importable within the FastAPI application without PYTHONPATH
manipulation.

This package exists as a future extraction point: when the API is split into
proper uv workspaces or pip editable packages, the code will move here.

For now, reference the API-side modules:
  apps/api/src/options/greeks.py        — Black-Scholes engine
  apps/api/src/options/scorer.py        — 5-factor options scorer
  apps/api/src/options/tradier_client.py — Tradier free-tier chain client
"""
