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

# Replace the original parallel-transition assumption with the canonical state x operation -> rule model.
$statePattern='(?s)\$smPath=Join-Path \$RepositoryRoot ''tests\\knowledge\\state-machines\\multi-hub\.json'';\$sm=Get-Content \$smPath -Raw -Encoding UTF8\|ConvertFrom-Json.*?Write-Json \$smPath \$sm'
$stateMatches=[regex]::Matches($text,$statePattern)
if($stateMatches.Count-ne1){throw('Canonical state-machine materialization block count='+$stateMatches.Count)}
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

# Risk-map surfaces do not carry a parallel `states` field. Bind the new coverage through
# the existing root-cause/regression/rule references instead.
$riskPattern='(?s)\$riskPath=Join-Path \$RepositoryRoot ''tests\\knowledge\\risk-map\.json'';\$risk=Get-Content \$riskPath -Raw -Encoding UTF8\|ConvertFrom-Json;\$surface=@\(\$risk\.surfaces\|Where-Object\{\[string\]\$_\.id-ceq''S-RUNTIME-REGISTRY-RESOLUTION''\}\);if\(\$surface\.Count-ne1\)\{Fail ''S-RUNTIME-REGISTRY-RESOLUTION missing/ambiguous\.''\};.*?Write-Json \$riskPath \$risk'
$riskMatches=[regex]::Matches($text,$riskPattern)
if($riskMatches.Count-ne1){throw('Canonical risk-map materialization block count='+$riskMatches.Count)}
$riskReplacement=@'
$riskPath=Join-Path $RepositoryRoot 'tests\knowledge\risk-map.json';$risk=Get-Content $riskPath -Raw -Encoding UTF8|ConvertFrom-Json
$surface=@($risk.surfaces|Where-Object{[string]$_.id-ceq'S-RUNTIME-REGISTRY-RESOLUTION'});if($surface.Count-ne1){Fail 'S-RUNTIME-REGISTRY-RESOLUTION missing/ambiguous.'}
foreach($v in @('RC-ENTRY-001')){if(@($surface[0].root_cause_classes)-notcontains$v){$surface[0].root_cause_classes=@($surface[0].root_cause_classes)+@($v)}}
foreach($v in @('tools/Invoke-ManagerEntryReachabilityMatrix.ps1','tools/Invoke-ManagerRecoveryBehaviorRegression.ps1','tools/Invoke-Manager41713ReviewRegression.ps1')){if(@($surface[0].regressions)-notcontains$v){$surface[0].regressions=@($surface[0].regressions)+@($v)}}
foreach($v in @('R-CURRENT-MISSING-LIST','R-CURRENT-CORRUPT-LIST','R-CURRENT-MISSING-SWITCH','R-CURRENT-CORRUPT-SWITCH','R-CURRENT-MISSING-BIND','R-CURRENT-CORRUPT-BIND','R-CURRENT-MISSING-UPDATE-MANAGER','R-CURRENT-CORRUPT-UPDATE-MANAGER')){if(@($surface[0].state_machine_rules)-notcontains$v){$surface[0].state_machine_rules=@($surface[0].state_machine_rules)+@($v)}}
Write-Json $riskPath $risk
'@
$text=[regex]::Replace($text,$riskPattern,{param($m)$riskReplacement.TrimEnd()},1)

$temp=Join-Path ([IO.Path]::GetTempPath()) ('Materialize-Manager41713Product-r2-'+[guid]::NewGuid().ToString('N')+'.ps1')
try{
    [IO.File]::WriteAllText($temp,$text,$Utf8)
    $tokens=$null;$errors=$null;[void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('R2 materializer parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
    exit [int]$LASTEXITCODE
}finally{Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue}
