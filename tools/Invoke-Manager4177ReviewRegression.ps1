[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
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
& $p -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $RepositoryRoot 'tools\Invoke-Manager4176ReviewRegression.ps1') -RepositoryRoot $RepositoryRoot
if($LASTEXITCODE-ne0){throw 'Inherited Manager 4.17.6 regression failed.'}
Write-Host '  PASS inherited Manager 4.17.6 regression chain'

# P1: a newly installed Manager reached through a legacy UpdateAll restart must not
# silently bind Hub work to whichever registered instance happens to be active.
Invoke-Expression (Get-FunctionText $runtimePath 'Assert-UpdateAllContextSafe')
$UpdateAll=$true
$ExpectedInstanceId=$null
$ExpectedSingleInstance=$false
$script:InstanceRegistryActive=$true
$blocked=$false
try { Assert-UpdateAllContextSafe } catch { $blocked=$_.Exception.Message -like '*UpdateAll*context*' -or $_.Exception.Message -like '*retry*current Manager*' }
Assert $blocked 'Tokenless UpdateAll did not fail closed when a multi-Hub registry was already active.'
$ExpectedInstanceId='77777777-7777-7777-7777-777777777777'
$ok=$true
try { Assert-UpdateAllContextSafe } catch { $ok=$false }
Assert $ok 'UpdateAll rejected an explicit ExpectedInstanceId.'
$ExpectedInstanceId=$null;$ExpectedSingleInstance=$true
$ok=$true
try { Assert-UpdateAllContextSafe } catch { $ok=$false }
Assert $ok 'UpdateAll rejected ExpectedSingleInstance.'
$ExpectedSingleInstance=$false;$script:InstanceRegistryActive=$false
$ok=$true
try { Assert-UpdateAllContextSafe } catch { $ok=$false }
Assert $ok 'Tokenless UpdateAll was rejected in unchanged single-instance compatibility mode.'
$UpdateAll=$false;$script:InstanceRegistryActive=$true
$ok=$true
try { Assert-UpdateAllContextSafe } catch { $ok=$false }
Assert $ok 'Non-UpdateAll invocation was incorrectly subject to legacy restart guard.'
Write-Host '  PASS legacy/no-token UpdateAll fails closed only for active multi-Hub context'

# P2: an existing registry is success only when the full registry + active selection
# resolves coherently. Mere instances.json existence is never sufficient.
Invoke-Expression (Get-FunctionText $runtimePath 'Test-ExistingInstanceRegistryForInitialization')
$temp=Join-Path ([IO.Path]::GetTempPath()) ('k4177_registry_'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($temp)
try {
    $script:InstanceRegistryFile=Join-Path $temp 'instances.json'
    $script:InstanceRegistryActive=$false;$script:ActiveInstanceId=$null
    function Resolve-RegisteredInstanceContextEarly { throw 'synthetic invalid active selection' }
    Assert (-not(Test-ExistingInstanceRegistryForInitialization)) 'Missing registry file should not report an initialized registry.'
    [IO.File]::WriteAllText($script:InstanceRegistryFile,'{}',(New-Object Text.UTF8Encoding($false)))
    $blocked=$false
    try { $null=Test-ExistingInstanceRegistryForInitialization } catch { $blocked=$_.Exception.Message -like '*Existing multi-Hub registry is invalid*synthetic invalid active selection*' }
    Assert $blocked 'Existing invalid registry did not fail closed during initialization.'
    function Resolve-RegisteredInstanceContextEarly {
        $script:InstanceRegistryActive=$true
        $script:ActiveInstanceId='88888888-8888-8888-8888-888888888888'
        return $true
    }
    Assert (Test-ExistingInstanceRegistryForInitialization) 'Valid existing registry did not report initialized state.'
} finally {
    if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force}
}
Write-Host '  PASS existing registry requires coherent registry + active selection validation'

$invokeUpdate=Get-FunctionText $runtimePath 'Invoke-Update'
$guardIndex=$invokeUpdate.IndexOf('Assert-UpdateAllContextSafe',[StringComparison]::Ordinal)
$sideEffectIndex=$invokeUpdate.IndexOf('Ensure-DesktopShortcut',[StringComparison]::Ordinal)
Assert ($guardIndex-ge0-and$sideEffectIndex-gt$guardIndex) 'Invoke-Update does not enforce UpdateAll context safety before side effects.'
$initialize=Get-FunctionText $runtimePath 'Invoke-InitializeInstanceRegistry'
Assert $initialize.Contains('Test-ExistingInstanceRegistryForInitialization') 'Registry initializer does not validate an existing registry before success.'
Assert (-not$initialize.Contains("if(Test-Path -LiteralPath `$script:InstanceRegistryFile -PathType Leaf){Write-Host 'Multi-Hub registry is already initialized.'")) 'Registry initializer still treats file existence alone as success.'
Write-Host '  PASS corrective source contracts are wired at transaction boundaries'

Write-Host 'MANAGER 4.17.7 REVIEW REGRESSION: PASS' -ForegroundColor Green
