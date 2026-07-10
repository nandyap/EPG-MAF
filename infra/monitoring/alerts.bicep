// W11 F13.3 — Alerts + Action Groups.
//
// Deploys the 9 alerts from Solution Design §22.2. Each alert points
// at the corresponding runbook via a documented link in the alert
// description; the shared Action Group routes to email + Teams
// webhook (contact list configured per-environment).

@description('Log Analytics workspace resource id backing App Insights.')
param logAnalyticsWorkspaceId string

@description('Application Insights resource id to query.')
param applicationInsightsId string

@description('Environment name — appended to alert names.')
@allowed(['dev', 'preprod', 'prod'])
param env string

@description('Email addresses for the shared Action Group.')
param actionGroupEmails array

@description('Teams webhook URL (secret; reference from Key Vault).')
@secure()
param teamsWebhookUrl string

// ── Action Group ──────────────────────────────────────────────────
resource ag 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-egp-${env}'
  location: 'global'
  properties: {
    groupShortName: 'egp-${env}'
    enabled: true
    emailReceivers: [for (e, i) in actionGroupEmails: {
      name: 'ops-${i}'
      emailAddress: e
      useCommonAlertSchema: true
    }]
    webhookReceivers: [
      {
        name: 'teams-ops'
        serviceUri: teamsWebhookUrl
        useCommonAlertSchema: true
      }
    ]
  }
}

// ── Reusable alert factory (metric-based) ─────────────────────────
var alerts = [
  {
    name: 'egp-turn-error-rate-high'
    severity: 1
    description: 'Turn error rate > 5% over 5m. Runbook: docs/runbooks/turn-errors.md'
    query: 'customMetrics | where name == "egp.turn.count" | summarize errors=sumif(value, tostring(customDimensions.outcome) == "error"), total=sum(value) by bin(timestamp, 5m) | extend rate=errors/total | where rate > 0.05'
    threshold: 0
    frequency: 'PT5M'
    window: 'PT5M'
  }
  {
    name: 'egp-turn-p95-latency-high'
    severity: 2
    description: 'Turn p95 latency > 15 s. Runbook: docs/runbooks/turn-latency.md'
    query: 'customMetrics | where name == "egp.turn.duration_ms" | summarize p95=percentile(value, 95) by bin(timestamp, 5m) | where p95 > 15000'
    threshold: 0
    frequency: 'PT5M'
    window: 'PT5M'
  }
  {
    name: 'egp-specialist-failure-spike'
    severity: 2
    description: 'egp.specialist.failed > 10/min. Runbook: docs/runbooks/specialist-failures.md'
    query: 'customMetrics | where name == "egp.specialist.failed" | summarize failures=sum(value) by bin(timestamp, 1m) | where failures > 10'
    threshold: 0
    frequency: 'PT5M'
    window: 'PT5M'
  }
  {
    name: 'egp-rate-limit-storm'
    severity: 2
    description: 'egp.rate_limit.hit > 20/min. Runbook: docs/runbooks/rate-limit.md'
    query: 'customMetrics | where name == "egp.rate_limit.hit" | summarize hits=sum(value) by bin(timestamp, 1m) | where hits > 20'
    threshold: 0
    frequency: 'PT5M'
    window: 'PT5M'
  }
  {
    name: 'egp-db-unavailable'
    severity: 1
    description: 'database_unavailable > 5/min. Runbook: docs/runbooks/db-unavailable.md'
    query: 'traces | where customDimensions["error.code"] == "database_unavailable" | summarize c=count() by bin(timestamp, 1m) | where c > 5'
    threshold: 0
    frequency: 'PT5M'
    window: 'PT5M'
  }
  {
    name: 'egp-cosmos-unavailable'
    severity: 1
    description: 'cosmos_unavailable > 3/min. Runbook: docs/runbooks/cosmos-unavailable.md'
    query: 'traces | where customDimensions["error.code"] == "cosmos_unavailable" | summarize c=count() by bin(timestamp, 1m) | where c > 3'
    threshold: 0
    frequency: 'PT5M'
    window: 'PT5M'
  }
  {
    name: 'egp-prompt-fallback-nonzero'
    severity: 3
    description: 'egp.prompt.fallback > 0 in the last hour. Runbook: docs/runbooks/foundry-outage.md'
    query: 'customMetrics | where name == "egp.prompt.fallback" | summarize c=sum(value) | where c > 0'
    threshold: 0
    frequency: 'PT15M'
    window: 'PT1H'
  }
  {
    name: 'egp-recursion-budget-exceeded'
    severity: 2
    description: 'routing_budget_exceeded > 3/hour. Runbook: docs/runbooks/routing-budget.md'
    query: 'traces | where customDimensions["error.code"] == "routing_budget_exceeded" | summarize c=count() | where c > 3'
    threshold: 0
    frequency: 'PT15M'
    window: 'PT1H'
  }
  {
    name: 'egp-db-pool-saturation'
    severity: 2
    description: 'egp.db.pool.utilisation > 0.9 for 10m. Runbook: docs/runbooks/db-pool.md'
    query: 'customMetrics | where name == "egp.db.pool.utilisation" | summarize avg_util=avg(value) by bin(timestamp, 5m) | where avg_util > 0.9'
    threshold: 0
    frequency: 'PT5M'
    window: 'PT10M'
  }
]

resource logAlerts 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = [for a in alerts: {
  name: '${a.name}-${env}'
  location: resourceGroup().location
  properties: {
    displayName: a.name
    description: a.description
    severity: a.severity
    enabled: true
    scopes: [applicationInsightsId]
    evaluationFrequency: a.frequency
    windowSize: a.window
    criteria: {
      allOf: [
        {
          query: a.query
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: a.threshold
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: [ag.id]
    }
  }
}]

output actionGroupId string = ag.id
