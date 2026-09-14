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
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path $env:RUNNER_TEMP 'manager-41713-prefreeze-knowledge-r7'}
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null
function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8)}
function Write-Json([string]$Path,$Object,[int]$Depth=70){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth $Depth).Replace("`r`n","`n"))+"`n")}
function Replace-Once([string]$Path,[string]$Old,[string]$New,[string]$Label){$s=[IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8);$count=[regex]::Matches($s,[regex]::Escape($Old)).Count;if($count-ne1){Fail($Label+' count='+$count)};Write-Utf8 $Path ($s.Replace($Old,$New))}
function Parse-File([string]$Path){$t=$null;$e=$null;[void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e);if(@($e).Count){Fail('Parser failed: '+$Path+' :: '+([string]::Join(' | ',@($e|ForEach-Object{$_.Message}))))}}
function Invoke-Child([string]$Script,[string[]]$Arguments){$exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference;try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old};foreach($line in @($out)){Write-Host $line};if($code-ne0){Fail('Child failed: '+$Script+' exit='+$code)};return [pscustomobject]@{ExitCode=$code;Text=[string]::Join("`n",@($out))}}
function Add-JsonPropertyIfMissing($Object,[string]$Name,$Value){if($null-eq$Object.PSObject.Properties[$Name]){$Object|Add-Member -NotePropertyName $Name -NotePropertyValue $Value}else{$Object.$Name=$Value}}

$head=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($head-cne$ExpectedBase.ToLowerInvariant()){Fail('Unexpected target HEAD: '+$head+' expected='+$ExpectedBase)}
if(@(& git.exe -C $RepositoryRoot status --porcelain).Count-ne0){Fail 'Target checkout is not clean.'}

$entryPath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability.json'
$stateMachinePath=Join-Path $RepositoryRoot 'tests\knowledge\state-machines\multi-hub.json'
$prefreezePath=Join-Path $RepositoryRoot 'tests\knowledge\prefreeze-semantic-review.json'
$riskPath=Join-Path $RepositoryRoot 'tests\knowledge\risk-map.json'
$entryValidatorPath=Join-Path $RepositoryRoot 'tools\Test-ManagerEntryReachabilityKnowledge.ps1'
$engineeringPath=Join-Path $RepositoryRoot 'tools\Test-ManagerEngineeringKnowledge.ps1'
$matrixPath=Join-Path $RepositoryRoot 'tools\Invoke-ManagerEntryReachabilityMatrix.ps1'
$entryWorkflowPath=Join-Path $RepositoryRoot '.github\workflows\entry-reachability-validation.yml'
$devStatePath=Join-Path $RepositoryRoot 'MANAGER_DEVELOPMENT_STATE.json'
$provenancePath=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json'
foreach($p in @($entryPath,$stateMachinePath,$prefreezePath,$riskPath,$entryValidatorPath,$engineeringPath,$matrixPath,$entryWorkflowPath,$devStatePath,$provenancePath)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Required R7 source missing: '+$p)}}

# Canonical InitializeRegistry semantics: existing valid registry is independent of old CURRENT;
# pending global Hub input uses InitializeRegistry as its explicit identity-bound reconciliation path.
$sm=Get-Content -LiteralPath $stateMachinePath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$sm.schema-cne'keelaryn.manager-state-machine.v1'){Fail 'Unexpected state-machine schema.'}
$idempotent=@($sm.rules|Where-Object{[string]$_.id-ceq'R-REGISTRY-INIT-IDEMPOTENT'})
if($idempotent.Count-ne1){Fail('R-REGISTRY-INIT-IDEMPOTENT count='+$idempotent.Count)}
$idempotent[0].states=@('REGISTRY_HEALTHY','REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_INSTANCE')
$idempotent[0].reason='An existing structurally valid registry may report initialized when active selection resolves; inactive-Hub degradation or instance-owned pending input does not invalidate registry initialization state.'
if(@($sm.rules|Where-Object{[string]$_.id-ceq'R-CURRENT-DEGRADED-INIT'}).Count-ne0){Fail 'R-CURRENT-DEGRADED-INIT already exists.'}
if(@($sm.rules|Where-Object{[string]$_.id-ceq'R-REGISTRY-GLOBAL-PENDING-INIT'}).Count-ne0){Fail 'R-REGISTRY-GLOBAL-PENDING-INIT already exists.'}
$sm.rules=@($sm.rules)+@(
    [pscustomobject][ordered]@{id='R-CURRENT-DEGRADED-INIT';states=@('REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT');operation='InitializeRegistry';priority=210;outcome='existing_registry_valid_without_old_current_dependency';invariants=@('MH-REGISTRY-001','MH-RECOVERY-001');reason='Existing-registry initialization validates registry and active selection but does not consume old active CURRENT; CURRENT recovery remains a separate lifecycle operation.'},
    [pscustomobject][ordered]@{id='R-REGISTRY-GLOBAL-PENDING-INIT';states=@('REGISTRY_PENDING_GLOBAL');operation='InitializeRegistry';priority=180;outcome='reconcile_identity_bound_global_inputs_then_report_initialized';invariants=@('MH-INBOX-001','MH-REGISTRY-001','MH-REACHABILITY-001');reason='InitializeRegistry is the explicit recovery path for identity-bound Hub inputs stranded in the global Manager inbox after registry activation.'}
)
Write-Json $stateMachinePath $sm 70

# Real-entry model: retain the proven 75 matrix and add invalid registry plus every newly explicit existing-registry Initialize semantic.
$model=Get-Content -LiteralPath $entryPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$model.schema-cne'keelaryn.manager-entry-reachability.v2'){Fail 'Unexpected entry-reachability schema.'}
$newStates=@(
    [pscustomobject][ordered]@{id='REGISTRY_DOCUMENT_INVALID';fixture='registry_document_invalid';description='instances.json exists but the authoritative registry document is malformed and unsafe to resolve.'},
    [pscustomobject][ordered]@{id='REGISTRY_HEALTHY';fixture='registry_healthy';description='Registry document, active selection, active Hub and CURRENT are healthy.'},
    [pscustomobject][ordered]@{id='REGISTRY_INACTIVE_HUB_MISSING';fixture='inactive_hub_missing';description='Active Hub is healthy while an inactive registered Hub path is missing.'},
    [pscustomobject][ordered]@{id='REGISTRY_INACTIVE_HUB_CORRUPT';fixture='inactive_hub_corrupt';description='Active Hub is healthy while an inactive registered Hub is structurally corrupt.'},
    [pscustomobject][ordered]@{id='REGISTRY_PENDING_GLOBAL';fixture='registry_pending_global';description='Registry is healthy while a valid identity-bound Hub input is stranded in the global Manager inbox.'},
    [pscustomobject][ordered]@{id='REGISTRY_PENDING_INSTANCE';fixture='registry_pending_instance';description='Registry is healthy while a valid Hub input is already pending in the active per-instance inbox.'}
)
foreach($s in $newStates){if(@($model.states|Where-Object{[string]$_.id-ceq[string]$s.id}).Count-ne0){Fail('Entry state already exists: '+[string]$s.id)}}
$model.states=@($model.states)+@($newStates)
$newReqs=@(
    [pscustomobject][ordered]@{id='CR-REGISTRY-INIT-INVALID-ACTIVE';states=@('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT');actions=@('InitializeInstanceRegistry');expected_mode='registry_init_rejected_after_dispatch'},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-GLOBAL';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout')},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-DOCTOR';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('Doctor')},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-RECOVERY';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('ListInstances','SwitchInstance','BindInstance');expected_mode='registry_document_rejected_after_dispatch'},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-INIT';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('InitializeInstanceRegistry');expected_mode='registry_init_rejected_after_dispatch'},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-BOUND';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('UpdateHub','UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport')},
    [pscustomobject][ordered]@{id='CR-REGISTRY-INIT-VALID-EXISTING';states=@('REGISTRY_HEALTHY','REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_INSTANCE');actions=@('InitializeInstanceRegistry');expected_mode='global_success'},
    [pscustomobject][ordered]@{id='CR-REGISTRY-INIT-PENDING-GLOBAL';states=@('REGISTRY_PENDING_GLOBAL');actions=@('InitializeInstanceRegistry');expected_mode='registry_init_reconciles_global_input'}
)
foreach($r in $newReqs){if(@($model.coverage_requirements|Where-Object{[string]$_.id-ceq[string]$r.id}).Count-ne0){Fail('Coverage requirement already exists: '+[string]$r.id)}}
$model.coverage_requirements=@($model.coverage_requirements)+@($newReqs)
$freezeExtra=' InitializeInstanceRegistry invalid-active coverage must prove operation-specific rejection after real process-entry dispatch. REGISTRY_DOCUMENT_INVALID must cover every modeled entry action; List/Switch/Bind must prove action-level registry reparsing while unsafe rows never become recovery targets. Existing-registry Initialize semantics for healthy, inactive-degraded, CURRENT-degraded, pending-instance and pending-global states must execute through real process entry; pending-global must prove identity-bound transfer into the registered per-instance inbox. Rejected and non-target scenarios must preserve authoritative Hub lifecycle state unless the modeled operation explicitly performs the pending-global inbox handoff. Entry-oracle InitializeInstanceRegistry expectations must resolve consistently with the canonical multi-Hub state machine.'
if(-not([string]$model.freeze_rule).Contains('pending-global must prove identity-bound transfer')){$model.freeze_rule=([string]$model.freeze_rule)+$freezeExtra}
Write-Json $entryPath $model 60

# Matrix: requirement overrides, new fixtures, lifecycle immutability, action-level rejection and failure-safe evidence.
$oldGenerator="            `$ordinal++;`$sid=[string]`$sid0;`$aid=[string]`$aid0`n            [void]`$scenarioSpecs.Add([pscustomobject]@{Id=('ER-{0:D3}' -f `$ordinal);Requirement=[string]`$req.id;State=`$sid;Action=`$aid;Mode=[string]`$actionById[`$aid].expected_mode})"
$newGenerator="            `$ordinal++;`$sid=[string]`$sid0;`$aid=[string]`$aid0`n            `$mode=[string]`$actionById[`$aid].expected_mode`n            if(`$null-ne`$req.PSObject.Properties['expected_mode']-and-not[string]::IsNullOrWhiteSpace([string]`$req.expected_mode)){`$mode=[string]`$req.expected_mode}`n            [void]`$scenarioSpecs.Add([pscustomobject]@{Id=('ER-{0:D3}' -f `$ordinal);Requirement=[string]`$req.id;State=`$sid;Action=`$aid;Mode=`$mode})"
Replace-Once $matrixPath $oldGenerator $newGenerator 'matrix requirement expected_mode override'
$oldResultInit="`$results=New-Object System.Collections.ArrayList;`$version='unknown';`$harnessError=`$null"
$newResultInit="`$results=New-Object System.Collections.ArrayList;`$version='unknown';`$harnessError=`$null;`$successor=`$null"
Replace-Once $matrixPath $oldResultInit $newResultInit 'matrix safe successor initialization'
$oldStatePaths="    `$stateRoot=Join-Path `$managerRoot 'state';`$alphaCurrent=Join-Path `$stateRoot ('instances\\'+`$alphaId+'\\baseline\\Keelaryn__Hub_CURRENT.zip');`$legacyCurrent=Join-Path `$stateRoot 'baseline\\Keelaryn__Hub_CURRENT.zip';`$activeFile=Join-Path `$stateRoot 'active_instance.json'"
$newStatePaths="    `$stateRoot=Join-Path `$managerRoot 'state';`$alphaCurrent=Join-Path `$stateRoot ('instances\\'+`$alphaId+'\\baseline\\Keelaryn__Hub_CURRENT.zip');`$legacyCurrent=Join-Path `$stateRoot 'baseline\\Keelaryn__Hub_CURRENT.zip';`$activeFile=Join-Path `$stateRoot 'active_instance.json'`n    `$globalInbox=Join-Path `$stateRoot 'inbox';`$alphaInbox=Join-Path `$stateRoot ('instances\\'+`$alphaId+'\\inbox')"
Replace-Once $matrixPath $oldStatePaths $newStatePaths 'matrix pending-input state paths'
$oldFixture="        switch(`$Fixture){`n            'active_metadata_invalid' {Write-Utf8 `$activeFile '{ not-json'}"
$newFixture="        `$script:ScenarioPendingGlobalSource=`$null;`$script:ScenarioPendingGlobalTarget=`$null;`$script:ScenarioPendingGlobalSha=`$null`n        switch(`$Fixture){`n            'registry_document_invalid' {Write-Utf8 (Join-Path `$stateRoot 'instances.json') '{ not-json'}`n            'registry_healthy' {}`n            'inactive_hub_missing' {Remove-Item -LiteralPath `$betaPath -Recurse -Force}`n            'inactive_hub_corrupt' {`$stateDoc=Join-Path `$betaPath '_System\\STATE.md';if(Test-Path -LiteralPath `$stateDoc){Remove-Item -LiteralPath `$stateDoc -Force}else{Fail('Beta structural marker missing before corruption fixture: '+`$stateDoc)}}`n            'registry_pending_global' {`$name='Keelaryn__Hub_APPROVED_entry-reachability.zip';`$dst=Join-Path `$globalInbox `$name;Copy-Item -LiteralPath `$alphaCurrent -Destination `$dst -Force;`$script:ScenarioPendingGlobalSource=`$dst;`$script:ScenarioPendingGlobalTarget=Join-Path `$alphaInbox `$name;`$script:ScenarioPendingGlobalSha=(Get-FileHash -LiteralPath `$dst -Algorithm SHA256).Hash.ToLowerInvariant()}`n            'registry_pending_instance' {`$name='Keelaryn__Hub_APPROVED_entry-reachability.zip';Copy-Item -LiteralPath `$alphaCurrent -Destination (Join-Path `$alphaInbox `$name) -Force}`n            'active_metadata_invalid' {Write-Utf8 `$activeFile '{ not-json'}"
Replace-Once $matrixPath $oldFixture $newFixture 'matrix expanded existing-registry fixtures'
$oldCapture="            `$alphaBefore=Get-TreeDigest `$alphaPath;`$betaBefore=Get-TreeDigest `$betaPath;`$betaRelocatedBefore=Get-TreeDigest `$betaRelocatedPath`n            `$r=Invoke-Runtime `$runtime (Get-ActionArguments `$spec.Action);`$exitCode=`$r.ExitCode`n            `$hubsUnchanged=((Get-TreeDigest `$alphaPath)-ceq`$alphaBefore-and(Get-TreeDigest `$betaPath)-ceq`$betaBefore-and(Get-TreeDigest `$betaRelocatedPath)-ceq`$betaRelocatedBefore)"
$newCapture="            `$alphaBefore=Get-TreeDigest `$alphaPath;`$betaBefore=Get-TreeDigest `$betaPath;`$betaRelocatedBefore=Get-TreeDigest `$betaRelocatedPath`n            `$registryControl=Join-Path `$stateRoot 'instances.json'`n            `$registryBefore=if(Test-Path -LiteralPath `$registryControl -PathType Leaf){(Get-FileHash -LiteralPath `$registryControl -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$activeBefore=if(Test-Path -LiteralPath `$activeFile -PathType Leaf){(Get-FileHash -LiteralPath `$activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$instancesStatePath=Join-Path `$stateRoot 'instances';`$compatBaselinePath=Join-Path `$stateRoot 'baseline'`n            `$instancesStateBefore=Get-TreeDigest `$instancesStatePath;`$compatBaselineBefore=Get-TreeDigest `$compatBaselinePath`n            `$r=Invoke-Runtime `$runtime (Get-ActionArguments `$spec.Action);`$exitCode=`$r.ExitCode`n            `$hubsUnchanged=((Get-TreeDigest `$alphaPath)-ceq`$alphaBefore-and(Get-TreeDigest `$betaPath)-ceq`$betaBefore-and(Get-TreeDigest `$betaRelocatedPath)-ceq`$betaRelocatedBefore)`n            `$registryAfter=if(Test-Path -LiteralPath `$registryControl -PathType Leaf){(Get-FileHash -LiteralPath `$registryControl -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$activeAfter=if(Test-Path -LiteralPath `$activeFile -PathType Leaf){(Get-FileHash -LiteralPath `$activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$controlStateUnchanged=(`$registryAfter-ceq`$registryBefore-and`$activeAfter-ceq`$activeBefore)`n            `$instancesStateAfter=Get-TreeDigest `$instancesStatePath;`$compatBaselineAfter=Get-TreeDigest `$compatBaselinePath`n            `$lifecycleStateUnchanged=(`$controlStateUnchanged-and`$instancesStateAfter-ceq`$instancesStateBefore-and`$compatBaselineAfter-ceq`$compatBaselineBefore)"
Replace-Once $matrixPath $oldCapture $newCapture 'matrix lifecycle-state capture'
Replace-Once $matrixPath "'list_success' {`$pass=(`$r.ExitCode-eq0-and`$r.Text.Contains('Registered Hubs:')-and`$hubsUnchanged);" "'list_success' {`$pass=(`$r.ExitCode-eq0-and`$r.Text.Contains('Registered Hubs:')-and`$hubsUnchanged-and`$lifecycleStateUnchanged);" 'list lifecycle immutability'
Replace-Once $matrixPath "`$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$installed-ceq[string]`$successor.Version-and`$restartObserved-and`$packageConsumed)" "`$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$lifecycleStateUnchanged-and`$installed-ceq[string]`$successor.Version-and`$restartObserved-and`$packageConsumed)" 'UpdateManager lifecycle immutability'
$oldGeneric="                    }else{`n                        `$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged);`$detail=if(`$pass){'Manager-global action completed independently of degraded Hub context'}else{'Manager-global action blocked/failed or mutated Hub bytes: '+`$r.Text}`n                    }"
$newGeneric="                    }elseif([string]`$spec.Action-ceq'InitializeInstanceRegistry'){`n                        `$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$lifecycleStateUnchanged-and`$r.Text.Contains('Multi-Hub registry is already initialized and valid.'))`n                        `$detail=if(`$pass){'existing-registry initialization remained reachable and preserved Hub lifecycle state'}else{'existing-registry initialization did not reach intended idempotent/recovery success or mutated lifecycle state: '+`$r.Text}`n                    }else{`n                        `$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$lifecycleStateUnchanged);`$detail=if(`$pass){'Manager-global action completed independently of degraded Hub context without Hub lifecycle mutation'}else{'Manager-global action blocked/failed or mutated Hub lifecycle state: '+`$r.Text}`n                    }"
Replace-Once $matrixPath $oldGeneric $newGeneric 'matrix global lifecycle immutability'
$oldDiagnostic="                'diagnostic_reached' {`$pass=(`$r.Text.Contains('Keelaryn Doctor - Manager')-and`$hubsUnchanged);`$detail=if(`$pass){'Doctor reached diagnostic body and left Hub bytes unchanged; exit='+`$r.ExitCode}else{'Doctor was blocked before diagnostic body or mutated Hub bytes: '+`$r.Text}}`n                'fail_closed' {`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged);`$detail=if(`$pass){'Hub/context-bound action failed closed without Hub mutation'}else{'expected fail-closed outcome not observed: '+`$r.Text}}"
$newDiagnostic="                'diagnostic_reached' {`$pass=(`$r.Text.Contains('Keelaryn Doctor - Manager')-and`$hubsUnchanged-and`$lifecycleStateUnchanged);`$detail=if(`$pass){'Doctor reached diagnostic body and preserved Hub lifecycle state; exit='+`$r.ExitCode}else{'Doctor was blocked before diagnostic body or mutated Hub lifecycle state: '+`$r.Text}}`n                'registry_document_rejected_after_dispatch' {`$startupBlocked=`$r.Text.Contains('Invalid Keelaryn multi-Hub registry:');`$operationReached=`$r.Text.Contains('Manager instance registry JSON is invalid:');`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$lifecycleStateUnchanged-and-not`$startupBlocked-and`$operationReached);`$detail=if(`$pass){'unsafe registry passed startup allow-dispatch, reached action-level parsing, and was rejected without lifecycle mutation'}else{'action-level unsafe-registry rejection was not proven, startup blocked first, or state mutated: '+`$r.Text}}`n                'registry_init_rejected_after_dispatch' {`$reached=`$r.Text.Contains('Existing multi-Hub registry is invalid:');`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$lifecycleStateUnchanged-and`$reached);`$detail=if(`$pass){'InitializeInstanceRegistry reached its existing-registry validator and rejected invalid authoritative registry state without mutation'}else{'registry initialization was blocked before operation-specific validation, succeeded unexpectedly, or mutated state: '+`$r.Text}}`n                'registry_init_reconciles_global_input' {`$sourceConsumed=(`$script:ScenarioPendingGlobalSource-and-not(Test-Path -LiteralPath `$script:ScenarioPendingGlobalSource -PathType Leaf));`$targetOk=`$false;if(`$script:ScenarioPendingGlobalTarget-and(Test-Path -LiteralPath `$script:ScenarioPendingGlobalTarget -PathType Leaf)){`$targetOk=((Get-FileHash -LiteralPath `$script:ScenarioPendingGlobalTarget -Algorithm SHA256).Hash.ToLowerInvariant()-ceq[string]`$script:ScenarioPendingGlobalSha)};`$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$controlStateUnchanged-and`$compatBaselineAfter-ceq`$compatBaselineBefore-and`$sourceConsumed-and`$targetOk-and`$r.Text.Contains('Reconciled 1 identity-bound Hub input(s)'));`$detail=if(`$pass){'InitializeInstanceRegistry moved the validated identity-bound global input into the active registered per-instance inbox while preserving registry/active/baseline state'}else{'pending-global Initialize reconciliation proof failed: '+`$r.Text}}`n                'fail_closed' {`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$lifecycleStateUnchanged);`$detail=if(`$pass){'Hub/context-bound action failed closed without Hub lifecycle mutation'}else{'expected fail-closed lifecycle outcome not observed: '+`$r.Text}}"
Replace-Once $matrixPath $oldDiagnostic $newDiagnostic 'matrix diagnostic/recovery outcome hardening'
Replace-Once $matrixPath 'transactional_proof_revision=2' 'transactional_proof_revision=4' 'matrix proof revision'
$oldReportStart="`$failed=@(`$results|Where-Object{-not[bool]`$_.pass})`n`$report=[ordered]@{"
$newReportStart="`$failed=@(`$results|Where-Object{-not[bool]`$_.pass})`n`$syntheticSuccessorVersion=if(`$null-ne`$successor){[string]`$successor.Version}else{''}`n`$report=[ordered]@{"
Replace-Once $matrixPath $oldReportStart $newReportStart 'matrix failure-safe report initialization'
Replace-Once $matrixPath 'synthetic_successor_version=[string]$successor.Version' 'synthetic_successor_version=$syntheticSuccessorVersion' 'matrix safe successor report field'

# Entry validator: requirement overrides, 101-pair floor and state-machine/oracle consistency.
$oldRead="`$invariants=Read-Json 'tests/knowledge/invariants/multi-hub.json'`n`$model=Read-Json 'tests/knowledge/entry-reachability.json'"
$newRead=$oldRead+"`n`$stateMachine=Read-Json 'tests/knowledge/state-machines/multi-hub.json'"
Replace-Once $entryValidatorPath $oldRead $newRead 'entry validator state-machine load'
$oldStates="foreach(`$requiredState in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT'))"
$newStates="foreach(`$requiredState in @('REGISTRY_DOCUMENT_INVALID','REGISTRY_HEALTHY','REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_GLOBAL','REGISTRY_PENDING_INSTANCE','REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT'))"
Replace-Once $entryValidatorPath $oldStates $newStates 'entry validator required states'
$oldReqSet="`$requirementIds=New-Set;`$pairs=New-Set"
$newReqSet="`$requirementIds=New-Set;`$pairs=New-Set;`$pairModes=@{}"
Replace-Once $entryValidatorPath $oldReqSet $newReqSet 'entry validator pair modes'
$oldReqHeader="    `$rid=[string]`$req.id;Add-Unique `$requirementIds `$rid 'coverage requirement'`n    if(@(`$req.states).Count-eq0-or@(`$req.actions).Count-eq0){Fail(`$rid+' must contain states and actions.')}"
$newReqHeader="    `$rid=[string]`$req.id;Add-Unique `$requirementIds `$rid 'coverage requirement'`n    if(`$null-ne`$req.PSObject.Properties['expected_mode']){`$reqMode=[string]`$req.expected_mode;if(@('list_success','target_success','global_success','diagnostic_reached','fail_closed','registry_init_rejected_after_dispatch','registry_document_rejected_after_dispatch','registry_init_reconciles_global_input') -cnotcontains `$reqMode){Fail(`$rid+' expected_mode override is unsupported: '+`$reqMode)}}`n    if(@(`$req.states).Count-eq0-or@(`$req.actions).Count-eq0){Fail(`$rid+' must contain states and actions.')}"
Replace-Once $entryValidatorPath $oldReqHeader $newReqHeader 'entry validator expected mode override'
$oldPair="            if(-not`$pairs.Add(`$sid+'|'+`$aid)){Fail('Duplicate generated state/action pair: '+`$sid+'|'+`$aid)}"
$newPair="            `$key=`$sid+'|'+`$aid`n            if(-not`$pairs.Add(`$key)){Fail('Duplicate generated state/action pair: '+`$key)}`n            `$mode=[string]`$actionById[`$aid].expected_mode`n            if(`$null-ne`$req.PSObject.Properties['expected_mode']-and-not[string]::IsNullOrWhiteSpace([string]`$req.expected_mode)){`$mode=[string]`$req.expected_mode}`n            `$pairModes[`$key]=`$mode"
Replace-Once $entryValidatorPath $oldPair $newPair 'entry validator pair mode capture'
$oldBoundary="foreach(`$sid in @('REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){`n    foreach(`$aid in @('UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','InitializeInstanceRegistry')){if(-not`$pairs.Contains(`$sid+'|'+`$aid)){Fail('CURRENT-degraded boundary coverage omitted '+`$sid+'|'+`$aid)}}`n}`nif(`$pairs.Count-lt75){Fail('Entry-reachability cross-product is unexpectedly small: '+`$pairs.Count)}"
$newBoundary="foreach(`$sid in @('REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){foreach(`$aid in @('UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','InitializeInstanceRegistry')){if(-not`$pairs.Contains(`$sid+'|'+`$aid)){Fail('CURRENT-degraded boundary coverage omitted '+`$sid+'|'+`$aid)}}}`nforeach(`$sid in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT')){if(-not`$pairs.Contains(`$sid+'|InitializeInstanceRegistry')){Fail('Invalid-active registry initialization coverage omitted '+`$sid+'|InitializeInstanceRegistry')}}`nforeach(`$aid in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','UpdateHub','UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','InitializeInstanceRegistry')){if(-not`$pairs.Contains('REGISTRY_DOCUMENT_INVALID|'+`$aid)){Fail('REGISTRY_DOCUMENT_INVALID coverage omitted '+`$aid)}}`nforeach(`$sid in @('REGISTRY_HEALTHY','REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_INSTANCE','REGISTRY_PENDING_GLOBAL')){if(-not`$pairs.Contains(`$sid+'|InitializeInstanceRegistry')){Fail('Existing-registry Initialize coverage omitted '+`$sid)}}`nif(`$pairs.Count-lt101){Fail('Entry-reachability cross-product is unexpectedly small: '+`$pairs.Count)}"
Replace-Once $entryValidatorPath $oldBoundary $newBoundary 'entry validator 101-pair floor'
$oldFreeze="if(-not([string]`$model.freeze_rule).Contains('newer valid disposable Manager package')){Fail 'Freeze rule must require a real UpdateManager installation/restart.'}"
$newFreeze=$oldFreeze+"`nif(-not([string]`$model.freeze_rule).Contains('pending-global must prove identity-bound transfer')){Fail 'Freeze rule must require executable existing-registry Initialize semantics.'}"
Replace-Once $entryValidatorPath $oldFreeze $newFreeze 'entry validator strengthened freeze rule'
$marker="Write-Host 'Manager entry-reachability knowledge: PASS' -ForegroundColor Green"
$consistency=@'
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
'@
Replace-Once $entryValidatorPath $marker ($consistency+"`n"+$marker) 'entry validator state-machine consistency'

# Risk-map traceability: map every historical and new non-default state-machine rule; enforce this permanently.
$risk=Get-Content -LiteralPath $riskPath -Raw -Encoding UTF8|ConvertFrom-Json
function Add-RuleMapping([string]$SurfaceId,[string]$RuleId){$surface=@($risk.surfaces|Where-Object{[string]$_.id-ceq$SurfaceId});if($surface.Count-ne1){Fail('Risk surface count for '+$SurfaceId+' = '+$surface.Count)};$rules=@($surface[0].state_machine_rules|ForEach-Object{[string]$_});if($rules-cnotcontains$RuleId){$surface[0].state_machine_rules=@($rules)+@($RuleId)}}
foreach($rid in @('R-INACTIVE-CORRUPT-SWITCH','R-INACTIVE-MISSING-SWITCH','R-MISMATCH-SWITCH','R-NONAPPROVED-SWITCH','R-POSTCOMMIT-SWITCH','R-REGISTRY-DOCUMENT-INVALID-LIST','R-SINGLE-BIND','R-CURRENT-DEGRADED-INIT')){Add-RuleMapping 'S-RUNTIME-REGISTRY-RESOLUTION' $rid}
foreach($rid in @('R-BROKEN-ACTIVE-UPDATE-ALL-CORRUPT','R-BROKEN-ACTIVE-UPDATE-ALL-MISSING')){Add-RuleMapping 'S-RUNTIME-UPDATE-HANDOFF' $rid}
Add-RuleMapping 'S-RUNTIME-INBOX' 'R-REGISTRY-GLOBAL-PENDING-INIT'
Write-Json $riskPath $risk 70
$oldDecl="`$surfaceIds=New-IdSet`n`$surfaceById=@{}`n`$coveredInvariantIds=New-IdSet"
$newDecl="`$surfaceIds=New-IdSet`n`$surfaceById=@{}`n`$coveredInvariantIds=New-IdSet`n`$coveredRuleIds=New-IdSet"
Replace-Once $engineeringPath $oldDecl $newDecl 'engineering covered rule set'
$oldRuleLoop="    foreach(`$rid in @(`$surface.state_machine_rules)){Assert-Ref `$ruleIds ([string]`$rid) 'state-machine rule' `$sid}"
$newRuleLoop="    foreach(`$rid in @(`$surface.state_machine_rules)){Assert-Ref `$ruleIds ([string]`$rid) 'state-machine rule' `$sid;[void]`$coveredRuleIds.Add([string]`$rid)}"
Replace-Once $engineeringPath $oldRuleLoop $newRuleLoop 'engineering rule mapping capture'
$oldInvariantCoverage="foreach(`$iid in @(`$invariantIds)){if(-not`$coveredInvariantIds.Contains(`$iid)){Fail('Invariant has no risk-surface mapping: '+`$iid)}}"
$newInvariantCoverage="foreach(`$rule in @(`$machine.rules|Where-Object{[int]`$_.priority-gt0})){`$rid=[string]`$rule.id;if(-not`$coveredRuleIds.Contains(`$rid)){Fail('Non-default state-machine rule has no risk-surface mapping: '+`$rid)}}`n"+$oldInvariantCoverage
Replace-Once $engineeringPath $oldInvariantCoverage $newInvariantCoverage 'engineering complete rule mapping guard'

# Dedicated entry workflow must trigger whenever its new canonical state-machine dependency changes.
$oldWorkflow="      - 'tests/knowledge/entry-reachability.json'`n      - 'tests/knowledge/invariants/multi-hub.json'`n      - 'tools/Test-ManagerEntryReachabilityKnowledge.ps1'"
$newWorkflow="      - 'tests/knowledge/entry-reachability.json'`n      - 'tests/knowledge/invariants/multi-hub.json'`n      - 'tests/knowledge/state-machines/multi-hub.json'`n      - 'tools/Test-ManagerEntryReachabilityKnowledge.ps1'"
Replace-Once $entryWorkflowPath $oldWorkflow $newWorkflow 'entry workflow state-machine dependency'

# Governance metadata records the strengthened pre-freeze contract.
$prefreeze=Get-Content -LiteralPath $prefreezePath -Raw -Encoding UTF8|ConvertFrom-Json
$sequence=New-Object System.Collections.ArrayList
foreach($item in @($prefreeze.required_sequence)){[void]$sequence.Add([string]$item);if([string]$item-ceq'entry_reachability_matrix_pass'-and@($prefreeze.required_sequence|ForEach-Object{[string]$_}) -cnotcontains 'state_machine_entry_oracle_consistency_pass'){[void]$sequence.Add('state_machine_entry_oracle_consistency_pass')}}
$prefreeze.required_sequence=@($sequence);Add-JsonPropertyIfMissing $prefreeze.evidence_required 'state_machine_entry_oracle_consistency_pass' $true
Write-Json $prefreezePath $prefreeze 30
$devState=Get-Content -LiteralPath $devStatePath -Raw -Encoding UTF8|ConvertFrom-Json
$succ=$devState.qualification.successor_4_17_13;$succ.status='materialized_unqualified_development_prefreeze_knowledge_hardening';$succ.process_entry_green_proof='R7 requires 101-scenario exact-entry PASS plus 29-mode completeness, state-machine/oracle consistency and complete non-default risk mapping'
$reqs=@($succ.required_before_freeze|ForEach-Object{[string]$_});if($reqs-cnotcontains'state_machine_entry_oracle_consistency_pass'){$succ.required_before_freeze=@($reqs)+@('state_machine_entry_oracle_consistency_pass')}
$devState.next_exact_goal.description='Obtain exact-head Development Validation with 29-mode entry-policy completeness, 101-scenario process-entry PASS, state-machine/oracle consistency and complete non-default state-machine risk mapping; then full-successor Risk/Defect Gate and semantic pre-freeze review.'
Write-Json $devStatePath $devState 40
$prov=Get-Content -LiteralPath $provenancePath -Raw -Encoding UTF8|ConvertFrom-Json
$prov.candidate_identity.validated_development_parent=$ExpectedBase.ToLowerInvariant();$prov.qualification_evidence.development_4_17_13.entry_reachability_scenarios=101;Add-JsonPropertyIfMissing $prov.qualification_evidence.development_4_17_13 'state_machine_entry_oracle_consistency' 'required_before_freeze';Add-JsonPropertyIfMissing $prov.qualification_evidence.development_4_17_13 'nondefault_state_machine_risk_mapping' 'required_before_freeze'
Write-Json $provenancePath $prov 50

Parse-File $matrixPath;Parse-File $entryValidatorPath;Parse-File $engineeringPath
$null=Invoke-Child $entryValidatorPath @('-RepositoryRoot',$RepositoryRoot)
$null=Invoke-Child $engineeringPath @('-RepositoryRoot',$RepositoryRoot)
$entryPolicy=Join-Path $RepositoryRoot 'tools\Test-ManagerEntryPolicyCompleteness.ps1';$null=Invoke-Child $entryPolicy @('-RepositoryRoot',$RepositoryRoot)
$finalMatrix=Join-Path $EvidenceRoot 'ENTRY_REACHABILITY_RESULT.json';$null=Invoke-Child $matrixPath @('-RepositoryRoot',$RepositoryRoot,'-OutputPath',$finalMatrix)
$report=Get-Content -LiteralPath $finalMatrix -Raw -Encoding UTF8|ConvertFrom-Json
if(-not[bool]$report.pass-or[int]$report.scenario_count-ne101-or[int]$report.executed_count-ne101){Fail('R7 requires exact 101/101 matrix PASS; count='+[string]$report.scenario_count+' executed='+[string]$report.executed_count)}
$docRows=@($report.scenarios|Where-Object{[string]$_.state-ceq'REGISTRY_DOCUMENT_INVALID'});if($docRows.Count-ne18-or@($docRows|Where-Object{-not[bool]$_.pass}).Count-ne0){Fail 'REGISTRY_DOCUMENT_INVALID must have exact 18/18 PASS.'}
$pending=@($report.scenarios|Where-Object{[string]$_.state-ceq'REGISTRY_PENDING_GLOBAL'-and[string]$_.action-ceq'InitializeInstanceRegistry'});if($pending.Count-ne1-or-not[bool]$pending[0].pass-or[string]$pending[0].expected_mode-cne'registry_init_reconciles_global_input'){Fail 'Pending-global Initialize reconciliation proof missing.'}
$initValid=@($report.scenarios|Where-Object{[string]$_.action-ceq'InitializeInstanceRegistry'-and@('REGISTRY_HEALTHY','REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_INSTANCE','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT') -ccontains [string]$_.state});if($initValid.Count-ne6-or@($initValid|Where-Object{-not[bool]$_.pass}).Count-ne0){Fail 'Existing valid-registry Initialize success coverage is incomplete.'}
$machine=Get-Content -LiteralPath $stateMachinePath -Raw -Encoding UTF8|ConvertFrom-Json;$risk2=Get-Content -LiteralPath $riskPath -Raw -Encoding UTF8|ConvertFrom-Json;$mapped=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal);foreach($surface in @($risk2.surfaces)){foreach($id in @($surface.state_machine_rules)){[void]$mapped.Add([string]$id)}};$nonDefault=@($machine.rules|Where-Object{[int]$_.priority-gt0}|ForEach-Object{[string]$_.id}|Sort-Object -Unique);$unmapped=@($nonDefault|Where-Object{-not$mapped.Contains($_)});if($unmapped.Count-ne0){Fail('Unmapped non-default rules remain: '+($unmapped-join', '))};Write-Host ('State-machine risk mapping: '+$nonDefault.Count+'/'+$nonDefault.Count+' PASS') -ForegroundColor Green

$changed=@(& git.exe -C $RepositoryRoot diff --name-only)
$expected=@('.github/workflows/entry-reachability-validation.yml','MANAGER_DEVELOPMENT_STATE.json','PUBLIC_PROVENANCE.json','tests/knowledge/entry-reachability.json','tests/knowledge/prefreeze-semantic-review.json','tests/knowledge/risk-map.json','tests/knowledge/state-machines/multi-hub.json','tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Test-ManagerEngineeringKnowledge.ps1','tools/Test-ManagerEntryReachabilityKnowledge.ps1')|Sort-Object
if(([string]::Join('|',@($changed|Sort-Object)))-cne([string]::Join('|',$expected))){Fail('Unexpected R7 patch set: '+($changed-join', '))}
if(@(& git.exe -C $RepositoryRoot diff --name-only -- manager).Count-ne0){Fail 'Manager product bytes changed in R7 prefreeze convergence.'}
Write-Host 'Manager 4.17.13 consolidated prefreeze knowledge/proof R7: PASS' -ForegroundColor Green
