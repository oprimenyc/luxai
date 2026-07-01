"""
Unit tests for AuthenticatedUser and auth dependencies.

Covers:
- AuthenticatedUser.id is alias for user_id
- AuthenticatedUser.is_admin reflects role
- AuthenticatedUser.__repr__ does not expose secrets
- get_current_user: valid JWT succeeds
- get_current_user: expired/invalid JWT → 401
- get_admin_user: admin role passes
- get_admin_user: non-admin role → 403
"""

from __future__ import annotations

from uuid import UUID

import pytest

# Lazy fastapi imports — fastapi may not be on the system Python path.
# Tests that need it import inside the function body.
fastapi = pytest.importorskip("fastapi", reason="fastapi not installed on this Python")

from fastapi import HTTPException  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials  # noqa: E402
from src.middleware.auth import AuthenticatedUser, get_admin_user, get_current_user  # noqa: E402


# ── AuthenticatedUser ─────────────────────────────────────────────────────────

class TestAuthenticatedUser:
    def test_id_is_alias_for_user_id(self) -> None:
        uid = UUID("12345678-1234-5678-1234-567812345678")
        user = AuthenticatedUser(user_id=uid, email="test@example.com", role="authenticated")
        assert user.id == uid
        assert user.id is user.user_id

    def test_is_admin_true_for_admin_role(self) -> None:
        user = AuthenticatedUser(
            user_id=UUID("12345678-1234-5678-1234-567812345678"),
            email="admin@example.com",
            role="admin",
        )
        assert user.is_admin is True

    def test_is_admin_false_for_authenticated_role(self) -> None:
        user = AuthenticatedUser(
            user_id=UUID("12345678-1234-5678-1234-567812345678"),
            email="user@example.com",
            role="authenticated",
        )
        assert user.is_admin is False

    def test_repr_contains_email_and_role(self) -> None:
        user = AuthenticatedUser(
            user_id=UUID("12345678-1234-5678-1234-567812345678"),
            email="test@example.com",
            role="authenticated",
        )
        r = repr(user)
        assert "test@example.com" in r
        assert "authenticated" in r


# ── get_current_user ──────────────────────────────────────────────────────────

class TestGetCurrentUser:
    async def test_valid_jwt_returns_user(self) -> None:
        """Test with a real JWT signed with the test secret."""
        from jose import jwt as jose_jwt

        secret = "test-secret-key-for-unit-tests-only"
        uid = "12345678-1234-5678-1234-567812345678"
        token = jose_jwt.encode(
            {
                "sub": uid,
                "email": "test@example.com",
                "role": "authenticated",
                "aud": "authenticated",
            },
            secret,
            algorithm="HS256",
        )

        # Patch settings to use the test secret
        from unittest.mock import patch
        with patch("src.middleware.auth.settings") as mock_settings:
            mock_settings.supabase_jwt_secret = secret
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            user = await get_current_user(creds)

        assert user.email == "test@example.com"
        assert str(user.user_id) == uid
        assert user.role == "authenticated"

    async def test_app_metadata_admin_role_takes_precedence(self) -> None:
        from jose import jwt as jose_jwt
        from unittest.mock import patch

        secret = "test-secret-key-for-unit-tests-only"
        uid = "12345678-1234-5678-1234-567812345678"
        token = jose_jwt.encode(
            {
                "sub": uid,
                "email": "admin@example.com",
                "role": "authenticated",
                "aud": "authenticated",
                "app_metadata": {"role": "admin"},
            },
            secret,
            algorithm="HS256",
        )

        with patch("src.middleware.auth.settings") as mock_settings:
            mock_settings.supabase_jwt_secret = secret
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            user = await get_current_user(creds)

        assert user.role == "admin"
        assert user.is_admin is True

    async def test_invalid_jwt_raises_401(self) -> None:
        from unittest.mock import patch
        with patch("src.middleware.auth.settings") as mock_settings:
            mock_settings.supabase_jwt_secret = "real-secret"
            creds = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="not.a.valid.jwt"
            )
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(creds)
        assert exc_info.value.status_code == 401

    async def test_missing_sub_raises_401(self) -> None:
        from jose import jwt as jose_jwt
        from unittest.mock import patch

        secret = "test-secret"
        token = jose_jwt.encode(
            {
                "email": "test@example.com",
                "role": "authenticated",
                "aud": "authenticated",
            },
            secret,
            algorithm="HS256",
        )
        with patch("src.middleware.auth.settings") as mock_settings:
            mock_settings.supabase_jwt_secret = secret
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(creds)
        assert exc_info.value.status_code == 401


# ── get_admin_user ────────────────────────────────────────────────────────────

class TestGetAdminUser:
    async def test_admin_role_passes(self) -> None:
        uid = UUID("12345678-1234-5678-1234-567812345678")
        admin = AuthenticatedUser(user_id=uid, email="admin@example.com", role="admin")
        result = await get_admin_user(admin)
        assert result is admin

    async def test_non_admin_raises_403(self) -> None:
        uid = UUID("12345678-1234-5678-1234-567812345678")
        user = AuthenticatedUser(user_id=uid, email="user@example.com", role="authenticated")
        with pytest.raises(HTTPException) as exc_info:
            await get_admin_user(user)
        assert exc_info.value.status_code == 403
