"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api, type Call, type TranscriptTurn } from "@/lib/api";
import { cleanTranscript, fmtDateTime, TRIAGE_META } from "@/lib/format";
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
  if (!call) return <p className="text-sm text-muted">Loading…</p>;

  const meta = call.triage ? TRIAGE_META[call.triage.level] : null;

  return (
    <div className="flex flex-col gap-6">
      <Link
        href={call.patient_id ? `/patients/${call.patient_id}` : "/"}
        className="rise text-sm text-muted transition-colors hover:text-ink"
      >
        ← {call.patient_id ? "Back to patient" : "Home"}
      </Link>

      {/* Headline card — triage front and center */}
      <Card
        className={`rise overflow-hidden ${meta ? meta.border : ""}`}
      >
        <div className={`flex flex-wrap items-center justify-between gap-4 p-6 ${meta ? meta.bg : ""}`}>
          <div className="flex items-center gap-4">
            <TriageBadge triage={call.triage} size="lg" />
            <div>
              <h1 className="font-display text-2xl font-medium tracking-tight text-ink">
                Check-in call
              </h1>
              <p className="text-sm text-muted">{fmtDateTime(call.started_at)}</p>
            </div>
          </div>
          <Button variant="ghost" onClick={rerun} disabled={rerunning}>
            {rerunning ? "Re-running…" : "Re-run analysis"}
          </Button>
        </div>
      </Card>

      {/* Retrieved key information */}
      {(call.summary || (call.triage && call.triage.flags.length > 0)) && (
        <Card className="rise flex flex-col gap-5 p-6" >
          <SectionTitle>Key findings</SectionTitle>
          {call.summary && (
            <p className="font-display text-lg leading-relaxed text-ink">
              {call.summary}
            </p>
          )}
          {call.triage && call.triage.flags.length > 0 && (
            <div className="flex flex-col gap-2">
              {call.triage.flags.map((f, i) => (
                <div key={i} className="flex items-start gap-2.5 text-sm text-ink">
                  <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${meta?.dot ?? "bg-faint"}`} />
                  {f}
                </div>
              ))}
            </div>
          )}
          {call.triage?.reason && (
            <p className="border-t border-line pt-4 text-sm text-muted">
              {call.triage.reason}
            </p>
          )}
        </Card>
      )}

      {/* At-a-glance meta */}
      <div className="grid grid-cols-3 gap-3 rise">
        <Stat label="Direction" value={call.direction} />
        <Stat label="Status" value={call.status} />
        <Stat
          label="Loved ones"
          value={call.notified_at ? "Notified" : "—"}
        />
      </div>

      {/* Transcript */}
      <Card className="rise flex flex-col gap-4 p-6">
        <div className="flex items-center justify-between">
          <SectionTitle>Transcript</SectionTitle>
          {turns.length > 0 && (
            <span className="font-mono text-xs text-faint">{turns.length} turns</span>
          )}
        </div>
        {turns.length === 0 ? (
          <p className="text-sm text-muted">
            No transcript captured. If the call just ended, give it a few seconds
            and refresh.
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            {turns.map((t) => {
              const agent = t.role === "agent";
              return (
                <div key={t.id} className={agent ? "flex" : "flex justify-end"}>
                  <div className={`max-w-[82%] ${agent ? "" : "text-right"}`}>
                    <p className="mb-1 px-1 font-mono text-[10px] uppercase tracking-widest text-faint">
                      {agent ? "Elle" : "Patient"}
                    </p>
                    <div
                      className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                        agent
                          ? "rounded-tl-sm bg-secondary text-secondary-foreground"
                          : "rounded-tr-sm bg-primary text-primary-foreground"
                      }`}
                    >
                      {cleanTranscript(t.text)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="p-4">
      <p className="font-mono text-[10px] uppercase tracking-widest text-faint">
        {label}
      </p>
      <p className="mt-1 text-sm font-medium capitalize text-ink">{value}</p>
    </Card>
  );
}
