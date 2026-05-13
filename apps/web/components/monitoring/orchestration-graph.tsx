"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useMemo } from "react";
import type { LuxEvent } from "@/lib/events/schemas";
import { useGraphNodes } from "@/lib/websocket/hooks";
import { cn } from "@/lib/utils";

interface OrchestrationGraphProps {
  events: LuxEvent[];
  className?: string;
}

const GRAPH_NODES = [
  { id: "researcher", label: "Researcher", color: "from-violet-600 to-violet-700" },
  { id: "executor", label: "Executor", color: "from-blue-600 to-blue-700" },
  { id: "critic", label: "Critic", color: "from-amber-600 to-amber-700" },
] as const;

const EDGES = [
  { from: "researcher", to: "executor" },
  { from: "executor", to: "critic" },
  { from: "critic", to: "executor", label: "retry", dashed: true },
  { from: "critic", to: "END", label: "pass" },
] as const;

type NodeId = (typeof GRAPH_NODES)[number]["id"] | "END";

function NodeCard({
  node,
  isActive,
  isCompleted,
  durationMs,
}: {
  node: (typeof GRAPH_NODES)[number];
  isActive: boolean;
  isCompleted: boolean;
  durationMs?: number;
}) {
  return (
    <motion.div
      layout
      className="relative flex flex-col items-center"
      animate={{
        scale: isActive ? 1.05 : 1,
      }}
      transition={{ type: "spring", stiffness: 300, damping: 25 }}
    >
      {/* Active glow */}
      {isActive && (
        <motion.div
          className={cn("absolute inset-0 rounded-xl blur-lg opacity-50 bg-gradient-to-br", node.color)}
          animate={{ opacity: [0.3, 0.6, 0.3] }}
          transition={{ duration: 1.5, repeat: Infinity }}
        />
      )}

      <div
        className={cn(
          "relative z-10 flex h-20 w-32 flex-col items-center justify-center rounded-xl border transition-all duration-300",
          isActive
            ? "border-white/30 bg-white/10 shadow-lg"
            : isCompleted
              ? "border-emerald-500/40 bg-emerald-950/30"
              : "border-white/10 bg-white/5",
        )}
      >
        {/* Status indicator */}
        <div
          className={cn(
            "absolute top-2 right-2 h-2 w-2 rounded-full",
            isActive ? "bg-white animate-pulse" : isCompleted ? "bg-emerald-400" : "bg-zinc-700",
          )}
        />

        <span className="text-sm font-semibold text-white">{node.label}</span>

        {isActive && (
          <motion.div
            className="mt-1 flex gap-0.5"
            animate={{ opacity: [0.4, 1, 0.4] }}
            transition={{ duration: 0.8, repeat: Infinity }}
          >
            {[0, 1, 2].map((i) => (
              <motion.div
                key={i}
                className="h-1 w-1 rounded-full bg-white"
                animate={{ scale: [0.5, 1, 0.5] }}
                transition={{ duration: 0.8, repeat: Infinity, delay: i * 0.15 }}
              />
            ))}
          </motion.div>
        )}

        {isCompleted && durationMs !== undefined && (
          <span className="mt-1 text-[10px] text-emerald-400">{durationMs}ms</span>
        )}
      </div>

      <span className="mt-1.5 text-[10px] uppercase tracking-widest text-zinc-600">{node.id}</span>
    </motion.div>
  );
}

function EndNode({ reached }: { reached: boolean }) {
  return (
    <div className="flex flex-col items-center">
      <div
        className={cn(
          "flex h-20 w-32 items-center justify-center rounded-xl border transition-all duration-500",
          reached
            ? "border-emerald-500/50 bg-emerald-950/40 shadow-emerald-900/30 shadow-lg"
            : "border-white/5 bg-white/[0.02]",
        )}
      >
        <span className={cn("text-sm font-semibold", reached ? "text-emerald-300" : "text-zinc-700")}>
          END
        </span>
      </div>
      <span className="mt-1.5 text-[10px] uppercase tracking-widest text-zinc-700">terminal</span>
    </div>
  );
}

function Arrow({ dashed, label }: { dashed?: boolean; label?: string }) {
  return (
    <div className="flex flex-col items-center gap-1 px-2">
      <svg width="48" height="24" className="overflow-visible">
        <defs>
          <marker id="arrowhead" markerWidth="6" markerHeight="4" refX="6" refY="2" orient="auto">
            <polygon points="0 0, 6 2, 0 4" fill="rgba(255,255,255,0.2)" />
          </marker>
        </defs>
        <line
          x1="0"
          y1="12"
          x2="48"
          y2="12"
          stroke="rgba(255,255,255,0.15)"
          strokeWidth="1.5"
          strokeDasharray={dashed ? "4 3" : undefined}
          markerEnd="url(#arrowhead)"
        />
      </svg>
      {label && <span className="text-[9px] text-zinc-600 -mt-1">{label}</span>}
    </div>
  );
}

export function OrchestrationGraph({ events, className }: OrchestrationGraphProps) {
  const nodeHistory = useGraphNodes(events);

  const activeNode = useMemo(() => {
    const entered = events.filter((e) => e.type === "graph.node_entered");
    const exited = new Set(
      events.filter((e) => e.type === "graph.node_exited").map((e) => e.payload["node_name"]),
    );
    const lastEntered = entered.at(-1);
    if (lastEntered && !exited.has(lastEntered.payload["node_name"])) {
      return lastEntered.payload["node_name"] as string;
    }
    return null;
  }, [events]);

  const completedNodes = useMemo(
    () =>
      new Set(
        events
          .filter((e) => e.type === "graph.node_exited")
          .map((e) => e.payload["node_name"] as string),
      ),
    [events],
  );

  const isCompleted = events.some((e) => e.type === "graph.completed");
  const nodeTimings = useMemo(() => {
    const map: Record<string, number> = {};
    for (const entry of nodeHistory) {
      if (entry.durationMs !== undefined) map[entry.name] = entry.durationMs;
    }
    return map;
  }, [nodeHistory]);

  return (
    <div className={cn("rounded-xl border border-white/10 bg-zinc-950 p-6", className)}>
      <div className="mb-5 flex items-center justify-between">
        <span className="text-sm font-semibold text-white">Orchestration Graph</span>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <div className={cn("h-1.5 w-1.5 rounded-full", activeNode ? "bg-white animate-pulse" : isCompleted ? "bg-emerald-400" : "bg-zinc-700")} />
          {activeNode ? `Running: ${activeNode}` : isCompleted ? "Completed" : "Idle"}
        </div>
      </div>

      <div className="flex items-center justify-center gap-0">
        {GRAPH_NODES.map((node, i) => (
          <div key={node.id} className="flex items-center">
            <NodeCard
              node={node}
              isActive={activeNode === node.id}
              isCompleted={completedNodes.has(node.id)}
              durationMs={nodeTimings[node.id]}
            />
            {i < GRAPH_NODES.length - 1 && <Arrow />}
          </div>
        ))}
        <Arrow label="pass" />
        <EndNode reached={isCompleted} />
      </div>

      {/* Retry edge indicator */}
      {events.some((e) => e.type === "telemetry.retry") && (
        <div className="mt-4 flex items-center gap-2 rounded-md bg-amber-950/30 border border-amber-500/20 px-3 py-2">
          <div className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
          <span className="text-xs text-amber-400">
            Retry loop active — critic sending back to executor
          </span>
        </div>
      )}
    </div>
  );
}
