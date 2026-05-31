"""
Auth dependencies — canonical import location for authentication.

Path: apps/api/src/core/auth.py
Security: Re-exports from src.middleware.auth. JWT validation uses the
          Supabase JWT secret (HS256). Admin role gated via Supabase
          app_metadata.role claim — never a user-writable field.
Scale: O(1) per request — JWT decode is CPU-bound but negligible at
       the single-instance Railway deployment scale.

Import from here (not from middleware.auth) for new code:
    from src.core.auth import AuthenticatedUser, get_current_user, get_admin_user
"""

from src.middleware.auth import (  # noqa: F401 — canonical re-export
    AuthenticatedUser,
    get_admin_user,
    get_current_user,
)

__all__ = ["AuthenticatedUser", "get_current_user", "get_admin_user"]
