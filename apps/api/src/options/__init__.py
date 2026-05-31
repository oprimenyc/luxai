"""
Options analytics package — Greeks, scoring, and Tradier chain fetch.

Path: apps/api/src/options/__init__.py
Security: No credentials stored here. Tradier API key read from settings only.
Scale: Stateless pure functions (greeks, scorer). Tradier client is instantiated
       per-request with Redis caching to avoid rate limits.
"""
