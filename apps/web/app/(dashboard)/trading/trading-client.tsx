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

const BASE = "/api/v1";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
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
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs font-medium uppercase tracking-wider">
      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
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
    <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-xl p-4">
      <p className="text-zinc-500 text-xs font-medium uppercase tracking-widest mb-1">
        {label}
      </p>
      <p className={`text-2xl font-light tabular-nums ${color}`}>{value}</p>
      {sub && <p className="text-zinc-500 text-xs mt-0.5">{sub}</p>}
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
        `/trading/size?symbol=${symbol.toUpperCase()}&price=${quote.last}`
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
      const body: Record<string, unknown> = {
        symbol: symbol.toUpperCase(),
        side,
        qty: parseInt(qty, 10),
        order_type: orderType,
      };
      if (orderType !== "market" && limitPrice) body.limit_price = parseFloat(limitPrice);
      if (orderType === "stop" && stopPrice)
        body.stop_price = parseFloat(stopPrice);

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
      onSubmit={handleSubmit}
      className="bg-zinc-900/60 border border-zinc-800/60 rounded-xl p-5 space-y-4"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-zinc-300 tracking-wide">New Order</h3>
        <StatusBadge mode="paper" />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className="text-xs text-zinc-500 mb-1 block">Symbol</label>
          <div className="flex gap-2">
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white uppercase focus:outline-none focus:border-zinc-500"
              placeholder="SPY"
              maxLength={20}
              required
            />
            <button
              type="button"
              onClick={loadSuggestion}
              className="px-3 py-2 text-xs text-zinc-400 bg-zinc-800 border border-zinc-700 rounded-lg hover:border-zinc-600 transition-colors"
            >
              Size
            </button>
          </div>
          {suggested !== null && (
            <p className="text-xs text-amber-400 mt-1">
              Suggested qty: {suggested}{" "}
              <button
                type="button"
                className="underline"
                onClick={() => setQty(String(suggested))}
              >
                use
              </button>
            </p>
          )}
        </div>

        <div>
          <label className="text-xs text-zinc-500 mb-1 block">Side</label>
          <div className="flex rounded-lg overflow-hidden border border-zinc-700">
            {(["buy", "sell"] as OrderSide[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSide(s)}
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
          <label className="text-xs text-zinc-500 mb-1 block">Quantity</label>
          <input
            type="number"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            min={1}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-zinc-500"
            required
          />
        </div>

        <div className="col-span-2">
          <label className="text-xs text-zinc-500 mb-1 block">Order Type</label>
          <select
            value={orderType}
            onChange={(e) => setOrderType(e.target.value as OrderType)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-zinc-500"
          >
            <option value="market">Market</option>
            <option value="limit">Limit</option>
            <option value="stop">Stop</option>
          </select>
        </div>

        {orderType === "limit" && (
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">Limit Price</label>
            <input
              type="number"
              step="0.01"
              value={limitPrice}
              onChange={(e) => setLimitPrice(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-zinc-500"
              placeholder="0.00"
            />
          </div>
        )}

        {orderType === "stop" && (
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">Stop Price</label>
            <input
              type="number"
              step="0.01"
              value={stopPrice}
              onChange={(e) => setStopPrice(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-zinc-500"
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
            className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2"
          >
            {error}
          </motion.p>
        )}
        {success && (
          <motion.p
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2"
          >
            {success}
          </motion.p>
        )}
      </AnimatePresence>

      <button
        type="submit"
        disabled={loading}
        className="w-full py-2.5 rounded-lg bg-white text-zinc-900 text-sm font-medium hover:bg-zinc-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
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
    return (
      <div className="text-center py-10 text-zinc-600 text-sm">No open positions</div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-zinc-500 text-xs uppercase tracking-widest border-b border-zinc-800">
            <th className="text-left py-2 pr-4 font-medium">Symbol</th>
            <th className="text-right py-2 pr-4 font-medium">Qty</th>
            <th className="text-right py-2 pr-4 font-medium">Avg Cost</th>
            <th className="text-right py-2 pr-4 font-medium">Price</th>
            <th className="text-right py-2 pr-4 font-medium">Mkt Value</th>
            <th className="text-right py-2 font-medium">Unr. PnL</th>
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
    return (
      <div className="text-center py-10 text-zinc-600 text-sm">No closed trades yet</div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-zinc-500 text-xs uppercase tracking-widest border-b border-zinc-800">
            <th className="text-left py-2 pr-4 font-medium">Symbol</th>
            <th className="text-right py-2 pr-4 font-medium">Side</th>
            <th className="text-right py-2 pr-4 font-medium">Qty</th>
            <th className="text-right py-2 pr-4 font-medium">Entry</th>
            <th className="text-right py-2 pr-4 font-medium">Exit</th>
            <th className="text-right py-2 font-medium">PnL</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r) => (
            <tr key={r.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
              <td className="py-2.5 pr-4 font-medium text-white">{r.symbol}</td>
              <td className="py-2.5 pr-4 text-right">
                <span
                  className={`text-xs font-medium px-2 py-0.5 rounded-full ${
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
              <td className={`py-2.5 text-right tabular-nums font-medium ${pnlColor(r.realized_pnl)}`}>
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
    return <div className="text-center py-10 text-zinc-600 text-sm">No journal entries</div>;
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
          className="flex items-start gap-3 px-3 py-2.5 rounded-lg hover:bg-zinc-800/30 transition-colors"
        >
          <span className={`text-xs font-mono mt-0.5 ${typeColor[e.entry_type] ?? "text-zinc-500"}`}>
            {e.entry_type.replace(/_/g, " ").toUpperCase()}
          </span>
          {e.symbol && (
            <span className="text-xs text-zinc-300 font-medium">{e.symbol}</span>
          )}
          <span className="text-xs text-zinc-600 ml-auto tabular-nums">
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

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, pnl, j] = await Promise.all([
        apiFetch<Portfolio>("/trading/portfolio"),
        apiFetch<PnLRecord[]>("/trading/pnl?limit=50"),
        apiFetch<JournalEntry[]>("/trading/journal?limit=50"),
      ]);
      setPortfolio(p);
      setPnlRecords(pnl);
      setJournal(j);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load trading data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = setInterval(() => void load(), 15_000);
    return () => clearInterval(interval);
  }, [load]);

  const tabs: { id: Tab; label: string }[] = [
    { id: "portfolio", label: "Positions" },
    { id: "pnl", label: "PnL History" },
    { id: "journal", label: "Journal" },
  ];

  return (
    <div className="min-h-screen bg-zinc-950 text-white p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-light tracking-wide text-white">Paper Trading</h1>
          <p className="text-zinc-500 text-sm mt-0.5">
            Deterministic simulation — no live orders
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge mode="paper" />
          <button
            onClick={() => void load()}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Error state */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="bg-amber-500/10 border border-amber-500/20 rounded-xl px-4 py-3 text-sm text-amber-400"
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

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Left: Metrics + Order Form */}
        <div className="space-y-4">
          {portfolio ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="grid grid-cols-2 gap-3"
            >
              <MetricCard
                label="Equity"
                value={`$${fmt(portfolio.equity)}`}
                sub="Paper account"
              />
              <MetricCard
                label="Cash"
                value={`$${fmt(portfolio.cash)}`}
              />
              <MetricCard
                label="Total PnL"
                value={`${portfolio.total_pnl >= 0 ? "+" : ""}$${fmt(Math.abs(portfolio.total_pnl))}`}
                accent={portfolio.total_pnl > 0 ? "positive" : portfolio.total_pnl < 0 ? "negative" : "neutral"}
              />
              <MetricCard
                label="Realized"
                value={`${portfolio.realized_pnl >= 0 ? "+" : ""}$${fmt(Math.abs(portfolio.realized_pnl))}`}
                accent={portfolio.realized_pnl > 0 ? "positive" : portfolio.realized_pnl < 0 ? "negative" : "neutral"}
              />
            </motion.div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="h-20 bg-zinc-900/60 border border-zinc-800/60 rounded-xl animate-pulse"
                />
              ))}
            </div>
          )}

          <OrderForm onSuccess={() => void load()} />
        </div>

        {/* Right: Tabs */}
        <div className="xl:col-span-2 bg-zinc-900/40 border border-zinc-800/60 rounded-xl">
          <div className="flex border-b border-zinc-800/60">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-5 py-3 text-sm transition-colors ${
                  tab === t.id
                    ? "text-white border-b border-white"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {t.label}
                {t.id === "portfolio" && portfolio && (
                  <span className="ml-2 text-xs text-zinc-600">
                    {portfolio.position_count}
                  </span>
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
                    <div key={i} className="h-8 bg-zinc-800/50 rounded animate-pulse" />
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
