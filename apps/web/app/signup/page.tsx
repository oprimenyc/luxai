"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { createBrowserClient } from "@supabase/ssr";
import { Zap } from "lucide-react";

const supabase = createBrowserClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
);

function SignUpForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { error } = await supabase.auth.signUp({ email, password });
    setLoading(false);
    if (error) setError(error.message);
    else setDone(true);
  }

  if (done) {
    return (
      <div className="rounded-xl border border-emerald-800/40 bg-emerald-950/30 px-6 py-5 text-center">
        <p className="text-sm font-medium text-emerald-400">Check your email</p>
        <p className="mt-1 text-xs text-zinc-500">Confirmation link sent to {email}.</p>
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        void handleSubmit(e);
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
          required
          minLength={8}
          autoComplete="new-password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
          }}
          placeholder="min 8 characters"
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
        {loading ? "Creating account…" : "Create account"}
      </button>

      <p className="text-center text-xs text-zinc-600">
        Already have an account?{" "}
        <Link href="/login" className="text-zinc-400 hover:text-zinc-200">
          Sign in
        </Link>
      </p>
    </form>
  );
}

export default function SignUpPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-10 flex flex-col items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-violet-800 shadow-lg shadow-violet-900/50">
            <Zap className="h-5 w-5 text-white" />
          </div>
          <div className="text-center">
            <p className="text-xs font-semibold uppercase tracking-widest text-zinc-600">.fylr</p>
            <h1 className="mt-0.5 text-lg font-bold text-white">Create account</h1>
          </div>
        </div>

        <Suspense fallback={<div className="h-48 animate-pulse rounded-xl bg-white/5" />}>
          <SignUpForm />
        </Suspense>

        <p className="mt-6 text-center text-[10px] text-zinc-700">
          Shadow mode active — paper trading only
        </p>
      </div>
    </div>
  );
}
