"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type Call, type Patient } from "@/lib/api";
import { fmtDate, recoveryDay } from "@/lib/format";
import { Button, Card, Input, TriageBadge } from "@/components/ui";

export default function RosterPage() {
  const [patients, setPatients] = useState<Patient[] | null>(null);
  const [calls, setCalls] = useState<Call[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  async function load() {
    try {
      const [ps, cs] = await Promise.all([api.listPatients(), api.listCalls()]);
      setPatients(ps);
      setCalls(cs);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => {
    load();
  }, []);

  // latest call per patient (calls come back newest-first)
  const latest = new Map<string, Call>();
  for (const c of calls) {
    if (c.patient_id && !latest.has(c.patient_id)) latest.set(c.patient_id, c);
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-end justify-between rise">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-faint">
            Patient roster
          </p>
          <h1 className="mt-2 font-display text-4xl font-medium tracking-tight text-ink">
            Recovering at home
          </h1>
          <p className="mt-2 max-w-md text-sm text-muted">
            Voice check-ins for recently-discharged patients, with recaps sent to
            their loved ones.
          </p>
        </div>
        <Button onClick={() => setAdding((v) => !v)}>
          {adding ? "Close" : "+ New patient"}
        </Button>
      </div>

      {adding && <AddPatientForm onDone={() => { setAdding(false); load(); }} />}

      {error && (
        <Card className="border-red-300 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {error} — is the backend up and <code>NEXT_PUBLIC_API_URL</code> set?
        </Card>
      )}

      {patients === null && !error && (
        <p className="text-sm text-muted">Loading…</p>
      )}

      {patients?.length === 0 && (
        <Card className="p-10 text-center text-sm text-muted">
          No patients yet. Add one to start check-ins.
        </Card>
      )}

      {patients && patients.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {patients.map((p, i) => {
            const day = recoveryDay(p.surgery_date);
            const call = latest.get(p.id);
            return (
              <Link key={p.id} href={`/patients/${p.id}`} className="rise" style={{ animationDelay: `${i * 40}ms` }}>
                <Card className="group h-full p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-sage/40">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="font-display text-xl font-medium tracking-tight text-ink">
                        {p.name}
                      </h3>
                      <p className="mt-0.5 text-sm text-muted">
                        {p.procedure ?? "—"}
                      </p>
                    </div>
                    {day !== null && (
                      <span className="shrink-0 rounded-full bg-sage-soft px-2.5 py-0.5 text-xs font-medium text-sage-ink">
                        Day {day}
                      </span>
                    )}
                  </div>
                  <div className="mt-4 flex items-center justify-between border-t border-line pt-3">
                    <span className="font-mono text-xs text-faint">{p.phone}</span>
                    {call ? (
                      <TriageBadge triage={call.triage} />
                    ) : (
                      <span className="text-xs text-faint">
                        {p.surgery_date ? `surgery ${fmtDate(p.surgery_date)}` : "no calls yet"}
                      </span>
                    )}
                  </div>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

function AddPatientForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [procedure, setProcedure] = useState("");
  const [surgeryDate, setSurgeryDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      await api.createPatient({
        name,
        phone,
        procedure: procedure || undefined,
        surgery_date: surgeryDate || undefined,
      });
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Card className="flex flex-col gap-3 p-5 rise">
      <div className="grid gap-3 sm:grid-cols-2">
        <Input value={name} onChange={setName} placeholder="Full name" />
        <Input value={phone} onChange={setPhone} placeholder="Phone e.g. +1650…" />
        <Input value={procedure} onChange={setProcedure} placeholder="Procedure" />
        <Input value={surgeryDate} onChange={setSurgeryDate} type="date" />
      </div>
      {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}
      <div>
        <Button onClick={submit} disabled={busy || !name || !phone}>
          {busy ? "Saving…" : "Save patient"}
        </Button>
      </div>
    </Card>
  );
}
