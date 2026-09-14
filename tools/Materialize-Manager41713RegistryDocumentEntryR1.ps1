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
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path $env:RUNNER_TEMP 'manager-41713-registry-document-entry-proof'}
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null
function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8)}
function Write-Json([string]$Path,$Object){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth 50).Replace("`r`n","`n"))+"`n")}
function Replace-Once([string]$Path,[string]$Old,[string]$New,[string]$Label){
    $s=[IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8);$count=[regex]::Matches($s,[regex]::Escape($Old)).Count
    if($count-ne1){Fail($Label+' count='+$count)};Write-Utf8 $Path ($s.Replace($Old,$New))
}
function Parse-File([string]$Path){$tokens=$null;$errors=$null;[void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors);if(@($errors).Count){Fail('Parser failed: '+$Path+' :: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}}
function Invoke-Child([string]$Script,[string[]]$Arguments){
    $exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    foreach($line in @($out)){Write-Host $line};if($code-ne0){Fail('Child failed: '+$Script+' exit='+$code)}
}

$head=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($head-cne$ExpectedBase.ToLowerInvariant()){Fail('Unexpected target HEAD: '+$head+' expected='+$ExpectedBase)}
if(@(& git.exe -C $RepositoryRoot status --porcelain).Count-ne0){Fail 'Target checkout is not clean.'}
$modelPath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability.json'
$validatorPath=Join-Path $RepositoryRoot 'tools\Test-ManagerEntryReachabilityKnowledge.ps1'
$matrixPath=Join-Path $RepositoryRoot 'tools\Invoke-ManagerEntryReachabilityMatrix.ps1'
$model=Get-Content -LiteralPath $modelPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$model.schema-cne'keelaryn.manager-entry-reachability.v2'){Fail 'Unexpected entry-reachability schema.'}
if(@($model.states|Where-Object{[string]$_.id-ceq'REGISTRY_DOCUMENT_INVALID'}).Count-ne0){Fail 'REGISTRY_DOCUMENT_INVALID is already represented in entry reachability.'}
if(@($model.coverage_requirements|Where-Object{[string]$_.id-ceq'CR-REGISTRY-INIT-INVALID-ACTIVE'}).Count-ne1){Fail 'Expected prior 78-scenario registry-init coverage materialization is absent.'}

$newState=[pscustomobject][ordered]@{id='REGISTRY_DOCUMENT_INVALID';fixture='registry_document_invalid';description='instances.json exists but the authoritative registry document itself is malformed or otherwise unsafe to resolve.'}
$model.states=@($model.states)+@($newState)
$newReqs=@(
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-GLOBAL';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout')},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-DOCTOR';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('Doctor')},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-HUB-BOUND';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('UpdateHub')},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-LIST';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('ListInstances');expected_mode='registry_document_rejected_after_dispatch'},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-TARGET';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('SwitchInstance','BindInstance');expected_mode='registry_document_rejected_after_dispatch'},
    [pscustomobject][ordered]@{id='CR-REGISTRY-DOCUMENT-INVALID-INIT';states=@('REGISTRY_DOCUMENT_INVALID');actions=@('InitializeInstanceRegistry');expected_mode='registry_init_rejected_after_dispatch'}
)
$model.coverage_requirements=@($model.coverage_requirements)+@($newReqs)
$freezeSentence=' REGISTRY_DOCUMENT_INVALID must execute through real process entry: Manager-global bypasses must remain usable, diagnostics must be reachable, unsafe registry rows must never become recovery targets, Hub-bound work must fail closed, and registry initialization must reject through its existing-registry validator. Rejected registry recovery/initialization scenarios must preserve instances.json and active_instance.json bytes.'
if(-not([string]$model.freeze_rule).Contains('REGISTRY_DOCUMENT_INVALID must execute through real process entry')){$model.freeze_rule=([string]$model.freeze_rule)+$freezeSentence}
Write-Json $modelPath $model

$oldFixture="        switch(`$Fixture){`n            'active_metadata_invalid' {Write-Utf8 `$activeFile '{ not-json'}"
$newFixture="        switch(`$Fixture){`n            'registry_document_invalid' {Write-Utf8 (Join-Path `$stateRoot 'instances.json') '{ not-json'}`n            'active_metadata_invalid' {Write-Utf8 `$activeFile '{ not-json'}"
Replace-Once $matrixPath $oldFixture $newFixture 'registry-document invalid fixture'

$oldBefore="            `$alphaBefore=Get-TreeDigest `$alphaPath;`$betaBefore=Get-TreeDigest `$betaPath;`$betaRelocatedBefore=Get-TreeDigest `$betaRelocatedPath`n            `$r=Invoke-Runtime `$runtime (Get-ActionArguments `$spec.Action);`$exitCode=`$r.ExitCode`n            `$hubsUnchanged=((Get-TreeDigest `$alphaPath)-ceq`$alphaBefore-and(Get-TreeDigest `$betaPath)-ceq`$betaBefore-and(Get-TreeDigest `$betaRelocatedPath)-ceq`$betaRelocatedBefore)"
$newBefore="            `$alphaBefore=Get-TreeDigest `$alphaPath;`$betaBefore=Get-TreeDigest `$betaPath;`$betaRelocatedBefore=Get-TreeDigest `$betaRelocatedPath`n            `$registryControl=Join-Path `$stateRoot 'instances.json'`n            `$registryBefore=if(Test-Path -LiteralPath `$registryControl -PathType Leaf){(Get-FileHash -LiteralPath `$registryControl -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$activeBefore=if(Test-Path -LiteralPath `$activeFile -PathType Leaf){(Get-FileHash -LiteralPath `$activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$r=Invoke-Runtime `$runtime (Get-ActionArguments `$spec.Action);`$exitCode=`$r.ExitCode`n            `$hubsUnchanged=((Get-TreeDigest `$alphaPath)-ceq`$alphaBefore-and(Get-TreeDigest `$betaPath)-ceq`$betaBefore-and(Get-TreeDigest `$betaRelocatedPath)-ceq`$betaRelocatedBefore)`n            `$registryAfter=if(Test-Path -LiteralPath `$registryControl -PathType Leaf){(Get-FileHash -LiteralPath `$registryControl -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$activeAfter=if(Test-Path -LiteralPath `$activeFile -PathType Leaf){(Get-FileHash -LiteralPath `$activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}`n            `$controlStateUnchanged=(`$registryAfter-ceq`$registryBefore-and`$activeAfter-ceq`$activeBefore)"
Replace-Once $matrixPath $oldBefore $newBefore 'control-state immutability capture'

$oldInit="                'registry_init_rejected_after_dispatch' {`$reached=`$r.Text.Contains('Existing multi-Hub registry is invalid:');`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$reached);`$detail=if(`$pass){'InitializeInstanceRegistry reached its existing-registry validator and rejected the invalid active context without Hub mutation'}else{'registry initialization was blocked before operation-specific validation, succeeded unexpectedly, or mutated Hub bytes: '+`$r.Text}}"
$newInit="                'registry_document_rejected_after_dispatch' {`$startupBlocked=`$r.Text.Contains('Invalid Keelaryn multi-Hub registry:');`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$controlStateUnchanged-and-not`$startupBlocked);`$detail=if(`$pass){'unsafe registry document was rejected after startup allow-dispatch without Hub or registry/active metadata mutation'}else{'unsafe registry handling was blocked in startup, succeeded unexpectedly, or mutated state: '+`$r.Text}}`n                'registry_init_rejected_after_dispatch' {`$reached=`$r.Text.Contains('Existing multi-Hub registry is invalid:');`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$controlStateUnchanged-and`$reached);`$detail=if(`$pass){'InitializeInstanceRegistry reached its existing-registry validator and rejected invalid authoritative registry state without Hub or registry/active metadata mutation'}else{'registry initialization was blocked before operation-specific validation, succeeded unexpectedly, or mutated state: '+`$r.Text}}"
Replace-Once $matrixPath $oldInit $newInit 'registry document dispatch + init rejection outcomes'

$oldAllowed="@('list_success','target_success','global_success','diagnostic_reached','fail_closed','registry_init_rejected_after_dispatch') -cnotcontains `$reqMode"
$newAllowed="@('list_success','target_success','global_success','diagnostic_reached','fail_closed','registry_init_rejected_after_dispatch','registry_document_rejected_after_dispatch') -cnotcontains `$reqMode"
Replace-Once $validatorPath $oldAllowed $newAllowed 'validator registry-document expected mode'

$oldStates="foreach(`$requiredState in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT'))"
$newStates="foreach(`$requiredState in @('REGISTRY_DOCUMENT_INVALID','REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT'))"
Replace-Once $validatorPath $oldStates $newStates 'validator required registry-document state'

$oldFloor="foreach(`$sid in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT')){if(-not`$pairs.Contains(`$sid+'|InitializeInstanceRegistry')){Fail('Invalid-active registry initialization coverage omitted '+`$sid+'|InitializeInstanceRegistry')}}`nif(`$pairs.Count-lt78){Fail('Entry-reachability cross-product is unexpectedly small: '+`$pairs.Count)}"
$newFloor="foreach(`$sid in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT')){if(-not`$pairs.Contains(`$sid+'|InitializeInstanceRegistry')){Fail('Invalid-active registry initialization coverage omitted '+`$sid+'|InitializeInstanceRegistry')}}`nforeach(`$aid in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','UpdateHub','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','InitializeInstanceRegistry')){if(-not`$pairs.Contains('REGISTRY_DOCUMENT_INVALID|'+`$aid)){Fail('Registry-document-invalid entry coverage omitted '+`$aid)}}`nif(`$pairs.Count-lt92){Fail('Entry-reachability cross-product is unexpectedly small: '+`$pairs.Count)}"
Replace-Once $validatorPath $oldFloor $newFloor 'validator registry-document coverage floor'

$oldFreeze="if(-not([string]`$model.freeze_rule).Contains('operation-specific rejection after real process-entry dispatch')){Fail 'Freeze rule must require operation-specific InitializeInstanceRegistry rejection proof.'}"
$newFreeze=$oldFreeze+"`nif(-not([string]`$model.freeze_rule).Contains('REGISTRY_DOCUMENT_INVALID must execute through real process entry')){Fail 'Freeze rule must require registry-document-invalid process-entry proof.'}`nif(-not([string]`$model.freeze_rule).Contains('preserve instances.json and active_instance.json bytes')){Fail 'Freeze rule must require registry/active control-state preservation for rejected recovery.'}"
Replace-Once $validatorPath $oldFreeze $newFreeze 'validator registry-document freeze rule'

Parse-File $validatorPath;Parse-File $matrixPath
Invoke-Child $validatorPath @('-RepositoryRoot',$RepositoryRoot)
$matrixOut=Join-Path $EvidenceRoot 'ENTRY_REACHABILITY_RESULT.json'
Invoke-Child $matrixPath @('-RepositoryRoot',$RepositoryRoot,'-OutputPath',$matrixOut)
$report=Get-Content -LiteralPath $matrixOut -Raw -Encoding UTF8|ConvertFrom-Json
if(-not[bool]$report.pass-or[int]$report.scenario_count-ne92-or[int]$report.executed_count-ne92){Fail('Expected exact strengthened 92/92 matrix PASS; count='+[string]$report.scenario_count+' executed='+[string]$report.executed_count)}
$docRows=@($report.scenarios|Where-Object{[string]$_.state-ceq'REGISTRY_DOCUMENT_INVALID'})
if($docRows.Count-ne14-or@($docRows|Where-Object{-not[bool]$_.pass}).Count-ne0){Fail 'REGISTRY_DOCUMENT_INVALID must have exactly 14/14 passing entry scenarios.'}
$docTarget=@($docRows|Where-Object{@('ListInstances','SwitchInstance','BindInstance') -ccontains [string]$_.action})
if($docTarget.Count-ne3-or@($docTarget|Where-Object{[string]$_.expected_mode-cne'registry_document_rejected_after_dispatch'}).Count-ne0){Fail 'Unsafe-registry List/Switch/Bind did not use after-dispatch rejection proof.'}
$initRows=@($report.scenarios|Where-Object{[string]$_.action-ceq'InitializeInstanceRegistry'-and@('REGISTRY_DOCUMENT_INVALID','REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT') -ccontains [string]$_.state})
if($initRows.Count-ne4-or@($initRows|Where-Object{-not[bool]$_.pass-or[string]$_.expected_mode-cne'registry_init_rejected_after_dispatch'}).Count-ne0){Fail 'Four invalid-registry InitializeInstanceRegistry process-entry proofs did not all PASS.'}

$changed=@(& git.exe -C $RepositoryRoot diff --name-only);$expected=@('tests/knowledge/entry-reachability.json','tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Test-ManagerEntryReachabilityKnowledge.ps1')|Sort-Object
if(([string]::Join('|',@($changed|Sort-Object)))-cne([string]::Join('|',$expected))){Fail('Unexpected materialized patch set: '+($changed-join', '))}
if(@(& git.exe -C $RepositoryRoot diff --name-only -- manager).Count-ne0){Fail 'Manager product bytes changed in registry-document proof materialization.'}
Write-Host 'Manager 4.17.13 registry-document process-entry proof materialization: PASS' -ForegroundColor Green
