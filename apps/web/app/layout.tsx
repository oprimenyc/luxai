import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Providers } from "./providers";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "LuxAI — Multi-Agent Operating System",
    template: "%s | LuxAI",
  },
  description:
    "Enterprise-grade multi-agent AI orchestration platform for intelligent automation at scale.",
  keywords: ["AI", "multi-agent", "LangGraph", "automation", "orchestration"],
  authors: [{ name: "LuxAI" }],
  creator: "LuxAI",
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_APP_URL ?? "https://luxai.app"
  ),
  openGraph: {
    type: "website",
    locale: "en_US",
    title: "LuxAI — Multi-Agent Operating System",
    description: "Enterprise-grade multi-agent AI orchestration platform.",
    siteName: "LuxAI",
  },
  twitter: {
    card: "summary_large_image",
    title: "LuxAI",
    description: "Enterprise-grade multi-agent AI orchestration platform.",
  },
  robots: {
    index: true,
    follow: true,
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#09090b" },
  ],
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-background font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
