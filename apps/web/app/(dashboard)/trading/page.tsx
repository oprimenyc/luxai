import type { Metadata } from "next";
import { TradingClient } from "./trading-client";

export const metadata: Metadata = {
  title: "Paper Trading | LuxAI",
  description: "Deterministic paper trading execution console",
};

export default function TradingPage() {
  return <TradingClient />;
}
