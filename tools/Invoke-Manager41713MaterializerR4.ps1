[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [Parameter(Mandatory=$true)][string]$MaterializationRunId
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$source=Join-Path $PSScriptRoot 'Materialize-Manager41713RecoveryShadow.ps1'
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)

# Harden the runtime guard replacement against line-ending/formatting variation.
$guardBlockPattern='(?ms)^\$oldGuard=\[string\]::Join\(\$nl,@\(.*?^\$runtime=Replace-ExactlyOnce \$runtime \$oldGuard \$newGuard ''pre-dispatch compatibility reconciliation guard''\r?\n'
$guardBlock=[regex]::Match($text,$guardBlockPattern)
if(-not$guardBlock.Success){throw 'Could not locate the legacy literal guard-replacement block in materializer source.'}
$guardReplacement=@'
$guardPattern='(?ms)^if\(\$script:InstanceRegistryActive -and -not\$Doctor\)\{\r?\n\s+Acquire-ManagerLock\r?\n\s+try\{\$null=Invoke-ReconcileActiveCompatibilityShadow\}\r?\n\s+finally\{Release-ManagerLock\}\r?\n\}'
$guardMatch=[regex]::Match($runtime,$guardPattern)
if(-not$guardMatch.Success){throw 'pre-dispatch compatibility reconciliation guard: source pattern not found'}
if([regex]::Matches($runtime,$guardPattern).Count-ne1){throw 'pre-dispatch compatibility reconciliation guard: source pattern is ambiguous'}
$newGuard=[string]::Join($nl,@(
    'function Test-ActiveCompatibilityShadowReconciliationRequired {',
    '    if(-not$script:InstanceRegistryActive){return $false}',
    '    # Diagnostic, target-driven recovery, and Manager-global actions must not depend on',
    '    # or mutate the previously active Hub compatibility shadow before their own dispatch.',
    '    if($Doctor-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$UpdateManager-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$FinalizeFilesystemLayout-or$InitializePresentation-or$PrepareTests){return $false}',
    '    return $true',
    '}',
    '',
    'if(Test-ActiveCompatibilityShadowReconciliationRequired){',
    '    Acquire-ManagerLock',
    '    try{$null=Invoke-ReconcileActiveCompatibilityShadow}',
    '    finally{Release-ManagerLock}',
    '}'
))
$runtime=$runtime.Substring(0,$guardMatch.Index)+$newGuard+$runtime.Substring($guardMatch.Index+$guardMatch.Length)
'@
$patched=$text.Substring(0,$guardBlock.Index)+(($guardReplacement.TrimEnd())+"`n")+$text.Substring($guardBlock.Index+$guardBlock.Length)

# Preserve the full 4.17.12 successor regression while adapting only its release-specific identity assertions.
$inheritOld=@'
$previous=Join-Path $RepositoryRoot 'tools\Invoke-Manager41712ReviewRegression.ps1'
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $previous -RepositoryRoot $RepositoryRoot
if($LASTEXITCODE-ne0){Fail 'Inherited Manager 4.17.12 review regression failed.'}
'@
$inheritNew=@'
$previous=Join-Path $RepositoryRoot 'tools\Invoke-Manager41712ReviewRegression.ps1'
$previousText=[IO.File]::ReadAllText($previous,[Text.Encoding]::UTF8)
$previousText=$previousText.Replace('4.17.12','4.17.13').Replace('4.17.11 -> 4.17.13','4.17.12 -> 4.17.13')
$adapted=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-41713-inherited-'+[guid]::NewGuid().ToString('N')+'.ps1')
try{
    [IO.File]::WriteAllText($adapted,$previousText,(New-Object Text.UTF8Encoding($false)))
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $adapted -RepositoryRoot $RepositoryRoot
    if($LASTEXITCODE-ne0){Fail 'Adapted inherited Manager 4.17.12 review regression failed.'}
}finally{if(Test-Path -LiteralPath $adapted){Remove-Item -LiteralPath $adapted -Force -ErrorAction SilentlyContinue}}
'@
$inheritCount=([regex]::Matches($patched,[regex]::Escape($inheritOld))).Count
if($inheritCount-ne1){throw "Expected exactly one inherited-regression block in materializer; actual=$inheritCount"}
$patched=$patched.Replace($inheritOld,$inheritNew)

$temp=Join-Path $env:RUNNER_TEMP 'Materialize-Manager41713RecoveryShadow-r4.ps1'
[IO.File]::WriteAllText($temp,$patched,(New-Object Text.UTF8Encoding($false)))
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
if(@($errors).Count){throw ('Patched r4 materializer parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -MaterializationRunId $MaterializationRunId
exit $LASTEXITCODE
