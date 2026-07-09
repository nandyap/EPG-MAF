// Entra ID app registration for EGP Window — W07 F09.1.
//
// This template is a **provisioning artefact**, not deployed by the
// application itself. Publishing it under `infra/entra/` lets us treat
// the app registration as code: reviewers see any change to app roles,
// redirect URIs, or exposed scopes in a PR.
//
// The Microsoft.Graph resource provider ships app-registration types
// under the `Microsoft.Graph/*` namespace. The apiVersion pin below
// matches the current recommended GA/preview mix for these types.
//
// This template only manages the app registration itself + its app
// roles + the identifier URI. Client secret / federated credentials
// are managed manually in the portal so they don't leak into git.

targetScope = 'tenant'

@description('Display name for the EGP Window application in Entra.')
param appDisplayName string = 'EGP-Window'

@description('The identifier URI exposed by the app (must match ENTRA_EXPECTED_AUDIENCE).')
param identifierUri string = 'api://egp-window'

@description('Environment tag on the app roles (dev | preprod | prod). Purely cosmetic.')
param envSuffix string = 'prod'

// ── App registration ────────────────────────────────────────────────

resource egpApp 'Microsoft.Graph/applications@2024-01-01' = {
  uniqueName: 'egp-window-${envSuffix}'
  displayName: appDisplayName
  identifierUris: [ identifierUri ]
  signInAudience: 'AzureADMyOrg'
  api: {
    requestedAccessTokenVersion: 2
  }
  // ── App roles — mapped to ClinicianContext.roles at runtime ────
  appRoles: [
    {
      id: '11111111-1111-1111-1111-111111111111'
      allowedMemberTypes: [ 'User', 'Application' ]
      displayName: 'Clinician'
      description: 'Can invoke the /chat endpoint against patients on the allowlist.'
      value: 'Clinician'
      isEnabled: true
    }
    {
      id: '22222222-2222-2222-2222-222222222222'
      allowedMemberTypes: [ 'User', 'Application' ]
      displayName: 'Auditor'
      description: 'Read-only access to audit logs. Cannot invoke /chat.'
      value: 'Auditor'
      isEnabled: true
    }
    {
      id: '33333333-3333-3333-3333-333333333333'
      allowedMemberTypes: [ 'User' ]
      displayName: 'Admin'
      description: 'Bypasses the per-patient allowlist. Break-glass access only.'
      value: 'Admin'
      isEnabled: true
    }
  ]
}

// ── Outputs — consumed by the application deployment ────────────────

@description('The application id. Set as ENTRA_EXPECTED_AUDIENCE on the app when the identifier URI form is not used.')
output appId string = egpApp.appId

@description('The identifier URI. Set as ENTRA_EXPECTED_AUDIENCE on the app.')
output identifierUri string = identifierUri

@description('The tenant id. Set as ENTRA_TENANT_ID on the app.')
output tenantId string = tenant().tenantId
