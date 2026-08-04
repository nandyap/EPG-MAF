using '../main.bicep'

// ── PROD ────────────────────────────────────────────────────────────
// Manual approval required in the deploy pipeline.

param env = 'prod'
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

param backendMinReplicas  = 2
param backendMaxReplicas  = 10
param frontendMinReplicas = 2
param frontendMaxReplicas = 10
param authStubEnabled     = false
param orchDispatchMode    = 'sequential'
