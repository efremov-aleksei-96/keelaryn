[CmdletBinding()]
param([string]$RepositoryRoot=$PSScriptRoot+'\..')

$ErrorActionPreference='Stop'
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$manager=Join-Path $RepositoryRoot 'manager'
$hub=Join-Path $RepositoryRoot 'hub'
$tests=Join-Path $RepositoryRoot 'tests'

function Fail([string]$Message){throw $Message}
function Sha([string]$Path){return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}

foreach($p in @($manager,$hub,$tests)){
    if(-not(Test-Path -LiteralPath $p -PathType Container)){Fail('Missing canonical repository directory: '+$p)}
}

$version=(Get-Content -LiteralPath (Join-Path $manager '_manager_version.txt') -Raw -Encoding UTF8).Trim()
$manifest=(Get-Content -LiteralPath (Join-Path $manager '_manager_manifest.json') -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$manifest.manager_version-ne$version){Fail 'Manager version/manifest mismatch.'}
foreach($rel in @($manifest.managed_files)){
    $p=Join-Path $manager ([string]$rel).Replace('/','\')
    if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Managed file missing: '+$rel)}
    $ext=[System.IO.Path]::GetExtension([string]$rel)
    if($ext-ieq'.ps1'-or$ext-ieq'.cmd'){
        foreach($b in [System.IO.File]::ReadAllBytes($p)){
            if($b-ge128){Fail('Non-ASCII managed executable source: '+$rel)}
        }
    }
    if($ext-ieq'.ps1'){
        $source=[System.IO.File]::ReadAllText($p,[System.Text.Encoding]::UTF8)
        $tokens=$null;$errors=$null
        [void][System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
        if(@($errors).Count){Fail('PowerShell parser error in '+$rel+': '+((@($errors)|ForEach-Object{$_.Message})-join'; '))}
    }
}

$runtimeDirs=@('_inbox','_history','_logs','_releases')
foreach($name in $runtimeDirs){if(Test-Path -LiteralPath (Join-Path $manager $name)){Fail('Runtime directory must not be committed: manager/'+$name)}}

$hubFiles=@(Get-ChildItem -LiteralPath $hub -File -Recurse -Force)
if($hubFiles.Count-ne1-or$hubFiles[0].Name-ne'README.md'){Fail 'Public hub/ must contain only README.md.'}

foreach($area in @('work','results')){
    $root=Join-Path $tests $area
    $files=@(Get-ChildItem -LiteralPath $root -File -Recurse -Force)
    if($files.Count-ne1-or$files[0].Name-ne'README.md'){Fail('Public tests/'+$area+' must contain only README.md.')}
}

$forbiddenExtensions=@('.kdbx','.pfx','.p12','.pem','.key','.bin')
foreach($f in @(Get-ChildItem -LiteralPath $RepositoryRoot -File -Recurse -Force)){
    $rel=$f.FullName.Substring($RepositoryRoot.Length).TrimStart('\').Replace('\','/')
    if($rel.StartsWith('.git/')){continue}
    if($rel-eq'tools/Verify-PublicRepository.ps1'){continue}
    if($forbiddenExtensions-contains$f.Extension.ToLowerInvariant()){Fail('Potential private/binary file in public tree: '+$rel)}
    if($f.Extension-ieq'.zip'){Fail('ZIP archive must not be committed to public source tree: '+$rel)}

    if($f.Length-le5MB-and$f.Extension.ToLowerInvariant()-in@('.md','.txt','.json','.ps1','.cmd','.yml','.yaml','.gitignore','.gitattributes')){
        $text=[System.IO.File]::ReadAllText($f.FullName,[System.Text.Encoding]::UTF8)
        foreach($pattern in @(
            '(?i)[A-Z]:\\Users\\',
            '(?i)/home/[^/\s]+',
            '(?i)D:\\0\\0__Core',
            '(?i)BEGIN (RSA|OPENSSH|EC) PRIVATE KEY',
            '(?i)appr-r\d{4}-[0-9a-f]{12}',
            '(?i)cand-r\d{4}-[0-9a-f]{12}'
        )){
            if($text-match$pattern){Fail('Potential instance/local leakage in '+$rel+'; pattern='+$pattern)}
        }
    }
}

Write-Host ('Public repository verification PASS. Manager '+$version+'; managed files='+@($manifest.managed_files).Count) -ForegroundColor Green
