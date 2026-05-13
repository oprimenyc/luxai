import { createSupabaseServerClient } from "@luxai/supabase/server";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

export default async function DashboardLayout({
  children,
}: {
  children: ReactNode;
}) {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/login");

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <aside className="hidden w-64 border-r border-border bg-card lg:flex lg:flex-col">
        <div className="flex h-16 items-center border-b border-border px-6">
          <span className="text-lg font-semibold tracking-tight">LuxAI</span>
        </div>
        <nav className="flex-1 overflow-y-auto px-4 py-6">
          <ul className="space-y-1">
            {[
              { href: "/dashboard", label: "Overview" },
              { href: "/agents", label: "Agents" },
              { href: "/sessions", label: "Sessions" },
              { href: "/monitoring", label: "Monitoring" },
              { href: "/settings", label: "Settings" },
            ].map((item) => (
              <li key={item.href}>
                <a
                  href={item.href}
                  className="flex items-center rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                >
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="border-t border-border p-4">
          <p className="truncate text-xs text-muted-foreground">{user.email}</p>
        </div>
      </aside>
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-16 items-center border-b border-border bg-card px-6">
          <h1 className="text-sm font-medium text-muted-foreground">
            Dashboard
          </h1>
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
