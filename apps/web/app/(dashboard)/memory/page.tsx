import type { Metadata } from "next";
import { MemoryClient } from "./memory-client";

export const metadata: Metadata = { title: "Memory" };
export default function MemoryPage() {
  return <MemoryClient />;
}
