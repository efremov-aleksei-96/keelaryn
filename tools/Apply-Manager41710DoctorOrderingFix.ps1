[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RepositoryRoot)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Replace-ExactlyOnce([string]$Text,[string]$Pattern,[string]$Replacement,[string]$Label){
    $m=[regex]::Matches($Text,$Pattern,[Text.RegularExpressions.RegexOptions]::Multiline)
    if($m.Count-ne1){throw("$Label expected exactly one match; observed $($m.Count).")}
    return [regex]::Replace($Text,$Pattern,$Replacement,[Text.RegularExpressions.RegexOptions]::Multiline)
}

$runtime=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$installation=Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json'
$release=Join-Path $RepositoryRoot 'manager\product\manager_release.json'
$readme=Join-Path $RepositoryRoot 'manager\README_FIRST.md'
foreach($p in @($runtime,$installation,$release,$readme)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Required product file missing: '+$p)}}

$text=[IO.File]::ReadAllText($runtime)
$text=Replace-ExactlyOnce $text '(?m)^\$ManagerVersion = "4\.17\.9"$' '$ManagerVersion = "4.17.10"' 'runtime version marker'
$doctorStart=$text.IndexOf('function Invoke-Doctor {',[StringComparison]::Ordinal)
if($doctorStart-lt0){throw 'Invoke-Doctor not found.'}
$nextFunction=$text.IndexOf("`nfunction ",$doctorStart+1,[StringComparison]::Ordinal)
if($nextFunction-lt0){throw 'Invoke-Doctor function boundary not found.'}
$doctor=$text.Substring($doctorStart,$nextFunction-$doctorStart)
$rowsMatches=[regex]::Matches($doctor,'(?m)^[ \t]*\$rows=New-Object System\.Collections\.ArrayList\r?$')
if($rowsMatches.Count-ne1){throw("Invoke-Doctor expected exactly one rows initializer before fix; observed $($rowsMatches.Count).")}
$doctor=[regex]::Replace($doctor,'(?m)^[ \t]*\$rows=New-Object System\.Collections\.ArrayList\r?\n','',1)
$open=[regex]::Match($doctor,'^function Invoke-Doctor \{(\r?\n)')
if(-not$open.Success){throw 'Invoke-Doctor opening line is not canonical.'}
$nl=$open.Groups[1].Value
$doctor=$doctor.Insert($open.Length,'    $rows=New-Object System.Collections.ArrayList'+$nl)
$prefix=$doctor.Substring(0,[Math]::Min($doctor.Length,400))
if($prefix-notmatch '^function Invoke-Doctor \{\r?\n    \$rows=New-Object System\.Collections\.ArrayList\r?\n'){throw 'Doctor rows initializer was not moved to function entry.'}
$text=$text.Substring(0,$doctorStart)+$doctor+$text.Substring($nextFunction)
[IO.File]::WriteAllText($runtime,$text,(New-Object Text.UTF8Encoding($false)))

$text=[IO.File]::ReadAllText($installation)
$text=Replace-ExactlyOnce $text '(?m)^  "manager_version": "4\.17\.9",$' '  "manager_version": "4.17.10",' 'INSTALLATION manager_version'
[IO.File]::WriteAllText($installation,$text,(New-Object Text.UTF8Encoding($false)))

$text=[IO.File]::ReadAllText($release)
$text=Replace-ExactlyOnce $text '(?m)^    "manager_version":  "4\.17\.9",$' '    "manager_version":  "4.17.10",' 'manager_release manager_version'
[IO.File]::WriteAllText($release,$text,(New-Object Text.UTF8Encoding($false)))

$text=[IO.File]::ReadAllText($readme)
$old='(?s)\A# Keelaryn Manager 4\.17\.9\r?\n(Manager 4\.17\.9 .*?Production multi-Hub remains disabled until this successor completes qualification\.)\r?\n\r?\n## 4\.17\.8 context'
$m=[regex]::Match($text,$old)
if(-not$m.Success){throw 'README 4.17.9 lead section is not canonical.'}
$lead="# Keelaryn Manager 4.17.10`r`nManager 4.17.10 is the corrective successor to the production-qualified but public-release-rejected Manager 4.17.9. It initializes the Doctor finding accumulator before any registry-active diagnostic path, so registered-mode Doctor cannot dereference an uninitialized collection while scanning global Hub-owned inbox objects. It preserves the qualified 4.17.9 multi-Hub convergence behavior and Framework r24 contracts. Production multi-Hub remains disabled until this successor completes qualification.`r`n`r`n## 4.17.9 context`r`n"+$m.Groups[1].Value+"`r`n`r`n## 4.17.8 context"
$text=$text.Substring(0,$m.Index)+$lead+$text.Substring($m.Index+$m.Length)
[IO.File]::WriteAllText($readme,$text,(New-Object Text.UTF8Encoding($false)))

Write-Host 'Manager 4.17.10 Doctor-ordering product materialization staged: PASS' -ForegroundColor Green
