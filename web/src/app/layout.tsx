import type { Metadata } from "next";
import Link from "next/link";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
});
const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "Eli — post-op care",
  description: "Clinician view for post-op voice check-ins",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrains.variable} h-full`}>
      <body className="flex min-h-full flex-col font-sans">
        <header className="sticky top-0 z-20 border-b border-border bg-background/80 backdrop-blur-md">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
            <Link href="/" className="flex items-center gap-2.5">
              <span className="grid h-7 w-7 place-items-center rounded-md bg-primary text-sm font-bold text-primary-foreground shadow-2xs">
                e
              </span>
              <span className="text-lg font-semibold tracking-tight text-foreground">
                Eli
              </span>
              <span className="hidden text-sm text-muted-foreground sm:inline">
                post-op care
              </span>
            </Link>
            <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-primary" />
              clinician console
            </span>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">{children}</main>
        <footer className="mx-auto w-full max-w-5xl px-6 py-8 text-xs text-muted-foreground">
          Eli · voice check-ins for recovering patients
        </footer>
      </body>
    </html>
  );
}
