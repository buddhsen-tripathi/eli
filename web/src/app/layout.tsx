import type { Metadata } from "next";
import Link from "next/link";
import { Fraunces, Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  axes: ["SOFT", "opsz"],
});

export const metadata: Metadata = {
  title: "arya — post-op care",
  description: "Clinician view for post-op voice check-ins",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${fraunces.variable} h-full`}
    >
      <body className="flex min-h-full flex-col">
        <header className="sticky top-0 z-20 border-b border-line/80 bg-paper/80 backdrop-blur-md">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
            <Link href="/" className="group flex items-center gap-2.5">
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-sage font-display text-sm font-semibold text-white shadow-sm">
                a
              </span>
              <span className="font-display text-lg font-medium tracking-tight text-ink">
                arya
              </span>
              <span className="hidden text-sm text-muted sm:inline">
                post-op care
              </span>
            </Link>
            <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-faint">
              <span className="h-1.5 w-1.5 rounded-full bg-sage" />
              clinician console
            </span>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">{children}</main>
        <footer className="mx-auto w-full max-w-5xl px-6 py-8 text-xs text-faint">
          arya · voice check-ins for recovering patients
        </footer>
      </body>
    </html>
  );
}
