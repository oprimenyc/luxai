"use client";

import { useEffect, useState } from "react";
import type { LuxEvent } from "@/lib/events/schemas";

export interface PendingApproval {
  approvalId: string;
  sessionId: string;
  agentId: string;
  riskScore: number;
  riskLevel: "low" | "medium" | "high" | "critical";
  action: string;
  expiresAt: string;
}

export function usePendingApprovals(events: LuxEvent[]): PendingApproval[] {
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);

  useEffect(() => {
    const resolved = new Set(
      events
        .filter(
          (e) =>
            e.type === "governance.approval_granted" ||
            e.type === "governance.approval_denied",
        )
        .map((e) => e.payload["approval_id"] as string),
    );

    const pending = events
      .filter((e) => e.type === "governance.approval_required")
      .map((e) => ({
        approvalId: e.payload["approval_id"] as string,
        sessionId: e.session_id ?? "",
        agentId: e.agent_id ?? "",
        riskScore: e.payload["risk_score"] as number,
        riskLevel: e.payload["risk_level"] as PendingApproval["riskLevel"],
        action: e.payload["action"] as string,
        expiresAt: e.payload["expires_at"] as string,
      }))
      .filter((a) => !resolved.has(a.approvalId));

    setApprovals(pending);
  }, [events]);

  return approvals;
}

export function useKillSwitchEvents(events: LuxEvent[]) {
  return events.filter((e) => e.type === "governance.kill_switch");
}
