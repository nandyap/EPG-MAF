"use client";

import { useState, FormEvent } from "react";
import { api } from "@/lib/api";
import { HttpError } from "@/lib/api";

export function NewChatModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (threadId: string) => void;
}) {
  const [patientId, setPatientId] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const resp = await api.createThread(
        patientId.trim(),
        title.trim() || undefined,
      );
      onCreated(resp.thread_id);
      setPatientId("");
      setTitle("");
    } catch (e) {
      if (e instanceof HttpError && e.status === 404) {
        setError(
          "That patient is not available for your session. Check the ID and your allowlist.",
        );
      } else {
        setError(e instanceof Error ? e.message : "Failed to start chat");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <form
        onSubmit={submit}
        className="w-full max-w-md rounded-lg bg-white p-6 shadow-lg"
      >
        <h2 className="text-lg font-semibold">Start a new chat</h2>
        <p className="mt-1 text-sm text-slate-600">
          The chat will be pinned to this patient. This cannot be changed
          later.
        </p>

        <label className="mt-4 block text-sm font-medium">Patient ID</label>
        <input
          type="text"
          required
          value={patientId}
          onChange={(e) => setPatientId(e.target.value)}
          placeholder="PGP001"
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
        />

        <label className="mt-4 block text-sm font-medium">
          Title <span className="text-slate-400">(optional)</span>
        </label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Family history review"
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
        />

        {error && (
          <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
            {error}
          </p>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-4 py-2 text-sm hover:bg-slate-100"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy || !patientId.trim()}
            className="rounded-md bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800 disabled:opacity-50"
          >
            {busy ? "Starting…" : "Start chat"}
          </button>
        </div>
      </form>
    </div>
  );
}
