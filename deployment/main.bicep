targetScope = 'resourceGroup'

@description('Azure ML workspace name.')
param workspaceName string = 'energy-failure-ml'

@description('Region for all resources; choose a region supporting your VM quota.')
param location string = resourceGroup().location

var suffix = uniqueString(resourceGroup().id, workspaceName)

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stenergy${suffix}'
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-energy-${suffix}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    accessPolicies: []
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-energy-${suffix}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-energy-${suffix}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acrenergy${suffix}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource workspace 'Microsoft.MachineLearningServices/workspaces@2024-10-01' = {
  name: workspaceName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    friendlyName: 'Energy predictive equipment failure'
    description: 'Synthetic maintenance benchmark, training pipeline and batch scoring.'
    storageAccount: storage.id
    keyVault: keyVault.id
    applicationInsights: insights.id
    containerRegistry: registry.id
    publicNetworkAccess: 'Enabled'
  }
}

output workspaceName string = workspace.name
output workspaceId string = workspace.id
output storageAccountName string = storage.name