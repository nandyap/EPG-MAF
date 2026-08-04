// Grants the UAMI the minimum RBAC it needs on existing landing-zone
// resources. Each assignment is scoped to its parent resource, so
// removing this module cleanly revokes all access.
//
// Data-plane roles (not RBAC):
//   - Postgres: an admin has to CREATE ROLE for the UAMI as an AAD
//     principal and grant DB privileges. That's handled by
//     ``scripts/postgres_bootstrap_aad.sql`` at deployment time, not
//     Bicep.
//   - Cosmos: SQL role assignment on the account (below) grants data
//     plane access.

@description('Principal id (object id) of the UAMI to grant roles to.')
param uamiPrincipalId string

@description('ACR name to grant AcrPull on.')
param acrName string

@description('Resource group of the ACR.')
param acrResourceGroup string

@description('Key Vault name to grant secret access on.')
param keyVaultName string

@description('Resource group of the Key Vault.')
param keyVaultResourceGroup string

@description('Cosmos account name to grant data-plane access on.')
param cosmosAccountName string

@description('Resource group of the Cosmos account.')
param cosmosResourceGroup string

// Built-in role IDs (well-known GUIDs).
var acrPullRoleId              = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var keyVaultSecretsUserRoleId  = '4633458b-17de-408a-b874-0445c86b69e6'
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002' // built-in SQL Data Contributor

// ── ACR pull ───────────────────────────────────────────────────────
module acrPull 'rbac-acrpull.bicep' = {
  scope: resourceGroup(acrResourceGroup)
  params: {
    acrName: acrName
    principalId: uamiPrincipalId
    roleId: acrPullRoleId
  }
}

// ── Key Vault secrets user ─────────────────────────────────────────
module kvUser 'rbac-kvsecrets.bicep' = {
  scope: resourceGroup(keyVaultResourceGroup)
  params: {
    keyVaultName: keyVaultName
    principalId: uamiPrincipalId
    roleId: keyVaultSecretsUserRoleId
  }
}

// ── Cosmos SQL data role assignment ────────────────────────────────
module cosmosRole 'rbac-cosmos.bicep' = {
  scope: resourceGroup(cosmosResourceGroup)
  params: {
    cosmosAccountName: cosmosAccountName
    principalId: uamiPrincipalId
    roleDefinitionId: cosmosDataContributorRoleId
  }
}
