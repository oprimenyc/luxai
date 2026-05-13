"use client";

import { motion } from "framer-motion";
import { Bell, Key, Shield, User } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

const TABS = ["Profile", "API Keys", "Security", "Notifications"] as const;
type Tab = (typeof TABS)[number];

const TAB_ICONS: Record<Tab, React.ComponentType<{ className?: string }>> = {
  Profile: User,
  "API Keys": Key,
  Security: Shield,
  Notifications: Bell,
};

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("Profile");

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <h2 className="text-2xl font-bold tracking-tight text-white">Settings</h2>
        <p className="mt-1 text-sm text-zinc-500">Account and system configuration</p>
      </motion.div>

      <div className="flex gap-6">
        {/* Tab navigation */}
        <nav className="w-48 shrink-0">
          <ul className="space-y-1">
            {TABS.map((tab) => {
              const Icon = TAB_ICONS[tab];
              return (
                <li key={tab}>
                  <button
                    onClick={() => setActiveTab(tab)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                      activeTab === tab
                        ? "bg-white/10 text-white"
                        : "text-zinc-500 hover:bg-white/5 hover:text-zinc-300",
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    {tab}
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
          {activeTab === "Profile" && (
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
              <button className="rounded-lg bg-white/10 px-4 py-2 text-sm font-medium text-white border border-white/10 transition-colors hover:bg-white/15">
                Save Changes
              </button>
            </div>
          )}

          {activeTab === "API Keys" && (
            <div className="space-y-5">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white">API Keys</h3>
                <button className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-300 transition-colors hover:bg-white/10">
                  + New Key
                </button>
              </div>
              <div className="rounded-lg border border-white/10 divide-y divide-white/5">
                {["Production Key", "Development Key"].map((key) => (
                  <div key={key} className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="text-sm text-white">{key}</p>
                      <p className="font-mono text-xs text-zinc-600">lux_••••••••••••••••</p>
                    </div>
                    <button className="text-xs text-zinc-600 hover:text-rose-400 transition-colors">Revoke</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === "Security" && (
            <div className="space-y-5">
              <h3 className="text-sm font-semibold text-white">Security Settings</h3>
              {[
                { label: "Two-factor Authentication", desc: "Add an extra layer of security", enabled: false },
                { label: "Session Timeout", desc: "Auto sign-out after inactivity", enabled: true },
                { label: "Audit Logging", desc: "Log all account actions", enabled: true },
              ].map((setting) => (
                <div key={setting.label} className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.02] px-4 py-3">
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

          {activeTab === "Notifications" && (
            <div className="space-y-5">
              <h3 className="text-sm font-semibold text-white">Notification Preferences</h3>
              {[
                { label: "Session Failures", desc: "Alert when a session fails" },
                { label: "Approval Requests", desc: "Alert on governance approvals" },
                { label: "Kill Switch Events", desc: "Alert on kill switch activation" },
                { label: "Weekly Reports", desc: "Usage summary every Monday" },
              ].map((notif) => (
                <div key={notif.label} className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.02] px-4 py-3">
                  <div>
                    <p className="text-sm text-white">{notif.label}</p>
                    <p className="text-xs text-zinc-600">{notif.desc}</p>
                  </div>
                  <input type="checkbox" defaultChecked className="h-4 w-4 rounded accent-violet-500" />
                </div>
              ))}
            </div>
          )}
        </motion.div>
      </div>
    </div>
  );
}
