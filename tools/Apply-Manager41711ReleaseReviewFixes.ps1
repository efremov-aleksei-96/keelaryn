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
foreach($p in @($runtime,$installation,$release,$readme)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Required product file missing: '+$p)}}

$text=[IO.File]::ReadAllText($runtime)
$text=Replace-ExactlyOnce $text '(?m)^\$ManagerVersion = "4\.17\.10"$' '$ManagerVersion = "4.17.11"' 'runtime version marker'
$pendingOld='(?m)^    \$pendingCandidates=@\(Get-ChildItem -LiteralPath \$Inbox -File -Filter ''\*\.zip'' -ErrorAction SilentlyContinue \| Where-Object \{ \$_\.Name\.StartsWith\(''Keelaryn__Hub_CANDIDATE_'',\[System\.StringComparison\]::OrdinalIgnoreCase\) -or \$_\.Name\.StartsWith\(\[string\]\$LegacyCoreCompat\.CandidatePrefix,\[System\.StringComparison\]::OrdinalIgnoreCase\) \}\)\.Count\r?$'
$pendingNew='    $pendingCandidates=@(Get-ChildItem -LiteralPath $HubInbox -File -Filter ''*.zip'' -ErrorAction SilentlyContinue | Where-Object { $_.Name.StartsWith(''Keelaryn__Hub_CANDIDATE_'',[System.StringComparison]::OrdinalIgnoreCase) -or $_.Name.StartsWith([string]$LegacyCoreCompat.CandidatePrefix,[System.StringComparison]::OrdinalIgnoreCase) }).Count'
$text=Replace-ExactlyOnce $text $pendingOld $pendingNew 'registry pending-CANDIDATE inbox routing'
[IO.File]::WriteAllText($runtime,$text,$Utf8NoBom)

$text=[IO.File]::ReadAllText($installation)
$text=Replace-ExactlyOnce $text '(?m)^  "manager_version": "4\.17\.10",\r?$' '  "manager_version": "4.17.11",' 'INSTALLATION manager_version'
[IO.File]::WriteAllText($installation,$text,$Utf8NoBom)

$text=[IO.File]::ReadAllText($release)
$text=Replace-ExactlyOnce $text '(?m)^    "manager_version":  "4\.17\.10",\r?$' '    "manager_version":  "4.17.11",' 'manager_release manager_version'
[IO.File]::WriteAllText($release,$text,$Utf8NoBom)

$text=[IO.File]::ReadAllText($readme)
$leadPattern='(?s)\A# Keelaryn Manager 4\.17\.10\r?\n(Manager 4\.17\.10 .*?Production multi-Hub remains disabled until this successor completes qualification\.)\r?\n\r?\n## 4\.17\.9 context'
$m=[regex]::Match($text,$leadPattern)
if(-not$m.Success){throw 'README 4.17.10 lead section is not canonical.'}
$lead="# Keelaryn Manager 4.17.11`r`nManager 4.17.11 is the corrective successor to the production-qualified but public-release-rejected Manager 4.17.10. It keeps pending Hub CANDIDATE reporting bound to the active instance inbox in registry mode and brings managed qualification instructions onto the exact 4.17.10 -> 4.17.11 transition. It preserves the qualified 4.17.10 single-instance behavior and Framework r24 contracts. Production multi-Hub remains disabled until this successor completes qualification.`r`n`r`n## 4.17.10 context`r`n"+$m.Groups[1].Value+"`r`n`r`n## 4.17.9 context"
$text=$text.Substring(0,$m.Index)+$lead+$text.Substring($m.Index+$m.Length)
$text=Replace-LiteralExactlyOnce $text 'Manager 4.17.7 preserves the native update compatibility floor in `product/manager_release.json` and the established UPDATE transition envelope.' 'Manager 4.17.11 preserves the native update compatibility floor in `product/manager_release.json` and the established UPDATE transition envelope.' 'README update compatibility version'
$text=Replace-LiteralExactlyOnce $text 'The normal production qualification transition for this corrective candidate is production-installed Manager 4.17.6 -> 4.17.7.' 'The normal production qualification transition for this corrective candidate is production-installed Manager 4.17.10 -> 4.17.11.' 'README qualification transition'
$text=Replace-LiteralExactlyOnce $text 'Installing Manager 4.17.7 alone must not change canonical Hub content.' 'Installing Manager 4.17.11 alone must not change canonical Hub content.' 'README install immutability version'
$text=Replace-LiteralExactlyOnce $text 'This source is not production-approved merely because it carries version 4.17.7. Production approval requires the applicable Windows PowerShell parser/static checks, inherited and 4.17.7 regressions, Manager/frontend SelfTests, deterministic SOURCE/DISTRIBUTION/UPDATE/AI_CONTEXT checks, disposable 4.17.6 -> 4.17.7 update and rollback/fault-injection coverage, Doctor/migration/UI/Genesis coverage, production Hub immutability, exact tested/public-source/release UPDATE identity, real CURRENT-backed Full Gate and gated publication. The consolidated gate uses qualified Gate Framework r24.' 'This source is not production-approved merely because it carries version 4.17.11. Production approval requires the applicable Windows PowerShell parser/static checks, inherited and 4.17.11 regressions, Manager/frontend SelfTests, deterministic SOURCE/DISTRIBUTION/UPDATE/AI_CONTEXT checks, disposable 4.17.10 -> 4.17.11 update and rollback/fault-injection coverage, Doctor/migration/UI/Genesis coverage, production Hub immutability, exact tested/public-source/release UPDATE identity, real CURRENT-backed Full Gate and gated publication. The consolidated gate uses qualified Gate Framework r24.' 'README release gate transition'
[IO.File]::WriteAllText($readme,$text,$Utf8NoBom)

Write-Host 'Manager 4.17.11 release-review product materialization staged: PASS' -ForegroundColor Green
