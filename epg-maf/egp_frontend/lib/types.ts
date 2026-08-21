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

// One provenance record: the evidence chain behind a single clinical
// fact. Built at query time by the Repository (ADR-005), never authored
// by the LLM.
export type Provenance = {
  tool_name: string;
  tool_parameters: Record<string, unknown>;
  source_table: string;
  source_row: Record<string, unknown>;
  fields_derived: string[];
  retrieved_at: string;
  trace_id: string | null;
  span_id: string | null;
};

// One specialist slot on the chat response. Matches
// ChatSpecialistSlotView in schemas.py.
//
// These fields previously read `reason` / `summary` / `data` /
// `provenance`, none of which the backend has ever sent — it sends
// `status`, `output` and `errors`. The status union was also wrong
// ("success" vs the actual "completed"), so `statusStyles` matched no
// case and every card rendered unstyled. Because `provenance` was
// declared at the top level it was always `undefined`; the real records
// are nested at `output.output.results[].provenance[]`.
export type SpecialistSlot = {
  status: "completed" | "partial" | "failed" | "pending" | "running";
  // Serialised <Domain>StateOutput. Its own `output` field holds the
  // <Domain>ResultList — hence the double nesting.
  output: {
    status?: string;
    errors?: string[];
    output?: {
      patient_id?: string;
      summary?: string | null;
      summary_model?: string | null;
      results?: Record<string, unknown>[];
    } | null;
  } | null;
  errors: string[];
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
