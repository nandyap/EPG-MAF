"use client";

import { useEffect, useRef, useState, FormEvent } from "react";
import { api, HttpError } from "@/lib/api";
import type { ChatResponse, ThreadDetail, ThreadMessage } from "@/lib/types";
import { ChatMessage } from "./ChatMessage";
import { SpecialistCards } from "./SpecialistCards";
import { ErrorBanner } from "./ErrorBanner";

type TranscriptItem =
  | { kind: "message"; msg: ThreadMessage; id: string }
  | { kind: "specialists"; response: ChatResponse; id: string };

export function ChatWindow({ thread }: { thread: ThreadDetail }) {
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
      <header className="border-b border-slate-200 bg-white px-6 py-3">
        <h1 className="text-sm font-semibold text-slate-800">
          {thread.title ?? "Chat"}
        </h1>
        <p className="text-xs text-slate-500">
          Patient <span className="font-mono">{thread.patient_id}</span> ·
          Thread <span className="font-mono">{thread.thread_id}</span>
        </p>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-6 py-4">
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

      <form
        onSubmit={submit}
        className="flex gap-2 border-t border-slate-200 bg-white px-6 py-3"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about this patient…"
          disabled={busy}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500 disabled:bg-slate-50"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-md bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800 disabled:opacity-50"
        >
          {busy ? "Thinking…" : "Send"}
        </button>
      </form>
    </div>
  );
}
