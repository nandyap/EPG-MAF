// User-assigned managed identity used by both container apps.
// Attached to the backend for Postgres (AAD) + Cosmos + Key Vault +
// ACR pull, and to the frontend for ACR pull only.

@description('Name of the user-assigned managed identity.')
param name string

@description('Azure region.')
param location string

@description('Tags applied to the UAMI.')
param tags object = {}

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
  tags: tags
}

output id string = uami.id
output principalId string = uami.properties.principalId
output clientId string = uami.properties.clientId
output name string = uami.name
