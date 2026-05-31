"""JWT authentication via Supabase."""

from uuid import UUID

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from src.config import settings

log = structlog.get_logger(__name__)
bearer = HTTPBearer(auto_error=True)


class AuthenticatedUser:
    def __init__(self, user_id: UUID, email: str, role: str) -> None:
        self.user_id = user_id
        self.email = email
        self.role = role

    @property
    def id(self) -> UUID:
        """Alias for user_id — convenience for code that uses user.id."""
        return self.user_id

    @property
    def is_admin(self) -> bool:
        """True if the user has admin role in their Supabase JWT."""
        return self.role == "admin"

    def __repr__(self) -> str:
        return f"AuthenticatedUser(id={self.user_id}, email={self.email!r}, role={self.role!r})"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> AuthenticatedUser:
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        user_id = payload.get("sub")
        email = payload.get("email", "")
        role = payload.get("role", "authenticated")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )

        return AuthenticatedUser(user_id=UUID(user_id), email=email, role=role)

    except JWTError as exc:
        log.warning("jwt_decode_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


async def get_admin_user(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """
    FastAPI dependency that requires admin role.

    Admin role is set in Supabase Auth via app_metadata.role = 'admin'.
    Returns AuthenticatedUser if admin; raises HTTP 403 otherwise.

    Usage: admin_user: AuthenticatedUser = Depends(get_admin_user)
    """
    if not user.is_admin:
        log.warning(
            "admin_access_denied",
            user_id=str(user.user_id),
            email=user.email,
            role=user.role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required for this operation.",
        )
    return user
