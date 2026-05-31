"""
Macro calendar warning engine — FOMC, CPI, NFP, earnings detection.

Path: apps/api/src/workbench/calendar.py
Security: Outbound HTTP to Yahoo Finance (public, no auth) for earnings dates only.
          Macro event list is static data; no credentials required.
Scale: Single async HTTP call for earnings. Macro lookup is O(n) over a small
       static list (~30 events). Entire calendar check < 200ms per analyze call.

Data sources:
  Macro events  — Static list of Fed-published FOMC/CPI/NFP dates (free, reliable).
                  Dates are published 12–18 months in advance by each agency.
  Earnings       — Yahoo Finance public quoteSummary endpoint (no API key required).
                  Falls back gracefully to None if unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import httpx
import structlog

log = structlog.get_logger(__name__)

RiskLevel = Literal["low", "medium", "high"]

_YF_TIMEOUT = httpx.Timeout(5.0)

# ── Static macro event calendar (2025) ───────────────────────────────────────
# Sources:
#   FOMC:  federalreserve.gov/monetarypolicy/fomccalendars.htm
#   CPI:   bls.gov/schedule/news_release/cpi.htm
#   NFP:   bls.gov/schedule/news_release/empsit.htm
#   PCE:   bea.gov/news/schedule
#   GDP:   bea.gov/news/schedule

_MACRO_EVENTS: list[tuple[date, str, RiskLevel]] = [
    # ── FOMC meetings (high impact) ──────────────────────────────────────────
    (date(2025, 1, 29), "FOMC Rate Decision", "high"),
    (date(2025, 3, 19), "FOMC Rate Decision", "high"),
    (date(2025, 5, 7),  "FOMC Rate Decision", "high"),
    (date(2025, 6, 18), "FOMC Rate Decision", "high"),
    (date(2025, 7, 30), "FOMC Rate Decision", "high"),
    (date(2025, 9, 17), "FOMC Rate Decision", "high"),
    (date(2025, 10, 29), "FOMC Rate Decision", "high"),
    (date(2025, 12, 10), "FOMC Rate Decision", "high"),

    # ── CPI releases (high impact) ───────────────────────────────────────────
    (date(2025, 1, 15), "CPI Inflation Report", "high"),
    (date(2025, 2, 12), "CPI Inflation Report", "high"),
    (date(2025, 3, 12), "CPI Inflation Report", "high"),
    (date(2025, 4, 10), "CPI Inflation Report", "high"),
    (date(2025, 5, 13), "CPI Inflation Report", "high"),
    (date(2025, 6, 11), "CPI Inflation Report", "high"),
    (date(2025, 7, 15), "CPI Inflation Report", "high"),
    (date(2025, 8, 13), "CPI Inflation Report", "high"),
    (date(2025, 9, 10), "CPI Inflation Report", "high"),
    (date(2025, 10, 15), "CPI Inflation Report", "high"),
    (date(2025, 11, 13), "CPI Inflation Report", "high"),
    (date(2025, 12, 10), "CPI Inflation Report", "high"),

    # ── Non-Farm Payrolls (high impact) ──────────────────────────────────────
    (date(2025, 1, 10), "Non-Farm Payrolls", "high"),
    (date(2025, 2, 7),  "Non-Farm Payrolls", "high"),
    (date(2025, 3, 7),  "Non-Farm Payrolls", "high"),
    (date(2025, 4, 4),  "Non-Farm Payrolls", "high"),
    (date(2025, 5, 2),  "Non-Farm Payrolls", "high"),
    (date(2025, 6, 6),  "Non-Farm Payrolls", "high"),
    (date(2025, 7, 3),  "Non-Farm Payrolls", "high"),
    (date(2025, 8, 1),  "Non-Farm Payrolls", "high"),
    (date(2025, 9, 5),  "Non-Farm Payrolls", "high"),
    (date(2025, 10, 3), "Non-Farm Payrolls", "high"),
    (date(2025, 11, 7), "Non-Farm Payrolls", "high"),
    (date(2025, 12, 5), "Non-Farm Payrolls", "high"),

    # ── PCE / Core PCE (medium impact) ───────────────────────────────────────
    (date(2025, 1, 31), "PCE Price Index",   "medium"),
    (date(2025, 2, 28), "PCE Price Index",   "medium"),
    (date(2025, 3, 28), "PCE Price Index",   "medium"),
    (date(2025, 4, 30), "PCE Price Index",   "medium"),
    (date(2025, 5, 30), "PCE Price Index",   "medium"),
    (date(2025, 6, 27), "PCE Price Index",   "medium"),
    (date(2025, 7, 31), "PCE Price Index",   "medium"),
    (date(2025, 8, 29), "PCE Price Index",   "medium"),
    (date(2025, 9, 26), "PCE Price Index",   "medium"),
    (date(2025, 10, 31), "PCE Price Index",  "medium"),
    (date(2025, 11, 26), "PCE Price Index",  "medium"),
    (date(2025, 12, 19), "PCE Price Index",  "medium"),

    # ── GDP (medium impact) ───────────────────────────────────────────────────
    (date(2025, 1, 30), "GDP Advance Estimate", "medium"),
    (date(2025, 4, 30), "GDP Advance Estimate", "medium"),
    (date(2025, 7, 30), "GDP Advance Estimate", "medium"),
    (date(2025, 10, 30), "GDP Advance Estimate", "medium"),
]


# ── Result models ─────────────────────────────────────────────────────────────

@dataclass
class MacroEvent:
    name: str
    event_date: date
    risk_level: RiskLevel
    days_away: int

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "event_date": self.event_date.isoformat(),
            "risk_level": self.risk_level,
            "days_away": self.days_away,
        }


@dataclass
class CalendarResult:
    macro_events: list[MacroEvent]
    earnings_warning: bool
    earnings_date: date | None
    earnings_symbol: str

    def to_dict(self) -> dict[str, object]:
        return {
            "macro_events": [e.to_dict() for e in self.macro_events],
            "earnings_warning": self.earnings_warning,
            "earnings_date": self.earnings_date.isoformat() if self.earnings_date else None,
            "earnings_symbol": self.earnings_symbol,
        }


# ── Calendar checker ──────────────────────────────────────────────────────────

class MacroCalendarChecker:
    """
    Checks a trade window (today → expiration) for macro risk events.

    Macro events are sourced from a static pre-loaded list of Fed/BLS/BEA
    published dates. Earnings dates are fetched from Yahoo Finance on demand.
    """

    def check(
        self,
        symbol: str,
        expiration: date,
        earnings_date: date | None = None,
    ) -> CalendarResult:
        """
        Return all macro events that fall between today and expiration (inclusive).

        Args:
            symbol: Underlying ticker — used for earnings warning labelling.
            expiration: Option expiration date.
            earnings_date: Pre-fetched earnings date (from fetch_earnings_date()).
                           If None, no earnings warning is raised.
        """
        today = datetime.now(UTC).date()
        events: list[MacroEvent] = []

        for event_date, name, risk_level in _MACRO_EVENTS:
            if today <= event_date <= expiration:
                events.append(MacroEvent(
                    name=name,
                    event_date=event_date,
                    risk_level=risk_level,
                    days_away=(event_date - today).days,
                ))

        # Sort by date ascending
        events.sort(key=lambda e: e.event_date)

        earnings_warning = False
        if earnings_date and today <= earnings_date <= expiration:
            earnings_warning = True

        return CalendarResult(
            macro_events=events,
            earnings_warning=earnings_warning,
            earnings_date=earnings_date,
            earnings_symbol=symbol.upper(),
        )


async def fetch_earnings_date(symbol: str) -> date | None:
    """
    Fetch the next earnings date for a symbol via Yahoo Finance.

    Free, no auth required. Returns None if unavailable or on any error.
    Failure is always non-fatal — the workbench proceeds without the warning.
    """
    url = (
        f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol.upper()}"
        f"?modules=calendarEvents"
    )
    try:
        async with httpx.AsyncClient(timeout=_YF_TIMEOUT) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return None

            data = resp.json()
            result = data.get("quoteSummary", {}).get("result", [])
            if not result:
                return None

            earnings_dates = (
                result[0]
                .get("calendarEvents", {})
                .get("earnings", {})
                .get("earningsDate", [])
            )
            if not earnings_dates:
                return None

            # earningsDate is a list of {raw: epoch_seconds, fmt: "YYYY-MM-DD"}
            raw_ts = earnings_dates[0].get("raw")
            if raw_ts:
                return datetime.fromtimestamp(raw_ts, tz=UTC).date()

    except Exception as exc:
        log.warning(
            "earnings_date_fetch_failed",
            symbol=symbol,
            error=str(exc),
        )
    return None
