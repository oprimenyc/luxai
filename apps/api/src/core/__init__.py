"""
Core infrastructure — Supabase clients, auth, shared dependencies.

Path: apps/api/src/core/__init__.py
Security: No credentials stored here. All secrets loaded from settings.
Scale: Clients created per-request or via singleton pattern per module.
"""
