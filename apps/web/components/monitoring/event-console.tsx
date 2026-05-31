"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Info, Terminal, XCircle, Zap } from "lucide-react";
import { useRef, useState } from "react";
import type { EventSeverity, EventType, LuxEvent } from "@/lib/events/schemas";
import { cn } from "@/lib/utils";

interface EventConsoleProps {
  events: LuxEvent[];
  maxVisible?: number;
  className?: string;
}

const SEVERITY_CONFIG: Record<
  EventSeverity,
  { icon: React.ComponentType<{ className?: string }>; color: string; dot: string }
> = {
  debug: { icon: Info, color: "text-zinc-500", dot: "bg-zinc-500" },
  info: { icon: Info, color: "text-blue-400", dot: "bg-blue-400" },
  warning: { icon: AlertTriangle, color: "text-amber-400", dot: "bg-amber-400" },
  error: { icon: XCircle, color: "text-rose-400", dot: "bg-rose-400" },
  critical: { icon: XCircle, color: "text-rose-300", dot: "bg-rose-300 animate-pulse" },
};

const TYPE_BADGE_COLOR: Partial<Record<EventType, string>> = {
  "graph.node_entered": "bg-violet-500/20 text-violet-300 border-violet-500/30",
  "graph.node_exited": "bg-violet-500/10 text-violet-400 border-violet-500/20",
  "graph.completed": "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  "session.started": "bg-blue-500/20 text-blue-300 border-blue-500/30",
  "session.completed": "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  "session.failed": "bg-rose-500/20 text-rose-300 border-rose-500/30",
  "telemetry.token_usage": "bg-amber-500/20 text-amber-300 border-amber-500/30",
  "telemetry.retry": "bg-orange-500/20 text-orange-300 border-orange-500/30",
  "memory.retrieved": "bg-cyan-500/20 text-cyan-300 border-cyan-500/30",
  "governance.approval_required": "bg-rose-500/20 text-rose-300 border-rose-500/30",
  "governance.kill_switch": "bg-rose-600/30 text-rose-200 border-rose-500/40",
};

function EventRow({ event, index }: { event: LuxEvent; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const config = SEVERITY_CONFIG[event.severity] ?? SEVERITY_CONFIG.info;
  const Icon = config.icon;
  const badgeClass = TYPE_BADGE_COLOR[event.type] ?? "bg-zinc-800 text-zinc-400 border-zinc-700";
  const ts = new Date(event.timestamp).toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  } as Intl.DateTimeFormatOptions);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: index * 0.02 }}
      className={cn(
        "group cursor-pointer border-b border-white/5 transition-colors hover:bg-white/[0.03]",
        event.severity === "critical" && "bg-rose-950/20",
      )}
      onClick={() => {
        setExpanded((p) => !p);
      }}
    >
      <div className="flex items-center gap-3 px-4 py-2">
        {/* Severity dot */}
        <div className={cn("h-1.5 w-1.5 shrink-0 rounded-full", config.dot)} />

        {/* Timestamp */}
        <span className="w-28 shrink-0 font-mono text-[10px] text-zinc-600">{ts}</span>

        {/* Icon */}
        <Icon className={cn("h-3.5 w-3.5 shrink-0", config.color)} />

        {/* Event type badge */}
        <span
          className={cn(
            "shrink-0 rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider",
            badgeClass,
          )}
        >
          {event.type}
        </span>

        {/* Payload preview */}
        <span className="flex-1 truncate text-xs text-zinc-400">
          {Object.entries(event.payload)
            .slice(0, 3)
            .map(([k, v]) => `${k}=${String(v).slice(0, 30)}`)
            .join("  ")}
        </span>
      </div>

      {/* Expanded payload */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <pre className="mx-4 mb-3 overflow-x-auto rounded-md border border-emerald-900/30 bg-black/50 p-3 font-mono text-[10px] text-emerald-300">
              {JSON.stringify(event.payload, null, 2)}
            </pre>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

export function EventConsole({ events, maxVisible = 200, className }: EventConsoleProps) {
  const [filter, setFilter] = useState<EventSeverity | "all">("all");
  const [search, setSearch] = useState("");
  const [paused, setPaused] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const filtered = events
    .filter((e) => filter === "all" || e.severity === filter)
    .filter(
      (e) =>
        !search ||
        e.type.includes(search.toLowerCase()) ||
        JSON.stringify(e.payload).toLowerCase().includes(search.toLowerCase()),
    )
    .slice(0, maxVisible);

  return (
    <div className={cn("flex flex-col rounded-xl border border-white/10 bg-zinc-950", className)}>
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-white/10 px-4 py-3">
        <Terminal className="h-4 w-4 text-emerald-400" />
        <span className="text-sm font-medium text-white">Event Console</span>
        <div className="ml-2 flex items-center gap-1">
          <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
          <span className="text-xs text-zinc-500">{events.length} events</span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {/* Severity filter */}
          <div className="flex items-center gap-1 rounded-md border border-white/10 p-1">
            {(["all", "info", "warning", "error", "critical"] as const).map((s) => (
              <button
                key={s}
                onClick={() => {
                  setFilter(s);
                }}
                className={cn(
                  "rounded px-2 py-0.5 text-xs capitalize transition-colors",
                  filter === s ? "bg-white/10 text-white" : "text-zinc-500 hover:text-zinc-300",
                )}
              >
                {s}
              </button>
            ))}
          </div>

          {/* Search */}
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
            placeholder="Filter events…"
            className="w-40 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-white/20"
          />

          {/* Pause */}
          <button
            onClick={() => {
              setPaused((p) => !p);
            }}
            className={cn(
              "rounded-md border px-2 py-1 text-xs transition-colors",
              paused
                ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
                : "border-white/10 text-zinc-500 hover:text-zinc-300",
            )}
          >
            {paused ? "Resume" : "Pause"}
          </button>
        </div>
      </div>

      {/* Events list */}
      <div ref={containerRef} className="flex-1 overflow-y-auto" style={{ maxHeight: "420px" }}>
        {filtered.length === 0 ? (
          <div className="flex h-32 items-center justify-center text-xs text-zinc-600">
            <Zap className="mr-2 h-4 w-4" />
            Waiting for events…
          </div>
        ) : (
          <AnimatePresence mode="popLayout" initial={false}>
            {filtered.map((ev, i) => (
              <EventRow key={ev.id} event={ev} index={i} />
            ))}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}
