import type { TriageLevel } from "./api";

/** Whole days since surgery (day of surgery = 0). null if no date. */
export function recoveryDay(surgeryDate: string | null): number | null {
  if (!surgeryDate) return null;
  const start = new Date(surgeryDate + "T00:00:00");
  const now = new Date();
  const diff = Math.floor((now.getTime() - start.getTime()) / 86_400_000);
  return diff >= 0 ? diff : null;
}

export function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export const TRIAGE_META: Record<
  TriageLevel,
  { label: string; dot: string; text: string; bg: string; border: string }
> = {
  ok: {
    label: "OK",
    dot: "bg-emerald-500",
    text: "text-emerald-700 dark:text-emerald-300",
    bg: "bg-emerald-50 dark:bg-emerald-950/40",
    border: "border-emerald-200 dark:border-emerald-900",
  },
  monitor: {
    label: "Monitor",
    dot: "bg-amber-500",
    text: "text-amber-700 dark:text-amber-300",
    bg: "bg-amber-50 dark:bg-amber-950/40",
    border: "border-amber-200 dark:border-amber-900",
  },
  urgent: {
    label: "Urgent",
    dot: "bg-red-500",
    text: "text-red-700 dark:text-red-300",
    bg: "bg-red-50 dark:bg-red-950/40",
    border: "border-red-200 dark:border-red-900",
  },
};
