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
$pattern='(?s)\$smPath=Join-Path \$RepositoryRoot ''tests\\knowledge\\state-machines\\multi-hub\.json'';\$sm=Get-Content \$smPath -Raw -Encoding UTF8\|ConvertFrom-Json.*?Write-Json \$smPath \$sm'
$matches=[regex]::Matches($text,$pattern)
if($matches.Count-ne1){throw('Canonical state-machine materialization block count='+$matches.Count)}
$replacement=@'
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
$text=[regex]::Replace($text,$pattern,{param($m)$replacement.TrimEnd()},1)
$temp=Join-Path ([IO.Path]::GetTempPath()) ('Materialize-Manager41713Product-r2-'+[guid]::NewGuid().ToString('N')+'.ps1')
try{
    [IO.File]::WriteAllText($temp,$text,$Utf8)
    $tokens=$null;$errors=$null;[void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('R2 materializer parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
    exit [int]$LASTEXITCODE
}finally{Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue}
