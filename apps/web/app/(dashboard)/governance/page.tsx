import type { Metadata } from "next";
import { GovernanceClient } from "./governance-client";

export const metadata: Metadata = { title: "Governance" };
export default function GovernancePage() {
  return <GovernanceClient />;
}
