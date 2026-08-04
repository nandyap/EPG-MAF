"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export default function HomePage() {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (auth.status === "signed-in") {
      router.replace("/threads");
    }
  }, [auth.status, router]);

  if (auth.status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-slate-500">Loading…</p>
      </main>
    );
  }

  if (auth.status === "signed-out") {
    return (
      <main className="flex min-h-screen items-center justify-center p-8">
        <div className="max-w-md rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
          <h1 className="text-xl font-semibold">EGP Clinical Assistant</h1>
          <p className="mt-4 text-sm text-slate-600">
            You are not signed in. In production this page redirects to Entra
            ID via Container Apps Easy Auth. In dev, set{" "}
            <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">
              NEXT_PUBLIC_DEV_BEARER
            </code>{" "}
            in <code>.env.local</code>.
          </p>
        </div>
      </main>
    );
  }

  return null;
}
