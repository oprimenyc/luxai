import { createSupabaseServerClient } from "@luxai/supabase/server";

export default async function DashboardPage() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Overview</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Welcome back, {user?.email}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Active Agents", value: "0" },
          { label: "Running Sessions", value: "0" },
          { label: "Tasks Completed", value: "0" },
          { label: "Avg. Latency", value: "—" },
        ].map((stat) => (
          <div
            key={stat.label}
            className="rounded-lg border border-border bg-card p-6"
          >
            <p className="text-sm font-medium text-muted-foreground">
              {stat.label}
            </p>
            <p className="mt-2 text-3xl font-bold tracking-tight">
              {stat.value}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
