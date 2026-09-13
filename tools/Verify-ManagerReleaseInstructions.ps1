[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message){throw $Message}
function Read-Json([string]$Path){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){Fail('Required file missing: '+$Path)}
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8)|ConvertFrom-Json
}
function Get-Section([string]$Text,[string]$Heading){
    $pattern='(?ms)^## '+[regex]::Escape($Heading)+'\s*\r?\n(?<body>.*?)(?=^## |\z)'
    $m=[regex]::Match($Text,$pattern)
    if(-not$m.Success){Fail('Managed README section missing: '+$Heading)}
    return [string]$m.Groups['body'].Value
}

$install=Read-Json (Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json')
$state=Read-Json (Join-Path $RepositoryRoot 'MANAGER_DEVELOPMENT_STATE.json')
$readmePath=Join-Path $RepositoryRoot 'manager\README_FIRST.md'
if(-not(Test-Path -LiteralPath $readmePath -PathType Leaf)){Fail('Managed README missing: '+$readmePath)}
$readme=Get-Content -LiteralPath $readmePath -Raw -Encoding UTF8

$current=([string]$install.manager_version).Trim()
if($current-notmatch'^\d+\.\d+\.\d+$'){Fail('Invalid current Manager version: '+$current)}
$successor=([string]$state.lineage.successor_manager_version).Trim()
$baseline=([string]$state.lineage.production_manager_version).Trim()
if($successor-cne$current){Fail('Development state successor/current version mismatch: successor='+$successor+' current='+$current)}
if($baseline-notmatch'^\d+\.\d+\.\d+$'){Fail('Invalid production baseline version: '+$baseline)}
if($baseline-ceq$current){Fail('Release-instruction guard requires a successor transition; baseline equals current '+$current)}

$firstLine=($readme -split '\r?\n',2)[0]
$expectedHeading='# Keelaryn Manager '+$current
if($firstLine-cne$expectedHeading){Fail('Managed README current heading mismatch: observed="'+$firstLine+'" expected="'+$expectedHeading+'"')}

$update=Get-Section $readme 'Update compatibility'
$release=Get-Section $readme 'Release gate'
$transition='production-installed Manager '+$baseline+' -> '+$current
foreach($pair in @(
    [pscustomobject]@{Section='Update compatibility';Text=$update;Token=('Manager '+$current+' preserves the native update compatibility floor')},
    [pscustomobject]@{Section='Update compatibility';Text=$update;Token=$transition},
    [pscustomobject]@{Section='Update compatibility';Text=$update;Token=('Installing Manager '+$current+' alone must not change canonical Hub content.')},
    [pscustomobject]@{Section='Release gate';Text=$release;Token=('carries version '+$current)},
    [pscustomobject]@{Section='Release gate';Text=$release;Token=('inherited and '+$current+' regressions')},
    [pscustomobject]@{Section='Release gate';Text=$release;Token=('disposable '+$baseline+' -> '+$current+' update')}
)){
    if(-not$pair.Text.Contains($pair.Token)){Fail($pair.Section+' does not bind the canonical release identity: '+$pair.Token)}
}

$versionPattern='\b\d+\.\d+\.\d+\b'
$updateVersions=@([regex]::Matches($update,$versionPattern)|ForEach-Object{$_.Value}|Sort-Object -Unique)
$releaseVersions=@([regex]::Matches($release,$versionPattern)|ForEach-Object{$_.Value}|Sort-Object -Unique)
$allowed=@($baseline,$current|Sort-Object -Unique)
foreach($entry in @([pscustomobject]@{Name='Update compatibility';Versions=$updateVersions},[pscustomobject]@{Name='Release gate';Versions=$releaseVersions})){
    $unexpected=@($entry.Versions|Where-Object{$allowed -notcontains $_})
    if($unexpected.Count){Fail($entry.Name+' contains stale/non-transition Manager version(s): '+([string]::Join(', ',$unexpected))+'; allowed='+([string]::Join(', ',$allowed)))}
}

Write-Host ('Manager release instructions identity: PASS. '+$baseline+' -> '+$current) -ForegroundColor Green
