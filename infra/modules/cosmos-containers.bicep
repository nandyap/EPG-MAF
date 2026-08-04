// Cosmos database + ``sessions`` container, created on the existing
// Cosmos account. Partition key ``/patient_id`` matches
// ``SessionDocument.patient_id`` and is required by the query patterns
// in ``egp_maf.services.thread_state``.

@description('Cosmos account name (in the current RG scope).')
param cosmosAccountName string

@description('Database name.')
param databaseName string

@description('Container throughput RUs. Autoscale ceiling.')
@minValue(1000)
param maxThroughput int = 4000

@description('Container TTL default in seconds. -1 = no expiry.')
param defaultTtlSeconds int = -1

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosAccountName
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: { id: databaseName }
    options: { autoscaleSettings: { maxThroughput: maxThroughput } }
  }
}

resource sessions 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: database
  name: 'sessions'
  properties: {
    resource: {
      id: 'sessions'
      partitionKey: {
        paths: [ '/patient_id' ]
        kind: 'Hash'
        version: 2
      }
      defaultTtl: defaultTtlSeconds
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [ { path: '/*' } ]
        excludedPaths: [ { path: '/"_etag"/?' } ]
      }
    }
  }
}

output databaseName string = database.name
output sessionsContainerName string = sessions.name
