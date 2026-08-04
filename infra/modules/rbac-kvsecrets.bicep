// Key Vault Secrets User role for the UAMI, scoped to the vault.

@description('Key Vault name (in the current RG scope).')
param keyVaultName string

@description('Principal id.')
param principalId string

@description('Key Vault Secrets User role definition id (GUID).')
param roleId string

resource kv 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultName
}

resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, principalId, roleId)
  scope: kv
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
  }
}
