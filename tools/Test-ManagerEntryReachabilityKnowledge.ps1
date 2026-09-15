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
$supplement=Read-Json 'tests/knowledge/entry-reachability-supplemental.json'
$stateMachine=Read-Json 'tests/knowledge/state-machines/multi-hub.json'
if([string]$model.schema-cne'keelaryn.manager-entry-reachability.v2'){Fail('Unexpected entry-reachability schema: '+[string]$model.schema)}
if([string]$supplement.schema-cne'keelaryn.manager-entry-reachability-supplemental.v1'){Fail('Unexpected supplemental entry-reachability schema: '+[string]$supplement.schema)}

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

foreach($requiredState in @('REGISTRY_DOCUMENT_INVALID','REGISTRY_HEALTHY','REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_GLOBAL','REGISTRY_PENDING_GLOBAL_INVALID','REGISTRY_PENDING_INSTANCE','REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){if(-not$stateIds.Contains($requiredState)){Fail('Required degraded state is missing: '+$requiredState)}}
foreach($requiredAction in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','InitializeInstanceRegistry','UpdateHub','UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport')){if(-not$actionIds.Contains($requiredAction)){Fail('Required action is missing: '+$requiredAction)}}
if([string]$actionById['BindInstance'].proof_mode-cne'changed_path_rebind_commit'){Fail 'BindInstance must require changed_path_rebind_commit proof.'}
if([string]$actionById['UpdateManager'].proof_mode-cne'install_successor_restart'){Fail 'UpdateManager must require install_successor_restart proof.'}
foreach($aid in @('BuildDistribution','BuildRelease','BuildAIContext','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout')){if([string]$actionById[$aid].proof_mode-cne'manager_global_execution'){Fail($aid+' must remain bound to manager_global_execution proof mode.')}}

$requirementIds=New-Set;$pairs=New-Set;$pairModes=@{}
foreach($req in @($model.coverage_requirements)){
    $rid=[string]$req.id;Add-Unique $requirementIds $rid 'coverage requirement'
    if($null-ne$req.PSObject.Properties['expected_mode']){$reqMode=[string]$req.expected_mode;if(@('list_success','target_success','global_success','diagnostic_reached','fail_closed','registry_init_rejected_after_dispatch','registry_document_rejected_after_dispatch','registry_init_reconciles_global_input','registry_init_mixed_invalid_rejected_without_partial_handoff') -cnotcontains $reqMode){Fail($rid+' expected_mode override is unsupported: '+$reqMode)}}
    if(@($req.states).Count-eq0-or@($req.actions).Count-eq0){Fail($rid+' must contain states and actions.')}
    foreach($state in @($req.states)){
        $sid=[string]$state;if(-not$stateIds.Contains($sid)){Fail($rid+' references unknown state '+$sid)}
        foreach($action in @($req.actions)){
            $aid=[string]$action;if(-not$actionIds.Contains($aid)){Fail($rid+' references unknown action '+$aid)}
            $key=$sid+'|'+$aid;if(-not$pairs.Add($key)){Fail('Duplicate generated state/action pair: '+$key)}
            $mode=[string]$actionById[$aid].expected_mode;if($null-ne$req.PSObject.Properties['expected_mode']-and-not[string]::IsNullOrWhiteSpace([string]$req.expected_mode)){$mode=[string]$req.expected_mode};$pairModes[$key]=$mode
        }
    }
}
foreach($sid in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){foreach($aid in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','UpdateHub')){if(-not$pairs.Contains($sid+'|'+$aid)){Fail('All-degraded coverage omitted '+$sid+'|'+$aid)}}}
foreach($sid in @('REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){foreach($aid in @('UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','InitializeInstanceRegistry')){if(-not$pairs.Contains($sid+'|'+$aid)){Fail('CURRENT-degraded boundary coverage omitted '+$sid+'|'+$aid)}}}
foreach($sid in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT')){if(-not$pairs.Contains($sid+'|InitializeInstanceRegistry')){Fail('Invalid-active registry initialization coverage omitted '+$sid+'|InitializeInstanceRegistry')}}
foreach($aid in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','UpdateHub','UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','InitializeInstanceRegistry')){if(-not$pairs.Contains('REGISTRY_DOCUMENT_INVALID|'+$aid)){Fail('REGISTRY_DOCUMENT_INVALID coverage omitted '+$aid)}}
foreach($sid in @('REGISTRY_HEALTHY','REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_INSTANCE','REGISTRY_PENDING_GLOBAL','REGISTRY_PENDING_GLOBAL_INVALID')){if(-not$pairs.Contains($sid+'|InitializeInstanceRegistry')){Fail('Existing-registry Initialize coverage omitted '+$sid)}}
if($pairs.Count-ne102){Fail('Canonical entry-reachability cross-product must remain exactly 102; actual='+$pairs.Count)}

$supplementRows=@($supplement.scenarios)
if($supplementRows.Count-ne2){Fail('Supplemental entry-reachability scenario count must be exactly 2; actual='+$supplementRows.Count)}
$er103=@($supplementRows|Where-Object{[string]$_.id-ceq'ER-103'});$er104=@($supplementRows|Where-Object{[string]$_.id-ceq'ER-104'})
if($er103.Count-ne1-or$er104.Count-ne1){Fail 'Supplemental rollback proofs must contain exactly ER-103 and ER-104.'}
$er103=$er103[0];$er104=$er104[0]
foreach($s in @($er103,$er104)){
    if([string]$s.state-cne'REGISTRY_PENDING_GLOBAL'-or-not$stateIds.Contains([string]$s.state)){Fail([string]$s.id+' must use canonical REGISTRY_PENDING_GLOBAL.')}
    if([string]$s.action-cne'InitializeInstanceRegistry'-or-not$actionIds.Contains([string]$s.action)){Fail([string]$s.id+' must exercise InitializeInstanceRegistry.')}
    if([string]$s.fixture-cne'registry_pending_global_rollback_fault'){Fail([string]$s.id+' rollback fixture mismatch.')}
    foreach($iid in @($s.invariants)){if(-not$invariantIds.Contains([string]$iid)){Fail([string]$s.id+' references unknown invariant '+[string]$iid)}}
    foreach($iid in @('MH-COMMIT-001','MH-LIFECYCLE-001','MH-INBOX-001')){if(@($s.invariants|ForEach-Object{[string]$_}) -cnotcontains $iid){Fail([string]$s.id+' omitted invariant '+$iid)}}
}
if([string]$er103.requirement-cne'SR-PENDING-GLOBAL-PUBLICATION-ROLLBACK'-or[string]$er103.expected_mode-cne'registry_init_publication_fault_rolls_back_batch'-or[string]$er103.proof_mode-cne'phase4_fault_after_first_verified_publication'){Fail 'ER-103 rollback contract mismatch.'}
foreach($token in @('two_valid_identity_bound_global_sources','first_destination_published_and_verified_before_fault','real_phase4_catch_executes','all_new_destinations_rolled_back','all_global_sources_preserved_with_exact_hashes','no_stage_residue','registry_active_compat_baseline_and_hubs_unchanged')){if(@($er103.required_assertions|ForEach-Object{[string]$_}) -cnotcontains $token){Fail('ER-103 omitted assertion '+$token)}}
if([string]$er104.requirement-cne'SR-PENDING-GLOBAL-ROLLBACK-SOURCE-PRESERVATION'-or[string]$er104.expected_mode-cne'registry_init_publication_fault_preserves_verified_destination_on_source_loss'-or[string]$er104.proof_mode-cne'phase4_fault_after_first_publication_with_source_loss'){Fail 'ER-104 source-loss rollback contract mismatch.'}
foreach($token in @('two_valid_identity_bound_global_sources','first_destination_published_and_verified_before_source_loss','first_global_source_removed_after_publication','real_phase4_catch_executes','verified_first_destination_retained_when_source_integrity_cannot_be_proven','second_global_source_preserved_with_exact_hash','second_destination_not_published','no_stage_residue','registry_active_compat_baseline_and_hubs_unchanged','partial_durable_handoff_reported_fail_closed')){if(@($er104.required_assertions|ForEach-Object{[string]$_}) -cnotcontains $token){Fail('ER-104 omitted assertion '+$token)}}
$executableTotal=$pairs.Count+$supplementRows.Count;if($executableTotal-ne104){Fail('Executable entry-reachability scenario total must be 104; actual='+$executableTotal)}

if([string]::IsNullOrWhiteSpace([string]$model.freeze_rule)){Fail 'Entry-reachability freeze_rule is empty.'}
if(-not([string]$model.freeze_rule).Contains('may not restore state through the same runtime path under test')){Fail 'Freeze rule must prohibit runtime-dependent scenario reset.'}
if(-not([string]$model.freeze_rule).Contains('changed-path rebind transaction')){Fail 'Freeze rule must require real changed-path BindInstance rebind.'}
if(-not([string]$model.freeze_rule).Contains('newer valid disposable Manager package')){Fail 'Freeze rule must require a real UpdateManager installation/restart.'}
if(-not([string]$model.freeze_rule).Contains('pending-global must prove identity-bound transfer')){Fail 'Freeze rule must require executable existing-registry Initialize semantics.'}
if(-not([string]$model.freeze_rule).Contains('mixed valid/invalid pending-global batch')){Fail 'Freeze rule must require mixed-invalid pending-global atomicity.'}

function Resolve-StateMachineOutcome([string]$State,[string]$Operation){
    $matches=@($stateMachine.rules|Where-Object{[string]$_.operation-ceq$Operation-and((@($_.states|ForEach-Object{[string]$_}) -ccontains $State)-or(@($_.states|ForEach-Object{[string]$_}) -ccontains '*'))})
    if($matches.Count-eq0){Fail('State machine has no rule for '+$State+' x '+$Operation)}
    $max=($matches|Measure-Object -Property priority -Maximum).Maximum;$top=@($matches|Where-Object{[int]$_.priority-eq[int]$max})
    if($top.Count-ne1){Fail('State machine rule resolution is ambiguous for '+$State+' x '+$Operation+' at priority '+$max)};return [string]$top[0].outcome
}
$initSuccessOutcomes=@('no_op_after_full_validation','existing_registry_valid_without_old_current_dependency','reconcile_identity_bound_global_inputs_then_report_initialized')
foreach($sid in @($stateIds)){
    $key=$sid+'|InitializeInstanceRegistry';if(-not$pairs.Contains($key)){continue};$mode=[string]$pairModes[$key];$outcome=Resolve-StateMachineOutcome $sid 'InitializeRegistry'
    if($mode-ceq'global_success'){if($initSuccessOutcomes-cnotcontains$outcome){Fail('Initialize oracle expects success but state machine resolves '+$sid+' to '+$outcome)}}
    elseif($mode-ceq'registry_init_rejected_after_dispatch'){if($outcome-cne'reject_fail_closed'){Fail('Initialize oracle expects rejection but state machine resolves '+$sid+' to '+$outcome)}}
    elseif($mode-ceq'registry_init_reconciles_global_input'){if($outcome-cne'reconcile_identity_bound_global_inputs_then_report_initialized'){Fail('Pending-global Initialize oracle/state-machine mismatch: '+$outcome)}}
    elseif($mode-ceq'registry_init_mixed_invalid_rejected_without_partial_handoff'){if($outcome-cne'reject_fail_closed'){Fail('Mixed-invalid pending-global Initialize oracle/state-machine mismatch: '+$outcome)}}
    else{Fail('Covered Initialize pair has unsupported cross-model mode '+$mode+' for '+$sid)}
}
Write-Host 'Manager entry-reachability knowledge: PASS' -ForegroundColor Green
Write-Host ('  states: '+@($model.states).Count)
Write-Host ('  actions: '+@($model.actions).Count)
Write-Host ('  canonical process-entry scenarios: '+$pairs.Count)
Write-Host ('  supplemental process-entry scenarios: '+$supplementRows.Count)
Write-Host ('  executable process-entry total: '+$executableTotal)
