[CmdletBinding()]
param()

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$frameworkRoot=$PSScriptRoot
$safetyPath=Join-Path $frameworkRoot 'SourceZipSafety.ps1'
$builderPath=Join-Path $frameworkRoot 'Build-ManagerGate.ps1'
if(-not(Test-Path -LiteralPath $safetyPath -PathType Leaf)){throw 'SourceZipSafety.ps1 is missing.'}
if(-not(Test-Path -LiteralPath $builderPath -PathType Leaf)){throw 'Build-ManagerGate.ps1 is missing.'}
. $safetyPath

function Write-EntryBytes($Archive,[string]$Name,[byte[]]$Bytes,[string]$Compression='Optimal',[int]$ExternalAttributes=0){
    $level=[System.IO.Compression.CompressionLevel]::$Compression
    $entry=$Archive.CreateEntry($Name,$level)
    $entry.ExternalAttributes=$ExternalAttributes
    if($null-ne$Bytes-and$Bytes.Length-gt0){
        $stream=$entry.Open()
        try{$stream.Write($Bytes,0,$Bytes.Length)}finally{$stream.Dispose()}
    }
}
function New-TestZip([string]$Path,[object[]]$Entries){
    $parent=Split-Path -Parent $Path;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    $stream=[System.IO.File]::Open($Path,[System.IO.FileMode]::Create,[System.IO.FileAccess]::ReadWrite,[System.IO.FileShare]::None)
    $archive=New-Object System.IO.Compression.ZipArchive($stream,[System.IO.Compression.ZipArchiveMode]::Create,$false)
    try{
        foreach($row in @($Entries)){
            $bytes=[byte[]]@()
            if($null-ne$row.Bytes){$bytes=[byte[]]$row.Bytes}
            elseif($null-ne$row.Text){$bytes=(New-Object System.Text.UTF8Encoding($false)).GetBytes([string]$row.Text)}
            $compression='Optimal';if($null-ne$row.Compression){$compression=[string]$row.Compression}
            $attrs=0;if($null-ne$row.ExternalAttributes){$attrs=[int]$row.ExternalAttributes}
            Write-EntryBytes $archive ([string]$row.Name) $bytes $compression $attrs
        }
    }finally{$archive.Dispose();$stream.Dispose()}
}
function Get-ValidEntries{
    $manifest=[ordered]@{
        schema='keelaryn.manager.installation.v2'
        manager_version='9.9.9'
        managed_files=@('product/install/INSTALLATION.json','product/runtime/Keelaryn__Manager.ps1')
    }
    $json=(($manifest|ConvertTo-Json -Depth 6).Replace("`r`n","`n"))+"`n"
    return @(
        [pscustomobject]@{Name='keelaryn/manager/product/install/INSTALLATION.json';Text=$json;Bytes=$null;Compression='Optimal';ExternalAttributes=0},
        [pscustomobject]@{Name='keelaryn/manager/product/runtime/Keelaryn__Manager.ps1';Text="param()`r`nexit 0`r`n";Bytes=$null;Compression='Optimal';ExternalAttributes=0}
    )
}
function Clone-Entries([object[]]$Entries){return @($Entries|ForEach-Object{[pscustomobject]@{Name=[string]$_.Name;Text=$_.Text;Bytes=$_.Bytes;Compression=$_.Compression;ExternalAttributes=$_.ExternalAttributes}})}
function Assert-Rejected([string]$Name,[object[]]$Entries,$Limits=$null){
    $zip=Join-Path $script:tempRoot ($Name+'.zip')
    $dest=Join-Path $script:tempRoot ($Name+'-out')
    New-TestZip $zip $Entries
    $rejected=$false
    try{[void](Expand-KeelarynSourceZipSafely -ZipPath $zip -Destination $dest -RequiredRoot 'keelaryn' -Limits $Limits)}
    catch{$rejected=$true;Write-Host ('  PASS reject '+$Name+': '+$_.Exception.Message)}
    if(-not$rejected){throw('Unsafe SOURCE ZIP was accepted: '+$Name)}
}

$revision=(Get-Content -LiteralPath (Join-Path $frameworkRoot 'FRAMEWORK_REVISION.txt') -Raw -Encoding UTF8).Trim()
if($revision-cne'13'){throw('Framework qualification expected revision 13, got '+$revision)}

foreach($ps in @(Get-ChildItem -LiteralPath $frameworkRoot -File -Recurse -Filter '*.ps1')){
    $tokens=$null;$errors=$null
    [void][System.Management.Automation.Language.Parser]::ParseFile($ps.FullName,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne0){throw('PowerShell parser rejected framework file '+$ps.FullName+': '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
}
$builderText=[System.IO.File]::ReadAllText($builderPath,[System.Text.Encoding]::UTF8)
if($builderText.IndexOf('Expand-Archive',[System.StringComparison]::OrdinalIgnoreCase)-ge0){throw 'Framework r13 builder must not use Expand-Archive for SourceZip.'}
foreach($token in @('SourceZipSafety.ps1','Expand-KeelarynSourceZipSafely')){if(-not$builderText.Contains($token)){throw('Framework r13 builder safety binding missing token: '+$token)}}

$script:tempRoot=Join-Path ([System.IO.Path]::GetTempPath()) ('keelaryn_framework_r13_selftest_'+[guid]::NewGuid().ToString('N'))
try{
    New-Item -ItemType Directory -Force -Path $script:tempRoot|Out-Null
    $valid=Get-ValidEntries

    Write-Host '[1/11] Valid SourceZip extraction...'
    $validZip=Join-Path $script:tempRoot 'valid-source.zip';New-TestZip $validZip $valid
    $validOut=Join-Path $script:tempRoot 'valid-out'
    $managerRoot=Expand-KeelarynSourceZipSafely -ZipPath $validZip -Destination $validOut -RequiredRoot 'keelaryn'
    if(-not(Test-Path -LiteralPath (Join-Path $managerRoot 'product\install\INSTALLATION.json') -PathType Leaf)){throw 'Valid SourceZip extraction lost INSTALLATION.json.'}

    Write-Host '[2/11] Builder SourceZip integration...'
    $gateOut=Join-Path $script:tempRoot 'manager-9.9.9.zip'
    & (Join-Path $PSHOME 'powershell.exe') -NoProfile -ExecutionPolicy Bypass -File $builderPath -SourceZip $validZip -BaselineVersion '9.9.8' -GateRevision 1 -OutputPath $gateOut
    if($LASTEXITCODE-ne0-or-not(Test-Path -LiteralPath $gateOut -PathType Leaf)){throw 'Builder SourceZip integration failed.'}

    Write-Host '[3/11] Zip Slip / dot-segment rejection...'
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/../escape.txt';Text='x';Bytes=$null;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'zip-slip' $rows
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/./dot.txt';Text='x';Bytes=$null;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'dot-segment' $rows

    Write-Host '[4/11] Windows reserved-name rejection...'
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/CON.txt';Text='x';Bytes=$null;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'reserved-name' $rows

    Write-Host '[5/11] Case-alias rejection...'
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/Case.txt';Text='a';Bytes=$null;Compression='Optimal';ExternalAttributes=0};$rows+=,[pscustomobject]@{Name='keelaryn/manager/case.txt';Text='b';Bytes=$null;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'case-alias' $rows

    Write-Host '[6/11] Unicode-normalization alias rejection...'
    $composed='caf'+[char]0x00E9+'.txt';$decomposed='cafe'+[char]0x0301+'.txt'
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name=('keelaryn/manager/'+$composed);Text='a';Bytes=$null;Compression='Optimal';ExternalAttributes=0};$rows+=,[pscustomobject]@{Name=('keelaryn/manager/'+$decomposed);Text='b';Bytes=$null;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'unicode-alias' $rows

    Write-Host '[7/11] Symlink metadata rejection...'
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/link';Text='target';Bytes=$null;Compression='Optimal';ExternalAttributes=-1577123840};Assert-Rejected 'symlink-metadata' $rows

    Write-Host '[8/11] Windows reparse metadata rejection...'
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/reparse';Text='x';Bytes=$null;Compression='Optimal';ExternalAttributes=1024};Assert-Rejected 'reparse-metadata' $rows

    Write-Host '[9/11] Compression-ratio rejection...'
    $bomb=New-Object byte[] (2MB);for($i=0;$i-lt$bomb.Length;$i++){$bomb[$i]=65}
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/ratio-bomb.bin';Text=$null;Bytes=$bomb;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'compression-ratio' $rows

    Write-Host '[10/11] Expanded-size limit rejection...'
    $limits=Get-KeelarynSourceZipLimits;$limits.MaxExpandedBytes=[long]1024;$limits.MaxEntryBytes=[long]1024
    $large=New-Object byte[] 2048
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/large.bin';Text=$null;Bytes=$large;Compression='NoCompression';ExternalAttributes=0};Assert-Rejected 'expanded-size' $rows $limits

    Write-Host '[11/11] Entry-count limit rejection...'
    $limits=Get-KeelarynSourceZipLimits;$limits.MaxEntries=2
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/third.txt';Text='x';Bytes=$null;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'entry-count' $rows $limits

    Write-Host 'FRAMEWORK r13 SELFTEST: PASS' -ForegroundColor Green
}finally{if(Test-Path -LiteralPath $script:tempRoot){Remove-Item -LiteralPath $script:tempRoot -Recurse -Force -ErrorAction SilentlyContinue}}
