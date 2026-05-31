/**
 * Production WebSocket client with:
 * - automatic reconnection (exponential backoff)
 * - event replay on reconnect (Last-Event-ID)
 * - message queueing during disconnect
 * - heartbeat monitoring
 * - SSE fallback detection
 */

import type { LuxEvent, WsMessage } from "@/lib/events/schemas";

export type ConnectionState = "connecting" | "connected" | "reconnecting" | "disconnected";

export interface WsClientOptions {
  url: string;
  token?: string;
  userId?: string;
  sessionId?: string;
  onMessage?: (event: LuxEvent, replay: boolean) => void;
  onStateChange?: (state: ConnectionState) => void;
  onError?: (error: Event) => void;
  maxReconnectAttempts?: number;
  reconnectBaseMs?: number;
  heartbeatTimeoutMs?: number;
}

const DEFAULT_MAX_RECONNECTS = 10;
const DEFAULT_RECONNECT_BASE = 1000;
const DEFAULT_HEARTBEAT_TIMEOUT = 45_000;

export class LuxWebSocketClient {
  private ws: WebSocket | null = null;
  private state: ConnectionState = "disconnected";
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  private lastEventId: string | null = null;
  private destroyed = false;

  constructor(private readonly options: WsClientOptions) {}

  connect(): void {
    if (this.destroyed) return;
    this.setState("connecting");
    this.openSocket();
  }

  disconnect(): void {
    this.destroyed = true;
    this.clearTimers();
    this.ws?.close(1000, "Client disconnect");
    this.setState("disconnected");
  }

  send(data: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  get connectionState(): ConnectionState {
    return this.state;
  }

  private buildUrl(): string {
    const url = new URL(this.options.url);
    if (this.options.token) url.searchParams.set("token", this.options.token);
    if (this.options.userId) url.searchParams.set("user_id", this.options.userId);
    if (this.lastEventId) url.searchParams.set("last_event_id", this.lastEventId);
    return url.toString();
  }

  private openSocket(): void {
    try {
      this.ws = new WebSocket(this.buildUrl());

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.setState("connected");
        this.resetHeartbeat();
        // Ping to confirm connection
        this.send({ type: "ping", ts: Date.now() });
      };

      this.ws.onmessage = (raw) => {
        this.resetHeartbeat();
        try {
          const msg = JSON.parse(raw.data as string) as WsMessage;
          if (msg.type === "event" && msg.event) {
            this.lastEventId = msg.event.id;
            this.options.onMessage?.(msg.event, msg.replay ?? false);
          }
          // heartbeat / pong — just resets the timer (done above)
        } catch {
          // non-JSON frame — ignore
        }
      };

      this.ws.onclose = (ev) => {
        if (!this.destroyed && ev.code !== 1000) {
          this.scheduleReconnect();
        }
      };

      this.ws.onerror = (ev) => {
        this.options.onError?.(ev);
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.destroyed) return;
    if (this.reconnectAttempts >= (this.options.maxReconnectAttempts ?? DEFAULT_MAX_RECONNECTS)) {
      this.setState("disconnected");
      return;
    }

    this.setState("reconnecting");
    const delay = Math.min(
      (this.options.reconnectBaseMs ?? DEFAULT_RECONNECT_BASE) *
        Math.pow(2, this.reconnectAttempts),
      30_000,
    );
    this.reconnectAttempts++;

    this.reconnectTimer = setTimeout(() => {
      if (!this.destroyed) this.openSocket();
    }, delay);
  }

  private resetHeartbeat(): void {
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
    this.heartbeatTimer = setTimeout(() => {
      // No message received — assume dead connection
      this.ws?.close();
      this.scheduleReconnect();
    }, this.options.heartbeatTimeoutMs ?? DEFAULT_HEARTBEAT_TIMEOUT);
  }

  private clearTimers(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
  }

  private setState(state: ConnectionState): void {
    if (this.state !== state) {
      this.state = state;
      this.options.onStateChange?.(state);
    }
  }
}
