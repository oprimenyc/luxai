import type { Metadata } from "next";
import { WorkflowsClient } from "./workflows-client";

export const metadata: Metadata = { title: "Workflows" };
export default function WorkflowsPage() {
  return <WorkflowsClient />;
}
