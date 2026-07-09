# Patient-scope allowlist (Phase 1 RBAC)

Design ADR-017 places the per-patient authorisation check at the
Repository entry — the "last mile" before the SQL. In Phase 1 the
policy is a JSON allowlist file mounted into the ACA container from
Key Vault (dev uses a plain file). Phase 3 replaces the file with a
policy engine (Discovery §R-09).

## Schema

Loaded by
[`AllowlistAuthzPolicy`](../../epg-maf/src/egp_maf/services/authz.py).

```json
{
    "version": 1,
    "clinicians": {
        "<clinician_oid>": ["<patient_id>", "<patient_id>", ...],
        ...
    },
    "admins": ["<clinician_oid>", ...]
}
```

- `version` — must equal `1`. Unknown versions raise
  `ConfigurationError` at load time.
- `clinicians[oid]` — the set of `patient_id`s that clinician `oid` is
  authorised to read. Empty list = no patients (but caller still needs
  the `Clinician` app role — see [entra.md](entra.md)).
- `admins` — bypass the per-patient check. Break-glass only. Members
  must additionally hold the `Admin` app role in Entra.

The clinician oid is the Entra object id (`oid` claim on the token),
mapped to `ClinicianContext.clinician_id` by
[`claims_to_context`](../../epg-maf/src/egp_maf/auth/claims.py).

## Lifecycle

- **First read** — the policy loads and parses the allowlist file
  eagerly at construction (fails startup on missing / malformed file).
- **Subsequent reads** — mtime is checked on every call; a changed
  file is re-parsed transparently. **Prod-mount** the Key Vault secret
  with `identity.rotationPolicy` so a rotated allowlist rolls out
  without a container restart.
- **Missing file at runtime** — raises `ConfigurationError` (the
  original file was found at construction; if it disappears we
  fail-closed on the next call rather than allowing).
- **No allowlist configured (`EGP_AUTHZ_ALLOWLIST_PATH` unset)** —
  policy denies **everyone** except `ClinicianContext.system()`. The
  fail-closed default means an ACA misconfiguration cannot silently
  open the app up.

## Config

| Env var | Default | Where |
|---|---|---|
| `EGP_AUTHZ_ALLOWLIST_PATH` | unset (deny-all) | ACA mount path in prod; local file path in dev |

## Audit

Every `enforce_read` call emits an `authz.granted` or `authz.denied`
audit event (via
[`AuditEventEmitter`](../../epg-maf/src/egp_maf/auth/audit.py)) with
the fields the compliance team needs to reconstruct access:
`clinician_id`, `tenant_id`, `patient_id`, `route`, `reason`,
`trace_id`.

`authz.denied` events also produce a `logger.warning('authz.denied')`
record on the main app logger, so they're visible in the standard
service log stream in addition to the dedicated audit route. The
denial message never contains the failed reason in the exception body
(`AccessDenied.message` is a stable "not authorised" string) — PHI-safe
by construction.

## Test matrix (F09.3 acceptance)

- ✅ Clinician **on** allowlist for `P1` → `authz.granted` audit event.
- ✅ Clinician **not on** allowlist for `P1` → `AccessDenied` +
  `authz.denied` audit event.
- ✅ Unknown clinician → `AccessDenied` + `authz.denied`.
- ✅ Unknown patient (clinician has an empty allowlist entry) →
  `AccessDenied` + `authz.denied`.
- ✅ `Admin`-role clinician bypasses per-patient check.
- ✅ System context (`ClinicianContext.system()`) bypasses every check.
- ✅ Fail-closed: no allowlist file + non-system clinician → deny.

Covered by
[`tests/unit/auth/test_end_to_end.py`](../../epg-maf/tests/unit/auth/test_end_to_end.py)
+ the W02
[`tests/unit/test_authz.py`](../../epg-maf/tests/unit/test_authz.py).

## Phase 3 migration path

The allowlist policy implements the
[`AuthzPolicy`](../../epg-maf/src/egp_maf/services/authz.py) protocol —
Phase 3 will drop in a replacement policy backed by a proper attribute-
or graph-based engine without changing any Repository code.

*Last updated: 2026-07-10.*
