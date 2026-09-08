Set-StrictMode -Version 2.0

function Get-KeelarynSourceZipLimits {
    [pscustomobject]@{
        MaxZipBytes = [long](128MB)
        MaxExpandedBytes = [long](64MB)
        MaxEntries = [int]10000
        MaxEntryBytes = [long](32MB)
        MaxCompressionRatio = [double]500.0
        MaxPathChars = [int]4096
        MaxSegmentChars = [int]255
    }
}

function Test-KeelarynWindowsReservedName([string]$Segment) {
    $base = $Segment
    $dot = $base.IndexOf('.')
    if ($dot -ge 0) { $base = $base.Substring(0,$dot) }
    return $base -match '^(?i:CON|PRN|AUX|NUL|CLOCK\$|COM[1-9]|LPT[1-9])$'
}

function Get-KeelarynCanonicalArchiveKey([string[]]$Segments,[bool]$IsDirectory) {
    $parts = New-Object 'System.Collections.Generic.List[string]'
    foreach ($segment in $Segments) {
        $normalized = $segment.Normalize([System.Text.NormalizationForm]::FormC).ToUpperInvariant()
        [void]$parts.Add($normalized)
    }
    $key = [string]::Join('/',@($parts))
    if ($IsDirectory) { $key += '/' }
    return $key
}

function Assert-KeelarynArchiveSegment([string]$Segment,$Limits) {
    if ([string]::IsNullOrEmpty($Segment)) { throw 'SOURCE ZIP contains an empty path segment.' }
    if ($Segment -ceq '.' -or $Segment -ceq '..') { throw ('SOURCE ZIP contains a dot path segment: '+$Segment) }
    if ($Segment.Length -gt [int]$Limits.MaxSegmentChars) { throw ('SOURCE ZIP path segment is too long: '+$Segment.Length) }
    if ($Segment.EndsWith(' ') -or $Segment.EndsWith('.')) { throw ('SOURCE ZIP path segment has a Windows-unsafe trailing character: '+$Segment) }
    if ($Segment -match '[<>:"|?*\x00-\x1F]') { throw ('SOURCE ZIP path segment contains a Windows-unsafe character: '+$Segment) }
    if (Test-KeelarynWindowsReservedName $Segment) { throw ('SOURCE ZIP uses a Windows reserved device name: '+$Segment) }
}

function Assert-KeelarynExtractionDirectory([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -ErrorAction Stop | Out-Null
    }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (-not $item.PSIsContainer) { throw ('SOURCE ZIP extraction path is not a directory: '+$Path) }
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('SOURCE ZIP extraction path is a reparse point: '+$Path) }
}

function Expand-KeelarynSourceZipSafely {
    param(
        [Parameter(Mandatory=$true)][string]$ZipPath,
        [Parameter(Mandatory=$true)][string]$Destination,
        [string]$RequiredRoot='keelaryn',
        $Limits=$null
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if ($null -eq $Limits) { $Limits = Get-KeelarynSourceZipLimits }

    $ZipPath = [System.IO.Path]::GetFullPath($ZipPath)
    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) { throw ('SOURCE ZIP missing: '+$ZipPath) }
    $zipItem = Get-Item -LiteralPath $ZipPath -Force -ErrorAction Stop
    if (($zipItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('SOURCE ZIP must not be a reparse point: '+$ZipPath) }
    if ([long]$zipItem.Length -gt [long]$Limits.MaxZipBytes) { throw ('SOURCE ZIP exceeds compressed-size limit: '+$zipItem.Length) }

    $Destination = [System.IO.Path]::GetFullPath($Destination).TrimEnd([char[]]'\/')
    if (Test-Path -LiteralPath $Destination) { throw ('SOURCE ZIP destination must not already exist: '+$Destination) }
    Assert-KeelarynExtractionDirectory $Destination
    $destinationPrefix = $Destination + [System.IO.Path]::DirectorySeparatorChar

    $stream = $null
    $archive = $null
    try {
        $stream = [System.IO.File]::Open($ZipPath,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::Read)
        $archive = New-Object System.IO.Compression.ZipArchive($stream,[System.IO.Compression.ZipArchiveMode]::Read,$false)
        if ($archive.Entries.Count -gt [int]$Limits.MaxEntries) { throw ('SOURCE ZIP exceeds entry-count limit: '+$archive.Entries.Count) }

        $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
        [long]$expanded = 0
        $validated = New-Object System.Collections.ArrayList
        foreach ($entry in @($archive.Entries)) {
            $raw = [string]$entry.FullName
            if ([string]::IsNullOrWhiteSpace($raw)) { throw 'SOURCE ZIP contains an empty entry name.' }
            if ($raw.Length -gt [int]$Limits.MaxPathChars) { throw ('SOURCE ZIP entry path is too long: '+$raw.Length) }
            $path = $raw.Replace('\','/')
            if ($path.StartsWith('/') -or $path.StartsWith('//') -or $path -match '^[A-Za-z]:') { throw ('SOURCE ZIP contains an absolute path: '+$raw) }
            $isDirectory = $path.EndsWith('/')
            $trimmed = $path.TrimEnd('/')
            if ([string]::IsNullOrWhiteSpace($trimmed)) { throw ('SOURCE ZIP contains an invalid root entry: '+$raw) }
            $segments = @($trimmed.Split('/'))
            foreach ($segment in $segments) { Assert-KeelarynArchiveSegment $segment $Limits }
            if ($segments[0] -cne $RequiredRoot) { throw ('SOURCE ZIP entry is outside required root '+$RequiredRoot+': '+$raw) }

            $key = Get-KeelarynCanonicalArchiveKey $segments $isDirectory
            if (-not $seen.Add($key)) { throw ('SOURCE ZIP contains a case/Unicode alias or duplicate path: '+$raw) }

            $external = [int]$entry.ExternalAttributes
            if (($external -band [int][System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('SOURCE ZIP contains Windows reparse metadata: '+$raw) }
            $unixType = (($external -shr 16) -band 0xF000)
            if ($unixType -ne 0 -and $unixType -ne 0x4000 -and $unixType -ne 0x8000) { throw ('SOURCE ZIP contains unsafe Unix file-type metadata: '+$raw) }
            if ($unixType -eq 0xA000) { throw ('SOURCE ZIP contains symlink metadata: '+$raw) }

            [long]$length = $entry.Length
            [long]$compressed = $entry.CompressedLength
            if ($length -lt 0 -or $compressed -lt 0) { throw ('SOURCE ZIP contains an invalid entry length: '+$raw) }
            if ($isDirectory -and $length -ne 0) { throw ('SOURCE ZIP directory entry has data: '+$raw) }
            if ($length -gt [long]$Limits.MaxEntryBytes) { throw ('SOURCE ZIP entry exceeds expanded-size limit: '+$raw) }
            if ($length -gt ([long]$Limits.MaxExpandedBytes - $expanded)) { throw ('SOURCE ZIP exceeds total expanded-size limit at: '+$raw) }
            $expanded += $length
            if ($length -gt 0) {
                if ($compressed -le 0) { throw ('SOURCE ZIP entry has an unsafe compression ratio: '+$raw) }
                $ratio = [double]$length / [double]$compressed
                if ($ratio -gt [double]$Limits.MaxCompressionRatio) { throw ('SOURCE ZIP entry exceeds compression-ratio limit: '+$raw) }
            }
            [void]$validated.Add([pscustomobject]@{ Entry=$entry; Path=$trimmed; IsDirectory=$isDirectory; Length=$length })
        }

        foreach ($row in @($validated)) {
            $relative = ([string]$row.Path).Replace('/',[System.IO.Path]::DirectorySeparatorChar)
            $target = [System.IO.Path]::GetFullPath((Join-Path $Destination $relative))
            if (-not $target.StartsWith($destinationPrefix,[System.StringComparison]::OrdinalIgnoreCase)) { throw ('SOURCE ZIP extraction escaped destination: '+[string]$row.Path) }
            if ([bool]$row.IsDirectory) {
                Assert-KeelarynExtractionDirectory $target
                continue
            }
            $parent = Split-Path -Parent $target
            if (-not [string]::IsNullOrWhiteSpace($parent)) {
                $relativeParent = $parent.Substring($Destination.Length).TrimStart([char[]]'\/')
                $current = $Destination
                foreach ($segment in @($relativeParent -split '[\\/]')) {
                    if ([string]::IsNullOrWhiteSpace($segment)) { continue }
                    $current = Join-Path $current $segment
                    Assert-KeelarynExtractionDirectory $current
                }
            }
            if (Test-Path -LiteralPath $target) { throw ('SOURCE ZIP extraction target already exists: '+$target) }
            $input = $null
            $output = $null
            try {
                $input = $row.Entry.Open()
                $output = [System.IO.File]::Open($target,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
                $input.CopyTo($output)
                $output.Flush()
                if ($output.Length -ne [long]$row.Length) { throw ('SOURCE ZIP extracted length mismatch: '+[string]$row.Path) }
            } finally {
                if ($output) { $output.Dispose() }
                if ($input) { $input.Dispose() }
            }
        }
    } finally {
        if ($archive) { $archive.Dispose() }
        if ($stream) { $stream.Dispose() }
    }

    $managerRoot = Join-Path $Destination ($RequiredRoot+'\manager')
    if (-not (Test-Path -LiteralPath $managerRoot -PathType Container)) { throw ('SOURCE ZIP does not contain canonical '+$RequiredRoot+'\manager root.') }
    return $managerRoot
}
