"""
Path: apps/api/tests/test_workbench_account_equity.py
Security: Verifies the workbench derives account equity from Alpaca paper
          instead of trusting caller-provided account size.
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

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str]) -> _FakeResponse:
        return self._response


@pytest.mark.asyncio
async def test_fetch_paper_account_equity_returns_equity() -> None:
    response = _FakeResponse({"paper": True, "equity": "432.10"})
    with (
        patch("src.workbench.router.settings.alpaca_api_key", "key"),
        patch("src.workbench.router.settings.alpaca_api_secret", "secret"),
        patch("src.workbench.router.httpx.AsyncClient", return_value=_FakeAsyncClient(response)),
    ):
        equity = await _fetch_paper_account_equity()

    assert equity == 432.10


@pytest.mark.asyncio
async def test_fetch_paper_account_equity_rejects_non_paper_account() -> None:
    response = _FakeResponse({"paper": False, "paper_trading": False, "equity": "432.10"})
    with (
        patch("src.workbench.router.settings.alpaca_api_key", "key"),
        patch("src.workbench.router.settings.alpaca_api_secret", "secret"),
        patch("src.workbench.router.httpx.AsyncClient", return_value=_FakeAsyncClient(response)),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _fetch_paper_account_equity()

    assert exc_info.value.status_code == 503
