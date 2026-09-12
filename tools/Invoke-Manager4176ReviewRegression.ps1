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

# Direct runtime/compat invocations that started in single-instance mode must
# detect registry activation after acquiring the Manager mutation lock even
# without an explicit frontend expectation token.
Invoke-Expression (Get-FunctionText $runtimePath 'Assert-InvocationInstanceUnchanged')
$ExpectedSingleInstance=$false
$script:InstanceRegistryActive=$false
$script:InvocationInstanceId=$null
function Read-InstanceRegistryEarly { return [pscustomobject]@{schema='keelaryn.manager.instances.v1';instances=@()} }
$blocked=$false
try { Assert-InvocationInstanceUnchanged } catch { $blocked=$_.Exception.Message -like '*registry appeared*' }
Assert $blocked 'Direct single-instance mutation guard did not detect registry activation without an explicit frontend token.'
function Read-InstanceRegistryEarly { return $null }
$clean=$true
try { Assert-InvocationInstanceUnchanged } catch { $clean=$false }
Assert $clean 'Direct single-instance mutation guard rejected unchanged single-instance state.'
Write-Host '  PASS direct single-instance post-lock registry revalidation'

# UpdateAll may restart after a Manager update. The restarted process must inherit
# exactly the original Hub expectation, not re-resolve whichever Hub is active later.
Invoke-Expression (Get-FunctionText $runtimePath 'Restart-UpdatedManager')
$temp=Join-Path ([IO.Path]::GetTempPath()) ('k4176restart_'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory((Join-Path $temp 'product\runtime'))
$capture=Join-Path $temp 'capture.json'
$fake=@'
param([switch]$UpdateAll,[switch]$UpdateManager,[string]$ExpectedInstanceId,[switch]$ExpectedSingleInstance)
[ordered]@{UpdateAll=[bool]$UpdateAll;UpdateManager=[bool]$UpdateManager;ExpectedInstanceId=[string]$ExpectedInstanceId;ExpectedSingleInstance=[bool]$ExpectedSingleInstance}|ConvertTo-Json -Compress|Set-Content -LiteralPath $env:K4176_CAPTURE -Encoding UTF8
exit 0
'@
[IO.File]::WriteAllText((Join-Path $temp 'product\runtime\Keelaryn__Manager.ps1'),$fake,(New-Object Text.UTF8Encoding($false)))
try {
    $Root=$temp;$StateLayoutReceipt=Join-Path $temp 'state\layout.json';$UpdateAll=$true;$UpdateManager=$false
    $env:K4176_CAPTURE=$capture
    $ExpectedInstanceId=$null;$ExpectedSingleInstance=$false
    $script:InstanceRegistryActive=$true;$script:InvocationInstanceId='55555555-5555-5555-5555-555555555555'
    $rc=Restart-UpdatedManager
    Assert ($rc-eq0) 'Active-instance UpdateAll restart failed.'
    $doc=Get-Content -LiteralPath $capture -Raw -Encoding UTF8|ConvertFrom-Json
    Assert ([bool]$doc.UpdateAll) 'UpdateAll was not preserved across restart.'
    Assert ([string]$doc.ExpectedInstanceId-ceq'55555555-5555-5555-5555-555555555555') 'Active instance identity was not preserved across UpdateAll restart.'
    Assert (-not[bool]$doc.ExpectedSingleInstance) 'Active-instance restart incorrectly became single-instance expectation.'

    Remove-Item -LiteralPath $capture -Force
    $ExpectedInstanceId=$null;$ExpectedSingleInstance=$false
    $script:InstanceRegistryActive=$false;$script:InvocationInstanceId=$null
    $rc=Restart-UpdatedManager
    Assert ($rc-eq0) 'Single-instance UpdateAll restart failed.'
    $doc=Get-Content -LiteralPath $capture -Raw -Encoding UTF8|ConvertFrom-Json
    Assert ([bool]$doc.ExpectedSingleInstance) 'Single-instance expectation was not preserved across UpdateAll restart.'
    Assert ([string]::IsNullOrWhiteSpace([string]$doc.ExpectedInstanceId)) 'Single-instance restart unexpectedly supplied ExpectedInstanceId.'
} finally {
    Remove-Item Env:K4176_CAPTURE -ErrorAction SilentlyContinue
    if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force}
}
Write-Host '  PASS UpdateAll restart preserves captured Hub expectation'

# Frontend UpdateHub/UpdateAll bind runtime work to the same captured context.
Invoke-Expression (Get-FunctionText $menuPath 'Invoke-Action')
$script:CapturedArgs=@()
function Invoke-Manager([string[]]$ManagerArgs){$script:CapturedArgs=@($ManagerArgs);return 0}
function Get-QuickStatus { return [pscustomobject]@{ManagerUpdates=0;HubApproved=1} }
function Write-UiHost {}
function Set-ActionSemantic {}
function Get-FrontendInstanceContext { return [pscustomobject]@{RegistryActive=$true;InstanceId='66666666-6666-6666-6666-666666666666'} }
$rc=Invoke-Action 'UpdateHub' $null
Assert ($rc-eq0) 'Frontend UpdateHub failed.'
Assert (($script:CapturedArgs-join' ')-ceq'-UpdateHub -ExpectedInstanceId 66666666-6666-6666-6666-666666666666') 'Frontend UpdateHub did not pass active instance expectation.'
$script:CapturedArgs=@();$rc=Invoke-Action 'UpdateAll' $null
Assert ($rc-eq0) 'Frontend UpdateAll failed.'
Assert (($script:CapturedArgs-join' ')-ceq'-UpdateAll -ExpectedInstanceId 66666666-6666-6666-6666-666666666666') 'Frontend UpdateAll did not pass active instance expectation.'
function Get-FrontendInstanceContext { return [pscustomobject]@{RegistryActive=$false;InstanceId=$null} }
$script:CapturedArgs=@();$rc=Invoke-Action 'UpdateHub' $null
Assert (($script:CapturedArgs-join' ')-ceq'-UpdateHub -ExpectedSingleInstance') 'Frontend UpdateHub did not pass single-instance expectation.'
$script:CapturedArgs=@();$rc=Invoke-Action 'UpdateAll' $null
Assert (($script:CapturedArgs-join' ')-ceq'-UpdateAll -ExpectedSingleInstance') 'Frontend UpdateAll did not pass single-instance expectation.'
Write-Host '  PASS frontend Hub update actions carry captured-context token'

$rt=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
Assert $rt.Contains('ExpectedSingleInstance is valid only with -UpdateHub or -UpdateAll.') 'ExpectedSingleInstance UpdateAll contract missing.'
Assert $rt.Contains('ExpectedInstanceId is valid only with -UpdateHub or -UpdateAll.') 'ExpectedInstanceId UpdateAll contract missing.'
Write-Host 'MANAGER 4.17.6 REVIEW REGRESSION: PASS' -ForegroundColor Green
