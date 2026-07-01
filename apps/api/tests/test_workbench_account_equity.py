"""
Path: apps/api/tests/test_workbench_account_equity.py
Security: Verifies the workbench derives account equity from Alpaca paper
          instead of trusting caller-provided account size, and delegates
          paper-mode verification to the shared resolve_paper_account check.
Scale: Unit tests with mocked HTTPX client; no broker/network side effects.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.workbench.router import _fetch_paper_account_equity


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
async def test_fetch_paper_account_equity_returns_equity() -> None:
    paper = _FakeResponse({"equity": "432.10", "id": "paper-acct"})
    live = _FakeResponse({"message": "unauthorized"}, status_code=401)
    with (
        patch("src.workbench.router.settings.alpaca_api_key", "key"),
        patch("src.workbench.router.settings.alpaca_api_secret", "secret"),
        patch(
            "src.core.startup_checks.httpx.AsyncClient",
            return_value=_FakeAsyncClient(paper, live),
        ),
    ):
        equity = await _fetch_paper_account_equity()

    assert equity == 432.10


@pytest.mark.asyncio
async def test_fetch_paper_account_equity_rejects_live_capable_credentials() -> None:
    paper = _FakeResponse({"equity": "432.10", "id": "acct"})
    live = _FakeResponse({"equity": "432.10", "id": "acct"}, status_code=200)
    with (
        patch("src.workbench.router.settings.alpaca_api_key", "key"),
        patch("src.workbench.router.settings.alpaca_api_secret", "secret"),
        patch(
            "src.core.startup_checks.httpx.AsyncClient",
            return_value=_FakeAsyncClient(paper, live),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await _fetch_paper_account_equity()

    assert exc_info.value.status_code == 503
