[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [switch]$Write,
    [switch]$Check
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Get-FileSha256([string]$Path){
    $stream=[System.IO.File]::Open($Path,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::Read)
    $sha=[System.Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}
    finally{$sha.Dispose();$stream.Dispose()}
}
function Get-TextSha256([string]$Text){
    $sha=[System.Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text))).Replace('-','').ToLowerInvariant()}
    finally{$sha.Dispose()}
}
function Write-Utf8NoBom([string]$Path,[string]$Text){[System.IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)}
function ConvertTo-StableJson($Value,[int]$Depth=30){return (($Value|ConvertTo-Json -Depth $Depth).Replace("`r`n","`n")+"`n")}
function Get-RelativePath([string]$Root,[string]$Path){
    $prefix=[System.IO.Path]::GetFullPath($Root).TrimEnd('\')+'\'
    $full=[System.IO.Path]::GetFullPath($Path)
    if(-not$full.StartsWith($prefix,[System.StringComparison]::OrdinalIgnoreCase)){Fail('Path escapes manifest root: '+$Path)}
    return $full.Substring($prefix.Length).Replace('\','/')
}
function Get-SafeFile([string]$Path){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){Fail('Required manifest source file is missing: '+$Path)}
    $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Manifest source file must not be a reparse point: '+$Path)}
    return $item
}
function Get-FileRow([string]$Root,[string]$Path){
    $item=Get-SafeFile $Path
    return [ordered]@{path=(Get-RelativePath $Root $item.FullName);size_bytes=[long]$item.Length;sha256=(Get-FileSha256 $item.FullName)}
}
function Get-OrdinalSortedUnique([object[]]$Values){
    $list=New-Object 'System.Collections.Generic.List[string]'
    foreach($raw in @($Values)){if($null-ne$raw){[void]$list.Add([string]$raw)}}
    $list.Sort([System.StringComparer]::Ordinal)
    $out=New-Object System.Collections.ArrayList
    $last=$null
    foreach($value in $list){
        if($null-eq$last-or-not[string]::Equals([string]$last,$value,[System.StringComparison]::Ordinal)){[void]$out.Add($value);$last=$value}
    }
    return @($out)
}
function Get-ManagedContentSha256([string]$ManagerRoot,$Install){
    $paths=@(Get-OrdinalSortedUnique @($Install.managed_files|ForEach-Object{([string]$_).Replace('\','/')}))
    if($paths.Count-ne@($Install.managed_files).Count){Fail('INSTALLATION managed_files contains duplicates.')}
    $rows=New-Object System.Collections.ArrayList
    foreach($rel in $paths){
        $file=Join-Path $ManagerRoot $rel.Replace('/','\')
        [void](Get-SafeFile $file)
        [void]$rows.Add($rel+"`0"+(Get-FileSha256 $file))
    }
    return Get-TextSha256 ([string]::Join("`n",@($rows)))
}
function Get-CanonicalObjectJson($Value){return ConvertTo-StableJson $Value 40}

if($Write-and$Check){Fail 'Choose either -Write or -Check, not both.'}
$managerRoot=Join-Path $RepositoryRoot 'manager'
$frameworkRoot=Join-Path $RepositoryRoot 'tests\framework\manager-gate'
$installPath=Join-Path $managerRoot 'product\install\INSTALLATION.json'
$revisionPath=Join-Path $frameworkRoot 'FRAMEWORK_REVISION.txt'
foreach($dir in @($managerRoot,$frameworkRoot)){if(-not(Test-Path -LiteralPath $dir -PathType Container)){Fail('Missing manifest source directory: '+$dir)}}
[void](Get-SafeFile $installPath);[void](Get-SafeFile $revisionPath)

$install=(Get-Content -LiteralPath $installPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$install.schema-ne'keelaryn.manager.installation.v2'){Fail('Unsupported INSTALLATION schema: '+[string]$install.schema)}
$version=([string]$install.manager_version).Trim()
if($version-notmatch'^\d+\.\d+\.\d+$'){Fail('Invalid Manager version: '+$version)}
$managedPaths=@(Get-OrdinalSortedUnique @($install.managed_files|ForEach-Object{([string]$_).Replace('\','/')}))
if($managedPaths.Count-lt1-or$managedPaths.Count-ne@($install.managed_files).Count){Fail 'INSTALLATION managed_files is empty or contains duplicates.'}

$actualManagerFiles=@(Get-ChildItem -LiteralPath $managerRoot -File -Recurse -Force|ForEach-Object{Get-RelativePath $managerRoot $_.FullName}|Sort-Object)
if($actualManagerFiles.Count-ne$managedPaths.Count){Fail('manager/ source set count mismatch: install='+$managedPaths.Count+' actual='+$actualManagerFiles.Count)}
for($i=0;$i-lt$managedPaths.Count;$i++){if([string]$managedPaths[$i]-cne[string]$actualManagerFiles[$i]){Fail('manager/ source set mismatch: expected='+[string]$managedPaths[$i]+' actual='+[string]$actualManagerFiles[$i])}}

$managerRows=New-Object System.Collections.ArrayList
foreach($rel in $managedPaths){[void]$managerRows.Add((Get-FileRow $managerRoot (Join-Path $managerRoot $rel.Replace('/','\'))))}

$frameworkRevision=0
if(-not[int]::TryParse((Get-Content -LiteralPath $revisionPath -Raw -Encoding UTF8).Trim(),[ref]$frameworkRevision)-or$frameworkRevision-lt1){Fail 'Invalid Gate Framework revision.'}
$frameworkFiles=@(Get-ChildItem -LiteralPath $frameworkRoot -File -Recurse -Force|Sort-Object FullName)
if($frameworkFiles.Count-lt1){Fail 'Gate Framework source set is empty.'}
$frameworkRows=New-Object System.Collections.ArrayList
foreach($file in $frameworkFiles){[void]$frameworkRows.Add((Get-FileRow $frameworkRoot $file.FullName))}

$manifest=[ordered]@{
    schema='keelaryn.public-file-manifest.v2'
    scope='authoritative_source_sets'
    manager=[ordered]@{
        version=$version
        file_count=$managedPaths.Count
        installation_sha256=(Get-FileSha256 $installPath)
        gate_managed_content_sha256=(Get-ManagedContentSha256 $managerRoot $install)
        files=@($managerRows)
    }
    gate_framework=[ordered]@{
        framework_version='2.0'
        revision=$frameworkRevision
        file_count=$frameworkFiles.Count
        files=@($frameworkRows)
    }
    note='Public scaffolding is validated structurally; this manifest cryptographically binds the authoritative Manager and frozen gate-framework source sets.'
}

$generated=Get-CanonicalObjectJson $manifest
$manifestPath=Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json'
if($Write){
    Write-Utf8NoBom $manifestPath $generated
    Write-Host('PUBLIC_FILE_MANIFEST generated: '+$manifestPath) -ForegroundColor Green
    Write-Host('Manager '+$version+'; managed='+$managedPaths.Count+'; framework=r'+$frameworkRevision) -ForegroundColor Green
    exit 0
}
if($Check){
    [void](Get-SafeFile $manifestPath)
    $existing=(Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8)|ConvertFrom-Json
    $existingCanonical=Get-CanonicalObjectJson $existing
    if($existingCanonical-cne$generated){Fail 'PUBLIC_FILE_MANIFEST is stale or non-canonical. Run tools\Build-PublicFileManifest.ps1 -Write and review the diff.'}
    Write-Host('PUBLIC_FILE_MANIFEST reproducibility: PASS. Manager '+$version+'; managed='+$managedPaths.Count+'; framework=r'+$frameworkRevision) -ForegroundColor Green
    exit 0
}
[Console]::Out.Write($generated)