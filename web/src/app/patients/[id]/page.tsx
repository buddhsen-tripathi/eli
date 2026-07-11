"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  api,
  type Caregiver,
  type Medication,
  type PatientDetail,
} from "@/lib/api";
import { fmtDate, fmtDateTime, recoveryDay } from "@/lib/format";
import { Button, Card, Input, SectionTitle, TriageBadge } from "@/components/ui";

export default function PatientPage() {
  const { id } = useParams<{ id: string }>();
  const [p, setP] = useState<PatientDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setP(await api.getPatientDetail(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [id]);
  useEffect(() => {
    load();
  }, [load]);

  if (error)
    return <p className="text-sm text-red-600 dark:text-red-400">{error}</p>;
  if (!p) return <p className="text-sm text-neutral-500">Loading…</p>;

  return (
    <div className="flex flex-col gap-6">
      <Link href="/" className="text-sm text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200">
        ← All patients
      </Link>

      <PatientHeader patient={p} onSaved={load} />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-2">
          <NotesCard patient={p} onSaved={load} />
          <MedicationsCard patient={p} onChanged={load} />
        </div>
        <div className="flex flex-col gap-6">
          <CaregiversCard patient={p} onChanged={load} />
          <CallsCard patient={p} />
        </div>
      </div>
    </div>
  );
}

function PatientHeader({ patient, onSaved }: { patient: PatientDetail; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: patient.name,
    procedure: patient.procedure ?? "",
    surgery_date: patient.surgery_date ?? "",
    phone: patient.phone,
    clinician: patient.clinician ?? "",
  });
  const [busy, setBusy] = useState(false);
  const day = recoveryDay(patient.surgery_date);

  async function save() {
    setBusy(true);
    await api.updatePatient(patient.id, {
      name: form.name,
      procedure: form.procedure || undefined,
      surgery_date: form.surgery_date || undefined,
      phone: form.phone,
      clinician: form.clinician || undefined,
    });
    setBusy(false);
    setEditing(false);
    onSaved();
  }

  if (editing) {
    return (
      <Card className="flex flex-col gap-3 p-5">
        <SectionTitle>Edit patient details</SectionTitle>
        <div className="grid gap-3 sm:grid-cols-2">
          <Input value={form.name} onChange={(v) => setForm({ ...form, name: v })} placeholder="Name" />
          <Input value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} placeholder="Phone" />
          <Input value={form.procedure} onChange={(v) => setForm({ ...form, procedure: v })} placeholder="Procedure" />
          <Input value={form.surgery_date} onChange={(v) => setForm({ ...form, surgery_date: v })} type="date" />
          <Input value={form.clinician} onChange={(v) => setForm({ ...form, clinician: v })} placeholder="Clinician" className="sm:col-span-2" />
        </div>
        <div className="flex gap-2">
          <Button onClick={save} disabled={busy || !form.name || !form.phone}>
            {busy ? "Saving…" : "Save"}
          </Button>
          <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
        </div>
      </Card>
    );
  }

  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{patient.name}</h1>
        <p className="mt-1 text-sm text-neutral-500">
          {patient.procedure ?? "No procedure recorded"}
          {patient.surgery_date && ` · surgery ${fmtDate(patient.surgery_date)}`}
          {day !== null && ` · day ${day} post-op`}
          {patient.clinician && ` · ${patient.clinician}`}
        </p>
        <p className="mt-1 font-mono text-xs text-neutral-400">{patient.phone}</p>
      </div>
      <div className="flex flex-col items-end gap-2">
        <CheckinButton patientId={patient.id} />
        <button
          onClick={() => setEditing(true)}
          className="text-xs text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200"
        >
          Edit details
        </button>
      </div>
    </div>
  );
}

function CheckinButton({ patientId }: { patientId: string }) {
  const [state, setState] = useState<"idle" | "calling" | "ok" | "error">("idle");
  const [msg, setMsg] = useState("");
  async function call() {
    setState("calling");
    try {
      await api.startCheckin(patientId);
      setState("ok");
      setMsg("Calling now — the phone should ring.");
    } catch (e) {
      setState("error");
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }
  return (
    <div className="flex flex-col items-end gap-1">
      <Button onClick={call} disabled={state === "calling"}>
        {state === "calling" ? "Dialing…" : "📞 Start check-in call"}
      </Button>
      {msg && (
        <p className={`text-xs ${state === "error" ? "text-red-600 dark:text-red-400" : "text-teal-600 dark:text-teal-400"}`}>
          {msg}
        </p>
      )}
    </div>
  );
}

function NotesCard({ patient, onSaved }: { patient: PatientDetail; onSaved: () => void }) {
  const [notes, setNotes] = useState(patient.notes ?? "");
  const [busy, setBusy] = useState(false);
  const dirty = notes !== (patient.notes ?? "");
  async function save() {
    setBusy(true);
    await api.updatePatient(patient.id, { notes });
    setBusy(false);
    onSaved();
  }
  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-center justify-between">
        <SectionTitle>EHR notes · source of truth</SectionTitle>
        {dirty && (
          <Button onClick={save} disabled={busy} className="!py-1 text-xs">
            {busy ? "Saving…" : "Save"}
          </Button>
        )}
      </div>
      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        rows={6}
        placeholder="• Discharged after hip replacement&#10;• Watch for signs of infection at incision&#10;• Lives alone; daughter checks in weekends"
        className="w-full resize-y rounded-lg border border-neutral-200 bg-transparent p-3 text-sm leading-relaxed outline-none placeholder:text-neutral-400 focus:border-neutral-400 dark:border-neutral-800 dark:focus:border-neutral-600"
      />
      <p className="text-xs text-neutral-400">
        Given to the agent as context on every call.
      </p>
    </Card>
  );
}

const EMPTY_MED = { name: "", appearance: "", dosage: "", schedule: "", instructions: "" };
type MedForm = typeof EMPTY_MED;

function medToForm(m: Medication): MedForm {
  return {
    name: m.name,
    appearance: m.appearance ?? "",
    dosage: m.dosage ?? "",
    schedule: m.schedule ?? "",
    instructions: m.instructions ?? "",
  };
}

function MedFields({ form, set }: { form: MedForm; set: (f: MedForm) => void }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <Input value={form.name} onChange={(v) => set({ ...form, name: v })} placeholder="Name e.g. Amoxicillin" />
      <Input value={form.appearance} onChange={(v) => set({ ...form, appearance: v })} placeholder="Looks like… e.g. small red capsule" />
      <Input value={form.dosage} onChange={(v) => set({ ...form, dosage: v })} placeholder="Dosage e.g. 500mg" />
      <Input value={form.schedule} onChange={(v) => set({ ...form, schedule: v })} placeholder="Schedule e.g. 8 AM & 8 PM" />
      <Input value={form.instructions} onChange={(v) => set({ ...form, instructions: v })} placeholder="Instructions e.g. with food" className="sm:col-span-2" />
    </div>
  );
}

function MedRow({ med, onChanged }: { med: Medication; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<MedForm>(medToForm(med));
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    await api.updateMedication(med.id, {
      name: form.name,
      appearance: form.appearance || undefined,
      dosage: form.dosage || undefined,
      schedule: form.schedule || undefined,
      instructions: form.instructions || undefined,
    });
    setBusy(false);
    setEditing(false);
    onChanged();
  }

  if (editing) {
    return (
      <div className="flex flex-col gap-2 rounded-lg border border-neutral-300 p-3 dark:border-neutral-700">
        <MedFields form={form} set={setForm} />
        <div className="flex gap-2">
          <Button onClick={save} disabled={busy || !form.name} className="!py-1 text-xs">
            {busy ? "Saving…" : "Save"}
          </Button>
          <Button variant="ghost" onClick={() => { setForm(medToForm(med)); setEditing(false); }} className="!py-1 text-xs">
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
      <div className="text-sm">
        <p className="font-medium">
          {med.name}
          {med.dosage && <span className="text-neutral-500"> · {med.dosage}</span>}
        </p>
        {med.appearance && (
          <p className="text-xs text-teal-700 dark:text-teal-400">“{med.appearance}”</p>
        )}
        <p className="text-xs text-neutral-500">
          {[med.schedule, med.instructions].filter(Boolean).join(" · ") || "—"}
        </p>
      </div>
      <div className="flex shrink-0 gap-3 text-xs">
        <button onClick={() => setEditing(true)} className="text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200">
          Edit
        </button>
        <button onClick={async () => { await api.deleteMedication(med.id); onChanged(); }} className="text-neutral-400 hover:text-red-500">
          Remove
        </button>
      </div>
    </div>
  );
}

function MedicationsCard({ patient, onChanged }: { patient: PatientDetail; onChanged: () => void }) {
  const [form, setForm] = useState<MedForm>({ ...EMPTY_MED });
  const [busy, setBusy] = useState(false);

  async function add() {
    if (!form.name) return;
    setBusy(true);
    await api.addMedication(patient.id, {
      name: form.name,
      appearance: form.appearance || undefined,
      dosage: form.dosage || undefined,
      schedule: form.schedule || undefined,
      instructions: form.instructions || undefined,
    });
    setForm({ ...EMPTY_MED });
    setBusy(false);
    onChanged();
  }

  return (
    <Card className="flex flex-col gap-4 p-5">
      <SectionTitle>Medications</SectionTitle>

      {patient.medications.length === 0 ? (
        <p className="text-sm text-neutral-500">No medications yet.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {patient.medications.map((m) => (
            <MedRow key={m.id} med={m} onChanged={onChanged} />
          ))}
        </div>
      )}

      <div className="flex flex-col gap-2 rounded-lg border border-dashed border-neutral-300 p-3 dark:border-neutral-700">
        <MedFields form={form} set={setForm} />
        <Button onClick={add} disabled={busy || !form.name} variant="ghost">
          {busy ? "Adding…" : "+ Add medication"}
        </Button>
      </div>
      <p className="text-xs text-neutral-400">
        The <strong>Looks like…</strong> field lets the agent answer “which is my red pill?”
      </p>
    </Card>
  );
}

const EMPTY_CG = { name: "", relationship_to_patient: "", phone: "", notify_when: "always" };
type CgForm = typeof EMPTY_CG;

function cgToForm(c: Caregiver): CgForm {
  return {
    name: c.name,
    relationship_to_patient: c.relationship_to_patient ?? "",
    phone: c.phone ?? "",
    notify_when: c.notify_when,
  };
}

function NotifySelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg border border-neutral-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-neutral-400 dark:border-neutral-800 dark:focus:border-neutral-600"
    >
      <option value="always">Notify: always</option>
      <option value="urgent">Notify: urgent only</option>
      <option value="never">Notify: never</option>
    </select>
  );
}

function CgFields({ form, set }: { form: CgForm; set: (f: CgForm) => void }) {
  return (
    <>
      <Input value={form.name} onChange={(v) => set({ ...form, name: v })} placeholder="Name" />
      <Input value={form.relationship_to_patient} onChange={(v) => set({ ...form, relationship_to_patient: v })} placeholder="Relationship e.g. daughter" />
      <Input value={form.phone} onChange={(v) => set({ ...form, phone: v })} placeholder="Phone e.g. +1650…" />
      <NotifySelect value={form.notify_when} onChange={(v) => set({ ...form, notify_when: v })} />
    </>
  );
}

function CaregiverRow({ cg, onChanged }: { cg: Caregiver; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<CgForm>(cgToForm(cg));
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    await api.updateCaregiver(cg.id, {
      name: form.name,
      relationship_to_patient: form.relationship_to_patient || undefined,
      phone: form.phone || undefined,
      notify_when: form.notify_when as Caregiver["notify_when"],
    });
    setBusy(false);
    setEditing(false);
    onChanged();
  }

  if (editing) {
    return (
      <div className="grid gap-2 rounded-lg border border-neutral-300 p-3 dark:border-neutral-700">
        <CgFields form={form} set={setForm} />
        <div className="flex gap-2">
          <Button onClick={save} disabled={busy || !form.name} className="!py-1 text-xs">
            {busy ? "Saving…" : "Save"}
          </Button>
          <Button variant="ghost" onClick={() => { setForm(cgToForm(cg)); setEditing(false); }} className="!py-1 text-xs">
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between text-sm">
      <div>
        <p className="font-medium">
          {cg.name}
          {cg.relationship_to_patient && (
            <span className="text-neutral-500"> · {cg.relationship_to_patient}</span>
          )}
        </p>
        <p className="font-mono text-xs text-neutral-400">
          {cg.phone ?? "no phone"} · {cg.notify_when}
        </p>
      </div>
      <div className="flex shrink-0 gap-3 text-xs">
        <button onClick={() => setEditing(true)} className="text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200">
          Edit
        </button>
        <button onClick={async () => { await api.deleteCaregiver(cg.id); onChanged(); }} className="text-neutral-400 hover:text-red-500">
          Remove
        </button>
      </div>
    </div>
  );
}

function CaregiversCard({ patient, onChanged }: { patient: PatientDetail; onChanged: () => void }) {
  const [form, setForm] = useState<CgForm>({ ...EMPTY_CG });
  const [busy, setBusy] = useState(false);

  async function add() {
    if (!form.name) return;
    setBusy(true);
    await api.addCaregiver(patient.id, {
      name: form.name,
      relationship_to_patient: form.relationship_to_patient || undefined,
      phone: form.phone || undefined,
      notify_when: form.notify_when as Caregiver["notify_when"],
    });
    setForm({ ...EMPTY_CG });
    setBusy(false);
    onChanged();
  }

  return (
    <Card className="flex flex-col gap-3 p-5">
      <SectionTitle>Loved ones</SectionTitle>
      {patient.caregivers.length === 0 ? (
        <p className="text-sm text-neutral-500">No contacts — no one gets notified.</p>
      ) : (
        patient.caregivers.map((c) => <CaregiverRow key={c.id} cg={c} onChanged={onChanged} />)
      )}
      <div className="grid gap-2 border-t border-neutral-200 pt-3 dark:border-neutral-800">
        <CgFields form={form} set={setForm} />
        <Button onClick={add} disabled={busy || !form.name} variant="ghost">
          {busy ? "Adding…" : "+ Add loved one"}
        </Button>
      </div>
    </Card>
  );
}

function CallsCard({ patient }: { patient: PatientDetail }) {
  return (
    <Card className="flex flex-col gap-3 p-5">
      <SectionTitle>Check-in history</SectionTitle>
      {patient.calls.length === 0 ? (
        <p className="text-sm text-neutral-500">No calls yet.</p>
      ) : (
        patient.calls.map((c) => (
          <Link
            key={c.id}
            href={`/calls/${c.id}`}
            className="flex items-center justify-between rounded-lg border border-neutral-200 px-3 py-2 text-sm transition-colors hover:bg-neutral-50 dark:border-neutral-800 dark:hover:bg-neutral-900"
          >
            <span className="text-neutral-500">{fmtDateTime(c.started_at)}</span>
            <TriageBadge triage={c.triage} />
          </Link>
        ))
      )}
    </Card>
  );
}
