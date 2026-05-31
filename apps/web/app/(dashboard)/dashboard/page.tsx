"use client";

import { motion } from "framer-motion";
import { Activity, Bot, GitBranch, Shield, TrendingUp, Zap } from "lucide-react";
import Link from "next/link";
import { useEventStream, useTokenMetrics } from "@/lib/websocket/hooks";
import { ConnectionIndicator } from "@/components/monitoring/connection-indicator";
import { cn } from "@/lib/utils";

const QUICK_ACTIONS = [
  {
    label: "Monitoring",
    desc: "Live orchestration view",
    icon: Activity,
    href: "/monitoring",
    accent: "from-violet-600/20 to-violet-800/10 border-violet-700/30",
  },
  {
    label: "Memory",
    desc: "Semantic memory store",
    icon: Zap,
    href: "/memory",
    accent: "from-cyan-600/20 to-cyan-800/10 border-cyan-700/30",
  },
  {
    label: "Workflows",
    desc: "Autonomous pipelines",
    icon: GitBranch,
    href: "/workflows",
    accent: "from-blue-600/20 to-blue-800/10 border-blue-700/30",
  },
  {
    label: "Governance",
    desc: "Risk & approvals",
    icon: Shield,
    href: "/governance",
    accent: "from-amber-600/20 to-amber-800/10 border-amber-700/30",
  },
];

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  accent,
  delay,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | number;
  sub?: string;
  accent: string;
  delay: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.3 }}
      className="rounded-xl border border-white/10 bg-zinc-950 p-5"
    >
      <div className="mb-4 flex items-center gap-2">
        <div className={cn("flex h-8 w-8 items-center justify-center rounded-lg", accent)}>
          <Icon className="h-4 w-4" />
        </div>
        <span className="text-sm text-zinc-500">{label}</span>
      </div>
      <p className="text-3xl font-bold tracking-tight text-white">{value}</p>
      {sub && <p className="mt-1 text-xs text-zinc-600">{sub}</p>}
    </motion.div>
  );
}

export default function DashboardPage() {
  const { events, connectionState } = useEventStream({ enabled: true, maxEvents: 200 });
  const tokenMetrics = useTokenMetrics(events);

  const sessionCount = events.filter((e) => e.type === "session.started").length;
  const completedCount = events.filter((e) => e.type === "session.completed").length;
  const agentCount = events.filter((e) => e.type === "agent.created").length;
  const retryCount = events.filter((e) => e.type === "telemetry.retry").length;
  const totalTokens = tokenMetrics.totalInputTokens + tokenMetrics.totalOutputTokens;

  return (
    <div className="space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between"
      >
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-white">Command Center</h2>
          <p className="mt-1 text-sm text-zinc-500">Enterprise AI orchestration — realtime view</p>
        </div>
        <ConnectionIndicator state={connectionState} />
      </motion.div>

      {/* Stat grid */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          icon={Bot}
          label="Active Agents"
          value={agentCount}
          sub="registered this session"
          accent="bg-violet-500/10 text-violet-400"
          delay={0.05}
        />
        <StatCard
          icon={Activity}
          label="Sessions"
          value={sessionCount}
          sub={`${completedCount} completed`}
          accent="bg-blue-500/10 text-blue-400"
          delay={0.1}
        />
        <StatCard
          icon={Zap}
          label="Tokens Used"
          value={totalTokens > 0 ? totalTokens.toLocaleString() : "—"}
          sub={`$${tokenMetrics.totalCostUsd.toFixed(4)} USD`}
          accent="bg-amber-500/10 text-amber-400"
          delay={0.15}
        />
        <StatCard
          icon={TrendingUp}
          label="Retries"
          value={retryCount}
          sub="fault tolerance events"
          accent={retryCount > 0 ? "bg-rose-500/10 text-rose-400" : "bg-zinc-800 text-zinc-500"}
          delay={0.2}
        />
      </div>

      {/* Quick actions */}
      <div>
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.25 }}
          className="mb-4 text-xs font-semibold uppercase tracking-widest text-zinc-600"
        >
          Quick Access
        </motion.p>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {QUICK_ACTIONS.map((action, i) => {
            const Icon = action.icon;
            return (
              <motion.div
                key={action.label}
                initial={{ opacity: 0, scale: 0.97 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.25 + i * 0.05 }}
              >
                <Link
                  href={action.href}
                  className={cn(
                    "flex flex-col gap-2 rounded-xl border bg-gradient-to-br p-5 transition-all hover:scale-[1.01] hover:shadow-lg hover:shadow-black/30",
                    action.accent,
                  )}
                >
                  <Icon className="h-5 w-5" />
                  <div>
                    <p className="text-sm font-semibold text-white">{action.label}</p>
                    <p className="text-xs text-zinc-500">{action.desc}</p>
                  </div>
                </Link>
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* Recent events */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
      >
        <p className="mb-4 text-xs font-semibold uppercase tracking-widest text-zinc-600">
          Recent Events
        </p>
        <div className="divide-y divide-white/5 rounded-xl border border-white/10 bg-zinc-950">
          {events.slice(0, 8).map((ev) => (
            <div key={ev.id} className="flex items-center gap-4 px-5 py-3">
              <div
                className={cn(
                  "h-1.5 w-1.5 shrink-0 rounded-full",
                  ev.severity === "error" || ev.severity === "critical"
                    ? "bg-rose-400"
                    : ev.severity === "warning"
                      ? "bg-amber-400"
                      : "bg-emerald-400",
                )}
              />
              <span className="w-20 shrink-0 font-mono text-xs text-zinc-600">
                {new Date(ev.timestamp).toLocaleTimeString("en-US", { hour12: false })}
              </span>
              <span className="shrink-0 font-mono text-xs text-zinc-400">{ev.type}</span>
              <span className="flex-1 truncate text-xs text-zinc-600">
                {Object.entries(ev.payload)
                  .slice(0, 2)
                  .map(([k, v]) => `${k}=${String(v).slice(0, 30)}`)
                  .join("  ")}
              </span>
            </div>
          ))}
          {events.length === 0 && (
            <div className="flex h-24 items-center justify-center text-xs text-zinc-700">
              Waiting for events from the event bus…
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}
