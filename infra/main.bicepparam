using 'main.bicep'

// Deploys the EGP MAF backend + frontend Container Apps into the
// dev landing-zone RG ``rg-ailz-egpwin-dev-m42-aen-001``.
//
// Every existing resource referenced below lives in the same RG.
// Postgres is the exception — it sits in a separate RG under the
// same subscription and is reached via VNet private endpoint. Bicep
// doesn't touch it; the backend connects to it at runtime using the
// UAMI's AAD token.
//
// See ``docs/deployment.md`` for the full runbook.

param env = 'dev'
param projectPrefix = 'egpmaf'
// Region defaults to resourceGroup().location; the RG is in uaenorth.

// Images built + pushed by ``azd deploy``. Tag substituted at deploy time.
param backendImage  = 'crailzegpwindevm42aen001.azurecr.io/egp-maf-backend:{{TAG}}'
param frontendImage = 'crailzegpwindevm42aen001.azurecr.io/egp-maf-frontend:{{TAG}}'

// Existing landing-zone resources (all in the same dev RG).
param containerAppsEnvironmentName   = 'cae-ailz-egpwin-dev-m42-aen-001'
param containerRegistryName          = 'crailzegpwindevm42aen001'
param containerRegistryResourceGroup = 'rg-ailz-egpwin-dev-m42-aen-001'
param cosmosAccountName              = 'cosmos-ailz-egpwin-dev-m42-aen-001'
param cosmosResourceGroup            = 'rg-ailz-egpwin-dev-m42-aen-001'
param keyVaultName                   = 'kvailzegpwindevm42aen001'
param keyVaultResourceGroup          = 'rg-ailz-egpwin-dev-m42-aen-001'
// Log Analytics: not wired yet. Bicep skips diagnostic settings when empty.
param logAnalyticsWorkspaceId        = ''

// Backend runtime config.
param postgresHost        = 'psql-egpwin-agent-prd-m42-aen.postgres.database.azure.com'
param postgresDatabase    = 'egp_window'
param llmEndpoint         = 'https://api.core42.ai/v1'  // Compass / Core42 API base URL
param llmApiKeySecretName = 'llm-api-key'            // KV secret name (value seeded out of band)

// Sizing.
param backendMinReplicas  = 1
param backendMaxReplicas  = 3
param frontendMinReplicas = 1
param frontendMaxReplicas = 3

// Feature flags — dev.
param authStubEnabled  = true
param orchDispatchMode = 'sequential'
// DB is not yet reachable in the landing-zone VNet (migration to
// psql-ailz-egpwin-dev-m42-aen-001 pending). Let the backend boot so
// pure-LLM chat + scope-guard refusals work; specialist queries will
// surface DatabaseUnavailable at request time until this flips to true.
param postgresStartupRequired = false
