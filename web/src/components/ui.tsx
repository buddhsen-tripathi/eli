import type { ReactNode } from "react";

import type { Triage, TriageLevel } from "@/lib/api";
import { TRIAGE_META } from "@/lib/format";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-2xl border border-line bg-card shadow-[0_1px_2px_rgb(var(--shadow)/0.04),0_8px_24px_-12px_rgb(var(--shadow)/0.10)] ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-faint">
      {children}
    </h2>
  );
}

export function TriageBadge({
  triage,
  size = "sm",
}: {
  triage: Triage | null;
  size?: "sm" | "lg";
}) {
  const pad = size === "lg" ? "px-3 py-1 text-sm" : "px-2.5 py-0.5 text-xs";
  if (!triage) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-full border border-line text-faint ${pad}`}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-faint" />
        No triage
      </span>
    );
  }
  const m = TRIAGE_META[triage.level as TriageLevel] ?? TRIAGE_META.monitor;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-medium ${m.bg} ${m.text} ${m.border} ${pad}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${m.dot}`} />
      {m.label}
    </span>
  );
}

export function Button({
  children,
  onClick,
  disabled,
  variant = "primary",
  type = "button",
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "ghost" | "danger";
  type?: "button" | "submit";
  className?: string;
}) {
  const styles = {
    primary:
      "bg-sage text-white hover:brightness-110 shadow-sm",
    ghost:
      "border border-line bg-transparent text-ink hover:bg-sage-soft/60",
    danger:
      "border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950/40",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all duration-150 active:scale-[0.98] disabled:opacity-50 disabled:active:scale-100 ${styles} ${className}`}
    >
      {children}
    </button>
  );
}

export function Input({
  value,
  onChange,
  placeholder,
  type = "text",
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  className?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className={`w-full rounded-xl border border-line bg-paper/50 px-3.5 py-2.5 text-sm text-ink outline-none transition-colors placeholder:text-faint focus:border-sage focus:bg-card focus:ring-2 focus:ring-sage/15 ${className}`}
    />
  );
}
