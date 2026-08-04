// AcrPull role assignment for the UAMI, scoped to the ACR resource.

@description('ACR name (in the current RG scope).')
param acrName string

@description('Principal id to grant AcrPull to.')
param principalId string

@description('AcrPull role definition id (GUID).')
param roleId string

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, principalId, roleId)
  scope: acr
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
  }
}
