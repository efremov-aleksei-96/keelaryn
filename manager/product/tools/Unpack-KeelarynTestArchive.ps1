[CmdletBinding()]
param(
    [string]$ZipPath,
    [string]$TestsRoot,
    [switch]$Replace,
    [switch]$NoAutoRun,
    [switch]$PlanOnly,
    [switch]$NonInteractive,
    [switch]$SelfTest
)

$ErrorActionPreference='Stop'

function Fail([string]$Message){throw $Message}

function Write-ToolLine {
    param(
        [AllowNull()][object]$Object='',
        [System.ConsoleColor]$ForegroundColor=[System.ConsoleColor]::Gray
    )
    $text=if($null-eq$Object){''}else{[string]$Object}
    try{
        $restore=$false
        $old=[System.ConsoleColor]::Gray
        try{
            if(-not[Console]::IsOutputRedirected){
                $old=[Console]::ForegroundColor
                [Console]::ForegroundColor=$ForegroundColor
                $restore=$true
            }
        }catch{}
        [Console]::WriteLine($text)
        if($restore){try{[Console]::ForegroundColor=$old}catch{}}
    }catch{
        Microsoft.PowerShell.Utility\Write-Host $text
    }
}

function Write-ToolHost {
    param(
        [Parameter(Position=0)][AllowNull()][object]$Object='',
        [System.ConsoleColor]$ForegroundColor=[System.ConsoleColor]::Gray
    )
    Write-ToolLine $Object -ForegroundColor $ForegroundColor
}

function Read-ToolInput([string]$Prompt){
    try{
        [Console]::Write($Prompt+': ')
        $line=[Console]::ReadLine()
        if($null-eq$line){return ''}
        return [string]$line
    }catch{
        return [string](Microsoft.PowerShell.Utility\Read-Host $Prompt)
    }
}


function Test-ReparsePoint([string]$Path){
    if(-not(Test-Path -LiteralPath $Path)){return $false}
    $item=Get-Item -LiteralPath $Path -Force
    return (($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0)
}

function Assert-SafeSegment([string]$Segment){
    if([string]::IsNullOrWhiteSpace($Segment)){Fail 'ZIP entry contains an empty path segment.'}
    if($Segment-eq'.'-or$Segment-eq'..'){Fail('Unsafe ZIP path segment: '+$Segment)}
    if($Segment.EndsWith(' ')-or$Segment.EndsWith('.')){Fail('ZIP path segment has a trailing dot/space: '+$Segment)}
    if($Segment.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars())-ge0){Fail('ZIP path segment contains invalid Windows filename characters: '+$Segment)}
    $base=[System.IO.Path]::GetFileNameWithoutExtension($Segment)
    if($base-match'(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$'){Fail('ZIP path uses a reserved Windows device name: '+$Segment)}
}

function Normalize-EntryName([string]$Name){
    if($null-eq$Name){Fail 'ZIP entry name is null.'}
    $n=$Name.Replace('\','/')
    if($n.StartsWith('/')-or$n.StartsWith('\')-or$n.Contains(':')){Fail('Unsafe absolute/drive ZIP path: '+$Name)}
    $trimmed=$n.TrimEnd('/')
    if([string]::IsNullOrEmpty($trimmed)){return ''}
    foreach($segment in $trimmed.Split('/')){Assert-SafeSegment $segment}
    return $trimmed
}

function Test-ZipSymlinkLike($Entry){
    $signed=[int32]$Entry.ExternalAttributes
    $bytes=[BitConverter]::GetBytes($signed)
    $attrs=[BitConverter]::ToUInt32($bytes,0)
    $mode=(($attrs-shr16)-band0xF000)
    return ($mode-eq0xA000)
}

function Resolve-ArchiveSpec([string]$InputPath){
    $leaf=[System.IO.Path]::GetFileName($InputPath)
    $stem=[System.IO.Path]::GetFileNameWithoutExtension($InputPath)
    $managerMatch=[regex]::Match($stem,'^(?i:manager)-(\d+\.\d+\.\d+)$')
    if($managerMatch.Success){
        return [pscustomobject]@{Kind='manager';Version=$managerMatch.Groups[1].Value;Folder=('manager-'+$managerMatch.Groups[1].Value)}
    }
    $profileMatch=[regex]::Match($stem,'^([A-Za-z0-9][A-Za-z0-9_-]{0,95})-(\d+\.\d+\.\d+)$')
    if($profileMatch.Success-and$profileMatch.Groups[1].Value-match'(?i)(profile|profiler)'){
        return [pscustomobject]@{Kind='profile';Version=$profileMatch.Groups[2].Value;Folder=$stem}
    }
    Fail('Unsupported Keelaryn test archive name: '+$leaf+'. Expected manager-<version>.zip or a versioned *profile*/*profiler* ZIP.')
}

function Get-DefaultTestsRoot{
    $product=Split-Path $PSScriptRoot -Parent
    $manager=[System.IO.Path]::GetFullPath((Split-Path $product -Parent)).TrimEnd('\')
    $layout=[System.IO.Path]::GetFullPath((Split-Path $manager -Parent)).TrimEnd('\')
    return Join-Path $layout 'tests'
}

function Select-Zip{
    try{
        Add-Type -AssemblyName System.Windows.Forms
        $dialog=New-Object System.Windows.Forms.OpenFileDialog
        try{
            $dialog.Title='Select Keelaryn test archive'
            $dialog.Filter='Keelaryn test archives (*.zip)|*.zip'
            $dialog.Multiselect=$false
            $downloads=Join-Path $env:USERPROFILE 'Downloads'
            if(Test-Path -LiteralPath $downloads -PathType Container){$dialog.InitialDirectory=$downloads}
            $result=$dialog.ShowDialog()
            if($result-eq[System.Windows.Forms.DialogResult]::OK){return $dialog.FileName}
            return $null
        }finally{$dialog.Dispose()}
    }catch{}
    $manual=Read-ToolInput 'GUI unavailable; enter full test archive path or leave blank to cancel'
    if([string]::IsNullOrWhiteSpace($manual)){return $null}
    return $manual.Trim('"')
}

$script:ArchiveToolSelfTestReason=''
function Test-ArchiveToolSelf{
    try{
        $a=Resolve-ArchiveSpec 'manager-4.6.4.zip'
        if($a.Kind-ne'manager'-or$a.Version-ne'4.6.4'-or$a.Folder-ne'manager-4.6.4'){
            $script:ArchiveToolSelfTestReason='manager archive-name contract failed.'
            return $false
        }
        $b=Resolve-ArchiveSpec 'ai-context-profile-4.6.4.zip'
        if($b.Kind-ne'profile'-or$b.Folder-ne'ai-context-profile-4.6.4'){
            $script:ArchiveToolSelfTestReason='profile archive-name contract failed.'
            return $false
        }
        $blocked=$false
        try{$null=Normalize-EntryName '../escape.txt'}catch{$blocked=$true}
        if(-not$blocked){
            $script:ArchiveToolSelfTestReason='path traversal was not rejected.'
            return $false
        }
        $blocked=$false
        try{$null=Normalize-EntryName 'AUX.txt'}catch{$blocked=$true}
        if(-not$blocked){
            $script:ArchiveToolSelfTestReason='reserved Windows device name was not rejected.'
            return $false
        }
        $script:ArchiveToolSelfTestReason=''
        return $true
    }
    catch{
        $script:ArchiveToolSelfTestReason=$_.Exception.Message
        return $false
    }
}

if($SelfTest){
    if(Test-ArchiveToolSelf){Write-ToolHost 'Keelaryn test-archive tool self-test PASS.' -ForegroundColor Green;exit 0}
    Write-ToolHost ('Keelaryn test-archive tool self-test FAIL: '+[string]$script:ArchiveToolSelfTestReason) -ForegroundColor Red
    exit 1
}

if(-not$TestsRoot){$TestsRoot=Get-DefaultTestsRoot}
$TestsRoot=[System.IO.Path]::GetFullPath($TestsRoot).TrimEnd('\')
if((Split-Path $TestsRoot -Leaf)-ine'tests'){Fail('TestsRoot must identify the canonical tests directory: '+$TestsRoot)}
if(-not(Test-Path -LiteralPath $TestsRoot)){New-Item -ItemType Directory -Force -Path $TestsRoot|Out-Null}
$item=Get-Item -LiteralPath $TestsRoot -Force
if(-not$item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Unsafe tests root: '+$TestsRoot)}
$WorkRoot=Join-Path $TestsRoot 'work'
if(-not(Test-Path -LiteralPath $WorkRoot)){New-Item -ItemType Directory -Force -Path $WorkRoot|Out-Null}
$workItem=Get-Item -LiteralPath $WorkRoot -Force
if(-not$workItem.PSIsContainer-or($workItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Unsafe tests work root: '+$WorkRoot)}

if(-not$ZipPath){$ZipPath=Select-Zip;if(-not$ZipPath){Write-ToolHost 'No archive selected.';exit 2}}
$ZipPath=[System.IO.Path]::GetFullPath($ZipPath)
if(-not(Test-Path -LiteralPath $ZipPath -PathType Leaf)){Fail('Archive not found: '+$ZipPath)}
if(Test-ReparsePoint $ZipPath){Fail 'Archive must not be a reparse point.'}
$spec=Resolve-ArchiveSpec $ZipPath
$Destination=Join-Path $WorkRoot $spec.Folder
if($PlanOnly){
    $plan=[ordered]@{kind=[string]$spec.Kind;version=[string]$spec.Version;folder=[string]$spec.Folder;destination=[string]$Destination}
    Write-ToolHost ('KEELARYN_PLAN_JSON:'+($plan|ConvertTo-Json -Compress))
    exit 0
}
$Staging=Join-Path $WorkRoot ('._unpack_'+$spec.Folder+'_'+[guid]::NewGuid().ToString('N'))
$Backup=$null

Unblock-File -LiteralPath $ZipPath -ErrorAction Stop
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$archive=[System.IO.Compression.ZipFile]::OpenRead($ZipPath)
try{
    $entries=@($archive.Entries)
    if($entries.Count-lt1){Fail 'Archive is empty.'}
    if($entries.Count-gt5000){Fail('Archive contains too many entries: '+$entries.Count)}
    [int64]$total=0
    $rows=New-Object System.Collections.Generic.List[object]
    $caseMap=New-Object 'System.Collections.Generic.Dictionary[string,string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach($entry in $entries){
        if(Test-ZipSymlinkLike $entry){Fail('ZIP contains a symlink-like entry: '+$entry.FullName)}
        $name=Normalize-EntryName $entry.FullName
        if([string]::IsNullOrEmpty($name)){continue}
        $isDir=$entry.FullName.Replace('\','/').EndsWith('/')
        if(-not$isDir){
            if($entry.Length-gt256MB){Fail('ZIP entry is too large: '+$entry.FullName)}
            $total+=[int64]$entry.Length
            if($total-gt1GB){Fail 'Archive uncompressed size exceeds the 1 GiB safety limit.'}
        }
        $existing=$null
        if($caseMap.TryGetValue($name,[ref]$existing)){Fail('ZIP contains a case-insensitive path collision: '+$existing+' / '+$name)}
        $caseMap.Add($name,$name)
        $rows.Add([pscustomobject]@{Entry=$entry;Name=$name;IsDirectory=$isDir})
    }

    $fileRows=@($rows|Where-Object{-not$_.IsDirectory})
    if($fileRows.Count-lt1){Fail 'Archive contains no files.'}
    $prefix=$spec.Folder+'/'
    $allUnder=$true
    foreach($row in $fileRows){
        if(-not$row.Name.StartsWith($prefix,[System.StringComparison]::OrdinalIgnoreCase)){$allUnder=$false;break}
    }

    New-Item -ItemType Directory -Path $Staging -Force|Out-Null
    foreach($row in $rows){
        $relative=$row.Name
        if($allUnder){
            if($relative.Length-le$prefix.Length){continue}
            $relative=$relative.Substring($prefix.Length)
        }
        if([string]::IsNullOrEmpty($relative)){continue}
        $target=[System.IO.Path]::GetFullPath((Join-Path $Staging $relative.Replace('/','\')))
        $stagePrefix=$Staging.TrimEnd('\')+'\'
        if(-not$target.StartsWith($stagePrefix,[System.StringComparison]::OrdinalIgnoreCase)){Fail('ZIP entry escapes staging directory: '+$row.Name)}
        if($row.IsDirectory){New-Item -ItemType Directory -Path $target -Force|Out-Null;continue}
        $parent=Split-Path -Parent $target
        if($parent){New-Item -ItemType Directory -Path $parent -Force|Out-Null}
        $input=$row.Entry.Open()
        try{
            $output=New-Object System.IO.FileStream($target,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
            try{$input.CopyTo($output)}finally{$output.Dispose()}
        }finally{$input.Dispose()}
    }
}finally{$archive.Dispose()}

try{
    Get-ChildItem -LiteralPath $Staging -File -Recurse -Force|ForEach-Object{Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue}
    $launcher=$null
    if($spec.Kind-eq'manager'){
        $script=Join-Path $Staging 'Keelaryn__Manager.ps1'
        $versionFile=Join-Path $Staging '_manager_version.txt'
        if(-not(Test-Path -LiteralPath $script -PathType Leaf)){Fail 'Extracted Manager gate does not contain Keelaryn__Manager.ps1.'}
        if(-not(Test-Path -LiteralPath $versionFile -PathType Leaf)){Fail 'Extracted Manager gate does not contain _manager_version.txt.'}
        $inside=(Get-Content -LiteralPath $versionFile -Raw -Encoding UTF8).Trim()
        if($inside-ne$spec.Version){Fail('Archive filename/version mismatch: filename='+$spec.Version+'; payload='+$inside)}
        $launchers=@(Get-ChildItem -LiteralPath $Staging -Filter 'RUN_*_FULL_GATE.cmd' -File)
        if($launchers.Count-ne1){Fail 'Extracted Manager gate must contain exactly one RUN_*_FULL_GATE.cmd launcher.'}
        $launcher=$launchers[0].FullName
    }else{
        $launchers=@(Get-ChildItem -LiteralPath $Staging -Filter 'RUN_*.cmd' -File)
        if($launchers.Count-ne1){Fail 'Extracted profiler archive must contain exactly one RUN_*.cmd launcher.'}
        if($launchers[0].Name-notmatch[regex]::Escape($spec.Version.Replace('.',''))){
            Fail('Profiler launcher/version mismatch: archive='+$spec.Version+'; launcher='+$launchers[0].Name)
        }
        $launcher=$launchers[0].FullName
    }

    if(Test-Path -LiteralPath $Destination){
        $destItem=Get-Item -LiteralPath $Destination -Force
        if(-not$destItem.PSIsContainer-or($destItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Existing destination is unsafe: '+$Destination)}
        if(-not$Replace){
            if($NonInteractive){Write-ToolHost 'Existing work folder requires explicit replacement.';exit 3}
            $answer=Read-ToolInput ('Destination already exists: '+$Destination+'. Replace disposable work folder? [y/N]')
            if($answer-notmatch'^(?i)y(es)?$'){Write-ToolHost 'Existing work folder left untouched.';exit 3}
        }
        $Backup=Join-Path $WorkRoot ('._old_'+$spec.Folder+'_'+[guid]::NewGuid().ToString('N'))
        Move-Item -LiteralPath $Destination -Destination $Backup
    }

    try{
        Move-Item -LiteralPath $Staging -Destination $Destination
        $Staging=$null
    }catch{
        if($Backup-and(Test-Path -LiteralPath $Backup)-and -not(Test-Path -LiteralPath $Destination)){
            Move-Item -LiteralPath $Backup -Destination $Destination
            $Backup=$null
        }
        throw
    }
    if($Backup-and(Test-Path -LiteralPath $Backup)){Remove-Item -LiteralPath $Backup -Recurse -Force;$Backup=$null}

    $finalLauncher=Join-Path $Destination ([System.IO.Path]::GetFileName($launcher))
    if(-not(Test-Path -LiteralPath $finalLauncher -PathType Leaf)){Fail('Committed launcher is missing: '+$finalLauncher)}
    Write-ToolHost ''
    Write-ToolHost 'Keelaryn test archive unpacked successfully.' -ForegroundColor Green
    Write-ToolHost ('Destination: '+$Destination)
    Write-ToolHost ('Launcher: '+$finalLauncher)
    if(-not$NoAutoRun){
        Start-Process -FilePath $finalLauncher -WorkingDirectory $Destination|Out-Null
        Write-ToolHost 'Validated launcher started automatically.' -ForegroundColor Cyan
    }
}finally{
    if($Staging-and(Test-Path -LiteralPath $Staging)){Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue}
    if($Backup-and(Test-Path -LiteralPath $Backup)-and -not(Test-Path -LiteralPath $Destination)){
        Move-Item -LiteralPath $Backup -Destination $Destination -ErrorAction SilentlyContinue
    }
}
