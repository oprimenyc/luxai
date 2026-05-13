export type AgentStatus = "idle" | "running" | "paused" | "error" | "terminated";

export type AgentCapability =
  | "web_search"
  | "code_execution"
  | "file_operations"
  | "database_query"
  | "email"
  | "calendar";

export interface Agent {
  id: string;
  userId: string;
  name: string;
  description: string;
  capabilities: AgentCapability[];
  systemPrompt: string;
  model: string;
  temperature: number;
  maxTokens: number;
  status: AgentStatus;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface AgentCreate {
  name: string;
  description: string;
  capabilities?: AgentCapability[];
  systemPrompt?: string;
  model?: string;
  temperature?: number;
  maxTokens?: number;
  metadata?: Record<string, unknown>;
}

export interface AgentUpdate extends Partial<AgentCreate> {}

export interface AgentListResponse {
  agents: Agent[];
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
}
