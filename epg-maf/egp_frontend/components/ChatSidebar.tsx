"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useThreads } from "@/lib/threads-context";

export function ChatSidebar({
  onNewChat,
  onDelete,
}: {
  onNewChat: () => void;
  onDelete: (threadId: string) => Promise<void>;
}) {
  const { threads, loading, error } = useThreads();
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="w-full rounded-md bg-sky-700 px-3 py-2 text-sm font-medium text-white hover:bg-sky-800"
        >
          + New chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2">
        <h2 className="px-2 pt-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Recent chats
        </h2>
        {loading && (
          <p className="p-2 text-sm text-slate-500">Loading…</p>
        )}
        {error && <p className="p-2 text-sm text-red-700">{error}</p>}
        {!loading && !error && threads.length === 0 && (
          <p className="p-2 text-sm text-slate-500">No chats yet.</p>
        )}
        <ul className="space-y-1">
          {threads.map((t) => {
            const href = `/threads/${t.thread_id}`;
            const active = pathname === href;
            return (
              <li key={t.thread_id}>
                <div
                  className={`group flex items-center gap-1 rounded-md px-2 py-2 text-sm ${
                    active
                      ? "bg-sky-50 text-sky-900"
                      : "text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  <Link href={href} className="flex-1 truncate">
                    <span className="block truncate font-medium">
                      {t.title ?? t.patient_id}
                    </span>
                    <span className="block truncate text-xs text-slate-500">
                      {t.patient_id} ·{" "}
                      {new Date(t.last_activity).toLocaleDateString()}
                    </span>
                  </Link>
                  <button
                    onClick={async () => {
                      if (
                        confirm(
                          `Delete this chat for ${t.patient_id}? This cannot be undone.`,
                        )
                      ) {
                        await onDelete(t.thread_id);
                      }
                    }}
                    className="invisible rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-red-700 group-hover:visible"
                    aria-label="Delete chat"
                  >
                    ×
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </aside>
  );
}
