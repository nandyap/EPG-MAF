# Entra ID app registration

W07 makes the EGP Window agent a first-class Entra ID application:
- Users obtain a JWT bearer token from Entra.
- The token is passed as `Authorization: Bearer <token>` on every
  request.
- APIM validates the signature at the edge; the application
  re-validates defensively via
  [`EntraTokenAuthenticator`](../../epg-maf/src/egp_maf/auth/authenticator.py)
  and maps the claims to a
  [`ClinicianContext`](../../epg-maf/src/egp_maf/state/clinician_context.py).

## App roles

Three app roles are exposed on the registration
([`infra/entra/app-registration.bicep`](../../infra/entra/app-registration.bicep)):

| Role | Assigned to | Effect at runtime |
|---|---|---|
| `Clinician` | Clinician users (via Entra group assignment) | Passes the `EGP_AUTH_REQUIRED_ROLE` check on `/chat`. Still subject to per-patient RBAC via the allowlist. |
| `Auditor` | Compliance / audit staff | Fails the `Clinician` role check on `/chat` (returns 403 `role_denied`). Read-only routes (planned W07+) accept `Auditor`. |
| `Admin` | Break-glass operators only | Passes the required-role check *and* bypasses the per-patient allowlist (see `AllowlistAuthzPolicy._Allowlist.is_admin`). Should be assigned to at most 2 users. |

## Runtime configuration

The application reads the following env vars at startup (defaults in
[`Settings`](../../epg-maf/src/egp_maf/config/settings.py)):

| Env var | Purpose | Example |
|---|---|---|
| `ENTRA_TENANT_ID` | Tenant GUID | `72f988bf-…` |
| `ENTRA_EXPECTED_AUDIENCE` | Must match the token's `aud` claim | `api://egp-window` |
| `ENTRA_EXPECTED_ISSUER` | Must match the token's `iss` claim | `https://sts.windows.net/72f988bf-.../` |
| `ENTRA_JWKS_URL` | Where to fetch the signing key | `https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys` |
| `ENTRA_LEEWAY_SECONDS` | Clock-skew tolerance for `nbf` / `exp` | `30` |
| `EGP_AUTH_REQUIRED_ROLE` | Role name required on `/chat` | `Clinician` |
| `EGP_AUTH_STUB_ENABLED` | **Dev only** — bypass signature | `false` in preprod/prod |

Any missing required var causes
[`build_authenticator`](../../epg-maf/src/egp_maf/auth/authenticator.py)
to raise `ConfigurationError` at startup (fail-closed).

## Provisioning steps

1. Deploy the Bicep template:

   ```powershell
   az deployment tenant create `
     --name "egp-window-app-reg" `
     --location "uaenorth" `
     --template-file infra/entra/app-registration.bicep `
     --parameters envSuffix=prod
   ```

2. Note the output `appId`, `identifierUri`, `tenantId`.
3. In the Entra portal, add app-role assignments for the pilot users
   (Group: `EGP-Window-Clinicians` → role `Clinician`; `EGP-Window-Admins`
   → role `Admin`).
4. Set the ACA container env vars:
   ```
   ENTRA_TENANT_ID              = <tenantId>
   ENTRA_EXPECTED_AUDIENCE      = <identifierUri>
   ENTRA_EXPECTED_ISSUER        = https://sts.windows.net/<tenantId>/
   ENTRA_JWKS_URL               = https://login.microsoftonline.com/<tenantId>/discovery/v2.0/keys
   EGP_AUTH_REQUIRED_ROLE       = Clinician
   EGP_AUTH_STUB_ENABLED        = false
   ```

## Audit trail

Every token-authn or authz outcome emits an
[`AuditEvent`](../../epg-maf/src/egp_maf/auth/audit.py) through the
shared `AuditEventEmitter` (routed to the `egp_maf.audit` logger). Event
names:

- `authz.granted` — clinician allowed to read `patient_id`.
- `authz.denied` — clinician not on the allowlist (or no allowlist).
- `auth.token_invalid` — token missing / expired / wrong signature / audience / issuer / mapping failed.
- `auth.role_denied` — token valid but missing required app role.

Every event carries `clinician_id`, `tenant_id`, `patient_id` (when
relevant), `reason`, and `trace_id` (populated by W08). Retention per
Design §21.

*Last updated: 2026-07-10.*
