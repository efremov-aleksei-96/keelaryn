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
function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8)}
function Write-Json([string]$Path,$Object){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth 60).Replace("`r`n","`n"))+"`n")}
function Replace-Once([string]$Text,[string]$Old,[string]$New,[string]$Label){$i=$Text.IndexOf($Old,[StringComparison]::Ordinal);if($i-lt0){Fail($Label+': source token missing')};if($Text.IndexOf($Old,$i+$Old.Length,[StringComparison]::Ordinal)-ge0){Fail($Label+': source token occurs more than once')};return $Text.Substring(0,$i)+$New+$Text.Substring($i+$Old.Length)}
function Replace-RegexOnce([string]$Text,[string]$Pattern,[string]$Replacement,[string]$Label){$m=[regex]::Matches($Text,$Pattern,[Text.RegularExpressions.RegexOptions]::Multiline);if($m.Count-ne1){Fail($Label+': regex matches='+$m.Count)};return [regex]::Replace($Text,$Pattern,$Replacement,[Text.RegularExpressions.RegexOptions]::Multiline)}
function Run([string]$Script,[string[]]$Args){$exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference;try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Args 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old};foreach($line in $out){Write-Host $line};if($code-ne0){Fail('Command failed: '+$Script+' '+($Args-join' ')+' exit='+$code)};return @($out)}

$actual=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($actual-cne$ExpectedBase.ToLowerInvariant()){Fail('Authoritative dev head moved. expected='+$ExpectedBase+' actual='+$actual)}
git.exe -C $RepositoryRoot config user.name 'Aleksei Efremov'
git.exe -C $RepositoryRoot config user.email 'efremov.aleksei.96@gmail.com'
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-41713-materialize-'+[guid]::NewGuid().ToString('N'))}
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null

# 1. Product runtime: exact version bump and action-class-aware pre-dispatch policy.
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
$runtime=Replace-Once $runtime '$ManagerVersion = "4.17.12"' '$ManagerVersion = "4.17.13"' 'runtime version'
$guardPattern='(?ms)^if\(\$script:InstanceRegistryActive -and -not\$Doctor\)\{\r?\n\s*Acquire-ManagerLock\r?\n\s*try\{\$null=Invoke-ReconcileActiveCompatibilityShadow\}\r?\n\s*finally\{Release-ManagerLock\}\r?\n\}'
$newGuard=@'
function Test-ActiveCompatibilityShadowReconciliationRequired {
    if(-not$script:InstanceRegistryActive){return $false}
    # Diagnostic/target-driven recovery and Manager-global operations must be reachable
    # without validating or repairing the old active Hub CURRENT they do not consume.
    if($Doctor-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$UpdateManager-or$BuildDistribution-or$BuildRelease-or$BuildAIContext){return $false}
    return $true
}

if(Test-ActiveCompatibilityShadowReconciliationRequired){
    Acquire-ManagerLock
    try{$null=Invoke-ReconcileActiveCompatibilityShadow}
    finally{Release-ManagerLock}
}
'@
$runtime=Replace-RegexOnce $runtime $guardPattern ($newGuard.TrimEnd()) 'pre-dispatch reconciliation guard'
$allow=[regex]::Match($runtime,'(?m)^\s*\$allowRegistryUnresolved=.*$').Value
foreach($token in @('$Doctor','$ListInstances','$SwitchInstanceId','$BindInstancePath','$UpdateManager','$BuildDistribution','$BuildRelease','$BuildAIContext')){if(-not$allow.Contains($token)){Fail('allowRegistryUnresolved omits '+$token)}}
Write-Utf8 $runtimePath $runtime

# 2. Product version markers.
foreach($relative in @('manager\product\install\INSTALLATION.json','manager\product\manager_release.json')){
    $path=Join-Path $RepositoryRoot $relative;$doc=Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json
    if([string]$doc.manager_version-cne'4.17.12'){Fail($relative+' expected 4.17.12 before successor materialization')}
    $doc.manager_version='4.17.13';Write-Json $path $doc
}

# 3. Managed release instructions. Historical context remains; only current sections move to 4.17.13.
$readmePath=Join-Path $RepositoryRoot 'manager\README_FIRST.md';$readme=[IO.File]::ReadAllText($readmePath,[Text.Encoding]::UTF8);$nl=if($readme.Contains("`r`n")){"`r`n"}else{"`n"}
$prefixPattern='(?s)\A# Keelaryn Manager 4\.17\.12\r?\n(?<old>Manager 4\.17\.12[^\r\n]*)\r?\n\r?\n## 4\.17\.11 context'
$m=[regex]::Match($readme,$prefixPattern);if(-not$m.Success){Fail 'README current 4.17.12 prefix not found.'}
$newPrefix="# Keelaryn Manager 4.17.13${nl}Manager 4.17.13 is the corrective successor to the production-installed but public-release-rejected Manager 4.17.12. It makes compatibility-shadow reconciliation action-aware: target-driven recovery, registry diagnostics and Manager-global build/update operations remain reachable when the old active CURRENT is missing or corrupt, while Hub/context-bound operations continue to reconcile or fail closed. The release process also adds real process-entry reachability coverage and mandatory semantic review before candidate freeze. Production multi-Hub remains disabled until qualification, installation, public release and separate activation approval.${nl}${nl}## 4.17.12 context${nl}$($m.Groups['old'].Value)${nl}${nl}## 4.17.11 context"
$readme=$newPrefix+$readme.Substring($m.Index+$m.Length)
$updateSection=[string]::Join($nl,@('## Update compatibility','', 'Manager 4.17.13 preserves the native update compatibility floor in `product/manager_release.json` and the established UPDATE transition envelope. The normal production qualification transition for this corrective candidate is production-installed Manager 4.17.12 -> 4.17.13.','', 'Manager-only update commands remain Manager-global and do not require a healthy active Hub compatibility CURRENT. Installing Manager 4.17.13 alone must not change canonical Hub content.',''))
$readme=[regex]::Replace($readme,'(?ms)^## Update compatibility\s*\r?\n.*?(?=^## User interface compatibility)',$updateSection,1)
$releaseSection=[string]::Join($nl,@('## Release gate','', 'This source is not production-approved merely because it carries version 4.17.13. Production approval requires the applicable parser/static checks, version-independent behavioral regressions, the 4.17.13 review regression, the real process-entry reachability matrix, Manager/frontend SelfTests, deterministic SOURCE/DISTRIBUTION/UPDATE/AI_CONTEXT checks, disposable 4.17.12 -> 4.17.13 update and rollback/fault-injection coverage, Doctor/migration/UI/Genesis coverage, full-successor Risk/Defect Gate, a clean exact-head pre-freeze semantic PR review, production Hub immutability, exact tested/public-source/release UPDATE identity, real CURRENT-backed Full Gate and gated publication. The consolidated gate uses qualified Gate Framework r24.',''))
$readme=[regex]::Replace($readme,'(?ms)^## Release gate\s*\r?\n.*\z',$releaseSection,1)
Write-Utf8 $readmePath $readme

# 4. Current-version review wrapper: behavior is version-independent; identity is separate.
$reviewPath=Join-Path $RepositoryRoot 'tools\Invoke-Manager41713ReviewRegression.ps1'
$review=@'
[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop';Set-StrictMode -Version 2.0;$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
function Fail([string]$Message){throw $Message}
function Assert([bool]$Condition,[string]$Message){if(-not$Condition){Fail $Message}}
function Get-FunctionText([string]$Path,[string]$Name){$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e);if(@($e).Count){Fail('Parser failed: '+([string]::Join(' | ',@($e|ForEach-Object{$_.Message})) ))};$r=@($a.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name});if($r.Count-ne1){Fail('Function '+$Name+' count='+$r.Count)};return [string]$r[0].Extent.Text}
$p=Join-Path $PSHOME 'powershell.exe';& $p -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $RepositoryRoot 'tools\Invoke-ManagerRecoveryBehaviorRegression.ps1') -RepositoryRoot $RepositoryRoot;if($LASTEXITCODE-ne0){Fail 'Version-independent recovery behavior regression failed.'}
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1';$installPath=Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json';$releasePath=Join-Path $RepositoryRoot 'manager\product\manager_release.json';$readmePath=Join-Path $RepositoryRoot 'manager\README_FIRST.md'
$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8);$install=Get-Content $installPath -Raw -Encoding UTF8|ConvertFrom-Json;$release=Get-Content $releasePath -Raw -Encoding UTF8|ConvertFrom-Json;$readme=[IO.File]::ReadAllText($readmePath,[Text.Encoding]::UTF8)
Assert ($runtime-match'(?m)^\$ManagerVersion = "4\.17\.13"$') 'Runtime version marker is not 4.17.13.';Assert ([string]$install.manager_version-ceq'4.17.13') 'INSTALLATION version is not 4.17.13.';Assert ([string]$release.manager_version-ceq'4.17.13') 'release policy version is not 4.17.13.';Assert ($readme.Contains('production-installed Manager 4.17.12 -> 4.17.13')) 'README transition identity is not 4.17.12 -> 4.17.13.'
$policy=Get-FunctionText $runtimePath 'Test-ActiveCompatibilityShadowReconciliationRequired';foreach($token in @('$Doctor','$ListInstances','$SwitchInstanceId','$BindInstancePath','$UpdateManager','$BuildDistribution','$BuildRelease','$BuildAIContext')){Assert ($policy.Contains($token)) ('Reconciliation policy omits '+$token)};Assert ($runtime.Contains('if(Test-ActiveCompatibilityShadowReconciliationRequired)')) 'Top-level runtime does not use centralized reconciliation policy.';Assert (-not$runtime.Contains('if($script:InstanceRegistryActive -and -not$Doctor)')) 'Legacy unconditional reconciliation guard remains.'
Write-Host 'MANAGER 4.17.13 REVIEW REGRESSION: PASS' -ForegroundColor Green
'@
Write-Utf8 $reviewPath (($review.TrimEnd())+"`n")

# 5. Extend canonical state/risk knowledge with CURRENT-degraded lifecycle states and entry regression selection.
$smPath=Join-Path $RepositoryRoot 'tests\knowledge\state-machines\multi-hub.json';$sm=Get-Content $smPath -Raw -Encoding UTF8|ConvertFrom-Json
foreach($row in @(
    [pscustomobject]@{id='S_ACTIVE_CURRENT_MISSING';description='Registry and active Hub resolve, but active per-instance/compatibility CURRENT is missing.'},
    [pscustomobject]@{id='S_ACTIVE_CURRENT_CORRUPT';description='Registry and active Hub resolve, but active per-instance/compatibility CURRENT is corrupt or unreadable.'}
)){if(@($sm.states|Where-Object{[string]$_.id-ceq$row.id}).Count-eq0){$sm.states=@($sm.states)+@($row)}}
foreach($row in @(
    [pscustomobject]@{id='T_ACTIVE_CURRENT_LOST';from='S_REGISTRY_ACTIVE_HEALTHY';to='S_ACTIVE_CURRENT_MISSING';trigger='active CURRENT removed/unavailable';guards=@('registry/active Hub still resolve');commit='none';failure='recovery/global actions remain reachable; Hub-bound actions fail closed'},
    [pscustomobject]@{id='T_ACTIVE_CURRENT_CORRUPT';from='S_REGISTRY_ACTIVE_HEALTHY';to='S_ACTIVE_CURRENT_CORRUPT';trigger='active CURRENT becomes corrupt/unreadable';guards=@('registry/active Hub still resolve');commit='none';failure='recovery/global actions remain reachable; Hub-bound actions fail closed'},
    [pscustomobject]@{id='T_SWITCH_FROM_CURRENT_DEGRADED';from='S_ACTIVE_CURRENT_MISSING';to='S_REGISTRY_ACTIVE_HEALTHY';trigger='target-driven switch to healthy registered Hub';guards=@('requested target independently activation-eligible');commit='active selection + compatibility shadow';failure='old active CURRENT is not a prerequisite'},
    [pscustomobject]@{id='T_SWITCH_FROM_CORRUPT_CURRENT';from='S_ACTIVE_CURRENT_CORRUPT';to='S_REGISTRY_ACTIVE_HEALTHY';trigger='target-driven switch to healthy registered Hub';guards=@('requested target independently activation-eligible');commit='active selection + compatibility shadow';failure='old active CURRENT is not a prerequisite'}
)){if(@($sm.transitions|Where-Object{[string]$_.id-ceq$row.id}).Count-eq0){$sm.transitions=@($sm.transitions)+@($row)}}
Write-Json $smPath $sm
$riskPath=Join-Path $RepositoryRoot 'tests\knowledge\risk-map.json';$risk=Get-Content $riskPath -Raw -Encoding UTF8|ConvertFrom-Json;$surface=@($risk.surfaces|Where-Object{[string]$_.id-ceq'S-RUNTIME-REGISTRY-RESOLUTION'});if($surface.Count-ne1){Fail 'S-RUNTIME-REGISTRY-RESOLUTION missing/ambiguous.'};foreach($v in @('S_ACTIVE_CURRENT_MISSING','S_ACTIVE_CURRENT_CORRUPT')){if(@($surface[0].states)-notcontains$v){$surface[0].states=@($surface[0].states)+@($v)}};foreach($v in @('RC-ENTRY-001')){if(@($surface[0].root_cause_classes)-notcontains$v){$surface[0].root_cause_classes=@($surface[0].root_cause_classes)+@($v)}};foreach($v in @('tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Invoke-ManagerRecoveryBehaviorRegression.ps1','tools/Invoke-Manager41713ReviewRegression.ps1')){if(@($surface[0].regressions)-notcontains$v){$surface[0].regressions=@($surface[0].regressions)+@($v)}};Write-Json $riskPath $risk

# 6. Development validation: execute reusable behavior + current-version wrapper + real entry matrix.
$devPath=Join-Path $RepositoryRoot 'tools\Invoke-DevelopmentValidation.ps1';$dev=[IO.File]::ReadAllText($devPath,[Text.Encoding]::UTF8)
$dev=Replace-Once $dev "    'tools\\Invoke-Manager41712ReviewRegression.ps1'" "    'tools\\Invoke-Manager41712ReviewRegression.ps1',${nl}    'tools\\Invoke-ManagerRecoveryBehaviorRegression.ps1',${nl}    'tools\\Test-ManagerEntryReachabilityKnowledge.ps1',${nl}    'tools\\Invoke-ManagerEntryReachabilityMatrix.ps1',${nl}    'tools\\Invoke-Manager41713ReviewRegression.ps1'" 'development knowledge-tool list'
$oldLoop="foreach(`$regressionName in @('Invoke-Manager41710ReviewRegression.ps1','Invoke-Manager41711ReviewRegression.ps1','Invoke-Manager41712ReviewRegression.ps1')){"
$newLoop="foreach(`$regressionName in @('Invoke-Manager41710ReviewRegression.ps1','Invoke-Manager41711ReviewRegression.ps1','Invoke-ManagerRecoveryBehaviorRegression.ps1','Invoke-Manager41713ReviewRegression.ps1')){"
$dev=Replace-Once $dev $oldLoop $newLoop 'development review-regression loop'
$dev=Replace-Once $dev "Write-Host 'Manager 4.17.10 + 4.17.11 + 4.17.12 review regression and release-instruction chain: PASS' -ForegroundColor Green" "`$entryModelValidator=Join-Path `$RepositoryRoot 'tools\\Test-ManagerEntryReachabilityKnowledge.ps1'${nl}Invoke-Child `$entryModelValidator @('-RepositoryRoot',`$RepositoryRoot)${nl}`$entryEvidence=Join-Path `$evidence 'ENTRY_REACHABILITY_RESULT.json'${nl}`$entryMatrix=Join-Path `$RepositoryRoot 'tools\\Invoke-ManagerEntryReachabilityMatrix.ps1'${nl}Invoke-Child `$entryMatrix @('-RepositoryRoot',`$RepositoryRoot,'-OutputPath',`$entryEvidence)${nl}Write-Host 'Manager review regressions + release identity + process-entry reachability: PASS' -ForegroundColor Green" 'development entry matrix insertion'
$dev=Replace-Once $dev '    review_regressions_pass=$true' "    review_regressions_pass=`$true${nl}    entry_reachability_pass=`$true" 'development evidence entry flag'
Write-Utf8 $devPath $dev

# 7. Run behavioral and real process-entry checks before closing the defect.
Run (Join-Path $RepositoryRoot 'tools\Invoke-ManagerRecoveryBehaviorRegression.ps1') @('-RepositoryRoot',$RepositoryRoot)|Out-Null
Run $reviewPath @('-RepositoryRoot',$RepositoryRoot)|Out-Null
Run (Join-Path $RepositoryRoot 'tools\Test-ManagerEntryReachabilityKnowledge.ps1') @('-RepositoryRoot',$RepositoryRoot)|Out-Null
$entryEvidence=Join-Path $EvidenceRoot 'ENTRY_REACHABILITY_RESULT.json';Run (Join-Path $RepositoryRoot 'tools\Invoke-ManagerEntryReachabilityMatrix.ps1') @('-RepositoryRoot',$RepositoryRoot,'-OutputPath',$entryEvidence)|Out-Null
$entry=Get-Content $entryEvidence -Raw -Encoding UTF8|ConvertFrom-Json;if(-not[bool]$entry.pass-or[int]$entry.scenario_count-ne53-or[int]$entry.executed_count-ne53){Fail 'Entry matrix did not produce full 53/53 PASS evidence.'}

# 8. Only after green proof close MGR-DEF-0030 and transition development policy.
$defectPath=Join-Path $RepositoryRoot 'tests\knowledge\defects\manager-4.17.12-postfreeze.json';$defect=Get-Content $defectPath -Raw -Encoding UTF8|ConvertFrom-Json;$d=@($defect.defects|Where-Object{[string]$_.id-ceq'MGR-DEF-0030'});if($d.Count-ne1){Fail 'MGR-DEF-0030 missing/ambiguous.'};$d[0].status='fixed';$d[0].fixed_in='4.17.13';$d[0].permanent_regressions=@('tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Invoke-ManagerRecoveryBehaviorRegression.ps1','tools/Invoke-Manager41713ReviewRegression.ps1');$d[0].evidence=@($d[0].evidence)+@([pscustomobject]@{type='green_process_entry_materialization_evidence';id=$entryEvidence});Write-Json $defectPath $defect
$statePath=Join-Path $RepositoryRoot 'MANAGER_DEVELOPMENT_STATE.json';$state=Get-Content $statePath -Raw -Encoding UTF8|ConvertFrom-Json;$state.materialization.manager_version='4.17.13';$state.materialization.status='materialized_unqualified_development';$state.open_release_blockers=@();$state.qualification.risk_defect_gate.status='required_pass_before_freeze';$state.qualification.successor_4_17_13.status='materialized_unqualified_development';$state.qualification.successor_4_17_13|Add-Member -NotePropertyName process_entry_red_proof_run -NotePropertyValue '34822083447' -Force;$state.qualification.successor_4_17_13|Add-Member -NotePropertyName process_entry_red_proof_artifact -NotePropertyValue '10338886824' -Force;$state.qualification.successor_4_17_13|Add-Member -NotePropertyName process_entry_green_proof -NotePropertyValue 'materializer_local_precommit_53_of_53_pass' -Force;$state.next_exact_goal.id='MANAGER-41713-QUALIFY-001';$state.next_exact_goal.description='Obtain clean exact-head Development Validation and Entry Reachability PASS, then full-successor Risk/Defect Gate and exact-head pre-freeze semantic PR review before candidate freeze.';$state.next_exact_goal.product_fix_may_start_only_after_red_proof=$false;$state.next_exact_goal.candidate_freeze_permitted=$false;Write-Json $statePath $state

# 9. Release identity/knowledge/SelfTests and public manifest must all be coherent before commit/push.
Run (Join-Path $RepositoryRoot 'tools\Verify-ManagerReleaseInstructions.ps1') @('-RepositoryRoot',$RepositoryRoot)|Out-Null
Run (Join-Path $RepositoryRoot 'tools\Test-ManagerEngineeringKnowledge.ps1') @('-RepositoryRoot',$RepositoryRoot)|Out-Null
Run $runtimePath @('-SelfTest')|Out-Null
Run (Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1') @('-SelfTest','-NoRootLauncher')|Out-Null
Run (Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1') @('-RepositoryRoot',$RepositoryRoot,'-Write')|Out-Null
Run (Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1') @('-RepositoryRoot',$RepositoryRoot,'-Check')|Out-Null

# 10. Commit exact coherent product successor. Push is performed by the caller only after this script exits 0.
git.exe -C $RepositoryRoot add --all
$status=@(git.exe -C $RepositoryRoot status --porcelain);if($status.Count-eq0){Fail 'Materializer produced no changes.'}
git.exe -C $RepositoryRoot commit -m 'Manager 4.17.13: make recovery reachable from process entry'
if($LASTEXITCODE-ne0){Fail 'Could not commit Manager 4.17.13 materialization.'}
$head=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant();$tree=(& git.exe -C $RepositoryRoot rev-parse HEAD^{tree}).Trim().ToLowerInvariant()
Write-Host ('MANAGER 4.17.13 MATERIALIZATION: PASS head='+$head+' tree='+$tree) -ForegroundColor Green
Write-Host ('ENTRY_EVIDENCE='+$entryEvidence)
