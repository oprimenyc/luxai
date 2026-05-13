/**
 * TypeScript event contracts mirroring the Python event models.
 * These are the wire types received over WebSocket / SSE.
 */

export type EventSeverity = "debug" | "info" | "warning" | "error" | "critical";

export type EventType =
  // Agent lifecycle
  | "agent.created"
  | "agent.updated"
  | "agent.deleted"
  | "agent.status_changed"
  // Session lifecycle
  | "session.created"
  | "session.started"
  | "session.completed"
  | "session.failed"
  | "session.cancelled"
  // Orchestration
  | "graph.node_entered"
  | "graph.node_exited"
  | "graph.edge_traversed"
  | "graph.completed"
  // Telemetry
  | "telemetry.token_usage"
  | "telemetry.latency"
  | "telemetry.retry"
  // Memory
  | "memory.stored"
  | "memory.retrieved"
  | "memory.evicted"
  // Governance
  | "governance.approval_required"
  | "governance.approval_granted"
  | "governance.approval_denied"
  | "governance.kill_switch"
  | "governance.risk_flagged"
  // Workflow
  | "workflow.created"
  | "workflow.step_started"
  | "workflow.step_completed"
  | "workflow.checkpoint"
  | "workflow.recovered"
  // System
  | "system.heartbeat"
  | "system.error";

export interface LuxEvent {
  id: string;
  type: EventType;
  severity: EventSeverity;
  timestamp: string;
  session_id: string | null;
  agent_id: string | null;
  user_id: string | null;
  correlation_id: string | null;
  payload: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface WsMessage {
  type: "event" | "heartbeat" | "pong" | "error";
  replay?: boolean;
  event?: LuxEvent;
  connections?: number;
  ts?: number;
}

// ── Typed payload helpers ─────────────────────────────────────────────────────

export interface GraphNodePayload {
  node_name: string;
  iteration: number;
  duration_ms?: number;
  output_preview?: string;
}

export interface TokenUsagePayload {
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd?: number;
}

export interface RetryPayload {
  attempt: number;
  max_attempts: number;
  error: string;
  backoff_ms: number;
}

export interface ApprovalPayload {
  approval_id: string;
  risk_score: number;
  risk_level: "low" | "medium" | "high" | "critical";
  policy_name: string;
  action: string;
  expires_at: string;
}

export interface MemoryPayload {
  memory_id: string;
  memory_type: string;
  content_preview: string;
}

// ── Event categories for filtering ───────────────────────────────────────────

export const ORCHESTRATION_EVENTS: EventType[] = [
  "graph.node_entered",
  "graph.node_exited",
  "graph.edge_traversed",
  "graph.completed",
];

export const SESSION_EVENTS: EventType[] = [
  "session.created",
  "session.started",
  "session.completed",
  "session.failed",
  "session.cancelled",
];

export const GOVERNANCE_EVENTS: EventType[] = [
  "governance.approval_required",
  "governance.approval_granted",
  "governance.approval_denied",
  "governance.kill_switch",
  "governance.risk_flagged",
];

export const TELEMETRY_EVENTS: EventType[] = [
  "telemetry.token_usage",
  "telemetry.latency",
  "telemetry.retry",
];
