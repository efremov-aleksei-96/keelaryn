[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [string]$EvidenceRoot=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Utf8=New-Object Text.UTF8Encoding($false)
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path $env:RUNNER_TEMP 'manager-41713-prefreeze-knowledge-r7d'}
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null

function Fail([string]$Message){throw $Message}
function Replace-Exact([string]$Text,[string]$Old,[string]$New,[string]$Label){
    $count=[regex]::Matches($Text,[regex]::Escape($Old)).Count
    if($count-ne1){Fail($Label+' count='+$count)}
    return $Text.Replace($Old,$New)
}

$source=Join-Path $PSScriptRoot 'Materialize-Manager41713PrefreezeKnowledgeR7.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){Fail('R7 source materializer missing: '+$source)}
$text=[IO.File]::ReadAllText($source,[Text.Encoding]::UTF8)

# R7/R7b failed before target materialization because generated PowerShell path literals
# were written with C/JSON-style doubled backslashes. PowerShell does not escape backslash.
$fixes=[ordered]@{
    'instances\\'='instances\'
    '\\baseline\\Keelaryn__Hub_CURRENT.zip'='\baseline\Keelaryn__Hub_CURRENT.zip'
    'baseline\\Keelaryn__Hub_CURRENT.zip'='baseline\Keelaryn__Hub_CURRENT.zip'
    '\\inbox'='\inbox'
    '_System\\STATE.md'='_System\STATE.md'
}
foreach($old in @($fixes.Keys)){
    $count=[regex]::Matches($text,[regex]::Escape($old)).Count
    if($count-lt1){Fail('Expected R7 path-literal defect was not found: '+$old)}
    $text=$text.Replace($old,[string]$fixes[$old])
}

# R7c reached the strengthened knowledge validator and exposed a second harness defect:
# the pre-R7 validator assumed every model state was one of the original five degraded
# states. R7 adds healthy/inactive/pending states for targeted InitializeRegistry proof;
# they must not inherit the old all-action cross-product implicitly.
$anchor="Replace-Once `$entryValidatorPath `$oldStates `$newStates 'entry validator required states'"
$injection=@'
Replace-Once $entryValidatorPath $oldStates $newStates 'entry validator required states'
$oldAllDegraded="foreach(`$sid in @(`$stateIds)){`n    foreach(`$aid in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','UpdateHub')){`n        if(-not`$pairs.Contains(`$sid+'|'+`$aid)){Fail('All-degraded coverage omitted '+`$sid+'|'+`$aid)}`n    }`n}"
$newAllDegraded="foreach(`$sid in @('REGISTRY_ACTIVE_METADATA_INVALID','REGISTRY_ACTIVE_HUB_MISSING','REGISTRY_ACTIVE_HUB_CORRUPT','REGISTRY_ACTIVE_CURRENT_MISSING','REGISTRY_ACTIVE_CURRENT_CORRUPT')){`n    foreach(`$aid in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','UpdateHub')){`n        if(-not`$pairs.Contains(`$sid+'|'+`$aid)){Fail('All-degraded coverage omitted '+`$sid+'|'+`$aid)}`n    }`n}"
Replace-Once $entryValidatorPath $oldAllDegraded $newAllDegraded 'entry validator explicit degraded cross-product states'
'@
$text=Replace-Exact $text $anchor $injection.TrimEnd("`r","`n") 'R7d validator-scope injection'

$temp=Join-Path $env:RUNNER_TEMP 'Materialize-Manager41713PrefreezeKnowledgeR7d.inner.ps1'
[IO.File]::WriteAllText($temp,$text,$Utf8)
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
if(@($errors).Count-ne0){Fail('R7d patched materializer parse failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}

$exe=Join-Path $PSHOME 'powershell.exe'
& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot -ExpectedBase $ExpectedBase -EvidenceRoot $EvidenceRoot
$code=[int]$LASTEXITCODE
if($code-ne0){exit $code}
Write-Host 'Manager 4.17.13 R7d gate-harness correction: PASS' -ForegroundColor Green
