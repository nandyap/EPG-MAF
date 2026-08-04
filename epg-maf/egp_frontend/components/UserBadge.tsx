"use client";

import { useAuth } from "@/lib/auth-context";

export function UserBadge() {
  const auth = useAuth();
  if (auth.status !== "signed-in") return null;
  const { identity } = auth;
  const name = identity.name ?? identity.clinician_id ?? "Signed in";
  return (
    <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm">
      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-sky-700 text-xs font-medium text-white">
        {name.slice(0, 1).toUpperCase()}
      </div>
      <div className="flex flex-col leading-tight">
        <span className="font-medium text-slate-800">{name}</span>
        <span className="text-xs text-slate-500">
          {identity.roles.join(", ") || "Clinician"}
        </span>
      </div>
    </div>
  );
}
