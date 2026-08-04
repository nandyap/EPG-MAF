"""Provisional refusal templates for :class:`ScopeGuard` (Slice 3).

Templates are the wording the agent uses when it refuses a request.
Sources:

- Golden dataset (``docs/golden_dataset_prompts.pdf``) shape.
- B-004 product decision by Vijay (2026-07-17) with the caveat
  "provisional — pending clinical safety / M42 UX sign-off".

Scorers assert on the *invariant* substrings ("this chat is for patient",
"start a new chat", "isn't available in our reference annotations") so
we can adjust wording later without breaking eval.
"""

from __future__ import annotations


# Invariant substrings each template contains — used by golden-set
# scorers and the ``test_refusal_templates.py`` unit tests.
CROSS_PATIENT_INVARIANT = "this chat is for patient"
NEW_CHAT_INVARIANT = "start a new chat"
COHORT_SCAN_INVARIANT = "i can only report on patient"
NO_SCAN_INVARIANT = "can't scan across other patients"
ANNOTATION_MISSING_INVARIANT = "isn't available in our reference annotations"


def cross_patient_refusal(session_patient_id: str) -> str:
    """Golden items G1, G4 — the message names another patient."""
    return (
        f"This chat is for patient {session_patient_id}. "
        f"To ask about another patient, please start a new chat."
    )


def cohort_scan_refusal(session_patient_id: str) -> str:
    """Golden items G2, G3, G5, R23, R24 — cohort-scan of patient rows."""
    return (
        f"I can only report on patient {session_patient_id} — "
        f"I can't scan across other patients. Would you like me to "
        f"report {session_patient_id}'s own findings instead?"
    )


# Golden items G8, G9 — the request is annotation-legitimate cohort
# information but the annotation table does not have it. The agent
# must refuse rather than fall back to a patient scan. Static string
# because no interpolation is needed.
ANNOTATION_MISSING_REFUSAL = (
    "That information isn't available in our reference annotations. "
    "I won't fall back to scanning patient records to compute it."
)
