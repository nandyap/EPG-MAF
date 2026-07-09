"""
Controlled vocabularies for fields the system owns.
Only include values WE define — not values sourced from external
data or tools whose vocabulary may evolve.
"""

# Agent lifecycle — we own this completely
AGENT_STATUSES = {"pending", "running", "complete", "failed", "partial"}

# Risk bands — we define this interpretation layer
RISK_BANDS = {"low", "average", "high", "very_high"}

# These we DON'T define here because the data owns them:
# - pathogenicity       → ClinVar's vocabulary, may expand
# - variant_type        → pipeline/caller dependent
# - acmg_classification → ACMG may update criteria
# - sequencing_platform → new platforms emerge constantly