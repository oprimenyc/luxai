"""
Path: apps/api/tests/test_startup_checks.py
Security: Verifies the boot gate refuses to start unless Alpaca credentials
          authenticate against the paper endpoint and are rejected by the
          live endpoint (Alpaca's account object has no "paper_trading"
          field, so mode is inferred from key/endpoint pairing).
Scale: Unit tests with mocked HTTPX client; no broker/network side effects.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.config import Settings
from src.core.startup_checks import AlpacaPaperModeError, verify_alpaca_paper_mode


def _settings(**overrides: object) -> Settings:
    base = {
        "supabase_url": "https://x.supabase.co",
        "supabase_anon_key": "anon",
        "supabase_service_role_key": "service",
        "supabase_jwt_secret": "secret",
        "alpaca_api_key": "key",
        "alpaca_api_secret": "secret",
        "alpaca_paper": True,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class _FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeAsyncClient:
    """Routes GET calls to a paper or live canned response by URL host."""

    def __init__(self, paper_response: _FakeResponse, live_response: _FakeResponse) -> None:
        self._paper_response = paper_response
        self._live_response = live_response

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str]) -> _FakeResponse:  # noqa: ARG002
        if "paper-api" in url:
            return self._paper_response
        return self._live_response


@pytest.mark.asyncio
async def test_refuses_start_when_alpaca_paper_flag_false() -> None:
    settings = _settings(alpaca_paper=False)
    with pytest.raises(AlpacaPaperModeError):
        await verify_alpaca_paper_mode(settings)


@pytest.mark.asyncio
async def test_refuses_start_when_credentials_also_work_on_live() -> None:
    settings = _settings()
    paper = _FakeResponse({"id": "acct-1"}, status_code=200)
    live = _FakeResponse({"id": "acct-1"}, status_code=200)
    with (
        patch(
            "src.core.startup_checks.httpx.AsyncClient",
            return_value=_FakeAsyncClient(paper, live),
        ),
        pytest.raises(AlpacaPaperModeError),
    ):
        await verify_alpaca_paper_mode(settings)


@pytest.mark.asyncio
async def test_refuses_start_when_paper_endpoint_rejects_credentials() -> None:
    settings = _settings()
    paper = _FakeResponse({"message": "unauthorized"}, status_code=401)
    live = _FakeResponse({"message": "unauthorized"}, status_code=401)
    with (
        patch(
            "src.core.startup_checks.httpx.AsyncClient",
            return_value=_FakeAsyncClient(paper, live),
        ),
        pytest.raises(AlpacaPaperModeError),
    ):
        await verify_alpaca_paper_mode(settings)


@pytest.mark.asyncio
async def test_passes_when_paper_accepts_and_live_rejects() -> None:
    settings = _settings()
    paper = _FakeResponse({"id": "paper-acct"}, status_code=200)
    live = _FakeResponse({"message": "unauthorized"}, status_code=401)
    with patch(
        "src.core.startup_checks.httpx.AsyncClient",
        return_value=_FakeAsyncClient(paper, live),
    ):
        await verify_alpaca_paper_mode(settings)


@pytest.mark.asyncio
async def test_skips_live_check_when_no_credentials_configured() -> None:
    settings = _settings(alpaca_api_key="", alpaca_api_secret="")
    await verify_alpaca_paper_mode(settings)
