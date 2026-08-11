// Throwaway template used to seed the Compass API key into Key Vault
// when the KV data-plane FQDN is unreachable from the operator's
// network (corporate DNS resolves to the private endpoint the
// operator can't reach). Deploys through ARM, not the KV data plane.
//
// Usage — from a shell with `az login` and Contributor on the RG:
//
//   $env:COMPASS_KEY = Read-Host -AsSecureString "Compass key" | ConvertFrom-SecureString -AsPlainText
//   az deployment group create `
//     --resource-group rg-ailz-egpwin-dev-m42-aen-001 `
//     --template-file infra/tools/set-llm-secret.bicep `
//     --parameters keyVaultName=kvailzegpwindevm42aen001 `
//     --parameters secretValue="$env:COMPASS_KEY"
//   Remove-Item Env:COMPASS_KEY
//
// Nothing is persisted from this file — the secret is passed as a
// deployment parameter (deployments hide @secure() params in history).

targetScope = 'resourceGroup'

@description('Existing Key Vault name.')
param keyVaultName string

@description('Secret name — must match ``llmApiKeySecretName`` in dev.bicepparam.')
param secretName string = 'llm-api-key'

@secure()
@description('Compass API key. Provided at deploy time, not stored anywhere.')
param secretValue string

resource kv 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultName
}

resource secret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: kv
  name: secretName
  properties: {
    value: secretValue
    contentType: 'text/plain'
    attributes: { enabled: true }
  }
}

output secretUri string = secret.properties.secretUriWithVersion
