[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [Parameter(Mandatory=$true)][string]$MaterializationRunId
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$source=Join-Path $PSScriptRoot 'Invoke-Manager41713MaterializerR4.ps1'
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)
$old='$previousText=$previousText.Replace(''4.17.12'',''4.17.13'').Replace(''4.17.11 -> 4.17.13'',''4.17.12 -> 4.17.13'')'
$new='$previousText=$previousText.Replace(''4\.17\.12'',''4\.17\.13'').Replace(''4.17.12'',''4.17.13'').Replace(''4.17.11 -> 4.17.13'',''4.17.12 -> 4.17.13'')'
$count=([regex]::Matches($text,[regex]::Escape($old))).Count
if($count-ne1){throw "Expected one successor identity-adaptation line in r4 wrapper; actual=$count"}
$patched=$text.Replace($old,$new)
$temp=Join-Path $env:RUNNER_TEMP 'Invoke-Manager41713MaterializerR5-inner.ps1'
[IO.File]::WriteAllText($temp,$patched,(New-Object Text.UTF8Encoding($false)))
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
if(@($errors).Count){throw ('Patched r5 wrapper parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -MaterializationRunId $MaterializationRunId
exit $LASTEXITCODE
