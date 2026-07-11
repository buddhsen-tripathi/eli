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
      className={`rounded-lg border border-border bg-card text-card-foreground shadow-2xs ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
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
        className={`inline-flex items-center gap-1.5 rounded-full border border-border text-muted-foreground ${pad}`}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/50" />
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
    primary: "bg-primary text-primary-foreground hover:bg-primary/90",
    ghost: "border border-border bg-background hover:bg-accent hover:text-accent-foreground",
    danger: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex cursor-pointer items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 ${styles} ${className}`}
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
      className={`w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/20 ${className}`}
    />
  );
}
