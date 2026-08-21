"use client";

import type { ChatResponse, SpecialistSlot } from "@/lib/types";
import { EvidencePanel } from "./EvidencePanel";

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

// Backend statuses come from SpecialistSlotOutput / SpecialistSlot:
// completed | partial | failed | pending | running. These previously
// read success/failure/skipped, so no case ever matched and every card
// rendered without styling.
function statusStyles(slot: NonNullable<SpecialistSlot>): string {
  switch (slot.status) {
    case "completed":
      return "border-emerald-200 bg-emerald-50 text-emerald-900";
    case "partial":
      return "border-amber-200 bg-amber-50 text-amber-900";
    case "failed":
      return "border-red-200 bg-red-50 text-red-900";
    default:
      return "border-slate-200 bg-slate-50 text-slate-600";
  }
}

export function SpecialistCards({ response }: { response: ChatResponse }) {
  const shown = SPECIALISTS.filter(({ key }) => response[key] !== null);
  if (shown.length === 0) return null;

  return (
    <div className="mt-3 grid grid-cols-1 gap-2">
      {shown.map(({ key, label }) => {
        const slot = response[key];
        if (!slot) return null;

        const summary = slot.output?.output?.summary ?? null;

        return (
          <div
            key={key}
            className={`rounded-md border px-3 py-2 text-xs ${statusStyles(slot)}`}
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold">{label}</span>
              <span className="uppercase tracking-wide">{slot.status}</span>
            </div>

            {summary && <p className="mt-1 whitespace-pre-wrap">{summary}</p>}

            {slot.status === "failed" && (
              <p className="mt-1 italic">
                This information could not be retrieved for this turn.
              </p>
            )}

            <EvidencePanel domain={key} slot={slot} />
          </div>
        );
      })}
    </div>
  );
}
