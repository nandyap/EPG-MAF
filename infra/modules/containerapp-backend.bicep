// Backend Container App. Ingress: internal-only (frontend is the only
// caller). Auth: UAMI attached, ACR pull via UAMI, secrets pulled from
// Key Vault via UAMI at container start.

@description('Container App name.')
param name string

@description('Azure region.')
param location string

param tags object = {}

@description('CAE resource id.')
param caeId string

@description('Fully-qualified image reference.')
param image string

@description('ACR login server, e.g. ``myacr.azurecr.io``.')
param acrLoginServer string

@description('UAMI resource id.')
param uamiId string

@description('UAMI client id — passed to the process as AZURE_CLIENT_ID for DefaultAzureCredential.')
param uamiClientId string

@minValue(0)
param minReplicas int = 1
@minValue(1)
param maxReplicas int = 5

@description('Postgres FQDN.')
param postgresHost string
param postgresDatabase string
param postgresUser string

@description('Cosmos account endpoint URL, e.g. ``https://myaccount.documents.azure.com:443/``.')
param cosmosEndpoint string
param cosmosDatabase string

@description('Per-document TTL for thread state, in seconds, or -1 to never expire. Refreshed on every save, so a finite value expires a thread that long after its LAST activity, not after creation. The container is provisioned with defaultTtl -1 (TTL enabled, per-item only), so this value is what actually expires threads. Set to -1 so the customer can review past conversations indefinitely — note that this makes Cosmos a growing store of clinical Q&A, which is a data-retention decision, not just a config value.')
param cosmosSessionTtlSeconds int = -1

@description('Key Vault URI, e.g. ``https://mykv.vault.azure.net/``. Retained for downstream code that reads other secrets from KV via UAMI; not used for the LLM key in this deploy.')
param keyVaultUri string
param llmEndpoint string

@secure()
@description('Compass API key. Injected directly as an app secret + LLM_API_KEY env var (Plan B — Container Apps KV secret reference via UAMI proved unreliable in this landing zone).')
param llmApiKey string

param authStubEnabled bool
param orchDispatchMode string
@description('If true, backend fails fast if Postgres pool cannot open at startup. Set false during rollout when the DB is not yet reachable.')
param postgresStartupRequired bool = true

@description('Log Analytics workspace id for diagnostic settings. Empty = skip.')
param logAnalyticsWorkspaceId string = ''

@description('JSON string for the authz allowlist. Mounted at /mnt/authz/allowlist.json and pointed to via EGP_AUTHZ_ALLOWLIST_PATH. Empty = no allowlist (fails closed).')
@secure()
param authzAllowlistJson string = ''

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uamiId}': {} }
  }
  properties: {
    environmentId: caeId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          identity: uamiId
        }
      ]
      secrets: [
        {
          name: 'llm-api-key'
          value: llmApiKey
        }
        {
          name: 'authz-allowlist'
          value: empty(authzAllowlistJson) ? '{"version":1,"clinicians":{},"admins":[]}' : authzAllowlistJson
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'backend'
          image: image
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'PORT', value: '8080' }
            { name: 'AZURE_CLIENT_ID', value: uamiClientId }
            { name: 'POSTGRES_HOST', value: postgresHost }
            { name: 'POSTGRES_DATABASE', value: postgresDatabase }
            { name: 'POSTGRES_USER', value: postgresUser }
            { name: 'POSTGRES_AUTH_MODE', value: 'aad' }
            { name: 'POSTGRES_USE_MANAGED_IDENTITY', value: 'true' }
            { name: 'POSTGRES_STARTUP_REQUIRED', value: string(postgresStartupRequired) }
            { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
            { name: 'COSMOS_DATABASE', value: cosmosDatabase }
            { name: 'COSMOS_CONTAINER', value: 'sessions' }
            { name: 'COSMOS_USE_MANAGED_IDENTITY', value: 'true' }
            { name: 'COSMOS_SESSION_TTL_SECONDS', value: string(cosmosSessionTtlSeconds) }
            { name: 'KEY_VAULT_URI', value: keyVaultUri }
            { name: 'LLM_ENDPOINT', value: llmEndpoint }
            { name: 'LLM_API_KEY', secretRef: 'llm-api-key' }
            { name: 'AUTH_STUB_ENABLED', value: string(authStubEnabled) }
            { name: 'ORCH_DISPATCH_MODE', value: orchDispatchMode }
            { name: 'EGP_AUTHZ_ALLOWLIST_PATH', value: '/mnt/authz/allowlist.json' }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/healthz', port: 8080 }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 30 // ~5 min for cold start (Cosmos + LLM warm-up)
            }
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8080 }
              initialDelaySeconds: 30
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: { path: '/healthz', port: 8080 }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 3
              failureThreshold: 3
            }
          ]
          volumeMounts: [
            {
              volumeName: 'authz'
              mountPath: '/mnt/authz'
            }
          ]
        }
      ]
      volumes: [
        {
          name: 'authz'
          storageType: 'Secret'
          secrets: [
            {
              secretRef: 'authz-allowlist'
              path: 'allowlist.json'
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http'
            http: { metadata: { concurrentRequests: '50' } }
          }
        ]
      }
    }
  }
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(logAnalyticsWorkspaceId)) {
  name: 'to-law'
  scope: app
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      { category: 'AllMetrics', enabled: true }
    ]
  }
}

output fqdn string = app.properties.configuration.ingress.fqdn
output internalUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
output name string = app.name
