// Mirrors the backend Pydantic response models. Keep in sync with
// epg-maf/src/egp_maf/api/schemas.py.

export type UserIdentity = {
  authenticated: boolean;
  clinician_id: string | null;
  name: string | null;
  roles: string[];
};

export type ThreadListItem = {
  thread_id: string;
  patient_id: string;
  title: string | null;
  created_at: string;
  last_activity: string;
};

export type ThreadListResponse = { threads: ThreadListItem[] };

export type ThreadMessage = {
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  timestamp: string;
};

export type ThreadDetail = {
  thread_id: string;
  patient_id: string;
  title: string | null;
  created_at: string;
  last_activity: string;
  messages: ThreadMessage[];
};

export type ThreadCreateResponse = {
  thread_id: string;
  patient_id: string;
  created_at: string;
};

// One specialist slot on the chat response. Matches
// ChatSpecialistSlotView in schemas.py.
export type SpecialistSlot = {
  status: "success" | "failure" | "skipped";
  reason: string | null;
  summary: string | null;
  data: Record<string, unknown> | null;
  provenance: unknown | null;
} | null;

export type ChatResponse = {
  thread_id: string;
  patient_id: string;
  trace_id: string | null;
  reply: string;
  agents_completed: string[];
  prs: SpecialistSlot;
  genomic_variants: SpecialistSlot;
  family_history: SpecialistSlot;
  pgx: SpecialistSlot;
  phenotype: SpecialistSlot;
};

export type ChatRequest = {
  thread_id: string;
  patient_id: string;
  message: string;
  requested_diseases?: string[];
  requested_genes?: string[];
};

export type ApiError = {
  error_code: string;
  message: string;
  trace_id?: string | null;
};
