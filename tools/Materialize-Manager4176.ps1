[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)
function ReadText([string]$Path){return [IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8)}
function WriteText([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)}
function ReplaceOnce([string]$Text,[string]$Old,[string]$New,[string]$Label){$i=$Text.IndexOf($Old,[StringComparison]::Ordinal);if($i-lt0){throw('Missing replacement anchor: '+$Label)};if($Text.IndexOf($Old,$i+$Old.Length,[StringComparison]::Ordinal)-ge0){throw('Replacement anchor is not unique: '+$Label)};return $Text.Substring(0,$i)+$New+$Text.Substring($i+$Old.Length)}
function ReplaceFunction([string]$Path,[string]$Name,[string]$Replacement){
    $text=ReadText $Path;$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('Parser failed before function replacement: '+$Path)}
    $rows=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name})
    if($rows.Count-ne1){throw('function '+$Name+' count='+$rows.Count)}
    $row=$rows[0];$out=$text.Substring(0,$row.Extent.StartOffset)+$Replacement+$text.Substring($row.Extent.EndOffset);WriteText $Path $out
}
function ReplaceSection([string]$Text,[string]$StartHeading,[string]$EndHeading,[string]$Replacement){$s=$Text.IndexOf($StartHeading,[StringComparison]::Ordinal);if($s-lt0){throw('Missing section '+$StartHeading)};$e=$Text.IndexOf($EndHeading,$s+$StartHeading.Length,[StringComparison]::Ordinal);if($e-lt0){throw('Missing section boundary '+$EndHeading)};return $Text.Substring(0,$s)+$Replacement+$Text.Substring($e)}

$runtime=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$menu=Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1'
$install=Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json'
$releasePolicy=Join-Path $RepositoryRoot 'manager\product\manager_release.json'
$readme=Join-Path $RepositoryRoot 'manager\README_FIRST.md'
$manifestTool=Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1'
$manifestPath=Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json'
$provPath=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json'

$rt=ReadText $runtime
$rt=ReplaceOnce $rt '$ManagerVersion = "4.17.5"' '$ManagerVersion = "4.17.6"' 'runtime version'
WriteText $runtime $rt
$nl=if((ReadText $runtime).Contains("`r`n")){"`r`n"}else{"`n"}
$newGuard=@(
'function Assert-InvocationInstanceUnchanged {'
'    if($ExpectedSingleInstance){'
'        $freshRegistry=Read-InstanceRegistryEarly'
"        if(`$freshRegistry){throw 'Multi-Hub registry appeared after this invocation captured single-instance Hub context. Retry the operation.'}"
'        return'
'    }'
'    if(-not$script:InstanceRegistryActive){return}'
'    $active=Read-ActiveInstanceEarly'
'    if(-not$script:InvocationInstanceId-or[string]$active.instance_id-ne[string]$script:InvocationInstanceId){'
"        throw 'Active Hub changed after this Manager invocation resolved its instance context. Retry the operation.'"
'    }'
'}'
)-join$nl
ReplaceFunction $runtime 'Assert-InvocationInstanceUnchanged' $newGuard

$menuText=ReadText $menu
$tokens=$null;$errors=$null;$menuAst=[Management.Automation.Language.Parser]::ParseInput($menuText,[ref]$tokens,[ref]$errors)
if(@($errors).Count){throw 'Frontend parser failed before P2 replacement.'}
$quickRows=@($menuAst.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq'Get-QuickStatus'})
if($quickRows.Count-ne1){throw('Get-QuickStatus count='+$quickRows.Count)}
$q=$quickRows[0];$qText=[string]$q.Extent.Text;$qNl=if($qText.Contains("`r`n")){"`r`n"}else{"`n"}
$start=$qText.IndexOf('    if(Test-Path -LiteralPath $Inbox -PathType Container){',[StringComparison]::Ordinal)
$end=$qText.IndexOf('    $rootExtras=@()',$start,[StringComparison]::Ordinal)
if($start-lt0-or$end-lt0-or$end-le$start){throw 'Get-QuickStatus inbox scan anchors missing.'}
$newScan=@(
'    if(Test-Path -LiteralPath $Inbox -PathType Container){'
"        `$managerUpdates=@(Get-ChildItem -LiteralPath `$Inbox -File -Filter '*.zip' -ErrorAction SilentlyContinue|"
"            Where-Object{`$_.Name-match'(?i)^Keelaryn__Manager_Update_'}).Count"
'    }'
"    `$hubApproved=if(Test-Path -LiteralPath `$activeHubInbox -PathType Container){@(Get-ChildItem -LiteralPath `$activeHubInbox -File -Filter '*.zip' -ErrorAction SilentlyContinue|"
"        Where-Object{`$_.Name-match'(?i)^(Keelaryn__Hub|Core__Hub)_APPROVED_'}).Count}else{0}"
"    `$hubCandidate=if(Test-Path -LiteralPath `$activeHubInbox -PathType Container){@(Get-ChildItem -LiteralPath `$activeHubInbox -File -Filter '*.zip' -ErrorAction SilentlyContinue|"
"        Where-Object{`$_.Name-match'(?i)^(Keelaryn__Hub|Core__Hub)_CANDIDATE_'}).Count}else{0}"
''
)-join$qNl
$qNew=$qText.Substring(0,$start)+$newScan+$qText.Substring($end)
$menuNew=$menuText.Substring(0,$q.Extent.StartOffset)+$qNew+$menuText.Substring($q.Extent.EndOffset)
WriteText $menu $menuNew

$installText=ReadText $install;$installText=ReplaceOnce $installText '"manager_version": "4.17.5"' '"manager_version": "4.17.6"' 'INSTALLATION version';WriteText $install $installText
$rp=ReadText $releasePolicy;$rp=ReplaceOnce $rp '"manager_version":  "4.17.5"' '"manager_version":  "4.17.6"' 'release-policy version';WriteText $releasePolicy $rp

$rd=ReadText $readme;$rdNl=if($rd.Contains("`r`n")){"`r`n"}else{"`n"}
$oldIntro='Manager 4.17.5 is the corrective successor to the production-qualified but public-release-rejected Manager 4.17.4. It aligns multi-Hub CANDIDATE ingress with the active instance, binds Hub APPROVED import/update to the captured instance identity, and makes registered Genesis parent-path validation explicitly case-insensitive on Windows while preserving the existing transaction-safety and Framework r24 contracts.'
$newIntro='Manager 4.17.6 is the corrective successor to the production-qualified but public-release-rejected Manager 4.17.5. It revalidates captured single-instance Hub context after acquiring the Manager mutation lock and makes active per-instance Hub inbox discovery independent of global Manager inbox existence, while preserving the qualified 4.17.5 architecture and Framework r24 contracts.'
$rd=ReplaceOnce $rd '# Keelaryn Manager 4.17.5' '# Keelaryn Manager 4.17.6' 'README heading'
$rd=ReplaceOnce $rd $oldIntro ($newIntro+$rdNl+$rdNl+'## 4.17.5 context'+$rdNl+$oldIntro) 'README introduction'
$updateSection='## Update compatibility'+$rdNl+$rdNl+'Manager 4.17.6 preserves the native update compatibility floor in `product/manager_release.json` and the established UPDATE transition envelope. The normal production qualification transition for this corrective candidate is production-installed Manager 4.17.5 -> 4.17.6.'+$rdNl+$rdNl+'Manager-only update commands continue to distinguish "no newer valid package" from failure and do not silently process Hub updates. Installing Manager 4.17.6 alone must not change canonical Hub content.'+$rdNl+$rdNl
$rd=ReplaceSection $rd '## Update compatibility' '## User interface compatibility' $updateSection
$releaseSection='## Release gate'+$rdNl+$rdNl+'This source is not production-approved merely because it carries version 4.17.6. Production approval requires the applicable Windows PowerShell parser/static checks, inherited and 4.17.6 regressions, Manager/frontend SelfTests, deterministic SOURCE/DISTRIBUTION/UPDATE/AI_CONTEXT checks, disposable 4.17.5 -> 4.17.6 update and rollback/fault-injection coverage, Doctor/migration/UI/Genesis coverage, production Hub immutability, exact tested/public-source/release UPDATE identity, real CURRENT-backed Full Gate and gated publication. The consolidated gate uses qualified Gate Framework r24.'+$rdNl
$releaseStart=$rd.IndexOf('## Release gate',[StringComparison]::Ordinal);if($releaseStart-lt0){throw 'README release-gate section missing'};$rd=$rd.Substring(0,$releaseStart)+$releaseSection
WriteText $readme $rd

& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $manifestTool -RepositoryRoot $RepositoryRoot -Write
if($LASTEXITCODE-ne0){throw 'PUBLIC_FILE_MANIFEST generation failed.'}
$mf=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$mf.manager.version-cne'4.17.6'){throw 'Generated manifest version mismatch.'}
$prov=[ordered]@{
 schema='keelaryn.public-repository-provenance.v2';role='public_source_sync_candidate';source_manager_version='4.17.6';source_gate_baseline_manager_version='4.17.5';source_manager_installation_sha256=[string]$mf.manager.installation_sha256;source_manager_gate_managed_content_sha256=[string]$mf.manager.gate_managed_content_sha256
 production_validation=[ordered]@{full_gate_pass=$false;gate_revision=$null;framework_revision=24;tested_update_sha256=$null;production_doctor_pass=$false;production_ux_smoke_pass=$false;production_managed_content_prefix=$null}
 personal_hub_included=$false;manager_runtime_state_included=$false;local_test_evidence_included=$false
 gate_framework=[ordered]@{version='2.0';revision=24;windows_qualified=$true;frozen_for_manager_candidate=$false}
 license=[ordered]@{spdx_id='MIT';file='LICENSE';copyright='Copyright (c) 2026 Keelaryn contributors'}
 public_candidate_revision=9
 git_checkout_contract=[ordered]@{manager_authoritative_tree_attribute='-text';framework_authoritative_tree_attribute='-text';core_autocrlf_true_roundtrip_required=$true}
 known_nonsecret_source_hygiene_notes=@('manager/product/docs/TESTING.md retains a maintainer-local D:\0\0__Core example for historical/maintainer qualification context; it is not a product installation default.')
 ci_policy=[ordered]@{github_actions='pull_request + main push + manual';hosted_scope='repository verification + Hub-blind SourceGate + hosted disposable Full Gate + Generic DISTRIBUTION smoke';full_gate='CURRENT-backed Windows Full Gate plus production Doctor, production UX smoke and Hub immutability before publication';update_identity='when full_gate_pass=true, PR and main BuildRelease UPDATE SHA-256 must equal production_validation.tested_update_sha256; publish consumes those gated bytes'}
 known_nonsecret_hygiene_notes=@('manager/product/docs/TESTING.md retains a maintainer-local D:\0\0__Core example; it is not a product default.')
}
$provText=(($prov|ConvertTo-Json -Depth 20).Replace("`r`n","`n"))+"`n";WriteText $provPath $provText
Write-Host ('MANAGER 4.17.6 MATERIALIZED: managed='+[string]$mf.manager.gate_managed_content_sha256+' install='+[string]$mf.manager.installation_sha256) -ForegroundColor Green
