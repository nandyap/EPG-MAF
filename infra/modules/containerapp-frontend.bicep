// Frontend Container App (Next.js standalone). Ingress: external.
// Container Apps Easy Auth is enabled OUT OF BAND (portal / az cli) —
// Bicep for authConfigs still varies by API version and is safer to
// wire post-deploy per environment.

@description('Container App name.')
param name string
param location string
param tags object = {}

@description('CAE resource id.')
param caeId string

@description('Fully-qualified frontend image reference.')
param image string

@description('ACR login server.')
param acrLoginServer string

@description('UAMI resource id (used for ACR pull).')
param uamiId string

@minValue(0)
param minReplicas int = 1
@minValue(1)
param maxReplicas int = 5

@description('Internal URL of the backend Container App, e.g. ``https://egpmaf-prod-backend.internal.<caedomain>``.')
param backendUrl string

@description('Log Analytics workspace id. Empty = skip.')
param logAnalyticsWorkspaceId string = ''

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
        external: true
        targetPort: 3000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          identity: uamiId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'frontend'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'PORT', value: '3000' }
            { name: 'HOSTNAME', value: '0.0.0.0' }
            { name: 'NODE_ENV', value: 'production' }
            { name: 'BACKEND_URL', value: backendUrl }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/', port: 3000 }
              initialDelaySeconds: 10
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
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
            http: { metadata: { concurrentRequests: '100' } }
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
    logs: [ { categoryGroup: 'allLogs', enabled: true } ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

output fqdn string = app.properties.configuration.ingress.fqdn
output name string = app.name
