"use client";

import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle, Shield, XCircle, Zap } from "lucide-react";
import { cn } from "@/lib/utils";

const MOCK_PENDING = [
  {
    id: "apr-1",
    session_id: "sess-abc123",
    agent_id: "agent-001",
    risk_score: 0.72,
    risk_level: "high" as const,
    task_preview: "Delete all archived workflow records from the database and compress audit logs older than 90 days.",
    expires_at: new Date(Date.now() + 25 * 60 * 1000).toISOString(),
    factors: [
      { name: "high_risk_pattern", score: 0.7, reason: "Task contains DELETE + database pattern" },
      { name: "high_risk_tool", score: 0.6, reason: "database_write tool requested" },
    ],
  },
];

const RISK_CONFIG = {
  low: { color: "text-emerald-400", bg: "bg-emerald-950/30 border-emerald-800/30" },
  medium: { color: "text-amber-400", bg: "bg-amber-950/30 border-amber-800/30" },
  high: { color: "text-orange-400", bg: "bg-orange-950/30 border-orange-800/30" },
  critical: { color: "text-rose-400", bg: "bg-rose-950/30 border-rose-800/30" },
};

export function GovernanceClient() {
  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-white">Governance</h2>
          <p className="mt-1 text-sm text-zinc-500">Risk controls, approvals, and execution policies</p>
        </div>
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-violet-400" />
          <span className="text-sm text-zinc-400">Policy: <span className="text-white">Default</span></span>
        </div>
      </motion.div>

      {/* Policy stats */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Risk Threshold", value: "High", icon: Shield, color: "text-violet-400" },
          { label: "Pending Approvals", value: MOCK_PENDING.length.toString(), icon: AlertTriangle, color: "text-amber-400" },
          { label: "Auto-Approved Today", value: "14", icon: CheckCircle, color: "text-emerald-400" },
          { label: "Kill Switches", value: "0", icon: Zap, color: "text-zinc-400" },
        ].map((stat) => {
          const Icon = stat.icon;
          return (
            <motion.div
              key={stat.label}
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="rounded-xl border border-white/10 bg-zinc-950 p-4"
            >
              <div className="flex items-center gap-2 mb-2">
                <Icon className={cn("h-4 w-4", stat.color)} />
                <span className="text-xs text-zinc-500">{stat.label}</span>
              </div>
              <p className="text-2xl font-bold text-white">{stat.value}</p>
            </motion.div>
          );
        })}
      </div>

      {/* Pending approvals */}
      <div>
        <h3 className="mb-3 text-sm font-semibold text-zinc-300">Pending Approvals</h3>
        <div className="space-y-3">
          {MOCK_PENDING.length === 0 ? (
            <div className="flex h-24 items-center justify-center rounded-xl border border-white/10 bg-zinc-950 text-sm text-zinc-600">
              No pending approvals
            </div>
          ) : (
            MOCK_PENDING.map((req) => {
              const riskCfg = RISK_CONFIG[req.risk_level];
              const expiresIn = Math.max(
                0,
                Math.round((new Date(req.expires_at).getTime() - Date.now()) / 60000),
              );

              return (
                <motion.div
                  key={req.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  className={cn("rounded-xl border p-5", riskCfg.bg)}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium border", riskCfg.bg, riskCfg.color)}>
                          {req.risk_level.toUpperCase()} RISK — {(req.risk_score * 100).toFixed(0)}%
                        </span>
                        <span className="text-xs text-zinc-500">
                          Session: {req.session_id.slice(0, 12)}…
                        </span>
                        <span className="text-xs text-zinc-600">Expires in {expiresIn}m</span>
                      </div>

                      <p className="text-sm text-zinc-300 mb-3">"{req.task_preview}"</p>

                      <div className="space-y-1">
                        {req.factors.map((f) => (
                          <div key={f.name} className="flex items-center gap-2 text-xs text-zinc-500">
                            <div className="h-1 w-1 rounded-full bg-zinc-600" />
                            {f.reason}
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="flex flex-col gap-2 shrink-0">
                      <button className="flex items-center gap-2 rounded-lg bg-emerald-600/90 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500">
                        <CheckCircle className="h-4 w-4" />
                        Approve
                      </button>
                      <button className="flex items-center gap-2 rounded-lg border border-rose-800/40 bg-rose-950/30 px-4 py-2 text-sm font-medium text-rose-300 transition-colors hover:bg-rose-950/60">
                        <XCircle className="h-4 w-4" />
                        Deny
                      </button>
                    </div>
                  </div>
                </motion.div>
              );
            })
          )}
        </div>
      </div>

      {/* Kill switch */}
      <div className="rounded-xl border border-rose-900/30 bg-rose-950/10 p-5">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-rose-300">Emergency Kill Switch</p>
            <p className="mt-1 text-xs text-zinc-500">Immediately terminate all running agent sessions</p>
          </div>
          <button className="flex items-center gap-2 rounded-lg border border-rose-700/50 bg-rose-950/50 px-4 py-2 text-sm font-medium text-rose-300 transition-colors hover:bg-rose-900/60">
            <Zap className="h-4 w-4" />
            Activate Kill Switch
          </button>
        </div>
      </div>
    </div>
  );
}
