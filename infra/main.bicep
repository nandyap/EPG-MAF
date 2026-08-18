// EGP Window — main deployment template.
//
// Pattern: **deploy INTO an existing landing zone**. We create only:
//   - user-assigned managed identity (UAMI)
//   - two Container Apps (backend + frontend)
//   - Cosmos database + container (`sessions`)
//   - RBAC on existing resources (ACR pull, Cosmos data contributor,
//     Key Vault secrets user, Postgres AAD admin role)
//
// Everything else (CAE, ACR, Postgres Flexible Server, Cosmos account,
// Key Vault, Log Analytics, VNet + subnets + private DNS) is assumed
// to already exist and is looked up via ``existing`` references. See
// ``docs/deployment.md`` and ``docs/blockers.md`` (B-008) for the
// intake checklist.

targetScope = 'resourceGroup'

@description('Environment tag: dev | preprod | prod.')
@allowed([ 'dev', 'preprod', 'prod' ])
param env string

@description('Azure region for the resources this template creates. Must match the region of the existing CAE.')
param location string = resourceGroup().location

@description('Short project prefix used to name every created resource. Kept ≤ 8 chars so downstream names fit within Azure name limits.')
@minLength(3)
@maxLength(8)
param projectPrefix string = 'egpmaf'

@description('Fully-qualified image reference for the backend, e.g. ``myacr.azurecr.io/egp-maf-backend:0.1.0``.')
param backendImage string

@description('Fully-qualified image reference for the frontend.')
param frontendImage string

// ── Existing landing-zone resources ─────────────────────────────────
@description('Name of the existing Container Apps Environment.')
param containerAppsEnvironmentName string

@description('Name of the existing Azure Container Registry.')
param containerRegistryName string

@description('Resource group containing the existing ACR. Defaults to the deployment RG.')
param containerRegistryResourceGroup string = resourceGroup().name

@description('Name of the existing Cosmos DB (NoSQL) account.')
param cosmosAccountName string

@description('Resource group containing the Cosmos account. Defaults to the deployment RG.')
param cosmosResourceGroup string = resourceGroup().name

@description('Name of the existing Key Vault.')
param keyVaultName string

@description('Resource group containing the Key Vault. Defaults to the deployment RG.')
param keyVaultResourceGroup string = resourceGroup().name

@description('Log Analytics workspace ID (customer/tenant id) for diagnostic settings. Optional.')
param logAnalyticsWorkspaceId string = ''

// ── Backend configuration ───────────────────────────────────────────
@description('Postgres FQDN for the clinical DB. e.g. ``egp-pg-prod.postgres.database.azure.com``.')
param postgresHost string

@description('Postgres database name.')
param postgresDatabase string = 'egp'

@description('Postgres AAD login. Defaults to the UAMI display name (must match the Postgres role granted SELECT — see docs/deployment.md).')
param postgresAadLogin string = '${projectPrefix}-${env}-uami'

@description('Cosmos database name for session/thread state.')
param cosmosDatabase string = 'egp'

@description('Compass / APIM endpoint URL for LLM access.')
param llmEndpoint string

@secure()
@description('Compass API key. Passed to the backend Container App as an app secret + LLM_API_KEY env var. Read from the AZURE_LLM_API_KEY env var by main.bicepparam.')
param llmApiKey string

// ── Sizing ─────────────────────────────────────────────────────────
@description('Minimum backend replicas.')
@minValue(0)
param backendMinReplicas int = 1

@description('Maximum backend replicas.')
@minValue(1)
param backendMaxReplicas int = 5

@description('Minimum frontend replicas.')
@minValue(0)
param frontendMinReplicas int = 1

@description('Maximum frontend replicas.')
@minValue(1)
param frontendMaxReplicas int = 5

// ── Feature flags ──────────────────────────────────────────────────
@description('Enable the ``StubAuthenticator`` bearer parser (dev only).')
param authStubEnabled bool = false

@description('``sequential`` (safe) or ``parallel`` fan-out for orchestrator dispatch.')
@allowed([ 'sequential', 'parallel' ])
param orchDispatchMode string = 'sequential'

@description('If true, backend fails fast when Postgres pool cannot open at startup. Set false during rollout when the DB is not yet reachable in the VNet.')
param postgresStartupRequired bool = true

@description('JSON string for the authz allowlist. Mounted at /mnt/authz/allowlist.json inside the backend container. Empty = deny-all (fail closed).')
@secure()
param authzAllowlistJson string = ''

// ── Derived names ──────────────────────────────────────────────────
var uamiName        = '${projectPrefix}-${env}-uami'
var backendAppName  = '${projectPrefix}-${env}-backend'
var frontendAppName = '${projectPrefix}-${env}-frontend'

// ── Existing resources ─────────────────────────────────────────────
resource cae 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: containerAppsEnvironmentName
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: containerRegistryName
  scope: resourceGroup(containerRegistryResourceGroup)
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosAccountName
  scope: resourceGroup(cosmosResourceGroup)
}

resource kv 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultName
  scope: resourceGroup(keyVaultResourceGroup)
}

// ── Modules ────────────────────────────────────────────────────────
module identity 'modules/identity.bicep' = {
  params: {
    name: uamiName
    location: location
    tags: { env: env, project: projectPrefix }
  }
}

module cosmosContainers 'modules/cosmos-containers.bicep' = {
  scope: resourceGroup(cosmosResourceGroup)
  params: {
    cosmosAccountName: cosmosAccountName
    databaseName: cosmosDatabase
  }
}

module rbac 'modules/rbac.bicep' = {
  params: {
    uamiPrincipalId: identity.outputs.principalId
    acrName: containerRegistryName
    acrResourceGroup: containerRegistryResourceGroup
    keyVaultName: keyVaultName
    keyVaultResourceGroup: keyVaultResourceGroup
    cosmosAccountName: cosmosAccountName
    cosmosResourceGroup: cosmosResourceGroup
  }
}

module backend 'modules/containerapp-backend.bicep' = {
  params: {
    name: backendAppName
    location: location
    tags: { env: env, project: projectPrefix, role: 'backend' }
    caeId: cae.id
    image: backendImage
    acrLoginServer: acr.properties.loginServer
    uamiId: identity.outputs.id
    uamiClientId: identity.outputs.clientId
    minReplicas: backendMinReplicas
    maxReplicas: backendMaxReplicas
    postgresHost: postgresHost
    postgresDatabase: postgresDatabase
    postgresUser: postgresAadLogin
    cosmosEndpoint: cosmos.properties.documentEndpoint
    cosmosDatabase: cosmosDatabase
    keyVaultUri: kv.properties.vaultUri
    llmApiKey: llmApiKey
    llmEndpoint: llmEndpoint
    authStubEnabled: authStubEnabled
    orchDispatchMode: orchDispatchMode
    postgresStartupRequired: postgresStartupRequired
    logAnalyticsWorkspaceId: logAnalyticsWorkspaceId
    authzAllowlistJson: authzAllowlistJson
  }
  dependsOn: [ rbac, cosmosContainers ]
}

module frontend 'modules/containerapp-frontend.bicep' = {
  params: {
    name: frontendAppName
    location: location
    tags: { env: env, project: projectPrefix, role: 'frontend' }
    caeId: cae.id
    image: frontendImage
    acrLoginServer: acr.properties.loginServer
    uamiId: identity.outputs.id
    minReplicas: frontendMinReplicas
    maxReplicas: frontendMaxReplicas
    backendUrl: backend.outputs.internalUrl
    logAnalyticsWorkspaceId: logAnalyticsWorkspaceId
  }
  dependsOn: [ rbac ]
}

// ── Outputs ────────────────────────────────────────────────────────
output backendFqdn string = backend.outputs.fqdn
output frontendFqdn string = frontend.outputs.fqdn
output uamiPrincipalId string = identity.outputs.principalId
output uamiClientId string = identity.outputs.clientId
output postgresAadLogin string = postgresAadLogin
