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
$lines=@([IO.File]::ReadAllLines($source,[Text.Encoding]::UTF8))
$targets=@()
for($i=0;$i-lt$lines.Count;$i++){if(([string]$lines[$i]).Contains("'R9 validator state-machine outcome'")){$targets+=@($i)}}
if($targets.Count-ne1){Fail('R9c source marker count='+$targets.Count)}
$idx=[int]$targets[0]
$replacement=@(
    '$oldOutcomeAnchor="    else{Fail(''Covered Initialize pair has unsupported cross-model mode ''+$mode+'' for ''+$sid)}"',
    '$newOutcomeAnchor="    elseif($mode-ceq''registry_init_mixed_invalid_rejected_without_partial_handoff''){if($outcome-cne''reject_fail_closed''){Fail(''Mixed-invalid pending-global Initialize oracle/state-machine mismatch: ''+$outcome)}}`r`n    else{Fail(''Covered Initialize pair has unsupported cross-model mode ''+$mode+'' for ''+$sid)}"',
    'if(-not$v.Contains($oldOutcomeAnchor)){$oldOutcomeAnchor=$oldOutcomeAnchor.Replace("`r`n","`n");$newOutcomeAnchor=$newOutcomeAnchor.Replace("`r`n","`n")}',
    '$v=Replace-Once $v $oldOutcomeAnchor $newOutcomeAnchor ''R9 validator state-machine outcome'''
)
$new=New-Object System.Collections.Generic.List[string]
for($i=0;$i-lt$idx;$i++){$new.Add([string]$lines[$i])}
foreach($line in $replacement){$new.Add([string]$line)}
for($i=$idx+1;$i-lt$lines.Count;$i++){$new.Add([string]$lines[$i])}
$temp=Join-Path $env:RUNNER_TEMP 'Materialize-Manager41713PendingGlobalAtomicityR9c.inner.ps1'
[IO.File]::WriteAllLines($temp,$new,$Utf8)
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
if(@($errors).Count-ne0){Fail('R9c patched materializer parse failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
$exe=Join-Path $PSHOME 'powershell.exe'
& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
$code=[int]$LASTEXITCODE
if($code-ne0){exit $code}
Write-Host 'Manager 4.17.13 R9c materializer harness correction: PASS' -ForegroundColor Green
