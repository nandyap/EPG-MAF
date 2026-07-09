-- =============================================================================
-- Clinical Genomics Agent Database Schema
-- DuckDB compatible
--
-- Designed to match the PRS and genomic variant agent schemas exactly.
-- Each table is annotated with which agent and which Pydantic model it feeds.
-- =============================================================================


-- =============================================================================
-- PATIENTS
-- Core patient table. patient_id is the shared FK across all tables.
-- Feeds: OrchestratorState.patient_id
-- Change: date_of_birth replaces age (age is derived, not stored)
-- =============================================================================

CREATE SEQUENCE patients_seq START 1;

CREATE TABLE patients (
    patient_id              VARCHAR PRIMARY KEY,
    medical_record_number   VARCHAR,
    date_of_birth           DATE NOT NULL,
    sex                     VARCHAR,
    created_date            DATE,
    last_updated            DATE,
    CHECK (sex IN ('female', 'male', 'other', 'unknown'))
);

CREATE INDEX idx_patients_mrn ON patients(medical_record_number);


-- =============================================================================
-- DIAGNOSES / PHENOTYPE
-- Feeds: phenotype subagent
-- Change: description column added to carry human-readable term alongside code
-- =============================================================================

CREATE SEQUENCE diagnoses_seq START 1;

CREATE TABLE diagnoses (
    id              INTEGER DEFAULT nextval('diagnoses_seq') PRIMARY KEY,
    patient_id      VARCHAR NOT NULL,
    code            VARCHAR NOT NULL,
    code_type       VARCHAR NOT NULL,
    term            VARCHAR NOT NULL,
    description     VARCHAR,
    disease_name    VARCHAR,
    encounter_date  DATE,
    recorded_date   DATE,
    visit_id        VARCHAR,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    UNIQUE (patient_id, code, encounter_date),
    CHECK (code_type IN ('ICD10', 'ICD9', 'SNOMED', 'HPO', 'OMIM', 'MONDO', 'OTHER'))
);

CREATE INDEX idx_diagnoses_patient         ON diagnoses(patient_id);
CREATE INDEX idx_diagnoses_code            ON diagnoses(code);
CREATE INDEX idx_diagnoses_date            ON diagnoses(encounter_date);
CREATE INDEX idx_diagnoses_code_type       ON diagnoses(code_type);
CREATE INDEX idx_diagnoses_disease         ON diagnoses(disease_name);
CREATE INDEX idx_diagnoses_patient_disease ON diagnoses(patient_id, disease_name);


-- =============================================================================
-- PRS
-- Feeds: PRSResult, PRSResultList (agents/prs/state/schemas.py)
--
-- patient_prs      → PRSResult.prs_score, .percentile, .risk_band
--                    NOTE: risk_band (interpretation) stored here as a DB-level
--                    value. The agent may override or re-derive it.
--                    prs_name added as FK to prs_annotations for JOIN.
--
-- prs_annotations  → PRSResult.source, .metadata_notes, .disease_name
--
-- Changes vs previous schema:
--   - patient_prs: added prs_name column (FK to prs_annotations)
--   - patient_prs: renamed score → prs_score for clarity
--   - patient_prs: renamed disease → disease_name for consistency
--   - patient_prs: score range 0-1 kept (matches CHECK constraint)
--   - patient_prs: interpretation vocabulary updated to match PRSResult.risk_band
--     low | average | high | very_high  (was: low | average | elevated | high)
--   - prs_annotations: renamed disease → disease_name
--   - prs_annotations: added notes column (feeds PRSResult.metadata_notes)
-- =============================================================================

CREATE TABLE prs_annotations (
    prs_name        VARCHAR PRIMARY KEY,                    -- e.g. PRS_CAD_001
    disease_name    VARCHAR NOT NULL,                       -- e.g. Coronary Artery Disease
    source          VARCHAR,                                -- e.g. PGS Catalog PGS000013
    notes           VARCHAR,                                -- feeds PRSResult.metadata_notes
    last_updated    DATE
);

CREATE INDEX idx_prs_annotations_disease ON prs_annotations(disease_name);

CREATE TABLE patient_prs (
    patient_id      VARCHAR,
    prs_name        VARCHAR NOT NULL,
    disease_name    VARCHAR NOT NULL,
    prs_score       FLOAT NOT NULL,
    percentile      INTEGER,
    risk_band       VARCHAR,
    prs_tool        VARCHAR,
    computed_date   DATE,
    last_updated    DATE,
    FOREIGN KEY (patient_id)  REFERENCES patients(patient_id),
    FOREIGN KEY (prs_name)    REFERENCES prs_annotations(prs_name),
    CHECK (percentile BETWEEN 0 AND 100),
    CHECK (risk_band IN ('low', 'average', 'high', 'very_high')),
    PRIMARY KEY (patient_id, prs_name)
);

CREATE INDEX idx_patient_prs_disease   ON patient_prs(disease_name);
CREATE INDEX idx_patient_prs_name      ON patient_prs(prs_name);
CREATE INDEX idx_patient_prs_risk_band ON patient_prs(risk_band);


-- =============================================================================
-- GENOMIC VARIANTS
-- Feeds: GenomicVariantResult, GenomicVariantsResultList
--        (agents/genomic_variants/state/schemas.py)
--
-- patient_variants     → links patient to variant (no sample-level data yet;
--                         genotype / platform / caller columns added here
--                         to feed VariantSampleData)
--
-- variant_annotations  → feeds VariantCoreAnnotations + VariantExtendedAnnotations
--                         Core filterable columns remain top-level.
--                         Extended annotations stored in annotations_json (JSONB).
--
-- Changes vs previous schema:
--   patient_variants:
--     - genotype added            → VariantSampleData.genotype
--     - sequencing_platform added → VariantSampleData.sequencing_platform
--     - variant_caller added      → VariantSampleData.variant_caller
--     - call_quality added        → VariantSampleData.call_quality
--
--   variant_annotations:
--     - variant_type added        → VariantCoreAnnotations.variant_type
--     - disease_name renamed from disease
--     - pathogenicity_source kept as supporting metadata
--     - clinical_significance kept (may differ from pathogenicity)
--     - inheritance kept
--     - population_note kept
--     - supporting_evidence kept
--     - annotations_json added    → VariantExtendedAnnotations (JSONB blob)
--       contains: rsid, hgvs_c, hgvs_p, gnomad_af, gnomad_af_popmax,
--                 sift, polyphen, cadd_score, acmg_criteria,
--                 acmg_classification, and any other annotations
--     - hgvs_c, hgvs_p, gnomad_af, common_name moved to annotations_json only
--       (no longer promoted to top-level columns)
--     - pathogenicity vocabulary: VUS → 'Variant of Uncertain Significance'
--       for consistency with ClinVar full terminology
-- =============================================================================

CREATE TABLE variant_annotations (
    variant_id              VARCHAR PRIMARY KEY,
    gene                    VARCHAR NOT NULL,
    variant_type            VARCHAR,
    pathogenicity           VARCHAR,
    pathogenicity_source    VARCHAR,
    disease_name            VARCHAR,
    inheritance             VARCHAR,
    notes                   VARCHAR,
    annotations_json        JSON,
    created_date            DATE,
    last_updated            DATE,
    CHECK (pathogenicity IN (
        'Pathogenic',
        'Likely Pathogenic',
        'Variant of Uncertain Significance',
        'Likely Benign',
        'Benign',
        'Unknown'
    )),
    CHECK (inheritance IN (
        'Autosomal Dominant',
        'Autosomal Recessive',
        'X-Linked',
        'Y-Linked',
        'Complex',
        'Mitochondrial',
        'Unknown'
    ))
);

CREATE INDEX idx_variant_annotations_gene          ON variant_annotations(gene);
CREATE INDEX idx_variant_annotations_disease       ON variant_annotations(disease_name);
CREATE INDEX idx_variant_annotations_pathogenicity ON variant_annotations(pathogenicity);
CREATE INDEX idx_variant_annotations_gene_path     ON variant_annotations(gene, pathogenicity);

CREATE TABLE patient_variants (
    patient_id          VARCHAR,
    variant_id          VARCHAR,
    genotype            VARCHAR,
    zygosity            VARCHAR,
    sequencing_platform VARCHAR,
    variant_caller      VARCHAR,
    call_quality        FLOAT,
    computed_date       DATE,
    last_updated        DATE,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (variant_id) REFERENCES variant_annotations(variant_id),
    PRIMARY KEY (patient_id, variant_id)
);

CREATE INDEX idx_patient_variants_variant ON patient_variants(variant_id);


-- =============================================================================
-- PGX
-- Feeds: pgx subagent
--
-- patient_pgx_status   → diplotype and phenotype per gene for patient
-- pgx_annotations      → drug recommendations keyed on gene + phenotype
--
-- Changes vs previous schema:
--   - recommendation_level → recommendation (free text, CPIC-sourced)
--   - phenotype CHECK constraint added to pgx_annotations
--   - metabolizer_status vocabulary standardised to title case
-- =============================================================================

CREATE TABLE patient_pgx_status (
    patient_id      VARCHAR,
    gene            VARCHAR NOT NULL,
    diplotype       VARCHAR,
    phenotype       VARCHAR,
    pgx_tool        VARCHAR,
    computed_date   DATE,
    last_updated    DATE,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    PRIMARY KEY (patient_id, gene),
    CHECK (phenotype IN (
        'Poor Metabolizer',
        'Intermediate Metabolizer',
        'Normal Metabolizer',
        'Rapid Metabolizer',
        'Unknown'
    ))
);

CREATE INDEX idx_patient_pgx_gene ON patient_pgx_status(gene);

CREATE SEQUENCE drug_rec_seq START 1;

CREATE TABLE pgx_annotations (
    id                      INTEGER DEFAULT nextval('drug_rec_seq') PRIMARY KEY,
    gene                    VARCHAR NOT NULL,
    phenotype               VARCHAR NOT NULL,
    drug                    VARCHAR NOT NULL,
    recommendation          VARCHAR,
    summary                 VARCHAR,
    source                  VARCHAR,
    created_date            DATE,
    last_updated            DATE,
    CHECK (phenotype IN (
        'Poor Metabolizer',
        'Intermediate Metabolizer',
        'Normal Metabolizer',
        'Rapid Metabolizer',
        'Unknown'
    )),
    UNIQUE (gene, phenotype, drug)
);

CREATE INDEX idx_pgx_annotations_lookup    ON pgx_annotations(gene, phenotype);
CREATE INDEX idx_pgx_annotations_gene      ON pgx_annotations(gene);
CREATE INDEX idx_pgx_annotations_drug      ON pgx_annotations(drug);
CREATE INDEX idx_pgx_annotations_drug_gene ON pgx_annotations(drug, gene);


-- =============================================================================
-- FAMILY HISTORY
-- Feeds: family_history subagent
--
-- patient_kinship_history      → per-patient, per-disease family history record
-- kinship_history_annotations  → reference data about each disease/criteria
--
-- Changes vs previous schema:
--   patient_kinship_history:
--     - criteria renamed → criteria_name for clarity
--     - affected_degree renamed → relationship_degree
--       vocabulary extended: added 'third' and 'first_and_second' already present,
--       now also consistent with agent state field name
--     - threshold_value added    → numeric threshold for criteria
--     - threshold_source added   → where the threshold comes from e.g. NCCN
--     - affected_relative_count added → how many relatives are affected
--     - total_relatives_searched added  → denominator for threshold computation
--     - search_context_notes added      → simulated demographic completeness note
--     - last_observed_diagnosis_in_database added → OMOP DB release date (data currency)
--     - relationship_degree, threshold_type, threshold_value, notes removed
--       (threshold details live in kinship_history_annotations; notes were redundant)
--     - PRIMARY KEY extended to (patient_id, disease_name, criteria_name)
--       to allow multiple criteria per disease per patient
--
--   kinship_history_annotations:
--     - disease renamed → disease_name
--     - criteria_name added for per-criteria annotations
-- =============================================================================

CREATE TABLE patient_kinship_history (
    patient_id                          VARCHAR NOT NULL,
    disease_name                        VARCHAR NOT NULL,
    criteria_name                       VARCHAR NOT NULL,
    affected_relative_count             INTEGER,
    total_relatives_searched            INTEGER,
    search_context_notes                TEXT,
    last_observed_diagnosis_in_database DATE,
    meets_threshold                     BOOLEAN NOT NULL,
    computed_date                       DATE,
    last_updated                        DATE,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (disease_name, criteria_name)
        REFERENCES kinship_history_annotations(disease_name, criteria_name),
    PRIMARY KEY (patient_id, disease_name, criteria_name)
);

CREATE INDEX idx_kinship_patient         ON patient_kinship_history(patient_id);
CREATE INDEX idx_kinship_disease         ON patient_kinship_history(disease_name);
CREATE INDEX idx_kinship_criteria        ON patient_kinship_history(criteria_name);
CREATE INDEX idx_kinship_meets_threshold ON patient_kinship_history(meets_threshold);

CREATE TABLE kinship_history_annotations (
    disease_name    VARCHAR NOT NULL,
    criteria_name   VARCHAR NOT NULL,                       -- e.g. 'Amsterdam II'
    description     VARCHAR,                                -- what the criteria checks for
    source          VARCHAR,                                -- guideline source e.g. NCCN
    created_date    DATE,
    last_updated    DATE,
    PRIMARY KEY (disease_name, criteria_name)
);