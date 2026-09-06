from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPACTOR = ROOT / 'manager/product/tools/Compact-KeelarynQualificationEvidence.ps1'
PATCHER = ROOT / '.github/manager-4.13-lifecycle.py'


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected one sentinel, found {count}')
    return text.replace(old, new, 1)


def replace_block(text, start_marker, end_marker, replacement, label):
    if text.count(start_marker) != 1:
        raise RuntimeError(f'{label}: start marker count={text.count(start_marker)}')
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    if text.find(end_marker, end + 1) >= 0:
        raise RuntimeError(f'{label}: end marker is not unique after start')
    return text[:start] + replacement.rstrip() + '\n\n' + text[end:]


s = COMPACTOR.read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
s = replace_once(
    s,
    "    [switch]$Apply,\n    [switch]$SelfTest",
    "    [switch]$Apply,\n    [string]$ReparseSubstitutionMapPath,\n    [switch]$SelfTest",
    'compactor parameter contract',
)

inventory_block = r'''function Test-SafeRelativeEvidencePath([string]$Value){
    if([string]::IsNullOrWhiteSpace($Value)-or[System.IO.Path]::IsPathRooted($Value)){return $false}
    $norm=$Value.Replace('\\','/')
    if($norm.StartsWith('/')-or$norm.EndsWith('/')){return $false}
    $parts=@($norm.Split('/'))
    if($parts.Count-lt1){return $false}
    foreach($part in $parts){
        if([string]::IsNullOrWhiteSpace($part)-or$part-eq'.'-or$part-eq'..'-or$part.Contains(':')-or$part.Contains('*')-or$part.Contains('?')){return $false}
    }
    return $true
}

function Assert-NoReparseDirectoryChain([string]$Directory,[string]$Purpose){
    $full=[System.IO.Path]::GetFullPath($Directory).TrimEnd('\\')
    $root=[System.IO.Path]::GetPathRoot($full)
    if([string]::IsNullOrWhiteSpace($root)){Fail($Purpose+' has no filesystem root: '+$full)}
    $current=$root
    $rootItem=Get-Item -LiteralPath $current -Force -ErrorAction Stop
    if(($rootItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail($Purpose+' filesystem root is a reparse point: '+$current)}
    $relative=$full.Substring($root.Length).Trim('\\')
    if(-not[string]::IsNullOrWhiteSpace($relative)){
        foreach($part in @($relative.Split('\\'))){
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
    $protectedRoot=[System.IO.Path]::GetFullPath($protectedRaw).TrimEnd('\\')
    [void](Assert-NoReparseDirectoryChain $protectedRoot 'Reparse substitution protected root')
    Assert-SafeDirectory $protectedRoot 'Reparse substitution protected root'
    $rows=@($map.entries)
    if($rows.Count-lt1-or$rows.Count-gt4096){Fail('Reparse substitution map must contain 1..4096 entries.')}
    $table=@{}
    foreach($row in $rows){
        $evidencePath=([string]$row.path).Replace('\\','/').Trim()
        $protectedPath=([string]$row.protected_path).Replace('\\','/').Trim()
        if(-not(Test-SafeRelativeEvidencePath $evidencePath)){Fail('Unsafe reparse substitution evidence path: '+$evidencePath)}
        if(-not(Test-SafeRelativeEvidencePath $protectedPath)){Fail('Unsafe reparse substitution protected path: '+$protectedPath)}
        if($table.ContainsKey($evidencePath)){Fail('Duplicate reparse substitution evidence path: '+$evidencePath)}
        [int64]$boundSize=[int64]$row.size
        $boundSha=([string]$row.sha256).Trim().ToLowerInvariant()
        if($boundSize-lt0-or$boundSha-notmatch'^[0-9a-f]{64}$'){Fail('Invalid size/SHA-256 binding for reparse substitution: '+$evidencePath)}
        $protectedFull=Join-Path $protectedRoot $protectedPath.Replace('/','\\')
        $protectedFull=[System.IO.Path]::GetFullPath($protectedFull)
        if(-not$protectedFull.StartsWith(($protectedRoot+'\\'),[System.StringComparison]::OrdinalIgnoreCase)){Fail('Protected substitution path escaped protected_root: '+$protectedPath)}
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
    $rootFull=[System.IO.Path]::GetFullPath($Root).TrimEnd('\\')
    $files=New-Object System.Collections.ArrayList
    $dirs=New-Object System.Collections.ArrayList
    $stack=New-Object 'System.Collections.Generic.Stack[string]'
    $stack.Push($rootFull)
    while($stack.Count-gt0){
        $dir=$stack.Pop()
        foreach($item in @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction Stop)){
            if($item.Name-ceq$ExcludeLeaf-and$item.FullName.Substring($rootFull.Length).TrimStart('\\').IndexOf('\\')-lt0){continue}
            $isReparse=(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0)
            if($item.PSIsContainer){
                if($isReparse){Fail('Qualification evidence contains a reparse-point directory: '+$item.FullName)}
                [void]$dirs.Add($item.FullName);$stack.Push($item.FullName);continue
            }
            $rel=$item.FullName.Substring($rootFull.Length).TrimStart('\\').Replace('\\','/')
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
}'''
s = replace_block(s, 'function Get-SafeEvidenceInventory', 'function Get-EvidenceDigest', inventory_block, 'safe evidence inventory')

s = replace_once(s, '            substitution=$null', '            substitution=$f.Substitution', 'manifest substitution provenance')
s = replace_once(s, "$source=[System.IO.File]::OpenRead([string]$f.Path)", "$archiveSource=[string]$f.ArchiveSourcePath\n                $archiveItem=Get-Item -LiteralPath $archiveSource -Force -ErrorAction Stop\n                if($archiveItem.PSIsContainer-or($archiveItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Archive source became a reparse point: '+[string]$f.RelativePath)}\n                if([int64]$archiveItem.Length-ne[int64]$f.Size-or(Get-Sha256 $archiveSource)-cne[string]$f.Sha256){Fail('Archive source changed after inventory: '+[string]$f.RelativePath)}\n                $source=[System.IO.File]::OpenRead($archiveSource)", 'archive source binding')

cleanup_block = r'''function Invoke-CleanupAfterArchive([string]$ResultsRoot,[string]$IndexPath){
    Assert-SafeDirectory $ResultsRoot 'Qualification evidence root'
    $rootFull=[System.IO.Path]::GetFullPath($ResultsRoot).TrimEnd('\\')
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
}'''
s = replace_block(s, 'function Invoke-CleanupAfterArchive', 'function Write-QualificationIndex', cleanup_block, 'post-archive cleanup')

s = replace_once(
    s,
    'function Invoke-Compaction([string]$TargetResults,[string]$TargetTests,[bool]$DoApply){',
    'function Invoke-Compaction([string]$TargetResults,[string]$TargetTests,[bool]$DoApply,[string]$SubstitutionMapPath=$null){',
    'Invoke-Compaction signature',
)
s = replace_once(
    s,
    "    Assert-SafeDirectory $results 'Qualification result'\n    $indexPath=Join-Path $results 'QUALIFICATION_INDEX.json'",
    "    Assert-SafeDirectory $results 'Qualification result'\n    $substitutionMap=Read-ReparseSubstitutionMap $SubstitutionMapPath\n    if($null-ne$substitutionMap){\n        if($substitutionMap.MapPath.StartsWith(($results+'\\'),[System.StringComparison]::OrdinalIgnoreCase)){Fail('Reparse substitution map must be outside qualification evidence so cleanup cannot delete it.')}\n        if($substitutionMap.ProtectedRoot-ieq$results-or$substitutionMap.ProtectedRoot.StartsWith(($results+'\\'),[System.StringComparison]::OrdinalIgnoreCase)){Fail('Reparse substitution protected_root must be outside qualification evidence.')}\n    }\n    $indexPath=Join-Path $results 'QUALIFICATION_INDEX.json'",
    'compaction substitution initialization',
)
s = replace_once(s, "$inventory=Get-SafeEvidenceInventory $results 'QUALIFICATION_INDEX.json'", "$inventory=Get-SafeEvidenceInventory $results 'QUALIFICATION_INDEX.json' $substitutionMap", 'inventory substitution map')
s = replace_once(
    s,
    "    Write-Host 'Reparse points: rejected; manager\\state\\history: outside scope and never touched.' -ForegroundColor DarkGray",
    "    $substitutionCount=@($inventory.Files|Where-Object{$null-ne$_.Substitution}).Count\n    Write-Host ('Reparse policy: directories rejected; file substitutions='+$substitutionCount+'; unknown/unmapped file reparse points rejected.') -ForegroundColor DarkGray\n    Write-Host 'manager\\state\\history: outside cleanup scope and never touched.' -ForegroundColor DarkGray",
    'compaction reparse plan output',
)

selftest_old = """        if((Invoke-Compaction $results $tests $true)-ne0){return $false}\n        return $true"""
selftest_new = r'''        if((Invoke-Compaction $results $tests $true)-ne0){return $false}

        # File reparse substitution: the link target is intentionally different from the protected bound copy.
        $r2=Join-Path $tests 'results\manager-9.9.10'
        New-Item -ItemType Directory -Force -Path $r2|Out-Null
        $summary2=[ordered]@{schema='keelaryn.manager.windows-gate-summary.v16';manager_version='9.9.10';baseline_version='9.9.9';gate_revision=3;framework_revision=11;status='PASS';completed='2026-01-02T00:00:00Z';candidate_installation_sha256=('c'*64);candidate_managed_content_sha256=('d'*64)}
        Write-Utf8NoBom (Join-Path $r2 'GATE_SUMMARY.json') (($summary2|ConvertTo-Json -Depth 4)+"`n")
        $evil=Join-Path $temp 'evil-target.txt';Write-Utf8NoBom $evil "evil-target-bytes`n"
        $protected=Join-Path $temp 'protected';New-Item -ItemType Directory -Force -Path $protected|Out-Null
        $protectedFile=Join-Path $protected 'copy.bin';Write-Utf8NoBom $protectedFile "protected-archive-bytes`n"
        $link=Join-Path $r2 'linked.txt'
        New-Item -ItemType SymbolicLink -Path $link -Target $evil -ErrorAction Stop|Out-Null
        $linkItem=Get-Item -LiteralPath $link -Force -ErrorAction Stop
        if(($linkItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-eq0){return $false}
        $mapPath=Join-Path $temp 'reparse-map.json'
        $protectedItem=Get-Item -LiteralPath $protectedFile -Force
        $map=[ordered]@{schema='keelaryn.reparse-substitution-map.v1';protected_root=$protected;entries=@([ordered]@{path='linked.txt';protected_path='copy.bin';size=[int64]$protectedItem.Length;sha256=(Get-Sha256 $protectedFile)})}
        Write-Utf8NoBom $mapPath (($map|ConvertTo-Json -Depth 6)+"`n")
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

        # Reparse-point directories remain unconditionally rejected and are never traversed.
        $r3=Join-Path $tests 'results\manager-9.9.11';New-Item -ItemType Directory -Force -Path $r3|Out-Null
        $summary3=[ordered]@{schema='keelaryn.manager.windows-gate-summary.v16';manager_version='9.9.11';baseline_version='9.9.10';gate_revision=4;framework_revision=11;status='PASS';completed='2026-01-03T00:00:00Z';candidate_installation_sha256=('e'*64);candidate_managed_content_sha256=('f'*64)}
        Write-Utf8NoBom (Join-Path $r3 'GATE_SUMMARY.json') (($summary3|ConvertTo-Json -Depth 4)+"`n")
        $dirTarget=Join-Path $temp 'dir-target';New-Item -ItemType Directory -Force -Path $dirTarget|Out-Null
        New-Item -ItemType Junction -Path (Join-Path $r3 'linked-dir') -Target $dirTarget -ErrorAction Stop|Out-Null
        $dirRejected=$false
        try{[void](Invoke-Compaction $r3 $tests $false $null)}catch{$dirRejected=$true}
        if(-not$dirRejected){return $false}
        return $true'''
s = replace_once(s, selftest_old, selftest_new, 'reparse substitution self-test')
s = replace_once(
    s,
    "    exit (Invoke-Compaction $ResultsPath $TestsRoot ([bool]$Apply))",
    "    exit (Invoke-Compaction $ResultsPath $TestsRoot ([bool]$Apply) $ReparseSubstitutionMapPath)",
    'command substitution-map forwarding',
)
COMPACTOR.write_text(s, encoding='utf-8', newline='\n')

p = PATCHER.read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
p = replace_once(
    p,
    "Reparse-point directories and file reparse points are rejected by automatic qualification compaction. The tool never follows them. A future substitution mechanism may only use an explicitly protected non-reparse counterpart bound by exact size and SHA-256 and must record substitution provenance.",
    "Reparse-point directories are always rejected and never traversed. File reparse points are rejected unless an explicit `keelaryn.reparse-substitution-map.v1` binds the original evidence path to a protected regular non-reparse copy by exact size and SHA-256. The archive is built from the protected copy under the original evidence path, while the manifest preserves original attributes/timestamps plus substitution provenance. Unknown, unused, changed or unsafe bindings fail closed.",
    'TESTING reparse policy docs',
)
PATCHER.write_text(p, encoding='utf-8', newline='\n')

print('LIFECYCLE_REPARSE_SUBSTITUTION_FIX=PASS')
