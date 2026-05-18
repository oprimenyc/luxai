"""Abstract broker protocol — all adapters must implement this interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from src.trading.models import (
    ExecutionMode,
    OptionsChain,
    Order,
    OrderRequest,
    PortfolioSnapshot,
    Position,
    Quote,
)


class BrokerABC(ABC):
    """
    Contract for all broker adapters.

    Implementations:
    - AlpacaPaperBroker  — Alpaca paper trading REST API
    - SimulationBroker   — fully in-process simulation (no external calls)

    IMPORTANT: live execution adapter is intentionally not implemented.
    All concrete adapters must default execution_mode=PAPER.
    """

    execution_mode: ExecutionMode = ExecutionMode.PAPER

    # ── Order management ─────────────────────────────────────────────────────

    @abstractmethod
    async def submit_order(self, request: OrderRequest) -> Order:
        """Submit a new order. Returns normalised Order with broker_order_id."""
        ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> Order:
        """Cancel a pending/submitted order."""
        ...

    @abstractmethod
    async def get_order(self, broker_order_id: str) -> Order:
        """Fetch current order state by broker ID."""
        ...

    @abstractmethod
    async def list_orders(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Order]:
        """List orders, optionally filtered by status."""
        ...

    # ── Position & portfolio ─────────────────────────────────────────────────

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all open positions."""
        ...

    @abstractmethod
    async def get_portfolio(self) -> PortfolioSnapshot:
        """Return the current portfolio snapshot."""
        ...

    # ── Market data ──────────────────────────────────────────────────────────

    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote:
        """Return latest quote for a symbol."""
        ...

    @abstractmethod
    async def get_options_chain(
        self,
        underlying: str,
        expiration: date,
    ) -> OptionsChain:
        """Return the full options chain for an underlying at a given expiry."""
        ...

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection / initialise session."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection / clean up."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the broker adapter is ready to accept orders."""
        ...
