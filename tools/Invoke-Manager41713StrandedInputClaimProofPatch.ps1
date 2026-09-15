[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$source=Join-Path $RepositoryRoot 'tools\Apply-Manager41713StrandedInputClaimProofPatch.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw('Claim proof patcher missing: '+$source)}

$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)

# Historical proof-patcher source is retained unchanged. Correct only two deterministic
# source-generation defects in a disposable copy before invoking it.
$rootPattern='(?m)^\$rootAnchor=.*InstancesStateRoot.*$'
$rootMatches=[regex]::Matches($text,$rootPattern)
if($rootMatches.Count-ne1){throw('Claim proof patch strict-mode anchor count mismatch: '+$rootMatches.Count)}
$rootReplacement=@'
$rootAnchor='$script:InstancesStateRoot=Join-Path $StateRoot ''instances'''
'@.Trim()
$text=[regex]::Replace($text,$rootPattern,[Text.RegularExpressions.MatchEvaluator]{param($m)$rootReplacement},1)

$syntaxBad=@'
        if(-not(Test-HubInputReconciliationDestinationExact $Claim $destination ([string]$identity.Sha256) ([string]$identity.InstanceId)){throw('final exact destination verification failed: '+$destination)}
'@.Trim()
$syntaxGood=@'
        if(-not(Test-HubInputReconciliationDestinationExact $Claim $destination ([string]$identity.Sha256) ([string]$identity.InstanceId))){throw('final exact destination verification failed: '+$destination)}
'@.Trim()
$syntaxCount=[regex]::Matches($text,[regex]::Escape($syntaxBad)).Count
if($syntaxCount-ne1){throw('Claim proof generated-runtime syntax anchor count mismatch: '+$syntaxCount)}
$text=$text.Replace($syntaxBad,$syntaxGood)

$temp=Join-Path ([IO.Path]::GetTempPath()) ('Apply-Manager41713StrandedInputClaimProofPatch.fixed.'+[guid]::NewGuid().ToString('N')+'.ps1')
$utf8=New-Object Text.UTF8Encoding($false)
try{
    [IO.File]::WriteAllText($temp,$text,$utf8)
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('Corrected proof patcher parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot
    $code=[int]$LASTEXITCODE
    if($code-ne0){exit $code}
    Write-Host 'MGR-DEF-0034 CLAIM-FIRST PROOF PATCH WRAPPER: PASS' -ForegroundColor Green
    exit 0
}finally{
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
}
