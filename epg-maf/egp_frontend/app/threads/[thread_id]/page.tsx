"use client";

import { use, useEffect, useState } from "react";
import { api, HttpError } from "@/lib/api";
import type { ThreadDetail } from "@/lib/types";
import { ChatWindow } from "@/components/ChatWindow";
import { ErrorBanner } from "@/components/ErrorBanner";

export default function ThreadPage({
  params,
}: {
  params: Promise<{ thread_id: string }>;
}) {
  const { thread_id } = use(params);
  const [thread, setThread] = useState<ThreadDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setThread(null);
    setError(null);
    api
      .getThread(thread_id)
      .then((doc) => {
        if (!cancelled) setThread(doc);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof HttpError && e.status === 404) {
          setError("This chat is not available.");
        } else {
          setError(e instanceof Error ? e.message : "Failed to load chat");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [thread_id]);

  if (error) {
    return (
      <div className="p-6">
        <ErrorBanner message={error} />
      </div>
    );
  }
  if (!thread) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-slate-500">Loading chat…</p>
      </div>
    );
  }
  return <ChatWindow thread={thread} />;
}
