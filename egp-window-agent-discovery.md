# EGP Window — Full Project Context

> **Repo recommendation:** `m42-egp-genomics-agent`
> **Owner (Microsoft):** Hamza El-Ghoujdami — Sr. Cloud & AI Architect, Microsoft UAE
> **Customer:** M42 — BIX / Genomics team (Emirati Genomics Program)
> **Initial users:** CCAD physicians (breast oncology being the first scenario)
> **Status (18 June 2026):** Customer prerequisites returned. Ready for Microsoft-side LLD review before Factory kickoff.
> **Classification:** Internal. **Synthetic data only — no real PHI**.

---

## 1. Executive Summary

EGP Window is an **AI-powered genomic decision-support assistant** for M42 clinicians. It allows a doctor to query patient-specific genomic information (pathogenic variants, PRS, PGx, family history, diagnoses) alongside clinical context to support diagnosis and treatment planning.

It is built on top of the **Emirati Genomics Program (EGP)** — UAE's national genomics initiative — and the first clinical pilot is targeted at **Cleveland Clinic Abu Dhabi (CCAD)**, specifically the breast oncology team.

**This is NOT** a diagnostic AI, autonomous treatment system, or a pure RAG chatbot. It is a **tool-calling agent over structured genomics data**, with a doctor always-in-the-loop.

**Phase 1 mandate:** *Replicate the existing M42 prototype on the Microsoft stack. Nothing more, nothing less.*

---

## 2. Business Context

### 2.1 What is EGP?
The **Emirati Genomics Program (EGP)** is a UAE national initiative to build a population-scale genomic dataset of Emirati citizens, used for precision medicine, hereditary risk assessment, clinical trials, and research.

M42 hosts the EGP infrastructure on Microsoft Azure, including the genomics processing pipeline and the Trusted Research Environment (TRE).

### 2.2 What is EGP Window?
EGP Window is the **clinician-facing interface layer** on top of the EGP. Where EGP stores and processes genomic data, EGP Window allows doctors to **ask questions** about a specific patient and get grounded, traceable responses combining:

- Genomic data (variants, PRS, PGx)
- Family history
- Diagnoses
- Demographics
- Clinical context

### 2.3 Why does it matter?
Without this agent, a doctor manually navigates multiple genomic datasets and reports per patient. The agent reduces consultation prep time, increases the chance of catching pathogenic variants, and improves treatment decisions (e.g., drug selection, dose adjustment, family screening).

---

## 3. Users & Use Cases

### 3.1 Primary user
- **CCAD breast oncology physicians** (first cohort)
- Long term: broader CCAD specialty teams and M42 clinical staff

### 3.2 Example questions the agent must answer
- "What pathogenic variants does patient X carry, and what diseases are associated?"
- "What PGx recommendations exist for drug Y, given the patient's phenotype?"
- "What is patient X's PRS risk for disease Z?"
- "What does the family history suggest about breast cancer risk?"
- "Show all diagnoses for patient X."

### 3.3 Out of scope (Phase 1)
- AI making clinical diagnosis
- Autonomous treatment recommendation
- Self-improvement / online learning loop
- Multi-patient cohort analysis
- Population-level analytics

---

## 4. Architecture

### 4.1 Architectural pattern
This is an **Agentic Retrieval system** — NOT a vector-RAG chatbot.

| Layer | Role |
|---|---|
| UI | Standalone clinician chat UI (similar to LangSmith / dev UI) |
| Agent | Microsoft Agent Framework (MAF), hosted on Azure AI Foundry |
| Tools / Skills | Function tools that query the genomics DB directly |
| MCP Server | Built in parallel by M42; agent will integrate with it |
| Models | Compass-hosted models (Core42) via APIM |
| Data | Direct database access (preferred by customer) |
| Auth | Clinical-grade (OAuth-style, to be designed by Microsoft) |

### 4.2 Existing prototype
M42 has already implemented a working prototype in **LangGraph** as a Shiny web app. The Microsoft Factory will **port this to the Microsoft stack** (MAF + Azure + Foundry + Compass).

### 4.3 Tool inventory (from handover)
Tools are described as **on-demand lookup tools**, not sequential workflows:
- Patient Info lookup
- Pathogenic Variants lookup
- Polygenic Risk Score (PRS) lookup
- Pharmacogenomics (PGx) lookup
- Family History lookup
- Diagnosis Codes lookup
- (Additional tools TBD from schema review)

### 4.4 Reasoning model
- Customer asked Microsoft to clarify "non-medical-grade reasoning model" terminology
- They are open to mix-of-models as long as available on **Compass**
- LLM selection MUST be Compass-hosted, in UAE region

---

## 5. Customer Prerequisites — Status Matrix

Reference email: Donal O'Shea (M42 Senior Bioinformatician) to Olga Gubina, **16 June 2026, "[EXTERNAL] Re: EGP Window Access - next steps"** — attachment `EGPWindow.zip`.

| # | Prerequisite | Status | Customer Response |
|---|---|---|---|
| 1 | Definition of "working MVP" | ✅ Provided | Genomic-retrieval assistant for a specific patient, traceable tool outputs, end-to-end in chat UI. No free-form guessing. |
| 2 | Example evaluation questions | ✅ Provided | Variants/diseases, PGx for a drug, PRS for a disease — clinician verified. |
| 3 | Expected accuracy tolerance | ✅ Provided | Tool retrieval ~100% accuracy; synthesis high but clinician-verified. |
| 4 | Existing evaluation approach | ⚠️ Not available | Customer asked Microsoft to define evaluation methodology. |
| 5 | Genomics DB / schema | ✅ Provided | Included in shared ZIP code base. |
| 6 | Sample anonymized data | ✅ Provided | Synthetic datasets: demographics, variants, PGx, PRS, diagnoses, kinship/family history. |
| 7 | Data access method | ✅ Confirmed | Direct DB access preferred. Customer asked if Microsoft will host. |
| 8 | Existing logic/functions | ✅ Provided | Substantial reusable logic included in ZIP. |
| 9 | UI expectation | ✅ Provided | Standalone dev UI (LangSmith-style) alongside MCP server. |
| 10 | Security / authentication | ⚠️ Joint | Customer requires clinical-grade auth (OAuth). Microsoft to design. |
| 11 | Non-medical reasoning model | ⚠️ Clarify | Customer asked Microsoft to clarify the term; open to mixed models on Compass. |
| 12 | Domain expert | ✅ Confirmed | BIX team (Donal O'Shea, Santosh Elavalli) available to review logic. |
| 13 | Subscription / environment | ✅ Created | M42 created an Azure subscription for EGP Window; Hari Balasubramani onboarding Factory team. |
| 14 | Factory access / VDI | ⚠️ In progress | Hari requested reusing existing M42 VDI access to avoid long onboarding. |

---

## 6. What M42 Delivered in the ZIP (`EGPWindow.zip`)

Confirmed by customer email of 16 June 2026:
- Database schema
- Existing application code (LangGraph-based prototype)
- Reusable logic / functions
- Synthetic anonymized datasets covering:
  - Patient demographics
  - Genomic variants
  - PGx data
  - PRS data
  - Diagnoses
  - Kinship / family history

**Action:** Factory needs to unzip, review, and validate the schema against expected agent tools before kickoff.

---

## 7. What is Still Missing / Microsoft-Owned

| # | Item | Owner | Notes |
|---|---|---|---|
| 1 | Low-Level Architecture Document (LLD) | Hamza | Must validate data flow, tools, security, hosting model. |
| 2 | Schema validation against agent tools | Factory (Varun/Kush) + Hamza | Confirm provided tables map to required lookups. |
| 3 | Authentication / authorization design | Microsoft (Hamza + Saad) | Clinical-grade, OAuth-style. |
| 4 | Evaluation framework | Microsoft (Saad + Sajid) | Define how MVP is scored. |
| 5 | Hosting decision | Joint | Is the DB hosted in Microsoft subscription or M42 subscription? |
| 6 | UI implementation owner | Joint | Customer wants standalone testing UI. Factory or partner UI? |
| 7 | Integration target (long-term) | Open | Possible future integration with CCAD Caregiver Assistant. |
| 8 | Compass model selection | Hamza | Confirm model availability and routing via APIM. |

---

## 8. Key Stakeholders

### 8.1 Microsoft
| Name | Role |
|---|---|
| Hamza El-Ghoujdami | Sr. Cloud & AI Architect (LLD / solution lead) |
| Olga Gubina | Sr. Cloud & AI Specialist (use-case owner / customer comms) |
| Jad Salloum | Principal CSAM (account / nomination) |
| Muhammad Sajid | Sr. AI Engineer (use-case domain knowledge from customer) |
| Saad Mahmood | Global CSA — GenAI (Factory lead / gating) |
| Kush Swaroop | Factory Engineering |
| Varun Balakrishnan Nambiar | Factory Engineering |
| Shagun Saraswat | Account / Customer Success |

### 8.2 M42 / Customer
| Name | Role |
|---|---|
| Donal O'Shea | Senior Bioinformatician — BIX (primary domain expert) |
| Santosh Elavalli | Senior Bioinformatician — BIX |
| Raony Cardenas | BIX team |
| Harikumar Balasubramani | Enterprise Architect (infra / access) |
| Dr. Zainab Abdelhamid | Executive sponsor (M42 / aware of use case) |

---

## 9. Key Decisions Made

1. **Phase 1 = replicate existing prototype only.** No self-improvement, no new capabilities.
2. **Tech stack = Microsoft Agent Framework + Azure + Foundry + APIM + Compass.**
3. **LLM = Compass-hosted, UAE region.**
4. **Data lives in UAE.** Same residency rules as other M42 use cases.
5. **Direct DB access preferred** over API.
6. **Standalone UI for testing**, not initially integrated into Caregiver Assistant (but possible future).
7. **Factory will NOT kick off** until LLD + schema validation are complete.
8. **Doctor is human-in-the-loop**; agent provides info, doctor decides.

---

## 10. Risks & Open Questions

| # | Item | Risk | Mitigation |
|---|---|---|---|
| 1 | Schema gap between what's in ZIP and what the agent needs | Medium | LLD review + data validation session with Donal O'Shea |
| 2 | Authentication model not yet designed | Medium | Microsoft to propose OAuth + RBAC plan |
| 3 | Evaluation framework missing | Medium | Microsoft to propose eval approach; reuse from CPG Agent pattern |
| 4 | Hosting model unclear (DB stays on M42 or moves to MS subscription?) | Medium | Confirm in LLD session |
| 5 | Compass model choice / latency for genomics queries | Low–Med | Validate during LLD with APIM team |
| 6 | UI scope creep (standalone vs Caregiver Assistant) | Medium | Lock scope: standalone testing UI for Phase 1 only |
| 7 | Factory onboarding via VDI vs new identities | Low | Use existing M42 VDI access where possible (per Hari) |

---

## 11. Timeline / Next Steps

| Step | Owner | Target |
|---|---|---|
| Review customer-provided ZIP and code | Hamza + Factory | This week |
| Schedule LLD working session with BIX | Olga + Hamza | This week |
| Validate schema and identify gaps | Hamza + Sajid + Donal | Next ~5 days |
| Define auth + eval approach | Hamza + Saad | Within 2 weeks |
| Finalize LLD document | Hamza | Before kickoff |
| Kickoff with customer | Olga + Jad | After LLD signed off |
| Phase 1 MVP development | Factory (Kush / Varun) | TBD post-kickoff |

---

## 12. Architectural Notes for Implementation

### 12.1 Pattern
```
Doctor (UI)
    │
    ▼
Agent (MAF on Foundry)
    │
    ├── Patient Info Tool ───┐
    ├── Variant Lookup ──────┤
    ├── PRS Lookup ──────────┼──► Genomics DB
    ├── PGx Lookup ──────────┤
    ├── Family History Tool ─┤
    └── Diagnosis Lookup ────┘
    │
    ▼
Compass LLM (via APIM)
    │
    ▼
Grounded Response → Doctor
```

### 12.2 Required Azure components
- Azure AI Foundry (agent hosting)
- Microsoft Agent Framework (MAF)
- APIM as AI Gateway → Core42 Compass
- Azure SQL or Postgres (genomics DB, per chosen hosting model)
- Application Insights + Log Analytics (observability)
- Entra ID (auth)
- Key Vault (secrets)
- Bicep IaC for deployment

### 12.3 Repo structure (suggested)
```
m42-egp-genomics-agent/
├── README.md
├── CONTEXT.md                    ← this file
├── docs/
│   ├── architecture/
│   │   ├── high-level.md
│   │   ├── low-level.md
│   │   └── diagrams/
│   ├── customer-inputs/
│   │   ├── prerequisites-response.md
│   │   └── schema.md
│   ├── evaluations/
│   └── security/
├── src/
│   ├── agent/
│   ├── tools/
│   │   ├── patient_info.py
│   │   ├── variants.py
│   │   ├── prs.py
│   │   ├── pgx.py
│   │   ├── family_history.py
│   │   └── diagnoses.py
│   ├── ui/
│   └── eval/
├── infra/
│   ├── bicep/
│   └── README.md
├── data/
│   └── synthetic/                ← from M42 ZIP
├── tests/
└── .github/
    └── workflows/
```

---

## 13. Reference Materials (internal)

- **Customer email**: "[EXTERNAL] Re: EGP Window Access - next steps" — Donal O'Shea, 16 June 2026 (with `EGPWindow.zip`)
- **Internal handover meeting**: "EGP Window - Use Case Handover (internal call)" — 9 June 2026, organized by Olga Gubina
- **Harness Approach - M42** transcript — 2 June 2026 (Olga + Sajid raised the use case to Jad)
- **G42 AI Engagements Tracker** — EGP Window listed as "Factory + CSU, In Progress"
- **M42-CCAD Unified ROSSs Tracking** — IHS EGP Window Agent, 20 hours, July, "On Track"
- **Dataverse milestone**: "EGP Window - Initial POC" (Active, Owner: Jad Salloum, created 14 April 2026)

---

## 14. One-Line Summary for AI Coding Assistants

> Build a **MAF-based agentic assistant** that lets M42/CCAD doctors query a **genomics database** via on-demand tools (patient, variants, PRS, PGx, family history, diagnoses), grounded in **Compass-hosted LLMs**, hosted in **UAE**, with **clinical-grade auth** and **clinician-in-the-loop**, replicating an existing LangGraph prototype as **Phase 1**.

---

*Last updated: 18 June 2026 — Hamza El-Ghoujdami*
