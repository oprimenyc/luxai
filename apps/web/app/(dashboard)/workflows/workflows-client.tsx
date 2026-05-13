"use client";

import { motion } from "framer-motion";
import { CheckCircle, GitBranch, Loader2, Plus, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

type WorkflowStatus = "draft" | "running" | "completed" | "failed" | "queued";

const STATUS_CONFIG: Record<WorkflowStatus, { label: string; color: string; icon: React.ComponentType<{ className?: string }> }> = {
  draft: { label: "Draft", color: "text-zinc-400", icon: GitBranch },
  queued: { label: "Queued", color: "text-amber-400", icon: GitBranch },
  running: { label: "Running", color: "text-blue-400", icon: Loader2 },
  completed: { label: "Completed", color: "text-emerald-400", icon: CheckCircle },
  failed: { label: "Failed", color: "text-rose-400", icon: XCircle },
};

const MOCK_WORKFLOWS = [
  {
    id: "wf-1",
    name: "Market Research Pipeline",
    description: "Research → Analyze → Summarize competitive landscape",
    status: "completed" as WorkflowStatus,
    steps: 4,
    completed_steps: 4,
    created_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    tags: ["research", "competitive"],
  },
  {
    id: "wf-2",
    name: "Code Review Workflow",
    description: "Automated PR analysis with security and quality checks",
    status: "running" as WorkflowStatus,
    steps: 3,
    completed_steps: 1,
    created_at: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
    tags: ["code", "review"],
  },
  {
    id: "wf-3",
    name: "Customer Onboarding",
    description: "Automated welcome, setup, and initial training sequence",
    status: "draft" as WorkflowStatus,
    steps: 6,
    completed_steps: 0,
    created_at: new Date().toISOString(),
    tags: ["onboarding"],
  },
];

export function WorkflowsClient() {
  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-white">Workflows</h2>
          <p className="mt-1 text-sm text-zinc-500">Autonomous execution pipelines</p>
        </div>
        <button className="flex items-center gap-2 rounded-lg bg-white/10 px-4 py-2 text-sm font-medium text-white border border-white/10 transition-colors hover:bg-white/15">
          <Plus className="h-4 w-4" />
          New Workflow
        </button>
      </motion.div>

      <div className="space-y-3">
        {MOCK_WORKFLOWS.map((wf, i) => {
          const cfg = STATUS_CONFIG[wf.status];
          const StatusIcon = cfg.icon;
          const progress = wf.steps > 0 ? (wf.completed_steps / wf.steps) * 100 : 0;

          return (
            <motion.div
              key={wf.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="group rounded-xl border border-white/10 bg-zinc-950 p-5 hover:border-white/20 transition-colors cursor-pointer"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-1">
                    <StatusIcon className={cn("h-4 w-4", cfg.color, wf.status === "running" && "animate-spin")} />
                    <span className="text-sm font-semibold text-white">{wf.name}</span>
                    <span className={cn("text-xs", cfg.color)}>{cfg.label}</span>
                  </div>
                  <p className="text-xs text-zinc-500 mb-3">{wf.description}</p>

                  {/* Step progress */}
                  <div className="flex items-center gap-3">
                    <div className="flex-1 max-w-xs h-1 rounded-full bg-white/10">
                      <motion.div
                        className={cn("h-1 rounded-full", wf.status === "completed" ? "bg-emerald-500" : wf.status === "failed" ? "bg-rose-500" : "bg-blue-500")}
                        initial={{ width: 0 }}
                        animate={{ width: `${progress}%` }}
                        transition={{ duration: 0.5 }}
                      />
                    </div>
                    <span className="text-[10px] text-zinc-600">
                      {wf.completed_steps}/{wf.steps} steps
                    </span>
                  </div>
                </div>

                <div className="flex flex-col items-end gap-2 ml-4">
                  <div className="flex gap-1">
                    {wf.tags.map((tag) => (
                      <span key={tag} className="rounded bg-white/5 px-2 py-0.5 text-[10px] text-zinc-600">
                        #{tag}
                      </span>
                    ))}
                  </div>
                  <span className="text-[10px] text-zinc-700">
                    {new Date(wf.created_at).toLocaleString()}
                  </span>
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
