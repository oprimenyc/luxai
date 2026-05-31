import { Metadata } from "next";
import { WorkbenchClient } from "./workbench-client";

export const metadata: Metadata = {
  title: "Workbench — .fylr",
  description: "Trade Idea Workbench — tip to affordable, risk-scored options recommendation",
};

export default function WorkbenchPage() {
  return <WorkbenchClient />;
}
