[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [string]$EvidenceRoot=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Utf8=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Replace-Exact([string]$Text,[string]$Old,[string]$New,[string]$Label){
    $count=[regex]::Matches($Text,[regex]::Escape($Old)).Count
    if($count-ne1){Fail($Label+' count='+$count)}
    return $Text.Replace($Old,$New)
}

$source=Join-Path $PSScriptRoot 'Materialize-Manager41713PrefreezeProductFixR8.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){Fail('R8 source materializer missing: '+$source)}
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)

# R8 failed before product materialization because it iterated FunctionDefinitionAst.Parameters
# for every function. Functions that declare parameters in a body param(...) block can expose a
# null inline-parameter collection; under StrictMode the old guard dereferenced .Name on null.
# Inspect ParameterAst nodes directly instead, then prove the one pre-fix $Input parameter lies
# inside the intended function extent. This changes only the gate/evidence harness.
$oldBefore=@'
$ast=Parse-Ast $runtimePath
$inputParamFunctions=New-Object System.Collections.ArrayList
foreach($fn in @($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]},$true))){
    foreach($param in @($fn.Parameters)){
        if([string]$param.Name.VariablePath.UserPath-ieq'Input'){[void]$inputParamFunctions.Add([string]$fn.Name)}
    }
}
if($inputParamFunctions.Count-ne1-or[string]$inputParamFunctions[0]-cne'Get-GlobalHubInputIdentity'){
    Fail('R8 expected exactly one runtime function parameter named $Input in Get-GlobalHubInputIdentity; observed='+([string]::Join(',',@($inputParamFunctions))))
}
$fnRows=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-ceq'Get-GlobalHubInputIdentity'},$true))
if($fnRows.Count-ne1){Fail('Get-GlobalHubInputIdentity function count='+$fnRows.Count)}
'@
$newBefore=@'
$ast=Parse-Ast $runtimePath
$inputParams=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.ParameterAst]-and[string]$n.Name.VariablePath.UserPath-ieq'Input'},$true))
$fnRows=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-ceq'Get-GlobalHubInputIdentity'},$true))
if($fnRows.Count-ne1){Fail('Get-GlobalHubInputIdentity function count='+$fnRows.Count)}
$inputInTarget=@($inputParams|Where-Object{$_.Extent.StartOffset-ge$fnRows[0].Extent.StartOffset-and$_.Extent.EndOffset-le$fnRows[0].Extent.EndOffset})
if($inputParams.Count-ne1-or$inputInTarget.Count-ne1){
    Fail('R8 expected exactly one runtime ParameterAst named $Input and it must belong to Get-GlobalHubInputIdentity; all='+$inputParams.Count+' target='+$inputInTarget.Count)
}
'@
$text=Replace-Exact $text $oldBefore.TrimEnd("`r","`n") $newBefore.TrimEnd("`r","`n") 'R8b pre-fix AST guard'

$oldAfter=@'
$astAfter=Parse-Ast $runtimePath
$remaining=New-Object System.Collections.ArrayList
foreach($f in @($astAfter.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]},$true))){foreach($p in @($f.Parameters)){if([string]$p.Name.VariablePath.UserPath-ieq'Input'){[void]$remaining.Add([string]$f.Name)}}}
if($remaining.Count-ne0){Fail('Runtime still contains function parameter(s) named $Input after R8: '+([string]::Join(',',@($remaining))))}
'@
$newAfter=@'
$astAfter=Parse-Ast $runtimePath
$remaining=@($astAfter.FindAll({param($n)$n-is[Management.Automation.Language.ParameterAst]-and[string]$n.Name.VariablePath.UserPath-ieq'Input'},$true))
if($remaining.Count-ne0){Fail('Runtime still contains ParameterAst node(s) named $Input after R8; count='+$remaining.Count)}
'@
$text=Replace-Exact $text $oldAfter.TrimEnd("`r","`n") $newAfter.TrimEnd("`r","`n") 'R8b post-fix AST guard'

# R8b proved the product correction and metadata, then failed only because git diff does not
# report a newly-created untracked defect record. Build the scope set from both tracked changes
# and untracked non-ignored files so the exact patch-set assertion covers the new provenance file.
$oldChanged='$changed=@(& git.exe -C $RepositoryRoot diff --name-only)'
$newChanged='$changed=@((@(& git.exe -C $RepositoryRoot diff --name-only)+@(& git.exe -C $RepositoryRoot ls-files --others --exclude-standard))|Sort-Object -Unique)'
$text=Replace-Exact $text $oldChanged $newChanged 'R8c tracked-plus-untracked patch-set capture'

$temp=Join-Path $env:RUNNER_TEMP 'Materialize-Manager41713PrefreezeProductFixR8c.inner.ps1'
[IO.File]::WriteAllText($temp,$text,$Utf8)
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
if(@($errors).Count-ne0){Fail('R8c patched materializer parse failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}

$exe=Join-Path $PSHOME 'powershell.exe'
& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
$code=[int]$LASTEXITCODE
if($code-ne0){exit $code}
Write-Host 'Manager 4.17.13 R8c gate-harness correction: PASS' -ForegroundColor Green
