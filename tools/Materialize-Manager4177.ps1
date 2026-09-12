[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)
function ReadText([string]$Path){return [IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8)}
function WriteText([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)}
function ReplaceOnce([string]$Text,[string]$Old,[string]$New,[string]$Label){$i=$Text.IndexOf($Old,[StringComparison]::Ordinal);if($i-lt0){throw('Missing replacement anchor: '+$Label)};if($Text.IndexOf($Old,$i+$Old.Length,[StringComparison]::Ordinal)-ge0){throw('Replacement anchor is not unique: '+$Label)};return $Text.Substring(0,$i)+$New+$Text.Substring($i+$Old.Length)}

$runtime=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$install=Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json'
$policy=Join-Path $RepositoryRoot 'manager\product\manager_release.json'
$readme=Join-Path $RepositoryRoot 'manager\README_FIRST.md'
$manifestTool=Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1'
$manifestPath=Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json'
$provPath=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json'

$rt=ReadText $runtime
$rt=ReplaceOnce $rt '$ManagerVersion = "4.17.6"' '$ManagerVersion = "4.17.7"' 'runtime version'
$nl=if($rt.Contains("`r`n")){"`r`n"}else{"`n"}

$helpers=@(
'function Assert-UpdateAllContextSafe {'
'    if(-not$UpdateAll){return}'
'    if($ExpectedSingleInstance-or-not[string]::IsNullOrWhiteSpace([string]$ExpectedInstanceId)){return}'
'    if($script:InstanceRegistryActive){'
"        throw 'UpdateAll reached a multi-Hub Manager without a captured Hub context token. The Manager update may already be installed; retry Update all under the current Manager so it can bind the active Hub explicitly.'"
'    }'
'}'
''
'function Test-ExistingInstanceRegistryForInitialization {'
'    if(-not(Test-Path -LiteralPath $script:InstanceRegistryFile -PathType Leaf)){return $false}'
'    try{'
'        $null=Resolve-RegisteredInstanceContextEarly'
"        if(-not`$script:InstanceRegistryActive-or[string]::IsNullOrWhiteSpace([string]`$script:ActiveInstanceId)){throw 'Registry resolution did not produce an active registered instance.'}"
'        return $true'
'    }catch{'
"        throw ('Existing multi-Hub registry is invalid: '+`$_.Exception.Message)"
'    }'
'}'
''
)-join$nl
$anchor='function Assert-InvocationInstanceUnchanged {'
$rt=ReplaceOnce $rt $anchor ($helpers+$anchor) 'runtime corrective helpers'
$oldInit="    if(Test-Path -LiteralPath `$script:InstanceRegistryFile -PathType Leaf){Write-Host 'Multi-Hub registry is already initialized.' -ForegroundColor Green;return 0}"
$newInit="    if(Test-ExistingInstanceRegistryForInitialization){Write-Host 'Multi-Hub registry is already initialized and valid.' -ForegroundColor Green;return 0}"
$rt=ReplaceOnce $rt $oldInit $newInit 'validated existing registry initialization'
$rt=ReplaceOnce $rt 'function Invoke-Update {' ('function Invoke-Update {'+$nl+'    Assert-UpdateAllContextSafe') 'UpdateAll pre-side-effect guard'
WriteText $runtime $rt

$installText=ReadText $install
$installText=[regex]::Replace($installText,'("manager_version"\s*:\s*")4\.17\.6("\s*)','${1}4.17.7${2}',1)
if($installText-notmatch '"manager_version"\s*:\s*"4\.17\.7"'){throw 'INSTALLATION version bump failed.'}
WriteText $install $installText
$policyText=ReadText $policy
$policyText=[regex]::Replace($policyText,'("manager_version"\s*:\s*")4\.17\.6("\s*)','${1}4.17.7${2}',1)
if($policyText-notmatch '"manager_version"\s*:\s*"4\.17\.7"'){throw 'release-policy version bump failed.'}
WriteText $policy $policyText

$rd=ReadText $readme
$rdNl=if($rd.Contains("`r`n")){"`r`n"}else{"`n"}
$oldIntro='Manager 4.17.6 is the corrective successor to the production-qualified but public-release-rejected Manager 4.17.5. It revalidates captured single-instance Hub context after acquiring the Manager mutation lock, keeps active per-instance Hub inbox discovery independent of global Manager inbox existence, and preserves the captured Hub expectation across UpdateHub/UpdateAll including Manager self-update restart, while preserving the qualified 4.17.5 architecture and Framework r24 contracts.'
$newIntro='Manager 4.17.7 is the corrective successor to the production-qualified but public-release-rejected Manager 4.17.6. It fails closed when a legacy UpdateAll restart reaches an active multi-Hub registry without a captured Hub-context token, and validates an already-present multi-Hub registry plus active selection before reporting registry initialization success. It preserves the qualified 4.17.6 transaction-safety architecture and Framework r24 contracts.'
$rd=ReplaceOnce $rd '# Keelaryn Manager 4.17.6' '# Keelaryn Manager 4.17.7' 'README heading'
$rd=ReplaceOnce $rd $oldIntro ($newIntro+$rdNl+$rdNl+'## 4.17.6 context'+$rdNl+$oldIntro) 'README intro'
$rd=$rd.Replace('Manager 4.17.6 preserves the native update compatibility floor','Manager 4.17.7 preserves the native update compatibility floor')
$rd=$rd.Replace('production-installed Manager 4.17.5 -> 4.17.6','production-installed Manager 4.17.6 -> 4.17.7')
$rd=$rd.Replace('Installing Manager 4.17.6 alone','Installing Manager 4.17.7 alone')
$rd=$rd.Replace('because it carries version 4.17.6','because it carries version 4.17.7')
$rd=$rd.Replace('inherited and 4.17.6 regressions','inherited and 4.17.7 regressions')
$rd=$rd.Replace('disposable 4.17.5 -> 4.17.6 update','disposable 4.17.6 -> 4.17.7 update')
WriteText $readme $rd

& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $manifestTool -RepositoryRoot $RepositoryRoot -Write
if($LASTEXITCODE-ne0){throw 'PUBLIC_FILE_MANIFEST generation failed.'}
$mf=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$mf.manager.version-cne'4.17.7'){throw 'Generated manifest version mismatch.'}
$prov=[ordered]@{
 schema='keelaryn.public-repository-provenance.v2';role='public_source_sync_candidate';source_manager_version='4.17.7';source_gate_baseline_manager_version='4.17.6';source_manager_installation_sha256=[string]$mf.manager.installation_sha256;source_manager_gate_managed_content_sha256=[string]$mf.manager.gate_managed_content_sha256
 production_validation=[ordered]@{full_gate_pass=$false;gate_revision=$null;framework_revision=24;tested_update_sha256=$null;production_doctor_pass=$false;production_ux_smoke_pass=$false;production_managed_content_prefix=$null}
 personal_hub_included=$false;manager_runtime_state_included=$false;local_test_evidence_included=$false
 gate_framework=[ordered]@{version='2.0';revision=24;windows_qualified=$true;frozen_for_manager_candidate=$false}
 license=[ordered]@{spdx_id='MIT';file='LICENSE';copyright='Copyright (c) 2026 Keelaryn contributors'}
 public_candidate_revision=11
 git_checkout_contract=[ordered]@{manager_authoritative_tree_attribute='-text';framework_authoritative_tree_attribute='-text';core_autocrlf_true_roundtrip_required=$true}
 known_nonsecret_source_hygiene_notes=@('manager/product/docs/TESTING.md retains a maintainer-local D:\0\0__Core example for historical/maintainer qualification context; it is not a product installation default.')
 ci_policy=[ordered]@{github_actions='pull_request + main push + manual';hosted_scope='repository verification + Hub-blind SourceGate + hosted disposable Full Gate + Generic DISTRIBUTION smoke';full_gate='CURRENT-backed Windows Full Gate plus production Doctor, production UX smoke and Hub immutability before publication';update_identity='when full_gate_pass=true, PR and main BuildRelease UPDATE SHA-256 must equal production_validation.tested_update_sha256; publish consumes those gated bytes'}
 known_nonsecret_hygiene_notes=@('manager/product/docs/TESTING.md retains a maintainer-local D:\0\0__Core example; it is not a product default.')
}
WriteText $provPath ((($prov|ConvertTo-Json -Depth 20).Replace("`r`n","`n"))+"`n")
Write-Host ('MANAGER 4.17.7 MATERIALIZED: managed='+[string]$mf.manager.gate_managed_content_sha256+' install='+[string]$mf.manager.installation_sha256) -ForegroundColor Green
