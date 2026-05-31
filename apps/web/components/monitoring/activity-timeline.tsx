"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Brain, CheckCircle, Clock, GitBranch, Shield, Zap } from "lucide-react";
import type { EventType, LuxEvent } from "@/lib/events/schemas";
import { cn } from "@/lib/utils";

interface ActivityTimelineProps {
  events: LuxEvent[];
  maxItems?: number;
  className?: string;
}

const EVENT_ICONS: Partial<Record<EventType, React.ComponentType<{ className?: string }>>> = {
  "session.started": Zap,
  "session.completed": CheckCircle,
  "graph.node_entered": GitBranch,
  "graph.node_exited": GitBranch,
  "memory.retrieved": Brain,
  "governance.approval_required": Shield,
  "telemetry.retry": Clock,
};

const EVENT_COLORS: Partial<Record<EventType, string>> = {
  "session.started": "text-blue-400 bg-blue-950/40 border-blue-800/30",
  "session.completed": "text-emerald-400 bg-emerald-950/40 border-emerald-800/30",
  "session.failed": "text-rose-400 bg-rose-950/40 border-rose-800/30",
  "graph.node_entered": "text-violet-400 bg-violet-950/40 border-violet-800/30",
  "graph.node_exited": "text-violet-300 bg-violet-950/20 border-violet-800/20",
  "graph.completed": "text-emerald-300 bg-emerald-950/40 border-emerald-800/30",
  "memory.retrieved": "text-cyan-400 bg-cyan-950/40 border-cyan-800/30",
  "governance.approval_required": "text-rose-400 bg-rose-950/40 border-rose-800/30",
  "telemetry.retry": "text-amber-400 bg-amber-950/40 border-amber-800/30",
};

function formatTime(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function getEventSummary(event: LuxEvent): string {
  const p = event.payload;
  switch (event.type) {
    case "graph.node_entered":
      return `Entered ${p.node_name} (iteration ${p.iteration})`;
    case "graph.node_exited":
      return `Exited ${p.node_name} in ${p.duration_ms}ms`;
    case "session.started":
      return `Session ${String(event.session_id).slice(0, 8)}… started`;
    case "session.completed":
      return `Session completed`;
    case "telemetry.token_usage":
      return `${p.model}: ${p.input_tokens}↑ ${p.output_tokens}↓ tokens`;
    case "memory.retrieved":
      return `Retrieved ${Array.isArray(p.memory_ids) ? p.memory_ids.length : 1} memories`;
    case "governance.approval_required":
      return `Approval required — risk: ${p.risk_level}`;
    case "telemetry.retry":
      return `Retry attempt ${p.attempt}/${p.max_attempts}`;
    default:
      return event.type;
  }
}

export function ActivityTimeline({ events, maxItems = 30, className }: ActivityTimelineProps) {
  const significantEvents = events
    .filter((e) => {
      const skip = new Set(["system.heartbeat", "system.error"]);
      return !skip.has(e.type);
    })
    .slice(0, maxItems);

  return (
    <div className={cn("rounded-xl border border-white/10 bg-zinc-950 p-4", className)}>
      <div className="mb-4 flex items-center justify-between">
        <span className="text-sm font-semibold text-white">Activity Timeline</span>
        <span className="text-xs text-zinc-600">{significantEvents.length} events</span>
      </div>

      <div className="relative">
        {/* Vertical line */}
        <div className="absolute bottom-0 left-5 top-0 w-px bg-white/5" />

        <div className="space-y-1">
          <AnimatePresence mode="popLayout" initial={false}>
            {significantEvents.map((event) => {
              const Icon = EVENT_ICONS[event.type] ?? Zap;
              const colorClass =
                EVENT_COLORS[event.type] ?? "text-zinc-400 bg-zinc-900 border-zinc-800";

              return (
                <motion.div
                  key={event.id}
                  layout
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 10 }}
                  transition={{ duration: 0.2 }}
                  className="flex items-start gap-3 py-1"
                >
                  {/* Icon */}
                  <div
                    className={cn(
                      "relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border",
                      colorClass,
                    )}
                  >
                    <Icon className="h-3 w-3" />
                  </div>

                  {/* Content */}
                  <div className="min-w-0 flex-1 pb-1">
                    <p className="truncate text-xs text-zinc-300">{getEventSummary(event)}</p>
                    <p className="mt-0.5 text-[10px] text-zinc-700">
                      {formatTime(event.timestamp)}
                    </p>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>

          {significantEvents.length === 0 && (
            <div className="ml-8 flex h-24 items-center justify-center text-xs text-zinc-700">
              No activity yet
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
