[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [Parameter(Mandatory=$true)][string]$EvidenceRoot
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Utf8=New-Object Text.UTF8Encoding($false)
function Fail([string]$Message){throw $Message}

$source=Join-Path $PSScriptRoot 'Materialize-Manager41713PendingGlobalAtomicityR9.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){Fail('R9 source materializer missing: '+$source)}
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)

# R9 failed before any target write because its materializer tried to replace two adjacent
# cross-model branches as one exact source string. Replace only that materializer statement;
# the product/proof contract remains unchanged. The inner R9 then inserts the new branch by
# the stable final-else anchor in Test-ManagerEntryReachabilityKnowledge.ps1.
$pattern='(?m)^\$v=Replace-Once \$v "elseif\(\$mode-ceq''registry_init_reconciles_global_input''\).*?''R9 validator state-machine outcome''\r?$'
$replacement=@'
$oldOutcomeAnchor="    else{Fail('Covered Initialize pair has unsupported cross-model mode '+`$mode+' for '+`$sid)}"
$newOutcomeAnchor="    elseif(`$mode-ceq'registry_init_mixed_invalid_rejected_without_partial_handoff'){if(`$outcome-cne'reject_fail_closed'){Fail('Mixed-invalid pending-global Initialize oracle/state-machine mismatch: '+`$outcome)}}`r`n    else{Fail('Covered Initialize pair has unsupported cross-model mode '+`$mode+' for '+`$sid)}"
if(-not$v.Contains($oldOutcomeAnchor)){$oldOutcomeAnchor=$oldOutcomeAnchor.Replace("`r`n","`n");$newOutcomeAnchor=$newOutcomeAnchor.Replace("`r`n","`n")}
$v=Replace-Once $v $oldOutcomeAnchor $newOutcomeAnchor 'R9 validator state-machine outcome'
'@
$matches=[regex]::Matches($text,$pattern)
if($matches.Count-ne1){Fail('R9b source correction target count='+$matches.Count)}
$text=[regex]::Replace($text,$pattern,[Text.RegularExpressions.MatchEvaluator]{param($m)$replacement.TrimEnd("`r","`n")},1)
$temp=Join-Path $env:RUNNER_TEMP 'Materialize-Manager41713PendingGlobalAtomicityR9b.inner.ps1'
[IO.File]::WriteAllText($temp,$text,$Utf8)
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
if(@($errors).Count-ne0){Fail('R9b patched materializer parse failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
$exe=Join-Path $PSHOME 'powershell.exe'
& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
$code=[int]$LASTEXITCODE
if($code-ne0){exit $code}
Write-Host 'Manager 4.17.13 R9b materializer harness correction: PASS' -ForegroundColor Green
