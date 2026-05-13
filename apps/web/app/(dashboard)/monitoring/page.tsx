import type { Metadata } from "next";
import { MonitoringClient } from "./monitoring-client";

export const metadata: Metadata = {
  title: "Monitoring",
  description: "Realtime agent orchestration monitoring",
};

export default function MonitoringPage() {
  return <MonitoringClient />;
}
