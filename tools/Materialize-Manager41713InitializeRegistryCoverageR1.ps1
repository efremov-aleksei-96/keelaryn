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
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path $env:RUNNER_TEMP 'manager-41713-init-registry-entry-proof'}
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null
function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8)}
function Write-Json([string]$Path,$Object){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth 40).Replace("`r`n","`n"))+"`n")}
function Replace-Once([string]$Path,[string]$Old,[string]$New,[string]$Label){
    $s=[IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8)
    $count=[regex]::Matches($s,[regex]::Escape($Old)).Count
    if($count-ne1){Fail($Label+' count='+$count)}
    Write-Utf8 $Path ($s.Replace($Old,$New))
}
function Parse-File([string]$Path){$tokens=$null;$errors=$null;[void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors);if(@($errors).Count){Fail('Parser failed: '+$Path+' :: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}}
function Invoke-Child([string]$Script,[string[]]$Arguments){
    $exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    foreach($line in @($out)){Write-Host $line}
    if($code-ne0){Fail('Child failed: '+$Script+' exit='+$code)}
}

$head=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($head-cne$ExpectedBase.ToLowerInvariant()){Fail('Unexpected target HEAD: '+$head+' expected='+$ExpectedBase)}
if(@(& git.exe -C $RepositoryRoot status --porcelain).Count-ne0){Fail 'Target checkout is not clean.'}

$modelPath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability.json'
$validatorPath=Join-Path $RepositoryRoot 'tools\Test-ManagerEntryReachabilityKnowledge.ps1'
$matrixPath=Join-Path $RepositoryRoot 'tools\Invoke-ManagerEntryReachabilityMatrix.ps1'
$model=Get-Content -LiteralPath $modelPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$model.schema-cne'keelaryn.manager-entry-reachability.v2'){Fail 'Unexpected entry-reachability schema.'}
if($null-eq$model.actions-or@($model.actions|Where-Object{[string]$_.id-ceq'InitializeInstanceRegistry'}).Count-ne1){Fail 'InitializeInstanceRegistry action model is missing or ambiguous.'}
if([string](@($model.actions|Where-Object{[string]$_.id-ceq'InitializeInstanceRegistry'})[0].proof_mode)-cne'manager_global_execution'){Fail 'Expected post-review proof_mode materialization is absent.'}
if(@($model.coverage_requirements|Where-Object{[string]$_.id-ceq'CR-REGISTRY-INIT-INVALID-ACTIVE'}).Count-ne0){Fail 'Registry-init invalid-active coverage requirement already exists.'}

$newReq=[pscustomobject][ordered]@{
    id='CR-REGISTRY-INIT-INVALID-ACTIVE'
    states=@('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT')
    actions=@('InitializeInstanceRegistry')
    expected_mode='registry_init_rejected_after_dispatch'
}
$model.coverage_requirements=@($model.coverage_requirements)+@($newReq)
$freezeSentence=' InitializeInstanceRegistry coverage for invalid active-registry states must prove operation-specific rejection after real process-entry dispatch, not merely a startup-layer failure.'
if(-not([string]$model.freeze_rule).Contains('operation-specific rejection after real process-entry dispatch')){$model.freeze_rule=([string]$model.freeze_rule)+$freezeSentence}
Write-Json $modelPath $model

$oldGenerator="            `$ordinal++;`$sid=[string]`$sid0;`$aid=[string]`$aid0`n            [void]`$scenarioSpecs.Add([pscustomobject]@{Id=('ER-{0:D3}' -f `$ordinal);Requirement=[string]`$req.id;State=`$sid;Action=`$aid;Mode=[string]`$actionById[`$aid].expected_mode})"
$newGenerator="            `$ordinal++;`$sid=[string]`$sid0;`$aid=[string]`$aid0`n            `$mode=[string]`$actionById[`$aid].expected_mode`n            if(`$null-ne`$req.PSObject.Properties['expected_mode']-and-not[string]::IsNullOrWhiteSpace([string]`$req.expected_mode)){`$mode=[string]`$req.expected_mode}`n            [void]`$scenarioSpecs.Add([pscustomobject]@{Id=('ER-{0:D3}' -f `$ordinal);Requirement=[string]`$req.id;State=`$sid;Action=`$aid;Mode=`$mode})"
Replace-Once $matrixPath $oldGenerator $newGenerator 'matrix requirement-level expected mode'

$failClosed="                'fail_closed' {`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged);`$detail=if(`$pass){'Hub/context-bound action failed closed without Hub mutation'}else{'expected fail-closed outcome not observed: '+`$r.Text}}"
$registryInit="                'registry_init_rejected_after_dispatch' {`$reached=`$r.Text.Contains('Existing multi-Hub registry is invalid:');`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$reached);`$detail=if(`$pass){'InitializeInstanceRegistry reached its existing-registry validator and rejected the invalid active context without Hub mutation'}else{'registry initialization was blocked before operation-specific validation, succeeded unexpectedly, or mutated Hub bytes: '+`$r.Text}}`n"+$failClosed
Replace-Once $matrixPath $failClosed $registryInit 'matrix registry-init operation-specific outcome'

$oldReqHeader="    `$rid=[string]`$req.id;Add-Unique `$requirementIds `$rid 'coverage requirement'`n    if(@(`$req.states).Count-eq0-or@(`$req.actions).Count-eq0){Fail(`$rid+' must contain states and actions.')}"
$newReqHeader="    `$rid=[string]`$req.id;Add-Unique `$requirementIds `$rid 'coverage requirement'`n    if(`$null-ne`$req.PSObject.Properties['expected_mode']){`$reqMode=[string]`$req.expected_mode;if(@('list_success','target_success','global_success','diagnostic_reached','fail_closed','registry_init_rejected_after_dispatch') -cnotcontains `$reqMode){Fail(`$rid+' expected_mode override is unsupported: '+`$reqMode)}}`n    if(@(`$req.states).Count-eq0-or@(`$req.actions).Count-eq0){Fail(`$rid+' must contain states and actions.')}"
Replace-Once $validatorPath $oldReqHeader $newReqHeader 'validator requirement expected-mode override'

$oldBoundary="foreach(`$sid in @('REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){`n    foreach(`$aid in @('UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','InitializeInstanceRegistry')){if(-not`$pairs.Contains(`$sid+'|'+`$aid)){Fail('CURRENT-degraded boundary coverage omitted '+`$sid+'|'+`$aid)}}`n}`nif(`$pairs.Count-lt75){Fail('Entry-reachability cross-product is unexpectedly small: '+`$pairs.Count)}"
$newBoundary=$oldBoundary.Replace("if(`$pairs.Count-lt75){Fail('Entry-reachability cross-product is unexpectedly small: '+`$pairs.Count)}", "foreach(`$sid in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT')){if(-not`$pairs.Contains(`$sid+'|InitializeInstanceRegistry')){Fail('Invalid-active registry initialization coverage omitted '+`$sid+'|InitializeInstanceRegistry')}}`nif(`$pairs.Count-lt78){Fail('Entry-reachability cross-product is unexpectedly small: '+`$pairs.Count)}")
Replace-Once $validatorPath $oldBoundary $newBoundary 'validator registry-init coverage floor'

$oldFreeze="if(-not([string]`$model.freeze_rule).Contains('newer valid disposable Manager package')){Fail 'Freeze rule must require a real UpdateManager installation/restart.'}"
$newFreeze=$oldFreeze+"`nif(-not([string]`$model.freeze_rule).Contains('operation-specific rejection after real process-entry dispatch')){Fail 'Freeze rule must require operation-specific InitializeInstanceRegistry rejection proof.'}"
Replace-Once $validatorPath $oldFreeze $newFreeze 'validator registry-init freeze rule'

Parse-File $validatorPath
Parse-File $matrixPath
Invoke-Child $validatorPath @('-RepositoryRoot',$RepositoryRoot)
$matrixOut=Join-Path $EvidenceRoot 'ENTRY_REACHABILITY_RESULT.json'
Invoke-Child $matrixPath @('-RepositoryRoot',$RepositoryRoot,'-OutputPath',$matrixOut)
$report=Get-Content -LiteralPath $matrixOut -Raw -Encoding UTF8|ConvertFrom-Json
if(-not[bool]$report.pass-or[int]$report.scenario_count-lt78-or[int]$report.executed_count-ne[int]$report.scenario_count){Fail('Strengthened entry matrix did not prove all scenarios: count='+[string]$report.scenario_count+' executed='+[string]$report.executed_count)}
$initRows=@($report.scenarios|Where-Object{[string]$_.action-ceq'InitializeInstanceRegistry'-and@('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT') -ccontains [string]$_.state})
if($initRows.Count-ne3-or@($initRows|Where-Object{-not[bool]$_.pass-or[string]$_.expected_mode-cne'registry_init_rejected_after_dispatch'}).Count-ne0){Fail 'Three invalid-active InitializeInstanceRegistry process-entry proofs did not all PASS with the operation-specific expectation.'}

$changed=@(& git.exe -C $RepositoryRoot diff --name-only)
$expected=@('tests/knowledge/entry-reachability.json','tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Test-ManagerEntryReachabilityKnowledge.ps1')|Sort-Object
if(([string]::Join('|',@($changed|Sort-Object)))-cne([string]::Join('|',$expected))){Fail('Unexpected materialized patch set: '+($changed-join', '))}
if(@(& git.exe -C $RepositoryRoot diff --name-only -- manager).Count-ne0){Fail 'Manager product bytes changed in registry-init proof materialization.'}
Write-Host 'Manager 4.17.13 registry-init process-entry proof materialization: PASS' -ForegroundColor Green
