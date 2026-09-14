"""Patient existence lookup.

The only repository that answers a question about a patient rather than
about their clinical data, and the only one with no corresponding
specialist tool — nothing in the agent layer should ever ask "does this
patient exist?", because the answer is an access-control fact, not a
clinical one.

Why it exists
-------------

``POST /threads`` had no existence check. The code said so::

    # Existence check would go here once a patient repository is wired.
    # For now the allowlist doubles as the existence check

That reasoning holds for an ordinary clinician: an unlisted patient and
a non-existent one both 404, which is the enumeration defence B-005
asked for. It stops holding for an **admin**, because
``_Allowlist.can_read`` returns ``True`` before any per-patient check —
so for ``demo`` the allowlist stopped doubling as anything and the
existence check disappeared entirely.

On 2026-09-10 a customer typed ``HG0007`` for ``HG04007``, got a thread,
and the assistant answered with three fabricated variants. ``HG010`` and
``HG009`` reproduced it. This closes that door at the point of entry;
`3c7a854` closes the one behind it.
"""

from __future__ import annotations

from egp_maf.services.repositories.base import BaseRepository
from egp_maf.state.clinician_context import ClinicianContext

# ``patient_id`` is compared with ``=``, not ``ILIKE``, deliberately.
#
# 13406ec converted every *clinical* filter to ILIKE because those values
# arrive re-typed by an LLM. This one does not: it comes from the
# clinician's own keystrokes via the New-chat modal, and it is an opaque
# identifier. ``hg04007`` is not a sloppy spelling of ``HG04007`` — it is
# a different key, and matching it loosely here would let a mistyped id
# open a thread against a real patient, which is a worse failure than
# the one being fixed.
_SQL_EXISTS = """
    SELECT 1
    FROM patients
    WHERE patient_id = %s
    LIMIT 1
"""


class PatientRepository(BaseRepository):
    """Read-only existence check against the ``patients`` table."""

    async def exists(self, ctx: ClinicianContext, patient_id: str) -> bool:
        """Return whether ``patient_id`` is a real patient.

        Authorises first, for consistency with ADR-017 (RBAC at
        repository entry) — every other repository method does, and a
        method that reads the patient table without one would be the
        odd exception a future reader has to reason about.

        Raises :class:`~egp_maf.errors.DatabaseUnavailable` if the query
        cannot run. **Callers must not map that to "patient not found".**
        A database we cannot reach tells us nothing about whether the
        patient exists, and reporting it as absence is the same
        absence-of-evidence fault this whole line of work has been
        chasing.
        """
        self._authorize(ctx, patient_id)
        rows = await self._fetch_all(_SQL_EXISTS, [patient_id])
        return bool(rows)
