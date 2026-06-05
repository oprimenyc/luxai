"use client";

import { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";

// ── Types ────────────────────────────────────────────────────────────────────

interface Portfolio {
  account_id: string;
  execution_mode: string;
  cash: number;
  equity: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  position_count: number;
  positions: Record<string, PositionData>;
}

interface PositionData {
  qty: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  side: string;
}

interface PnLRecord {
  id: string;
  symbol: string;
  side: string;
  qty: number;
  entry_price: number;
  exit_price: number;
  realized_pnl: number;
  realized_pnl_pct: number;
  holding_period_seconds: number;
  opened_at: string;
  closed_at: string;
}

interface JournalEntry {
  id: string;
  entry_type: string;
  symbol: string | null;
  order_id: string | null;
  recorded_at: string;
  payload: Record<string, unknown>;
}

type Tab = "portfolio" | "pnl" | "journal";
type OrderSide = "buy" | "sell";
type OrderType = "market" | "limit" | "stop";

// ── Helpers ──────────────────────────────────────────────────────────────────

// Use absolute URL to the backend — relative /api/v1 would hit Vercel, not Fly.io.
const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function fmt(n: number, decimals = 2) {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function fmtPct(n: number) {
  return `${n >= 0 ? "+" : ""}${(n * 100).toFixed(2)}%`;
}

function pnlColor(v: number) {
  if (v > 0) return "text-emerald-400";
  if (v < 0) return "text-red-400";
  return "text-zinc-400";
}

// ── Components ───────────────────────────────────────────────────────────────

function StatusBadge({ mode }: { mode: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium uppercase tracking-wider text-amber-400">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" />
      {mode}
    </span>
  );
}

function MetricCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "positive" | "negative" | "neutral";
}) {
  const color =
    accent === "positive"
      ? "text-emerald-400"
      : accent === "negative"
        ? "text-red-400"
        : "text-white";
  return (
    <div className="rounded-xl border border-zinc-800/60 bg-zinc-900/60 p-4">
      <p className="mb-1 text-xs font-medium uppercase tracking-widest text-zinc-500">{label}</p>
      <p className={`text-2xl font-light tabular-nums ${color}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-zinc-500">{sub}</p>}
    </div>
  );
}

// ── Order Form ────────────────────────────────────────────────────────────────

function OrderForm({ onSuccess }: { onSuccess: () => void }) {
  const [symbol, setSymbol] = useState("SPY");
  const [side, setSide] = useState<OrderSide>("buy");
  const [qty, setQty] = useState("1");
  const [orderType, setOrderType] = useState<OrderType>("market");
  const [limitPrice, setLimitPrice] = useState("");
  const [stopPrice, setStopPrice] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [suggested, setSuggested] = useState<number | null>(null);

  async function loadSuggestion() {
    try {
      const quote = await apiFetch<{ last: number }>(`/trading/quote/${symbol.toUpperCase()}`);
      const size = await apiFetch<{ suggested_qty: number }>(
        `/trading/size?symbol=${symbol.toUpperCase()}&price=${quote.last}`,
      );
      setSuggested(size.suggested_qty);
    } catch {
      setSuggested(null);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setLoading(true);
    try {
      // idempotency_key is required by the backend (B1 safety chain).
      // Generate a new UUID per submission — prevents duplicate order replay.
      const idempotencyKey = crypto.randomUUID();

      const body: Record<string, unknown> = {
        symbol: symbol.toUpperCase(),
        side,
        qty: parseInt(qty, 10),
        order_type: orderType,
        idempotency_key: idempotencyKey,
      };
      if (orderType !== "market" && limitPrice) body.limit_price = parseFloat(limitPrice);
      if (orderType === "stop" && stopPrice) body.stop_price = parseFloat(stopPrice);

      const order = await apiFetch<{ broker_order_id: string }>("/trading/orders", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setSuccess(`Order submitted: ${order.broker_order_id}`);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit order");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form
      onSubmit={(e) => {
        void handleSubmit(e);
      }}
      className="space-y-4 rounded-xl border border-zinc-800/60 bg-zinc-900/60 p-5"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium tracking-wide text-zinc-300">New Order</h3>
        <StatusBadge mode="paper" />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className="mb-1 block text-xs text-zinc-500">Symbol</label>
          <div className="flex gap-2">
            <input
              value={symbol}
              onChange={(e) => {
                setSymbol(e.target.value.toUpperCase());
              }}
              className="flex-1 rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm uppercase text-white focus:border-zinc-500 focus:outline-none"
              placeholder="SPY"
              maxLength={20}
              required
            />
            <button
              type="button"
              onClick={() => {
                void loadSuggestion();
              }}
              className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-xs text-zinc-400 transition-colors hover:border-zinc-600"
            >
              Size
            </button>
          </div>
          {suggested !== null && (
            <p className="mt-1 text-xs text-amber-400">
              Suggested qty: {suggested}{" "}
              <button
                type="button"
                className="underline"
                onClick={() => {
                  setQty(String(suggested));
                }}
              >
                use
              </button>
            </p>
          )}
        </div>

        <div>
          <label className="mb-1 block text-xs text-zinc-500">Side</label>
          <div className="flex overflow-hidden rounded-lg border border-zinc-700">
            {(["buy", "sell"] as OrderSide[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => {
                  setSide(s);
                }}
                className={`flex-1 py-2 text-xs font-medium transition-colors ${
                  side === s
                    ? s === "buy"
                      ? "bg-emerald-600 text-white"
                      : "bg-red-600 text-white"
                    : "bg-zinc-800 text-zinc-400 hover:text-white"
                }`}
              >
                {s.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="mb-1 block text-xs text-zinc-500">Quantity</label>
          <input
            type="number"
            value={qty}
            onChange={(e) => {
              setQty(e.target.value);
            }}
            min={1}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white focus:border-zinc-500 focus:outline-none"
            required
          />
        </div>

        <div className="col-span-2">
          <label className="mb-1 block text-xs text-zinc-500">Order Type</label>
          <select
            value={orderType}
            onChange={(e) => {
              setOrderType(e.target.value as OrderType);
            }}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white focus:border-zinc-500 focus:outline-none"
          >
            <option value="market">Market</option>
            <option value="limit">Limit</option>
            <option value="stop">Stop</option>
          </select>
        </div>

        {orderType === "limit" && (
          <div>
            <label className="mb-1 block text-xs text-zinc-500">Limit Price</label>
            <input
              type="number"
              step="0.01"
              value={limitPrice}
              onChange={(e) => {
                setLimitPrice(e.target.value);
              }}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white focus:border-zinc-500 focus:outline-none"
              placeholder="0.00"
            />
          </div>
        )}

        {orderType === "stop" && (
          <div>
            <label className="mb-1 block text-xs text-zinc-500">Stop Price</label>
            <input
              type="number"
              step="0.01"
              value={stopPrice}
              onChange={(e) => {
                setStopPrice(e.target.value);
              }}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white focus:border-zinc-500 focus:outline-none"
              placeholder="0.00"
            />
          </div>
        )}
      </div>

      <AnimatePresence>
        {error && (
          <motion.p
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400"
          >
            {error}
          </motion.p>
        )}
        {success && (
          <motion.p
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-400"
          >
            {success}
          </motion.p>
        )}
      </AnimatePresence>

      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-lg bg-white py-2.5 text-sm font-medium text-zinc-900 transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {loading ? "Submitting…" : "Submit Paper Order"}
      </button>
    </form>
  );
}

// ── Positions Table ───────────────────────────────────────────────────────────

function PositionsTable({ positions }: { positions: Record<string, PositionData> }) {
  const rows = Object.entries(positions);
  if (rows.length === 0) {
    return <div className="py-10 text-center text-sm text-zinc-600">No open positions</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-xs uppercase tracking-widest text-zinc-500">
            <th className="py-2 pr-4 text-left font-medium">Symbol</th>
            <th className="py-2 pr-4 text-right font-medium">Qty</th>
            <th className="py-2 pr-4 text-right font-medium">Avg Cost</th>
            <th className="py-2 pr-4 text-right font-medium">Price</th>
            <th className="py-2 pr-4 text-right font-medium">Mkt Value</th>
            <th className="py-2 text-right font-medium">Unr. PnL</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([sym, pos]) => (
            <tr key={sym} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
              <td className="py-2.5 pr-4 font-medium text-white">{sym}</td>
              <td className="py-2.5 pr-4 text-right tabular-nums text-zinc-300">{pos.qty}</td>
              <td className="py-2.5 pr-4 text-right tabular-nums text-zinc-400">
                ${fmt(pos.avg_cost, 4)}
              </td>
              <td className="py-2.5 pr-4 text-right tabular-nums text-zinc-300">
                ${fmt(pos.current_price, 4)}
              </td>
              <td className="py-2.5 pr-4 text-right tabular-nums text-zinc-300">
                ${fmt(pos.market_value)}
              </td>
              <td className={`py-2.5 text-right tabular-nums ${pnlColor(pos.unrealized_pnl)}`}>
                {pos.unrealized_pnl >= 0 ? "+" : ""}${fmt(pos.unrealized_pnl)}{" "}
                <span className="text-xs opacity-70">{fmtPct(pos.unrealized_pnl_pct)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── PnL Table ─────────────────────────────────────────────────────────────────

function PnLTable({ records }: { records: PnLRecord[] }) {
  if (records.length === 0) {
    return <div className="py-10 text-center text-sm text-zinc-600">No closed trades yet</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-xs uppercase tracking-widest text-zinc-500">
            <th className="py-2 pr-4 text-left font-medium">Symbol</th>
            <th className="py-2 pr-4 text-right font-medium">Side</th>
            <th className="py-2 pr-4 text-right font-medium">Qty</th>
            <th className="py-2 pr-4 text-right font-medium">Entry</th>
            <th className="py-2 pr-4 text-right font-medium">Exit</th>
            <th className="py-2 text-right font-medium">PnL</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r) => (
            <tr key={r.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
              <td className="py-2.5 pr-4 font-medium text-white">{r.symbol}</td>
              <td className="py-2.5 pr-4 text-right">
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    r.side === "long"
                      ? "bg-emerald-500/10 text-emerald-400"
                      : "bg-red-500/10 text-red-400"
                  }`}
                >
                  {r.side.toUpperCase()}
                </span>
              </td>
              <td className="py-2.5 pr-4 text-right tabular-nums text-zinc-400">{r.qty}</td>
              <td className="py-2.5 pr-4 text-right tabular-nums text-zinc-400">
                ${fmt(r.entry_price, 4)}
              </td>
              <td className="py-2.5 pr-4 text-right tabular-nums text-zinc-400">
                ${fmt(r.exit_price, 4)}
              </td>
              <td
                className={`py-2.5 text-right font-medium tabular-nums ${pnlColor(r.realized_pnl)}`}
              >
                {r.realized_pnl >= 0 ? "+" : ""}${fmt(r.realized_pnl)}{" "}
                <span className="text-xs opacity-70">{fmtPct(r.realized_pnl_pct)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Journal Table ─────────────────────────────────────────────────────────────

function JournalTable({ entries }: { entries: JournalEntry[] }) {
  if (entries.length === 0) {
    return <div className="py-10 text-center text-sm text-zinc-600">No journal entries</div>;
  }

  const typeColor: Record<string, string> = {
    order_submitted: "text-blue-400",
    order_filled: "text-emerald-400",
    order_cancelled: "text-zinc-500",
    order_rejected: "text-red-400",
    pnl_closed: "text-amber-400",
    risk_trigger: "text-orange-400",
    portfolio_snapshot: "text-purple-400",
  };

  return (
    <div className="space-y-1">
      {entries.map((e) => (
        <div
          key={e.id}
          className="flex items-start gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-zinc-800/30"
        >
          <span
            className={`mt-0.5 font-mono text-xs ${typeColor[e.entry_type] ?? "text-zinc-500"}`}
          >
            {e.entry_type.replace(/_/g, " ").toUpperCase()}
          </span>
          {e.symbol && <span className="text-xs font-medium text-zinc-300">{e.symbol}</span>}
          <span className="ml-auto text-xs tabular-nums text-zinc-600">
            {new Date(e.recorded_at).toLocaleTimeString()}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export function TradingClient() {
  const [tab, setTab] = useState<Tab>("portfolio");
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [pnlRecords, setPnlRecords] = useState<PnLRecord[]>([]);
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [halting, setHalting] = useState(false);
  const [telemetry, setTelemetry] = useState<any>(null);

  const handleEmergencyHalt = async () => {
    if (
      !confirm(
        "Are you sure? This will permanently lock the trading engine and cancel all pending orders.",
      )
    )
      return;
    setHalting(true);
    try {
      await apiFetch("/trading/emergency-halt", { method: "POST" });
      setError("EMERGENCY HALT ACTIVATED: Trading engine is locked.");
      void load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to execute emergency halt.");
    } finally {
      setHalting(false);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, pnl, j, stat] = await Promise.all([
        apiFetch<Portfolio>("/trading/portfolio"),
        apiFetch<PnLRecord[]>("/trading/pnl?limit=50"),
        apiFetch<JournalEntry[]>("/trading/journal?limit=50"),
        apiFetch<any>("/trading/status"),
      ]);
      setPortfolio(p);
      setPnlRecords(pnl);
      setJournal(j);
      if (stat.telemetry) setTelemetry(stat.telemetry);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load trading data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = setInterval(() => void load(), 15_000);
    return () => {
      clearInterval(interval);
    };
  }, [load]);

  const tabs: { id: Tab; label: string }[] = [
    { id: "portfolio", label: "Positions" },
    { id: "pnl", label: "PnL History" },
    { id: "journal", label: "Journal" },
  ];

  return (
    <div className="min-h-screen space-y-6 bg-zinc-950 p-6 text-white">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-light tracking-wide text-white">Paper Trading</h1>
          <p className="mt-0.5 text-sm text-zinc-500">Deterministic simulation — no live orders</p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge mode="paper" />
          <button
            onClick={() => void load()}
            className="text-xs text-zinc-500 transition-colors hover:text-zinc-300"
          >
            Refresh
          </button>
          <button
            onClick={() => {
              void handleEmergencyHalt();
            }}
            disabled={halting}
            className="ml-2 rounded border border-red-500/30 bg-red-500/20 px-3 py-1.5 text-xs font-bold uppercase tracking-widest text-red-500 transition-colors hover:bg-red-500/30 disabled:opacity-50"
          >
            {halting ? "HALTING..." : "EMERGENCY HALT"}
          </button>
        </div>
      </div>

      {/* Error state */}
      <AnimatePresence>
        {telemetry?.degraded_risk_mode && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm font-medium text-red-400"
          >
            ⚠️ DEGRADED RISK MODE: Market data quotes are delayed. New entries blocked.
          </motion.div>
        )}
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-400"
          >
            {error.includes("not configured") ? (
              <>
                Alpaca paper trading credentials are not configured. Add{" "}
                <code className="text-amber-300">ALPACA_API_KEY</code> and{" "}
                <code className="text-amber-300">ALPACA_API_SECRET</code> to your environment.
              </>
            ) : (
              error
            )}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        {/* Left: Metrics + Order Form */}
        <div className="space-y-4">
          {portfolio ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="grid grid-cols-2 gap-3"
            >
              <MetricCard label="Equity" value={`$${fmt(portfolio.equity)}`} sub="Paper account" />
              <MetricCard label="Cash" value={`$${fmt(portfolio.cash)}`} />
              <MetricCard
                label="Total PnL"
                value={`${portfolio.total_pnl >= 0 ? "+" : ""}$${fmt(Math.abs(portfolio.total_pnl))}`}
                accent={
                  portfolio.total_pnl > 0
                    ? "positive"
                    : portfolio.total_pnl < 0
                      ? "negative"
                      : "neutral"
                }
              />
              <MetricCard
                label="Realized"
                value={`${portfolio.realized_pnl >= 0 ? "+" : ""}$${fmt(Math.abs(portfolio.realized_pnl))}`}
                accent={
                  portfolio.realized_pnl > 0
                    ? "positive"
                    : portfolio.realized_pnl < 0
                      ? "negative"
                      : "neutral"
                }
              />
            </motion.div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="h-20 animate-pulse rounded-xl border border-zinc-800/60 bg-zinc-900/60"
                />
              ))}
            </div>
          )}

          <OrderForm onSuccess={() => void load()} />
        </div>

        {/* Right: Tabs */}
        <div className="rounded-xl border border-zinc-800/60 bg-zinc-900/40 xl:col-span-2">
          <div className="flex border-b border-zinc-800/60">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => {
                  setTab(t.id);
                }}
                className={`px-5 py-3 text-sm transition-colors ${
                  tab === t.id
                    ? "border-b border-white text-white"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {t.label}
                {t.id === "portfolio" && portfolio && (
                  <span className="ml-2 text-xs text-zinc-600">{portfolio.position_count}</span>
                )}
              </button>
            ))}
          </div>

          <div className="p-4">
            <AnimatePresence mode="wait">
              {loading && !portfolio ? (
                <motion.div
                  key="loading"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="space-y-2 py-4"
                >
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="h-8 animate-pulse rounded bg-zinc-800/50" />
                  ))}
                </motion.div>
              ) : tab === "portfolio" ? (
                <motion.div
                  key="portfolio"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                >
                  <PositionsTable positions={portfolio?.positions ?? {}} />
                </motion.div>
              ) : tab === "pnl" ? (
                <motion.div
                  key="pnl"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                >
                  <PnLTable records={pnlRecords} />
                </motion.div>
              ) : (
                <motion.div
                  key="journal"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                >
                  <JournalTable entries={journal} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </div>
  );
}
