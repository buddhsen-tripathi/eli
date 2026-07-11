// Client for the FastAPI backend. Point NEXT_PUBLIC_API_URL at it (see .env.example).

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    headers: init?.body ? { "content-type": "application/json" } : undefined,
    ...init,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: string })?.detail ?? res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data as T;
}

const get = <T>(p: string) => req<T>(p);
const post = <T>(p: string, body?: unknown) =>
  req<T>(p, { method: "POST", body: body ? JSON.stringify(body) : undefined });
const patch = <T>(p: string, body: unknown) =>
  req<T>(p, { method: "PATCH", body: JSON.stringify(body) });
const del = (p: string) => req<unknown>(p, { method: "DELETE" });

// ── Types ─────────────────────────────────────────────────────────────────────

export type TriageLevel = "ok" | "monitor" | "urgent";

export type Triage = { level: TriageLevel; flags: string[]; reason: string };

export type Patient = {
  id: string;
  name: string;
  phone: string;
  procedure: string | null;
  surgery_date: string | null;
  clinician: string | null;
  notes: string | null;
  checkin_days: number[] | null;
  created_at: string;
};

export type Medication = {
  id: string;
  patient_id: string;
  name: string;
  appearance: string | null;
  tactile: string | null;
  dosage: string | null;
  schedule: string | null;
  instructions: string | null;
  purpose: string | null;
  active: boolean;
};

export type Caregiver = {
  id: string;
  patient_id: string;
  name: string;
  relationship_to_patient: string | null;
  phone: string | null;
  email: string | null;
  notify_when: "always" | "urgent" | "never";
  is_primary: boolean;
};

export type Call = {
  id: string;
  call_sid?: string;
  patient_id?: string | null;
  direction: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  summary: string | null;
  triage: Triage | null;
  notified_at: string | null;
};

export type TranscriptTurn = {
  id: string;
  role: string;
  text: string;
  timestamp: string;
};

export type PatientDetail = Patient & {
  medications: Medication[];
  caregivers: Caregiver[];
  calls: Call[];
};

// ── Inputs ──────────────────────────────────────────────────────────────────────

export type PatientInput = Partial<Omit<Patient, "id" | "created_at">> & {
  name: string;
  phone: string;
};
export type MedicationInput = Partial<Omit<Medication, "id" | "patient_id">> & {
  name: string;
};
export type CaregiverInput = Partial<Omit<Caregiver, "id" | "patient_id">> & {
  name: string;
};

// ── API ─────────────────────────────────────────────────────────────────────────

export const api = {
  // patients
  listPatients: () => get<Patient[]>("/api/patients"),
  getPatientDetail: (id: string) => get<PatientDetail>(`/api/patients/${id}/detail`),
  createPatient: (body: PatientInput) => post<Patient>("/api/patients", body),
  updatePatient: (id: string, body: Partial<PatientInput>) =>
    patch<Patient>(`/api/patients/${id}`, body),

  // medications
  addMedication: (patientId: string, body: MedicationInput) =>
    post<Medication>(`/api/patients/${patientId}/medications`, body),
  updateMedication: (id: string, body: Partial<MedicationInput>) =>
    patch<Medication>(`/api/medications/${id}`, body),
  deleteMedication: (id: string) => del(`/api/medications/${id}`),

  // caregivers
  addCaregiver: (patientId: string, body: CaregiverInput) =>
    post<Caregiver>(`/api/patients/${patientId}/caregivers`, body),
  updateCaregiver: (id: string, body: Partial<CaregiverInput>) =>
    patch<Caregiver>(`/api/caregivers/${id}`, body),
  deleteCaregiver: (id: string) => del(`/api/caregivers/${id}`),

  // calls
  listCalls: () => get<Call[]>("/api/calls"),
  getCall: (id: string) => get<Call>(`/api/calls/${id}`),
  getTurns: (id: string) => get<TranscriptTurn[]>(`/api/calls/${id}/turns`),
  rerunCall: (id: string) => post<{ triage: Triage }>(`/api/calls/${id}/rerun`),

  // place a check-in call to a specific patient (optional day overrides recovery day)
  startCheckin: (patientId: string, day?: number) =>
    post<{ call_sid: string; status: string }>(
      `/call/outbound/${patientId}${day != null ? `?day=${day}` : ""}`,
    ),
  // demo: dial DESTINATION_PHONE_NUMBER configured on the backend
  triggerDemoCall: () =>
    post<{ call_sid: string; to: string; status: string }>("/call/outbound"),
};
