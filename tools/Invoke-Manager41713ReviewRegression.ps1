[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [switch]$LeafOnly
)
$ErrorActionPreference='Stop';Set-StrictMode -Version 2.0;$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
function Fail([string]$Message){throw $Message}
function Assert([bool]$Condition,[string]$Message){if(-not$Condition){Fail $Message}}
function Get-FunctionText([string]$Path,[string]$Name){$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e);if(@($e).Count){Fail('Parser failed: '+([string]::Join(' | ',@($e|ForEach-Object{$_.Message})) ))};$r=@($a.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name});if($r.Count-ne1){Fail('Function '+$Name+' count='+$r.Count)};return [string]$r[0].Extent.Text}
if(-not$LeafOnly){$p=Join-Path $PSHOME 'powershell.exe';& $p -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $RepositoryRoot 'tools\Invoke-ManagerRecoveryBehaviorRegression.ps1') -RepositoryRoot $RepositoryRoot;if($LASTEXITCODE-ne0){Fail 'Version-independent recovery behavior regression failed.'}}
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1';$installPath=Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json';$releasePath=Join-Path $RepositoryRoot 'manager\product\manager_release.json';$readmePath=Join-Path $RepositoryRoot 'manager\README_FIRST.md'
$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8);$install=Get-Content $installPath -Raw -Encoding UTF8|ConvertFrom-Json;$release=Get-Content $releasePath -Raw -Encoding UTF8|ConvertFrom-Json;$readme=[IO.File]::ReadAllText($readmePath,[Text.Encoding]::UTF8)
Assert ($runtime-match'(?m)^\$ManagerVersion = "4\.17\.13"$') 'Runtime version marker is not 4.17.13.';Assert ([string]$install.manager_version-ceq'4.17.13') 'INSTALLATION version is not 4.17.13.';Assert ([string]$release.manager_version-ceq'4.17.13') 'release policy version is not 4.17.13.';Assert ($readme.Contains('production-installed Manager 4.17.12 -> 4.17.13')) 'README transition identity is not 4.17.12 -> 4.17.13.'
$policy=Get-FunctionText $runtimePath 'Test-ActiveCompatibilityShadowReconciliationRequired';foreach($token in @('$Doctor','$ListInstances','$SwitchInstanceId','$BindInstancePath','$UpdateManager','$BuildDistribution','$BuildRelease','$BuildAIContext')){Assert ($policy.Contains($token)) ('Reconciliation policy omits '+$token)};Assert ($runtime.Contains('if(Test-ActiveCompatibilityShadowReconciliationRequired)')) 'Top-level runtime does not use centralized reconciliation policy.';Assert (-not$runtime.Contains('if($script:InstanceRegistryActive -and -not$Doctor)')) 'Legacy unconditional reconciliation guard remains.'
Write-Host 'MANAGER 4.17.13 REVIEW REGRESSION: PASS' -ForegroundColor Green
