"use client";

import { motion } from "framer-motion";
import { Download, RefreshCw, Settings2 } from "lucide-react";
import { useState } from "react";
import { ActivityTimeline } from "@/components/monitoring/activity-timeline";
import { ConnectionIndicator } from "@/components/monitoring/connection-indicator";
import { EventConsole } from "@/components/monitoring/event-console";
import { MetricsPanel } from "@/components/monitoring/metrics-panel";
import { OrchestrationGraph } from "@/components/monitoring/orchestration-graph";
import { useEventStream } from "@/lib/websocket/hooks";

export function MonitoringClient() {
  const [sessionFilter, setSessionFilter] = useState<string>("");

  const { events, connectionState, clearEvents, isConnected } = useEventStream({
    sessionId: sessionFilter || undefined,
    enabled: true,
    maxEvents: 500,
  });

  const exportEvents = () => {
    const json = JSON.stringify(events, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `luxai-events-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-full space-y-6">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between"
      >
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-white">Monitoring</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Realtime agent orchestration visibility
          </p>
        </div>

        <div className="flex items-center gap-3">
          <ConnectionIndicator state={connectionState} />

          {/* Session filter */}
          <input
            type="text"
            value={sessionFilter}
            onChange={(e) => setSessionFilter(e.target.value)}
            placeholder="Filter by session ID…"
            className="w-52 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-white/20"
          />

          <button
            onClick={clearEvents}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-400 transition-colors hover:bg-white/10 hover:text-white"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Clear
          </button>

          <button
            onClick={exportEvents}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-400 transition-colors hover:bg-white/10 hover:text-white"
          >
            <Download className="h-3.5 w-3.5" />
            Export
          </button>
        </div>
      </motion.div>

      {/* Orchestration graph */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.05 }}
      >
        <OrchestrationGraph events={events} />
      </motion.div>

      {/* Metrics */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <MetricsPanel events={events} />
      </motion.div>

      {/* Bottom row: timeline + console */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="grid grid-cols-1 gap-4 lg:grid-cols-2"
      >
        <ActivityTimeline events={events} />
        <EventConsole events={events} />
      </motion.div>
    </div>
  );
}
