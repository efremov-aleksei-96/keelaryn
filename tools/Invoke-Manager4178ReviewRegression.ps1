[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
function Assert([bool]$Condition,[string]$Message){if(-not$Condition){throw $Message}}
function Get-FunctionAst([string]$Path,[string]$Name){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('Parser failed for '+$Path)}
    $rows=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name})
    if($rows.Count-ne1){throw('function '+$Name+' count='+$rows.Count)}
    return $rows[0]
}
function Get-FunctionText([string]$Path,[string]$Name){return [string](Get-FunctionAst $Path $Name).Extent.Text}
function Get-FunctionCommandAsts($FunctionAst,[string]$CommandName){
    return @($FunctionAst.Body.FindAll({param($node)
        if($node-isnot[Management.Automation.Language.CommandAst]){return $false}
        return [string]::Equals([string]$node.GetCommandName(),$CommandName,[StringComparison]::OrdinalIgnoreCase)
    },$true))
}
$p=Join-Path $PSHOME 'powershell.exe'
& $p -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $RepositoryRoot 'tools\Invoke-Manager4177ReviewRegression.ps1') -RepositoryRoot $RepositoryRoot
if($LASTEXITCODE-ne0){throw 'Inherited Manager 4.17.7 regression failed.'}
Write-Host '  PASS inherited Manager 4.17.7 regression chain'

$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$frontendPath=Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1'
$aliasPath=Join-Path $RepositoryRoot 'manager\compat\commands\UPDATE_ALL.cmd'
$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
$alias=[IO.File]::ReadAllText($aliasPath,[Text.Encoding]::UTF8)

# P1: the documented compatibility alias must enter the token-capturing frontend path,
# while the 4.17.7 legacy-restart guard remains in the runtime regression chain.
Assert $alias.Contains('product\tools\KeelarynMenu.ps1') 'UPDATE_ALL.cmd does not route through the frontend.'
Assert $alias.Contains('-Action UpdateAll') 'UPDATE_ALL.cmd does not request frontend UpdateAll.'
Assert $alias.Contains('-NoRootLauncher') 'UPDATE_ALL.cmd may recurse through the root launcher.'
Assert (-not$alias.Contains('Keelaryn__Manager.ps1" -UpdateAll')) 'UPDATE_ALL.cmd still directly invokes tokenless runtime UpdateAll.'
Assert $runtime.Contains("'UPDATE_ALL.cmd' = [ordered]@{ kind='frontend'; frontend_action='UpdateAll'; pause='always' }") 'Runtime compatibility specification does not preserve frontend routing.'
$generator=Get-FunctionText $runtimePath 'Get-GeneratedCompatibilityCommandText'
Assert $generator.Contains("if ([string]`$spec.kind -eq 'frontend')") 'Compatibility generator lacks the frontend command kind.'
$invokeAction=Get-FunctionText $frontendPath 'Invoke-Action'
Assert $invokeAction.Contains("`$args+=@('-ExpectedInstanceId',[string]`$ctx.InstanceId)") 'Frontend UpdateAll no longer captures active instance_id.'
Assert $invokeAction.Contains("`$args+=@('-ExpectedSingleInstance')") 'Frontend UpdateAll no longer captures single-instance expectation.'
Write-Host '  PASS UPDATE_ALL compatibility alias preserves explicit Hub context via frontend'

# P2: staged registration state must be APPROVED as well as content/identity-consistent.
Invoke-Expression (Get-FunctionText $runtimePath 'Assert-RegisteredInstanceActivationEligible')
$script:baselineCalls=0
$script:syntheticStatus='candidate'
function Assert-RegisteredInstanceBaseline { param($Row) $script:baselineCalls++; return $true }
function Get-InstanceStatePaths { param([string]$InstanceId) return [pscustomobject]@{Current='synthetic-current.zip'} }
function Get-CompatibilityCheckpointIdentityFast { param([string]$Path) return [pscustomobject]@{ArtifactStatus=$script:syntheticStatus} }
$row=[pscustomobject]@{instance_id='99999999-9999-9999-9999-999999999999'}
$blocked=$false
try{$null=Assert-RegisteredInstanceActivationEligible $row}catch{$blocked=$_.Exception.Message -like '*approved checkpoint*before registration can commit*'}
Assert $blocked 'Registration activation guard accepted a CANDIDATE checkpoint.'
Assert ($script:baselineCalls-eq1) 'Registration activation guard skipped full Hub/CURRENT baseline validation.'
$script:syntheticStatus='approved';$script:baselineCalls=0
$ok=$true
try{$null=Assert-RegisteredInstanceActivationEligible $row}catch{$ok=$false}
Assert $ok 'Registration activation guard rejected an APPROVED coherent checkpoint.'
Assert ($script:baselineCalls-eq1) 'Approved registration did not retain full baseline validation.'

# Verify the actual transaction commands rather than broad string absence. An earlier
# baseline check is useful defense-in-depth; after staging, however, the fresh validation
# immediately preceding the registry commit must be the stronger activation-eligibility guard.
$registerAst=Get-FunctionAst $runtimePath 'Invoke-RegisterExistingInstance'
$stages=@(Get-FunctionCommandAsts $registerAst 'New-RegisteredInstanceStateFromVault')
$guards=@(Get-FunctionCommandAsts $registerAst 'Assert-RegisteredInstanceActivationEligible')
$commits=@(Get-FunctionCommandAsts $registerAst 'Write-ManagerInstanceRegistry')
$directBaselines=@(Get-FunctionCommandAsts $registerAst 'Assert-RegisteredInstanceBaseline')
Assert ($stages.Count-eq1) ('Registration staging command count mismatch: '+$stages.Count)
Assert ($guards.Count-eq1) ('Registration activation-guard command count mismatch: '+$guards.Count)
Assert ($commits.Count-eq1) ('Registration registry-commit command count mismatch: '+$commits.Count)
$stageOffset=[int]$stages[0].Extent.StartOffset
$guardOffset=[int]$guards[0].Extent.StartOffset
$commitOffset=[int]$commits[0].Extent.StartOffset
Assert ($stageOffset-lt$guardOffset-and$guardOffset-lt$commitOffset) 'Activation eligibility is not revalidated after staging and before registry commit.'
$weakBetween=@($directBaselines|Where-Object{[int]$_.Extent.StartOffset-gt$stageOffset-and[int]$_.Extent.StartOffset-lt$commitOffset})
Assert ($weakBetween.Count-eq0) 'Registration still uses a weaker direct baseline validation at the final commit boundary.'
Write-Host '  PASS existing-Hub registration rejects non-APPROVED activation baselines before commit'

Write-Host 'MANAGER 4.17.8 REVIEW REGRESSION: PASS' -ForegroundColor Green
