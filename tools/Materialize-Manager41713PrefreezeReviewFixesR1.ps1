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
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path $env:RUNNER_TEMP 'manager-41713-prefreeze-review-fixes'}
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

# Strengthen the executable model so the two semantic-review findings cannot regress to no-op coverage.
$model=Get-Content -LiteralPath $modelPath -Raw -Encoding UTF8|ConvertFrom-Json
$proofModes=@{
    ListInstances='entry_list_no_mutation';SwitchInstance='target_switch';BindInstance='changed_path_rebind_commit';UpdateManager='install_successor_restart';
    BuildDistribution='manager_global_execution';BuildRelease='manager_global_execution';BuildAIContext='manager_global_execution';Doctor='diagnostic_body';
    UpdateHub='fail_closed_no_hub_mutation';UpdateAll='fail_closed_no_hub_mutation';RepairCurrent='fail_closed_no_hub_mutation';BuildCandidateTransport='fail_closed_no_hub_mutation';RestoreCandidateTransport='fail_closed_no_hub_mutation';
    SelfTest='manager_global_execution';PrepareTests='manager_global_execution';InitializePresentation='manager_global_execution';FinalizeFilesystemLayout='manager_global_execution';InitializeInstanceRegistry='manager_global_execution'
}
foreach($a in @($model.actions)){
    $id=[string]$a.id
    if(-not$proofModes.ContainsKey($id)){Fail('No proof_mode mapping for action '+$id)}
    $a|Add-Member -NotePropertyName proof_mode -NotePropertyValue ([string]$proofModes[$id]) -Force
}
$extraRule=' BindInstance coverage must execute a changed-path rebind transaction and assert the new registry path is committed without Manager-driven Hub-byte movement or cloning. UpdateManager coverage must seed a newer valid disposable Manager package and assert the successor is installed, self-test succeeds, and the restarted -UpdateManager process reaches its post-install no-newer-package completion path.'
if(-not([string]$model.freeze_rule).Contains('changed-path rebind transaction')){$model.freeze_rule=([string]$model.freeze_rule)+$extraRule}
Write-Json $modelPath $model

$oldValidator="    if([string]::IsNullOrWhiteSpace([string]`$row.class)){Fail(`$id+' class is empty.')}`n    if(@('list_success','target_success','global_success','diagnostic_reached','fail_closed') -cnotcontains [string]`$row.expected_mode){Fail(`$id+' expected_mode is unsupported: '+[string]`$row.expected_mode)}"
$newValidator="    if([string]::IsNullOrWhiteSpace([string]`$row.class)){Fail(`$id+' class is empty.')}`n    if([string]::IsNullOrWhiteSpace([string]`$row.proof_mode)){Fail(`$id+' proof_mode is empty.')}`n    if(@('list_success','target_success','global_success','diagnostic_reached','fail_closed') -cnotcontains [string]`$row.expected_mode){Fail(`$id+' expected_mode is unsupported: '+[string]`$row.expected_mode)}"
Replace-Once $validatorPath $oldValidator $newValidator 'validator proof_mode guard'
$oldRequired="foreach(`$requiredAction in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','InitializeInstanceRegistry','UpdateHub','UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport')){if(-not`$actionIds.Contains(`$requiredAction)){Fail('Required action is missing: '+`$requiredAction)}}"
$newRequired=$oldRequired+"`nif([string]`$actionById['BindInstance'].proof_mode-cne'changed_path_rebind_commit'){Fail 'BindInstance must require changed_path_rebind_commit proof.'}`nif([string]`$actionById['UpdateManager'].proof_mode-cne'install_successor_restart'){Fail 'UpdateManager must require install_successor_restart proof.'}"
Replace-Once $validatorPath $oldRequired $newRequired 'validator transactional proof requirements'
$oldFreeze="if(-not([string]`$model.freeze_rule).Contains('may not restore state through the same runtime path under test')){Fail 'Freeze rule must prohibit runtime-dependent scenario reset.'}"
$newFreeze=$oldFreeze+"`nif(-not([string]`$model.freeze_rule).Contains('changed-path rebind transaction')){Fail 'Freeze rule must require real changed-path BindInstance rebind.'}`nif(-not([string]`$model.freeze_rule).Contains('newer valid disposable Manager package')){Fail 'Freeze rule must require a real UpdateManager installation/restart.'}"
Replace-Once $validatorPath $oldFreeze $newFreeze 'validator freeze transactional guards'

$helperOld="function Read-Registry([string]`$ManagerRoot){return Get-Content -LiteralPath (Join-Path `$ManagerRoot 'state\\instances.json') -Raw -Encoding UTF8|ConvertFrom-Json}`nfunction Read-Active([string]`$ManagerRoot){return Get-Content -LiteralPath (Join-Path `$ManagerRoot 'state\\active_instance.json') -Raw -Encoding UTF8|ConvertFrom-Json}"
$helperNew=@'
function Read-Registry([string]$ManagerRoot){return Get-Content -LiteralPath (Join-Path $ManagerRoot 'state\instances.json') -Raw -Encoding UTF8|ConvertFrom-Json}
function Read-Active([string]$ManagerRoot){return Get-Content -LiteralPath (Join-Path $ManagerRoot 'state\active_instance.json') -Raw -Encoding UTF8|ConvertFrom-Json}
function Get-PathKey([string]$Path){return [IO.Path]::GetFullPath($Path).TrimEnd('\').ToLowerInvariant()}
function Get-InstalledManagerVersion([string]$ManagerRoot){
    $p=Join-Path $ManagerRoot 'product\install\INSTALLATION.json'
    if(-not(Test-Path -LiteralPath $p -PathType Leaf)){return ''}
    try{return ([string]((Get-Content -LiteralPath $p -Raw -Encoding UTF8|ConvertFrom-Json).manager_version)).Trim()}catch{return ''}
}
function Set-SyntheticManagerVersion([string]$ManagerRoot,[string]$FromVersion,[string]$ToVersion){
    $runtimePath=Join-Path $ManagerRoot 'product\runtime\Keelaryn__Manager.ps1'
    $text=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
    $old='$ManagerVersion = "'+$FromVersion+'"';$new='$ManagerVersion = "'+$ToVersion+'"'
    if([regex]::Matches($text,[regex]::Escape($old)).Count-ne1){Fail('Synthetic runtime version marker count mismatch for '+$FromVersion)}
    Write-Utf8 $runtimePath ($text.Replace($old,$new))
    foreach($rel in @('product\install\INSTALLATION.json','product\manager_release.json')){
        $p=Join-Path $ManagerRoot $rel;$j=Get-Content -LiteralPath $p -Raw -Encoding UTF8|ConvertFrom-Json;$j.manager_version=$ToVersion;Write-Json $p $j
    }
    $readme=Join-Path $ManagerRoot 'README_FIRST.md';$rt=[IO.File]::ReadAllText($readme,[Text.Encoding]::UTF8)
    $rx=New-Object Text.RegularExpressions.Regex(('(?m)^# Keelaryn Manager '+[regex]::Escape($FromVersion)+'\r?$'))
    if($rx.Matches($rt).Count-ne1){Fail('Synthetic README version header count mismatch for '+$FromVersion)}
    Write-Utf8 $readme ($rx.Replace($rt,('# Keelaryn Manager '+$ToVersion),1))
}
function New-SyntheticSuccessorUpdate([string]$SourceManager,[string]$TempRoot,[string]$CurrentVersion){
    $v=[version]$CurrentVersion;if($v.Build-lt0){Fail('Cannot derive synthetic successor from '+$CurrentVersion)}
    $next=('{0}.{1}.{2}' -f $v.Major,$v.Minor,($v.Build+1))
    $builder=Join-Path $TempRoot 'successor-builder\manager';$null=Copy-ManagedManager $SourceManager $builder
    Set-SyntheticManagerVersion $builder $CurrentVersion $next
    $builderRuntime=Join-Path $builder 'product\runtime\Keelaryn__Manager.ps1'
    $null=Invoke-Required $builderRuntime @('-InitializePresentation') 'Synthetic successor InitializePresentation'
    $null=Invoke-Required $builderRuntime @('-SelfTest') 'Synthetic successor SelfTest'
    $null=Invoke-Required $builderRuntime @('-BuildRelease') 'Synthetic successor BuildRelease'
    $built=Join-Path $builder ('state\releases\Keelaryn__Manager_Update_v'+$next+'_Built.zip')
    if(-not(Test-Path -LiteralPath $built -PathType Leaf)){Fail('Synthetic successor UPDATE missing: '+$built)}
    $fixtureDir=Join-Path $TempRoot 'fixtures';New-Item -ItemType Directory -Force -Path $fixtureDir|Out-Null
    $fixture=Join-Path $fixtureDir ([IO.Path]::GetFileName($built));Copy-Item -LiteralPath $built -Destination $fixture -Force
    return [pscustomobject]@{Version=$next;Path=$fixture;FileName=[IO.Path]::GetFileName($fixture)}
}
'@
Replace-Once $matrixPath $helperOld ($helperNew.TrimEnd()) 'matrix transactional helper insertion'

$oldSnapshot=@'
    # Baseline snapshots live outside the tested installation. Scenario reset never invokes Manager runtime.
    $snapRoot=Join-Path $tempRoot 'snapshots';New-Item -ItemType Directory -Force -Path $snapRoot|Out-Null
    $snapState=Join-Path $snapRoot 'manager-state';$snapAlpha=Join-Path $snapRoot 'alpha-hub';$snapBeta=Join-Path $snapRoot 'beta-hub'
    Copy-DirectoryExact $stateRoot $snapState;Copy-DirectoryExact $alphaPath $snapAlpha;Copy-DirectoryExact $betaPath $snapBeta

    function Reset-ScenarioBaseline {Copy-DirectoryExact $snapState $stateRoot;Copy-DirectoryExact $snapAlpha $alphaPath;Copy-DirectoryExact $snapBeta $betaPath}
'@
$newSnapshot=@'
    # Build proof fixtures outside the tested installation. Bind uses a relocated copy with the same immutable instance_id;
    # UpdateManager receives a real valid higher-version UPDATE that must install, self-test and restart.
    $betaRelocatedPath=Join-Path $keelarynRoot 'hubs\beta-relocated';Copy-DirectoryExact $betaPath $betaRelocatedPath
    $successor=New-SyntheticSuccessorUpdate $sourceManager $tempRoot $version

    # Baseline snapshots live outside the tested installation. Scenario reset never invokes Manager runtime.
    # The entire Manager root is restored because UpdateManager is now intentionally mutating product bytes.
    $snapRoot=Join-Path $tempRoot 'snapshots';New-Item -ItemType Directory -Force -Path $snapRoot|Out-Null
    $snapManager=Join-Path $snapRoot 'manager';$snapAlpha=Join-Path $snapRoot 'alpha-hub';$snapBeta=Join-Path $snapRoot 'beta-hub';$snapBetaRelocated=Join-Path $snapRoot 'beta-relocated-hub'
    Copy-DirectoryExact $managerRoot $snapManager;Copy-DirectoryExact $alphaPath $snapAlpha;Copy-DirectoryExact $betaPath $snapBeta;Copy-DirectoryExact $betaRelocatedPath $snapBetaRelocated

    function Reset-ScenarioBaseline {Copy-DirectoryExact $snapManager $managerRoot;Copy-DirectoryExact $snapAlpha $alphaPath;Copy-DirectoryExact $snapBeta $betaPath;Copy-DirectoryExact $snapBetaRelocated $betaRelocatedPath}
'@
Replace-Once $matrixPath ($oldSnapshot.Trim()) ($newSnapshot.Trim()) 'matrix full snapshot and fixtures'
Replace-Once $matrixPath "            'BindInstance' {return @('-BindInstancePath',`$betaPath,'-RegisterInstanceName','Beta')}" "            'BindInstance' {return @('-BindInstancePath',`$betaRelocatedPath,'-RegisterInstanceName','Beta')}" 'matrix changed-path bind argument'

$oldLoop=@'
        try{
            Reset-ScenarioBaseline
            $fixture=[string]$stateById[$spec.State].fixture;Apply-DegradedFixture $fixture
            $alphaBefore=Get-TreeDigest $alphaPath;$betaBefore=Get-TreeDigest $betaPath
            $r=Invoke-Runtime $runtime (Get-ActionArguments $spec.Action);$exitCode=$r.ExitCode
            $hubsUnchanged=((Get-TreeDigest $alphaPath)-ceq$alphaBefore-and(Get-TreeDigest $betaPath)-ceq$betaBefore)
            switch([string]$spec.Mode){
                'list_success' {$pass=($r.ExitCode-eq0-and$r.Text.Contains('Registered Hubs:')-and$hubsUnchanged);$detail=if($pass){'real process entry reached registry listing without Hub mutation'}else{'listing unreachable/failed or Hub bytes changed: '+$r.Text}}
                'target_success' {$activeOk=$false;if($r.ExitCode-eq0){try{$activeOk=([string](Read-Active $managerRoot).instance_id-ceq$betaId)}catch{}};$pass=($r.ExitCode-eq0-and$activeOk-and$hubsUnchanged);$detail=if($pass){'healthy requested target became active without moving/cloning Hub bytes'}else{'target-driven recovery unreachable/failed or mutated Hub bytes: '+$r.Text}}
                'global_success' {$pass=($r.ExitCode-eq0-and$hubsUnchanged);$detail=if($pass){'Manager-global action completed independently of degraded Hub context'}else{'Manager-global action blocked/failed or mutated Hub bytes: '+$r.Text}}
                'diagnostic_reached' {$pass=($r.Text.Contains('Keelaryn Doctor - Manager')-and$hubsUnchanged);$detail=if($pass){'Doctor reached diagnostic body and left Hub bytes unchanged; exit='+$r.ExitCode}else{'Doctor was blocked before diagnostic body or mutated Hub bytes: '+$r.Text}}
                'fail_closed' {$pass=($r.ExitCode-ne0-and$hubsUnchanged);$detail=if($pass){'Hub/context-bound action failed closed without Hub mutation'}else{'expected fail-closed outcome not observed: '+$r.Text}}
                default {Fail('Unsupported expected mode: '+[string]$spec.Mode)}
            }
        }catch{
'@
$newLoop=@'
        try{
            Reset-ScenarioBaseline
            $fixture=[string]$stateById[$spec.State].fixture;Apply-DegradedFixture $fixture
            $proofMode=[string]$actionById[[string]$spec.Action].proof_mode
            $updateInboxPath=$null
            if([string]$spec.Action-ceq'UpdateManager'){
                $updateInboxPath=Join-Path $managerRoot ('state\inbox\'+[string]$successor.FileName)
                Copy-Item -LiteralPath ([string]$successor.Path) -Destination $updateInboxPath -Force
            }
            $alphaBefore=Get-TreeDigest $alphaPath;$betaBefore=Get-TreeDigest $betaPath;$betaRelocatedBefore=Get-TreeDigest $betaRelocatedPath
            $r=Invoke-Runtime $runtime (Get-ActionArguments $spec.Action);$exitCode=$r.ExitCode
            $hubsUnchanged=((Get-TreeDigest $alphaPath)-ceq$alphaBefore-and(Get-TreeDigest $betaPath)-ceq$betaBefore-and(Get-TreeDigest $betaRelocatedPath)-ceq$betaRelocatedBefore)
            switch([string]$spec.Mode){
                'list_success' {$pass=($r.ExitCode-eq0-and$r.Text.Contains('Registered Hubs:')-and$hubsUnchanged);$detail=if($pass){'real process entry reached registry listing without Hub mutation'}else{'listing unreachable/failed or Hub bytes changed: '+$r.Text}}
                'target_success' {
                    $activeOk=$false;$registryPathOk=$true
                    if($r.ExitCode-eq0){
                        try{
                            $activeOk=([string](Read-Active $managerRoot).instance_id-ceq$betaId)
                            if([string]$spec.Action-ceq'BindInstance'){
                                $rows=@((Read-Registry $managerRoot).instances|Where-Object{[string]$_.instance_id-ceq$betaId})
                                $registryPathOk=($rows.Count-eq1-and(Get-PathKey ([string]$rows[0].vault_path))-ceq(Get-PathKey $betaRelocatedPath))
                            }
                        }catch{$activeOk=$false;$registryPathOk=$false}
                    }
                    $pass=($r.ExitCode-eq0-and$activeOk-and$registryPathOk-and$hubsUnchanged)
                    if([string]$spec.Action-ceq'BindInstance'){$detail=if($pass){'real changed-path rebind committed the relocated Beta path, activated the same instance_id, and left both old/relocated Hub bytes unchanged'}else{'changed-path rebind transaction unreachable/failed, registry path not committed, or Hub bytes changed: '+$r.Text}}
                    else{$detail=if($pass){'healthy requested target became active without moving/cloning Hub bytes'}else{'target-driven recovery unreachable/failed or mutated Hub bytes: '+$r.Text}}
                }
                'global_success' {
                    if([string]$spec.Action-ceq'UpdateManager'){
                        $installed=(Get-InstalledManagerVersion $managerRoot);$restartObserved=$r.Text.Contains('Manager update: no newer valid Manager package was found.');$packageConsumed=(-not(Test-Path -LiteralPath $updateInboxPath -PathType Leaf))
                        $pass=($r.ExitCode-eq0-and$hubsUnchanged-and$installed-ceq[string]$successor.Version-and$restartObserved-and$packageConsumed)
                        $detail=if($pass){'valid disposable successor installed, post-install self-test passed, restarted -UpdateManager reached completion, and Hub bytes stayed unchanged'}else{'real Manager install/restart proof failed; installed='+$installed+' restart='+$restartObserved+' package_consumed='+$packageConsumed+' output='+$r.Text}
                    }else{
                        $pass=($r.ExitCode-eq0-and$hubsUnchanged);$detail=if($pass){'Manager-global action completed independently of degraded Hub context'}else{'Manager-global action blocked/failed or mutated Hub bytes: '+$r.Text}
                    }
                }
                'diagnostic_reached' {$pass=($r.Text.Contains('Keelaryn Doctor - Manager')-and$hubsUnchanged);$detail=if($pass){'Doctor reached diagnostic body and left Hub bytes unchanged; exit='+$r.ExitCode}else{'Doctor was blocked before diagnostic body or mutated Hub bytes: '+$r.Text}}
                'fail_closed' {$pass=($r.ExitCode-ne0-and$hubsUnchanged);$detail=if($pass){'Hub/context-bound action failed closed without Hub mutation'}else{'expected fail-closed outcome not observed: '+$r.Text}}
                default {Fail('Unsupported expected mode: '+[string]$spec.Mode)}
            }
        }catch{
'@
Replace-Once $matrixPath ($oldLoop.Trim()) ($newLoop.Trim()) 'matrix transactional scenario execution'
$oldResult="        [void]`$results.Add([ordered]@{id=[string]`$spec.Id;requirement=[string]`$spec.Requirement;state=[string]`$spec.State;action=[string]`$spec.Action;expected_mode=[string]`$spec.Mode;pass=`$pass;classification=if(`$pass){'pass'}else{`$classification};exit_code=`$exitCode;detail=`$detail})"
$newResult="        [void]`$results.Add([ordered]@{id=[string]`$spec.Id;requirement=[string]`$spec.Requirement;state=[string]`$spec.State;action=[string]`$spec.Action;expected_mode=[string]`$spec.Mode;proof_mode=[string]`$actionById[[string]`$spec.Action].proof_mode;pass=`$pass;classification=if(`$pass){'pass'}else{`$classification};exit_code=`$exitCode;detail=`$detail})"
Replace-Once $matrixPath $oldResult $newResult 'matrix proof_mode evidence'
$oldReport="    schema='keelaryn.manager-entry-reachability-result.v2';manager_version=`$version;model_sha256=`$modelSha;scenario_count=@(`$scenarioSpecs).Count;executed_count=@(`$results).Count;pass=(`$null-eq`$harnessError-and`$failed.Count-eq0);harness_error=`$harnessError;failures=@(`$failed|ForEach-Object{[string]`$_.id});scenarios=@(`$results);production_hub_used=`$false;scenario_reset='direct_external_snapshot_restore';completed_utc=[DateTime]::UtcNow.ToString('o')"
$newReport="    schema='keelaryn.manager-entry-reachability-result.v2';manager_version=`$version;model_sha256=`$modelSha;scenario_count=@(`$scenarioSpecs).Count;executed_count=@(`$results).Count;pass=(`$null-eq`$harnessError-and`$failed.Count-eq0);harness_error=`$harnessError;failures=@(`$failed|ForEach-Object{[string]`$_.id});scenarios=@(`$results);production_hub_used=`$false;scenario_reset='direct_external_full_manager_and_hub_snapshot_restore';transactional_proof_revision=2;synthetic_successor_version=[string]`$successor.Version;completed_utc=[DateTime]::UtcNow.ToString('o')"
Replace-Once $matrixPath $oldReport $newReport 'matrix report proof revision'

Parse-File $validatorPath;Parse-File $matrixPath
if(@(& git.exe -C $RepositoryRoot diff --name-only -- manager).Count-ne0){Fail 'Product bytes changed while fixing qualification proof.'}
$changed=@(& git.exe -C $RepositoryRoot diff --name-only)
$expected=@('tests/knowledge/entry-reachability.json','tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Test-ManagerEntryReachabilityKnowledge.ps1')|Sort-Object
$actual=@($changed|ForEach-Object{[string]$_}|Sort-Object)
if(([string]::Join('|',$actual))-cne([string]::Join('|',$expected))){Fail('Unexpected changed-file set: '+([string]::Join(',',$actual)))}

Invoke-Child $validatorPath @('-RepositoryRoot',$RepositoryRoot)
$matrixEvidence=Join-Path $EvidenceRoot 'ENTRY_REACHABILITY_RESULT.json'
Invoke-Child $matrixPath @('-RepositoryRoot',$RepositoryRoot,'-OutputPath',$matrixEvidence)
Write-Host 'PREFREEZE REVIEW PROOF FIXES: LOCAL GREEN; product bytes unchanged.' -ForegroundColor Green
