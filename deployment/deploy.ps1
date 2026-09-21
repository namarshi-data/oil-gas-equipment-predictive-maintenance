<#
.SYNOPSIS
Provision Azure ML, run the reproducible pipeline, register the result, and smoke-test batch inference.
.DESCRIPTION
This script creates billable Azure resources. It has not been executed for this portfolio.
Run from a PowerShell terminal after reviewing docs/azure.md and selecting your subscription.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$ResourceGroup,
    [Parameter(Mandatory)][string]$WorkspaceName,
    [Parameter(Mandatory)][string]$EndpointName,
    [string]$Location = 'canadacentral',
    [string]$ModelVersion,
    [ValidateSet('Pipeline', 'Local')][string]$ModelSource = 'Pipeline',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Az {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $result = & az @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI failed: az $($Arguments[0]) $($Arguments[1])" }
    return $result
}

function Wait-MLJob {
    param([string]$JobName)
    Invoke-Az -Arguments (@('ml', 'job', 'stream', '--name', $JobName) + $script:mlScope) | Out-Host
    $status = Invoke-Az -Arguments (@('ml', 'job', 'show', '--name', $JobName, '--query', 'status', '-o', 'tsv') + $script:mlScope)
    if ($status.Trim() -ne 'Completed') { throw "Azure ML job $JobName ended with status $status" }
}

function Find-OneFile {
    param([string]$Folder, [string]$Name)
    $files = @(Get-ChildItem -LiteralPath $Folder -Recurse -File -Filter $Name)
    if ($files.Count -ne 1) { throw "Expected exactly one $Name beneath $Folder" }
    return $files[0].FullName
}

Get-Command az -ErrorAction Stop | Out-Null
Push-Location $repoRoot
try {
    # Parsing produces JSON locally. Validation mode creates no cloud resources.
    Invoke-Az -Arguments @('bicep', 'build', '--file', 'deployment/main.bicep', '--stdout') | Out-Null
    if ($ValidateOnly) {
        Write-Host 'Bicep parsed. No cloud resources created. Azure ML schema validation still requires a configured workspace.'
        return
    }
    Invoke-Az -Arguments @('account', 'set', '--subscription', $SubscriptionId) | Out-Null
    Invoke-Az -Arguments @('extension', 'add', '--name', 'ml', '--upgrade', '--yes') | Out-Null
    Invoke-Az -Arguments @('group', 'create', '--name', $ResourceGroup, '--location', $Location, '-o', 'none') | Out-Null
    Invoke-Az -Arguments @('deployment', 'group', 'create', '--resource-group', $ResourceGroup,
        '--name', 'energy-ml-infrastructure', '--template-file', 'deployment/main.bicep',
        '--parameters', "workspaceName=$WorkspaceName", "location=$Location", '-o', 'none') | Out-Null
    $script:mlScope = @('--resource-group', $ResourceGroup, '--workspace-name', $WorkspaceName, '--subscription', $SubscriptionId)
    $releaseId = (Get-Date -Format 'yyyyMMddHHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0,6))
    $releaseFolder = Join-Path $repoRoot "artifacts/azure-releases/$releaseId"
    New-Item -ItemType Directory -Path $releaseFolder -Force | Out-Null
    Invoke-Az -Arguments (@('ml', 'compute', 'create', '--file', 'deployment/compute.yml', '-o', 'none') + $mlScope) | Out-Null
    Invoke-Az -Arguments (@('ml', 'environment', 'create', '--file', 'deployment/environment.yml', '-o', 'none') + $mlScope) | Out-Null

    if ($ModelSource -eq 'Pipeline') {
        Invoke-Az -Arguments (@('ml', 'job', 'validate', '--file', 'deployment/pipeline.yml') + $mlScope) | Out-Host
        $trainingJob = Invoke-Az -Arguments (@('ml', 'job', 'create', '--file', 'deployment/pipeline.yml', '--query', 'name', '-o', 'tsv') + $mlScope)
        $trainingJob = $trainingJob.Trim()
        Wait-MLJob -JobName $trainingJob
        $modelPath = "azureml://jobs/$trainingJob/outputs/model/paths/"
        $scoringInput = "azureml://jobs/$trainingJob/outputs/features/paths/"
        foreach ($outputName in @('model', 'features', 'predictions')) {
            Invoke-Az -Arguments (@('ml', 'job', 'download', '--name', $trainingJob, '--output-name', $outputName,
                '--download-path', (Join-Path $releaseFolder $outputName)) + $mlScope) | Out-Host
        }
        $manifestPath = Find-OneFile -Folder (Join-Path $releaseFolder 'model') -Name 'provenance.json'
        $expectedPath = Find-OneFile -Folder (Join-Path $releaseFolder 'predictions') -Name 'predictions.csv'
    } else {
        if (-not (Test-Path -LiteralPath 'artifacts/model.joblib')) { throw 'Run the local pipeline first.' }
        if (-not (Test-Path -LiteralPath 'data/processed/batch_features.csv')) { throw 'Batch features are missing.' }
        $modelPath = 'artifacts/model.joblib'
        $scoringInput = 'data/processed/batch_features.csv'
        $manifestPath = Join-Path $repoRoot 'artifacts/provenance.json'
        $expectedPath = Join-Path $releaseFolder 'expected.csv'
        & python -m energy_failure.batch_score --model $modelPath --input $scoringInput --output $expectedPath
        if ($LASTEXITCODE -ne 0) { throw 'Local candidate reference scoring failed.' }
    }

    $provenance = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $candidateModelFile = if ($ModelSource -eq 'Pipeline') {
        Find-OneFile -Folder (Join-Path $releaseFolder 'model') -Name 'model.joblib'
    } else { Join-Path $repoRoot 'artifacts/model.joblib' }
    if ((Get-FileHash -LiteralPath $candidateModelFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $provenance.model_artifact_sha256) {
        throw 'Candidate artifact hash differs from its provenance manifest.'
    }
    if ($ModelVersion -and $ModelVersion -ne $provenance.model_version) { throw 'ModelVersion must match the artifact provenance identity.' }
    $ModelVersion = $provenance.model_version
    $candidate = "candidate-$releaseId"
    $endpoints = @(Invoke-Az -Arguments (@('ml', 'batch-endpoint', 'list', '-o', 'json') + $mlScope) | ConvertFrom-Json)
    $existing = @($endpoints | Where-Object name -eq $EndpointName)
    $previousDefault = $null
    if ($existing.Count -gt 0) {
        $previousDefault = Invoke-Az -Arguments (@('ml', 'batch-endpoint', 'show', '--name', $EndpointName,
            '--query', 'defaults.deployment_name', '-o', 'tsv') + $mlScope)
        if ($previousDefault) { $previousDefault = $previousDefault.Trim() }
    } else {
        Invoke-Az -Arguments (@('ml', 'batch-endpoint', 'create', '--file', 'deployment/batch-endpoint.yml', '--name', $EndpointName, '-o', 'none') + $mlScope) | Out-Null
    }
    $rollbackArguments = @()
    if ($previousDefault) {
        $rollbackArguments = @('ml', 'batch-endpoint', 'update', '--name', $EndpointName,
            '--set', "defaults.deployment_name=$previousDefault") + $mlScope
    }
    $receipt = [ordered]@{status='candidate_prepared'; endpoint=$EndpointName; candidate=$candidate;
        model_version=$ModelVersion; previous_default=$previousDefault; rollback_arguments=$rollbackArguments;
        first_deployment_has_no_previous_default=(-not [bool]$previousDefault)}
    $receiptPath = Join-Path $releaseFolder 'release.json'
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8

    Invoke-Az -Arguments (@('ml', 'model', 'create', '--name', 'energy-failure-30d', '--version', $ModelVersion,
        '--type', 'custom_model', '--path', $modelPath, '--description', 'Synthetic 30-day equipment failure model', '-o', 'none') + $mlScope) | Out-Null
    Invoke-Az -Arguments (@('ml', 'batch-deployment', 'create', '--file', 'deployment/batch-deployment.yml',
        '--name', $candidate, '--endpoint-name', $EndpointName, '--set', "model=azureml:energy-failure-30d:$ModelVersion", '-o', 'none') + $mlScope) | Out-Null
    $inputType = if ($ModelSource -eq 'Pipeline') { 'uri_folder' } else { 'uri_file' }
    $scoringJob = Invoke-Az -Arguments (@('ml', 'batch-endpoint', 'invoke', '--name', $EndpointName,
        '--deployment-name', $candidate, '--input', $scoringInput, '--input-type', $inputType, '--query', 'name', '-o', 'tsv') + $mlScope)
    $scoringJob = $scoringJob.Trim()
    Wait-MLJob -JobName $scoringJob
    Invoke-Az -Arguments (@('ml', 'job', 'download', '--name', $scoringJob, '--output-name', 'score',
        '--download-path', (Join-Path $releaseFolder 'cloud-output')) + $mlScope) | Out-Host
    $actualPath = Find-OneFile -Folder (Join-Path $releaseFolder 'cloud-output') -Name 'predictions.csv'
    & python deployment/reconcile_cloud_output.py --expected $expectedPath --actual $actualPath --report (Join-Path $releaseFolder 'reconciliation.json')
    if ($LASTEXITCODE -ne 0) { throw 'Candidate failed reconciliation; the existing default has not been changed.' }
    $currentDefault = Invoke-Az -Arguments (@('ml', 'batch-endpoint', 'show', '--name', $EndpointName,
        '--query', 'defaults.deployment_name', '-o', 'tsv') + $mlScope)
    if ([string]$currentDefault -ne [string]$previousDefault) { throw 'Default changed during validation; stop to avoid overwriting another release.' }
    $receipt.status = 'validated_not_promoted'
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8
    Invoke-Az -Arguments (@('ml', 'batch-endpoint', 'update', '--name', $EndpointName,
        '--set', "defaults.deployment_name=$candidate", '-o', 'none') + $mlScope) | Out-Null
    $promoted = Invoke-Az -Arguments (@('ml', 'batch-endpoint', 'show', '--name', $EndpointName,
        '--query', 'defaults.deployment_name', '-o', 'tsv') + $mlScope)
    if ([string]$promoted -ne $candidate) { throw 'Default promotion was not confirmed; inspect the release receipt and endpoint.' }
    $receipt.status = 'promoted'
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8
    Write-Host "Validated and promoted $candidate. Previous deployment retained; rollback arguments recorded in $receiptPath."
} finally {
    Pop-Location
}