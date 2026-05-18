"""Trading domain models — orders, positions, portfolio, options, risk."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


# ══════════════════════════════════════════════════════════════════════════════
# Enumerations
# ══════════════════════════════════════════════════════════════════════════════


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"


class OrderStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(StrEnum):
    DAY = "day"
    GTC = "gtc"   # good till cancelled
    IOC = "ioc"   # immediate or cancel
    FOK = "fok"   # fill or kill


class AssetClass(StrEnum):
    EQUITY = "equity"
    OPTION = "option"
    CRYPTO = "crypto"


class OptionType(StrEnum):
    CALL = "call"
    PUT = "put"


class ExecutionMode(StrEnum):
    PAPER = "paper"
    SIMULATION = "simulation"
    LIVE = "live"  # reserved — never enabled automatically


class RiskAction(StrEnum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    POSITION_LIMIT = "position_limit"


# ══════════════════════════════════════════════════════════════════════════════
# Market Data
# ══════════════════════════════════════════════════════════════════════════════


class Quote(BaseModel):
    symbol: str
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    last: float
    volume: int
    timestamp: datetime

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_pct(self) -> float:
        return self.spread / self.mid if self.mid > 0 else 0.0


class Bar(BaseModel):
    """OHLCV bar."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float | None = None
    trade_count: int | None = None


# ══════════════════════════════════════════════════════════════════════════════
# Options
# ══════════════════════════════════════════════════════════════════════════════


class Greeks(BaseModel):
    """Option Greeks — all values nullable until computed."""
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    iv: float | None = None  # implied volatility


class OptionContract(BaseModel):
    """A single options contract with market data and Greeks."""
    symbol: str           # OCC symbol e.g. SPY240119C00480000
    underlying: str       # e.g. SPY
    option_type: OptionType
    strike: float
    expiration: date
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    greeks: Greeks = Field(default_factory=Greeks)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def dte(self) -> int:
        """Days to expiration."""
        return (self.expiration - datetime.now(UTC).date()).days


class OptionsChain(BaseModel):
    """Full options chain for an underlying at a specific expiry."""
    underlying: str
    expiration: date
    underlying_price: float
    calls: list[OptionContract] = Field(default_factory=list)
    puts: list[OptionContract] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def nearest_strike(self, option_type: OptionType, target_delta: float = 0.5) -> OptionContract | None:
        """Return the contract whose delta is closest to target_delta."""
        contracts = self.calls if option_type == OptionType.CALL else self.puts
        with_delta = [c for c in contracts if c.greeks.delta is not None]
        if not with_delta:
            return None
        return min(with_delta, key=lambda c: abs((c.greeks.delta or 0) - target_delta))


class SpreadLeg(BaseModel):
    contract: OptionContract
    quantity: int  # positive = long, negative = short


class VerticalSpread(BaseModel):
    """Bull call / bear put spread — two legs, same expiry, different strikes."""
    underlying: str
    option_type: OptionType
    long_leg: SpreadLeg
    short_leg: SpreadLeg
    max_profit: float
    max_loss: float
    breakeven: float
    risk_reward: float


# ══════════════════════════════════════════════════════════════════════════════
# Orders
# ══════════════════════════════════════════════════════════════════════════════


class OrderRequest(BaseModel):
    """Submitted by strategy — broker adapter converts to broker-specific payload."""
    id: UUID = Field(default_factory=uuid4)
    symbol: str
    side: OrderSide
    qty: int = Field(ge=1)
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    trail_percent: float | None = None   # for trailing stop
    trail_dollars: float | None = None   # for trailing stop
    time_in_force: TimeInForce = TimeInForce.DAY
    asset_class: AssetClass = AssetClass.EQUITY
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    client_order_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("limit_price", "stop_price", mode="before")
    @classmethod
    def round_price(cls, v: float | None) -> float | None:
        return round(v, 4) if v is not None else None


class Order(BaseModel):
    """Canonical order state — normalised from any broker response."""
    id: UUID = Field(default_factory=uuid4)
    broker_order_id: str
    symbol: str
    side: OrderSide
    qty: int
    order_type: OrderType
    status: OrderStatus = OrderStatus.PENDING
    limit_price: float | None = None
    stop_price: float | None = None
    filled_qty: int = 0
    avg_fill_price: float | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    asset_class: AssetClass = AssetClass.EQUITY
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )

    @property
    def fill_value(self) -> float:
        return self.filled_qty * (self.avg_fill_price or 0)


class Fill(BaseModel):
    """An individual execution report / fill event."""
    id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    broker_order_id: str
    symbol: str
    side: OrderSide
    qty: int
    price: float
    commission: float = 0.0
    filled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ══════════════════════════════════════════════════════════════════════════════
# Positions & Portfolio
# ══════════════════════════════════════════════════════════════════════════════


class Position(BaseModel):
    """Open position — updated by the portfolio after each fill."""
    symbol: str
    qty: int                        # positive = long, negative = short
    avg_cost: float                 # cost basis per share
    current_price: float = 0.0
    asset_class: AssetClass = AssetClass.EQUITY
    opened_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def market_value(self) -> float:
        return self.qty * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.qty * self.avg_cost

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        return self.unrealized_pnl / self.cost_basis if self.cost_basis != 0 else 0.0

    @property
    def side(self) -> str:
        return "long" if self.qty > 0 else "short"


class PortfolioSnapshot(BaseModel):
    """Point-in-time portfolio state."""
    account_id: str
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    cash: float
    positions: dict[str, Position] = Field(default_factory=dict)
    realized_pnl: float = 0.0
    snapshotted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def equity(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions.values())

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def position_count(self) -> int:
        return len(self.positions)


class PnLRecord(BaseModel):
    """Closed trade PnL record written to the journal."""
    id: UUID = Field(default_factory=uuid4)
    symbol: str
    side: str  # "long" | "short"
    qty: int
    entry_price: float
    exit_price: float
    commission: float = 0.0
    realized_pnl: float
    realized_pnl_pct: float
    holding_period_seconds: float
    opened_at: datetime
    closed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
# Risk Constraints
# ══════════════════════════════════════════════════════════════════════════════


class RiskConstraints(BaseModel):
    """Hard risk limits — enforced deterministically, never by LLM."""
    max_position_pct: float = Field(default=0.10, ge=0.0, le=1.0)
    max_portfolio_risk_pct: float = Field(default=0.02, ge=0.0, le=1.0)
    stop_loss_pct: float = Field(default=0.02, ge=0.0, le=1.0)
    take_profit_pct: float = Field(default=0.06, ge=0.0, le=1.0)
    trailing_stop_pct: float = Field(default=0.03, ge=0.0, le=1.0)
    max_daily_loss_pct: float = Field(default=0.05, ge=0.0, le=1.0)
    max_open_positions: int = Field(default=10, ge=1)
    allow_shorting: bool = False
    allow_options: bool = True
    max_option_contracts: int = Field(default=5, ge=0)
    execution_mode: ExecutionMode = ExecutionMode.PAPER


class RiskTrigger(BaseModel):
    """Records a risk engine action taken on a position."""
    id: UUID = Field(default_factory=uuid4)
    symbol: str
    action: RiskAction
    reason: str
    entry_price: float
    trigger_price: float
    current_price: float
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
# Audit / Journal
# ══════════════════════════════════════════════════════════════════════════════


class JournalEntry(BaseModel):
    """Immutable audit log entry — written for every order lifecycle event."""
    id: UUID = Field(default_factory=uuid4)
    entry_type: str  # "order_submitted" | "order_filled" | "risk_trigger" | "position_opened" | etc.
    order_id: UUID | None = None
    symbol: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
