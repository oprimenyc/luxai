/**
 * Typed HTTP client for the LuxAI orchestrator service.
 * Handles SSE streaming, retries, and auth headers.
 */

export interface OrchestratorClientConfig {
  baseUrl: string;
  apiKey?: string;
  timeout?: number;
}

export interface RunAgentParams {
  task: string;
  agentId: string;
  sessionId?: string;
  context?: Record<string, unknown>;
  maxIterations?: number;
  model?: string;
  stream?: boolean;
}

export interface RunAgentResult {
  sessionId: string;
  result: string;
  iterations: number;
  status: string;
}

export class OrchestratorClient {
  private readonly baseUrl: string;
  private readonly apiKey: string | undefined;
  private readonly timeout: number;

  constructor(config: OrchestratorClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, "");
    this.apiKey = config.apiKey;
    this.timeout = config.timeout ?? 300_000;
  }

  private buildHeaders(): HeadersInit {
    const headers: HeadersInit = { "Content-Type": "application/json" };
    if (this.apiKey) headers["X-Orchestrator-Key"] = this.apiKey;
    return headers;
  }

  async run(params: RunAgentParams): Promise<RunAgentResult> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await fetch(`${this.baseUrl}/run`, {
        method: "POST",
        headers: this.buildHeaders(),
        body: JSON.stringify({
          task: params.task,
          agent_id: params.agentId,
          session_id: params.sessionId,
          context: params.context ?? {},
          max_iterations: params.maxIterations ?? 10,
          model: params.model ?? "gpt-4o",
          stream: false,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const error = (await response.json()) as { detail?: string };
        throw new Error(error.detail ?? `Orchestrator error: ${response.status}`);
      }

      return (await response.json()) as RunAgentResult;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  async *stream(params: RunAgentParams): AsyncGenerator<string, void, unknown> {
    const response = await fetch(`${this.baseUrl}/run`, {
      method: "POST",
      headers: this.buildHeaders(),
      body: JSON.stringify({ ...params, stream: true }),
    });

    if (!response.ok || !response.body) {
      throw new Error(`Stream error: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6).trim();
            if (data === "[DONE]") return;
            yield data;
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  async healthCheck(): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl}/health`, { method: "GET" });
      return response.ok;
    } catch {
      return false;
    }
  }
}
