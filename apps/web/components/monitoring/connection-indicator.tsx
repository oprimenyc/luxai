"use client";

import { motion } from "framer-motion";
import type { ConnectionState } from "@/lib/websocket/client";
import { cn } from "@/lib/utils";

interface ConnectionIndicatorProps {
  state: ConnectionState;
  className?: string;
}

const STATE_CONFIG: Record<
  ConnectionState,
  { label: string; dotClass: string; textClass: string }
> = {
  connected: {
    label: "Live",
    dotClass: "bg-emerald-400",
    textClass: "text-emerald-400",
  },
  connecting: {
    label: "Connecting",
    dotClass: "bg-amber-400 animate-pulse",
    textClass: "text-amber-400",
  },
  reconnecting: {
    label: "Reconnecting",
    dotClass: "bg-amber-400 animate-pulse",
    textClass: "text-amber-400",
  },
  disconnected: {
    label: "Offline",
    dotClass: "bg-zinc-600",
    textClass: "text-zinc-600",
  },
};

export function ConnectionIndicator({ state, className }: ConnectionIndicatorProps) {
  const config = STATE_CONFIG[state];

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="relative flex items-center justify-center">
        {state === "connected" && (
          <motion.div
            className="absolute h-3 w-3 rounded-full bg-emerald-400"
            animate={{ scale: [1, 1.8, 1], opacity: [0.6, 0, 0.6] }}
            transition={{ duration: 2, repeat: Infinity }}
          />
        )}
        <div className={cn("h-2 w-2 rounded-full", config.dotClass)} />
      </div>
      <span className={cn("text-xs font-medium", config.textClass)}>{config.label}</span>
    </div>
  );
}
