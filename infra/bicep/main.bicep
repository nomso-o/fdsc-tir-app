@description('Base prefix used for resource names. Keep it short and globally unique.')
param baseName string

@description('Deployment location, defaults to the resource group location.')
param location string = resourceGroup().location

@description('Object ID for the administrator/service principal that manages secrets.')
param keyVaultAdminObjectId string

@description('Optional tags applied to every resource.')
param tags object = {}

var storageName = toLower('${baseName}storage')
var searchName = toLower('${baseName}-search')
var cosmosName = '${baseName}-cosmos'
var keyVaultName = '${baseName}-kv'
var openAiName = '${baseName}-openai'
var docIntelName = '${baseName}-docintel'
var cosmosDatabaseName = '${baseName}-db'

resource fdscIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${baseName}-uami'
  location: location
  tags: tags
}

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Disabled'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storage
  name: 'default'
}

resource tirDatasetsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'tir-datasets'
  properties: {
    publicAccess: 'None'
  }
}

resource tirResultsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'tir-results'
  properties: {
    publicAccess: 'None'
  }
}

resource fdscDocsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'fdsc-docs'
  properties: {
    publicAccess: 'None'
  }
}

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchName
  location: location
  tags: tags
  sku: {
    name: 'standard'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    disableLocalAuth: true
  }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' = {
  name: cosmosName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    enableFreeTier: false
    locations: [
      {
        locationName: location
        failoverPriority: 0
      }
    ]
    capabilities: []
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource cosmosSqlDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-04-15' = {
  parent: cosmos
  name: cosmosDatabaseName
  properties: {
    resource: {
      id: cosmosDatabaseName
    }
    options: {}
  }
}

resource chatHistoryContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosSqlDb
  name: 'chat_history'
  properties: {
    resource: {
      id: 'chat_history'
      partitionKey: {
        paths: [
          '/session_id'
        ]
        kind: 'Hash'
      }
    }
    options: {}
  }
}

resource tirScoresContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosSqlDb
  name: 'tir_scores'
  properties: {
    resource: {
      id: 'tir_scores'
      partitionKey: {
        paths: [
          '/session_id'
        ]
        kind: 'Hash'
      }
    }
    options: {}
  }
}

resource fdscDocumentsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: cosmosSqlDb
  name: 'fdsc_documents'
  properties: {
    resource: {
      id: 'fdsc_documents'
      partitionKey: {
        paths: [
          '/id'
        ]
        kind: 'Hash'
      }
    }
    options: {}
  }
}

resource openai 'Microsoft.CognitiveServices/accounts@2023-10-01' = {
  name: openAiName
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: '${baseName}-openai'
    publicNetworkAccess: 'Enabled'
  }
}

resource docintel 'Microsoft.CognitiveServices/accounts@2023-10-01' = {
  name: docIntelName
  location: location
  tags: tags
  kind: 'FormRecognizer'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: '${baseName}-docintel'
    publicNetworkAccess: 'Enabled'
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-02-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    enabledForTemplateDeployment: true
    enableRbacAuthorization: false
    enableSoftDelete: true
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    accessPolicies: [
      {
        tenantId: subscription().tenantId
        objectId: keyVaultAdminObjectId
        permissions: {
          secrets: [
            'get'
            'list'
            'set'
          ]
          keys: [
            'get'
            'create'
          ]
        }
      }
      {
        tenantId: subscription().tenantId
        objectId: fdscIdentity.properties.principalId
        permissions: {
          secrets: [
            'get'
            'list'
          ]
        }
      }
    ]
    publicNetworkAccess: 'Enabled'
  }
}

output managedIdentityResourceId string = fdscIdentity.id
output managedIdentityPrincipalId string = fdscIdentity.properties.principalId
output keyVaultUri string = keyVault.properties.vaultUri
output storageAccountId string = storage.id
output searchEndpoint string = search.properties.hostName
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output openAiEndpoint string = openai.properties.endpoint
output docIntelEndpoint string = docintel.properties.endpoint
output cosmosDatabaseName string = cosmosDatabaseName
