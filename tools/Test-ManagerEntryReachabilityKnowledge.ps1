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
$stateMachine=Read-Json 'tests/knowledge/state-machines/multi-hub.json'
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
    if([string]::IsNullOrWhiteSpace([string]$row.proof_mode)){Fail($id+' proof_mode is empty.')}
    if(@('list_success','target_success','global_success','diagnostic_reached','fail_closed') -cnotcontains [string]$row.expected_mode){Fail($id+' expected_mode is unsupported: '+[string]$row.expected_mode)}
    if(@($row.invariants).Count-eq0){Fail($id+' has no invariant mapping.')}
    foreach($iid in @($row.invariants)){if(-not$invariantIds.Contains([string]$iid)){Fail($id+' references unknown invariant '+[string]$iid)}}
}

foreach($requiredState in @('REGISTRY_DOCUMENT_INVALID','REGISTRY_HEALTHY','REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_GLOBAL','REGISTRY_PENDING_INSTANCE','REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){if(-not$stateIds.Contains($requiredState)){Fail('Required degraded state is missing: '+$requiredState)}}
foreach($requiredAction in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','InitializeInstanceRegistry','UpdateHub','UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport')){if(-not$actionIds.Contains($requiredAction)){Fail('Required action is missing: '+$requiredAction)}}
if([string]$actionById['BindInstance'].proof_mode-cne'changed_path_rebind_commit'){Fail 'BindInstance must require changed_path_rebind_commit proof.'}
if([string]$actionById['UpdateManager'].proof_mode-cne'install_successor_restart'){Fail 'UpdateManager must require install_successor_restart proof.'}

$requirementIds=New-Set;$pairs=New-Set;$pairModes=@{}
foreach($req in @($model.coverage_requirements)){
    $rid=[string]$req.id;Add-Unique $requirementIds $rid 'coverage requirement'
    if($null-ne$req.PSObject.Properties['expected_mode']){$reqMode=[string]$req.expected_mode;if(@('list_success','target_success','global_success','diagnostic_reached','fail_closed','registry_init_rejected_after_dispatch','registry_document_rejected_after_dispatch','registry_init_reconciles_global_input') -cnotcontains $reqMode){Fail($rid+' expected_mode override is unsupported: '+$reqMode)}}
    if(@($req.states).Count-eq0-or@($req.actions).Count-eq0){Fail($rid+' must contain states and actions.')}
    foreach($state in @($req.states)){
        $sid=[string]$state;if(-not$stateIds.Contains($sid)){Fail($rid+' references unknown state '+$sid)}
        foreach($action in @($req.actions)){
            $aid=[string]$action;if(-not$actionIds.Contains($aid)){Fail($rid+' references unknown action '+$aid)}
            $key=$sid+'|'+$aid
            if(-not$pairs.Add($key)){Fail('Duplicate generated state/action pair: '+$key)}
            $mode=[string]$actionById[$aid].expected_mode
            if($null-ne$req.PSObject.Properties['expected_mode']-and-not[string]::IsNullOrWhiteSpace([string]$req.expected_mode)){$mode=[string]$req.expected_mode}
            $pairModes[$key]=$mode
        }
    }
}
foreach($sid in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){
    foreach($aid in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','UpdateHub')){
        if(-not$pairs.Contains($sid+'|'+$aid)){Fail('All-degraded coverage omitted '+$sid+'|'+$aid)}
    }
}
foreach($sid in @('REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){foreach($aid in @('UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','InitializeInstanceRegistry')){if(-not$pairs.Contains($sid+'|'+$aid)){Fail('CURRENT-degraded boundary coverage omitted '+$sid+'|'+$aid)}}}
foreach($sid in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT')){if(-not$pairs.Contains($sid+'|InitializeInstanceRegistry')){Fail('Invalid-active registry initialization coverage omitted '+$sid+'|InitializeInstanceRegistry')}}
foreach($aid in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','UpdateHub','UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','InitializeInstanceRegistry')){if(-not$pairs.Contains('REGISTRY_DOCUMENT_INVALID|'+$aid)){Fail('REGISTRY_DOCUMENT_INVALID coverage omitted '+$aid)}}
foreach($sid in @('REGISTRY_HEALTHY','REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_INSTANCE','REGISTRY_PENDING_GLOBAL')){if(-not$pairs.Contains($sid+'|InitializeInstanceRegistry')){Fail('Existing-registry Initialize coverage omitted '+$sid)}}
if($pairs.Count-lt101){Fail('Entry-reachability cross-product is unexpectedly small: '+$pairs.Count)}
if([string]::IsNullOrWhiteSpace([string]$model.freeze_rule)){Fail 'Entry-reachability freeze_rule is empty.'}
if(-not([string]$model.freeze_rule).Contains('may not restore state through the same runtime path under test')){Fail 'Freeze rule must prohibit runtime-dependent scenario reset.'}
if(-not([string]$model.freeze_rule).Contains('changed-path rebind transaction')){Fail 'Freeze rule must require real changed-path BindInstance rebind.'}
if(-not([string]$model.freeze_rule).Contains('newer valid disposable Manager package')){Fail 'Freeze rule must require a real UpdateManager installation/restart.'}
if(-not([string]$model.freeze_rule).Contains('pending-global must prove identity-bound transfer')){Fail 'Freeze rule must require executable existing-registry Initialize semantics.'}

function Resolve-StateMachineOutcome([string]$State,[string]$Operation){
    $matches=@($stateMachine.rules|Where-Object{[string]$_.operation-ceq$Operation-and((@($_.states|ForEach-Object{[string]$_}) -ccontains $State)-or(@($_.states|ForEach-Object{[string]$_}) -ccontains '*'))})
    if($matches.Count-eq0){Fail('State machine has no rule for '+$State+' x '+$Operation)}
    $max=($matches|Measure-Object -Property priority -Maximum).Maximum
    $top=@($matches|Where-Object{[int]$_.priority-eq[int]$max})
    if($top.Count-ne1){Fail('State machine rule resolution is ambiguous for '+$State+' x '+$Operation+' at priority '+$max)}
    return [string]$top[0].outcome
}
$initSuccessOutcomes=@('no_op_after_full_validation','existing_registry_valid_without_old_current_dependency','reconcile_identity_bound_global_inputs_then_report_initialized')
foreach($sid in @($stateIds)){
    $key=$sid+'|InitializeInstanceRegistry';if(-not$pairs.Contains($key)){continue}
    $mode=[string]$pairModes[$key];$outcome=Resolve-StateMachineOutcome $sid 'InitializeRegistry'
    if($mode-ceq'global_success'){if($initSuccessOutcomes-cnotcontains$outcome){Fail('Initialize oracle expects success but state machine resolves '+$sid+' to '+$outcome)}}
    elseif($mode-ceq'registry_init_rejected_after_dispatch'){if($outcome-cne'reject_fail_closed'){Fail('Initialize oracle expects rejection but state machine resolves '+$sid+' to '+$outcome)}}
    elseif($mode-ceq'registry_init_reconciles_global_input'){if($outcome-cne'reconcile_identity_bound_global_inputs_then_report_initialized'){Fail('Pending-global Initialize oracle/state-machine mismatch: '+$outcome)}}
    else{Fail('Covered Initialize pair has unsupported cross-model mode '+$mode+' for '+$sid)}
}
Write-Host 'Manager entry-reachability knowledge: PASS' -ForegroundColor Green
Write-Host ('  states: '+@($model.states).Count)
Write-Host ('  actions: '+@($model.actions).Count)
Write-Host ('  generated process-entry scenarios: '+$pairs.Count)
