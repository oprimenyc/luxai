// Server component — no client boundary, no manifest required.
// Redirects the bare route-group index to /dashboard so the
// (dashboard) layout wraps the real overview page.
import { redirect } from "next/navigation";

export default function DashboardGroupIndex() {
  redirect("/dashboard");
}
