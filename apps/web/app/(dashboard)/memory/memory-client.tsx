"use client";

import { motion } from "framer-motion";
import { Brain, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

type MemoryType = "semantic" | "episodic" | "workflow" | "user" | "project" | "strategic";

const MEMORY_TYPE_CONFIG: Record<MemoryType, { color: string; dot: string }> = {
  semantic: { color: "text-violet-300 bg-violet-950/40 border-violet-800/30", dot: "bg-violet-400" },
  episodic: { color: "text-blue-300 bg-blue-950/40 border-blue-800/30", dot: "bg-blue-400" },
  workflow: { color: "text-amber-300 bg-amber-950/40 border-amber-800/30", dot: "bg-amber-400" },
  user: { color: "text-emerald-300 bg-emerald-950/40 border-emerald-800/30", dot: "bg-emerald-400" },
  project: { color: "text-cyan-300 bg-cyan-950/40 border-cyan-800/30", dot: "bg-cyan-400" },
  strategic: { color: "text-rose-300 bg-rose-950/40 border-rose-800/30", dot: "bg-rose-400" },
};

// Mock data for UI demonstration
const MOCK_MEMORIES = [
  { id: "1", memory_type: "semantic" as MemoryType, content: "The supervisor graph uses a researcher → executor → critic loop with conditional re-routing until the critic passes or max_iterations is reached.", importance_score: 0.9, access_count: 7, created_at: new Date().toISOString(), tags: ["architecture", "langgraph"] },
  { id: "2", memory_type: "episodic" as MemoryType, content: "User requested generation of an enterprise monorepo architecture for a luxury multi-agent AI OS. Completed with 85 files.", importance_score: 0.8, access_count: 3, created_at: new Date().toISOString(), tags: ["session", "completed"] },
  { id: "3", memory_type: "user" as MemoryType, content: "User prefers enterprise-grade, no placeholder code, strict TypeScript, ruff + mypy for Python.", importance_score: 1.0, access_count: 12, created_at: new Date().toISOString(), tags: ["preferences"] },
  { id: "4", memory_type: "strategic" as MemoryType, content: "Goal: build a production-grade luxury AI operating system with realtime monitoring, persistent memory, and governance.", importance_score: 0.95, access_count: 5, created_at: new Date().toISOString(), tags: ["goal", "strategy"] },
];

export function MemoryClient() {
  const [query, setQuery] = useState("");
  const [selectedType, setSelectedType] = useState<MemoryType | "all">("all");
  const memories = MOCK_MEMORIES.filter(
    (m) =>
      (selectedType === "all" || m.memory_type === selectedType) &&
      (!query || m.content.toLowerCase().includes(query.toLowerCase())),
  );

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-white">Memory</h2>
          <p className="mt-1 text-sm text-zinc-500">Persistent semantic memory store</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <Brain className="h-4 w-4 text-cyan-400" />
          <span className="text-cyan-400">{memories.length}</span>
          <span>memories active</span>
        </div>
      </motion.div>

      {/* Search + filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-600" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search memories…"
            className="w-full rounded-lg border border-white/10 bg-white/5 pl-9 pr-3 py-2 text-sm text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-white/20"
          />
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-white/10 p-1">
          {(["all", "semantic", "episodic", "workflow", "user", "project", "strategic"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setSelectedType(t)}
              className={cn(
                "rounded-md px-2 py-1 text-xs capitalize transition-colors",
                selectedType === t ? "bg-white/10 text-white" : "text-zinc-600 hover:text-zinc-400",
              )}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Memory cards */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {memories.map((mem, i) => {
          const config = MEMORY_TYPE_CONFIG[mem.memory_type];
          return (
            <motion.div
              key={mem.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
              className="group rounded-xl border border-white/10 bg-zinc-950 p-4 hover:border-white/20 transition-colors"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className={cn("h-1.5 w-1.5 rounded-full", config.dot)} />
                  <span className={cn("rounded border px-2 py-0.5 text-[10px] uppercase tracking-wider", config.color)}>
                    {mem.memory_type}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1">
                    <div className="h-1 w-16 rounded-full bg-white/10">
                      <div
                        className="h-1 rounded-full bg-violet-500"
                        style={{ width: `${mem.importance_score * 100}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-zinc-600">{(mem.importance_score * 100).toFixed(0)}%</span>
                  </div>
                  <button className="opacity-0 group-hover:opacity-100 transition-opacity text-zinc-700 hover:text-rose-400">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              <p className="text-sm text-zinc-300 leading-relaxed line-clamp-3">{mem.content}</p>

              <div className="mt-3 flex items-center gap-3 text-[10px] text-zinc-700">
                <span>{mem.access_count} accesses</span>
                <span>·</span>
                <span>{new Date(mem.created_at).toLocaleDateString()}</span>
                {mem.tags.map((tag) => (
                  <span key={tag} className="rounded bg-white/5 px-1.5 py-0.5 text-zinc-600">
                    #{tag}
                  </span>
                ))}
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
