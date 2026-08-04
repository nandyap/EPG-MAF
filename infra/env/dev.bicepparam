using '../main.bicep'

// ── DEV ─────────────────────────────────────────────────────────────
// Placeholder values — replace {{...}} tokens from the B-008 intake.
// See ``docs/deployment.md``.

param env = 'dev'
param projectPrefix = 'egpmaf'
// Region defaults to resourceGroup().location; override if the RG is
// in a different region than the CAE.
// param location = 'uaenorth'

// Images built by ``azd package`` and pushed to ACR by ``azd deploy``.
// Tag placeholder — azd substitutes at deploy time.
param backendImage  = '{{ACR_LOGIN_SERVER}}/egp-maf-backend:{{TAG}}'
param frontendImage = '{{ACR_LOGIN_SERVER}}/egp-maf-frontend:{{TAG}}'

// Existing landing-zone resources (see B-008).
param containerAppsEnvironmentName = '{{CAE_NAME}}'
param containerRegistryName        = '{{ACR_NAME}}'
param containerRegistryResourceGroup = '{{ACR_RG}}'
param cosmosAccountName            = '{{COSMOS_ACCOUNT}}'
param cosmosResourceGroup          = '{{COSMOS_RG}}'
param keyVaultName                 = '{{KEYVAULT_NAME}}'
param keyVaultResourceGroup        = '{{KEYVAULT_RG}}'
param logAnalyticsWorkspaceId      = '{{LOG_ANALYTICS_WORKSPACE_ID}}'

// Backend runtime config.
param postgresHost       = '{{POSTGRES_FQDN}}'
param postgresDatabase   = 'egp'
param llmEndpoint        = '{{APIM_LLM_ENDPOINT}}'
param llmApiKeySecretName = 'llm-api-key'

// Dev-only sizing + flags.
param backendMinReplicas  = 1
param backendMaxReplicas  = 3
param frontendMinReplicas = 1
param frontendMaxReplicas = 3
param authStubEnabled     = true
param orchDispatchMode    = 'sequential'
