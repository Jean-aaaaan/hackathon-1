/**
 * Vantage — Azure Infrastructure
 * Deploys: ACR + Container Apps Environment + API Container App + Nightly Container Job
 *
 * Deploy command (run once from your Azure subscription):
 *   az group create --name rg-vantage-prod --location southeastasia
 *   az deployment group create \
 *     --resource-group rg-vantage-prod \
 *     --template-file infrastructure/azure/main.bicep \
 *     --parameters @infrastructure/azure/parameters.prod.json
 *
 * Subsequent deploys (CI/CD does this automatically):
 *   az containerapp update --name vantage-api --resource-group rg-vantage-prod \
 *     --image <acr-name>.azurecr.io/vantage-api:<tag>
 */

@description('Environment name (prod / staging)')
param environmentName string = 'prod'

@description('Azure region — southeastasia for Singapore')
param location string = 'southeastasia'

@description('Container image tag (set by CI/CD)')
param imageTag string = 'latest'

@description('Database connection string (from Azure Key Vault reference or secret)')
@secure()
param databaseUrl string

@description('Anthropic API key')
@secure()
param anthropicApiKey string

@description('WorkOS API key')
@secure()
param workosApiKey string

@description('WorkOS Client ID')
@secure()
param workosClientId string

@description('HubSpot OAuth client ID')
@secure()
param hubspotClientId string

@description('HubSpot OAuth client secret')
@secure()
param hubspotClientSecret string

@description('Perplexity API key')
@secure()
param perplexityApiKey string = ''

@description('VoyageAI API key for embeddings')
@secure()
param voyageApiKey string = ''

@description('Fireflies API key')
@secure()
param firefliesApiKey string = ''

@description('Microsoft Teams webhook URL for alerts')
@secure()
param teamsWebhookUrl string = ''

@description('Frontend URL (Vercel deployment)')
param frontendUrl string = 'https://app.vantage.ai'

@description('Sentry DSN for error tracking')
@secure()
param sentryDsn string = ''

// ── Derived names ─────────────────────────────────────────────────────────────

var resourcePrefix = 'vantage'
var acrName = '${resourcePrefix}acr${uniqueString(resourceGroup().id)}'
var appEnvName = '${resourcePrefix}-env-${environmentName}'
var apiAppName = '${resourcePrefix}-api'
var nightlyJobName = '${resourcePrefix}-nightly'
var logWorkspaceName = '${resourcePrefix}-logs-${environmentName}'

// ── Log Analytics Workspace ───────────────────────────────────────────────────

resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logWorkspaceName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ── Azure Container Registry ──────────────────────────────────────────────────

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }   // ~$5/month — upgrade to Standard when you need geo-replication
  properties: {
    adminUserEnabled: false  // Use managed identity (AcrPull role) — no admin credentials
  }
}

// AcrPull built-in role definition ID
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

// ── Container Apps Environment ────────────────────────────────────────────────

resource appEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: appEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
}

// ── API Container App ─────────────────────────────────────────────────────────

resource apiApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: apiAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: appEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: 'system'
        }
      ]
      secrets: [
        { name: 'database-url', value: databaseUrl }
        { name: 'anthropic-api-key', value: anthropicApiKey }
        { name: 'workos-api-key', value: workosApiKey }
        { name: 'hubspot-client-secret', value: hubspotClientSecret }
        { name: 'perplexity-api-key', value: perplexityApiKey }
        { name: 'voyage-api-key', value: voyageApiKey }
        { name: 'fireflies-api-key', value: firefliesApiKey }
        { name: 'teams-webhook-url', value: teamsWebhookUrl }
        { name: 'sentry-dsn', value: sentryDsn }
      ]
    }
    template: {
      containers: [
        {
          name: 'vantage-api'
          image: '${acr.properties.loginServer}/vantage-api:${imageTag}'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'ENVIRONMENT', value: environmentName }
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'ANTHROPIC_API_KEY', secretRef: 'anthropic-api-key' }
            { name: 'WORKOS_API_KEY', secretRef: 'workos-api-key' }
            { name: 'WORKOS_CLIENT_ID', value: workosClientId }
            { name: 'WORKOS_REDIRECT_URI', value: '${frontendUrl}/auth/callback' }
            { name: 'HUBSPOT_CLIENT_ID', value: hubspotClientId }
            { name: 'HUBSPOT_CLIENT_SECRET', secretRef: 'hubspot-client-secret' }
            { name: 'HUBSPOT_REDIRECT_URI', value: '${frontendUrl}/auth/hubspot/callback' }
            { name: 'PERPLEXITY_API_KEY', secretRef: 'perplexity-api-key' }
            { name: 'VOYAGE_API_KEY', secretRef: 'voyage-api-key' }
            { name: 'FIREFLIES_API_KEY', secretRef: 'fireflies-api-key' }
            { name: 'TEAMS_WEBHOOK_URL', secretRef: 'teams-webhook-url' }
            { name: 'FRONTEND_URL', value: frontendUrl }
            { name: 'SENTRY_DSN', secretRef: 'sentry-dsn' }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8000 }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'http-scaling'
            http: { metadata: { concurrentRequests: '20' } }
          }
        ]
      }
    }
  }
}

// ── AcrPull role assignments ──────────────────────────────────────────────────

resource apiAppAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, apiApp.id, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: apiApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Nightly Container Job ─────────────────────────────────────────────────────

resource nightlyJob 'Microsoft.App/jobs@2023-05-01' = {
  name: nightlyJobName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: appEnv.id
    configuration: {
      triggerType: 'Schedule'
      scheduleTriggerConfig: {
        cronExpression: '0 2 * * *'   // 02:00 UTC = 10:00 SGT
        parallelism: 1
        replicaCompletionCount: 1
      }
      replicaTimeout: 3600            // 1 hour max
      replicaRetryLimit: 1
      registries: [
        {
          server: acr.properties.loginServer
          identity: 'system'
        }
      ]
      secrets: [
        { name: 'database-url', value: databaseUrl }
        { name: 'anthropic-api-key', value: anthropicApiKey }
        { name: 'workos-api-key', value: workosApiKey }
        { name: 'perplexity-api-key', value: perplexityApiKey }
        { name: 'voyage-api-key', value: voyageApiKey }
        { name: 'fireflies-api-key', value: firefliesApiKey }
        { name: 'teams-webhook-url', value: teamsWebhookUrl }
        { name: 'sentry-dsn', value: sentryDsn }
      ]
    }
    template: {
      containers: [
        {
          name: 'vantage-nightly'
          image: '${acr.properties.loginServer}/vantage-api:${imageTag}'
          command: ['python', 'nightly_job.py']
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            { name: 'ENVIRONMENT', value: environmentName }
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'ANTHROPIC_API_KEY', secretRef: 'anthropic-api-key' }
            { name: 'WORKOS_API_KEY', secretRef: 'workos-api-key' }
            { name: 'PERPLEXITY_API_KEY', secretRef: 'perplexity-api-key' }
            { name: 'VOYAGE_API_KEY', secretRef: 'voyage-api-key' }
            { name: 'FIREFLIES_API_KEY', secretRef: 'fireflies-api-key' }
            { name: 'TEAMS_WEBHOOK_URL', secretRef: 'teams-webhook-url' }
            { name: 'SENTRY_DSN', secretRef: 'sentry-dsn' }
          ]
        }
      ]
    }
  }
}

resource nightlyJobAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, nightlyJob.id, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: nightlyJob.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────────

output acrLoginServer string = acr.properties.loginServer
output apiUrl string = 'https://${apiApp.properties.configuration.ingress.fqdn}'
output apiAppName string = apiApp.name
output nightlyJobName string = nightlyJob.name
