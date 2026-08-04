"use client";

import { useRouter } from "next/navigation";
import { useState, ReactNode } from "react";
import { ChatSidebar } from "@/components/ChatSidebar";
import { NewChatModal } from "@/components/NewChatModal";
import { UserBadge } from "@/components/UserBadge";
import { useAuth } from "@/lib/auth-context";
import { useThreads } from "@/lib/threads-context";

export default function ThreadsLayout({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const router = useRouter();
  const { refresh, remove } = useThreads();
  const [modal, setModal] = useState(false);

  if (auth.status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-slate-500">Loading…</p>
      </div>
    );
  }
  if (auth.status === "signed-out") {
    return (
      <div className="flex min-h-screen items-center justify-center p-8">
        <p className="text-slate-600">
          Not signed in — see the home page.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <ChatSidebar
        onNewChat={() => setModal(true)}
        onDelete={async (id) => {
          await remove(id);
          router.push("/threads");
        }}
      />
      <main className="flex flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-2">
          <h1 className="text-sm font-semibold text-slate-700">
            EGP Clinical Assistant
          </h1>
          <UserBadge />
        </div>
        <div className="flex-1 overflow-hidden">{children}</div>
      </main>
      <NewChatModal
        open={modal}
        onClose={() => setModal(false)}
        onCreated={async (threadId) => {
          setModal(false);
          await refresh();
          router.push(`/threads/${threadId}`);
        }}
      />
    </div>
  );
}
