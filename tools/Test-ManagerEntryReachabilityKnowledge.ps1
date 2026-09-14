[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message){throw $Message}
function Read-Json([string]$Relative){
    $path=Join-Path $RepositoryRoot ($Relative.Replace('/','\'))
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Missing engineering-knowledge file: '+$Relative)}
    try{return Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json}catch{Fail('Invalid JSON '+$Relative+': '+$_.Exception.Message)}
}
function New-Set(){return New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)}
function Add-Unique($Set,[string]$Id,[string]$Kind){if([string]::IsNullOrWhiteSpace($Id)){Fail($Kind+' id is empty.')}if(-not$Set.Add($Id)){Fail('Duplicate '+$Kind+' id: '+$Id)}}

$invariants=Read-Json 'tests/knowledge/invariants/multi-hub.json'
$model=Read-Json 'tests/knowledge/entry-reachability.json'
if([string]$model.schema-cne'keelaryn.manager-entry-reachability.v1'){Fail('Unexpected entry-reachability schema: '+[string]$model.schema)}

$invariantIds=New-Set
$invariantById=@{}
foreach($row in @($invariants.invariants)){
    $id=[string]$row.id;Add-Unique $invariantIds $id 'invariant';$invariantById[$id]=$row
}
if(-not$invariantIds.Contains('MH-RECOVERY-001')){Fail 'MH-RECOVERY-001 is missing.'}
$recoveryCoverage=@($invariantById['MH-RECOVERY-001'].coverage|ForEach-Object{[string]$_})
if($recoveryCoverage -notcontains 'entry_executable'){Fail 'MH-RECOVERY-001 must require entry_executable coverage.'}

$stateIds=New-Set
foreach($row in @($model.states)){Add-Unique $stateIds ([string]$row.id) 'entry state'}
$actionIds=New-Set
$actionById=@{}
foreach($row in @($model.actions)){
    $id=[string]$row.id;Add-Unique $actionIds $id 'entry action';$actionById[$id]=$row
    if([string]::IsNullOrWhiteSpace([string]$row.class)){Fail($id+' class is empty.')}
    if([string]::IsNullOrWhiteSpace([string]$row.expected)){Fail($id+' expected contract is empty.')}
    if(@($row.invariants).Count-eq0){Fail($id+' has no invariant mapping.')}
    foreach($iid in @($row.invariants)){if(-not$invariantIds.Contains([string]$iid)){Fail($id+' references unknown invariant '+[string]$iid)}}
}

foreach($requiredState in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){
    if(-not$stateIds.Contains($requiredState)){Fail('Required degraded state is missing: '+$requiredState)}
}
foreach($requiredAction in @('ListInstances','SwitchInstance','BindInstance','RepairCurrent','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','UpdateHub','UpdateAll','BuildCandidateTransport','RestoreCandidateTransport')){
    if(-not$actionIds.Contains($requiredAction)){Fail('Required action is missing: '+$requiredAction)}
}

$scenarioIds=New-Set
$scenarioPairs=New-Set
foreach($row in @($model.mandatory_process_entry_scenarios)){
    $id=[string]$row.id;Add-Unique $scenarioIds $id 'entry scenario'
    $state=[string]$row.state;$action=[string]$row.action
    if(-not$stateIds.Contains($state)){Fail($id+' references unknown state '+$state)}
    if(-not$actionIds.Contains($action)){Fail($id+' references unknown action '+$action)}
    if([string]::IsNullOrWhiteSpace([string]$row.expected)){Fail($id+' expected result is empty.')}
    [void]$scenarioPairs.Add($state+'|'+$action)
}
foreach($pair in @(
    'REGISTRY_ACTIVE_CURRENT_MISSING|ListInstances',
    'REGISTRY_ACTIVE_CURRENT_MISSING|SwitchInstance',
    'REGISTRY_ACTIVE_CURRENT_MISSING|BindInstance',
    'REGISTRY_ACTIVE_CURRENT_MISSING|RepairCurrent',
    'REGISTRY_ACTIVE_CURRENT_MISSING|UpdateManager',
    'REGISTRY_ACTIVE_CURRENT_MISSING|UpdateHub',
    'REGISTRY_ACTIVE_METADATA_INVALID|ListInstances',
    'REGISTRY_ACTIVE_METADATA_INVALID|SwitchInstance'
)){
    if(-not$scenarioPairs.Contains($pair)){Fail('Mandatory process-entry pair is missing: '+$pair)}
}
if([string]::IsNullOrWhiteSpace([string]$model.freeze_rule)){Fail 'Entry-reachability freeze_rule is empty.'}

Write-Host 'Manager entry-reachability knowledge: PASS' -ForegroundColor Green
Write-Host ('  states: '+@($model.states).Count)
Write-Host ('  actions: '+@($model.actions).Count)
Write-Host ('  mandatory process-entry scenarios: '+@($model.mandatory_process_entry_scenarios).Count)
