"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createBrowserClient } from "@supabase/ssr";
import { Zap } from "lucide-react";

const supabase = createBrowserClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
);

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const redirect = params.get("redirect") ?? "/dashboard";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [magicSent, setMagicSent] = useState(false);

  async function handlePassword(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (error) {
      setError(error.message);
    } else {
      router.push(redirect);
      router.refresh();
    }
  }

  async function handleMagicLink(e: React.MouseEvent) {
    e.preventDefault();
    if (!email) {
      setError("Enter your email first.");
      return;
    }
    setError(null);
    setLoading(true);
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${window.location.origin}${redirect}` },
    });
    setLoading(false);
    if (error) setError(error.message);
    else setMagicSent(true);
  }

  if (magicSent) {
    return (
      <div className="rounded-xl border border-emerald-800/40 bg-emerald-950/30 px-6 py-5 text-center">
        <p className="text-sm font-medium text-emerald-400">Magic link sent</p>
        <p className="mt-1 text-xs text-zinc-500">Check {email} — click the link to sign in.</p>
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        void handlePassword(e);
      }}
      className="space-y-4"
    >
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-zinc-500">Email</label>
        <input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value);
          }}
          placeholder="you@domain.com"
          className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-zinc-200 placeholder:text-zinc-700 focus:border-white/20 focus:outline-none focus:ring-1 focus:ring-white/20"
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium text-zinc-500">Password</label>
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
          }}
          placeholder="••••••••"
          className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-zinc-200 placeholder:text-zinc-700 focus:border-white/20 focus:outline-none focus:ring-1 focus:ring-white/20"
        />
      </div>

      {error && (
        <p className="rounded-lg border border-red-900/40 bg-red-950/30 px-3 py-2 text-xs text-red-400">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-zinc-950 transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {loading ? "Signing in…" : "Sign in"}
      </button>

      <div className="relative">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-white/10" />
        </div>
        <div className="relative flex justify-center">
          <span className="bg-zinc-950 px-2 text-xs text-zinc-700">or</span>
        </div>
      </div>

      <button
        type="button"
        onClick={(e) => {
          void handleMagicLink(e);
        }}
        disabled={loading}
        className="w-full rounded-lg border border-white/10 px-4 py-2.5 text-sm text-zinc-400 transition-colors hover:border-white/20 hover:text-zinc-200 disabled:opacity-50"
      >
        Send magic link
      </button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950 px-4">
      <div className="w-full max-w-sm">
        {/* Wordmark */}
        <div className="mb-10 flex flex-col items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-violet-800 shadow-lg shadow-violet-900/50">
            <Zap className="h-5 w-5 text-white" />
          </div>
          <div className="text-center">
            <p className="text-xs font-semibold uppercase tracking-widest text-zinc-600">.fylr</p>
            <h1 className="mt-0.5 text-lg font-bold text-white">LuxAI OS</h1>
          </div>
        </div>

        <Suspense fallback={<div className="h-48 animate-pulse rounded-xl bg-white/5" />}>
          <LoginForm />
        </Suspense>

        <p className="mt-6 text-center text-[10px] text-zinc-700">
          Shadow mode active — paper trading only
        </p>
      </div>
    </div>
  );
}
