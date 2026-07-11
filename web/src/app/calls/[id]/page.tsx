"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api, type Call, type TranscriptTurn } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { Button, Card, SectionTitle, TriageBadge } from "@/components/ui";

export default function CallPage() {
  const { id } = useParams<{ id: string }>();
  const [call, setCall] = useState<Call | null>(null);
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [rerunning, setRerunning] = useState(false);

  const load = useCallback(async () => {
    try {
      const [c, t] = await Promise.all([api.getCall(id), api.getTurns(id)]);
      setCall(c);
      setTurns(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [id]);
  useEffect(() => {
    load();
  }, [load]);

  async function rerun() {
    setRerunning(true);
    try {
      await api.rerunCall(id);
      await load();
    } finally {
      setRerunning(false);
    }
  }

  if (error) return <p className="text-sm text-red-600 dark:text-red-400">{error}</p>;
  if (!call) return <p className="text-sm text-neutral-500">Loading…</p>;

  return (
    <div className="flex flex-col gap-6">
      {call.patient_id ? (
        <Link href={`/patients/${call.patient_id}`} className="text-sm text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200">
          ← Back to patient
        </Link>
      ) : (
        <Link href="/" className="text-sm text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200">
          ← Home
        </Link>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">Check-in call</h1>
          <TriageBadge triage={call.triage} />
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-neutral-500">{fmtDateTime(call.started_at)}</span>
          <Button variant="ghost" onClick={rerun} disabled={rerunning} className="!py-1 text-xs">
            {rerunning ? "Re-running…" : "Re-run analysis"}
          </Button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Direction" value={call.direction} />
        <Stat label="Status" value={call.status} />
        <Stat
          label="Loved ones notified"
          value={call.notified_at ? fmtDateTime(call.notified_at) : "—"}
        />
      </div>

      {call.summary && (
        <Card className="p-5">
          <SectionTitle>Summary</SectionTitle>
          <p className="mt-2 text-sm leading-relaxed">{call.summary}</p>
        </Card>
      )}

      {call.triage && call.triage.flags.length > 0 && (
        <Card className="p-5">
          <SectionTitle>Flags</SectionTitle>
          <div className="mt-2 flex flex-wrap gap-2">
            {call.triage.flags.map((f, i) => (
              <span key={i} className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs dark:bg-neutral-800">
                {f}
              </span>
            ))}
          </div>
          {call.triage.reason && (
            <p className="mt-3 text-sm text-neutral-500">{call.triage.reason}</p>
          )}
        </Card>
      )}

      <Card className="p-5">
        <SectionTitle>Transcript</SectionTitle>
        {turns.length === 0 ? (
          <p className="mt-2 text-sm text-neutral-500">
            No transcript captured. If the call just ended, give it a few seconds and refresh —
            it&apos;s pulled from ElevenLabs after hangup.
          </p>
        ) : (
          <div className="mt-3 flex flex-col gap-3">
            {turns.map((t) => (
              <div key={t.id} className={t.role === "agent" ? "" : "flex justify-end"}>
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm ${
                    t.role === "agent"
                      ? "bg-neutral-100 dark:bg-neutral-800"
                      : "bg-teal-600 text-white"
                  }`}
                >
                  <p className="mb-0.5 text-[10px] font-medium uppercase tracking-wide opacity-60">
                    {t.role === "agent" ? "Grace" : "Patient"}
                  </p>
                  {t.text}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs uppercase tracking-widest text-neutral-500">{label}</p>
      <p className="mt-1 text-sm font-medium capitalize">{value}</p>
    </Card>
  );
}
