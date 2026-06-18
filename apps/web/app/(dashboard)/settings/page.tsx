"use client";

import { motion } from "framer-motion";
import { Activity, Bell, Key, Lock, Shield, ShieldAlert, Sliders, User } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { AccountPanel } from "@/components/settings/AccountPanel";
import { RiskPanel } from "@/components/settings/RiskPanel";
import { ShadowPanel, type ShadowSettings } from "@/components/settings/ShadowPanel";

// ── Tab definitions ───────────────────────────────────────────────────────────

const TABS = [
  { id: "account", label: "Account", icon: User },
  { id: "risk", label: "Risk Controls", icon: Sliders },
  { id: "shadow", label: "Shadow Testing", icon: Activity },
  { id: "danger", label: "Danger Zone", icon: ShieldAlert },
  { id: "profile", label: "Profile", icon: User },
  { id: "api-keys", label: "API Keys", icon: Key },
  { id: "security", label: "Security", icon: Shield },
  { id: "notifications", label: "Notifications", icon: Bell },
] as const;

type TabId = (typeof TABS)[number]["id"];

// ── Settings fetcher ──────────────────────────────────────────────────────────

const DEFAULT_SHADOW: ShadowSettings = {
  shadow_min_dte: 3,
  shadow_max_dte: 21,
  shadow_max_contracts: 3,
  shadow_max_risk_usd: 15,
  shadow_allow_earnings: false,
  score_threshold: 7.0,
};

async function fetchSettings(): Promise<ShadowSettings> {
  const res = await fetch("/api/v1/settings", { credentials: "include" });
  if (!res.ok) return DEFAULT_SHADOW;
  return res.json();
}

async function patchSettings(values: ShadowSettings): Promise<void> {
  const res = await fetch("/api/v1/settings", {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to save settings");
  }
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<TabId>("account");
  const [shadowSettings, setShadowSettings] = useState<ShadowSettings>(DEFAULT_SHADOW);

  useEffect(() => {
    fetchSettings()
      .then(setShadowSettings)
      .catch(() => {});
  }, []);

  const handleSaveShadow = useCallback(async (values: ShadowSettings) => {
    await patchSettings(values);
    setShadowSettings(values);
  }, []);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <h2 className="text-2xl font-bold tracking-tight text-white">Settings</h2>
        <p className="mt-1 text-sm text-zinc-500">Account and system configuration</p>
      </motion.div>

      <div className="flex gap-6">
        {/* Tab navigation */}
        <nav className="w-52 shrink-0">
          {/* Trading section */}
          <p className="mb-1.5 px-3 font-mono text-[9px] uppercase tracking-widest text-zinc-700">
            Trading
          </p>
          <ul className="mb-4 space-y-0.5">
            {TABS.filter((t) => ["account", "risk", "shadow", "danger"].includes(t.id)).map(
              (tab) => {
                const Icon = tab.icon;
                const isDanger = tab.id === "danger";
                return (
                  <li key={tab.id}>
                    <button
                      onClick={() => setActiveTab(tab.id)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                        activeTab === tab.id
                          ? isDanger
                            ? "bg-rose-500/10 text-rose-400"
                            : "bg-white/10 text-white"
                          : isDanger
                            ? "text-zinc-600 hover:bg-rose-500/5 hover:text-rose-400"
                            : "text-zinc-500 hover:bg-white/5 hover:text-zinc-300",
                      )}
                    >
                      <Icon className="h-4 w-4" />
                      {tab.label}
                    </button>
                  </li>
                );
              },
            )}
          </ul>

          {/* Account section */}
          <p className="mb-1.5 px-3 font-mono text-[9px] uppercase tracking-widest text-zinc-700">
            System
          </p>
          <ul className="space-y-0.5">
            {TABS.filter((t) =>
              ["profile", "api-keys", "security", "notifications"].includes(t.id),
            ).map((tab) => {
              const Icon = tab.icon;
              return (
                <li key={tab.id}>
                  <button
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                      activeTab === tab.id
                        ? "bg-white/10 text-white"
                        : "text-zinc-500 hover:bg-white/5 hover:text-zinc-300",
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    {tab.label}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Content */}
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, x: 10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.15 }}
          className="flex-1 rounded-xl border border-white/10 bg-zinc-950 p-6"
        >
          {activeTab === "account" && <AccountPanel shadowActive={true} accountSize={100} />}

          {activeTab === "risk" && <RiskPanel />}

          {activeTab === "shadow" && (
            <ShadowPanel initial={shadowSettings} onSave={handleSaveShadow} />
          )}

          {activeTab === "danger" && (
            <div className="space-y-6">
              <div>
                <h3 className="font-mono text-xs uppercase tracking-widest text-zinc-400">
                  Danger Zone
                </h3>
                <p className="mt-1 text-xs text-zinc-600">
                  Irreversible or high-consequence actions. Read carefully before acting.
                </p>
              </div>

              {/* Live trading gate info */}
              <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
                <div className="flex items-center gap-2">
                  <Lock className="h-4 w-4 text-zinc-600" strokeWidth={1.5} />
                  <p className="font-mono text-xs text-zinc-400">Live Trading Gate</p>
                </div>
                <p className="text-xs leading-relaxed text-zinc-500">
                  Live trading is locked. It cannot be enabled from this UI. The only path to live
                  trading is a successful 2-week shadow run followed by a manual admin journal audit
                  and explicit admin confirmation.
                </p>
                <div className="space-y-1 pt-1">
                  {[
                    ["Shadow run status", "Active — day 0 of 14"],
                    ["Gate criteria", "7 items — none cleared yet"],
                    ["Admin confirmation", "Not received"],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between font-mono text-[10px]">
                      <span className="text-zinc-600">{k}</span>
                      <span className="text-zinc-500">{v}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Kill switch info */}
              <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
                <div className="flex items-center gap-2">
                  <ShieldAlert className="h-4 w-4 text-zinc-600" strokeWidth={1.5} />
                  <p className="font-mono text-xs text-zinc-400">Kill Switch</p>
                </div>
                <p className="text-xs leading-relaxed text-zinc-500">
                  The kill switch is managed via the admin API. When active, all order submissions
                  are rejected immediately. It persists across restarts (dual-written to Redis and
                  Supabase). Clearing it requires an explicit admin action — it cannot be
                  self-cleared from this UI.
                </p>
                <p className="font-mono text-[10px] text-emerald-400">Kill switch: inactive</p>
              </div>
            </div>
          )}

          {activeTab === "profile" && (
            <div className="space-y-5">
              <h3 className="text-sm font-semibold text-white">Profile Information</h3>
              <div className="grid grid-cols-2 gap-4">
                {["Display Name", "Email"].map((field) => (
                  <div key={field}>
                    <label className="mb-1.5 block text-xs text-zinc-500">{field}</label>
                    <input
                      type={field === "Email" ? "email" : "text"}
                      placeholder={`Your ${field.toLowerCase()}`}
                      className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-zinc-700 focus:outline-none focus:ring-1 focus:ring-white/20"
                    />
                  </div>
                ))}
              </div>
              <button className="rounded-lg border border-white/10 bg-white/10 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/15">
                Save Changes
              </button>
            </div>
          )}

          {activeTab === "api-keys" && (
            <div className="space-y-5">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white">API Keys</h3>
                <button className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-300 transition-colors hover:bg-white/10">
                  + New Key
                </button>
              </div>
              <div className="divide-y divide-white/5 rounded-lg border border-white/10">
                {["Production Key", "Development Key"].map((key) => (
                  <div key={key} className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="text-sm text-white">{key}</p>
                      <p className="font-mono text-xs text-zinc-600">lux_••••••••••••••••</p>
                    </div>
                    <button className="text-xs text-zinc-600 transition-colors hover:text-rose-400">
                      Revoke
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === "security" && (
            <div className="space-y-5">
              <h3 className="text-sm font-semibold text-white">Security Settings</h3>
              {[
                {
                  label: "Two-factor Authentication",
                  desc: "Add an extra layer of security",
                  enabled: false,
                },
                { label: "Session Timeout", desc: "Auto sign-out after inactivity", enabled: true },
                { label: "Audit Logging", desc: "Log all account actions", enabled: true },
              ].map((setting) => (
                <div
                  key={setting.label}
                  className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.02] px-4 py-3"
                >
                  <div>
                    <p className="text-sm text-white">{setting.label}</p>
                    <p className="text-xs text-zinc-600">{setting.desc}</p>
                  </div>
                  <div
                    className={cn(
                      "relative h-5 w-9 rounded-full transition-colors",
                      setting.enabled ? "bg-violet-600" : "bg-zinc-700",
                    )}
                  >
                    <div
                      className={cn(
                        "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
                        setting.enabled ? "translate-x-4" : "translate-x-0.5",
                      )}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}

          {activeTab === "notifications" && (
            <div className="space-y-5">
              <h3 className="text-sm font-semibold text-white">Notification Preferences</h3>
              {[
                { label: "Session Failures", desc: "Alert when a session fails" },
                { label: "Approval Requests", desc: "Alert on governance approvals" },
                { label: "Kill Switch Events", desc: "Alert on kill switch activation" },
                { label: "Weekly Reports", desc: "Usage summary every Monday" },
              ].map((notif) => (
                <div
                  key={notif.label}
                  className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.02] px-4 py-3"
                >
                  <div>
                    <p className="text-sm text-white">{notif.label}</p>
                    <p className="text-xs text-zinc-600">{notif.desc}</p>
                  </div>
                  <input
                    type="checkbox"
                    defaultChecked
                    className="h-4 w-4 rounded accent-violet-500"
                  />
                </div>
              ))}
            </div>
          )}
        </motion.div>
      </div>
    </div>
  );
}
