"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  Bot,
  Brain,
  ChevronRight,
  Clock,
  Command,
  GitBranch,
  LayoutDashboard,
  Search,
  Settings,
  Shield,
  Zap,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface CommandItem {
  id: string;
  label: string;
  description?: string;
  icon: React.ComponentType<{ className?: string }>;
  action: () => void;
  category: string;
  keywords?: string[];
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const router = useRouter();

  const navigate = useCallback(
    (path: string) => {
      router.push(path);
      onClose();
    },
    [router, onClose],
  );

  const commands: CommandItem[] = useMemo(
    () => [
      {
        id: "dash",
        label: "Dashboard",
        description: "Overview and key metrics",
        icon: LayoutDashboard,
        action: () => {
          navigate("/dashboard");
        },
        category: "Navigation",
        keywords: ["home", "overview"],
      },
      {
        id: "agents",
        label: "Agents",
        description: "Manage your AI agents",
        icon: Bot,
        action: () => {
          navigate("/agents");
        },
        category: "Navigation",
        keywords: ["ai", "bot"],
      },
      {
        id: "monitoring",
        label: "Monitoring",
        description: "Realtime orchestration dashboard",
        icon: Activity,
        action: () => {
          navigate("/monitoring");
        },
        category: "Navigation",
        keywords: ["realtime", "live", "events", "stream"],
      },
      {
        id: "memory",
        label: "Memory",
        description: "Explore persistent memory",
        icon: Brain,
        action: () => {
          navigate("/memory");
        },
        category: "Navigation",
        keywords: ["semantic", "vector", "recall"],
      },
      {
        id: "workflows",
        label: "Workflows",
        description: "Autonomous execution pipelines",
        icon: GitBranch,
        action: () => {
          navigate("/workflows");
        },
        category: "Navigation",
        keywords: ["automation", "pipeline", "dag"],
      },
      {
        id: "governance",
        label: "Governance",
        description: "Risk controls and approvals",
        icon: Shield,
        action: () => {
          navigate("/governance");
        },
        category: "Navigation",
        keywords: ["rbac", "policy", "risk", "approval"],
      },
      {
        id: "sessions",
        label: "Sessions",
        description: "View execution sessions",
        icon: Clock,
        action: () => {
          navigate("/sessions");
        },
        category: "Navigation",
        keywords: ["history", "runs"],
      },
      {
        id: "settings",
        label: "Settings",
        description: "Account and system configuration",
        icon: Settings,
        action: () => {
          navigate("/settings");
        },
        category: "Navigation",
        keywords: ["config", "preferences"],
      },
      {
        id: "new-agent",
        label: "New Agent",
        description: "Create a new AI agent",
        icon: Zap,
        action: () => {
          navigate("/agents?new=true");
        },
        category: "Actions",
        keywords: ["create", "add"],
      },
      {
        id: "new-workflow",
        label: "New Workflow",
        description: "Create an autonomous workflow",
        icon: GitBranch,
        action: () => {
          navigate("/workflows?new=true");
        },
        category: "Actions",
        keywords: ["create", "pipeline"],
      },
    ],
    [navigate],
  );

  const filtered = useMemo(() => {
    if (!query.trim()) return commands;
    const q = query.toLowerCase();
    return commands.filter(
      (c) =>
        c.label.toLowerCase().includes(q) ||
        (c.description?.toLowerCase().includes(q) ?? false) ||
        c.category.toLowerCase().includes(q) ||
        (c.keywords?.some((k) => k.includes(q)) ?? false),
    );
  }, [commands, query]);

  const grouped = useMemo(() => {
    const groups: Record<string, CommandItem[]> = {};
    for (const cmd of filtered) {
      const bucket = groups[cmd.category] ?? [];
      bucket.push(cmd);
      groups[cmd.category] = bucket;
    }
    return groups;
  }, [filtered]);

  const flatFiltered = useMemo(() => filtered, [filtered]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setActiveIndex((i) => Math.min(i + 1, flatFiltered.length - 1));
          break;
        case "ArrowUp":
          e.preventDefault();
          setActiveIndex((i) => Math.max(i - 1, 0));
          break;
        case "Enter":
          e.preventDefault();
          flatFiltered[activeIndex]?.action();
          break;
        case "Escape":
          onClose();
          break;
      }
    },
    [flatFiltered, activeIndex, onClose],
  );

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* Panel */}
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: -20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: -10 }}
            transition={{ type: "spring", stiffness: 400, damping: 30 }}
            className="fixed left-1/2 top-24 z-50 w-full max-w-xl -translate-x-1/2"
          >
            <div className="overflow-hidden rounded-2xl border border-white/10 bg-zinc-950 shadow-2xl shadow-black/60">
              {/* Search input */}
              <div className="flex items-center gap-3 border-b border-white/10 px-4 py-3">
                <Search className="h-4 w-4 shrink-0 text-zinc-500" />
                <input
                  ref={inputRef}
                  type="text"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setActiveIndex(0);
                  }}
                  onKeyDown={handleKeyDown}
                  placeholder="Search commands…"
                  className="flex-1 bg-transparent text-sm text-white placeholder:text-zinc-600 focus:outline-none"
                />
                <kbd className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[10px] text-zinc-600">
                  ESC
                </kbd>
              </div>

              {/* Results */}
              <ul ref={listRef} className="max-h-96 overflow-y-auto py-2" role="listbox">
                {Object.entries(grouped).map(([category, items]) => (
                  <li key={category}>
                    <div className="px-4 py-1.5">
                      <span className="text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
                        {category}
                      </span>
                    </div>
                    {items.map((item) => {
                      const globalIndex = flatFiltered.indexOf(item);
                      const isActive = globalIndex === activeIndex;
                      const Icon = item.icon;

                      return (
                        <button
                          key={item.id}
                          role="option"
                          aria-selected={isActive}
                          onClick={item.action}
                          onMouseEnter={() => {
                            setActiveIndex(globalIndex);
                          }}
                          className={cn(
                            "flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors",
                            isActive ? "bg-white/[0.06]" : "hover:bg-white/[0.03]",
                          )}
                        >
                          <div
                            className={cn(
                              "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border",
                              isActive
                                ? "border-violet-500/40 bg-violet-950/50 text-violet-400"
                                : "border-white/10 bg-white/5 text-zinc-500",
                            )}
                          >
                            <Icon className="h-4 w-4" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <p
                              className={cn(
                                "text-sm font-medium",
                                isActive ? "text-white" : "text-zinc-300",
                              )}
                            >
                              {item.label}
                            </p>
                            {item.description && (
                              <p className="truncate text-xs text-zinc-600">{item.description}</p>
                            )}
                          </div>
                          {isActive && <ChevronRight className="h-4 w-4 shrink-0 text-zinc-600" />}
                        </button>
                      );
                    })}
                  </li>
                ))}

                {flatFiltered.length === 0 && (
                  <li className="flex items-center justify-center py-12 text-sm text-zinc-600">
                    No commands found for &ldquo;{query}&rdquo;
                  </li>
                )}
              </ul>

              {/* Footer */}
              <div className="flex items-center gap-4 border-t border-white/10 px-4 py-2">
                {[
                  { keys: ["↑", "↓"], label: "navigate" },
                  { keys: ["↵"], label: "select" },
                  { keys: ["ESC"], label: "close" },
                ].map(({ keys, label }) => (
                  <div key={label} className="flex items-center gap-1">
                    {keys.map((k) => (
                      <kbd
                        key={k}
                        className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[9px] text-zinc-600"
                      >
                        {k}
                      </kbd>
                    ))}
                    <span className="text-[10px] text-zinc-700">{label}</span>
                  </div>
                ))}
                <div className="ml-auto flex items-center gap-1 text-zinc-700">
                  <Command className="h-3 w-3" />
                  <span className="text-[10px]">K to open</span>
                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

export function useCommandPalette() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((p) => !p);
      }
    };
    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
    };
  }, []);

  return {
    open,
    setOpen,
    onClose: () => {
      setOpen(false);
    },
  };
}
