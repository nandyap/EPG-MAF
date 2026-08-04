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
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load chats");
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
