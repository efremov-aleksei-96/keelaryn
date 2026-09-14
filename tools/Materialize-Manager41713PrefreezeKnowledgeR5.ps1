[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [string]$EvidenceRoot=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8=New-Object Text.UTF8Encoding($false)
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path $env:RUNNER_TEMP 'manager-41713-prefreeze-knowledge-r5'}
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null
function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8)}
function Write-Json([string]$Path,$Object,[int]$Depth=60){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth $Depth).Replace("`r`n","`n"))+"`n")}
function Replace-Once([string]$Path,[string]$Old,[string]$New,[string]$Label){
    $s=[IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8);$count=[regex]::Matches($s,[regex]::Escape($Old)).Count
    if($count-ne1){Fail($Label+' count='+$count)}
    Write-Utf8 $Path ($s.Replace($Old,$New))
}
function Parse-File([string]$Path){$t=$null;$e=$null;[void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e);if(@($e).Count){Fail('Parser failed: '+$Path+' :: '+([string]::Join(' | ',@($e|ForEach-Object{$_.Message}))))}}
function Invoke-Child([string]$Script,[string[]]$Arguments,[switch]$AllowFailure){
    $exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    foreach($line in @($out)){Write-Host $line}
    if(-not$AllowFailure-and$code-ne0){Fail('Child failed: '+$Script+' exit='+$code)}
    return [pscustomobject]@{ExitCode=$code;Output=@($out);Text=[string]::Join("`n",@($out))}
}
function Add-JsonPropertyIfMissing($Object,[string]$Name,$Value){if($null-eq$Object.PSObject.Properties[$Name]){$Object|Add-Member -NotePropertyName $Name -NotePropertyValue $Value}else{$Object.$Name=$Value}}

$head=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($head-cne$ExpectedBase.ToLowerInvariant()){Fail('Unexpected target HEAD: '+$head+' expected='+$ExpectedBase)}
if(@(& git.exe -C $RepositoryRoot status --porcelain).Count-ne0){Fail 'Target checkout is not clean.'}

$entryPath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability.json'
$stateMachinePath=Join-Path $RepositoryRoot 'tests\knowledge\state-machines\multi-hub.json'
$prefreezePath=Join-Path $RepositoryRoot 'tests\knowledge\prefreeze-semantic-review.json'
$validatorPath=Join-Path $RepositoryRoot 'tools\Test-ManagerEntryReachabilityKnowledge.ps1'
$matrixPath=Join-Path $RepositoryRoot 'tools\Invoke-ManagerEntryReachabilityMatrix.ps1'
$devStatePath=Join-Path $RepositoryRoot 'MANAGER_DEVELOPMENT_STATE.json'
$provenancePath=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json'
foreach($p in @($entryPath,$stateMachinePath,$prefreezePath,$validatorPath,$matrixPath,$devStatePath,$provenancePath)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Required source missing: '+$p)}}

# 1. Converge the canonical state machine with the already-intended executable InitializeRegistry semantics.
$sm=Get-Content -LiteralPath $stateMachinePath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$sm.schema-cne'keelaryn.manager-state-machine.v1'){Fail 'Unexpected state-machine schema.'}
$idempotent=@($sm.rules|Where-Object{[string]$_.id-ceq'R-REGISTRY-INIT-IDEMPOTENT'})
if($idempotent.Count-ne1){Fail('R-REGISTRY-INIT-IDEMPOTENT count='+$idempotent.Count)}
$idempotent[0].states=@('REGISTRY_HEALTHY','REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_INSTANCE')
$idempotent[0].reason='An existing structurally valid registry may report initialized when active selection resolves; inactive-Hub degradation or instance-owned pending input does not invalidate registry initialization state.'
if(@($sm.rules|Where-Object{[string]$_.id-ceq'R-CURRENT-DEGRADED-INIT'}).Count-ne0){Fail 'R-CURRENT-DEGRADED-INIT already exists.'}
if(@($sm.rules|Where-Object{[string]$_.id-ceq'R-REGISTRY-GLOBAL-PENDING-INIT'}).Count-ne0){Fail 'R-REGISTRY-GLOBAL-PENDING-INIT already exists.'}
$currentInit=[pscustomobject][ordered]@{
    id='R-CURRENT-DEGRADED-INIT';states=@('REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT');operation='InitializeRegistry';priority=210;outcome='existing_registry_valid_without_old_current_dependency';invariants=@('MH-REGISTRY-001','MH-RECOVERY-001');reason='Existing-registry initialization validates registry and active selection but does not consume old active CURRENT; CURRENT recovery remains a separate lifecycle operation.'
}
$pendingInit=[pscustomobject][ordered]@{
    id='R-REGISTRY-GLOBAL-PENDING-INIT';states=@('REGISTRY_PENDING_GLOBAL');operation='InitializeRegistry';priority=180;outcome='reconcile_identity_bound_global_inputs_then_report_initialized';invariants=@('MH-INBOX-001','MH-REGISTRY-001','MH-REACHABILITY-001');reason='InitializeRegistry is the explicit recovery path for identity-bound Hub inputs stranded in the global Manager inbox after registry activation.'
}
$sm.rules=@($sm.rules)+@($currentInit,$pendingInit)
Write-Json $stateMachinePath $sm 70

# 2. Strengthen real-entry coverage to include invalid registry document plus operation-specific registry-init rejection.
$model=Get-Content -LiteralPath $entryPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$model.schema-cne'keelaryn.manager-entry-reachability.v2'){Fail 'Unexpected entry-reachability schema.'}
if(@($model.states|Where-Object{[string]$_.id-ceq'REGISTRY_DOCUMENT_INVALID'}).Count-ne0){Fail 'REGISTRY_DOCUMENT_INVALID already exists in entry model.'}
$model.states=@($model.states)+@([pscustomobject][ordered]@{id='REGISTRY_DOCUMENT_INVALID';fixture='registry_document_invalid';description='instances.json exists but the authoritative registry document is malformed and unsafe to resolve.'})
$newRequirements=@(
    [pscustomobject][ordered]@{id='CR-REGISTRY-INIT-INVALID-ACTIVE';states=@('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT');actions=@('InitializeInstanceRegistry');expected_mode='registry_init_rejected_after_dispatch'},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-GLOBAL';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout')},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-DOCTOR';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('Doctor')},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-RECOVERY';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('ListInstances','SwitchInstance','BindInstance');expected_mode='registry_document_rejected_after_dispatch'},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-INIT';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('InitializeInstanceRegistry');expected_mode='registry_init_rejected_after_dispatch'},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-BOUND';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('UpdateHub','UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport')}
)
foreach($r in $newRequirements){if(@($model.coverage_requirements|Where-Object{[string]$_.id-ceq[string]$r.id}).Count-ne0){Fail('Coverage requirement already exists: '+[string]$r.id)}}
$model.coverage_requirements=@($model.coverage_requirements)+@($newRequirements)
$freezeExtra=' InitializeInstanceRegistry invalid-active coverage must prove operation-specific rejection after process-entry dispatch. REGISTRY_DOCUMENT_INVALID must cover every modeled entry action; List/Switch/Bind must prove action-level registry reparsing while unsafe rows never become recovery targets. Rejected registry recovery/initialization must preserve instances.json and active_instance.json bytes. Entry-oracle InitializeInstanceRegistry expectations must resolve consistently with the canonical multi-Hub state machine.'
if(-not([string]$model.freeze_rule).Contains('Entry-oracle InitializeInstanceRegistry expectations')){$model.freeze_rule=([string]$model.freeze_rule)+$freezeExtra}
Write-Json $entryPath $model 60

# 3. Matrix supports requirement-level expected outcomes, malformed-registry fixture and control-state immutability.
$oldGenerator="            `$ordinal++;`$sid=[string]`$sid0;`$aid=[string]`$aid0`n            [void]`$scenarioSpecs.Add([pscustomobject]@{Id=('ER-{0:D3}' -f `$ordinal);Requirement=[string]`$req.id;State=`$sid;Action=`$aid;Mode=[string]`$actionById[`$aid].expected_mode})"
$newGenerator="            `$ordinal++;`$sid=[string]`$sid0;`$aid=[string]`$aid0`n            `$mode=[string]`$actionById[`$aid].expected_mode`n            if(`$null-ne`$req.PSObject.Properties['expected_mode']-and-not[string]::IsNullOrWhiteSpace([string]`$req.expected_mode)){`$mode=[string]`$req.expected_mode}`n            [void]`$scenarioSpecs.Add([pscustomobject]@{Id=('ER-{0:D3}' -f `$ordinal);Requirement=[string]`$req.id;State=`$sid;Action=`$aid;Mode=`$mode})"
Replace-Once $matrixPath $oldGenerator $newGenerator 'matrix requirement expected_mode override'
$oldFixture="        switch(`$Fixture){`n            'active_metadata_invalid' {Write-Utf8 `$activeFile '{ not-json'}"
$newFixture="        switch(`$Fixture){`n            'registry_document_invalid' {Write-Utf8 (Join-Path `$stateRoot 'instances.json') '{ not-json'}`n            'active_metadata_invalid' {Write-Utf8 `$activeFile '{ not-json'}"
Replace-Once $matrixPath $oldFixture $newFixture 'matrix invalid registry fixture'
$oldCapture="            `$alphaBefore=Get-TreeDigest `$alphaPath;`$betaBefore=Get-TreeDigest `$betaPath;`$betaRelocatedBefore=Get-TreeDigest `$betaRelocatedPath`n            `$r=Invoke-Runtime `$runtime (Get-ActionArguments `$spec.Action);`$exitCode=`$r.ExitCode`n            `$hubsUnchanged=((Get-TreeDigest `$alphaPath)-ceq`$alphaBefore-and(Get-TreeDigest `$betaPath)-ceq`$betaBefore-and(Get-TreeDigest `$betaRelocatedPath)-ceq`$betaRelocatedBefore)"
$newCapture="            `$alphaBefore=Get-TreeDigest `$alphaPath;`$betaBefore=Get-TreeDigest `$betaPath;`$betaRelocatedBefore=Get-TreeDigest `$betaRelocatedPath`n            `$registryControl=Join-Path `$stateRoot 'instances.json'`n            `$registryBefore=if(Test-Path -LiteralPath `$registryControl -PathType Leaf){(Get-FileHash -LiteralPath `$registryControl -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$activeBefore=if(Test-Path -LiteralPath `$activeFile -PathType Leaf){(Get-FileHash -LiteralPath `$activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$r=Invoke-Runtime `$runtime (Get-ActionArguments `$spec.Action);`$exitCode=`$r.ExitCode`n            `$hubsUnchanged=((Get-TreeDigest `$alphaPath)-ceq`$alphaBefore-and(Get-TreeDigest `$betaPath)-ceq`$betaBefore-and(Get-TreeDigest `$betaRelocatedPath)-ceq`$betaRelocatedBefore)`n            `$registryAfter=if(Test-Path -LiteralPath `$registryControl -PathType Leaf){(Get-FileHash -LiteralPath `$registryControl -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$activeAfter=if(Test-Path -LiteralPath `$activeFile -PathType Leaf){(Get-FileHash -LiteralPath `$activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$controlStateUnchanged=(`$registryAfter-ceq`$registryBefore-and`$activeAfter-ceq`$activeBefore)"
Replace-Once $matrixPath $oldCapture $newCapture 'matrix control state immutability capture'
$oldGeneric="                    }else{`n                        `$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged);`$detail=if(`$pass){'Manager-global action completed independently of degraded Hub context'}else{'Manager-global action blocked/failed or mutated Hub bytes: '+`$r.Text}`n                    }"
$newGeneric="                    }elseif([string]`$spec.Action-ceq'InitializeInstanceRegistry'){`n                        `$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$controlStateUnchanged-and`$r.Text.Contains('Multi-Hub registry is already initialized and valid.'))`n                        `$detail=if(`$pass){'existing-registry initialization remained reachable without old CURRENT dependency and preserved registry/active control bytes'}else{'existing-registry initialization did not reach intended idempotent/recovery success or mutated control state: '+`$r.Text}`n                    }else{`n                        `$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged);`$detail=if(`$pass){'Manager-global action completed independently of degraded Hub context'}else{'Manager-global action blocked/failed or mutated Hub bytes: '+`$r.Text}`n                    }"
Replace-Once $matrixPath $oldGeneric $newGeneric 'matrix InitializeInstanceRegistry success proof'
$oldFail="                'fail_closed' {`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged);`$detail=if(`$pass){'Hub/context-bound action failed closed without Hub mutation'}else{'expected fail-closed outcome not observed: '+`$r.Text}}"
$newFail="                'registry_document_rejected_after_dispatch' {`$startupBlocked=`$r.Text.Contains('Invalid Keelaryn multi-Hub registry:');`$operationReached=`$r.Text.Contains('Manager instance registry JSON is invalid:');`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$controlStateUnchanged-and-not`$startupBlocked-and`$operationReached);`$detail=if(`$pass){'unsafe registry document passed startup allow-dispatch, reached action-level registry parsing, and was rejected without state mutation'}else{'action-level unsafe-registry rejection was not proven, startup blocked first, or state mutated: '+`$r.Text}}`n                'registry_init_rejected_after_dispatch' {`$reached=`$r.Text.Contains('Existing multi-Hub registry is invalid:');`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$controlStateUnchanged-and`$reached);`$detail=if(`$pass){'InitializeInstanceRegistry reached its existing-registry validator and rejected invalid authoritative registry state without mutation'}else{'registry initialization was blocked before operation-specific validation, succeeded unexpectedly, or mutated state: '+`$r.Text}}`n                'fail_closed' {`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$controlStateUnchanged);`$detail=if(`$pass){'Hub/context-bound action failed closed without Hub or registry/active mutation'}else{'expected fail-closed outcome not observed: '+`$r.Text}}"
Replace-Once $matrixPath $oldFail $newFail 'matrix registry rejection outcomes'
$oldRevision="transactional_proof_revision=2"
$newRevision="transactional_proof_revision=3"
Replace-Once $matrixPath $oldRevision $newRevision 'matrix proof revision'

# 4. Knowledge validator understands requirement overrides and proves state-machine/oracle consistency.
$oldRead="`$invariants=Read-Json 'tests/knowledge/invariants/multi-hub.json'`n`$model=Read-Json 'tests/knowledge/entry-reachability.json'"
$newRead=$oldRead+"`n`$stateMachine=Read-Json 'tests/knowledge/state-machines/multi-hub.json'"
Replace-Once $validatorPath $oldRead $newRead 'validator state machine load'
$oldStates="foreach(`$requiredState in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT'))"
$newStates="foreach(`$requiredState in @('REGISTRY_DOCUMENT_INVALID','REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT'))"
Replace-Once $validatorPath $oldStates $newStates 'validator required registry document state'
$oldReqSet="`$requirementIds=New-Set;`$pairs=New-Set"
$newReqSet="`$requirementIds=New-Set;`$pairs=New-Set;`$pairModes=@{}"
Replace-Once $validatorPath $oldReqSet $newReqSet 'validator pair mode map'
$oldReqHeader="    `$rid=[string]`$req.id;Add-Unique `$requirementIds `$rid 'coverage requirement'`n    if(@(`$req.states).Count-eq0-or@(`$req.actions).Count-eq0){Fail(`$rid+' must contain states and actions.')}"
$newReqHeader="    `$rid=[string]`$req.id;Add-Unique `$requirementIds `$rid 'coverage requirement'`n    if(`$null-ne`$req.PSObject.Properties['expected_mode']){`$reqMode=[string]`$req.expected_mode;if(@('list_success','target_success','global_success','diagnostic_reached','fail_closed','registry_init_rejected_after_dispatch','registry_document_rejected_after_dispatch') -cnotcontains `$reqMode){Fail(`$rid+' expected_mode override is unsupported: '+`$reqMode)}}`n    if(@(`$req.states).Count-eq0-or@(`$req.actions).Count-eq0){Fail(`$rid+' must contain states and actions.')}"
Replace-Once $validatorPath $oldReqHeader $newReqHeader 'validator requirement expected_mode override'
$oldPair="            if(-not`$pairs.Add(`$sid+'|'+`$aid)){Fail('Duplicate generated state/action pair: '+`$sid+'|'+`$aid)}"
$newPair="            `$key=`$sid+'|'+`$aid`n            if(-not`$pairs.Add(`$key)){Fail('Duplicate generated state/action pair: '+`$key)}`n            `$mode=[string]`$actionById[`$aid].expected_mode`n            if(`$null-ne`$req.PSObject.Properties['expected_mode']-and-not[string]::IsNullOrWhiteSpace([string]`$req.expected_mode)){`$mode=[string]`$req.expected_mode}`n            `$pairModes[`$key]=`$mode"
Replace-Once $validatorPath $oldPair $newPair 'validator pair expected mode capture'
$oldBoundary="foreach(`$sid in @('REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){`n    foreach(`$aid in @('UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','InitializeInstanceRegistry')){if(-not`$pairs.Contains(`$sid+'|'+`$aid)){Fail('CURRENT-degraded boundary coverage omitted '+`$sid+'|'+`$aid)}}`n}`nif(`$pairs.Count-lt75){Fail('Entry-reachability cross-product is unexpectedly small: '+`$pairs.Count)}"
$newBoundary="foreach(`$sid in @('REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){`n    foreach(`$aid in @('UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','InitializeInstanceRegistry')){if(-not`$pairs.Contains(`$sid+'|'+`$aid)){Fail('CURRENT-degraded boundary coverage omitted '+`$sid+'|'+`$aid)}}`n}`nforeach(`$sid in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT')){if(-not`$pairs.Contains(`$sid+'|InitializeInstanceRegistry')){Fail('Invalid-active registry initialization coverage omitted '+`$sid+'|InitializeInstanceRegistry')}}`nforeach(`$aid in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','UpdateHub','UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','InitializeInstanceRegistry')){if(-not`$pairs.Contains('REGISTRY_DOCUMENT_INVALID|'+`$aid)){Fail('REGISTRY_DOCUMENT_INVALID coverage omitted '+`$aid)}}`nif(`$pairs.Count-lt96){Fail('Entry-reachability cross-product is unexpectedly small: '+`$pairs.Count)}"
Replace-Once $validatorPath $oldBoundary $newBoundary 'validator strengthened coverage floor'
$oldFreeze="if(-not([string]`$model.freeze_rule).Contains('newer valid disposable Manager package')){Fail 'Freeze rule must require a real UpdateManager installation/restart.'}"
$newFreeze=$oldFreeze+"`nif(-not([string]`$model.freeze_rule).Contains('Entry-oracle InitializeInstanceRegistry expectations')){Fail 'Freeze rule must require state-machine/oracle InitializeInstanceRegistry consistency.'}"
Replace-Once $validatorPath $oldFreeze $newFreeze 'validator state-machine consistency freeze rule'
$marker="Write-Host 'Manager entry-reachability knowledge: PASS' -ForegroundColor Green"
$consistency=@'
function Resolve-StateMachineOutcome([string]$State,[string]$Operation){
    $matches=@($stateMachine.rules|Where-Object{[string]$_.operation-ceq$Operation-and(@($_.states|ForEach-Object{[string]$_}) -ccontains $State-or@($_.states|ForEach-Object{[string]$_}) -ccontains '*')})
    if($matches.Count-eq0){Fail('State machine has no rule for '+$State+' x '+$Operation)}
    $max=($matches|Measure-Object -Property priority -Maximum).Maximum
    $top=@($matches|Where-Object{[int]$_.priority-eq[int]$max})
    if($top.Count-ne1){Fail('State machine rule resolution is ambiguous for '+$State+' x '+$Operation+' at priority '+$max)}
    return [string]$top[0].outcome
}
$initSuccessOutcomes=@('no_op_after_full_validation','existing_registry_valid_without_old_current_dependency','reconcile_identity_bound_global_inputs_then_report_initialized')
foreach($sid in @($stateIds)){
    $key=$sid+'|InitializeInstanceRegistry'
    if(-not$pairs.Contains($key)){continue}
    $mode=[string]$pairModes[$key];$outcome=Resolve-StateMachineOutcome $sid 'InitializeRegistry'
    if($mode-ceq'global_success'){
        if($initSuccessOutcomes-cnotcontains$outcome){Fail('InitializeInstanceRegistry entry oracle expects success but state machine resolves '+$sid+' to '+$outcome)}
    }elseif($mode-ceq'registry_init_rejected_after_dispatch'){
        if($outcome-cne'reject_fail_closed'){Fail('InitializeInstanceRegistry entry oracle expects rejection but state machine resolves '+$sid+' to '+$outcome)}
    }else{Fail('Covered InitializeInstanceRegistry pair has unsupported cross-model mode '+$mode+' for '+$sid)}
}
foreach($sid in @('REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_INSTANCE')){if((Resolve-StateMachineOutcome $sid 'InitializeRegistry')-cne'no_op_after_full_validation'){Fail('State machine lost intended existing-registry idempotence for '+$sid)}}
if((Resolve-StateMachineOutcome 'REGISTRY_PENDING_GLOBAL' 'InitializeRegistry')-cne'reconcile_identity_bound_global_inputs_then_report_initialized'){Fail 'State machine lost explicit stranded-global-input InitializeRegistry recovery semantics.'}
'@
Replace-Once $validatorPath $marker ($consistency+"`n"+$marker) 'validator state-machine/oracle consistency implementation'

# 5. Governance metadata must describe the strengthened pre-freeze contract, not the superseded 75-scenario floor.
$prefreeze=Get-Content -LiteralPath $prefreezePath -Raw -Encoding UTF8|ConvertFrom-Json
$sequence=New-Object System.Collections.ArrayList
foreach($item in @($prefreeze.required_sequence)){
    [void]$sequence.Add([string]$item)
    if([string]$item-ceq'entry_reachability_matrix_pass'-and@($prefreeze.required_sequence|ForEach-Object{[string]$_}) -cnotcontains 'state_machine_entry_oracle_consistency_pass'){[void]$sequence.Add('state_machine_entry_oracle_consistency_pass')}
}
$prefreeze.required_sequence=@($sequence)
Add-JsonPropertyIfMissing $prefreeze.evidence_required 'state_machine_entry_oracle_consistency_pass' $true
Write-Json $prefreezePath $prefreeze 30

$devState=Get-Content -LiteralPath $devStatePath -Raw -Encoding UTF8|ConvertFrom-Json
$succ=$devState.qualification.successor_4_17_13
$succ.status='materialized_unqualified_development_prefreeze_knowledge_hardening'
$succ.process_entry_green_proof='R5 requires 96-scenario exact-entry PASS plus 29-mode completeness and state-machine/oracle consistency guards'
$reqs=@($succ.required_before_freeze|ForEach-Object{[string]$_});if($reqs-cnotcontains'state_machine_entry_oracle_consistency_pass'){$succ.required_before_freeze=@($reqs)+@('state_machine_entry_oracle_consistency_pass')}
$devState.next_exact_goal.description='Obtain exact-head Development Validation with 29-mode entry-policy completeness, 96-scenario process-entry PASS and state-machine/oracle consistency, then full-successor Risk/Defect Gate and semantic pre-freeze review.'
Write-Json $devStatePath $devState 40

$prov=Get-Content -LiteralPath $provenancePath -Raw -Encoding UTF8|ConvertFrom-Json
$prov.candidate_identity.validated_development_parent=$ExpectedBase.ToLowerInvariant()
$prov.qualification_evidence.development_4_17_13.entry_reachability_scenarios=96
Add-JsonPropertyIfMissing $prov.qualification_evidence.development_4_17_13 'state_machine_entry_oracle_consistency' 'required_before_freeze'
Write-Json $provenancePath $prov 50

Parse-File $validatorPath;Parse-File $matrixPath
$null=Invoke-Child $validatorPath @('-RepositoryRoot',$RepositoryRoot)
$matrixOut=Join-Path $EvidenceRoot 'ENTRY_REACHABILITY_RESULT.json'
$null=Invoke-Child $matrixPath @('-RepositoryRoot',$RepositoryRoot,'-OutputPath',$matrixOut)
$report=Get-Content -LiteralPath $matrixOut -Raw -Encoding UTF8|ConvertFrom-Json
if(-not[bool]$report.pass-or[int]$report.scenario_count-ne96-or[int]$report.executed_count-ne96){Fail('Expected exact 96/96 matrix PASS; count='+[string]$report.scenario_count+' executed='+[string]$report.executed_count)}
$docRows=@($report.scenarios|Where-Object{[string]$_.state-ceq'REGISTRY_DOCUMENT_INVALID'})
if($docRows.Count-ne18-or@($docRows|Where-Object{-not[bool]$_.pass}).Count-ne0){Fail 'REGISTRY_DOCUMENT_INVALID must have exact 18/18 PASS.'}
$initInvalid=@($report.scenarios|Where-Object{[string]$_.action-ceq'InitializeInstanceRegistry'-and@('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_DOCUMENT_INVALID') -ccontains [string]$_.state})
if($initInvalid.Count-ne4-or@($initInvalid|Where-Object{-not[bool]$_.pass-or[string]$_.expected_mode-cne'registry_init_rejected_after_dispatch'}).Count-ne0){Fail 'Invalid-registry InitializeInstanceRegistry operation-specific rejection proof is incomplete.'}
$currentInitRows=@($report.scenarios|Where-Object{[string]$_.action-ceq'InitializeInstanceRegistry'-and@('REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT') -ccontains [string]$_.state})
if($currentInitRows.Count-ne2-or@($currentInitRows|Where-Object{-not[bool]$_.pass-or[string]$_.expected_mode-cne'global_success'-or-not([string]$_.detail).Contains('without old CURRENT dependency')}).Count-ne0){Fail 'CURRENT-degraded InitializeInstanceRegistry intended success proof is incomplete.'}

$changed=@(& git.exe -C $RepositoryRoot diff --name-only)
$expected=@('MANAGER_DEVELOPMENT_STATE.json','PUBLIC_PROVENANCE.json','tests/knowledge/entry-reachability.json','tests/knowledge/prefreeze-semantic-review.json','tests/knowledge/state-machines/multi-hub.json','tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Test-ManagerEntryReachabilityKnowledge.ps1')|Sort-Object
if(([string]::Join('|',@($changed|Sort-Object)))-cne([string]::Join('|',$expected))){Fail('Unexpected materialized patch set: '+($changed-join', '))}
if(@(& git.exe -C $RepositoryRoot diff --name-only -- manager).Count-ne0){Fail 'Manager product bytes changed in prefreeze knowledge convergence.'}
Write-Host 'Manager 4.17.13 prefreeze knowledge convergence R5: PASS' -ForegroundColor Green
