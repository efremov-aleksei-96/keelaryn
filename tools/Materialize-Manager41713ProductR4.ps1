[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [string]$EvidenceRoot=''
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Utf8=New-Object Text.UTF8Encoding($false)
$source=Join-Path $PSScriptRoot 'Materialize-Manager41713Product.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw 'Base 4.17.13 product materializer is missing.'}
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)

# Fix child-process argument forwarding. $Args is a PowerShell automatic variable and is
# not a safe formal parameter name for our explicit argument vector.
$runSignature='function Run([string]$Script,[string[]]$Args){'
if(([regex]::Matches($text,[regex]::Escape($runSignature))).Count-ne1){throw 'Base Run signature is missing/ambiguous.'}
if(([regex]::Matches($text,[regex]::Escape('@Args 2>&1'))).Count-ne1){throw 'Base Run @Args invocation is missing/ambiguous.'}
if(([regex]::Matches($text,[regex]::Escape("(`$Args-join' ')"))).Count-ne1){throw 'Base Run Args diagnostic is missing/ambiguous.'}
$text=$text.Replace($runSignature,'function Run([string]$Script,[string[]]$Arguments){')
$text=$text.Replace('@Args 2>&1','@Arguments 2>&1')
$text=$text.Replace("(`$Args-join' ')","(`$Arguments-join' ')")

# Keep the managed README bound to the canonical release-instruction validator.
$releaseIdentityOld='version-independent behavioral regressions, the 4.17.13 review regression'
$releaseIdentityNew='inherited and 4.17.13 regressions, the version-independent behavioral regression suite'
if(([regex]::Matches($text,[regex]::Escape($releaseIdentityOld))).Count-ne1){throw '4.17.13 README regression identity token is missing/ambiguous.'}
$text=$text.Replace($releaseIdentityOld,$releaseIdentityNew)

# Canonical state-machine model is states + operations + rules. Do not invent transitions.
$statePattern='(?s)\$smPath=Join-Path \$RepositoryRoot ''tests\\knowledge\\state-machines\\multi-hub\.json'';\$sm=Get-Content \$smPath -Raw -Encoding UTF8\|ConvertFrom-Json.*?Write-Json \$smPath \$sm'
if(([regex]::Matches($text,$statePattern)).Count-ne1){throw 'Canonical state-machine materialization block is missing/ambiguous.'}
$stateReplacement=@'
$smPath=Join-Path $RepositoryRoot 'tests\knowledge\state-machines\multi-hub.json';$sm=Get-Content $smPath -Raw -Encoding UTF8|ConvertFrom-Json
foreach($row in @(
    [pscustomobject]@{id='REGISTRY_ACTIVE_CURRENT_MISSING';description='Registry and active selection resolve and the selected active Hub is structurally valid, but both old-active per-instance/compatibility CURRENT checkpoints are missing.'},
    [pscustomobject]@{id='REGISTRY_ACTIVE_CURRENT_CORRUPT';description='Registry and active selection resolve and the selected active Hub is structurally valid, but both old-active per-instance/compatibility CURRENT checkpoints are corrupt or unreadable.'}
)){if(@($sm.states|Where-Object{[string]$_.id-ceq$row.id}).Count-eq0){$sm.states=@($sm.states)+@($row)}}
foreach($row in @(
    [pscustomobject]@{id='R-CURRENT-MISSING-LIST';states=@('REGISTRY_ACTIVE_CURRENT_MISSING');operation='ListInstances';priority=210;outcome='list_registry_rows_without_old_active_current';invariants=@('MH-REGISTRY-001','MH-RECOVERY-001');reason='Registry diagnostics must remain reachable when the old active CURRENT is missing.'},
    [pscustomobject]@{id='R-CURRENT-CORRUPT-LIST';states=@('REGISTRY_ACTIVE_CURRENT_CORRUPT');operation='ListInstances';priority=210;outcome='list_registry_rows_without_old_active_current';invariants=@('MH-REGISTRY-001','MH-RECOVERY-001');reason='Registry diagnostics must remain reachable when the old active CURRENT is corrupt.'},
    [pscustomobject]@{id='R-CURRENT-MISSING-SWITCH';states=@('REGISTRY_ACTIVE_CURRENT_MISSING');operation='SwitchInstance';priority=210;outcome='recover_by_validating_requested_registered_target_only';invariants=@('MH-RECOVERY-001','MH-SWITCH-001','MH-COMMIT-001');reason='Target-driven switch validates the requested target and must not require the old active CURRENT.'},
    [pscustomobject]@{id='R-CURRENT-CORRUPT-SWITCH';states=@('REGISTRY_ACTIVE_CURRENT_CORRUPT');operation='SwitchInstance';priority=210;outcome='recover_by_validating_requested_registered_target_only';invariants=@('MH-RECOVERY-001','MH-SWITCH-001','MH-COMMIT-001');reason='Target-driven switch validates the requested target and must not require the old active CURRENT.'},
    [pscustomobject]@{id='R-CURRENT-MISSING-BIND';states=@('REGISTRY_ACTIVE_CURRENT_MISSING');operation='BindInstance';priority=210;outcome='rebind_or_register_requested_target_without_old_active_current';invariants=@('MH-RECOVERY-001','MH-REBIND-001','MH-BINDING-001');reason='Target-driven bind/rebind validates the requested target and must not require the old active CURRENT.'},
    [pscustomobject]@{id='R-CURRENT-CORRUPT-BIND';states=@('REGISTRY_ACTIVE_CURRENT_CORRUPT');operation='BindInstance';priority=210;outcome='rebind_or_register_requested_target_without_old_active_current';invariants=@('MH-RECOVERY-001','MH-REBIND-001','MH-BINDING-001');reason='Target-driven bind/rebind validates the requested target and must not require the old active CURRENT.'},
    [pscustomobject]@{id='R-CURRENT-MISSING-UPDATE-MANAGER';states=@('REGISTRY_ACTIVE_CURRENT_MISSING');operation='UpdateManager';priority=210;outcome='global_only_without_old_active_current';invariants=@('MH-MANAGER-GLOBAL-001','MH-RECOVERY-001');reason='Manager-global update must remain reachable without active Hub CURRENT health.'},
    [pscustomobject]@{id='R-CURRENT-CORRUPT-UPDATE-MANAGER';states=@('REGISTRY_ACTIVE_CURRENT_CORRUPT');operation='UpdateManager';priority=210;outcome='global_only_without_old_active_current';invariants=@('MH-MANAGER-GLOBAL-001','MH-RECOVERY-001');reason='Manager-global update must remain reachable without active Hub CURRENT health.'}
)){if(@($sm.rules|Where-Object{[string]$_.id-ceq$row.id}).Count-eq0){$sm.rules=@($sm.rules)+@($row)}}
Write-Json $smPath $sm
'@
$text=[regex]::Replace($text,$statePattern,{param($m)$stateReplacement.TrimEnd()},1)

# Risk-map surfaces already expose root-cause/regression/state-machine-rule fields.
$riskPattern='(?s)\$riskPath=Join-Path \$RepositoryRoot ''tests\\knowledge\\risk-map\.json'';\$risk=Get-Content \$riskPath -Raw -Encoding UTF8\|ConvertFrom-Json;\$surface=@\(\$risk\.surfaces\|Where-Object\{\[string\]\$_\.id-ceq''S-RUNTIME-REGISTRY-RESOLUTION''\}\);if\(\$surface\.Count-ne1\)\{Fail ''S-RUNTIME-REGISTRY-RESOLUTION missing/ambiguous\.''\};.*?Write-Json \$riskPath \$risk'
if(([regex]::Matches($text,$riskPattern)).Count-ne1){throw 'Canonical risk-map materialization block is missing/ambiguous.'}
$riskReplacement=@'
$riskPath=Join-Path $RepositoryRoot 'tests\knowledge\risk-map.json';$risk=Get-Content $riskPath -Raw -Encoding UTF8|ConvertFrom-Json
$surface=@($risk.surfaces|Where-Object{[string]$_.id-ceq'S-RUNTIME-REGISTRY-RESOLUTION'});if($surface.Count-ne1){Fail 'S-RUNTIME-REGISTRY-RESOLUTION missing/ambiguous.'}
foreach($v in @('RC-ENTRY-001')){if(@($surface[0].root_cause_classes)-notcontains$v){$surface[0].root_cause_classes=@($surface[0].root_cause_classes)+@($v)}}
foreach($v in @('tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Invoke-ManagerRecoveryBehaviorRegression.ps1','tools/Invoke-Manager41713ReviewRegression.ps1')){if(@($surface[0].regressions)-notcontains$v){$surface[0].regressions=@($surface[0].regressions)+@($v)}}
foreach($v in @('R-CURRENT-MISSING-LIST','R-CURRENT-CORRUPT-LIST','R-CURRENT-MISSING-SWITCH','R-CURRENT-CORRUPT-SWITCH','R-CURRENT-MISSING-BIND','R-CURRENT-CORRUPT-BIND','R-CURRENT-MISSING-UPDATE-MANAGER','R-CURRENT-CORRUPT-UPDATE-MANAGER')){if(@($surface[0].state_machine_rules)-notcontains$v){$surface[0].state_machine_rules=@($surface[0].state_machine_rules)+@($v)}}
Write-Json $riskPath $risk
'@
$text=[regex]::Replace($text,$riskPattern,{param($m)$riskReplacement.TrimEnd()},1)

# Development Validation inherits behavior, current-version identity and real process-entry proof.
$devPattern='(?s)# 6\. Development validation: execute reusable behavior \+ current-version wrapper \+ real entry matrix\..*?Write-Utf8 \$devPath \$dev'
if(([regex]::Matches($text,$devPattern)).Count-ne1){throw 'Development-validation materialization block is missing/ambiguous.'}
$devReplacement=@'
# 6. Development validation: execute reusable behavior + current-version wrapper + real entry matrix.
$devPath=Join-Path $RepositoryRoot 'tools\Invoke-DevelopmentValidation.ps1';$dev=[IO.File]::ReadAllText($devPath,[Text.Encoding]::UTF8)
$knowledgeAnchor="    'tools\Invoke-Manager41712ReviewRegression.ps1'"
$dev=Replace-Once $dev $knowledgeAnchor ($knowledgeAnchor+","+$nl+"    'tools\Invoke-ManagerRecoveryBehaviorRegression.ps1',"+$nl+"    'tools\Test-ManagerEntryReachabilityKnowledge.ps1',"+$nl+"    'tools\Invoke-ManagerEntryReachabilityMatrix.ps1',"+$nl+"    'tools\Invoke-Manager41713ReviewRegression.ps1'") 'development knowledge-tool list'
$oldLoop="foreach(`$regressionName in @('Invoke-Manager41710ReviewRegression.ps1','Invoke-Manager41711ReviewRegression.ps1','Invoke-Manager41712ReviewRegression.ps1')){"
$newLoop="foreach(`$regressionName in @('Invoke-Manager41710ReviewRegression.ps1','Invoke-Manager41711ReviewRegression.ps1','Invoke-ManagerRecoveryBehaviorRegression.ps1','Invoke-Manager41713ReviewRegression.ps1')){"
$dev=Replace-Once $dev $oldLoop $newLoop 'development review-regression loop'
$oldReviewPass="Write-Host 'Manager 4.17.10 + 4.17.11 + 4.17.12 review regression and release-instruction chain: PASS' -ForegroundColor Green"
$newReviewPass="`$entryModelValidator=Join-Path `$RepositoryRoot 'tools\Test-ManagerEntryReachabilityKnowledge.ps1'"+$nl+"Invoke-Child `$entryModelValidator @('-RepositoryRoot',`$RepositoryRoot)"+$nl+"`$entryEvidence=Join-Path `$evidence 'ENTRY_REACHABILITY_RESULT.json'"+$nl+"`$entryMatrix=Join-Path `$RepositoryRoot 'tools\Invoke-ManagerEntryReachabilityMatrix.ps1'"+$nl+"Invoke-Child `$entryMatrix @('-RepositoryRoot',`$RepositoryRoot,'-OutputPath',`$entryEvidence)"+$nl+"Write-Host 'Manager review regressions + release identity + process-entry reachability: PASS' -ForegroundColor Green"
$dev=Replace-Once $dev $oldReviewPass $newReviewPass 'development entry matrix insertion'
$dev=Replace-Once $dev '    review_regressions_pass=$true' ('    review_regressions_pass=$true'+$nl+'    entry_reachability_pass=$true') 'development evidence entry flag'
Write-Utf8 $devPath $dev
'@
$text=[regex]::Replace($text,$devPattern,{param($m)$devReplacement.TrimEnd()},1)

# Generated helper scripts always receive the repository root explicitly.
$reviewParam="param([string]`$RepositoryRoot=(Join-Path `$PSScriptRoot '..'))"
if(([regex]::Matches($text,[regex]::Escape($reviewParam))).Count-ne1){throw 'Generated review RepositoryRoot default is missing/ambiguous.'}
$text=$text.Replace($reviewParam,"param([Parameter(Mandatory=`$true)][string]`$RepositoryRoot)")
$section7='# 7. Run behavioral and real process-entry checks before closing the defect.'
if(([regex]::Matches($text,[regex]::Escape($section7))).Count-ne1){throw 'Behavioral section marker is missing/ambiguous.'}
$behaviorParamFix=@'
# Normalize the reusable behavior helper to the same explicit-root execution contract.
$behaviorPath=Join-Path $RepositoryRoot 'tools\Invoke-ManagerRecoveryBehaviorRegression.ps1'
$behavior=[IO.File]::ReadAllText($behaviorPath,[Text.Encoding]::UTF8)
$behavior=Replace-Once $behavior "param([string]`$RepositoryRoot=(Join-Path `$PSScriptRoot '..'))" 'param([Parameter(Mandatory=$true)][string]$RepositoryRoot)' 'recovery behavior required RepositoryRoot'
Write-Utf8 $behaviorPath $behavior

# 7. Run behavioral and real process-entry checks before closing the defect.
'@
$text=$text.Replace($section7,$behaviorParamFix.TrimEnd())

# SelfTests are validation, never source-generation. Execute them on an exact managed-set
# copy so runtime diagnostic state cannot contaminate manager/ before public-manifest binding.
$selfTestPattern=@'
(?m)^Run \$runtimePath @\('-SelfTest'\)\|Out-Null\r?\nRun \(Join-Path \$RepositoryRoot '[^']*KeelarynMenu\.ps1'\) @\('-SelfTest','-NoRootLauncher'\)\|Out-Null$
'@
$selfTestPattern=$selfTestPattern.Trim()
if(([regex]::Matches($text,$selfTestPattern)).Count-ne1){throw 'Base source-SelfTest block is missing/ambiguous.'}
$selfTestReplacement=@'
$selfTestRoot=Join-Path $EvidenceRoot 'managed-selftest'
$selfTestManager=Join-Path $selfTestRoot 'manager'
if(Test-Path -LiteralPath $selfTestRoot){Remove-Item -LiteralPath $selfTestRoot -Recurse -Force}
New-Item -ItemType Directory -Force -Path $selfTestManager|Out-Null
$selfTestInstall=Get-Content -LiteralPath (Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
foreach($raw in @($selfTestInstall.managed_files)){
    $rel=([string]$raw).Replace('/','\')
    $src=Join-Path (Join-Path $RepositoryRoot 'manager') $rel
    $dst=Join-Path $selfTestManager $rel
    if(-not(Test-Path -LiteralPath $src -PathType Leaf)){Fail('Managed SelfTest source missing: '+$rel)}
    $parent=Split-Path -Parent $dst
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    Copy-Item -LiteralPath $src -Destination $dst -Force
}
try{
    Run (Join-Path $selfTestManager 'product\runtime\Keelaryn__Manager.ps1') @('-SelfTest')|Out-Null
    Run (Join-Path $selfTestManager 'product\tools\KeelarynMenu.ps1') @('-SelfTest','-NoRootLauncher')|Out-Null
}finally{
    if(Test-Path -LiteralPath $selfTestRoot){Remove-Item -LiteralPath $selfTestRoot -Recurse -Force -ErrorAction SilentlyContinue}
}
'@
$text=[regex]::Replace($text,$selfTestPattern,{param($m)$selfTestReplacement.TrimEnd()},1)

$temp=Join-Path ([IO.Path]::GetTempPath()) ('Materialize-Manager41713Product-r4-'+[guid]::NewGuid().ToString('N')+'.ps1')
try{
    [IO.File]::WriteAllText($temp,$text,$Utf8)
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('R4 generated materializer parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
    exit [int]$LASTEXITCODE
}finally{
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
}
