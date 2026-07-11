// Thin client for the FastAPI backend. Point NEXT_PUBLIC_API_URL at it (see .env.example).

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: string })?.detail ?? res.statusText;
    throw new Error(detail);
  }
  return data as T;
}

export type Patient = {
  id: string;
  name: string;
  phone: string;
  procedure: string | null;
  surgery_date: string | null;
  clinician: string | null;
  notes: string | null;
  created_at: string;
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

export type TriageLevel = "ok" | "monitor" | "urgent";

export type Triage = {
  level: TriageLevel;
  flags: string[];
  reason: string;
};

export type Call = {
  id: string;
  call_sid: string;
  patient_id: string | null;
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

export type DemoCallResult = {
  call_sid: string;
  patient_id: string;
  to: string;
  status: string;
};

export const api = {
  listPatients: () => get<Patient[]>("/api/patients"),
  listCalls: () => get<Call[]>("/api/calls"),
  getCall: (id: string) => get<Call>(`/api/calls/${id}`),
  getTurns: (id: string) => get<TranscriptTurn[]>(`/api/calls/${id}/turns`),
  listCaregivers: (patientId: string) =>
    get<Caregiver[]>(`/api/patients/${patientId}/caregivers`),
  // Dials DESTINATION_PHONE_NUMBER (set on the backend) and bridges to the agent.
  triggerDemoCall: () => post<DemoCallResult>("/call/outbound"),
};
