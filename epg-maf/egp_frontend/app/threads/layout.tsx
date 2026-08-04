"use client";

import Image from "next/image";
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
        <p className="text-slate-600">Not signed in — see the home page.</p>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden">
      {/* Top header — spans full width, brand upper-left, user upper-right. */}
      <header className="flex shrink-0 items-center justify-between px-6 py-3">
        <div className="flex items-center gap-3">
          <Image
            src="/branding/M42-logo.png"
            alt="M42"
            width={36}
            height={36}
            priority
            className="h-9 w-auto"
          />
          <div className="hidden h-8 w-px bg-slate-300/70 sm:block" />
          <div className="flex flex-col leading-tight">
            <span className="brand-mark text-lg">EGP Clinical Assistant</span>
            <span className="text-[11px] uppercase tracking-[0.14em] text-slate-500">
              Emirati Genome Program
            </span>
          </div>
        </div>
        <UserBadge />
      </header>

      <div className="flex min-h-0 flex-1 gap-3 px-3 pb-3">
        <ChatSidebar
          onNewChat={() => setModal(true)}
          onDelete={async (id) => {
            await remove(id);
            router.push("/threads");
          }}
        />
        <main className="panel flex min-w-0 flex-1 flex-col overflow-hidden">
          {children}
        </main>
      </div>

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
