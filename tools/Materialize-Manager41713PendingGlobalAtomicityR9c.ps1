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
function Replace-Exact([string]$Text,[string]$Old,[string]$New,[string]$Label){
    $count=[regex]::Matches($Text,[regex]::Escape($Old)).Count
    if($count-ne1){Fail($Label+' count='+$count)}
    return $Text.Replace($Old,$New)
}

$source=Join-Path $PSScriptRoot 'Materialize-Manager41713PendingGlobalAtomicityR9.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){Fail('R9 source materializer missing: '+$source)}
$sourceText=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)

# Pre-qualification adversarial review of the proposed R9 fix found two defects in the
# unpublished implementation. Correct the materializer before it can generate candidate bytes:
# 1) staging cleanup must use -not IsNullOrWhiteSpace;
# 2) missing-destination publication must use a no-overwrite same-volume rename and must enter
#    the rollback set immediately after the durable rename, before presentation/hash verification.
#    This avoids both clobbering a race-created destination and losing rollback ownership if a
#    post-commit SetHidden/hash check fails.
$sourceText=Replace-Exact $sourceText \
    'if(-[string]::IsNullOrWhiteSpace([string]$plan.Stage)-and(Test-Path -LiteralPath ([string]$plan.Stage))){Remove-Item -LiteralPath ([string]$plan.Stage) -Force -ErrorAction SilentlyContinue}' \
    'if(-not [string]::IsNullOrWhiteSpace([string]$plan.Stage)-and(Test-Path -LiteralPath ([string]$plan.Stage))){Remove-Item -LiteralPath ([string]$plan.Stage) -Force -ErrorAction SilentlyContinue}' \
    'R9 unpublished stage cleanup correction'

$oldPublish=@'
                Publish-CompletedFileAtomically ([string]$plan.Stage) ([string]$plan.Destination)
                $plan.Stage=''
                $destItem=Get-Item -LiteralPath ([string]$plan.Destination) -Force -ErrorAction Stop
                if($destItem.PSIsContainer-or($destItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Published stranded Hub input destination is unsafe: '+[string]$plan.Destination)}
                if((Get-FileHash -LiteralPath ([string]$plan.Destination) -Algorithm SHA256).Hash.ToLowerInvariant()-ne[string]$plan.Sha256){throw('Published stranded Hub input destination failed hash verification: '+[string]$plan.Destination)}
                $plan.PublishedByThisRun=$true
                [void]$published.Add($plan)
'@.TrimEnd("`r","`n")
$newPublish=@'
                [System.IO.File]::Move([string]$plan.Stage,[string]$plan.Destination)
                $plan.Stage=''
                $plan.PublishedByThisRun=$true
                [void]$published.Add($plan)
                Set-ManagerMutablePresentationHidden ([string]$plan.Destination)
                $destItem=Get-Item -LiteralPath ([string]$plan.Destination) -Force -ErrorAction Stop
                if($destItem.PSIsContainer-or($destItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Published stranded Hub input destination is unsafe: '+[string]$plan.Destination)}
                if((Get-FileHash -LiteralPath ([string]$plan.Destination) -Algorithm SHA256).Hash.ToLowerInvariant()-ne[string]$plan.Sha256){throw('Published stranded Hub input destination failed hash verification: '+[string]$plan.Destination)}
'@.TrimEnd("`r","`n")
if(-not$sourceText.Contains($oldPublish)){$oldPublish=$oldPublish.Replace("`r`n","`n");$newPublish=$newPublish.Replace("`r`n","`n")}
$sourceText=Replace-Exact $sourceText $oldPublish $newPublish 'R9 unpublished publication-boundary correction'

$lines=@([regex]::Split($sourceText,'\r?\n'))
$targets=@()
for($i=0;$i-lt$lines.Count;$i++){if(([string]$lines[$i]).Contains("'R9 validator state-machine outcome'")){$targets+=@($i)}}
if($targets.Count-ne1){Fail('R9c source marker count='+$targets.Count)}
$idx=[int]$targets[0]

# The generated inner materializer must preserve $mode/$sid/$outcome as literal target-source
# text. A single-quoted outer here-string avoids a second interpolation layer under StrictMode.
$replacementText=@'
$oldOutcomeAnchor='    else{Fail(''Covered Initialize pair has unsupported cross-model mode ''+$mode+'' for ''+$sid)}'
$newOutcomeAnchor='    elseif($mode-ceq''registry_init_mixed_invalid_rejected_without_partial_handoff''){if($outcome-cne''reject_fail_closed''){Fail(''Mixed-invalid pending-global Initialize oracle/state-machine mismatch: ''+$outcome)}}'+"`r`n"+'    else{Fail(''Covered Initialize pair has unsupported cross-model mode ''+$mode+'' for ''+$sid)}'
if(-not$v.Contains($oldOutcomeAnchor)){$oldOutcomeAnchor=$oldOutcomeAnchor.Replace("`r`n","`n");$newOutcomeAnchor=$newOutcomeAnchor.Replace("`r`n","`n")}
$v=Replace-Once $v $oldOutcomeAnchor $newOutcomeAnchor 'R9 validator state-machine outcome'
'@
$replacement=@([regex]::Split($replacementText.TrimEnd("`r","`n"),'\r?\n'))

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
Write-Host 'Manager 4.17.13 R9c materializer harness/product-prequalification correction: PASS' -ForegroundColor Green
