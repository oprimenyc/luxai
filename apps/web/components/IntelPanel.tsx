"use client";

import { motion, AnimatePresence } from "framer-motion";
import { Activity, Brain, Database, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type Regime = "TRENDING_UP" | "TRENDING_DOWN" | "CHOPPY" | "HIGH_VOL" | "RISK_OFF";
type Verdict = "BULLISH" | "BEARISH" | "NEUTRAL";

interface ScannerSignal {
  symbol: string;
  verdict: Verdict;
  confidence: number;
  score: number;
}

interface IntelState {
  regime: Regime | null;
  regime_detail: Record<string, number>;
  scanner_ran_at: string | null;
  signals_total: number;
  signals_approved: number;
  signals_rejected: number;
  top_signal: ScannerSignal | null;
  weekly_win_rate: number | null;
  data_sources: string[];
  last_updated: string | null;
}

interface IntelPanelProps {
  className?: string;
}

// ── Regime config ─────────────────────────────────────────────────────────────

const REGIME_CONFIG: Record<Regime, { label: string; color: string; icon: typeof Activity }> = {
  TRENDING_UP: { label: "Trending Up", color: "text-emerald-400", icon: TrendingUp },
  TRENDING_DOWN: { label: "Trending Down", color: "text-rose-400", icon: TrendingDown },
  CHOPPY: { label: "Choppy", color: "text-amber-400", icon: Minus },
  HIGH_VOL: { label: "High Vol", color: "text-orange-400", icon: Activity },
  RISK_OFF: { label: "Risk Off", color: "text-rose-500", icon: TrendingDown },
};

const VERDICT_CONFIG: Record<Verdict, { color: string }> = {
  BULLISH: { color: "text-emerald-400" },
  BEARISH: { color: "text-rose-400" },
  NEUTRAL: { color: "text-zinc-400" },
};

// ── Component ─────────────────────────────────────────────────────────────────

export function IntelPanel({ className }: IntelPanelProps) {
  const [intel, setIntel] = useState<IntelState>({
    regime: null,
    regime_detail: {},
    scanner_ran_at: null,
    signals_total: 0,
    signals_approved: 0,
    signals_rejected: 0,
    top_signal: null,
    weekly_win_rate: null,
    data_sources: ["yfinance", "Tradier"],
    last_updated: null,
  });

  // Listen for intel events via the existing WebSocket connection
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string);
        if (msg.type === "intel_update") {
          setIntel((prev) => ({ ...prev, ...msg.payload, last_updated: new Date().toISOString() }));
        }
      } catch {
        // non-JSON message — ignore
      }
    };

    // Attach to the page-level WebSocket if available
    const ws = (window as unknown as Record<string, unknown>).__luxai_ws as WebSocket | undefined;
    ws?.addEventListener("message", handler);
    return () => ws?.removeEventListener("message", handler);
  }, []);

  const regime = intel.regime ? REGIME_CONFIG[intel.regime] : null;
  const RegimeIcon = regime?.icon ?? Activity;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className={cn(
        "space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/60 p-4 backdrop-blur-sm",
        className,
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-zinc-400" strokeWidth={1.5} />
          <span className="font-mono text-xs uppercase tracking-widest text-zinc-300">Intel</span>
        </div>
        {intel.last_updated && (
          <span className="font-mono text-[10px] text-zinc-600">
            {new Date(intel.last_updated).toLocaleTimeString()}
          </span>
        )}
      </div>

      {/* Regime */}
      <Row label="Regime">
        <AnimatePresence mode="wait">
          {intel.regime ? (
            <motion.span
              key={intel.regime}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className={cn("flex items-center gap-1 font-mono text-xs", regime?.color)}
            >
              <RegimeIcon className="h-3 w-3" strokeWidth={1.5} />
              {regime?.label}
            </motion.span>
          ) : (
            <Skeleton />
          )}
        </AnimatePresence>
      </Row>

      {/* Scanner */}
      <Row label="Scanner">
        <span className="font-mono text-xs text-zinc-300">
          {intel.scanner_ran_at
            ? `ran ${_relativeTime(intel.scanner_ran_at)} · ${intel.signals_total} signals`
            : "—"}
        </span>
      </Row>

      {/* Agent debate */}
      <Row label="Debates">
        <span className="font-mono text-xs text-zinc-300">
          {intel.signals_total > 0
            ? `${intel.signals_approved} approved · ${intel.signals_rejected} rejected`
            : "—"}
        </span>
      </Row>

      {/* Top signal */}
      <Row label="Top signal">
        <AnimatePresence mode="wait">
          {intel.top_signal ? (
            <motion.div
              key={intel.top_signal.symbol}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-2"
            >
              <span className="font-mono text-xs text-zinc-200">{intel.top_signal.symbol}</span>
              <span
                className={cn(
                  "font-mono text-[10px]",
                  VERDICT_CONFIG[intel.top_signal.verdict].color,
                )}
              >
                {intel.top_signal.verdict}
              </span>
              <span className="font-mono text-[10px] text-zinc-500">
                {Math.round(intel.top_signal.confidence * 100)}%
              </span>
            </motion.div>
          ) : (
            <span className="font-mono text-xs text-zinc-600">—</span>
          )}
        </AnimatePresence>
      </Row>

      {/* Win rate */}
      <Row label="Win rate">
        <span className="font-mono text-xs text-zinc-300">
          {intel.weekly_win_rate !== null
            ? `${Math.round(intel.weekly_win_rate * 100)}% (7d)`
            : "—"}
        </span>
      </Row>

      {/* Data sources */}
      <div className="border-t border-zinc-800/60 pt-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Database className="h-3 w-3 text-zinc-600" strokeWidth={1.5} />
          {intel.data_sources.map((src) => (
            <span key={src} className="font-mono text-[10px] text-zinc-600">
              {src}
            </span>
          ))}
          <span className="ml-auto font-mono text-[10px] text-zinc-700">all free</span>
        </div>
      </div>
    </motion.div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-zinc-600">
        {label}
      </span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function Skeleton() {
  return <div className="h-3 w-20 animate-pulse rounded bg-zinc-800" />;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _relativeTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    return `${hrs}h ago`;
  } catch {
    return "—";
  }
}
