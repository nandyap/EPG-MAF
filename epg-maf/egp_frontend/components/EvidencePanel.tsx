"use client";

import { useState } from "react";
import type { Provenance, SpecialistSlot } from "@/lib/types";

// One clinical fact plus the database rows it came from.
type Fact = {
  headline: string;
  detail: string;
  interpretation: string | null;
  interpretationModel: string | null;
  provenance: Provenance[];
};

function str(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

/**
 * Build a display label for one result row.
 *
 * Each domain names its findings differently — a variant by gene and
 * coordinate, a PRS by score name, PGx by gene and drug — so the label
 * is domain-specific rather than a generic key dump.
 */
function label(domain: string, r: Record<string, unknown>): {
  headline: string;
  detail: string;
} {
  const core = (r.core_annotations ?? {}) as Record<string, unknown>;
  let headline = "";
  let bits: (string | null)[] = [];

  switch (domain) {
    case "genomic_variants":
      headline = [str(core.gene), str(r.variant_id)].filter(Boolean).join("  ");
      bits = [
        str(core.pathogenicity),
        str(core.variant_type),
        str(core.disease_name),
      ];
      break;
    case "prs":
      headline = [str(r.prs_name), str(r.disease_name)].filter(Boolean).join("  ");
      bits = [
        r.prs_score !== null && r.prs_score !== undefined
          ? `score ${r.prs_score}`
          : null,
        r.percentile !== null && r.percentile !== undefined
          ? `${r.percentile}th percentile`
          : null,
        str(r.risk_band),
      ];
      break;
    case "pgx":
      headline = [str(r.gene), str(r.phenotype)].filter(Boolean).join("  ");
      bits = [str(r.drug), str(r.recommendation)];
      break;
    case "family_history":
      headline = str(r.disease_name) ?? "";
      bits = [
        str(r.criteria_name),
        r.meets_threshold === true
          ? "threshold met"
          : r.meets_threshold === false
            ? "threshold not met"
            : null,
      ];
      break;
    default:
      headline = str(r.disease_name) ?? str(r.term) ?? "";
      bits = [str(r.code), str(r.code_type)];
  }

  return {
    headline: headline || "(unnamed finding)",
    detail: bits.filter(Boolean).join(" · "),
  };
}

/**
 * Pull facts out of a slot.
 *
 * Note the double `output`: SpecialistSlot.output holds a serialised
 * <Domain>StateOutput, which itself has an `output` holding the result
 * list.
 */
export function extractFacts(domain: string, slot: SpecialistSlot): Fact[] {
  const results = slot?.output?.output?.results;
  if (!Array.isArray(results)) return [];

  return results.map((r) => {
    const { headline, detail } = label(domain, r);
    const prov = Array.isArray(r.provenance)
      ? (r.provenance as Provenance[])
      : [];
    return {
      headline,
      detail,
      interpretation: str(r.interpretation),
      interpretationModel: str(r.interpretation_model),
      provenance: prov,
    };
  });
}

export function countSources(domain: string, slot: SpecialistSlot): number {
  return extractFacts(domain, slot).reduce(
    (n, f) => n + f.provenance.length,
    0,
  );
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function cellValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// Keys that are not database columns and must not appear under
// "Database row as retrieved".
//
// On the ReAct path, _attach_provenance sets source_row from the tool's
// output row — which for a get_* tool is an already-serialised result
// object, so it carries the model's own interpretation and a nested copy
// of the provenance record we are currently rendering. Showing those
// back would both duplicate the panel and, worse, present LLM-derived
// text as if it were retrieved data.
const NON_COLUMN_KEYS = new Set([
  "provenance",
  "interpretation",
  "interpretation_model",
  "summary_model",
]);

function ProvenanceRecord({ p }: { p: Provenance }) {
  const params = Object.entries(p.tool_parameters ?? {});
  const row = Object.entries(p.source_row ?? {}).filter(
    ([k]) => !NON_COLUMN_KEYS.has(k),
  );

  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1 text-[11px]">
        <dt className="text-slate-500">Retrieved</dt>
        <dd className="font-mono text-slate-800">
          {formatTime(p.retrieved_at)}
        </dd>

        <dt className="text-slate-500">Tool</dt>
        <dd className="font-mono text-slate-800">{p.tool_name}</dd>

        {params.length > 0 && (
          <>
            <dt className="text-slate-500">Parameters</dt>
            <dd className="font-mono text-slate-800">
              {params.map(([k, v]) => `${k}=${cellValue(v)}`).join(", ")}
            </dd>
          </>
        )}

        <dt className="text-slate-500">Source</dt>
        <dd className="font-mono text-slate-800">{p.source_table}</dd>

        {p.fields_derived?.length > 0 && (
          <>
            <dt className="text-slate-500">Populated</dt>
            <dd className="text-slate-700">{p.fields_derived.join(", ")}</dd>
          </>
        )}
      </dl>

      {row.length > 0 && (
        <div className="mt-2">
          <p className="mb-1 text-[11px] font-medium text-slate-600">
            Database row as retrieved
          </p>
          <div className="overflow-x-auto rounded border border-slate-100">
            <table className="w-full border-collapse text-[11px]">
              <tbody>
                {row.map(([k, v]) => (
                  <tr key={k} className="border-b border-slate-100 last:border-0">
                    <td className="w-40 bg-slate-50 px-2 py-1 align-top font-mono text-slate-600">
                      {k}
                    </td>
                    <td className="px-2 py-1 align-top font-mono break-all text-slate-800">
                      {cellValue(v)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Expandable evidence trail for one specialist domain.
 *
 * Renders stored provenance only — nothing here is generated or inferred
 * by a model. Every row shown is the exact record the repository read
 * from Postgres at query time.
 */
export function EvidencePanel({
  domain,
  slot,
}: {
  domain: string;
  slot: SpecialistSlot;
}) {
  const [open, setOpen] = useState(false);
  const facts = extractFacts(domain, slot);
  const sources = facts.reduce((n, f) => n + f.provenance.length, 0);

  if (facts.length === 0) return null;

  const unevidenced = facts.filter((f) => f.provenance.length === 0).length;

  return (
    <div className="mt-2 border-t border-slate-200/70 pt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-[11px] font-medium text-slate-600 transition hover:text-slate-900"
      >
        <span>
          {open ? "▾" : "▸"} Evidence
          <span className="ml-1 font-normal text-slate-500">
            ({sources} source{sources === 1 ? "" : "s"} for {facts.length}{" "}
            finding{facts.length === 1 ? "" : "s"})
          </span>
        </span>
        {unevidenced > 0 && (
          <span className="text-amber-700">
            {unevidenced} without evidence
          </span>
        )}
      </button>

      {open && (
        <div className="mt-2 space-y-3">
          {facts.map((f, i) => (
            <div key={i} className="rounded-md bg-slate-50/80 p-2">
              <p className="text-xs font-semibold text-slate-800">
                {f.headline}
              </p>
              {f.detail && (
                <p className="text-[11px] text-slate-600">{f.detail}</p>
              )}

              {f.interpretation && (
                <p className="mt-1 text-[11px] italic text-slate-600">
                  {f.interpretation}
                  {f.interpretationModel && (
                    <span className="not-italic text-slate-400">
                      {" "}
                      — {f.interpretationModel}
                    </span>
                  )}
                </p>
              )}

              <div className="mt-2 space-y-2">
                {f.provenance.length === 0 ? (
                  <p className="text-[11px] text-amber-700">
                    No database record was linked to this finding.
                  </p>
                ) : (
                  f.provenance.map((p, j) => (
                    <ProvenanceRecord key={j} p={p} />
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
