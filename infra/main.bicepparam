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

// Images built + pushed by ``azd`` during ``package`` phase. On each
// deploy azd exports the fully-qualified image reference (with the
// tag it generated) as ``SERVICE_<NAME>_IMAGE_NAME``, and Bicep reads
// it here. The second arg is a fallback only used when you run
// ``azd provision`` standalone before ever packaging — in that case
// Container Apps preflight will reject the tag, which is the correct
// signal to run ``azd up`` or ``azd package && azd provision``.
param backendImage  = readEnvironmentVariable('SERVICE_BACKEND_IMAGE_NAME', 'mcr.microsoft.com/k8se/quickstart:latest')
param frontendImage = readEnvironmentVariable('SERVICE_FRONTEND_IMAGE_NAME', 'mcr.microsoft.com/k8se/quickstart:latest')

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
// Customer moved egp_window onto the landing-zone Postgres server —
// same VNet as the CAE, so Container Apps reach it via the existing
// private endpoint (once the customer registers the DNS record in
// their hub for privatelink.postgres.database.azure.com).
param postgresHost        = 'psql-ailz-egpwin-dev-m42-aen-001.postgres.database.azure.com'
param postgresDatabase    = 'egp_window'
param llmEndpoint         = 'https://api.core42.ai/v1'  // Compass / Core42 API base URL
// Plan B — the KV secret reference via UAMI proved unreliable in this
// landing zone (see notes in modules/containerapp-backend.bicep). We
// pass the key straight from the operator's environment to Bicep as a
// @secure() param, and it lands as an app secret on the Container App.
// Set once locally:  $env:AZURE_LLM_API_KEY = "<key>"   before ``azd up``.
param llmApiKey           = readEnvironmentVariable('AZURE_LLM_API_KEY', '')

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
