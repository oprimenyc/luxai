"use client";

import { Lock } from "lucide-react";

interface RiskRule {
  label: string;
  tiny: string;
  growth: string;
  aggressive: string;
}

const RISK_RULES: RiskRule[] = [
  { label: "Max risk / trade", tiny: "$5 or 3%", growth: "$25 or 5%", aggressive: "5% cap" },
  { label: "Max contracts", tiny: "1", growth: "2", aggressive: "5" },
  { label: "Min DTE", tiny: "7 days", growth: "5 days", aggressive: "1 day" },
  { label: "0DTE", tiny: "Never", growth: "Never", aggressive: "Never" },
  { label: "Earnings plays", tiny: "Prohibited", growth: "Allowed", aggressive: "Allowed" },
  { label: "Naked options", tiny: "Prohibited", growth: "Prohibited", aggressive: "Prohibited" },
  { label: "Averaging down", tiny: "Prohibited", growth: "Prohibited", aggressive: "Prohibited" },
];

export function RiskPanel() {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="font-mono text-xs uppercase tracking-widest text-zinc-400">Risk Controls</h3>
        <p className="mt-1 text-xs text-zinc-600">
          Hard limits by account tier. These are read-only — enforced at the engine, not the UI.
        </p>
      </div>

      <div className="overflow-hidden rounded-lg border border-zinc-800">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-zinc-800">
              <th className="px-4 py-2.5 text-left font-mono text-[10px] uppercase tracking-wider text-zinc-600">
                Rule
              </th>
              <th className="px-4 py-2.5 text-center font-mono text-[10px] uppercase tracking-wider text-amber-500/80">
                Tiny
              </th>
              <th className="px-4 py-2.5 text-center font-mono text-[10px] uppercase tracking-wider text-emerald-500/80">
                Growth
              </th>
              <th className="px-4 py-2.5 text-center font-mono text-[10px] uppercase tracking-wider text-violet-500/80">
                Aggressive
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/60">
            {RISK_RULES.map((rule) => (
              <tr key={rule.label} className="hover:bg-zinc-900/40">
                <td className="px-4 py-2.5 font-mono text-[11px] text-zinc-400">{rule.label}</td>
                <td className="px-4 py-2.5 text-center font-mono text-[11px] text-zinc-300">
                  {rule.tiny}
                </td>
                <td className="px-4 py-2.5 text-center font-mono text-[11px] text-zinc-300">
                  {rule.growth}
                </td>
                <td className="px-4 py-2.5 text-center font-mono text-[11px] text-zinc-300">
                  {rule.aggressive}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-zinc-800/40 bg-zinc-900/30 px-4 py-3">
        <Lock className="mt-0.5 h-3 w-3 shrink-0 text-zinc-600" strokeWidth={1.5} />
        <p className="text-[11px] text-zinc-600">
          These values are hardcoded into the engine. No setting, API call, or UI action can
          override them for live order submission. Shadow testing overrides are separate and only
          affect paper signal evaluation.
        </p>
      </div>

      <div className="space-y-2">
        <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-600">
          Position Sizing Cap
        </p>
        <div className="divide-y divide-zinc-800/60 rounded-lg border border-zinc-800">
          {[
            ["Global cap", "5% of account per trade"],
            ["Tiny account (<$500)", "$5 hard dollar cap"],
            ["0DTE block", "Permanently blocked — every tier"],
          ].map(([rule, val]) => (
            <div key={rule} className="flex items-center justify-between px-4 py-2.5">
              <span className="font-mono text-xs text-zinc-500">{rule}</span>
              <span className="font-mono text-xs text-zinc-300">{val}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
