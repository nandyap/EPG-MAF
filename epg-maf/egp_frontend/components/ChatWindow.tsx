"use client";

import { useEffect, useRef, useState, FormEvent } from "react";
import { api, HttpError } from "@/lib/api";
import type { ChatResponse, ThreadDetail, ThreadMessage } from "@/lib/types";
import { useThreads } from "@/lib/threads-context";
import { ChatMessage } from "./ChatMessage";
import { SpecialistCards } from "./SpecialistCards";
import { ErrorBanner } from "./ErrorBanner";

type TranscriptItem =
  | { kind: "message"; msg: ThreadMessage; id: string }
  | { kind: "specialists"; response: ChatResponse; id: string };

export function ChatWindow({ thread }: { thread: ThreadDetail }) {
  const { refresh: refreshThreads } = useThreads();
  const [items, setItems] = useState<TranscriptItem[]>(() =>
    thread.messages.map((m, i) => ({
      kind: "message",
      msg: m,
      id: `hist-${i}`,
    })),
  );
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    const now = new Date().toISOString();
    const optimistic: TranscriptItem = {
      kind: "message",
      msg: { role: "user", content: text, timestamp: now },
      id: `local-${Date.now()}`,
    };
    setItems((prev) => [...prev, optimistic]);
    setInput("");

    try {
      const resp = await api.chat({
        thread_id: thread.thread_id,
        patient_id: thread.patient_id,
        message: text,
      });
      const assistant: TranscriptItem = {
        kind: "message",
        msg: {
          role: "assistant",
          content: resp.reply,
          timestamp: new Date().toISOString(),
        },
        id: `reply-${Date.now()}`,
      };
      const cards: TranscriptItem = {
        kind: "specialists",
        response: resp,
        id: `cards-${Date.now()}`,
      };
      setItems((prev) => [...prev, assistant, cards]);
      // The turn advanced the thread's ``last_activity`` (and, for an
      // auto-titled thread, its title) server-side. Re-pull the sidebar
      // so ordering and labels reflect the write we just made.
      void refreshThreads();
    } catch (e) {
      let msg = e instanceof Error ? e.message : "Chat failed";
      if (e instanceof HttpError) {
        if (e.status === 409)
          msg =
            "This chat is pinned to a different patient. Start a new chat to switch patients.";
        else if (e.status === 404)
          msg = "This patient is not available for your session.";
        else if (e.status === 401) msg = "Session expired — please sign in again.";
      }
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="px-6 py-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-base font-semibold text-slate-800">
            {thread.title ?? "Chat"}
          </h1>
          <span className="inline-flex items-center gap-1 rounded-full bg-[color:var(--brand-50)] px-2 py-0.5 text-[11px] font-medium text-[color:var(--brand-800)] ring-1 ring-inset ring-[color:var(--brand-100)]">
            <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--brand-500)]" />
            Patient {thread.patient_id}
          </span>
        </div>
        <p className="mt-0.5 text-[11px] text-slate-400">
          Thread <span className="font-mono">{thread.thread_id}</span>
        </p>
      </header>
      <div className="hair-divider mx-6" />

      <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
        {items.length === 0 && (
          <p className="text-center text-sm text-slate-500">
            Ask the assistant about this patient. Cross-patient and cohort
            queries will be refused by the guardrail.
          </p>
        )}
        {items.map((it) =>
          it.kind === "message" ? (
            <ChatMessage
              key={it.id}
              role={it.msg.role}
              content={it.msg.content}
            />
          ) : (
            <SpecialistCards key={it.id} response={it.response} />
          ),
        )}
        <div ref={endRef} />
      </div>

      {error && (
        <div className="px-6 pb-2">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      <div className="hair-divider mx-6" />
      <form
        onSubmit={submit}
        className="flex gap-2 px-6 py-3"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about this patient…"
          disabled={busy}
          className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm transition focus:border-[color:var(--brand-500)] focus:outline-none focus:ring-2 focus:ring-[color:var(--brand-100)] disabled:bg-slate-50"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-lg bg-[color:var(--brand-700)] px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-[color:var(--brand-800)] disabled:opacity-50"
        >
          {busy ? "Thinking…" : "Send"}
        </button>
      </form>
    </div>
  );
}
