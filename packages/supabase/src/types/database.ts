/**
 * Supabase database type definitions.
 * Regenerate with: supabase gen types typescript --project-id <project-id> > src/types/database.ts
 */
export type Json = string | number | boolean | null | { [key: string]: Json } | Json[];

export interface Database {
  public: {
    Tables: {
      agents: {
        Row: {
          id: string;
          user_id: string;
          name: string;
          description: string;
          capabilities: string[];
          system_prompt: string;
          model: string;
          temperature: number;
          max_tokens: number;
          status: "idle" | "running" | "paused" | "error" | "terminated";
          metadata: Json;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?: string;
          user_id: string;
          name: string;
          description: string;
          capabilities?: string[];
          system_prompt?: string;
          model?: string;
          temperature?: number;
          max_tokens?: number;
          status?: "idle" | "running" | "paused" | "error" | "terminated";
          metadata?: Json;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          name?: string;
          description?: string;
          capabilities?: string[];
          system_prompt?: string;
          model?: string;
          temperature?: number;
          max_tokens?: number;
          status?: "idle" | "running" | "paused" | "error" | "terminated";
          metadata?: Json;
          updated_at?: string;
        };
      };
      sessions: {
        Row: {
          id: string;
          user_id: string;
          agent_id: string;
          task: string;
          context: Json;
          status: "pending" | "running" | "completed" | "failed" | "cancelled";
          messages: Json;
          result: Json | null;
          error: string | null;
          started_at: string | null;
          completed_at: string | null;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?: string;
          user_id: string;
          agent_id: string;
          task: string;
          context?: Json;
          status?: "pending" | "running" | "completed" | "failed" | "cancelled";
          messages?: Json;
          result?: Json | null;
          error?: string | null;
          started_at?: string | null;
          completed_at?: string | null;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          status?: "pending" | "running" | "completed" | "failed" | "cancelled";
          messages?: Json;
          result?: Json | null;
          error?: string | null;
          started_at?: string | null;
          completed_at?: string | null;
          updated_at?: string;
        };
      };
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
    Enums: {
      agent_status: "idle" | "running" | "paused" | "error" | "terminated";
      session_status: "pending" | "running" | "completed" | "failed" | "cancelled";
    };
  };
}
