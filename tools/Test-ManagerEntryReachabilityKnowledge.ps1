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
if([string]$model.schema-cne'keelaryn.manager-entry-reachability.v2'){Fail('Unexpected entry-reachability schema: '+[string]$model.schema)}

$invariantIds=New-Set;$invariantById=@{}
foreach($row in @($invariants.invariants)){$id=[string]$row.id;Add-Unique $invariantIds $id 'invariant';$invariantById[$id]=$row}
if(-not$invariantIds.Contains('MH-RECOVERY-001')){Fail 'MH-RECOVERY-001 is missing.'}
if(@($invariantById['MH-RECOVERY-001'].coverage|ForEach-Object{[string]$_}) -notcontains 'entry_executable'){Fail 'MH-RECOVERY-001 must require entry_executable coverage.'}

$stateIds=New-Set;$stateById=@{};$fixtureIds=New-Set
foreach($row in @($model.states)){
    $id=[string]$row.id;Add-Unique $stateIds $id 'entry state';$stateById[$id]=$row
    $fixture=[string]$row.fixture;if([string]::IsNullOrWhiteSpace($fixture)){Fail($id+' fixture is empty.')};Add-Unique $fixtureIds $fixture 'entry fixture'
}
$actionIds=New-Set;$actionById=@{}
foreach($row in @($model.actions)){
    $id=[string]$row.id;Add-Unique $actionIds $id 'entry action';$actionById[$id]=$row
    if([string]::IsNullOrWhiteSpace([string]$row.class)){Fail($id+' class is empty.')}
    if(@('list_success','target_success','global_success','diagnostic_reached','fail_closed') -cnotcontains [string]$row.expected_mode){Fail($id+' expected_mode is unsupported: '+[string]$row.expected_mode)}
    if(@($row.invariants).Count-eq0){Fail($id+' has no invariant mapping.')}
    foreach($iid in @($row.invariants)){if(-not$invariantIds.Contains([string]$iid)){Fail($id+' references unknown invariant '+[string]$iid)}}
}

foreach($requiredState in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){if(-not$stateIds.Contains($requiredState)){Fail('Required degraded state is missing: '+$requiredState)}}
foreach($requiredAction in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','InitializeInstanceRegistry','UpdateHub','UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport')){if(-not$actionIds.Contains($requiredAction)){Fail('Required action is missing: '+$requiredAction)}}

$requirementIds=New-Set;$pairs=New-Set
foreach($req in @($model.coverage_requirements)){
    $rid=[string]$req.id;Add-Unique $requirementIds $rid 'coverage requirement'
    if(@($req.states).Count-eq0-or@($req.actions).Count-eq0){Fail($rid+' must contain states and actions.')}
    foreach($state in @($req.states)){
        $sid=[string]$state;if(-not$stateIds.Contains($sid)){Fail($rid+' references unknown state '+$sid)}
        foreach($action in @($req.actions)){
            $aid=[string]$action;if(-not$actionIds.Contains($aid)){Fail($rid+' references unknown action '+$aid)}
            if(-not$pairs.Add($sid+'|'+$aid)){Fail('Duplicate generated state/action pair: '+$sid+'|'+$aid)}
        }
    }
}
foreach($sid in @($stateIds)){
    foreach($aid in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','UpdateHub')){
        if(-not$pairs.Contains($sid+'|'+$aid)){Fail('All-degraded coverage omitted '+$sid+'|'+$aid)}
    }
}
foreach($sid in @('REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){
    foreach($aid in @('UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','InitializeInstanceRegistry')){if(-not$pairs.Contains($sid+'|'+$aid)){Fail('CURRENT-degraded boundary coverage omitted '+$sid+'|'+$aid)}}
}
if($pairs.Count-lt75){Fail('Entry-reachability cross-product is unexpectedly small: '+$pairs.Count)}
if([string]::IsNullOrWhiteSpace([string]$model.freeze_rule)){Fail 'Entry-reachability freeze_rule is empty.'}
if(-not([string]$model.freeze_rule).Contains('may not restore state through the same runtime path under test')){Fail 'Freeze rule must prohibit runtime-dependent scenario reset.'}

Write-Host 'Manager entry-reachability knowledge: PASS' -ForegroundColor Green
Write-Host ('  states: '+@($model.states).Count)
Write-Host ('  actions: '+@($model.actions).Count)
Write-Host ('  generated process-entry scenarios: '+$pairs.Count)
