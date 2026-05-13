import Link from "next/link";

export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-background">
      <div className="mx-auto max-w-4xl px-6 text-center">
        <div className="mb-6 inline-flex items-center rounded-full border border-border bg-muted px-4 py-1.5 text-sm text-muted-foreground">
          Multi-Agent AI Operating System
        </div>
        <h1 className="mb-6 text-6xl font-bold tracking-tight text-foreground">
          LuxAI
        </h1>
        <p className="mb-10 text-xl text-muted-foreground">
          Enterprise-grade multi-agent orchestration. Build, deploy, and monitor
          intelligent agent workflows at scale.
        </p>
        <div className="flex items-center justify-center gap-4">
          <Link
            href="/dashboard"
            className="inline-flex h-11 items-center justify-center rounded-md bg-primary px-8 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Open Dashboard
          </Link>
          <Link
            href="/agents"
            className="inline-flex h-11 items-center justify-center rounded-md border border-input bg-background px-8 text-sm font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            Browse Agents
          </Link>
        </div>
      </div>
    </main>
  );
}
