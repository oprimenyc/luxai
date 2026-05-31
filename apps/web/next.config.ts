import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,

  // ESLint errors in websocket lib are tracked separately; don't block deploys.
  // Lint still enforced in CI (ci.yml lint-api / typecheck-lint jobs).
  eslint: { ignoreDuringBuilds: true },

  allowedDevOrigins: ["*"],

  images: {
    formats: ["image/avif", "image/webp"],
    remotePatterns: [
      {
        protocol: "https",
        hostname: "*.supabase.co",
      },
    ],
  },

  headers: async () => [
    {
      source: "/(.*)",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "SAMEORIGIN" },
        { key: "X-XSS-Protection", value: "1; mode=block" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        {
          key: "Permissions-Policy",
          value: "camera=(), microphone=(), geolocation=()",
        },
        {
          key: "Content-Security-Policy",
          value: [
            "default-src 'self'",
            "script-src 'self' 'unsafe-eval' 'unsafe-inline'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' blob: data: https://*.supabase.co",
            "connect-src 'self' https://*.supabase.co wss://*.supabase.co https://luxai-api.fly.dev",
            "font-src 'self'",
          ].join("; "),
        },
      ],
    },
  ],
};

export default config;
