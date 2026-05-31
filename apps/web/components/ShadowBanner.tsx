"use client";

/**
 * Path: apps/web/components/ShadowBanner.tsx
 * Security: Reads shadow status via authenticated API call. Defaults to
 *           showing (fail-safe) if the API is unreachable.
 * Scale: Single component, client-side polling every 60s. No WebSocket needed.
 *
 * CLAUDE.md requirement: "A persistent UI banner is displayed at all times
 * while shadow mode is active — it cannot be dismissed by the user."
 */

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { createClient } from "@supabase/supabase-js";
import { Eye, TrendingUp, TrendingDown, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

interface ShadowSummary {
  is_active: boolean;
  activated_at: string | null;
  days_active: number | null;
  gate_passed: boolean;
  total_shadow_pnl: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  hit_rate_pct: number;
}

const DEFAULT_SUMMARY: ShadowSummary = {
  is_active: true,
  activated_at: null,
  days_active: null,
  gate_passed: false,
  total_shadow_pnl: 0,
  total_trades: 0,
  winning_trades: 0,
  losing_trades: 0,
  hit_rate_pct: 0,
};

const POLL_INTERVAL_MS = 60_000;
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function formatPnl(pnl: number): string {
  const sign = pnl >= 0 ? "+" : "";
  return `${sign}$${Math.abs(pnl).toFixed(2)}`;
}

function PnlPill({ pnl }: { pnl: number }) {
  const isPositive = pnl >= 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 font-mono text-xs font-semibold tabular-nums",
        isPositive ? "text-emerald-400" : "text-rose-400",
      )}
    >
      {isPositive ? (
        <TrendingUp className="h-3 w-3 shrink-0" strokeWidth={1.5} />
      ) : (
        <TrendingDown className="h-3 w-3 shrink-0" strokeWidth={1.5} />
      )}
      {formatPnl(pnl)}
    </span>
  );
}

export function ShadowBanner() {
  const [summary, setSummary] = useState<ShadowSummary>(DEFAULT_SUMMARY);
  const [loaded, setLoaded] = useState(false);

  async function fetchStatus() {
    try {
      // Obtain the Supabase session token for authenticated API call.
      const supabase = createClient(
        process.env.NEXT_PUBLIC_SUPABASE_URL!,
        process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      );
      const { data: sessionData } = await supabase.auth.getSession();
      const token = sessionData?.session?.access_token;

      const headers: HeadersInit = { "Content-Type": "application/json" };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      const res = await fetch(`${API_BASE}/api/v1/trading/shadow-status`, {
        headers,
        signal: AbortSignal.timeout(5_000),
      });

      if (res.ok) {
        const data: ShadowSummary = await res.json();
        setSummary(data);
      }
      // Non-OK responses: keep previous state (fail-safe — show banner)
    } catch {
      // Network error or timeout: keep showing banner (fail-safe)
    } finally {
      setLoaded(true);
    }
  }

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  // Always render during SSR/loading — fail-safe: show banner until confirmed inactive
  if (loaded && !summary.is_active) return null;

  return (
    <AnimatePresence>
      <motion.div
        key="shadow-banner"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
        className={cn("relative z-30 w-full shrink-0", "border-b border-amber-900/40 bg-[#0f0c00]")}
        aria-live="polite"
        role="status"
      >
        <div className="mx-auto flex max-w-none items-center justify-between gap-4 px-4 py-2 md:px-6">
          {/* Left: mode indicator */}
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="relative flex h-2 w-2 shrink-0">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-500 opacity-50" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
            </span>
            <div className="flex min-w-0 items-center gap-2">
              <Eye className="h-3.5 w-3.5 shrink-0 text-amber-500" strokeWidth={1.5} />
              <span className="whitespace-nowrap text-[11px] font-semibold uppercase tracking-widest text-amber-500">
                Shadow Mode
              </span>
              <span className="hidden whitespace-nowrap text-[11px] text-amber-700 sm:inline">
                — No orders executing
              </span>
            </div>
          </div>

          {/* Center: stats */}
          <div className="hidden items-center gap-4 md:flex">
            {summary.total_trades > 0 && (
              <>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] uppercase tracking-wider text-zinc-600">
                    Shadow P&amp;L
                  </span>
                  <PnlPill pnl={summary.total_shadow_pnl} />
                </div>

                <div className="h-3 w-px bg-white/5" />

                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] uppercase tracking-wider text-zinc-600">
                    Signals
                  </span>
                  <span className="font-mono text-xs tabular-nums text-zinc-400">
                    {summary.total_trades}
                  </span>
                </div>

                <div className="h-3 w-px bg-white/5" />

                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] uppercase tracking-wider text-zinc-600">
                    Hit Rate
                  </span>
                  <span
                    className={cn(
                      "font-mono text-xs font-semibold tabular-nums",
                      summary.hit_rate_pct >= 50 ? "text-emerald-400" : "text-rose-400",
                    )}
                  >
                    {summary.hit_rate_pct.toFixed(1)}%
                  </span>
                </div>
              </>
            )}
          </div>

          {/* Right: days counter */}
          <div className="flex shrink-0 items-center gap-1.5">
            <Clock className="h-3 w-3 text-zinc-600" strokeWidth={1.5} />
            {summary.days_active !== null ? (
              <span className="text-[10px] tabular-nums text-zinc-600">
                Day{" "}
                <span className="font-mono font-semibold text-zinc-400">{summary.days_active}</span>{" "}
                <span className="hidden sm:inline">of 14 min</span>
              </span>
            ) : (
              <span className="text-[10px] text-zinc-700">Pending start</span>
            )}
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
