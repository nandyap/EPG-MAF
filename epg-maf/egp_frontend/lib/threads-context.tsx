"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";
import { api } from "./api";
import type { ThreadListItem } from "./types";

type ThreadsState = {
  threads: ThreadListItem[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  remove: (threadId: string) => Promise<void>;
};

const Ctx = createContext<ThreadsState | null>(null);

export function ThreadsProvider({ children }: { children: ReactNode }) {
  const [threads, setThreads] = useState<ThreadListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.listThreads();
      setThreads(resp.threads);
    } catch {
      // Show a stable, user-facing message rather than the raw backend
      // string. A server-side fault (e.g. a document that fails schema
      // validation) otherwise surfaces here as something that reads like
      // a user mistake — and, rendered in the list, like a chat entry.
      setError("Couldn't load your chats.");
      setThreads([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const remove = useCallback(
    async (threadId: string) => {
      await api.deleteThread(threadId);
      setThreads((prev) => prev.filter((t) => t.thread_id !== threadId));
    },
    [],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <Ctx.Provider value={{ threads, loading, error, refresh, remove }}>
      {children}
    </Ctx.Provider>
  );
}

export function useThreads(): ThreadsState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useThreads must be used inside <ThreadsProvider>");
  return v;
}
