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
$pattern='(?ms)^\$oldGuard=\[string\]::Join\(\$nl,@\(.*?^\$runtime=Replace-ExactlyOnce \$runtime \$oldGuard \$newGuard ''pre-dispatch compatibility reconciliation guard''\r?\n'
$m=[regex]::Match($text,$pattern)
if(-not$m.Success){throw 'Could not locate the legacy literal guard-replacement block in materializer source.'}
$replacement=@'
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
$patched=$text.Substring(0,$m.Index)+(($replacement.TrimEnd())+"`n")+$text.Substring($m.Index+$m.Length)
$temp=Join-Path $env:RUNNER_TEMP 'Materialize-Manager41713RecoveryShadow-r3.ps1'
[IO.File]::WriteAllText($temp,$patched,(New-Object Text.UTF8Encoding($false)))
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
if(@($errors).Count){throw ('Patched r3 materializer parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -MaterializationRunId $MaterializationRunId
exit $LASTEXITCODE
