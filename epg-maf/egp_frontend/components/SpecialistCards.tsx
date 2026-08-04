"use client";

import type { ChatResponse, SpecialistSlot } from "@/lib/types";

const SPECIALISTS: {
  key: keyof Pick<
    ChatResponse,
    "prs" | "genomic_variants" | "family_history" | "pgx" | "phenotype"
  >;
  label: string;
}[] = [
  { key: "prs", label: "PRS" },
  { key: "genomic_variants", label: "Genomic variants" },
  { key: "family_history", label: "Family history" },
  { key: "pgx", label: "Pharmacogenomics" },
  { key: "phenotype", label: "Phenotype" },
];

function statusStyles(slot: SpecialistSlot): string {
  if (!slot) return "border-slate-200 bg-slate-50 text-slate-500";
  switch (slot.status) {
    case "success":
      return "border-emerald-200 bg-emerald-50 text-emerald-900";
    case "failure":
      return "border-red-200 bg-red-50 text-red-900";
    case "skipped":
      return "border-slate-200 bg-slate-50 text-slate-600";
  }
}

export function SpecialistCards({ response }: { response: ChatResponse }) {
  const shown = SPECIALISTS.filter(({ key }) => response[key] !== null);
  if (shown.length === 0) return null;

  return (
    <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
      {shown.map(({ key, label }) => {
        const slot = response[key];
        if (!slot) return null;
        return (
          <div
            key={key}
            className={`rounded-md border px-3 py-2 text-xs ${statusStyles(slot)}`}
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold">{label}</span>
              <span className="uppercase tracking-wide">{slot.status}</span>
            </div>
            {slot.summary && (
              <p className="mt-1 whitespace-pre-wrap">{slot.summary}</p>
            )}
            {slot.reason && slot.status !== "success" && (
              <p className="mt-1 italic">{slot.reason}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
