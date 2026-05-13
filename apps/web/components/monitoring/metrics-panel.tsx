"use client";

import { motion } from "framer-motion";
import { Activity, Clock, DollarSign, Zap } from "lucide-react";
import { useMemo } from "react";
import { Bar, BarChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { LuxEvent } from "@/lib/events/schemas";
import { useTokenMetrics } from "@/lib/websocket/hooks";
import { cn } from "@/lib/utils";

interface MetricsPanelProps {
  events: LuxEvent[];
  className?: string;
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  accent,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="rounded-xl border border-white/10 bg-white/[0.03] p-4 backdrop-blur-sm"
    >
      <div className="flex items-center gap-2 mb-3">
        <Icon className={cn("h-4 w-4", accent ?? "text-zinc-500")} />
        <span className="text-xs text-zinc-500">{label}</span>
      </div>
      <p className="text-2xl font-bold tracking-tight text-white">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-zinc-600">{sub}</p>}
    </motion.div>
  );
}

const CustomTooltip = ({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number; name: string }>;
  label?: string;
}) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-white/10 bg-zinc-900 px-3 py-2 text-xs shadow-xl">
      <p className="text-zinc-400 mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.name} className="text-white">
          {p.name}: <span className="text-violet-300">{p.value.toLocaleString()}</span>
        </p>
      ))}
    </div>
  );
};

export function MetricsPanel({ events, className }: MetricsPanelProps) {
  const tokenMetrics = useTokenMetrics(events);

  const latencyData = useMemo(() => {
    return events
      .filter((e) => e.type === "graph.node_exited" && e.payload["duration_ms"])
      .slice(-20)
      .map((e, i) => ({
        name: String(e.payload["node_name"] ?? "").slice(0, 8),
        ms: Number(e.payload["duration_ms"] ?? 0),
        i,
      }));
  }, [events]);

  const tokenChartData = useMemo(() => {
    return Object.entries(tokenMetrics.byModel).map(([model, data]) => ({
      model: model.replace("gpt-", "").replace("-preview", ""),
      input: data.input,
      output: data.output,
    }));
  }, [tokenMetrics]);

  const retryCount = events.filter((e) => e.type === "telemetry.retry").length;
  const sessionCount = events.filter((e) => e.type === "session.started").length;
  const completedCount = events.filter((e) => e.type === "session.completed").length;

  const totalTokens = tokenMetrics.totalInputTokens + tokenMetrics.totalOutputTokens;

  return (
    <div className={cn("space-y-4", className)}>
      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          icon={Zap}
          label="Total Tokens"
          value={totalTokens > 0 ? totalTokens.toLocaleString() : "—"}
          sub={`$${tokenMetrics.totalCostUsd.toFixed(4)}`}
          accent="text-violet-400"
        />
        <StatCard
          icon={Activity}
          label="Sessions"
          value={sessionCount.toString()}
          sub={`${completedCount} completed`}
          accent="text-blue-400"
        />
        <StatCard
          icon={Clock}
          label="Avg Latency"
          value={
            latencyData.length > 0
              ? `${Math.round(latencyData.reduce((a, b) => a + b.ms, 0) / latencyData.length)}ms`
              : "—"
          }
          sub="per node"
          accent="text-emerald-400"
        />
        <StatCard
          icon={DollarSign}
          label="Retries"
          value={retryCount.toString()}
          sub="fault tolerance"
          accent={retryCount > 0 ? "text-amber-400" : "text-zinc-500"}
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {/* Latency timeline */}
        <div className="rounded-xl border border-white/10 bg-zinc-950 p-4">
          <p className="mb-4 text-xs font-medium text-zinc-400">Node Latency (ms)</p>
          {latencyData.length > 0 ? (
            <ResponsiveContainer width="100%" height={120}>
              <LineChart data={latencyData}>
                <XAxis dataKey="name" tick={{ fontSize: 9, fill: "#52525b" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 9, fill: "#52525b" }} axisLine={false} tickLine={false} width={32} />
                <Tooltip content={<CustomTooltip />} />
                <Line
                  type="monotone"
                  dataKey="ms"
                  stroke="#8b5cf6"
                  strokeWidth={2}
                  dot={{ fill: "#8b5cf6", r: 3 }}
                  activeDot={{ r: 5, fill: "#a78bfa" }}
                  isAnimationActive
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-28 items-center justify-center text-xs text-zinc-700">
              No latency data yet
            </div>
          )}
        </div>

        {/* Token usage by model */}
        <div className="rounded-xl border border-white/10 bg-zinc-950 p-4">
          <p className="mb-4 text-xs font-medium text-zinc-400">Token Usage by Model</p>
          {tokenChartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={120}>
              <BarChart data={tokenChartData} barGap={2}>
                <XAxis dataKey="model" tick={{ fontSize: 9, fill: "#52525b" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 9, fill: "#52525b" }} axisLine={false} tickLine={false} width={36} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="input" name="Input" fill="#6d28d9" radius={[2, 2, 0, 0]} />
                <Bar dataKey="output" name="Output" fill="#2563eb" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-28 items-center justify-center text-xs text-zinc-700">
              No token data yet
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
