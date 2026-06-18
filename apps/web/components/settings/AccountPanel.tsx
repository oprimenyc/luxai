"use client";

import { Activity, CreditCard, Shield } from "lucide-react";
import { cn } from "@/lib/utils";

interface AccountPanelProps {
  userId?: string;
  accountSize?: number;
  shadowActive?: boolean;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="space-y-1 rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
      <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600">{label}</p>
      <p className="font-mono text-lg text-zinc-100">{value}</p>
      {sub && <p className="font-mono text-xs text-zinc-500">{sub}</p>}
    </div>
  );
}

function tierLabel(size: number): { name: string; color: string } {
  if (size < 500) return { name: "Tiny", color: "text-amber-400" };
  if (size < 2500) return { name: "Growth", color: "text-emerald-400" };
  return { name: "Aggressive", color: "text-violet-400" };
}

export function AccountPanel({ userId, accountSize = 0, shadowActive = true }: AccountPanelProps) {
  const tier = tierLabel(accountSize);

  return (
    <div className="space-y-6">
      <div>
        <h3 className="font-mono text-xs uppercase tracking-widest text-zinc-400">Account</h3>
        <p className="mt-1 text-xs text-zinc-600">Current account status and tier assignment.</p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Stat label="Account Size" value={`$${accountSize.toFixed(2)}`} sub="paper balance" />
        <Stat
          label="Tier"
          value={tier.name}
          sub={`${tier.name === "Tiny" ? "$0 – $500" : tier.name === "Growth" ? "$500 – $2,500" : "$2,500+"}`}
        />
      </div>

      {/* Mode badge */}
      <div
        className={cn(
          "flex items-center gap-3 rounded-lg border px-4 py-3",
          shadowActive
            ? "border-amber-500/30 bg-amber-500/5"
            : "border-emerald-500/30 bg-emerald-500/5",
        )}
      >
        <Activity
          className={cn("h-4 w-4 shrink-0", shadowActive ? "text-amber-400" : "text-emerald-400")}
          strokeWidth={1.5}
        />
        <div>
          <p
            className={cn(
              "font-mono text-xs font-medium",
              shadowActive ? "text-amber-300" : "text-emerald-300",
            )}
          >
            {shadowActive ? "Shadow Mode Active" : "Live Mode Active"}
          </p>
          <p className="mt-0.5 text-xs text-zinc-500">
            {shadowActive
              ? "All orders intercepted and logged. No real capital at risk."
              : "Orders submitted to live broker. Real capital at risk."}
          </p>
        </div>
      </div>

      {/* Account ID */}
      {userId && (
        <div className="space-y-1">
          <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600">
            Account ID
          </p>
          <p className="break-all font-mono text-xs text-zinc-400">{userId}</p>
        </div>
      )}

      {/* Tier rules quick reference */}
      <div className="space-y-2">
        <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600">
          {tier.name} Tier Rules
        </p>
        <div className="divide-y divide-zinc-800/60 rounded-lg border border-zinc-800">
          {[
            [
              "Max risk / trade",
              tier.name === "Tiny" ? "$5 or 3%" : tier.name === "Growth" ? "$25 or 5%" : "5%",
            ],
            ["Max contracts", tier.name === "Tiny" ? "1" : tier.name === "Growth" ? "2" : "5"],
            [
              "Min DTE",
              tier.name === "Tiny" ? "7 days" : tier.name === "Growth" ? "5 days" : "1 day",
            ],
            ["0DTE", "Never"],
          ].map(([rule, val]) => (
            <div key={rule} className="flex items-center justify-between px-4 py-2.5">
              <span className="font-mono text-xs text-zinc-500">{rule}</span>
              <span className="font-mono text-xs text-zinc-300">{val}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2 rounded-lg border border-zinc-800/40 bg-zinc-900/30 px-4 py-3">
        <Shield className="h-3 w-3 shrink-0 text-zinc-600" strokeWidth={1.5} />
        <p className="text-[11px] text-zinc-600">
          Tier limits are enforced at the engine level. UI settings cannot override them.
        </p>
      </div>
    </div>
  );
}
