import Link from "next/link";

export default function HomePage() {
  return (
    <main className="bg-background flex min-h-screen flex-col items-center justify-center">
      <div className="mx-auto max-w-4xl px-6 text-center">
        <div className="border-border bg-muted text-muted-foreground mb-6 inline-flex items-center rounded-full border px-4 py-1.5 text-sm">
          Multi-Agent AI Operating System
        </div>
        <h1 className="text-foreground mb-6 text-6xl font-bold tracking-tight">LuxAI</h1>
        <p className="text-muted-foreground mb-10 text-xl">
          Enterprise-grade multi-agent orchestration. Build, deploy, and monitor intelligent agent
          workflows at scale.
        </p>
        <div className="flex items-center justify-center gap-4">
          <Link
            href="/dashboard"
            className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex h-11 items-center justify-center rounded-md px-8 text-sm font-medium transition-colors"
          >
            Open Dashboard
          </Link>
          <Link
            href="/agents"
            className="border-input bg-background text-foreground hover:bg-accent hover:text-accent-foreground inline-flex h-11 items-center justify-center rounded-md border px-8 text-sm font-medium transition-colors"
          >
            Browse Agents
          </Link>
        </div>
      </div>
    </main>
  );
}
