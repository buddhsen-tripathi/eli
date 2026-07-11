"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type Patient } from "@/lib/api";
import { fmtDate, recoveryDay } from "@/lib/format";
import { Button, Card, Input } from "@/components/ui";

export default function RosterPage() {
  const [patients, setPatients] = useState<Patient[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  async function load() {
    try {
      setPatients(await api.listPatients());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => {
    load();
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Patients</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Post-op check-ins for recently-discharged patients.
          </p>
        </div>
        <Button onClick={() => setAdding((v) => !v)}>
          {adding ? "Close" : "+ Add patient"}
        </Button>
      </div>

      {adding && <AddPatientForm onDone={() => { setAdding(false); load(); }} />}

      {error && (
        <Card className="border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {error} — is the backend up and <code>NEXT_PUBLIC_API_URL</code> set?
        </Card>
      )}

      {patients === null && !error && (
        <p className="text-sm text-neutral-500">Loading…</p>
      )}

      {patients?.length === 0 && (
        <Card className="p-8 text-center text-sm text-neutral-500">
          No patients yet. Add one to start check-ins.
        </Card>
      )}

      {patients && patients.length > 0 && (
        <Card className="divide-y divide-neutral-200 dark:divide-neutral-800">
          {patients.map((p) => {
            const day = recoveryDay(p.surgery_date);
            return (
              <Link
                key={p.id}
                href={`/patients/${p.id}`}
                className="flex items-center justify-between px-5 py-4 transition-colors hover:bg-neutral-50 dark:hover:bg-neutral-900"
              >
                <div>
                  <p className="font-medium">{p.name}</p>
                  <p className="text-sm text-neutral-500">
                    {p.procedure ?? "—"}
                    <span className="mx-1.5 text-neutral-300">·</span>
                    <span className="font-mono text-xs">{p.phone}</span>
                  </p>
                </div>
                <div className="text-right text-sm">
                  {day !== null ? (
                    <span className="rounded-full bg-teal-50 px-2.5 py-0.5 text-xs font-medium text-teal-700 dark:bg-teal-950/40 dark:text-teal-300">
                      Day {day}
                    </span>
                  ) : (
                    <span className="text-xs text-neutral-400">
                      {fmtDate(p.surgery_date)}
                    </span>
                  )}
                </div>
              </Link>
            );
          })}
        </Card>
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
    <Card className="flex flex-col gap-3 p-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <Input value={name} onChange={setName} placeholder="Full name" />
        <Input value={phone} onChange={setPhone} placeholder="Phone e.g. +1650…" />
        <Input value={procedure} onChange={setProcedure} placeholder="Procedure" />
        <Input value={surgeryDate} onChange={setSurgeryDate} type="date" />
      </div>
      {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}
      <div className="flex gap-2">
        <Button onClick={submit} disabled={busy || !name || !phone}>
          {busy ? "Saving…" : "Save patient"}
        </Button>
      </div>
    </Card>
  );
}
