"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ConnectionState } from "./client";
import { LuxWebSocketClient } from "./client";
import type { EventType, LuxEvent } from "@/lib/events/schemas";

// Use the backend API URL, not the frontend host.
// NEXT_PUBLIC_API_URL = "https://luxai-api.fly.dev" in production.
// Replace http(s):// with ws(s):// so WebSocket connects to the API server.
const _API_ORIGIN = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const WS_BASE_URL =
  typeof window !== "undefined"
    ? _API_ORIGIN.replace(/^https(?=:\/\/)/, "wss").replace(/^http(?=:\/\/)/, "ws")
    : "ws://localhost:8000";

export interface UseEventStreamOptions {
  sessionId?: string;
  eventTypes?: EventType[];
  maxEvents?: number;
  enabled?: boolean;
  token?: string;
  userId?: string;
}

export interface UseEventStreamResult {
  events: LuxEvent[];
  connectionState: ConnectionState;
  latestEvent: LuxEvent | null;
  clearEvents: () => void;
  isConnected: boolean;
}

export function useEventStream({
  sessionId,
  eventTypes,
  maxEvents = 500,
  enabled = true,
  token,
  userId,
}: UseEventStreamOptions = {}): UseEventStreamResult {
  const [events, setEvents] = useState<LuxEvent[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  const [latestEvent, setLatestEvent] = useState<LuxEvent | null>(null);
  const clientRef = useRef<LuxWebSocketClient | null>(null);

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  useEffect(() => {
    if (!enabled) return;

    // Backend routes (prefix="/api/v1" in main.py):
    //   /api/v1/events         — global event stream
    //   /api/v1/sessions/{id}  — session-scoped stream
    const url = sessionId
      ? `${WS_BASE_URL}/api/v1/sessions/${sessionId}`
      : `${WS_BASE_URL}/api/v1/events`;

    const client = new LuxWebSocketClient({
      url,
      token,
      userId,
      onMessage: (event, _replay) => {
        if (eventTypes && !eventTypes.includes(event.type)) return;
        setLatestEvent(event);
        setEvents((prev) => {
          const next = [event, ...prev];
          return next.length > maxEvents ? next.slice(0, maxEvents) : next;
        });
      },
      onStateChange: setConnectionState,
    });

    clientRef.current = client;
    client.connect();

    return () => {
      client.disconnect();
      clientRef.current = null;
    };
  }, [enabled, sessionId, token, userId, maxEvents]);

  return {
    events,
    connectionState,
    latestEvent,
    clearEvents,
    isConnected: connectionState === "connected",
  };
}

// ── Derived hooks ─────────────────────────────────────────────────────────────

export interface TokenMetrics {
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCostUsd: number;
  byModel: Record<string, { input: number; output: number; cost: number }>;
}

export function useTokenMetrics(events: LuxEvent[]): TokenMetrics {
  const tokenEvents = events.filter((e) => e.type === "telemetry.token_usage");
  const byModel: TokenMetrics["byModel"] = {};
  let totalInput = 0;
  let totalOutput = 0;
  let totalCost = 0;

  for (const ev of tokenEvents) {
    const p = ev.payload as Record<string, number>;
    const rawModel = ev.payload.model;
    const model = typeof rawModel === "string" ? rawModel : "unknown";
    const input = p.input_tokens ?? 0;
    const output = p.output_tokens ?? 0;
    const cost = p.cost_usd ?? 0;

    totalInput += input;
    totalOutput += output;
    totalCost += cost;

    byModel[model] ??= { input: 0, output: 0, cost: 0 };
    byModel[model].input += input;
    byModel[model].output += output;
    byModel[model].cost += cost;
  }

  return {
    totalInputTokens: totalInput,
    totalOutputTokens: totalOutput,
    totalCostUsd: totalCost,
    byModel,
  };
}

interface NodeEntry {
  name: string;
  enteredAt: string;
  exitedAt?: string;
  durationMs?: number;
}

export function useGraphNodes(events: LuxEvent[]) {
  const nodes: NodeEntry[] = [];
  const map: Record<string, NodeEntry> = {};

  for (const ev of [...events].reverse()) {
    const rawName = ev.payload.node_name;
    const name = typeof rawName === "string" ? rawName : "";
    if (!name) continue;

    if (ev.type === "graph.node_entered") {
      const entry: NodeEntry = { name, enteredAt: ev.timestamp };
      map[name] = entry;
      nodes.push(entry);
    } else if (ev.type === "graph.node_exited" && map[name]) {
      map[name].exitedAt = ev.timestamp;
      map[name].durationMs = Number(ev.payload.duration_ms ?? 0);
    }
  }

  return nodes;
}

export function useActiveSession(events: LuxEvent[]): string | null {
  const started = events.find((e) => e.type === "session.started");
  const ended = events.find((e) => e.type === "session.completed" || e.type === "session.failed");
  if (started && !ended) return started.session_id;
  return null;
}
