[CmdletBinding()]
param(
    [string]$ResultsPath,
    [string]$TestsRoot,
    [switch]$Apply,
    [string]$ReparseSubstitutionMapPath,
    [switch]$SelfTest
)

$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Fail([string]$Message){throw $Message}

function Get-Sha256([string]$Path){
    $stream=[System.IO.File]::OpenRead($Path)
    $sha=[System.Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}
    finally{$sha.Dispose();$stream.Dispose()}
}

function Get-StreamSha256([System.IO.Stream]$Stream){
    $sha=[System.Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($sha.ComputeHash($Stream)).Replace('-','').ToLowerInvariant()}
    finally{$sha.Dispose()}
}

function Get-TextSha256([string]$Text){
    $enc=New-Object System.Text.UTF8Encoding($false)
    $sha=[System.Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($sha.ComputeHash($enc.GetBytes($Text))).Replace('-','').ToLowerInvariant()}
    finally{$sha.Dispose()}
}

function Write-Utf8NoBom([string]$Path,[string]$Text){
    [System.IO.File]::WriteAllText($Path,$Text,(New-Object System.Text.UTF8Encoding($false)))
}

function Read-Json([string]$Path){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){Fail('JSON file missing: '+$Path)}
    return ([System.IO.File]::ReadAllText($Path,[System.Text.Encoding]::UTF8)|ConvertFrom-Json)
}

function Assert-SafeDirectory([string]$Path,[string]$Purpose){
    if(-not(Test-Path -LiteralPath $Path -PathType Container)){Fail($Purpose+' is missing: '+$Path)}
    $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if(-not$item.PSIsContainer){Fail($Purpose+' is not a directory: '+$Path)}
    if(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail($Purpose+' must not be a reparse point: '+$Path)}
}

function Ensure-SafeDirectory([string]$Path,[string]$Purpose){
    if(-not(Test-Path -LiteralPath $Path)){New-Item -ItemType Directory -Force -Path $Path|Out-Null}
    Assert-SafeDirectory $Path $Purpose
}

function Assert-StrictChild([string]$Parent,[string]$Child,[string]$Purpose){
    $parentFull=[System.IO.Path]::GetFullPath($Parent).TrimEnd('\')
    $childFull=[System.IO.Path]::GetFullPath($Child).TrimEnd('\')
    if(-not$childFull.StartsWith(($parentFull+'\'),[System.StringComparison]::OrdinalIgnoreCase)){Fail($Purpose+' must be below '+$parentFull+': '+$childFull)}
    return $childFull
}

function Test-SafeRelativeEvidencePath([string]$Value){
    if([string]::IsNullOrWhiteSpace($Value)-or[System.IO.Path]::IsPathRooted($Value)){return $false}
    $norm=$Value.Replace('\','/')
    if($norm.StartsWith('/')-or$norm.EndsWith('/')){return $false}
    $parts=@($norm.Split('/'))
    if($parts.Count-lt1){return $false}
    foreach($part in $parts){
        if([string]::IsNullOrWhiteSpace($part)-or$part-eq'.'-or$part-eq'..'-or$part.Contains(':')-or$part.Contains('*')-or$part.Contains('?')){return $false}
    }
    return $true
}

function Assert-NoReparseDirectoryChain([string]$Directory,[string]$Purpose){
    $full=[System.IO.Path]::GetFullPath($Directory).TrimEnd('\')
    $root=[System.IO.Path]::GetPathRoot($full)
    if([string]::IsNullOrWhiteSpace($root)){Fail($Purpose+' has no filesystem root: '+$full)}
    $current=$root
    $rootItem=Get-Item -LiteralPath $current -Force -ErrorAction Stop
    if(($rootItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail($Purpose+' filesystem root is a reparse point: '+$current)}
    $relative=$full.Substring($root.Length).Trim('\')
    if(-not[string]::IsNullOrWhiteSpace($relative)){
        foreach($part in @($relative.Split('\'))){
            $current=Join-Path $current $part
            $item=Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if(-not$item.PSIsContainer){Fail($Purpose+' path component is not a directory: '+$current)}
            if(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail($Purpose+' path chain contains a reparse-point directory: '+$current)}
        }
    }
    return $full
}

function Read-ReparseSubstitutionMap([string]$MapPath){
    if([string]::IsNullOrWhiteSpace($MapPath)){return $null}
    $full=[System.IO.Path]::GetFullPath($MapPath)
    $parent=Split-Path $full -Parent
    [void](Assert-NoReparseDirectoryChain $parent 'Reparse substitution map parent')
    if(-not(Test-Path -LiteralPath $full -PathType Leaf)){Fail('Reparse substitution map is missing: '+$full)}
    $mapItem=Get-Item -LiteralPath $full -Force -ErrorAction Stop
    if(($mapItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Reparse substitution map must not be a reparse point: '+$full)}
    if($mapItem.Length-gt4MB){Fail('Reparse substitution map exceeds 4 MiB safety limit: '+$full)}
    $map=Read-Json $full
    if([string]$map.schema-ne'keelaryn.reparse-substitution-map.v1'){Fail('Unsupported reparse substitution map schema.')}
    $protectedRaw=([string]$map.protected_root).Trim()
    if([string]::IsNullOrWhiteSpace($protectedRaw)-or-not[System.IO.Path]::IsPathRooted($protectedRaw)){Fail('Reparse substitution protected_root must be an absolute path.')}
    $protectedRoot=[System.IO.Path]::GetFullPath($protectedRaw).TrimEnd('\')
    [void](Assert-NoReparseDirectoryChain $protectedRoot 'Reparse substitution protected root')
    Assert-SafeDirectory $protectedRoot 'Reparse substitution protected root'
    $rows=@($map.entries)
    if($rows.Count-lt1-or$rows.Count-gt4096){Fail('Reparse substitution map must contain 1..4096 entries.')}
    $table=@{}
    foreach($row in $rows){
        $evidencePath=([string]$row.path).Replace('\','/').Trim()
        $protectedPath=([string]$row.protected_path).Replace('\','/').Trim()
        if(-not(Test-SafeRelativeEvidencePath $evidencePath)){Fail('Unsafe reparse substitution evidence path: '+$evidencePath)}
        if(-not(Test-SafeRelativeEvidencePath $protectedPath)){Fail('Unsafe reparse substitution protected path: '+$protectedPath)}
        if($table.ContainsKey($evidencePath)){Fail('Duplicate reparse substitution evidence path: '+$evidencePath)}
        [int64]$boundSize=[int64]$row.size
        $boundSha=([string]$row.sha256).Trim().ToLowerInvariant()
        if($boundSize-lt0-or$boundSha-notmatch'^[0-9a-f]{64}$'){Fail('Invalid size/SHA-256 binding for reparse substitution: '+$evidencePath)}
        $protectedFull=Join-Path $protectedRoot $protectedPath.Replace('/','\')
        $protectedFull=[System.IO.Path]::GetFullPath($protectedFull)
        if(-not$protectedFull.StartsWith(($protectedRoot+'\'),[System.StringComparison]::OrdinalIgnoreCase)){Fail('Protected substitution path escaped protected_root: '+$protectedPath)}
        [void](Assert-NoReparseDirectoryChain (Split-Path $protectedFull -Parent) ('Protected substitution parent for '+$evidencePath))
        if(-not(Test-Path -LiteralPath $protectedFull -PathType Leaf)){Fail('Protected substitution copy is missing: '+$protectedFull)}
        $protectedItem=Get-Item -LiteralPath $protectedFull -Force -ErrorAction Stop
        if($protectedItem.PSIsContainer-or($protectedItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Protected substitution copy must be a regular non-reparse file: '+$protectedFull)}
        if([int64]$protectedItem.Length-ne$boundSize){Fail('Protected substitution size binding mismatch: '+$evidencePath)}
        $actualSha=Get-Sha256 $protectedFull
        if($actualSha-cne$boundSha){Fail('Protected substitution SHA-256 binding mismatch: '+$evidencePath)}
        $table[$evidencePath]=[pscustomobject]@{
            EvidencePath=$evidencePath;ProtectedRelativePath=$protectedPath;ProtectedFullPath=$protectedFull;
            Size=$boundSize;Sha256=$boundSha;Used=$false
        }
    }
    return [pscustomobject]@{Schema='keelaryn.reparse-substitution-map.v1';MapPath=$full;MapSha256=(Get-Sha256 $full);ProtectedRoot=$protectedRoot;Entries=$table}
}

function Resolve-ReparseSubstitution($SubstitutionMap,[string]$RelativePath){
    if($null-eq$SubstitutionMap-or-not$SubstitutionMap.Entries.ContainsKey($RelativePath)){Fail('Qualification evidence contains an unmapped file reparse point: '+$RelativePath)}
    $entry=$SubstitutionMap.Entries[$RelativePath]
    $entry.Used=$true
    $item=Get-Item -LiteralPath ([string]$entry.ProtectedFullPath) -Force -ErrorAction Stop
    if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Protected substitution copy became unsafe: '+$RelativePath)}
    if([int64]$item.Length-ne[int64]$entry.Size-or(Get-Sha256 ([string]$entry.ProtectedFullPath))-cne[string]$entry.Sha256){Fail('Protected substitution copy changed after map validation: '+$RelativePath)}
    return [pscustomobject]@{
        ArchiveSourcePath=[string]$entry.ProtectedFullPath
        Size=[int64]$entry.Size
        Sha256=[string]$entry.Sha256
        Substitution=[ordered]@{
            schema='keelaryn.reparse-substitution.v1'
            map_sha256=[string]$SubstitutionMap.MapSha256
            protected_relative_path=[string]$entry.ProtectedRelativePath
            bound_size=[int64]$entry.Size
            bound_sha256=[string]$entry.Sha256
        }
    }
}

function Get-SafeEvidenceInventory([string]$Root,[string]$ExcludeLeaf,$SubstitutionMap){
    Assert-SafeDirectory $Root 'Qualification evidence root'
    $rootFull=[System.IO.Path]::GetFullPath($Root).TrimEnd('\')
    $files=New-Object System.Collections.ArrayList
    $dirs=New-Object System.Collections.ArrayList
    $stack=New-Object 'System.Collections.Generic.Stack[string]'
    $stack.Push($rootFull)
    while($stack.Count-gt0){
        $dir=$stack.Pop()
        foreach($item in @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction Stop)){
            if($item.Name-ceq$ExcludeLeaf-and$item.FullName.Substring($rootFull.Length).TrimStart('\').IndexOf('\')-lt0){continue}
            $isReparse=(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0)
            if($item.PSIsContainer){
                if($isReparse){Fail('Qualification evidence contains a reparse-point directory: '+$item.FullName)}
                [void]$dirs.Add($item.FullName);$stack.Push($item.FullName);continue
            }
            $rel=$item.FullName.Substring($rootFull.Length).TrimStart('\').Replace('\','/')
            if($isReparse){
                $resolved=Resolve-ReparseSubstitution $SubstitutionMap $rel
                [void]$files.Add([pscustomobject]@{
                    Path=$item.FullName;ArchiveSourcePath=[string]$resolved.ArchiveSourcePath;RelativePath=$rel;
                    Size=[int64]$resolved.Size;Sha256=[string]$resolved.Sha256;Attributes=[int]$item.Attributes;
                    CreationTimeUtc=$item.CreationTimeUtc.ToString('o');LastWriteTimeUtc=$item.LastWriteTimeUtc.ToString('o');
                    Substitution=$resolved.Substitution
                })
                continue
            }
            [void]$files.Add([pscustomobject]@{
                Path=$item.FullName;ArchiveSourcePath=$item.FullName;RelativePath=$rel;Size=[int64]$item.Length;
                Sha256=(Get-Sha256 $item.FullName);Attributes=[int]$item.Attributes;
                CreationTimeUtc=$item.CreationTimeUtc.ToString('o');LastWriteTimeUtc=$item.LastWriteTimeUtc.ToString('o');Substitution=$null
            })
        }
    }
    if($null-ne$SubstitutionMap){
        $unused=@($SubstitutionMap.Entries.Values|Where-Object{-not[bool]$_.Used})
        if($unused.Count-ne0){Fail('Reparse substitution map contains unused binding(s): '+[string]::Join(', ',@($unused|ForEach-Object{$_.EvidencePath})))}
    }
    return [pscustomobject]@{Files=@($files|Sort-Object RelativePath);Directories=@($dirs|Sort-Object Length -Descending)}
}

function Get-EvidenceDigest($Files){
    $rows=New-Object System.Collections.ArrayList
    foreach($f in @($Files)){[void]$rows.Add(([string]$f.RelativePath)+"`0"+([string]$f.Sha256))}
    return Get-TextSha256 ([string]::Join("`n",@($rows)))
}

function Get-ArchiveIdentity([string]$ResultsRoot,$Summary,[string]$EvidenceDigest){
    $version=([string]$Summary.manager_version).Trim()
    if($version-notmatch'^\d+\.\d+\.\d+$'){Fail('Gate summary manager_version is invalid: '+$version)}
    $gate=[int]$Summary.gate_revision;$framework=[int]$Summary.framework_revision
    if($gate-lt1-or$framework-lt1){Fail('Gate summary gate/framework revision is invalid.')}
    $leaf='manager-'+$version+'_g'+$gate+'_f'+$framework+'_'+$EvidenceDigest.Substring(0,12)
    return [pscustomobject]@{Version=$version;GateRevision=$gate;FrameworkRevision=$framework;Leaf=$leaf}
}

function Get-FrozenManifest([string]$ResultsRoot,$Summary,$Inventory,[string]$EvidenceDigest){
    $entries=New-Object System.Collections.ArrayList
    foreach($f in @($Inventory.Files)){
        [void]$entries.Add([ordered]@{
            path=[string]$f.RelativePath
            size=[int64]$f.Size
            sha256=[string]$f.Sha256
            attributes=[int]$f.Attributes
            creation_time_utc=[string]$f.CreationTimeUtc
            last_write_time_utc=[string]$f.LastWriteTimeUtc
            substitution=$f.Substitution
        })
    }
    return [ordered]@{
        schema='keelaryn.qualification-evidence-archive.v1'
        manager_version=[string]$Summary.manager_version
        baseline_version=[string]$Summary.baseline_version
        gate_revision=[int]$Summary.gate_revision
        framework_revision=[int]$Summary.framework_revision
        gate_status=[string]$Summary.status
        gate_completed=[string]$Summary.completed
        candidate_installation_sha256=[string]$Summary.candidate_installation_sha256
        candidate_managed_content_sha256=[string]$Summary.candidate_managed_content_sha256
        source_result_leaf=(Split-Path $ResultsRoot -Leaf)
        source_evidence_digest=$EvidenceDigest
        file_count=@($Inventory.Files).Count
        source_bytes=[int64](($Inventory.Files|Measure-Object -Property Size -Sum).Sum)
        reparse_policy='directories rejected; file reparse points rejected unless a future explicit protected-copy substitution contract is implemented'
        entries=@($entries)
    }
}

function New-VerifiedArchive([string]$ArchivePath,[string]$ManifestPath,$ManifestObject,$Inventory){
    $archiveDir=Split-Path $ArchivePath -Parent
    Ensure-SafeDirectory $archiveDir 'Qualification archive directory'
    $manifestJson=($ManifestObject|ConvertTo-Json -Depth 12).Replace("`r`n","`n")+"`n"
    $manifestSha=Get-TextSha256 $manifestJson
    $tmpArchive=$ArchivePath+'.tmp-'+[guid]::NewGuid().ToString('N')
    $tmpManifest=$ManifestPath+'.tmp-'+[guid]::NewGuid().ToString('N')
    try{
        $stream=[System.IO.File]::Open($tmpArchive,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::ReadWrite,[System.IO.FileShare]::None)
        $zip=New-Object System.IO.Compression.ZipArchive($stream,[System.IO.Compression.ZipArchiveMode]::Create,$false)
        try{
            foreach($f in @($Inventory.Files)){
                $entry=$zip.CreateEntry([string]$f.RelativePath,[System.IO.Compression.CompressionLevel]::Optimal)
                $entry.LastWriteTime=[DateTimeOffset]::Parse([string]$f.LastWriteTimeUtc)
                $archiveSource=[string]$f.ArchiveSourcePath
                $archiveItem=Get-Item -LiteralPath $archiveSource -Force -ErrorAction Stop
                if($archiveItem.PSIsContainer-or($archiveItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Archive source became a reparse point: '+[string]$f.RelativePath)}
                if([int64]$archiveItem.Length-ne[int64]$f.Size-or(Get-Sha256 $archiveSource)-cne[string]$f.Sha256){Fail('Archive source changed after inventory: '+[string]$f.RelativePath)}
                $source=[System.IO.File]::OpenRead($archiveSource)
                $dest=$entry.Open()
                try{$source.CopyTo($dest)}finally{$dest.Dispose();$source.Dispose()}
            }
            $manifestEntry=$zip.CreateEntry('__KEELARYN_ARCHIVE_MANIFEST.json',[System.IO.Compression.CompressionLevel]::Optimal)
            $writer=New-Object System.IO.StreamWriter($manifestEntry.Open(),(New-Object System.Text.UTF8Encoding($false)))
            try{$writer.Write($manifestJson)}finally{$writer.Dispose()}
        }finally{$zip.Dispose();$stream.Dispose()}
        Write-Utf8NoBom $tmpManifest $manifestJson

        $read=[System.IO.File]::OpenRead($tmpArchive)
        $verifyZip=New-Object System.IO.Compression.ZipArchive($read,[System.IO.Compression.ZipArchiveMode]::Read,$false)
        try{
            if($verifyZip.Entries.Count-ne(@($Inventory.Files).Count+1)){Fail('Qualification archive entry count mismatch.')}
            foreach($f in @($Inventory.Files)){
                $matches=@($verifyZip.Entries|Where-Object{$_.FullName-ceq[string]$f.RelativePath})
                if($matches.Count-ne1){Fail('Qualification archive missing/duplicate entry: '+[string]$f.RelativePath)}
                if([int64]$matches[0].Length-ne[int64]$f.Size){Fail('Qualification archive size mismatch: '+[string]$f.RelativePath)}
                $entryStream=$matches[0].Open()
                try{$hash=Get-StreamSha256 $entryStream}finally{$entryStream.Dispose()}
                if($hash-cne[string]$f.Sha256){Fail('Qualification archive SHA-256 mismatch: '+[string]$f.RelativePath)}
            }
            $manifestEntries=@($verifyZip.Entries|Where-Object{$_.FullName-ceq'__KEELARYN_ARCHIVE_MANIFEST.json'})
            if($manifestEntries.Count-ne1){Fail('Qualification archive manifest entry is missing or duplicated.')}
            $reader=New-Object System.IO.StreamReader($manifestEntries[0].Open(),[System.Text.Encoding]::UTF8)
            try{$inside=$reader.ReadToEnd()}finally{$reader.Dispose()}
            if((Get-TextSha256 $inside)-cne$manifestSha){Fail('Qualification archive embedded manifest hash mismatch.')}
        }finally{$verifyZip.Dispose();$read.Dispose()}

        if(Test-Path -LiteralPath $ArchivePath -PathType Leaf){
            if((Get-Sha256 $ArchivePath)-cne(Get-Sha256 $tmpArchive)){Fail('Existing qualification archive has different bytes: '+$ArchivePath)}
            Remove-Item -LiteralPath $tmpArchive -Force
        }else{Move-Item -LiteralPath $tmpArchive -Destination $ArchivePath -ErrorAction Stop}
        if(Test-Path -LiteralPath $ManifestPath -PathType Leaf){
            if((Get-Sha256 $ManifestPath)-cne(Get-Sha256 $tmpManifest)){Fail('Existing qualification manifest has different bytes: '+$ManifestPath)}
            Remove-Item -LiteralPath $tmpManifest -Force
        }else{Move-Item -LiteralPath $tmpManifest -Destination $ManifestPath -ErrorAction Stop}
        return [pscustomobject]@{ArchiveSha256=(Get-Sha256 $ArchivePath);ManifestSha256=(Get-Sha256 $ManifestPath);ManifestTextSha256=$manifestSha}
    }finally{
        foreach($p in @($tmpArchive,$tmpManifest)){if(Test-Path -LiteralPath $p){Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue}}
    }
}

function Test-PublishedArchive([string]$ArchivePath,[string]$ManifestPath,[string]$ExpectedArchiveSha,[string]$ExpectedManifestSha){
    if(-not(Test-Path -LiteralPath $ArchivePath -PathType Leaf) -or -not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)){return $false}
    if((Get-Sha256 $ArchivePath)-cne$ExpectedArchiveSha -or (Get-Sha256 $ManifestPath)-cne$ExpectedManifestSha){return $false}
    $manifest=Read-Json $ManifestPath
    $read=[System.IO.File]::OpenRead($ArchivePath)
    $zip=New-Object System.IO.Compression.ZipArchive($read,[System.IO.Compression.ZipArchiveMode]::Read,$false)
    try{
        foreach($row in @($manifest.entries)){
            $matches=@($zip.Entries|Where-Object{$_.FullName-ceq[string]$row.path})
            if($matches.Count-ne1 -or [int64]$matches[0].Length-ne[int64]$row.size){return $false}
            $s=$matches[0].Open();try{$h=Get-StreamSha256 $s}finally{$s.Dispose()}
            if($h-cne[string]$row.sha256){return $false}
        }
        return $true
    }finally{$zip.Dispose();$read.Dispose()}
}

function Remove-FileRetry([string]$Path){
    for($i=0;$i-lt5;$i++){
        try{if(Test-Path -LiteralPath $Path -PathType Leaf){Remove-Item -LiteralPath $Path -Force -ErrorAction Stop};return $true}
        catch{if($i-ge4){return $false};Start-Sleep -Milliseconds (150*($i+1))}
    }
    return $false
}

function Remove-EmptyDirectoryRetry([string]$Path){
    for($i=0;$i-lt5;$i++){
        try{if(Test-Path -LiteralPath $Path -PathType Container){Remove-Item -LiteralPath $Path -Force -ErrorAction Stop};return $true}
        catch{if($i-ge4){return $false};Start-Sleep -Milliseconds (150*($i+1))}
    }
    return $false
}

function Invoke-CleanupAfterArchive([string]$ResultsRoot,[string]$IndexPath){
    Assert-SafeDirectory $ResultsRoot 'Qualification evidence root'
    $rootFull=[System.IO.Path]::GetFullPath($ResultsRoot).TrimEnd('\')
    $indexFull=[System.IO.Path]::GetFullPath($IndexPath)
    $files=New-Object System.Collections.ArrayList
    $dirs=New-Object System.Collections.ArrayList
    $stack=New-Object 'System.Collections.Generic.Stack[string]'
    $stack.Push($rootFull)
    while($stack.Count-gt0){
        $dir=$stack.Pop()
        foreach($item in @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction Stop)){
            $full=[System.IO.Path]::GetFullPath($item.FullName)
            if($full-ceq$indexFull){continue}
            $isReparse=(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0)
            if($item.PSIsContainer){
                if($isReparse){Fail('Cleanup refused a reparse-point directory that appeared after archive verification: '+$item.FullName)}
                [void]$dirs.Add($item.FullName);$stack.Push($item.FullName);continue
            }
            [void]$files.Add($item.FullName)
        }
    }
    $pendingFiles=New-Object System.Collections.ArrayList
    foreach($path in @($files)){if(-not(Remove-FileRetry ([string]$path))){[void]$pendingFiles.Add([string]$path)}}
    $pendingDirs=New-Object System.Collections.ArrayList
    foreach($dir in @($dirs|Sort-Object Length -Descending)){
        if(Test-Path -LiteralPath $dir -PathType Container){
            if(@(Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue).Count-eq0){if(-not(Remove-EmptyDirectoryRetry $dir)){[void]$pendingDirs.Add($dir)}}else{[void]$pendingDirs.Add($dir)}
        }
    }
    return [pscustomobject]@{PendingFiles=@($pendingFiles);PendingDirectories=@($pendingDirs)}
}

function Write-QualificationIndex([string]$IndexPath,$Data){
    $json=($Data|ConvertTo-Json -Depth 10).Replace("`r`n","`n")+"`n"
    Write-Utf8NoBom $IndexPath $json
}

function Resolve-DefaultTestsRoot {
    $managerRoot=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    $layoutRoot=Split-Path $managerRoot -Parent
    return Join-Path $layoutRoot 'tests'
}

function Invoke-Compaction([string]$TargetResults,[string]$TargetTests,[bool]$DoApply,[string]$SubstitutionMapPath=$null){
    $tests=[System.IO.Path]::GetFullPath($TargetTests).TrimEnd('\')
    Assert-SafeDirectory $tests 'Tests root'
    $resultsParent=Join-Path $tests 'results';$archivesParent=Join-Path $tests 'archives'
    Ensure-SafeDirectory $resultsParent 'Tests results root';Ensure-SafeDirectory $archivesParent 'Tests archives root'
    $results=Assert-StrictChild $resultsParent $TargetResults 'Qualification result'
    Assert-SafeDirectory $results 'Qualification result'
    $substitutionMap=Read-ReparseSubstitutionMap $SubstitutionMapPath
    if($null-ne$substitutionMap){
        if($substitutionMap.MapPath.StartsWith(($results+'\'),[System.StringComparison]::OrdinalIgnoreCase)){Fail('Reparse substitution map must be outside qualification evidence so cleanup cannot delete it.')}
        if($substitutionMap.ProtectedRoot-ieq$results-or$substitutionMap.ProtectedRoot.StartsWith(($results+'\'),[System.StringComparison]::OrdinalIgnoreCase)){Fail('Reparse substitution protected_root must be outside qualification evidence.')}
    }
    $indexPath=Join-Path $results 'QUALIFICATION_INDEX.json'

    if(Test-Path -LiteralPath $indexPath -PathType Leaf){
        $index=Read-Json $indexPath
        if([string]$index.schema-ne'keelaryn.qualification-index.v1'){Fail('Existing qualification index schema is unsupported.')}
        $archivePath=Join-Path $tests ([string]$index.archive_path).Replace('/','\')
        $manifestPath=Join-Path $tests ([string]$index.manifest_path).Replace('/','\')
        if(-not(Test-PublishedArchive $archivePath $manifestPath ([string]$index.archive_sha256) ([string]$index.manifest_sha256))){Fail('Existing qualification archive/index verification failed.')}
        if(-not$DoApply){Write-Host 'Qualification evidence is already archived and verified.' -ForegroundColor Green;Write-Host ('Index: '+$indexPath);return 0}
        $cleanup=Invoke-CleanupAfterArchive $results $indexPath
        $index.cleanup_pending_files=@($cleanup.PendingFiles|ForEach-Object{$_.Substring($results.Length).TrimStart('\').Replace('\','/')})
        $index.cleanup_pending_directories=@($cleanup.PendingDirectories|ForEach-Object{$_.Substring($results.Length).TrimStart('\').Replace('\','/')})
        $index.cleanup_status=if(@($cleanup.PendingFiles).Count-ne0 -or @($cleanup.PendingDirectories).Count-ne0){'pending'}else{'complete'}
        $index.cleanup_checked=(Get-Date).ToUniversalTime().ToString('o')
        Write-QualificationIndex $indexPath $index
        if([string]$index.cleanup_status-eq'complete'){Write-Host 'Qualification evidence archive verified; expanded evidence cleanup complete.' -ForegroundColor Green}else{Write-Host 'Qualification archive is verified; cleanup remains pending for locked paths.' -ForegroundColor Yellow}
        return 0
    }

    $summaryPath=Join-Path $results 'GATE_SUMMARY.json'
    $summary=Read-Json $summaryPath
    if([string]$summary.schema-notmatch'^keelaryn\.manager\.windows-gate-summary\.v\d+$'){Fail('Qualification GATE_SUMMARY schema is unsupported: '+[string]$summary.schema)}
    if([string]::IsNullOrWhiteSpace([string]$summary.completed) -or [string]$summary.status-eq'running'){Fail('Qualification is not completed; evidence compaction is refused.')}
    $inventory=Get-SafeEvidenceInventory $results 'QUALIFICATION_INDEX.json' $substitutionMap
    if(@($inventory.Files).Count-lt1){Fail('Qualification result contains no evidence files.')}
    $evidenceDigest=Get-EvidenceDigest $inventory.Files
    $identity=Get-ArchiveIdentity $results $summary $evidenceDigest
    $archiveDir=Join-Path $archivesParent ('manager-'+$identity.Version)
    $archivePath=Join-Path $archiveDir ($identity.Leaf+'.zip')
    $manifestPath=Join-Path $archiveDir ($identity.Leaf+'.manifest.json')
    [int64]$bytes=0;foreach($f in @($inventory.Files)){$bytes+=[int64]$f.Size}
    Write-Host 'Qualification evidence compaction plan' -ForegroundColor Cyan
    Write-Host ('Result:    '+$results)
    Write-Host ('Verdict:   '+[string]$summary.status)
    Write-Host ('Manager:   '+$identity.Version+' | gate='+$identity.GateRevision+' | framework='+$identity.FrameworkRevision)
    Write-Host ('Evidence:  files='+@($inventory.Files).Count+' bytes='+$bytes+' digest='+$evidenceDigest)
    Write-Host ('Archive:   '+$archivePath)
    Write-Host ('Manifest:  '+$manifestPath)
    $substitutionCount=@($inventory.Files|Where-Object{$null-ne$_.Substitution}).Count
    Write-Host ('Reparse policy: directories rejected; file substitutions='+$substitutionCount+'; unknown/unmapped file reparse points rejected.') -ForegroundColor DarkGray
    Write-Host 'manager\state\history: outside cleanup scope and never touched.' -ForegroundColor DarkGray
    if(-not$DoApply){Write-Host 'DRY RUN ONLY. Nothing was archived or deleted.' -ForegroundColor DarkGray;return 0}

    $manifest=Get-FrozenManifest $results $summary $inventory $evidenceDigest
    $verified=New-VerifiedArchive $archivePath $manifestPath $manifest $inventory
    $archiveRel=$archivePath.Substring($tests.Length).TrimStart('\').Replace('\','/')
    $manifestRel=$manifestPath.Substring($tests.Length).TrimStart('\').Replace('\','/')
    $index=[ordered]@{
        schema='keelaryn.qualification-index.v1'
        manager_version=$identity.Version
        baseline_version=[string]$summary.baseline_version
        gate_revision=$identity.GateRevision
        framework_revision=$identity.FrameworkRevision
        verdict=[string]$summary.status
        gate_completed=[string]$summary.completed
        candidate_installation_sha256=[string]$summary.candidate_installation_sha256
        candidate_managed_content_sha256=[string]$summary.candidate_managed_content_sha256
        source_evidence_digest=$evidenceDigest
        source_file_count=@($inventory.Files).Count
        source_bytes=$bytes
        archive_path=$archiveRel
        archive_sha256=[string]$verified.ArchiveSha256
        manifest_path=$manifestRel
        manifest_sha256=[string]$verified.ManifestSha256
        archive_verified=$true
        archived=(Get-Date).ToUniversalTime().ToString('o')
        cleanup_status='not_started'
        cleanup_pending_files=@()
        cleanup_pending_directories=@()
        cleanup_checked=$null
    }
    Write-QualificationIndex $indexPath $index
    $cleanup=Invoke-CleanupAfterArchive $results $indexPath
    $index.cleanup_pending_files=@($cleanup.PendingFiles|ForEach-Object{$_.Substring($results.Length).TrimStart('\').Replace('\','/')})
    $index.cleanup_pending_directories=@($cleanup.PendingDirectories|ForEach-Object{$_.Substring($results.Length).TrimStart('\').Replace('\','/')})
    $index.cleanup_status=if(@($cleanup.PendingFiles).Count-ne0 -or @($cleanup.PendingDirectories).Count-ne0){'pending'}else{'complete'}
    $index.cleanup_checked=(Get-Date).ToUniversalTime().ToString('o')
    Write-QualificationIndex $indexPath $index
    if([string]$index.cleanup_status-eq'complete'){Write-Host 'Qualification evidence archived, verified and compacted.' -ForegroundColor Green}else{Write-Host 'Qualification evidence archived and verified; locked-path cleanup is pending and resumable.' -ForegroundColor Yellow}
    return 0
}

function Test-Self {
    $temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_qualification_compaction_'+[guid]::NewGuid().ToString('N'))
    try{
        $tests=Join-Path $temp 'tests';$results=Join-Path $tests 'results\manager-9.9.9';$archives=Join-Path $tests 'archives'
        New-Item -ItemType Directory -Force -Path $results,$archives|Out-Null
        $summary=[ordered]@{schema='keelaryn.manager.windows-gate-summary.v16';manager_version='9.9.9';baseline_version='9.9.8';gate_revision=2;framework_revision=11;status='PASS';completed='2026-01-01T00:00:00Z';candidate_installation_sha256=('a'*64);candidate_managed_content_sha256=('b'*64)}
        Write-Utf8NoBom (Join-Path $results 'GATE_SUMMARY.json') (($summary|ConvertTo-Json -Depth 4)+"`n")
        Write-Utf8NoBom (Join-Path $results 'FULL_GATE.log') "selftest`n"
        New-Item -ItemType Directory -Force -Path (Join-Path $results 'command_logs')|Out-Null
        Write-Utf8NoBom (Join-Path $results 'command_logs\one.txt') "one`n"
        if((Invoke-Compaction $results $tests $true)-ne0){return $false}
        $indexPath=Join-Path $results 'QUALIFICATION_INDEX.json'
        if(-not(Test-Path -LiteralPath $indexPath -PathType Leaf)){return $false}
        $remaining=@(Get-ChildItem -LiteralPath $results -Force -Recurse)
        if(@($remaining|Where-Object{-not$_.PSIsContainer}).Count-ne1){return $false}
        $index=Read-Json $indexPath
        if([string]$index.cleanup_status-ne'complete' -or -not [bool]$index.archive_verified){return $false}
        $archive=Join-Path $tests ([string]$index.archive_path).Replace('/','\')
        $manifest=Join-Path $tests ([string]$index.manifest_path).Replace('/','\')
        if(-not(Test-PublishedArchive $archive $manifest ([string]$index.archive_sha256) ([string]$index.manifest_sha256))){return $false}
        if((Invoke-Compaction $results $tests $true)-ne0){return $false}

        # File reparse substitution. Actual file-symlink coverage is used when the host grants
        # symlink creation. Ordinary Windows without Developer Mode / SeCreateSymbolicLinkPrivilege
        # must still be able to run Manager SelfTest, so the protected-copy binding/archive contract
        # also has a privilege-free path that CI exercises explicitly.
        $r2=Join-Path $tests 'results\manager-9.9.10'
        New-Item -ItemType Directory -Force -Path $r2|Out-Null
        $summary2=[ordered]@{schema='keelaryn.manager.windows-gate-summary.v16';manager_version='9.9.10';baseline_version='9.9.9';gate_revision=3;framework_revision=11;status='PASS';completed='2026-01-02T00:00:00Z';candidate_installation_sha256=('c'*64);candidate_managed_content_sha256=('d'*64)}
        Write-Utf8NoBom (Join-Path $r2 'GATE_SUMMARY.json') (($summary2|ConvertTo-Json -Depth 4)+"`n")
        $evil=Join-Path $temp 'evil-target.txt';Write-Utf8NoBom $evil "evil-target-bytes`n"
        $protected=Join-Path $temp 'protected';New-Item -ItemType Directory -Force -Path $protected|Out-Null
        $protectedFile=Join-Path $protected 'copy.bin';Write-Utf8NoBom $protectedFile "protected-archive-bytes`n"
        $link=Join-Path $r2 'linked.txt'
        $forceNoFileSymlink=([string]$env:KEELARYN_SELFTEST_FORCE_NO_FILE_SYMLINK-eq'1')
        $linkCreated=$false;$linkCreationDetail=''
        if(-not$forceNoFileSymlink){
            try{New-Item -ItemType SymbolicLink -Path $link -Target $evil -ErrorAction Stop|Out-Null;$linkCreated=$true}
            catch{$linkCreationDetail=$_.Exception.Message}
        }else{$linkCreationDetail='forced no-file-symlink mode'}
        $mapPath=Join-Path $temp 'reparse-map.json'
        $protectedItem=Get-Item -LiteralPath $protectedFile -Force
        $map=[ordered]@{schema='keelaryn.reparse-substitution-map.v1';protected_root=$protected;entries=@([ordered]@{path='linked.txt';protected_path='copy.bin';size=[int64]$protectedItem.Length;sha256=(Get-Sha256 $protectedFile)})}
        Write-Utf8NoBom $mapPath (($map|ConvertTo-Json -Depth 6)+"`n")
        if($linkCreated){
            $linkItem=Get-Item -LiteralPath $link -Force -ErrorAction Stop
            if(($linkItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-eq0){return $false}
            $unmappedRejected=$false
            try{[void](Invoke-Compaction $r2 $tests $false $null)}catch{$unmappedRejected=$true}
            if(-not$unmappedRejected){return $false}
            if((Invoke-Compaction $r2 $tests $true $mapPath)-ne0){return $false}
            if(-not(Test-Path -LiteralPath $evil -PathType Leaf)-or-not(Test-Path -LiteralPath $protectedFile -PathType Leaf)-or(Test-Path -LiteralPath $link)){return $false}
            $idx2=Read-Json (Join-Path $r2 'QUALIFICATION_INDEX.json')
            $manifest2=Read-Json (Join-Path $tests ([string]$idx2.manifest_path).Replace('/','\'))
            $row2=@($manifest2.entries|Where-Object{[string]$_.path-ceq'linked.txt'})
            if($row2.Count-ne1-or$null-eq$row2[0].substitution){return $false}
            if([string]$row2[0].substitution.schema-ne'keelaryn.reparse-substitution.v1'-or[string]$row2[0].substitution.bound_sha256-cne(Get-Sha256 $protectedFile)){return $false}
            if([string]$row2[0].sha256-cne(Get-Sha256 $protectedFile)-or[string]$row2[0].sha256-ceq(Get-Sha256 $evil)){return $false}
        }else{
            Write-Host ('Qualification compaction self-test: file-symlink fixture unavailable; validating privilege-free substitution binding. '+$linkCreationDetail) -ForegroundColor DarkGray
            $subMap=Read-ReparseSubstitutionMap $mapPath
            $resolved=Resolve-ReparseSubstitution $subMap 'linked.txt'
            if([System.IO.Path]::GetFullPath([string]$resolved.ArchiveSourcePath)-cne[System.IO.Path]::GetFullPath($protectedFile)){return $false}
            if([int64]$resolved.Size-ne[int64]$protectedItem.Length-or[string]$resolved.Sha256-cne(Get-Sha256 $protectedFile)){return $false}
            if([string]$resolved.Substitution.schema-ne'keelaryn.reparse-substitution.v1'-or[string]$resolved.Substitution.bound_sha256-cne(Get-Sha256 $protectedFile)){return $false}
            $syntheticFile=[pscustomobject]@{
                Path=$evil;ArchiveSourcePath=$protectedFile;RelativePath='linked.txt';Size=[int64]$resolved.Size;Sha256=[string]$resolved.Sha256;
                Attributes=[int]$protectedItem.Attributes;CreationTimeUtc=$protectedItem.CreationTimeUtc.ToString('o');LastWriteTimeUtc=$protectedItem.LastWriteTimeUtc.ToString('o');Substitution=$resolved.Substitution
            }
            $syntheticInventory=[pscustomobject]@{Files=@($syntheticFile);Directories=@()}
            $digest2=Get-EvidenceDigest $syntheticInventory.Files
            $manifestObject=Get-FrozenManifest $r2 $summary2 $syntheticInventory $digest2
            $fallbackDir=Join-Path $tests 'archives\manager-9.9.10-fallback';Ensure-SafeDirectory $fallbackDir 'Qualification fallback archive directory'
            $fallbackArchive=Join-Path $fallbackDir 'fallback.zip';$fallbackManifest=Join-Path $fallbackDir 'fallback.manifest.json'
            $verifiedFallback=New-VerifiedArchive $fallbackArchive $fallbackManifest $manifestObject $syntheticInventory
            if(-not(Test-PublishedArchive $fallbackArchive $fallbackManifest ([string]$verifiedFallback.ArchiveSha256) ([string]$verifiedFallback.ManifestSha256))){return $false}
        }

        # Reparse-point directories remain unconditionally rejected and are never traversed.
        $r3=Join-Path $tests 'results\manager-9.9.11';New-Item -ItemType Directory -Force -Path $r3|Out-Null
        $summary3=[ordered]@{schema='keelaryn.manager.windows-gate-summary.v16';manager_version='9.9.11';baseline_version='9.9.10';gate_revision=4;framework_revision=11;status='PASS';completed='2026-01-03T00:00:00Z';candidate_installation_sha256=('e'*64);candidate_managed_content_sha256=('f'*64)}
        Write-Utf8NoBom (Join-Path $r3 'GATE_SUMMARY.json') (($summary3|ConvertTo-Json -Depth 4)+"`n")
        $dirTarget=Join-Path $temp 'dir-target';New-Item -ItemType Directory -Force -Path $dirTarget|Out-Null
        New-Item -ItemType Junction -Path (Join-Path $r3 'linked-dir') -Target $dirTarget -ErrorAction Stop|Out-Null
        $dirRejected=$false
        try{[void](Invoke-Compaction $r3 $tests $false $null)}catch{$dirRejected=$true}
        if(-not$dirRejected){return $false}
        return $true
    }catch{Write-Host ('Qualification compaction self-test detail: '+$_.Exception.Message) -ForegroundColor Red;return $false}
    finally{if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}}
}

try{
    if($SelfTest){if(Test-Self){Write-Host 'Qualification evidence compaction self-test PASS.' -ForegroundColor Green;exit 0};Write-Host 'Qualification evidence compaction self-test FAIL.' -ForegroundColor Red;exit 1}
    if([string]::IsNullOrWhiteSpace($TestsRoot)){$TestsRoot=Resolve-DefaultTestsRoot}
    if([string]::IsNullOrWhiteSpace($ResultsPath)){Fail('ResultsPath is required.')}
    exit (Invoke-Compaction $ResultsPath $TestsRoot ([bool]$Apply) $ReparseSubstitutionMapPath)
}catch{Write-Host ('Qualification evidence compaction error: '+$_.Exception.Message) -ForegroundColor Red;exit 1}
