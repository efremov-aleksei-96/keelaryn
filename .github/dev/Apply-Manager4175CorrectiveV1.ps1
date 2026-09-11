[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..\..'))
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$root=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$runtime=Join-Path $root 'manager\product\runtime\Keelaryn__Manager.ps1'
$menu=Join-Path $root 'manager\product\tools\KeelarynMenu.ps1'
$install=Join-Path $root 'manager\product\install\INSTALLATION.json'
$release=Join-Path $root 'manager\product\manager_release.json'
$docs=Join-Path $root 'manager\product\docs\CANDIDATE_TRANSPORT.md'
$devValidation=Join-Path $root 'tools\Invoke-DevelopmentValidation.ps1'
$regression=Join-Path $root 'tools\Invoke-Manager4175ReviewRegression.ps1'
$utf8=New-Object Text.UTF8Encoding($false)
function R([string]$Path){return [IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8)}
function W([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$utf8)}
function Replace-One([string]$Path,[string]$Old,[string]$New){$t=R $Path;$i=$t.IndexOf($Old,[StringComparison]::Ordinal);if($i-lt0){throw('Anchor missing: '+$Path+' :: '+$Old)};if($t.IndexOf($Old,$i+$Old.Length,[StringComparison]::Ordinal)-ge0){throw('Anchor non-unique: '+$Path+' :: '+$Old)};W $Path ($t.Substring(0,$i)+$New+$t.Substring($i+$Old.Length))}
function Replace-OneRegex([string]$Path,[string]$Pattern,[string]$Replacement){$t=R $Path;$rx=New-Object Text.RegularExpressions.Regex($Pattern,[Text.RegularExpressions.RegexOptions]::Multiline);$m=$rx.Matches($t);if($m.Count-ne1){throw('Regex anchor count '+$m.Count+': '+$Path+' :: '+$Pattern)};W $Path ($rx.Replace($t,$Replacement,1))}

Replace-One $runtime '$ManagerVersion = "4.17.4"' '$ManagerVersion = "4.17.5"'
Replace-One $install '"manager_version": "4.17.4"' '"manager_version": "4.17.5"'
Replace-One $release '"manager_version":  "4.17.4"' '"manager_version":  "4.17.5"'
Replace-One $runtime '    [string]$GenesisInstanceName' "    [string]`$GenesisInstanceName,`r`n    [string]`$ExpectedInstanceId"
$switchLine='if (-not [string]::IsNullOrWhiteSpace($SwitchInstanceId)) { $SwitchInstanceId=([string]$SwitchInstanceId).Trim().ToLowerInvariant() }'
$expected=@'
if (-not [string]::IsNullOrWhiteSpace($SwitchInstanceId)) { $SwitchInstanceId=([string]$SwitchInstanceId).Trim().ToLowerInvariant() }
if (-not [string]::IsNullOrWhiteSpace($ExpectedInstanceId)) {
    $expectedGuid=[guid]::Empty
    if(-not[guid]::TryParse(([string]$ExpectedInstanceId).Trim(),[ref]$expectedGuid)-or$expectedGuid-eq[guid]::Empty){throw 'ExpectedInstanceId is invalid.'}
    $ExpectedInstanceId=$expectedGuid.ToString().ToLowerInvariant()
    if(-not($UpdateHub-or$UpdateAll)){throw 'ExpectedInstanceId is valid only with -UpdateHub or -UpdateAll.'}
}
'@.TrimEnd()
Replace-One $runtime $switchLine $expected
$resolvePattern='function Resolve-RegisteredInstanceContextEarly \{\r?\n    \$registry=Read-InstanceRegistryEarly\r?\n    if\(-not\$registry\)\{return \$false\}\r?\n    \$active=Read-ActiveInstanceEarly'
$resolve=@'
function Resolve-RegisteredInstanceContextEarly {
    $registry=Read-InstanceRegistryEarly
    if(-not$registry){
        if($ExpectedInstanceId){throw 'ExpectedInstanceId requires an initialized multi-Hub registry.'}
        return $false
    }
    $active=Read-ActiveInstanceEarly
    if($ExpectedInstanceId-and[string]$active.instance_id-ne[string]$ExpectedInstanceId){
        throw ('Active Hub changed before this Manager invocation bound its expected instance. Expected='+$ExpectedInstanceId+'; active='+[string]$active.instance_id+'. Retry the operation.')
    }
'@.TrimEnd()
Replace-OneRegex $runtime $resolvePattern $resolve
Replace-One $runtime "    if(`$parent-cne`$hubsRoot){throw('New registered Hub must be a direct child of '+`$hubsRoot+'.')}" "    if(-not `$parent.Equals(`$hubsRoot,[StringComparison]::OrdinalIgnoreCase)){throw('New registered Hub must be a direct child of '+`$hubsRoot+'.')}"

$t=R $menu
$old="    `$destinationInbox=`$Inbox`r`n    if(`$mode-eq'hub'){`$ctx=Get-FrontendInstanceContext;`$destinationInbox=[string]`$ctx.HubInbox;if(`$ctx.RegistryActive-and-not`$ctx.InstanceId){Fail('Multi-Hub registry is unresolved; Hub package import refused.')}}"
if($t.IndexOf($old,[StringComparison]::Ordinal)-lt0){$old=$old.Replace("`r`n","`n")}
$new=@'
    $destinationInbox=$Inbox
    $hubExpectedInstanceId=$null
    if($mode-eq'hub'){
        $ctx=Get-FrontendInstanceContext
        $destinationInbox=[string]$ctx.HubInbox
        if($ctx.RegistryActive-and-not$ctx.InstanceId){Fail('Multi-Hub registry is unresolved; Hub package import refused.')}
        if($ctx.RegistryActive){$hubExpectedInstanceId=[string]$ctx.InstanceId}
    }
'@.TrimEnd()
Replace-One $menu $old $new
Replace-One $menu "    return Invoke-Manager @('-UpdateHub')" @'
    $hubArgs=@('-UpdateHub')
    if($hubExpectedInstanceId){$hubArgs+=@('-ExpectedInstanceId',$hubExpectedInstanceId)}
    return Invoke-Manager $hubArgs
'@.TrimEnd()
$t=R $menu
$old="        'StorageReport','CleanTestsWork','CompactQualificationEvidence',`r`n        'OpenInbox','OpenLogs'";if($t.IndexOf($old,[StringComparison]::Ordinal)-lt0){$old=$old.Replace("`r`n","`n")}
$new=$old.Replace("'OpenInbox','OpenLogs'","'OpenInbox','OpenHubInbox','OpenLogs'")
Replace-One $menu $old $new
Replace-One $menu "        'OpenInbox' { Ensure-DirectorySafe `$Inbox 'Manager inbox'; return Open-Folder `$Inbox }" @'
        'OpenInbox' { Ensure-DirectorySafe $Inbox 'Manager inbox'; return Open-Folder $Inbox }
        'OpenHubInbox' { $ctx=Get-FrontendInstanceContext;if($ctx.RegistryActive-and-not$ctx.InstanceId){Fail('Multi-Hub registry is unresolved; active Hub inbox cannot be opened.')};$hubInbox=[string]$ctx.HubInbox;Ensure-DirectorySafe $hubInbox 'Active Hub inbox';return Open-Folder $hubInbox }
'@.TrimEnd()
Replace-One $menu "        Write-UiHost '  [7] Restore Hub CANDIDATE transport'" "        Write-UiHost '  [7] Restore Hub CANDIDATE transport'`r`n        Write-UiHost '  [I] Open active Hub inbox'"
Replace-One $menu "            '^7$' {`$null=Invoke-MenuAction 'RestoreCandidateTransport' `$null 'Restore Hub CANDIDATE transport';Pause-Menu}" "            '^7$' {`$null=Invoke-MenuAction 'RestoreCandidateTransport' `$null 'Restore Hub CANDIDATE transport';Pause-Menu}`r`n            '^(?i)i$' {`$null=Invoke-MenuAction 'OpenHubInbox' `$null 'Open active Hub inbox'}"

$doc=R $docs
$old1='Place one or more validated `Keelaryn__Hub_CANDIDATE_*.zip` files in Manager `state/inbox`, keep the matching canonical `state/baseline/Keelaryn__Hub_CURRENT.zip` in place, and run Development > Build CANDIDATE transport (compatibility command `compat/commands/BUILD_CANDIDATE_TRANSPORT.cmd`).'
$new1='Place one or more validated `Keelaryn__Hub_CANDIDATE_*.zip` files in the **active Hub inbox**, then run Development > Build CANDIDATE transport (compatibility command `compat/commands/BUILD_CANDIDATE_TRANSPORT.cmd`). Use Development > Open active Hub inbox to open the authoritative ingress. In single-instance compatibility mode this is Manager `state/inbox` with `state/baseline/Keelaryn__Hub_CURRENT.zip`; after multi-Hub initialization it is `state/instances/<instance_id>/inbox` with the matching `state/instances/<instance_id>/baseline/Keelaryn__Hub_CURRENT.zip`.'
$old2='If the original CANDIDATE ZIP is unavailable, place its transport JSON in `state/inbox` with the exact CURRENT used as `reconstruction_base`, then run Development > Restore CANDIDATE transport (compatibility command `compat/commands/RESTORE_CANDIDATE_TRANSPORT.cmd`).'
$new2='If the original CANDIDATE ZIP is unavailable, place its transport JSON in the **active Hub inbox** (Development > Open active Hub inbox) with the exact instance-bound CURRENT used as `reconstruction_base`, then run Development > Restore CANDIDATE transport (compatibility command `compat/commands/RESTORE_CANDIDATE_TRANSPORT.cmd`). In multi-Hub mode the active Hub inbox is `state/instances/<instance_id>/inbox`, not global `state/inbox`.'
if(-not$doc.Contains($old1)-or-not$doc.Contains($old2)){throw 'Candidate transport documentation anchors are missing.'}
W $docs ($doc.Replace($old1,$new1).Replace($old2,$new2))

$reg=@'
[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop';Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1';$menuPath=Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1';$docsPath=Join-Path $RepositoryRoot 'manager\product\docs\CANDIDATE_TRANSPORT.md'
function Assert([bool]$C,[string]$M){if(-not$C){throw $M}}
function F([string]$P,[string]$N){$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($P,[ref]$t,[ref]$e);if(@($e).Count){throw 'parse'};$r=@($a.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$N},$true));if($r.Count-ne1){throw('function '+$N+' count='+$r.Count)};return [string]$r[0].Extent.Text}
$p=Join-Path $PSHOME 'powershell.exe';foreach($n in @('Invoke-Manager4174ReviewRegression.ps1','Invoke-Manager4174BootstrapRegression.ps1')){& $p -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $RepositoryRoot ('tools\'+$n)) -RepositoryRoot $RepositoryRoot;if($LASTEXITCODE-ne0){throw($n+' failed')}}
Write-Host '  PASS inherited Manager 4.17.4 regressions'
$rt=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8);$mt=[IO.File]::ReadAllText($menuPath,[Text.Encoding]::UTF8);$dt=[IO.File]::ReadAllText($docsPath,[Text.Encoding]::UTF8)
Assert $rt.Contains('[string]$ExpectedInstanceId') 'missing ExpectedInstanceId';Assert $mt.Contains("@('-ExpectedInstanceId',`$hubExpectedInstanceId)") 'frontend expected instance missing';Assert $mt.Contains("'OpenHubInbox'") 'OpenHubInbox missing';Assert $dt.Contains('state/instances/<instance_id>/inbox') 'instance inbox docs missing';Assert $dt.Contains('Development > Open active Hub inbox') 'inbox UI docs missing'
Invoke-Expression (F $runtimePath 'Resolve-RegisteredInstanceContextEarly');$ExpectedInstanceId='11111111-1111-1111-1111-111111111111';function Read-InstanceRegistryEarly{return [pscustomobject]@{instances=@()}};function Read-ActiveInstanceEarly{return [pscustomobject]@{instance_id='22222222-2222-2222-2222-222222222222'}};$blocked=$false;try{$null=Resolve-RegisteredInstanceContextEarly}catch{$blocked=$_.Exception.Message.Contains('Expected=11111111-1111-1111-1111-111111111111')};Assert $blocked 'expected-instance guard did not fail closed'
Write-Host '  PASS expected-instance runtime guard'
Invoke-Expression (F $runtimePath 'Assert-NewRegisteredHubTargetPathSafe');$temp=Join-Path ([IO.Path]::GetTempPath()) ('k4175_'+[guid]::NewGuid().ToString('N'));[void][IO.Directory]::CreateDirectory($temp);try{$script:InstanceRegistryFile=Join-Path $temp 'instances.json';[IO.File]::WriteAllText($script:InstanceRegistryFile,'{}');$LayoutRoot=$temp.ToUpperInvariant();$Root=Join-Path $temp 'manager';$CanonicalTestsPath=Join-Path $temp 'tests';function Test-IsWindowsReservedPathSegment{return $false};function Test-KeelarynPathOverlap{return $false};function Get-ManagerInstanceRegistry{return [pscustomobject]@{instances=@()}};$target=Join-Path (Join-Path $temp.ToLowerInvariant() 'hubs') 'new-hub';$actual=Assert-NewRegisteredHubTargetPathSafe $target;Assert ([IO.Path]::GetFullPath($actual).Equals([IO.Path]::GetFullPath($target),[StringComparison]::OrdinalIgnoreCase)) 'case-insensitive Genesis path failed'}finally{if(Test-Path $temp){Remove-Item $temp -Recurse -Force}}
Write-Host '  PASS Windows case-insensitive Genesis path'
Invoke-Expression (F $menuPath 'Import-Package');$temp=Join-Path ([IO.Path]::GetTempPath()) ('k4175imp_'+[guid]::NewGuid().ToString('N'));[void][IO.Directory]::CreateDirectory($temp);try{$Inbox=Join-Path $temp 'mi';[void][IO.Directory]::CreateDirectory($Inbox);$activeInbox=Join-Path $temp 'hi';[void][IO.Directory]::CreateDirectory($activeInbox);$pkg=Join-Path $temp 'Keelaryn__Hub_APPROVED_test.zip';[IO.File]::WriteAllText($pkg,'approved');$script:Args=@();function Test-ReparsePoint{return $false};function Get-FrontendInstanceContext{return [pscustomobject]@{RegistryActive=$true;InstanceId='33333333-3333-3333-3333-333333333333';HubInbox=$activeInbox}};function Ensure-DirectorySafe([string]$Path,[string]$Purpose){if(-not(Test-Path $Path)){[void][IO.Directory]::CreateDirectory($Path)}};function Get-FileSha256Hex([string]$Path){return (Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant()};function Write-UiHost{};function Invoke-Manager([string[]]$ManagerArgs){$script:Args=@($ManagerArgs);return 0};function Request-CommitConfirmation{return $false};function Set-ActionSemantic{};$Replace=$false;$rc=Import-Package $pkg;Assert ($rc-eq0) 'Hub import failed';Assert ($script:Args.Count-eq3) 'Hub import args count';Assert ($script:Args[0]-ceq'-UpdateHub') 'Hub action';Assert ($script:Args[1]-ceq'-ExpectedInstanceId') 'expected flag';Assert ($script:Args[2]-ceq'33333333-3333-3333-3333-333333333333') 'expected id';Assert (Test-Path (Join-Path $activeInbox 'Keelaryn__Hub_APPROVED_test.zip')) 'copy not in active inbox'}finally{if(Test-Path $temp){Remove-Item $temp -Recurse -Force}}
Write-Host '  PASS Hub import/update captured-instance binding'
Write-Host 'MANAGER 4.17.5 REVIEW REGRESSION: PASS' -ForegroundColor Green
'@
W $regression $reg
Replace-One $devValidation "Write-Host '[2/5] Run Manager 4.17.4 review/bootstrap regressions...'" "Write-Host '[2/5] Run Manager 4.17.5 regression chain...'"
Replace-One $devValidation "foreach(`$regressionName in @('Invoke-Manager4174ReviewRegression.ps1','Invoke-Manager4174BootstrapRegression.ps1')){" "foreach(`$regressionName in @('Invoke-Manager4175ReviewRegression.ps1')){"
Replace-One $devValidation "if(-not(Test-Path -LiteralPath `$regression -PathType Leaf)){Fail('Manager 4.17.4 regression tool is missing: '+`$regressionName)}" "if(-not(Test-Path -LiteralPath `$regression -PathType Leaf)){Fail('Manager 4.17.5 regression tool is missing: '+`$regressionName)}"
Replace-One $devValidation "Write-Host 'Review/bootstrap regressions: PASS' -ForegroundColor Green" "Write-Host 'Manager 4.17.5 regression chain: PASS' -ForegroundColor Green"
foreach($p in @($runtime,$menu,$devValidation,$regression)){$tok=$null;$err=$null;[void][Management.Automation.Language.Parser]::ParseFile($p,[ref]$tok,[ref]$err);if(@($err).Count){throw('Parser failed '+$p+': '+([string]::Join(' | ',@($err|ForEach-Object{$_.Message}))))}}
& $p=$null
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $regression -RepositoryRoot $root
if($LASTEXITCODE-ne0){throw '4.17.5 regression failed'}
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $root 'tools\Build-PublicFileManifest.ps1') -RepositoryRoot $root -Write
if($LASTEXITCODE-ne0){throw 'manifest write failed'}
$manifest=Get-Content (Join-Path $root 'PUBLIC_FILE_MANIFEST.json') -Raw -Encoding UTF8|ConvertFrom-Json;$provPath=Join-Path $root 'PUBLIC_PROVENANCE.json';$prov=Get-Content $provPath -Raw -Encoding UTF8|ConvertFrom-Json;$prov.source_manager_version='4.17.5';$prov.source_gate_baseline_manager_version='4.17.4';$prov.source_manager_installation_sha256=[string]$manifest.manager.installation_sha256;$prov.source_manager_gate_managed_content_sha256=[string]$manifest.manager.gate_managed_content_sha256;$prov.production_validation.full_gate_pass=$false;$prov.production_validation.gate_revision=$null;$prov.production_validation.framework_revision=24;$prov.production_validation.tested_update_sha256=$null;$prov.production_validation.production_doctor_pass=$false;$prov.production_validation.production_ux_smoke_pass=$false;$prov.production_validation.production_managed_content_prefix=$null;$prov.public_candidate_revision=8;$prov.gate_framework.frozen_for_manager_candidate=$false;$prov.known_nonsecret_source_hygiene_notes=@('manager/product/docs/TESTING.md retains a maintainer-local D:\0\0__Core example for historical/maintainer qualification context; it is not a product installation default.');$prov|ConvertTo-Json -Depth 20|Set-Content $provPath -Encoding UTF8
Write-Host 'PATCH MATERIALIZATION: PASS' -ForegroundColor Green
