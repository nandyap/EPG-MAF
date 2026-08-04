// Cosmos SQL data-plane role assignment for the UAMI. Cosmos uses its
// own SQL role model, not standard Azure RBAC, so this is a
// ``sqlRoleAssignments`` child resource on the account.

@description('Cosmos account name (in the current RG scope).')
param cosmosAccountName string

@description('Principal id to grant data-plane access to.')
param principalId string

@description('Cosmos SQL role definition id (built-in ``00000000-0000-0000-0000-000000000002`` for Data Contributor).')
param roleDefinitionId string

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosAccountName
}

resource assignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: account
  name: guid(account.id, principalId, roleDefinitionId)
  properties: {
    principalId: principalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/${roleDefinitionId}'
    scope: account.id
  }
}
