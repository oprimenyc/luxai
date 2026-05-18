"use client";

import { motion } from "framer-motion";
import {
  Activity,
  Bot,
  Brain,
  ChevronRight,
  Clock,
  Command,
  GitBranch,
  LayoutDashboard,
  LineChart,
  LogOut,
  Settings,
  Shield,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useState } from "react";
import { CommandPalette, useCommandPalette } from "@/components/command/command-palette";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard, section: "main" },
  { href: "/agents", label: "Agents", icon: Bot, section: "main" },
  { href: "/sessions", label: "Sessions", icon: Clock, section: "main" },
  { href: "/monitoring", label: "Monitoring", icon: Activity, section: "observe", badge: "live" },
  { href: "/memory", label: "Memory", icon: Brain, section: "observe" },
  { href: "/workflows", label: "Workflows", icon: GitBranch, section: "automate" },
  { href: "/governance", label: "Governance", icon: Shield, section: "automate" },
  { href: "/trading", label: "Trading", icon: LineChart, section: "automate", badge: "paper" },
  { href: "/settings", label: "Settings", icon: Settings, section: "system" },
];

const SECTION_LABELS: Record<string, string> = {
  main: "Core",
  observe: "Observability",
  automate: "Automation",
  system: "System",
};

function NavItem({
  item,
  active,
}: {
  item: (typeof NAV_ITEMS)[number];
  active: boolean;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={cn(
        "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all duration-150",
        active
          ? "bg-white/10 text-white"
          : "text-zinc-500 hover:bg-white/5 hover:text-zinc-300",
      )}
    >
      {active && (
        <motion.div
          layoutId="nav-indicator"
          className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-white"
          transition={{ type: "spring", stiffness: 400, damping: 30 }}
        />
      )}
      <Icon className={cn("h-4 w-4 shrink-0 transition-colors", active ? "text-white" : "text-zinc-600 group-hover:text-zinc-400")} />
      <span className="flex-1 font-medium">{item.label}</span>
      {item.badge && (
        <span className="flex items-center gap-1 rounded-full bg-emerald-500/20 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-widest text-emerald-400">
          <span className="h-1 w-1 rounded-full bg-emerald-400 animate-pulse" />
          {item.badge}
        </span>
      )}
    </Link>
  );
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { open, onClose, setOpen } = useCommandPalette();
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const grouped = Object.entries(SECTION_LABELS).map(([key, label]) => ({
    key,
    label,
    items: NAV_ITEMS.filter((i) => i.section === key),
  }));

  return (
    <div className="flex h-screen overflow-hidden bg-zinc-950 text-white">
      {/* Command palette */}
      <CommandPalette open={open} onClose={onClose} />

      {/* Sidebar */}
      <aside
        className={cn(
          "flex flex-col border-r border-white/5 bg-zinc-950 transition-all duration-300",
          sidebarOpen ? "w-56" : "w-16",
        )}
      >
        {/* Wordmark */}
        <div className="flex h-14 items-center gap-2.5 border-b border-white/5 px-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-violet-600 to-violet-800 shadow-lg shadow-violet-900/50">
            <Zap className="h-4 w-4 text-white" />
          </div>
          {sidebarOpen && (
            <motion.span
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              className="text-sm font-bold tracking-tight text-white"
            >
              LuxAI
            </motion.span>
          )}
        </div>

        {/* Command palette trigger */}
        {sidebarOpen && (
          <button
            onClick={() => setOpen(true)}
            className="mx-3 mt-3 flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-zinc-500 transition-colors hover:bg-white/10 hover:text-zinc-300"
          >
            <Command className="h-3.5 w-3.5" />
            <span className="flex-1 text-left">Search…</span>
            <kbd className="rounded border border-white/10 bg-white/5 px-1 font-mono text-[9px]">⌘K</kbd>
          </button>
        )}

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto p-3 space-y-5">
          {grouped.map(({ key, label, items }) => (
            <div key={key}>
              {sidebarOpen && (
                <p className="mb-1.5 px-3 text-[9px] font-semibold uppercase tracking-widest text-zinc-700">
                  {label}
                </p>
              )}
              <ul className="space-y-0.5">
                {items.map((item) => (
                  <li key={item.href}>
                    <NavItem item={item} active={pathname === item.href || pathname.startsWith(item.href + "/")} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="border-t border-white/5 p-3">
          <button className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-zinc-600 transition-colors hover:bg-white/5 hover:text-zinc-400">
            <LogOut className="h-4 w-4" />
            {sidebarOpen && <span>Sign out</span>}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Topbar */}
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-white/5 bg-zinc-950 px-6">
          <div className="flex items-center gap-3">
            {/* Breadcrumb */}
            <span className="text-xs text-zinc-600">LuxAI</span>
            <ChevronRight className="h-3.5 w-3.5 text-zinc-800" />
            <span className="text-xs font-medium text-zinc-300 capitalize">
              {pathname.split("/").filter(Boolean).at(-1) ?? "Dashboard"}
            </span>
          </div>

          <div className="flex items-center gap-3">
            {/* Live indicator */}
            <div className="flex items-center gap-1.5 rounded-full border border-emerald-900/40 bg-emerald-950/30 px-2.5 py-1">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-[10px] font-medium text-emerald-400">System Nominal</span>
            </div>

            <button
              onClick={() => setOpen(true)}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-zinc-500 transition-colors hover:bg-white/10 hover:text-zinc-300"
            >
              <Command className="h-3.5 w-3.5" />
              <span>⌘K</span>
            </button>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto bg-[#0a0a0a] p-6">
          <motion.div
            key={pathname}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2 }}
          >
            {children}
          </motion.div>
        </main>
      </div>
    </div>
  );
}
