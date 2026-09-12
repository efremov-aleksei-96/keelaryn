[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$menuPath=Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1'
function Assert([bool]$Condition,[string]$Message){if(-not$Condition){throw $Message}}
function F([string]$Path,[string]$Name){
    $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('Parser failed: '+$Path)}
    $rows=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name})
    if($rows.Count-ne1){throw('function '+$Name+' count='+$rows.Count)}
    return [string]$rows[0].Extent.Text
}

# Direct runtime/compat invocations that started in single-instance mode must also
# detect registry activation after acquiring the Manager mutation lock.
Invoke-Expression (F $runtimePath 'Assert-InvocationInstanceUnchanged')
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
Invoke-Expression (F $runtimePath 'Restart-UpdatedManager')
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

# Frontend UpdateHub/UpdateAll must bind runtime work to the same captured context.
Invoke-Expression (F $menuPath 'Invoke-Action')
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
Write-Host 'MANAGER 4.17.6 UPDATE CONTEXT REGRESSION: PASS' -ForegroundColor Green
