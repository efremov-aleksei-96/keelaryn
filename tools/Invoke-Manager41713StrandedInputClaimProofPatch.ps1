[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$source=Join-Path $RepositoryRoot 'tools\Apply-Manager41713StrandedInputClaimProofPatch.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw('Claim proof patcher missing: '+$source)}

$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)
$pattern='(?m)^\$rootAnchor=.*InstancesStateRoot.*$'
$matches=[regex]::Matches($text,$pattern)
if($matches.Count-ne1){throw('Claim proof patch strict-mode anchor count mismatch: '+$matches.Count)}
$replacement=@'
$rootAnchor='$script:InstancesStateRoot=Join-Path $StateRoot ''instances'''
'@.Trim()
$text=[regex]::Replace($text,$pattern,[Text.RegularExpressions.MatchEvaluator]{param($m)$replacement},1)

$temp=Join-Path ([IO.Path]::GetTempPath()) ('Apply-Manager41713StrandedInputClaimProofPatch.fixed.'+[guid]::NewGuid().ToString('N')+'.ps1')
$utf8=New-Object Text.UTF8Encoding($false)
try{
    [IO.File]::WriteAllText($temp,$text,$utf8)
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('Strict-mode-corrected proof patcher parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $exe=Join-Path $PSHOME 'powershell.exe'
    & $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot
    $code=[int]$LASTEXITCODE
    if($code-ne0){exit $code}
    Write-Host 'MGR-DEF-0034 CLAIM-FIRST PROOF PATCH WRAPPER: PASS' -ForegroundColor Green
    exit 0
}finally{
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
}
