[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [string]$EvidenceRoot=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Utf8=New-Object Text.UTF8Encoding($false)
function Replace-TargetOnce([string]$Path,[string]$Old,[string]$New,[string]$Label){
    $s=[IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8)
    $count=[regex]::Matches($s,[regex]::Escape($Old)).Count
    if($count-ne1){throw($Label+' count='+$count)}
    [IO.File]::WriteAllText($Path,$s.Replace($Old,$New),$Utf8)
}
$source=Join-Path $PSScriptRoot 'Materialize-Manager41713EntryPolicyR1.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw 'Entry-policy R1 materializer is missing.'}
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)

$old='$policyRun="$entryPolicyValidator='
$new='$policyRun="`$entryPolicyValidator='
$count=[regex]::Matches($text,[regex]::Escape($old)).Count
if($count-ne1){throw('R1 entry-policy interpolation prefix count='+$count)}
$text=$text.Replace($old,$new)

# Authoritative repository source is LF-preserved (-text); R1's oldSelf matcher used CRLF.
# Patch only the literal matcher token, not generated product/source content.
$oldSelfBreak='`r`nInvoke-Child `$menu @(''-SelfTest'',''-NoRootLauncher'')'
$newSelfBreak='`nInvoke-Child `$menu @(''-SelfTest'',''-NoRootLauncher'')'
$selfBreakCount=[regex]::Matches($text,[regex]::Escape($oldSelfBreak)).Count
if($selfBreakCount-ne1){throw('R1 source-SelfTest line-ending matcher count='+$selfBreakCount)}
$text=$text.Replace($oldSelfBreak,$newSelfBreak)

# PowerShell represents $true/$false as VariableExpressionAst nodes. They are syntax literals,
# not Manager action variables, so the completeness guard must normalize them out.
$oldBool=@'
|Where-Object{$_-cne'script:InstanceRegistryActive'}|Sort-Object -Unique)
'@
$newBool=@'
|Where-Object{$_-cne'script:InstanceRegistryActive'-and$_-cne'true'-and$_-cne'false'}|Sort-Object -Unique)
'@
$oldBool=$oldBool.Trim();$newBool=$newBool.Trim()
$boolCount=[regex]::Matches($text,[regex]::Escape($oldBool)).Count
if($boolCount-ne1){throw('R1 AST boolean-normalization token count='+$boolCount)}
$text=$text.Replace($oldBool,$newBool)

# development-validation.yml is published as a separate CI-only commit because the Actions
# token cannot update workflow files. Keep the materializer transactional by validating the
# already-published trigger paths instead of rewriting the workflow in the product commit.
$oldWorkflow=@'
# Keep workflow triggering complete for future policy-only changes.
$workflowPath=Join-Path $RepositoryRoot '.github\workflows\development-validation.yml';$wf=[IO.File]::ReadAllText($workflowPath,[Text.Encoding]::UTF8)
$wf=Replace-Once $wf "      - 'tools/Invoke-Manager41712ReviewRegression.ps1'" "      - 'tools/Invoke-Manager41712ReviewRegression.ps1'`n      - 'tools/Invoke-ManagerRecoveryBehaviorRegression.ps1'`n      - 'tools/Invoke-Manager41713ReviewRegression.ps1'`n      - 'tools/Test-ManagerEntryReachabilityKnowledge.ps1'`n      - 'tools/Test-ManagerEntryPolicyCompleteness.ps1'`n      - 'tools/Invoke-ManagerEntryReachabilityMatrix.ps1'" 'development workflow policy paths'
Write-Utf8 $workflowPath $wf
'@
$newWorkflow=@'
# Workflow trigger wiring is a separately published development-CI commit. Validate exact
# required paths here so the product materialization cannot silently rely on stale CI coverage.
$workflowPath=Join-Path $RepositoryRoot '.github\workflows\development-validation.yml';$wf=[IO.File]::ReadAllText($workflowPath,[Text.Encoding]::UTF8)
foreach($requiredWorkflowPath in @('tools/Invoke-ManagerRecoveryBehaviorRegression.ps1','tools/Invoke-Manager41713ReviewRegression.ps1','tools/Test-ManagerEntryReachabilityKnowledge.ps1','tools/Test-ManagerEntryPolicyCompleteness.ps1','tools/Invoke-ManagerEntryReachabilityMatrix.ps1')){if(-not$wf.Contains("      - '"+$requiredWorkflowPath+"'")){Fail('Development validation workflow missing required path trigger: '+$requiredWorkflowPath)}}
'@
$oldWorkflow=$oldWorkflow.Trim();$newWorkflow=$newWorkflow.Trim()
$workflowBlockCount=[regex]::Matches($text,[regex]::Escape($oldWorkflow)).Count
if($workflowBlockCount-ne1){throw('R1 workflow-publication block count='+$workflowBlockCount)}
$text=$text.Replace($oldWorkflow,$newWorkflow)

# Historical executable regressions remain applicable to 4.17.13. Extend only their
# release-identity guards; the behavioral assertions themselves are unchanged.
$r41710=Join-Path $RepositoryRoot 'tools\Invoke-Manager41710ReviewRegression.ps1'
Replace-TargetOnce $r41710 "@('4.17.10','4.17.12')-contains[string]`$install.manager_version" "@('4.17.10','4.17.12','4.17.13')-contains[string]`$install.manager_version" '4.17.10 managed-copy version guard'
Replace-TargetOnce $r41710 "Regression requires Manager 4.17.10 source or validated 4.17.12 successor source; observed " "Regression requires Manager 4.17.10 source or validated 4.17.12/4.17.13 successor source; observed " '4.17.10 managed-copy guard message'
Replace-TargetOnce $r41710 "@('4.17.10','4.17.12')-contains`$currentVersion" "@('4.17.10','4.17.12','4.17.13')-contains`$currentVersion" '4.17.10 current-version guard'
Replace-TargetOnce $r41710 "supports 4.17.10, delegated 4.17.11, or validated 4.17.12 successor source; observed " "supports 4.17.10, delegated 4.17.11, or validated 4.17.12/4.17.13 successor source; observed " '4.17.10 current-version guard message'

$r41711=Join-Path $RepositoryRoot 'tools\Invoke-Manager41711ReviewRegression.ps1'
Replace-TargetOnce $r41711 "@('4.17.11','4.17.12')-contains[string]`$install.manager_version" "@('4.17.11','4.17.12','4.17.13')-contains[string]`$install.manager_version" '4.17.11 managed-copy version guard'
Replace-TargetOnce $r41711 "Regression requires Manager 4.17.11 source or validated 4.17.12 successor source; observed " "Regression requires Manager 4.17.11 source or validated 4.17.12/4.17.13 successor source; observed " '4.17.11 managed-copy guard message'
Replace-TargetOnce $r41711 "@('4.17.11','4.17.12')-contains`$currentVersion" "@('4.17.11','4.17.12','4.17.13')-contains`$currentVersion" '4.17.11 current-version guard'
Replace-TargetOnce $r41711 "supports 4.17.11 or validated 4.17.12 successor source; observed " "supports 4.17.11 or validated 4.17.12/4.17.13 successor source; observed " '4.17.11 current-version guard message'

$temp=Join-Path ([IO.Path]::GetTempPath()) ('Materialize-Manager41713EntryPolicy-r3-'+[guid]::NewGuid().ToString('N')+'.ps1')
try{
    [IO.File]::WriteAllText($temp,$text,$Utf8)
    foreach($parsePath in @($temp,$r41710,$r41711)){
        $tokens=$null;$errors=$null
        [void][Management.Automation.Language.Parser]::ParseFile($parsePath,[ref]$tokens,[ref]$errors)
        if(@($errors).Count){throw('Entry-policy R3 parser failed: '+$parsePath+' :: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    }
    $exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
    exit [int]$LASTEXITCODE
}finally{Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue}
