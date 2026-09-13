[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Read-Text([string]$Path){return [IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8)}
function Write-Text([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)}
function Get-Nl([string]$Text){if($Text.IndexOf("`r`n",[StringComparison]::Ordinal)-ge0){return "`r`n"};return "`n"}
function Replace-Once([string]$Path,[string]$Old,[string]$New){
    $text=Read-Text $Path
    $first=$text.IndexOf($Old,[StringComparison]::Ordinal)
    if($first-lt0){throw('Materializer anchor missing: '+$Path+' :: '+$Old)}
    $second=$text.IndexOf($Old,$first+$Old.Length,[StringComparison]::Ordinal)
    if($second-ge0){throw('Materializer anchor is not unique: '+$Path+' :: '+$Old)}
    Write-Text $Path ($text.Substring(0,$first)+$New+$text.Substring($first+$Old.Length))
}
function Insert-BeforeOnce([string]$Path,[string]$Anchor,[string[]]$Lines){
    $text=Read-Text $Path
    $first=$text.IndexOf($Anchor,[StringComparison]::Ordinal)
    if($first-lt0){throw('Materializer insertion anchor missing: '+$Path+' :: '+$Anchor)}
    if($text.IndexOf($Anchor,$first+$Anchor.Length,[StringComparison]::Ordinal)-ge0){throw('Materializer insertion anchor is not unique: '+$Path+' :: '+$Anchor)}
    $nl=Get-Nl $text
    $insert=([string]::Join($nl,$Lines)+$nl)
    Write-Text $Path ($text.Substring(0,$first)+$insert+$text.Substring($first))
}

$manager=Join-Path $RepositoryRoot 'manager'
$runtime=Join-Path $manager 'product\runtime\Keelaryn__Manager.ps1'
$compatUpdateAll=Join-Path $manager 'compat\commands\UPDATE_ALL.cmd'
$install=Join-Path $manager 'product\install\INSTALLATION.json'
$releasePolicy=Join-Path $manager 'product\manager_release.json'
$readme=Join-Path $manager 'README_FIRST.md'
$devValidation=Join-Path $RepositoryRoot 'tools\Invoke-DevelopmentValidation.ps1'
$devWorkflow=Join-Path $RepositoryRoot '.github\workflows\development-validation.yml'
$provenance=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json'
$manifest=Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json'

if((Read-Text $runtime)-match '\$ManagerVersion = "4\.17\.8"'){
    Write-Host 'Manager 4.17.8 is already materialized; no changes required.' -ForegroundColor Green
    exit 0
}

# Version identity.
Replace-Once $runtime '$ManagerVersion = "4.17.7"' '$ManagerVersion = "4.17.8"'
Replace-Once $install '"manager_version": "4.17.7"' '"manager_version": "4.17.8"'
Replace-Once $releasePolicy '"manager_version":  "4.17.7"' '"manager_version":  "4.17.8"'

# P1: UPDATE_ALL compatibility alias must use the same token-capturing frontend path as the menu.
Replace-Once $runtime "    'UPDATE_ALL.cmd' = [ordered]@{ kind='standard'; manager_arg='-UpdateAll'; pause='always' }" "    'UPDATE_ALL.cmd' = [ordered]@{ kind='frontend'; frontend_action='UpdateAll'; pause='always' }"
Insert-BeforeOnce $runtime "    if ([string]`$spec.kind -eq 'bind') {" @(
    "    if ([string]`$spec.kind -eq 'frontend') {",
    '        $lines=@(',
    "            '@echo off','setlocal','rem Keelaryn generated compatibility command',",
    "            ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File \\"%~dp0..\\..\\product\\tools\\KeelarynMenu.ps1\\" -Action '+[string]`$spec.frontend_action+' -NoRootLauncher'),",
    "            'set \\"RC=%ERRORLEVEL%\\"'",
    '        )',
    "        if ([string]`$spec.pause -eq 'always') { `$lines += @('echo.','pause') }",
    "        elseif ([string]`$spec.pause -eq 'error') { `$lines += 'if not \\"%RC%\\"==\\"0\\" pause' }",
    "        `$lines += @('exit /b %RC%','')",
    '        return [string]::Join("`r`n",$lines)',
    '    }'
)
$oldSelf="        if (`$generated -notmatch '(?i)Keelaryn__Manager\.ps1') { return `$false }"
$newSelf=@"
        `$spec=`$CompatibilityCommandSpecs[`$name]
        if ([string]`$spec.kind -eq 'frontend') {
            if (`$generated -notmatch '(?i)KeelarynMenu\.ps1' -or `$generated -notmatch ('(?i)-Action\s+'+[regex]::Escape([string]`$spec.frontend_action))) { return `$false }
        } elseif (`$generated -notmatch '(?i)Keelaryn__Manager\.ps1') { return `$false }
"@.TrimEnd("`r","`n")
Replace-Once $runtime $oldSelf $newSelf
$compatText=[string]::Join("`r`n",@(
    '@echo off',
    'setlocal',
    'rem Keelaryn generated compatibility command',
    'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\product\tools\KeelarynMenu.ps1" -Action UpdateAll -NoRootLauncher',
    'set "RC=%ERRORLEVEL%"',
    'echo.',
    'pause',
    'exit /b %RC%',
    ''
))
Write-Text $compatUpdateAll $compatText

# P2: registration must prove that the staged CURRENT is activation-eligible before registry commit.
Insert-BeforeOnce $runtime 'function Assert-UpdateAllContextSafe {' @(
    'function Assert-RegisteredInstanceActivationEligible($Row) {',
    '    $null=Assert-RegisteredInstanceBaseline $Row',
    '    $paths=Get-InstanceStatePaths ([string]$Row.instance_id)',
    '    $identity=Get-CompatibilityCheckpointIdentityFast $paths.Current',
    "    if(-not`$identity){throw 'Registered instance CURRENT activation identity is invalid.'}",
    "    if([string]`$identity.ArtifactStatus-ne'approved'){throw 'Registered instance CURRENT must be an approved checkpoint before registration can commit.'}",
    '    return $true',
    '}',
    ''
)
Replace-Once $runtime '$null=Assert-RegisteredInstanceBaseline $candidateRow' '$null=Assert-RegisteredInstanceActivationEligible $candidateRow'

# Permanent 4.17.8 regression suite.
$regressionPath=Join-Path $RepositoryRoot 'tools\Invoke-Manager4178ReviewRegression.ps1'
$regression=@'
[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
function Assert([bool]$Condition,[string]$Message){if(-not$Condition){throw $Message}}
function Get-FunctionText([string]$Path,[string]$Name){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('Parser failed for '+$Path)}
    $rows=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name})
    if($rows.Count-ne1){throw('function '+$Name+' count='+$rows.Count)}
    return [string]$rows[0].Extent.Text
}
$p=Join-Path $PSHOME 'powershell.exe'
& $p -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $RepositoryRoot 'tools\Invoke-Manager4177ReviewRegression.ps1') -RepositoryRoot $RepositoryRoot
if($LASTEXITCODE-ne0){throw 'Inherited Manager 4.17.7 regression failed.'}
Write-Host '  PASS inherited Manager 4.17.7 regression chain'

$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$frontendPath=Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1'
$aliasPath=Join-Path $RepositoryRoot 'manager\compat\commands\UPDATE_ALL.cmd'
$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
$alias=[IO.File]::ReadAllText($aliasPath,[Text.Encoding]::UTF8)

# P1: the documented compatibility alias must enter the token-capturing frontend path,
# while the 4.17.7 legacy-restart guard remains in the runtime regression chain.
Assert $alias.Contains('product\tools\KeelarynMenu.ps1') 'UPDATE_ALL.cmd does not route through the frontend.'
Assert $alias.Contains('-Action UpdateAll') 'UPDATE_ALL.cmd does not request frontend UpdateAll.'
Assert $alias.Contains('-NoRootLauncher') 'UPDATE_ALL.cmd may recurse through the root launcher.'
Assert (-not$alias.Contains('Keelaryn__Manager.ps1" -UpdateAll')) 'UPDATE_ALL.cmd still directly invokes tokenless runtime UpdateAll.'
Assert $runtime.Contains("'UPDATE_ALL.cmd' = [ordered]@{ kind='frontend'; frontend_action='UpdateAll'; pause='always' }") 'Runtime compatibility specification does not preserve frontend routing.'
$generator=Get-FunctionText $runtimePath 'Get-GeneratedCompatibilityCommandText'
Assert $generator.Contains("if ([string]`$spec.kind -eq 'frontend')") 'Compatibility generator lacks the frontend command kind.'
$invokeAction=Get-FunctionText $frontendPath 'Invoke-Action'
Assert $invokeAction.Contains("`$args+=@('-ExpectedInstanceId',[string]`$ctx.InstanceId)") 'Frontend UpdateAll no longer captures active instance_id.'
Assert $invokeAction.Contains("`$args+=@('-ExpectedSingleInstance')") 'Frontend UpdateAll no longer captures single-instance expectation.'
Write-Host '  PASS UPDATE_ALL compatibility alias preserves explicit Hub context via frontend'

# P2: staged registration state must be APPROVED as well as content/identity-consistent.
Invoke-Expression (Get-FunctionText $runtimePath 'Assert-RegisteredInstanceActivationEligible')
$script:baselineCalls=0
$script:syntheticStatus='candidate'
function Assert-RegisteredInstanceBaseline { param($Row) $script:baselineCalls++; return $true }
function Get-InstanceStatePaths { param([string]$InstanceId) return [pscustomobject]@{Current='synthetic-current.zip'} }
function Get-CompatibilityCheckpointIdentityFast { param([string]$Path) return [pscustomobject]@{ArtifactStatus=$script:syntheticStatus} }
$row=[pscustomobject]@{instance_id='99999999-9999-9999-9999-999999999999'}
$blocked=$false
try{$null=Assert-RegisteredInstanceActivationEligible $row}catch{$blocked=$_.Exception.Message -like '*approved checkpoint*before registration can commit*'}
Assert $blocked 'Registration activation guard accepted a CANDIDATE checkpoint.'
Assert ($script:baselineCalls-eq1) 'Registration activation guard skipped full Hub/CURRENT baseline validation.'
$script:syntheticStatus='approved';$script:baselineCalls=0
$ok=$true
try{$null=Assert-RegisteredInstanceActivationEligible $row}catch{$ok=$false}
Assert $ok 'Registration activation guard rejected an APPROVED coherent checkpoint.'
Assert ($script:baselineCalls-eq1) 'Approved registration did not retain full baseline validation.'
$register=Get-FunctionText $runtimePath 'Invoke-RegisterExistingInstance'
$stageIndex=$register.IndexOf('New-RegisteredInstanceStateFromVault',[StringComparison]::Ordinal)
$guardIndex=$register.IndexOf('Assert-RegisteredInstanceActivationEligible',[StringComparison]::Ordinal)
$commitIndex=$register.IndexOf('Write-ManagerInstanceRegistry',[StringComparison]::Ordinal)
Assert ($stageIndex-ge0-and$guardIndex-gt$stageIndex-and$commitIndex-gt$guardIndex) 'Activation eligibility is not revalidated after staging and before registry commit.'
Assert (-not$register.Contains('Assert-RegisteredInstanceBaseline $candidateRow')) 'Registration still bypasses the stronger activation-eligibility helper.'
Write-Host '  PASS existing-Hub registration rejects non-APPROVED activation baselines before commit'

Write-Host 'MANAGER 4.17.8 REVIEW REGRESSION: PASS' -ForegroundColor Green
'@
Write-Text $regressionPath ($regression.Replace("`r`n","`n")+"`n")

# Wire the permanent regression into ordinary development validation and its trigger surface.
$dv=Read-Text $devValidation
$dv=$dv.Replace('Manager 4.17.7 regression chain','Manager 4.17.8 regression chain').Replace("@('Invoke-Manager4177ReviewRegression.ps1')","@('Invoke-Manager4178ReviewRegression.ps1')").Replace('Manager 4.17.7 regression tool is missing','Manager 4.17.8 regression tool is missing')
Write-Text $devValidation $dv
$dw=Read-Text $devWorkflow
Replace-Once $devWorkflow "      - 'tools/Invoke-Manager4177ReviewRegression.ps1'" ([string]::Join((Get-Nl $dw),@("      - 'tools/Invoke-Manager4178ReviewRegression.ps1'","      - 'tools/Invoke-Manager4177ReviewRegression.ps1'")))
Replace-Once $devWorkflow '# Manager 4.17.7 clean-head development validation with permanent corrective regressions.' '# Manager 4.17.8 clean-head development validation with permanent corrective regressions.'

# Presentation/version context.
$introOld="# Keelaryn Manager 4.17.7`r`nManager 4.17.7 is the corrective successor to the production-qualified but public-release-rejected Manager 4.17.6. It fails closed when a legacy UpdateAll restart reaches an active multi-Hub registry without a captured Hub-context token, and validates an already-present multi-Hub registry plus active selection before reporting registry initialization success. It preserves the qualified 4.17.6 transaction-safety architecture and Framework r24 contracts.`r`n"
$readmeText=Read-Text $readme
if(-not$readmeText.Contains($introOld)){
    $introOld=$introOld.Replace("`r`n","`n")
}
$introNew=(@(
    '# Keelaryn Manager 4.17.8',
    'Manager 4.17.8 is the corrective successor to the production-qualified but public-release-rejected Manager 4.17.7. It restores the documented UPDATE_ALL compatibility alias in multi-Hub mode by routing it through the frontend that captures the active Hub expectation, and it rejects existing Hubs whose staged CURRENT is not an APPROVED activation baseline before instances.json can commit. It preserves the qualified 4.17.7 fail-closed legacy-restart guard, registry-validation contracts and Framework r24 architecture.',
    '',
    '## 4.17.7 context',
    'Manager 4.17.7 is the corrective successor to the production-qualified but public-release-rejected Manager 4.17.6. It fails closed when a legacy UpdateAll restart reaches an active multi-Hub registry without a captured Hub-context token, and validates an already-present multi-Hub registry plus active selection before reporting registry initialization success. It preserves the qualified 4.17.6 transaction-safety architecture and Framework r24 contracts.',
    ''
)-join (Get-Nl $readmeText))
Replace-Once $readme $introOld $introNew

# Rebuild authoritative public manifest from exact product bytes.
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1') -RepositoryRoot $RepositoryRoot -Write
if($LASTEXITCODE-ne0){throw 'Build-PublicFileManifest -Write failed.'}
$m=Get-Content -LiteralPath $manifest -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$m.manager.version-cne'4.17.8'){throw 'Generated public manifest did not bind Manager 4.17.8.'}

# Reset publication provenance for unqualified 4.17.8 development while binding exact source identities.
$prov=Get-Content -LiteralPath $provenance -Raw -Encoding UTF8|ConvertFrom-Json
$prov.source_manager_version='4.17.8'
$prov.source_gate_baseline_manager_version='4.17.7'
$prov.source_manager_installation_sha256=[string]$m.manager.installation_sha256
$prov.source_manager_gate_managed_content_sha256=[string]$m.manager.gate_managed_content_sha256
$prov.production_validation.full_gate_pass=$false
$prov.production_validation.gate_revision=$null
$prov.production_validation.framework_revision=24
$prov.production_validation.tested_update_sha256=$null
$prov.production_validation.production_doctor_pass=$false
$prov.production_validation.production_ux_smoke_pass=$false
$prov.production_validation.production_managed_content_prefix=$null
$prov.public_candidate_revision=12
$prov.gate_framework.revision=24
$prov.gate_framework.windows_qualified=$true
$prov.gate_framework.frozen_for_manager_candidate=$false
$provText=(($prov|ConvertTo-Json -Depth 30).Replace("`r`n","`n")+"`n")
Write-Text $provenance $provText

# Remove temporary materializer source/workflow from the product-development HEAD.
$workflow=Join-Path $RepositoryRoot '.github\workflows\materialize-manager-4.17.8.yml'
if(Test-Path -LiteralPath $workflow){Remove-Item -LiteralPath $workflow -Force}
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force

Write-Host 'Manager 4.17.8 materialization complete.' -ForegroundColor Green
