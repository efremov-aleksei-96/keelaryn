[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message){throw $Message}
function Require-File([string]$Relative){
    $path=Join-Path $RepositoryRoot $Relative.Replace('/','\')
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Missing public presentation file: '+$Relative)}
    return [System.IO.Path]::GetFullPath($path)
}
function Read-Utf8([string]$Path){return [System.IO.File]::ReadAllText($Path,[System.Text.Encoding]::UTF8)}
function Require-Token([string]$Text,[string]$Token,[string]$Purpose){
    if($Text.IndexOf($Token,[System.StringComparison]::Ordinal)-lt0){Fail($Purpose+' missing token: '+$Token)}
}
function Assert-InsideRepository([string]$Path,[string]$Purpose){
    $full=[System.IO.Path]::GetFullPath($Path)
    $prefix=$RepositoryRoot+'\'
    if(-not($full.Equals($RepositoryRoot,[System.StringComparison]::OrdinalIgnoreCase))-and
       -not($full.StartsWith($prefix,[System.StringComparison]::OrdinalIgnoreCase))){
        Fail($Purpose+' escapes repository root: '+$Path)
    }
    return $full
}

$provenancePath=Require-File 'PUBLIC_PROVENANCE.json'
$manifestPath=Require-File 'PUBLIC_FILE_MANIFEST.json'
$provenance=(Get-Content -LiteralPath $provenancePath -Raw -Encoding UTF8)|ConvertFrom-Json
$manifest=(Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$provenance.schema-ne'keelaryn.public-repository-provenance.v2'){Fail('Unsupported PUBLIC_PROVENANCE schema: '+[string]$provenance.schema)}
if([string]$manifest.schema-ne'keelaryn.public-file-manifest.v2'){Fail('Unsupported PUBLIC_FILE_MANIFEST schema: '+[string]$manifest.schema)}
$managerVersion=([string]$provenance.source_manager_version).Trim()
$manifestVersion=([string]$manifest.manager.version).Trim()
if($managerVersion-notmatch'^\d+\.\d+\.\d+$'){Fail('Invalid provenance Manager version: '+$managerVersion)}
if($managerVersion-cne$manifestVersion){Fail('Presentation metadata Manager version mismatch: provenance='+$managerVersion+' manifest='+$manifestVersion)}
$frameworkRevision=[int]$provenance.gate_framework.revision
if($frameworkRevision-lt1-or$frameworkRevision-ne[int]$manifest.gate_framework.revision){Fail('Presentation metadata Gate Framework revision mismatch.')}

$presentationDocs=@(
    'README.md',
    'GETTING_STARTED.md',
    'PORTFOLIO.md',
    'docs/ARCHITECTURE_OVERVIEW.md',
    'docs/ENGINEERING_CASE_STUDY.md',
    'docs/SECURITY_MODEL.md',
    'docs/RELEASE_ENGINEERING.md',
    'docs/PUBLISHING_CHECKLIST.md'
)
$volatileFreeDocs=@(
    'README.md',
    'GETTING_STARTED.md',
    'PORTFOLIO.md',
    'docs/ARCHITECTURE_OVERVIEW.md',
    'docs/SECURITY_MODEL.md',
    'docs/RELEASE_ENGINEERING.md',
    'docs/PUBLISHING_CHECKLIST.md'
)

$textByDoc=@{}
foreach($relative in $presentationDocs){
    $path=Require-File $relative
    $text=Read-Utf8 $path
    if([string]::IsNullOrWhiteSpace($text)){Fail('Public presentation file is empty: '+$relative)}
    $textByDoc[$relative]=$text
}

$readme=[string]$textByDoc['README.md']
foreach($token in @(
    'Windows-first local automation and state-management platform',
    'PUBLIC_PROVENANCE.json',
    'PUBLIC_FILE_MANIFEST.json',
    'docs/ENGINEERING_CASE_STUDY.md',
    'docs/SECURITY_MODEL.md',
    'docs/RELEASE_ENGINEERING.md',
    'releases/latest',
    '```mermaid'
)){Require-Token $readme $token 'README portfolio landing page'}
if($readme-match'(?i)Keelaryn is a Windows-first local knowledge and project-management system'){Fail 'README regressed to knowledge-management-first positioning.'}

$forbidden=@(
    [pscustomobject]@{Name='semantic version';Pattern='(?<![0-9])\d+\.\d+\.\d+(?![0-9])'},
    [pscustomobject]@{Name='versioned Manager claim';Pattern='(?i)\bManager\s+\d+\.\d+(?:\.\d+)?\+?\b'},
    [pscustomobject]@{Name='numbered Gate Framework claim';Pattern='(?i)\b(?:Gate\s+)?Framework(?:\s+v\d+(?:\.\d+)?)?\s+(?:revision\s+|r)\d+\b'},
    [pscustomobject]@{Name='hard-coded managed-file count';Pattern='(?i)\b\d+\s+(?:Manager\s+)?managed[- ]files?\b'}
)
foreach($relative in $volatileFreeDocs){
    $text=[string]$textByDoc[$relative]
    foreach($rule in $forbidden){
        $match=[regex]::Match($text,[string]$rule.Pattern)
        if($match.Success){Fail('Volatile public presentation claim in '+$relative+' ('+[string]$rule.Name+'): '+$match.Value)}
    }
}

$localLinks=0
foreach($relative in $presentationDocs){
    $sourcePath=Require-File $relative
    $sourceDir=Split-Path -Parent $sourcePath
    $text=[string]$textByDoc[$relative]
    $matches=[regex]::Matches($text,'!?\[[^\]]*\]\(([^)]+)\)')
    foreach($match in $matches){
        $raw=([string]$match.Groups[1].Value).Trim()
        if(-not$raw){continue}
        if($raw.StartsWith('<')-and$raw.EndsWith('>')){$raw=$raw.Substring(1,$raw.Length-2).Trim()}
        if($raw-match'^(?i)(https?://|mailto:|#)'){continue}
        $target=$raw
        $hash=$target.IndexOf('#');if($hash-ge0){$target=$target.Substring(0,$hash)}
        $query=$target.IndexOf('?');if($query-ge0){$target=$target.Substring(0,$query)}
        $target=$target.Trim()
        if(-not$target){continue}
        try{$target=[System.Uri]::UnescapeDataString($target)}catch{Fail('Invalid escaped Markdown link in '+$relative+': '+$raw)}
        if([System.IO.Path]::IsPathRooted($target)){Fail('Public presentation local link must be repository-relative: '+$relative+' -> '+$raw)}
        $resolved=Assert-InsideRepository (Join-Path $sourceDir $target.Replace('/','\')) ('Markdown link from '+$relative)
        if(-not(Test-Path -LiteralPath $resolved)){Fail('Broken public presentation link: '+$relative+' -> '+$raw)}
        $localLinks++
    }
}

$portfolio=[string]$textByDoc['PORTFOLIO.md']
foreach($token in @('20 seconds','Engineering case study','What not to claim')){Require-Token $portfolio $token 'PORTFOLIO recruiter path'}
$caseStudy=[string]$textByDoc['docs/ENGINEERING_CASE_STUDY.md']
foreach($token in @('Transactional','rejected','67d9c2b1d96b27ba8291a61c33cd414a0afa73af','Remote qualification')){Require-Token $caseStudy $token 'Engineering case study evidence'}
$releaseDoc=[string]$textByDoc['docs/RELEASE_ENGINEERING.md']
foreach($token in @('SourceGate','Hosted disposable Full Gate','Production Full Gate','Immutable GitHub Release','PUBLIC_PROVENANCE.json')){Require-Token $releaseDoc $token 'Release engineering presentation'}
$securityDoc=[string]$textByDoc['docs/SECURITY_MODEL.md']
foreach($token in @('Trust boundaries','reparse','rollback','Non-goals')){Require-Token $securityDoc $token 'Security model presentation'}
$checklist=[string]$textByDoc['docs/PUBLISHING_CHECKLIST.md']
Require-Token $checklist 'Verify-PublicPresentation.ps1' 'Publishing checklist presentation validation'

Write-Host ('Public presentation validation: PASS. docs='+$presentationDocs.Count+'; manager='+$managerVersion+'; framework=r'+$frameworkRevision+'; local_links='+$localLinks) -ForegroundColor Green
