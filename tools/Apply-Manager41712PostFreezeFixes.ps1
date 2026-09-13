[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RepositoryRoot)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Replace-ExactlyOnce([string]$Text,[string]$Pattern,[string]$Replacement,[string]$Label){
    $m=[regex]::Matches($Text,$Pattern,[Text.RegularExpressions.RegexOptions]::Multiline)
    if($m.Count-ne1){throw("$Label expected exactly one match; observed $($m.Count).")}
    return [regex]::Replace($Text,$Pattern,$Replacement,[Text.RegularExpressions.RegexOptions]::Multiline)
}
function Replace-SinglelineExactlyOnce([string]$Text,[string]$Pattern,[string]$Replacement,[string]$Label){
    $options=[Text.RegularExpressions.RegexOptions]::Multiline-bor[Text.RegularExpressions.RegexOptions]::Singleline
    $m=[regex]::Matches($Text,$Pattern,$options)
    if($m.Count-ne1){throw("$Label expected exactly one match; observed $($m.Count).")}
    return [regex]::Replace($Text,$Pattern,$Replacement,$options)
}
function Replace-LiteralExactlyOnce([string]$Text,[string]$Old,[string]$New,[string]$Label){
    $first=$Text.IndexOf($Old,[StringComparison]::Ordinal)
    if($first-lt0){throw("$Label expected exactly one literal match; observed 0.")}
    $second=$Text.IndexOf($Old,$first+$Old.Length,[StringComparison]::Ordinal)
    if($second-ge0){throw("$Label expected exactly one literal match; observed more than one.")}
    return $Text.Substring(0,$first)+$New+$Text.Substring($first+$Old.Length)
}

$runtime=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$installation=Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json'
$release=Join-Path $RepositoryRoot 'manager\product\manager_release.json'
$readme=Join-Path $RepositoryRoot 'manager\README_FIRST.md'
$frontend=Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1'
foreach($p in @($runtime,$installation,$release,$readme,$frontend)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Required product file missing: '+$p)}}

$text=[IO.File]::ReadAllText($runtime)
$text=Replace-ExactlyOnce $text '(?m)^\$ManagerVersion = "4\.17\.11"$' '$ManagerVersion = "4.17.12"' 'runtime version marker'
[IO.File]::WriteAllText($runtime,$text,$Utf8NoBom)

$text=[IO.File]::ReadAllText($installation)
$text=Replace-ExactlyOnce $text '(?m)^  "manager_version": "4\.17\.11",\r?$' '  "manager_version": "4.17.12",' 'INSTALLATION manager_version'
[IO.File]::WriteAllText($installation,$text,$Utf8NoBom)

$text=[IO.File]::ReadAllText($release)
$text=Replace-ExactlyOnce $text '(?m)^    "manager_version":  "4\.17\.11",\r?$' '    "manager_version":  "4.17.12",' 'manager_release manager_version'
[IO.File]::WriteAllText($release,$text,$Utf8NoBom)

$text=[IO.File]::ReadAllText($readme)
$leadPattern='(?s)\A# Keelaryn Manager 4\.17\.11\r?\n(Manager 4\.17\.11 .*?Production multi-Hub remains disabled until this successor completes qualification\.)\r?\n\r?\n## 4\.17\.10 context'
$m=[regex]::Match($text,$leadPattern)
if(-not$m.Success){throw 'README 4.17.11 lead section is not canonical.'}
$lead="# Keelaryn Manager 4.17.12`r`nManager 4.17.12 is the corrective successor to the production-installed but public-release-rejected Manager 4.17.11. It restores target-driven recovery switching in the Manage Hubs UI when active selection metadata is broken, while preserving runtime target validation and fail-closed behavior for actions that require a resolved active Hub. It also ships with the hardened pre-freeze risk-range contract in repository tooling. Production multi-Hub remains disabled until this successor completes qualification, installation, public release, and separate activation approval.`r`n`r`n## 4.17.11 context`r`n"+$m.Groups[1].Value+"`r`n`r`n## 4.17.10 context"
$text=$text.Substring(0,$m.Index)+$lead+$text.Substring($m.Index+$m.Length)
$text=Replace-LiteralExactlyOnce $text 'Manager 4.17.11 preserves the native update compatibility floor in `product/manager_release.json` and the established UPDATE transition envelope.' 'Manager 4.17.12 preserves the native update compatibility floor in `product/manager_release.json` and the established UPDATE transition envelope.' 'README update compatibility version'
$text=Replace-LiteralExactlyOnce $text 'The normal production qualification transition for this corrective candidate is production-installed Manager 4.17.10 -> 4.17.11.' 'The normal production qualification transition for this corrective candidate is production-installed Manager 4.17.11 -> 4.17.12.' 'README qualification transition'
$text=Replace-LiteralExactlyOnce $text 'Installing Manager 4.17.11 alone must not change canonical Hub content.' 'Installing Manager 4.17.12 alone must not change canonical Hub content.' 'README install immutability version'
$text=Replace-LiteralExactlyOnce $text 'This source is not production-approved merely because it carries version 4.17.11. Production approval requires the applicable Windows PowerShell parser/static checks, inherited and 4.17.11 regressions, Manager/frontend SelfTests, deterministic SOURCE/DISTRIBUTION/UPDATE/AI_CONTEXT checks, disposable 4.17.10 -> 4.17.11 update and rollback/fault-injection coverage, Doctor/migration/UI/Genesis coverage, production Hub immutability, exact tested/public-source/release UPDATE identity, real CURRENT-backed Full Gate and gated publication. The consolidated gate uses qualified Gate Framework r24.' 'This source is not production-approved merely because it carries version 4.17.12. Production approval requires the applicable Windows PowerShell parser/static checks, inherited and 4.17.12 regressions, Manager/frontend SelfTests, deterministic SOURCE/DISTRIBUTION/UPDATE/AI_CONTEXT checks, disposable 4.17.11 -> 4.17.12 update and rollback/fault-injection coverage, Doctor/migration/UI/Genesis coverage, production Hub immutability, exact tested/public-source/release UPDATE identity, real CURRENT-backed Full Gate and gated publication. The consolidated gate uses qualified Gate Framework r24.' 'README release gate transition'
[IO.File]::WriteAllText($readme,$text,$Utf8NoBom)

$text=[IO.File]::ReadAllText($frontend)
$registryPattern='(?s)function Get-FrontendRegistryRows \{.*?\r?\n\}\r?\n\r?\nfunction Show-HubManagementMenu \{'
$registryReplacement=@'
function Get-FrontendRegistryRows {
    if(-not$StateLayoutActive){return @()}
    $registryPath=Join-Path $StateRoot 'instances.json'
    if(-not(Test-Path -LiteralPath $registryPath -PathType Leaf)){return @()}
    $item=Get-Item -LiteralPath $registryPath -Force -ErrorAction Stop
    if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0-or$item.Length-gt1MB){throw 'Manager instance registry is unsafe.'}
    try{$registry=Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8|ConvertFrom-Json}catch{throw('Manager instance registry JSON is invalid: '+$_.Exception.Message)}
    if([string]$registry.schema-cne'keelaryn.manager.instances.v1'){throw 'Unsupported Manager instance registry schema.'}
    $rows=New-Object System.Collections.ArrayList
    $seen=New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    foreach($candidate in @($registry.instances)){
        $id=ConvertTo-CanonicalFrontendInstanceId $candidate.instance_id
        if(-not$seen.Add($id)){throw('Manager instance registry contains duplicate instance_id: '+$id)}
        $name=([string]$candidate.name).Trim()
        if(-not$name-or$name.Length-gt64-or$name-match'[\x00-\x1F]'){throw('Manager instance registry contains invalid display name for '+$id)}
        [void]$rows.Add([pscustomobject]@{instance_id=$id;name=$name;vault_path=[string]$candidate.vault_path})
    }
    if($rows.Count-eq0){throw 'Manager instance registry contains no instances.'}
    return @($rows|Sort-Object name,instance_id)
}

function Show-HubManagementMenu {
'@
$text=Replace-SinglelineExactlyOnce $text $registryPattern $registryReplacement 'frontend registry enumeration independence'

# Scope recovery replacement to the exact UI function. Similar unresolved-active guards
# elsewhere are intentionally retained and must not be broadened into recovery paths.
$showPattern='(?s)function Show-HubManagementMenu \{.*?\r?\n\}\r?\nfunction Show-MaintenanceMenu \{'
$showMatches=[regex]::Matches($text,$showPattern)
if($showMatches.Count-ne1){throw("Show-HubManagementMenu function scope expected exactly one match; observed $($showMatches.Count).")}
$showBlock=$showMatches[0].Value
$unresolvedPattern=@'
(?s)        if\(-not\$ctx\.InstanceId\)\{\r?\n            Write-UiHost 'Registry exists but is invalid/unresolved\. Run Doctor; switching is disabled\.' -ForegroundColor Red\r?\n            Write-UiHost '  \[0\] Back'\r?\n            if\(\(Read-UiInput 'Select'\)\.Trim\(\)-eq'0'\)\{return\}\r?\n            continue\r?\n        \}
'@
$unresolvedReplacement=@'
        if(-not$ctx.InstanceId){
            $rows=@()
            try{$rows=@(Get-FrontendRegistryRows)}catch{
                Write-UiHost ('Registry exists but cannot be enumerated safely: '+$_.Exception.Message) -ForegroundColor Red
                Write-UiHost 'Run Doctor; recovery switching remains fail-closed until the registry itself is valid.' -ForegroundColor Yellow
                Write-UiHost '  [0] Back'
                if((Read-UiInput 'Select').Trim()-eq'0'){return}
                continue
            }
            Write-UiHost 'Active selection is invalid/unresolved. Choose a registered Hub to recover active selection.' -ForegroundColor Yellow
            for($i=0;$i-lt$rows.Count;$i++){
                Write-UiHost ('  [{0}] {1} | {2}' -f ($i+1),[string]$rows[$i].name,([string]$rows[$i].instance_id).Substring(0,8))
            }
            Write-UiHost '  [0] Back'
            $raw=(Read-UiInput 'Select recovery Hub number').Trim()
            if($raw-eq'0'){return}
            $n=0
            if([int]::TryParse($raw,[ref]$n)-and$n-ge1-and$n-le$rows.Count){
                $target=$rows[$n-1]
                if(Confirm ('Recover active selection by switching to '+[string]$target.name+'?')){
                    $null=Invoke-Manager @('-SwitchInstanceId',[string]$target.instance_id)
                    Pause-Menu
                }
            }else{Write-UiHost 'Invalid selection.' -ForegroundColor Yellow;Pause-Menu}
            continue
        }
'@
$updatedShowBlock=Replace-SinglelineExactlyOnce $showBlock $unresolvedPattern $unresolvedReplacement 'frontend unresolved-active recovery menu within Show-HubManagementMenu'
$text=Replace-LiteralExactlyOnce $text $showBlock $updatedShowBlock 'Show-HubManagementMenu scoped publication'
if($updatedShowBlock.Contains('Registry exists but is invalid/unresolved. Run Doctor; switching is disabled.')){throw 'Stale frontend recovery-blocking message remains inside Show-HubManagementMenu.'}
[IO.File]::WriteAllText($frontend,$text,$Utf8NoBom)

Write-Host 'Manager 4.17.12 post-freeze product materialization staged: PASS' -ForegroundColor Green
