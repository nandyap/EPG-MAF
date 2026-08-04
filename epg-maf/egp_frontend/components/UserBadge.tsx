"use client";

import { useAuth } from "@/lib/auth-context";

export function UserBadge() {
  const auth = useAuth();
  if (auth.status !== "signed-in") return null;
  const { identity } = auth;
  const name = identity.name ?? identity.clinician_id ?? "Signed in";
  return (
    <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-white/60 px-3 py-1.5 text-sm shadow-sm backdrop-blur">
      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[color:var(--brand-700)] text-xs font-medium text-white">
        {name.slice(0, 1).toUpperCase()}
      </div>
      <div className="flex flex-col leading-tight">
        <span className="font-medium text-slate-800">{name}</span>
        <span className="text-[11px] text-slate-500">
          {identity.roles.join(", ") || "Clinician"}
        </span>
      </div>
    </div>
  );
}
