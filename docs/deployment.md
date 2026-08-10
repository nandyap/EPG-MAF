# EGP Window — Deployment Runbook

Deploys the backend + frontend Container Apps **INTO an existing
Azure landing zone**. The Bicep template does NOT create the CAE, ACR,
Postgres server, Cosmos account, Key Vault, or Log Analytics workspace
— those are assumed to already exist and are looked up via ``existing``
references.

Related docs:

- [`../infra/main.bicep`](../infra/main.bicep) — entry template.
- [`blockers.md#B-008`](blockers.md) — landing-zone intake (must be
  complete before first deploy).

## 1. Prerequisites

Tools:

- [`azd`](https://aka.ms/azd) v1.10+
- Bicep CLI 0.30+ (bundled with recent Azure CLI)
- Docker Desktop (or any Docker CLI) for local build
- Access rights on the target subscription:
  - Contributor on the deployment resource group.
  - User Access Administrator on the ACR, Cosmos, and Key Vault (for
    the RBAC assignments the template creates).
  - Postgres AAD admin (to CREATE ROLE for the UAMI post-deploy).

Landing-zone intake (from B-008):

| Placeholder                    | Meaning                                    |
| ------------------------------ | ------------------------------------------ |
| `{{CAE_NAME}}`                 | Container Apps Environment name            |
| `{{ACR_NAME}}` / `{{ACR_RG}}`  | Container registry name + RG               |
| `{{COSMOS_ACCOUNT}}` / `{{COSMOS_RG}}` | Cosmos account + RG                |
| `{{KEYVAULT_NAME}}` / `{{KEYVAULT_RG}}`| Key Vault + RG                     |
| `{{POSTGRES_FQDN}}`            | e.g. `egp-pg-prod.postgres.database.azure.com` |
| `{{APIM_LLM_ENDPOINT}}`        | APIM URL fronting Compass                  |
| `{{LOG_ANALYTICS_WORKSPACE_ID}}` | Optional — enables diagnostic settings   |
| `{{ACR_LOGIN_SERVER}}`         | e.g. `myacr.azurecr.io`                    |
| `{{TAG}}`                      | Image tag — usually the git SHA            |

Populate them in the appropriate file:

- [`../infra/env/dev.bicepparam`](../infra/env/dev.bicepparam)
- [`../infra/env/preprod.bicepparam`](../infra/env/preprod.bicepparam)
- [`../infra/env/prod.bicepparam`](../infra/env/prod.bicepparam)

## 2. Prerequisite: Key Vault secret

Before `azd up`, seed the LLM API key into Key Vault:

```powershell
az keyvault secret set `
  --vault-name {{KEYVAULT_NAME}} `
  --name llm-api-key `
  --value "<COMPASS_API_KEY>"
```

## 3. First deployment (per environment)

```powershell
# Create the azd environment.
azd env new egpmaf-dev
azd env set AZURE_LOCATION uaenorth
azd env set AZURE_RESOURCE_GROUP {{DEPLOYMENT_RG_NAME}}
azd env set AZURE_SUBSCRIPTION_ID {{SUBSCRIPTION_ID}}

# Log in.
azd auth login

# Build images, push to ACR, run Bicep, run post-provision hook.
azd up
```

`azd up` performs, in order:

1. `docker build` for both services (contexts:
   [`../epg-maf`](../epg-maf) and
   [`../epg-maf/egp_frontend`](../epg-maf/egp_frontend)).
2. Pushes images to ACR with tag `azd-deploy-<timestamp>`.
3. Runs `bicep build` and deploys the resource group.
4. Runs [`../scripts/deploy_postprovision.ps1`](../scripts/deploy_postprovision.ps1)
   — smokes `/health`.

## 4. Post-provision — Postgres AAD role

Bicep can't `CREATE ROLE` in Postgres. Run this **once per environment**
after the first `azd up`, from the **jump VM inside the VNet** (the
Postgres server is behind a private endpoint and unreachable from
outside), connected as a Postgres AAD admin.

The backend is **read-only** on the clinical DB — writes go to Cosmos,
not Postgres. So we grant `SELECT` only.

```sql
-- Role name matches the UAMI Bicep creates:
--   projectPrefix-env-uami  ->  egpmaf-dev-uami
CREATE ROLE "egpmaf-dev-uami" WITH LOGIN IN ROLE azure_ad_user;
GRANT CONNECT ON DATABASE egp_window TO "egpmaf-dev-uami";
GRANT USAGE ON SCHEMA public TO "egpmaf-dev-uami";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO "egpmaf-dev-uami";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO "egpmaf-dev-uami";
```

The first `azd up` will crash-loop the backend Container App with
`FATAL: role "egpmaf-dev-uami" does not exist` — that's expected.
After running the SQL above, restart the revision:

```powershell
az containerapp revision restart `
  --name egpmaf-dev-backend `
  --resource-group rg-ailz-egpwin-dev-m42-aen-001 `
  --revision $(az containerapp show `
    --name egpmaf-dev-backend `
    --resource-group rg-ailz-egpwin-dev-m42-aen-001 `
    --query "properties.latestRevisionName" -o tsv)
```

## 5. Enable Container Apps Easy Auth (frontend)

Easy Auth for the frontend is wired post-deploy so tenant details stay
out of Bicep:

```powershell
az containerapp auth microsoft update `
  --name egpmaf-dev-frontend `
  --resource-group {{DEPLOYMENT_RG_NAME}} `
  --client-id {{ENTRA_APP_CLIENT_ID}} `
  --tenant-id {{ENTRA_TENANT_ID}} `
  --yes
az containerapp auth update `
  --name egpmaf-dev-frontend `
  --resource-group {{DEPLOYMENT_RG_NAME}} `
  --unauthenticated-client-action RedirectToLoginPage `
  --redirect-provider AzureActiveDirectory
```

Verify with a browser: an unauthenticated request should redirect to
`login.microsoftonline.com`. Once signed in, the frontend forwards
`X-MS-CLIENT-PRINCIPAL-*` headers to the backend via the internal-only
Container Apps ingress.

## 6. Subsequent deploys

```powershell
azd deploy backend    # backend only
azd deploy frontend   # frontend only
azd deploy            # both
```

## 7. Verification checklist

- [ ] `/health` returns 200 on the backend internal FQDN
      (`az containerapp exec` from a peer container to reach it).
- [ ] Frontend home page loads via the external FQDN and redirects to
      Easy Auth on first visit.
- [ ] After sign-in, `/api/me` returns `authenticated=true` with the
      clinician's OID.
- [ ] Create a chat for a known-good patient (e.g. `PGP001` from the
      allowlist) → completes.
- [ ] Refuse-path smoke: ask "compare to PGP002" → scope-guard refusal.
- [ ] Log Analytics receives Container Apps stdout logs.

## 8. Rollback

`azd` builds are tagged with a timestamp. To roll back the backend:

```powershell
az containerapp revision list --name egpmaf-prod-backend `
  --resource-group {{DEPLOYMENT_RG_NAME}} `
  --query "[].{name:name, image:template.containers[0].image, active:properties.active}"

az containerapp revision activate `
  --name egpmaf-prod-backend `
  --resource-group {{DEPLOYMENT_RG_NAME}} `
  --revision {{PREVIOUS_REVISION_NAME}}
```

Container Apps keeps the last N revisions so single-command rollback is
always available.

## 9. Local docker build (no push)

```powershell
# Backend
cd epg-maf
docker build -t egp-maf-backend:local .

# Frontend
cd egp_frontend
docker build -t egp-maf-frontend:local .
```

These match what `azd deploy` builds — validate images run before
pushing.
