"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log the error to an error reporting service
    console.error("Global Error Boundary caught an error:", error);
  }, [error]);

  return (
    <html lang="en">
      <body className="flex min-h-screen items-center justify-center bg-zinc-950 p-6 text-white">
        <div className="w-full max-w-md space-y-4 rounded-xl border border-red-500/30 bg-zinc-900/60 p-6 text-center shadow-2xl shadow-red-900/10">
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-red-500/10 text-red-500">
            <svg
              className="h-6 w-6"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
          </div>
          <h2 className="text-lg font-medium tracking-wide text-red-400">
            Critical System Failure
          </h2>
          <p className="text-sm text-zinc-400">
            The application encountered an unrecoverable error. Please reset the session or contact
            the administrator.
          </p>
          <div className="pt-4">
            <button
              onClick={() => reset()}
              className="w-full rounded-lg border border-red-500/30 bg-red-500/10 px-6 py-2.5 text-sm font-medium uppercase tracking-wider text-red-400 transition-colors hover:bg-red-500/20"
            >
              Restart System
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
