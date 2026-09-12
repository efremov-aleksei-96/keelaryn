[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$menuPath=Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1'
function Assert([bool]$Condition,[string]$Message){if(-not$Condition){throw $Message}}
function Get-FunctionText([string]$Path,[string]$Name){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('Parser failed for '+$Path)}
    $rows=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name})
    if($rows.Count-ne1){throw('function '+$Name+' count='+$rows.Count)}
    return [string]$rows[0].Extent.Text
}
$p=Join-Path $PSHOME 'powershell.exe'
& $p -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $RepositoryRoot 'tools\Invoke-Manager4175ReviewRegression.ps1') -RepositoryRoot $RepositoryRoot
if($LASTEXITCODE-ne0){throw 'Inherited Manager 4.17.5 regression failed.'}
Write-Host '  PASS inherited Manager 4.17.5 regression chain'

# P1: ExpectedSingleInstance must be freshly revalidated at the post-lock guard,
# even when startup cached InstanceRegistryActive=false.
Invoke-Expression (Get-FunctionText $runtimePath 'Assert-InvocationInstanceUnchanged')
$ExpectedSingleInstance=$true
$script:InstanceRegistryActive=$false
$script:InvocationInstanceId=$null
function Read-InstanceRegistryEarly { return [pscustomobject]@{schema='keelaryn.manager.instances.v1';instances=@()} }
$blocked=$false
try { Assert-InvocationInstanceUnchanged 'Hub update' }
catch { $blocked=$_.Exception.Message -like '*single-instance*' -or $_.Exception.Message -like '*registry*' }
Assert $blocked 'ExpectedSingleInstance post-lock guard did not fail closed when registry appeared after startup resolution.'
function Read-InstanceRegistryEarly { return $null }
$clean=$true
try { Assert-InvocationInstanceUnchanged 'Hub update' } catch { $clean=$false }
Assert $clean 'ExpectedSingleInstance post-lock guard rejected a still-single-instance state.'
Write-Host '  PASS single-instance expectation fresh post-lock revalidation'

# P2: active Hub inbox scans must not depend on the global Manager inbox existing.
Invoke-Expression (Get-FunctionText $menuPath 'Get-QuickStatus')
$temp=Join-Path ([IO.Path]::GetTempPath()) ('k4176_status_'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($temp)
try {
    $Inbox=Join-Path $temp 'missing-manager-inbox'
    $Logs=Join-Path $temp 'logs';[void][IO.Directory]::CreateDirectory($Logs)
    $LayoutRoot=Join-Path $temp 'layout';[void][IO.Directory]::CreateDirectory($LayoutRoot)
    $TestsRoot=Join-Path $temp 'tests'
    $hubRoot=Join-Path $temp 'hub';[void][IO.Directory]::CreateDirectory($hubRoot)
    $activeInbox=Join-Path $temp 'active-hub-inbox';[void][IO.Directory]::CreateDirectory($activeInbox)
    [IO.File]::WriteAllText((Join-Path $activeInbox 'Keelaryn__Hub_APPROVED_test.zip'),'approved')
    [IO.File]::WriteAllText((Join-Path $activeInbox 'Keelaryn__Hub_CANDIDATE_test.zip'),'candidate')
    function Read-ManagerVersion { return '4.17.6' }
    function Get-QuickHubBinding { return [pscustomobject]@{Path=$hubRoot;Source='test'} }
    function Get-FrontendInstanceContext { return [pscustomobject]@{RegistryActive=$true;InstanceId='44444444-4444-4444-4444-444444444444';Name='Test Hub';HubInbox=$activeInbox} }
    $status=Get-QuickStatus
    Assert ([int]$status.ManagerUpdates-eq0) 'Missing global Manager inbox should yield zero Manager updates.'
    Assert ([int]$status.HubApproved-eq1) 'Active Hub APPROVED scan incorrectly depends on global Manager inbox existence.'
    Assert ([int]$status.HubCandidate-eq1) 'Active Hub CANDIDATE scan incorrectly depends on global Manager inbox existence.'
} finally {
    if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force}
}
Write-Host '  PASS active Hub inbox scan independent of global Manager inbox'

Write-Host 'MANAGER 4.17.6 REVIEW REGRESSION: PASS' -ForegroundColor Green
