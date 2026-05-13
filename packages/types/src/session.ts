export type SessionStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type MessageRole = "system" | "user" | "assistant" | "tool";

export interface Message {
  role: MessageRole;
  content: string;
  toolCalls?: Record<string, unknown>[];
  toolCallId?: string;
  timestamp: string;
}

export interface Session {
  id: string;
  userId: string;
  agentId: string;
  task: string;
  context: Record<string, unknown>;
  status: SessionStatus;
  messages: Message[];
  result: Record<string, unknown> | null;
  error: string | null;
  startedAt: string | null;
  completedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface SessionCreate {
  agentId: string;
  task: string;
  context?: Record<string, unknown>;
}
