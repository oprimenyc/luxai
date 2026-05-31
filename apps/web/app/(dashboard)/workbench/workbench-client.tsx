"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  Calendar,
  ChevronDown,
  TrendingDown,
  TrendingUp,
  X,
  ScanSearch,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ContractRec {
  symbol: string;
  underlying: string;
  option_type: string;
  strike: number;
  expiration: string;
  bid: number;
  ask: number;
  mid: number;
  open_interest: number;
  dte: number;
  greeks: { delta?: number; gamma?: number; theta?: number; vega?: number; iv?: number };
  score: number;
  score_breakdown: Record<string, number>;
  estimated_cost_usd: number;
  within_budget: boolean;
  max_loss: number;
  max_profit: number;
  breakeven: number;
  risk_reward_note: string;
}

interface SpreadRec {
  long_strike: number;
  short_strike: number;
  long_symbol: string;
  short_symbol: string;
  option_type: string;
  net_debit: number;
  max_profit: number;
  max_loss: number;
  breakeven: number;
  risk_reward_ratio: number;
  score: number;
  within_budget: boolean;
}

interface MacroEvent {
  name: string;
  event_date: string;
  risk_level: "low" | "medium" | "high";
  days_away: number;
}

interface WorkbenchResult {
  symbol: string;
  direction: string;
  expiration: string;
  underlying_price: number;
  budget_usd: number;
  account_tier: string;
  best_value: ContractRec | null;
  best_probability: ContractRec | null;
  spread_version: SpreadRec | null;
  budget_exceeded: boolean;
  budget_note: string;
  macro_events: MacroEvent[];
  earnings_warning: boolean;
  earnings_date: string | null;
  verdict: "accept" | "caution" | "reject";
  verdict_rationale: string;
  analyzed_at: string;
  tradier_sandbox: boolean;
}

// ── Score Ring (SVG animated) ─────────────────────────────────────────────────

function ScoreRing({ score }: { score: number }) {
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const pct = score / 10;
  const offset = circumference * (1 - pct);

  const color = score >= 7 ? "#22c55e" : score >= 5 ? "#f59e0b" : "#ef4444";

  return (
    <div className="relative flex h-24 w-24 items-center justify-center">
      <svg className="absolute inset-0 -rotate-90" viewBox="0 0 88 88">
        {/* Track */}
        <circle
          cx="44"
          cy="44"
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth="6"
        />
        {/* Progress */}
        <motion.circle
          cx="44"
          cy="44"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1.2, ease: "easeOut", delay: 0.2 }}
        />
      </svg>
      <motion.div
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.5, duration: 0.3 }}
        className="flex flex-col items-center"
      >
        <span className="text-2xl font-bold tabular-nums" style={{ color }}>
          {score.toFixed(1)}
        </span>
        <span className="text-[9px] font-semibold uppercase tracking-widest text-zinc-600">
          /10
        </span>
      </motion.div>
    </div>
  );
}

// ── Score breakdown bars ──────────────────────────────────────────────────────

const FACTOR_LABELS: Record<string, string> = {
  liquidity: "Liquidity",
  spread: "Spread",
  delta: "Delta",
  iv: "IV",
  dte: "DTE",
};

function ScoreBreakdown({ breakdown }: { breakdown: Record<string, number> }) {
  return (
    <div className="mt-3 space-y-1.5">
      {Object.entries(breakdown).map(([key, val]) => (
        <div key={key} className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-[10px] text-zinc-600">
            {FACTOR_LABELS[key] ?? key}
          </span>
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/5">
            <motion.div
              className="h-full rounded-full bg-white/30"
              initial={{ width: 0 }}
              animate={{ width: `${val * 100}%` }}
              transition={{ duration: 0.8, ease: "easeOut", delay: 0.1 }}
            />
          </div>
          <span className="w-6 text-right text-[10px] tabular-nums text-zinc-500">
            {(val * 100).toFixed(0)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Verdict chip ──────────────────────────────────────────────────────────────

function VerdictChip({
  verdict,
  rationale,
}: {
  verdict: WorkbenchResult["verdict"];
  rationale: string;
}) {
  const styles = {
    accept: {
      bg: "bg-emerald-950/40 border-emerald-800/50",
      text: "text-emerald-400",
      label: "Accept",
    },
    caution: {
      bg: "bg-amber-950/40 border-amber-800/50",
      text: "text-amber-400",
      label: "Caution",
    },
    reject: { bg: "bg-red-950/40 border-red-800/50", text: "text-red-400", label: "Reject" },
  }[verdict];

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("rounded-xl border px-4 py-3", styles.bg)}
    >
      <div className="mb-1 flex items-center gap-2">
        <span className={cn("text-xs font-bold uppercase tracking-widest", styles.text)}>
          {styles.label}
        </span>
      </div>
      <p className="text-[11px] leading-relaxed text-zinc-500">{rationale}</p>
    </motion.div>
  );
}

// ── Contract card ─────────────────────────────────────────────────────────────

function ContractCard({
  label,
  rec,
  budgetUsd,
  delay,
}: {
  label: string;
  rec: ContractRec;
  budgetUsd: number;
  delay: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const cost = rec.estimated_cost_usd;
  const budgetPct = Math.min((cost / budgetUsd) * 100, 120);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay, ease: "easeOut" }}
      className="overflow-hidden rounded-2xl border border-white/[0.06] bg-zinc-900/60"
    >
      {/* Header */}
      <div className="px-5 pb-4 pt-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
              {label}
            </p>
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-lg font-bold text-white">
                ${rec.strike.toFixed(0)}{" "}
                <span className="text-sm font-medium text-zinc-400">
                  {rec.option_type.toUpperCase()}
                </span>
              </span>
              <span className="text-xs text-zinc-600">{rec.expiration}</span>
              <span className="text-xs text-zinc-600">{rec.dte}d</span>
            </div>
            <p className="mt-0.5 font-mono text-xs text-zinc-500">{rec.symbol}</p>
          </div>
          <ScoreRing score={rec.score} />
        </div>

        {/* Greeks row */}
        <div className="mt-4 grid grid-cols-4 gap-2">
          {[
            { label: "Delta", val: rec.greeks.delta },
            {
              label: "IV",
              val: rec.greeks.iv != null ? `${(rec.greeks.iv * 100).toFixed(0)}%` : null,
            },
            { label: "Theta", val: rec.greeks.theta },
            { label: "OI", val: rec.open_interest.toLocaleString() },
          ].map(({ label: l, val }) => (
            <div
              key={l}
              className="flex flex-col items-center rounded-lg bg-white/[0.03] px-1 py-2"
            >
              <span className="mb-0.5 text-[9px] uppercase tracking-widest text-zinc-700">{l}</span>
              <span className="text-xs font-semibold tabular-nums text-zinc-300">
                {val != null ? (typeof val === "number" ? val.toFixed(3) : val) : "—"}
              </span>
            </div>
          ))}
        </div>

        {/* Budget bar */}
        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[10px] text-zinc-600">Cost vs budget</span>
            <span
              className={cn(
                "text-xs font-semibold tabular-nums",
                rec.within_budget ? "text-emerald-400" : "text-red-400",
              )}
            >
              ${cost.toFixed(2)} / ${budgetUsd.toFixed(0)}
            </span>
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-white/5">
            <motion.div
              className={cn(
                "h-full rounded-full",
                rec.within_budget ? "bg-emerald-500" : "bg-red-500",
              )}
              initial={{ width: 0 }}
              animate={{ width: `${Math.min(budgetPct, 100)}%` }}
              transition={{ duration: 0.8, ease: "easeOut", delay: delay + 0.2 }}
            />
          </div>
        </div>
      </div>

      {/* Footer: key stats */}
      <div className="grid grid-cols-3 gap-3 border-t border-white/[0.05] px-5 py-3 text-center">
        {[
          { label: "Max loss", val: `$${rec.max_loss.toFixed(2)}` },
          { label: "Breakeven", val: `$${rec.breakeven.toFixed(2)}` },
          { label: "OI", val: rec.open_interest.toLocaleString() },
        ].map(({ label: l, val }) => (
          <div key={l}>
            <p className="mb-0.5 text-[9px] uppercase tracking-widest text-zinc-700">{l}</p>
            <p className="text-xs font-semibold tabular-nums text-zinc-300">{val}</p>
          </div>
        ))}
      </div>

      {/* Expandable: score breakdown */}
      <button
        onClick={() => {
          setExpanded(!expanded);
        }}
        className="flex w-full items-center justify-between border-t border-white/[0.05] px-5 py-2.5 text-[10px] text-zinc-600 transition-colors hover:text-zinc-400"
      >
        <span>Score breakdown</span>
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")} />
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: "auto" }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-4">
              <ScoreBreakdown breakdown={rec.score_breakdown} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ── Spread card ────────────────────────────────────────────────────────────────

function SpreadCard({
  spread,
  budgetUsd: _budgetUsd,
  delay,
}: {
  spread: SpreadRec;
  budgetUsd: number;
  delay: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay, ease: "easeOut" }}
      className="overflow-hidden rounded-2xl border border-white/[0.06] bg-zinc-900/60"
    >
      <div className="px-5 pb-4 pt-5">
        <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
          Spread Version
        </p>
        {/* Leg visualizer */}
        <div className="mb-4 flex items-center gap-2">
          <div className="flex-1 rounded-lg border border-emerald-900/40 bg-emerald-950/30 px-3 py-2 text-center">
            <p className="mb-0.5 text-[9px] uppercase tracking-wider text-emerald-700">Long</p>
            <p className="text-sm font-bold text-emerald-400">${spread.long_strike}</p>
            <p className="mt-0.5 truncate font-mono text-[9px] text-zinc-600">
              {spread.long_symbol}
            </p>
          </div>
          <ArrowRight className="h-4 w-4 shrink-0 text-zinc-700" />
          <div className="flex-1 rounded-lg border border-red-900/40 bg-red-950/30 px-3 py-2 text-center">
            <p className="mb-0.5 text-[9px] uppercase tracking-wider text-red-700">Short</p>
            <p className="text-sm font-bold text-red-400">${spread.short_strike}</p>
            <p className="mt-0.5 truncate font-mono text-[9px] text-zinc-600">
              {spread.short_symbol}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          {[
            { label: "Net debit", val: `$${spread.net_debit.toFixed(2)}` },
            { label: "Max profit", val: `$${spread.max_profit.toFixed(2)}` },
            { label: "Max loss", val: `$${spread.max_loss.toFixed(2)}` },
            { label: "R:R", val: `${spread.risk_reward_ratio.toFixed(2)}×` },
          ].map(({ label: l, val }) => (
            <div key={l} className="flex flex-col rounded-lg bg-white/[0.03] px-3 py-2">
              <span className="mb-0.5 text-[9px] uppercase tracking-widest text-zinc-700">{l}</span>
              <span className="text-xs font-semibold tabular-nums text-zinc-300">{val}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-white/[0.05] px-5 py-3">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-zinc-600">Breakeven</span>
          <span className="text-xs font-semibold tabular-nums text-zinc-300">
            ${spread.breakeven.toFixed(2)}
          </span>
        </div>
        <span
          className={cn(
            "text-[10px] font-semibold uppercase tracking-widest",
            spread.within_budget ? "text-emerald-400" : "text-red-400",
          )}
        >
          {spread.within_budget ? "Within budget" : "Over budget"}
        </span>
      </div>
    </motion.div>
  );
}

// ── Macro warning banner ──────────────────────────────────────────────────────

function MacroWarningBanner({
  events,
  earningsWarning,
  earningsDate,
  symbol,
}: {
  events: MacroEvent[];
  earningsWarning: boolean;
  earningsDate: string | null;
  symbol: string;
}) {
  const hasWarnings = events.length > 0 || earningsWarning;
  if (!hasWarnings) return null;

  const highRisk = events.filter((e) => e.risk_level === "high");

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-amber-800/40 bg-amber-950/30 px-4 py-3"
    >
      <div className="flex items-start gap-2.5">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        <div className="min-w-0">
          <p className="mb-1 text-xs font-semibold text-amber-400">
            Calendar risk within expiration window
          </p>
          <ul className="space-y-0.5">
            {earningsWarning && (
              <li className="text-[11px] text-amber-600/80">
                {symbol} earnings {earningsDate ? `on ${earningsDate}` : "expected"} — IV spike risk
              </li>
            )}
            {highRisk.slice(0, 3).map((e) => (
              <li key={e.name + e.event_date} className="text-[11px] text-amber-600/80">
                {e.name} — {e.event_date} ({e.days_away}d away)
              </li>
            ))}
            {events
              .filter((e) => e.risk_level !== "high")
              .slice(0, 2)
              .map((e) => (
                <li key={e.name + e.event_date} className="text-[11px] text-zinc-600">
                  {e.name} — {e.event_date}
                </li>
              ))}
          </ul>
        </div>
      </div>
    </motion.div>
  );
}

// ── Form ──────────────────────────────────────────────────────────────────────

function WorkbenchForm({
  onSubmit,
  loading,
}: {
  onSubmit: (data: {
    symbol: string;
    direction: "bullish" | "bearish";
    expiration: string;
    budget_usd: number;
    account_size_usd: number;
  }) => void;
  loading: boolean;
}) {
  const [symbol, setSymbol] = useState("");
  const [direction, setDirection] = useState<"bullish" | "bearish">("bullish");
  const [expiration, setExpiration] = useState("");
  const [budget, setBudget] = useState("");
  const [accountSize, setAccountSize] = useState("");

  const canSubmit =
    symbol.trim() && expiration && Number(budget) > 0 && Number(accountSize) > 0 && !loading;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      symbol: symbol.trim().toUpperCase(),
      direction,
      expiration,
      budget_usd: Number(budget),
      account_size_usd: Number(accountSize),
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Symbol + Direction */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-2 block text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
            Symbol
          </label>
          <input
            value={symbol}
            onChange={(e) => {
              setSymbol(e.target.value.toUpperCase());
            }}
            placeholder="AAPL"
            maxLength={10}
            className="min-h-[44px] w-full rounded-lg border border-white/[0.07] bg-white/[0.04] px-3 py-2.5 font-mono text-sm text-white transition-colors placeholder:text-zinc-700 focus:border-white/20 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-2 block text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
            Direction
          </label>
          <div className="grid min-h-[44px] grid-cols-2 gap-1.5">
            {(["bullish", "bearish"] as const).map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => {
                  setDirection(d);
                }}
                className={cn(
                  "flex min-h-[44px] items-center justify-center gap-1.5 rounded-lg border text-xs font-semibold transition-all",
                  direction === d
                    ? d === "bullish"
                      ? "border-emerald-700/60 bg-emerald-950/50 text-emerald-400"
                      : "border-red-700/60 bg-red-950/50 text-red-400"
                    : "border-white/[0.07] bg-white/[0.03] text-zinc-600 hover:text-zinc-400",
                )}
              >
                {d === "bullish" ? (
                  <TrendingUp className="h-3.5 w-3.5" />
                ) : (
                  <TrendingDown className="h-3.5 w-3.5" />
                )}
                {d === "bullish" ? "Bull" : "Bear"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Expiration */}
      <div>
        <label className="mb-2 block text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
          Target Expiration
        </label>
        <div className="relative">
          <Calendar className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-600" />
          <input
            type="date"
            value={expiration}
            onChange={(e) => {
              setExpiration(e.target.value);
            }}
            className="min-h-[44px] w-full rounded-lg border border-white/[0.07] bg-white/[0.04] py-2.5 pl-9 pr-3 text-sm text-white transition-colors [color-scheme:dark] focus:border-white/20 focus:outline-none"
          />
        </div>
      </div>

      {/* Budget + Account size */}
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: "Budget (USD)", val: budget, set: setBudget, placeholder: "50" },
          { label: "Account size", val: accountSize, set: setAccountSize, placeholder: "500" },
        ].map(({ label: l, val, set, placeholder }) => (
          <div key={l}>
            <label className="mb-2 block text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
              {l}
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-zinc-600">
                $
              </span>
              <input
                type="number"
                min="1"
                value={val}
                onChange={(e) => {
                  set(e.target.value);
                }}
                placeholder={placeholder}
                className="min-h-[44px] w-full rounded-lg border border-white/[0.07] bg-white/[0.04] py-2.5 pl-6 pr-3 text-sm tabular-nums text-white transition-colors placeholder:text-zinc-700 focus:border-white/20 focus:outline-none"
              />
            </div>
          </div>
        ))}
      </div>

      {/* Submit */}
      <button
        type="submit"
        disabled={!canSubmit}
        className={cn(
          "flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl py-3.5 text-sm font-semibold transition-all",
          canSubmit
            ? "bg-white text-zinc-950 hover:bg-zinc-100"
            : "cursor-not-allowed bg-white/5 text-zinc-700",
        )}
      >
        {loading ? (
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
            className="h-4 w-4 rounded-full border-2 border-zinc-700 border-t-white"
          />
        ) : (
          <>
            <ScanSearch className="h-4 w-4" />
            Analyze trade idea
          </>
        )}
      </button>
    </form>
  );
}

// ── Main client ───────────────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function WorkbenchClient() {
  const [result, setResult] = useState<WorkbenchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (data: {
    symbol: string;
    direction: "bullish" | "bearish";
    expiration: string;
    budget_usd: number;
    account_size_usd: number;
  }) => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const resp = await fetch(`${API_BASE}/api/v1/workbench/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(data),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail ?? "Analysis failed");
      }

      const json: WorkbenchResult = await resp.json();
      setResult(json);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unexpected error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">Trade Idea Workbench</h1>
        <p className="mt-1 text-xs text-zinc-600">
          Enter any tip. Get three risk-scored, budget-aware options alternatives.
        </p>
      </div>

      {/* Sandbox notice */}
      {result?.tradier_sandbox && (
        <div className="rounded-lg border border-violet-900/40 bg-violet-950/20 px-3 py-2 text-[10px] text-violet-500">
          Tradier sandbox active — data is simulated. Set TRADIER_SANDBOX=false for live chains.
        </div>
      )}

      {/* Input form */}
      <div className="rounded-2xl border border-white/[0.06] bg-zinc-900/60 p-5">
        <WorkbenchForm
          onSubmit={(d) => {
            void handleSubmit(d);
          }}
          loading={loading}
        />
      </div>

      {/* Error */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="flex items-start gap-2.5 rounded-xl border border-red-900/40 bg-red-950/20 px-4 py-3"
          >
            <X className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
            <p className="text-xs text-red-400">{error}</p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Results */}
      <AnimatePresence>
        {result && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
            {/* Meta row */}
            <div className="flex items-center justify-between text-[10px] text-zinc-700">
              <span>
                {result.symbol} · ${result.underlying_price} · {result.account_tier} tier
              </span>
              <span>{new Date(result.analyzed_at).toLocaleTimeString()}</span>
            </div>

            {/* Verdict */}
            <VerdictChip verdict={result.verdict} rationale={result.verdict_rationale} />

            {/* Budget exceeded note */}
            {result.budget_exceeded && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="rounded-lg border border-amber-900/30 bg-amber-950/20 px-3 py-2 text-[11px] text-amber-600"
              >
                {result.budget_note}
              </motion.div>
            )}

            {/* Macro calendar warning */}
            <MacroWarningBanner
              events={result.macro_events}
              earningsWarning={result.earnings_warning}
              earningsDate={result.earnings_date}
              symbol={result.symbol}
            />

            {/* Contract cards — staggered reveal */}
            {result.best_value && (
              <ContractCard
                label="Best Value"
                rec={result.best_value}
                budgetUsd={result.budget_usd}
                delay={0.1}
              />
            )}
            {result.best_probability && (
              <ContractCard
                label="Best Probability"
                rec={result.best_probability}
                budgetUsd={result.budget_usd}
                delay={0.25}
              />
            )}
            {result.spread_version && (
              <SpreadCard
                spread={result.spread_version}
                budgetUsd={result.budget_usd}
                delay={0.4}
              />
            )}

            {/* Empty state */}
            {!result.best_value && !result.best_probability && !result.spread_version && (
              <div className="rounded-2xl border border-white/[0.06] bg-zinc-900/60 px-5 py-8 text-center">
                <p className="text-sm text-zinc-600">
                  No valid contracts found for these parameters.
                </p>
                <p className="mt-1 text-xs text-zinc-700">
                  Try a different expiration, higher budget, or check the symbol.
                </p>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
