using '../main.bicep'

// ── PREPROD ─────────────────────────────────────────────────────────
// Same shape as dev.bicepparam but with production-adjacent sizing
// and stub auth OFF.

param env = 'preprod'
param projectPrefix = 'egpmaf'

param backendImage  = '{{ACR_LOGIN_SERVER}}/egp-maf-backend:{{TAG}}'
param frontendImage = '{{ACR_LOGIN_SERVER}}/egp-maf-frontend:{{TAG}}'

param containerAppsEnvironmentName = '{{CAE_NAME}}'
param containerRegistryName        = '{{ACR_NAME}}'
param containerRegistryResourceGroup = '{{ACR_RG}}'
param cosmosAccountName            = '{{COSMOS_ACCOUNT}}'
param cosmosResourceGroup          = '{{COSMOS_RG}}'
param keyVaultName                 = '{{KEYVAULT_NAME}}'
param keyVaultResourceGroup        = '{{KEYVAULT_RG}}'
param logAnalyticsWorkspaceId      = '{{LOG_ANALYTICS_WORKSPACE_ID}}'

param postgresHost        = '{{POSTGRES_FQDN}}'
param postgresDatabase    = 'egp'
param llmEndpoint         = '{{APIM_LLM_ENDPOINT}}'
param llmApiKeySecretName = 'llm-api-key'

param backendMinReplicas  = 1
param backendMaxReplicas  = 5
param frontendMinReplicas = 1
param frontendMaxReplicas = 5
param authStubEnabled     = false
param orchDispatchMode    = 'sequential'
