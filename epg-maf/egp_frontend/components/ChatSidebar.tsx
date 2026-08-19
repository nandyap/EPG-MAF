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
  const { threads, loading, error, refresh } = useThreads();
  const pathname = usePathname();

  return (
    <aside className="panel flex h-full w-72 shrink-0 flex-col overflow-hidden">
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="w-full rounded-lg bg-[color:var(--brand-700)] px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-[color:var(--brand-800)]"
        >
          + New chat
        </button>
      </div>

      <div className="hair-divider mx-3" />

      <div className="flex-1 overflow-y-auto px-2 pt-2">
        <h2 className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
          Recent chats
        </h2>
        {loading && (
          <p className="p-2 text-sm text-slate-500">Loading…</p>
        )}
        {/* Rendered as a bordered card, visually distinct from the chat
            list, so a load failure can never be mistaken for a thread. */}
        {error && !loading && (
          <div className="mx-1 mt-1 rounded-lg border border-red-200 bg-red-50 p-3">
            <p className="text-sm font-medium text-red-800">{error}</p>
            <button
              onClick={() => void refresh()}
              className="mt-2 rounded-md border border-red-300 bg-white px-2 py-1 text-xs font-medium text-red-800 transition hover:bg-red-100"
            >
              Retry
            </button>
          </div>
        )}
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
                  className={`group flex items-center gap-1 rounded-lg px-2 py-2 text-sm transition ${
                    active
                      ? "bg-[color:var(--brand-50)] text-[color:var(--brand-800)] ring-1 ring-[color:var(--brand-100)]"
                      : "text-slate-700 hover:bg-slate-50"
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
