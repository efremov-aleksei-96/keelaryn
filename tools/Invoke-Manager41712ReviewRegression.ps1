[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [switch]$LeafOnly
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Assert([bool]$Condition,[string]$Message){if(-not$Condition){Fail $Message}}
function Get-FunctionAst([string]$Path,[string]$Name){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){Fail('Parser failed for '+$Path+': '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $rows=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name})
    if($rows.Count-ne1){Fail('function '+$Name+' count='+$rows.Count)}
    return $rows[0]
}
function Get-FunctionText([string]$Path,[string]$Name){return [string](Get-FunctionAst $Path $Name).Extent.Text}
function Pass([string]$Id,[string]$Text){Write-Host ('  PASS '+$Id+' '+$Text) -ForegroundColor Green}

$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$menuPath=Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1'
$installPath=Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json'
$releasePath=Join-Path $RepositoryRoot 'manager\product\manager_release.json'
$readmePath=Join-Path $RepositoryRoot 'manager\README_FIRST.md'
foreach($p in @($runtimePath,$menuPath,$installPath,$releasePath,$readmePath)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Required Manager 4.17.12 path missing: '+$p)}}

if(-not$LeafOnly){
    $p=Join-Path $PSHOME 'powershell.exe'
    & $p -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $RepositoryRoot 'tools\Invoke-Manager4179ConvergenceRegression.ps1') -RepositoryRoot $RepositoryRoot
    if($LASTEXITCODE-ne0){Fail 'Inherited Manager 4.17.9 convergence/recovery regression failed.'}
    Pass 'RUNTIME' 'target switch remains independently validated and recovery-safe'
}

$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
$menu=[IO.File]::ReadAllText($menuPath,[Text.Encoding]::UTF8)
$readme=[IO.File]::ReadAllText($readmePath,[Text.Encoding]::UTF8)
$install=Get-Content -LiteralPath $installPath -Raw -Encoding UTF8|ConvertFrom-Json
$release=Get-Content -LiteralPath $releasePath -Raw -Encoding UTF8|ConvertFrom-Json
Assert ($runtime -match '(?m)^\$ManagerVersion = "4\.17\.12"$' -or $runtime -match '(?m)^\$ManagerVersion = "4\.17\.13"$') 'Runtime version marker is not an accepted 4.17.12/4.17.13 successor.'
Assert (@('4.17.12','4.17.13')-contains[string]$install.manager_version) 'INSTALLATION manager_version is not an accepted 4.17.12/4.17.13 successor.'
Assert (@('4.17.12','4.17.13')-contains[string]$release.manager_version) 'manager_release manager_version is not an accepted 4.17.12/4.17.13 successor.'
Assert ($readme.Contains('# Keelaryn Manager '+[string]$install.manager_version)) 'README does not identify the current validated successor version.'
if([string]$install.manager_version-ceq'4.17.12'){Assert ($readme.Contains('production-installed Manager 4.17.11 -> 4.17.12')) 'README does not identify the 4.17.11 -> 4.17.12 production qualification transition.'}
Pass 'IDENTITY' '4.17.12 behavior remains coherent on the current validated successor'

$rowsText=Get-FunctionText $menuPath 'Get-FrontendRegistryRows'
$showText=Get-FunctionText $menuPath 'Show-HubManagementMenu'
Assert (-not$rowsText.Contains('Get-FrontendInstanceContext')) 'Frontend registry enumeration still depends on resolved active context.'
Assert ($rowsText.Contains('instances.json')) 'Frontend recovery enumeration no longer reads the registry.'
Assert ($rowsText.Contains('ConvertTo-CanonicalFrontendInstanceId')) 'Frontend recovery enumeration no longer canonicalizes instance IDs.'
Assert ($rowsText.Contains('HashSet[string]')) 'Frontend recovery enumeration lacks duplicate instance-id rejection.'
Assert ($showText.Contains('Active selection is invalid/unresolved. Choose a registered Hub to recover active selection.')) 'Manage Hubs does not expose explicit unresolved-active recovery mode.'
Assert ($showText.Contains('Get-FrontendRegistryRows')) 'Manage Hubs recovery mode does not enumerate the registry independently.'
Assert ($showText.Contains('-SwitchInstanceId')) 'Manage Hubs recovery mode does not call target-driven runtime switching.'
Assert ($showText.Contains('Select recovery Hub number')) 'Manage Hubs recovery mode lacks explicit target selection.'
Assert (-not$showText.Contains('switching is disabled')) 'Stale frontend message still disables recovery switching.'
Assert ($menu.Contains("'OpenHubInbox' { `$ctx=Get-FrontendInstanceContext;if(`$ctx.RegistryActive-and-not`$ctx.InstanceId){Fail('Multi-Hub registry is unresolved; active Hub inbox cannot be opened.')")) 'Non-recovery active-instance actions were broadened instead of remaining fail-closed.'
Pass 'SURFACE' 'Manage Hubs recovery is target-driven while unrelated active-context actions stay fail-closed'

# Execute only the pure/safe frontend registry-enumeration slice against synthetic state.
$convertText=Get-FunctionText $menuPath 'ConvertTo-CanonicalFrontendInstanceId'
. ([scriptblock]::Create($convertText+"`n"+$rowsText))
$temp=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-41712-frontend-'+[guid]::NewGuid().ToString('N'))
try{
    [void][IO.Directory]::CreateDirectory($temp)
    $StateLayoutActive=$true
    $StateRoot=$temp
    $idA='11111111-1111-1111-1111-111111111111'
    $idB='22222222-2222-2222-2222-222222222222'
    $registry=[ordered]@{schema='keelaryn.manager.instances.v1';registry_revision=1;instances=@(
        [ordered]@{instance_id=$idA;name='Hub A';vault_path='C:\synthetic\hub-a';registered_utc='2026-09-13T00:00:00Z'},
        [ordered]@{instance_id=$idB;name='Hub B';vault_path='C:\synthetic\hub-b';registered_utc='2026-09-13T00:00:00Z'}
    )}
    [IO.File]::WriteAllText((Join-Path $temp 'instances.json'),(($registry|ConvertTo-Json -Depth 6)+"`n"),$Utf8NoBom)
    $active=Join-Path $temp 'active_instance.json'

    $rows=@(Get-FrontendRegistryRows)
    Assert ($rows.Count-eq2) 'Valid registry is not enumerable when active_instance.json is missing.'
    Assert (@($rows.instance_id)-contains$idA-and@($rows.instance_id)-contains$idB) 'Missing-active recovery enumeration lost registered targets.'
    Pass 'MISSING' 'valid registry remains enumerable with missing active selection'

    [IO.File]::WriteAllText($active,'{ not-json',$Utf8NoBom)
    $rows=@(Get-FrontendRegistryRows)
    Assert ($rows.Count-eq2) 'Valid registry is not enumerable when active_instance.json is corrupt.'
    Pass 'CORRUPT' 'valid registry remains enumerable with corrupt active selection'

    [IO.File]::WriteAllText($active,('{"schema":"keelaryn.manager.active-instance.v1","instance_id":"33333333-3333-3333-3333-333333333333"}'+"`n"),$Utf8NoBom)
    $rows=@(Get-FrontendRegistryRows)
    Assert ($rows.Count-eq2) 'Valid registry is not enumerable when active selection names an unregistered instance.'
    Pass 'UNRESOLVED' 'valid registry remains enumerable with unresolved active selection'

    $bad=[ordered]@{schema='keelaryn.manager.instances.v1';registry_revision=2;instances=@(
        [ordered]@{instance_id=$idA;name='Hub A';vault_path='C:\synthetic\hub-a'},
        [ordered]@{instance_id=$idA;name='Duplicate';vault_path='C:\synthetic\other'}
    )}
    [IO.File]::WriteAllText((Join-Path $temp 'instances.json'),(($bad|ConvertTo-Json -Depth 6)+"`n"),$Utf8NoBom)
    $blocked=$false
    try{$null=Get-FrontendRegistryRows}catch{$blocked=$true}
    Assert $blocked 'Invalid registry must not be presented as a recovery switch target list.'
    Pass 'REGISTRY' 'registry corruption remains fail-closed'
}finally{if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}}

$copyCurrentText=Get-FunctionText $menuPath 'Copy-CurrentForChatGPT'
Assert ($copyCurrentText.Contains('Assert-FrontendCurrentArchiveBinding $archive ([string]$Context.InstanceId)')) 'ChatGPT CURRENT export does not validate embedded instance identity against captured context.'
Assert ($copyCurrentText.Contains('[IO.FileShare]::Read')) 'ChatGPT CURRENT export does not hold a read lock from identity validation through byte copy.'
Assert ($menu.Contains('function Assert-FrontendCurrentArchiveBinding')) 'Frontend CURRENT identity-binding validator is missing.'
Assert ($menu.Contains("CURRENT belongs to a different instance_id")) 'Frontend CURRENT wrong-instance failure contract is missing.'
Assert ($copyCurrentText.Contains('Previous exchange artifact is preserved at')) 'ChatGPT CURRENT post-publication failure does not preserve/report rollback data.'
$postVerifyIndex=$copyCurrentText.IndexOf('$publishedHash=Get-FileSha256Hex $target',[StringComparison]::Ordinal)
$backupCleanupIndex=$copyCurrentText.IndexOf('if(Test-Path -LiteralPath $backup){Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue}',[StringComparison]::Ordinal)
Assert ($postVerifyIndex-ge0-and$backupCleanupIndex-gt$postVerifyIndex) 'ChatGPT CURRENT rollback backup is deleted before post-publication verification.'
Write-Host '  PASS CURRENT export identity binding is enforced under a locked source artifact'
Write-Host 'MANAGER 4.17.12 REVIEW REGRESSION: PASS' -ForegroundColor Green
