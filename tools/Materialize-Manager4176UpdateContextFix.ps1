[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop';Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)
function R([string]$p){[IO.File]::ReadAllText($p,[Text.Encoding]::UTF8)}
function W([string]$p,[string]$t){[IO.File]::WriteAllText($p,$t,$Utf8NoBom)}
function ReplaceOnce([string]$t,[string]$o,[string]$n,[string]$label){$i=$t.IndexOf($o,[StringComparison]::Ordinal);if($i-lt0){throw('Missing anchor: '+$label)};if($t.IndexOf($o,$i+$o.Length,[StringComparison]::Ordinal)-ge0){throw('Non-unique anchor: '+$label)};return $t.Substring(0,$i)+$n+$t.Substring($i+$o.Length)}
function ReplaceFunction([string]$p,[string]$name,[string]$replacement){$t=R $p;$tok=$null;$err=$null;$ast=[Management.Automation.Language.Parser]::ParseInput($t,[ref]$tok,[ref]$err);if(@($err).Count){throw('Parser failed: '+$p)};$rows=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$name});if($rows.Count-ne1){throw('function '+$name+' count='+$rows.Count)};$r=$rows[0];W $p ($t.Substring(0,$r.Extent.StartOffset)+$replacement+$t.Substring($r.Extent.EndOffset))}

$runtime=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$menu=Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1'
$readme=Join-Path $RepositoryRoot 'manager\README_FIRST.md'
$legacyRegression=Join-Path $RepositoryRoot 'tools\Invoke-Manager4175ReviewRegression.ps1'
$manifestTool=Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1'
$manifestPath=Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json'
$provPath=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json'

$rt=R $runtime
$rt=ReplaceOnce $rt "if(`$ExpectedSingleInstance-and-not`$UpdateHub){throw 'ExpectedSingleInstance is valid only with -UpdateHub.'}" "if(`$ExpectedSingleInstance-and-not(`$UpdateHub-or`$UpdateAll)){throw 'ExpectedSingleInstance is valid only with -UpdateHub or -UpdateAll.'}" 'ExpectedSingleInstance update-mode guard'
$rt=ReplaceOnce $rt "if(-not`$UpdateHub){throw 'ExpectedInstanceId is valid only with -UpdateHub.'}" "if(-not(`$UpdateHub-or`$UpdateAll)){throw 'ExpectedInstanceId is valid only with -UpdateHub or -UpdateAll.'}" 'ExpectedInstanceId update-mode guard'
W $runtime $rt
$nl=if((R $runtime).Contains("`r`n")){"`r`n"}else{"`n"}
$newAssert=@(
'function Assert-InvocationInstanceUnchanged {'
'    if($ExpectedSingleInstance-or-not$script:InstanceRegistryActive){'
'        $freshRegistry=Read-InstanceRegistryEarly'
"        if(`$freshRegistry){throw 'Multi-Hub registry appeared after this invocation captured single-instance Hub context. Retry the operation.'}"
'        return'
'    }'
'    $active=Read-ActiveInstanceEarly'
'    if(-not$script:InvocationInstanceId-or[string]$active.instance_id-ne[string]$script:InvocationInstanceId){'
"        throw 'Active Hub changed after this Manager invocation resolved its instance context. Retry the operation.'"
'    }'
'}'
)-join$nl
ReplaceFunction $runtime 'Assert-InvocationInstanceUnchanged' $newAssert
$newRestart=@(
'function Restart-UpdatedManager {'
"    `$script=Join-Path `$Root 'product\runtime\Keelaryn__Manager.ps1'"
'    $previousHandoff=[string]$env:KEELARYN_FILESYSTEM_HANDOFF_ACTIVE'
'    $setHandoff=$false'
'    if(Test-Path -LiteralPath $StateLayoutReceipt -PathType Leaf){'
"        try{`$layoutReceipt=([System.IO.File]::ReadAllText(`$StateLayoutReceipt,[System.Text.Encoding]::UTF8)|ConvertFrom-Json);`$setHandoff=[bool]`$layoutReceipt.legacy_log_handoff_pending}catch{}"
'    }'
'    try {'
"        if(`$setHandoff){`$env:KEELARYN_FILESYSTEM_HANDOFF_ACTIVE='1'}"
'        if ($UpdateAll) {'
'            $contextArgs=@()'
"            if(-not[string]::IsNullOrWhiteSpace([string]`$ExpectedInstanceId)){`$contextArgs=@('-ExpectedInstanceId',[string]`$ExpectedInstanceId)}"
"            elseif(`$ExpectedSingleInstance){`$contextArgs=@('-ExpectedSingleInstance')}"
"            elseif(`$script:InstanceRegistryActive-and-not[string]::IsNullOrWhiteSpace([string]`$script:InvocationInstanceId)){`$contextArgs=@('-ExpectedInstanceId',[string]`$script:InvocationInstanceId)}"
"            else{`$contextArgs=@('-ExpectedSingleInstance')}"
'            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -UpdateAll @contextArgs | Out-Host'
'        }'
'        elseif ($UpdateManager) {'
'            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -UpdateManager | Out-Host'
'        }'
"        else { throw 'Manager restart requested without a Manager-capable update mode.' }"
'        return $LASTEXITCODE'
'    }'
'    finally {'
'        if([string]::IsNullOrEmpty($previousHandoff)){Remove-Item Env:KEELARYN_FILESYSTEM_HANDOFF_ACTIVE -ErrorAction SilentlyContinue}else{$env:KEELARYN_FILESYSTEM_HANDOFF_ACTIVE=$previousHandoff}'
'    }'
'}'
)-join$nl
ReplaceFunction $runtime 'Restart-UpdatedManager' $newRestart

$mt=R $menu
$oldAll="        'UpdateAll' { `$q=Get-QuickStatus;if((`$q.ManagerUpdates+`$q.HubApproved)-eq0){Write-UiHost 'Manager: no pending update.';Write-UiHost 'Hub: no APPROVED update.';Set-ActionSemantic 'no_changes';return 0};return Invoke-Manager @('-UpdateAll') }"
$newAll="        'UpdateAll' { `$q=Get-QuickStatus;if((`$q.ManagerUpdates+`$q.HubApproved)-eq0){Write-UiHost 'Manager: no pending update.';Write-UiHost 'Hub: no APPROVED update.';Set-ActionSemantic 'no_changes';return 0};`$ctx=Get-FrontendInstanceContext;`$args=@('-UpdateAll');if(`$ctx.RegistryActive){if(-not`$ctx.InstanceId){Fail 'Multi-Hub registry exists but the active instance cannot be resolved. Update refused.'};`$args+=@('-ExpectedInstanceId',[string]`$ctx.InstanceId)}else{`$args+=@('-ExpectedSingleInstance')};return Invoke-Manager `$args }"
$oldHub="        'UpdateHub' { return Invoke-Manager @('-UpdateHub') }"
$newHub="        'UpdateHub' { `$ctx=Get-FrontendInstanceContext;`$args=@('-UpdateHub');if(`$ctx.RegistryActive){if(-not`$ctx.InstanceId){Fail 'Multi-Hub registry exists but the active instance cannot be resolved. Update refused.'};`$args+=@('-ExpectedInstanceId',[string]`$ctx.InstanceId)}else{`$args+=@('-ExpectedSingleInstance')};return Invoke-Manager `$args }"
$mt=ReplaceOnce $mt $oldAll $newAll 'frontend UpdateAll case'
$mt=ReplaceOnce $mt $oldHub $newHub 'frontend UpdateHub case'
W $menu $mt

$rd=R $readme
$rd=ReplaceOnce $rd 'It revalidates captured single-instance Hub context after acquiring the Manager mutation lock and makes active per-instance Hub inbox discovery independent of global Manager inbox existence, while preserving the qualified 4.17.5 architecture and Framework r24 contracts.' 'It revalidates captured single-instance Hub context after acquiring the Manager mutation lock, keeps active per-instance Hub inbox discovery independent of global Manager inbox existence, and preserves the captured Hub expectation across UpdateHub/UpdateAll including Manager self-update restart, while preserving the qualified 4.17.5 architecture and Framework r24 contracts.' 'README 4.17.6 summary'
W $readme $rd

# Adapt the inherited 4.17.5 regression only in the disposable working tree: its
# old prohibition on UpdateAll is intentionally superseded by 4.17.6. This file
# is restored before product publication and updated permanently after PASS.
$lr=R $legacyRegression
$lr=ReplaceOnce $lr "Assert `$rt.Contains('ExpectedInstanceId is valid only with -UpdateHub.') 'ExpectedInstanceId UpdateHub-only guard missing';Assert (-not `$rt.Contains('-UpdateHub or -UpdateAll')) 'ExpectedInstanceId must not allow UpdateAll';" "Assert `$rt.Contains('ExpectedInstanceId is valid only with -UpdateHub or -UpdateAll.') 'ExpectedInstanceId Hub-capable update guard missing';" 'legacy regression superseded UpdateAll assertion'
W $legacyRegression $lr

& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $manifestTool -RepositoryRoot $RepositoryRoot -Write
if($LASTEXITCODE-ne0){throw 'PUBLIC_FILE_MANIFEST generation failed.'}
$mf=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$mf.manager.version-cne'4.17.6'){throw 'Manifest version mismatch.'}
$prov=Get-Content -LiteralPath $provPath -Raw -Encoding UTF8|ConvertFrom-Json
$prov.source_manager_installation_sha256=[string]$mf.manager.installation_sha256
$prov.source_manager_gate_managed_content_sha256=[string]$mf.manager.gate_managed_content_sha256
$prov.source_gate_baseline_manager_version='4.17.5'
$prov.production_validation.full_gate_pass=$false;$prov.production_validation.gate_revision=$null;$prov.production_validation.tested_update_sha256=$null;$prov.production_validation.production_doctor_pass=$false;$prov.production_validation.production_ux_smoke_pass=$false;$prov.production_validation.production_managed_content_prefix=$null
$prov.gate_framework.frozen_for_manager_candidate=$false
$prov.public_candidate_revision=10
W $provPath ((($prov|ConvertTo-Json -Depth 30).Replace("`r`n","`n"))+"`n")
Write-Host ('MANAGER 4.17.6 UPDATE-CONTEXT FIX MATERIALIZED: managed='+[string]$mf.manager.gate_managed_content_sha256+' install='+[string]$mf.manager.installation_sha256) -ForegroundColor Green
