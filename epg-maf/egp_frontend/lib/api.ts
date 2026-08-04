// Thin client that talks to the Next.js /api/* proxy (which forwards
// to the FastAPI backend). Never call BACKEND_URL directly from the
// browser — that would leak the bearer to the network tab and skip the
// Easy Auth principal injection.

import type {
  ApiError,
  ChatRequest,
  ChatResponse,
  ThreadCreateResponse,
  ThreadDetail,
  ThreadListResponse,
  UserIdentity,
} from "./types";

export class HttpError extends Error {
  constructor(
    public status: number,
    public body: ApiError | null,
    message: string,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

// In dev, inject the stub bearer so the smoke server's
// StubAuthenticator sees the same clinician on every request. In prod,
// Easy Auth injects the principal at the edge and this env var is
// intentionally unset.
const DEV_BEARER =
  typeof process !== "undefined"
    ? process.env.NEXT_PUBLIC_DEV_BEARER
    : undefined;

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (DEV_BEARER && !headers["Authorization"]) {
    headers["Authorization"] = `Bearer ${DEV_BEARER}`;
  }
  const res = await fetch(path, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    // fall through
  }
  if (!res.ok) {
    const body = (json ?? null) as ApiError | null;
    throw new HttpError(
      res.status,
      body,
      body?.message ?? `HTTP ${res.status}`,
    );
  }
  return json as T;
}

export const api = {
  me: () => request<UserIdentity>("/api/me"),
  listThreads: (patientId?: string) => {
    const qs = patientId
      ? `?patient_id=${encodeURIComponent(patientId)}`
      : "";
    return request<ThreadListResponse>(`/api/threads${qs}`);
  },
  getThread: (threadId: string) =>
    request<ThreadDetail>(`/api/threads/${encodeURIComponent(threadId)}`),
  createThread: (patientId: string, title?: string) =>
    request<ThreadCreateResponse>("/api/threads", {
      method: "POST",
      body: JSON.stringify({ patient_id: patientId, title }),
    }),
  deleteThread: (threadId: string) =>
    request<void>(`/api/threads/${encodeURIComponent(threadId)}`, {
      method: "DELETE",
    }),
  chat: (body: ChatRequest) =>
    request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
