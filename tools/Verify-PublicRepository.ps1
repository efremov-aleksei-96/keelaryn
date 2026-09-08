[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Fail([string]$Message){throw $Message}
function Sha([string]$Path){return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Rel([string]$Path){return [System.IO.Path]::GetFullPath($Path).Substring($RepositoryRoot.Length).TrimStart('\').Replace('\','/')}

$manager=Join-Path $RepositoryRoot 'manager'
$hub=Join-Path $RepositoryRoot 'hub'
$tests=Join-Path $RepositoryRoot 'tests'
foreach($p in @($manager,$hub,$tests)){
    if(-not(Test-Path -LiteralPath $p -PathType Container)){Fail('Missing canonical repository directory: '+$p)}
}

$installPath=Join-Path $manager 'product\install\INSTALLATION.json'
if(-not(Test-Path -LiteralPath $installPath -PathType Leaf)){Fail 'Missing canonical INSTALLATION.json.'}
$install=(Get-Content -LiteralPath $installPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$install.schema-ne'keelaryn.manager.installation.v2'){Fail('Unsupported installation schema: '+[string]$install.schema)}
$version=[string]$install.manager_version

$expected=New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
foreach($raw in @($install.managed_files)){[void]$expected.Add(([string]$raw).Replace('\','/'))}
if($expected.Count-ne@($install.managed_files).Count){Fail 'INSTALLATION managed_files contains duplicates.'}

$actual=New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
foreach($f in @(Get-ChildItem -LiteralPath $manager -File -Recurse -Force)){
    $rel=$f.FullName.Substring($manager.Length).TrimStart('\').Replace('\','/')
    [void]$actual.Add($rel)
}
if($actual.Count-ne$expected.Count){Fail('manager/ must contain exactly the managed source set; expected='+$expected.Count+' actual='+$actual.Count)}
foreach($rel in $expected){if(-not($actual.Contains($rel))){Fail('Managed source missing: '+$rel)}}
foreach($rel in $actual){if(-not($expected.Contains($rel))){Fail('Unexpected Manager repository file: '+$rel)}}

foreach($rel in $expected){
    $p=Join-Path $manager $rel.Replace('/','\')
    $ext=[System.IO.Path]::GetExtension($rel).ToLowerInvariant()
    if($ext-in@('.ps1','.cmd')){
        foreach($b in [System.IO.File]::ReadAllBytes($p)){if($b-ge128){Fail('Non-ASCII executable source: manager/'+$rel)}}
    }
    if($ext-eq'.ps1'){
        $src=[System.IO.File]::ReadAllText($p,[System.Text.Encoding]::UTF8)
        $tokens=$null;$errors=$null
        [void][System.Management.Automation.Language.Parser]::ParseInput($src,[ref]$tokens,[ref]$errors)
        if(@($errors).Count){Fail('PowerShell parser error: manager/'+$rel+'; '+((@($errors)|ForEach-Object{$_.Message})-join'; '))}
    }
}
if(Test-Path -LiteralPath (Join-Path $manager 'state')){Fail 'manager/state must not be committed.'}

$hubFiles=@(Get-ChildItem -LiteralPath $hub -File -Recurse -Force)
if($hubFiles.Count-ne1-or(Rel $hubFiles[0].FullName)-ne'hub/README.md'){Fail 'Public hub/ must contain only README.md.'}
foreach($area in @('work','results')){
    $dir=Join-Path $tests $area
    if(-not(Test-Path -LiteralPath $dir -PathType Container)){Fail('Missing tests/'+$area)}
    $files=@(Get-ChildItem -LiteralPath $dir -File -Recurse -Force)
    if($files.Count-ne1-or$files[0].Name-ne'README.md'){Fail('Public tests/'+$area+' must contain only README.md.')}
}

$framework=Join-Path $tests 'framework\manager-gate'
if(-not(Test-Path -LiteralPath $framework -PathType Container)){Fail 'Missing tests/framework/manager-gate.'}
$frameworkRevisionPath=Join-Path $framework 'FRAMEWORK_REVISION.txt'
if(-not(Test-Path -LiteralPath $frameworkRevisionPath -PathType Leaf)){Fail 'Missing Gate Framework revision marker.'}
$fr=0
$frText=(Get-Content -LiteralPath $frameworkRevisionPath -Raw -Encoding UTF8).Trim()
if(-not[int]::TryParse($frText,[ref]$fr)-or$fr-lt1){Fail('Invalid Gate Framework revision marker: '+$frText)}

$manifestPath=Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json'
if(-not(Test-Path -LiteralPath $manifestPath -PathType Leaf)){Fail 'Missing PUBLIC_FILE_MANIFEST.json.'}
$publicManifest=(Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$publicManifest.schema-ne'keelaryn.public-file-manifest.v2'){Fail 'Unsupported PUBLIC_FILE_MANIFEST schema.'}
if([string]$publicManifest.manager.version-ne$version){Fail 'Public manifest Manager version mismatch.'}
if([int]$publicManifest.manager.file_count-ne$expected.Count){Fail 'Public manifest Manager file_count mismatch.'}
if(([string]$publicManifest.manager.installation_sha256).ToLowerInvariant()-ne(Sha $installPath)){Fail 'Public manifest INSTALLATION SHA-256 mismatch.'}

$manifestManagerPaths=New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
foreach($row in @($publicManifest.manager.files)){
    $rel=([string]$row.path).Replace('\','/')
    if(-not($manifestManagerPaths.Add($rel))){Fail('Duplicate public Manager manifest path: '+$rel)}
    $p=Join-Path $manager $rel.Replace('/','\')
    if(-not(Test-Path -LiteralPath $p -PathType Leaf)-or(Sha $p)-ne([string]$row.sha256).ToLowerInvariant()){Fail('Public Manager source hash mismatch: '+$rel)}
}
if($manifestManagerPaths.Count-ne$expected.Count){Fail 'Public Manager manifest path count mismatch.'}
foreach($rel in $expected){if(-not($manifestManagerPaths.Contains($rel))){Fail('Public Manager manifest omitted managed path: '+$rel)}}

if([string]$publicManifest.gate_framework.framework_version-ne'2.0'){Fail('Unsupported public Gate Framework version: '+[string]$publicManifest.gate_framework.framework_version)}
if([int]$publicManifest.gate_framework.revision-ne$fr){Fail('Public manifest Gate Framework revision mismatch: marker=r'+$fr+' manifest=r'+[int]$publicManifest.gate_framework.revision)}
$frameworkFiles=@(Get-ChildItem -LiteralPath $framework -File -Recurse -Force)
if([int]$publicManifest.gate_framework.file_count-ne$frameworkFiles.Count){Fail 'Public manifest Gate Framework file_count mismatch.'}
$manifestFrameworkPaths=New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
foreach($row in @($publicManifest.gate_framework.files)){
    $rel=([string]$row.path).Replace('\','/')
    if(-not($manifestFrameworkPaths.Add($rel))){Fail('Duplicate public Gate Framework manifest path: '+$rel)}
    $p=Join-Path $framework $rel.Replace('/','\')
    if(-not(Test-Path -LiteralPath $p -PathType Leaf)-or(Sha $p)-ne([string]$row.sha256).ToLowerInvariant()){Fail('Public Gate Framework source hash mismatch: '+$rel)}
}
if($manifestFrameworkPaths.Count-ne$frameworkFiles.Count){Fail 'Public Gate Framework manifest path count mismatch.'}
foreach($f in $frameworkFiles){
    $rel=$f.FullName.Substring($framework.Length).TrimStart('\').Replace('\','/')
    if(-not($manifestFrameworkPaths.Contains($rel))){Fail('Public Gate Framework manifest omitted source path: '+$rel)}
}

$provPath=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json'
if(-not(Test-Path -LiteralPath $provPath -PathType Leaf)){Fail 'Missing PUBLIC_PROVENANCE.json.'}
$prov=(Get-Content -LiteralPath $provPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$prov.schema-ne'keelaryn.public-repository-provenance.v2'){Fail('Unsupported PUBLIC_PROVENANCE schema: '+[string]$prov.schema)}
if([string]$prov.source_manager_version-ne$version){Fail 'Public provenance Manager version mismatch.'}
if([string]$prov.gate_framework.version-ne'2.0'){Fail 'Public provenance Gate Framework version mismatch.'}
if([int]$prov.gate_framework.revision-ne$fr){Fail('Public provenance Gate Framework revision mismatch: marker=r'+$fr+' provenance=r'+[int]$prov.gate_framework.revision)}
if($null-eq$prov.production_validation-or$null-eq$prov.production_validation.PSObject.Properties['tested_update_sha256']){Fail 'Public provenance is missing production_validation.tested_update_sha256.'}
$productionFrameworkRevision=[int]$prov.production_validation.framework_revision
if($productionFrameworkRevision-lt1){Fail 'Production-validation Framework revision must be >= 1.'}
if($productionFrameworkRevision-gt$fr){Fail('Production-validation Framework revision cannot be newer than current public Framework: production=r'+$productionFrameworkRevision+' current=r'+$fr)}
$testedUpdate=([string]$prov.production_validation.tested_update_sha256).Trim().ToLowerInvariant()
if([bool]$prov.production_validation.full_gate_pass){
    if($testedUpdate-notmatch'^[0-9a-f]{64}$'){Fail 'Full-Gate-qualified provenance requires a valid tested_update_sha256.'}
    if($null-eq$prov.production_validation.gate_revision){Fail 'Full-Gate-qualified provenance requires gate_revision.'}
}elseif(-not[string]::IsNullOrWhiteSpace($testedUpdate)){
    Fail 'Unqualified provenance must not retain a tested_update_sha256.'
}

$forbiddenExt=@('.kdbx','.pfx','.p12','.pem','.key','.bin')
$warnings=@()
$maintainerPath=('D:'+'\0'+'\0__Core'+'\keelaryn')
foreach($f in @(Get-ChildItem -LiteralPath $RepositoryRoot -File -Recurse -Force)){
    $rel=Rel $f.FullName
    if($rel.StartsWith('.git/')){continue}
    if($forbiddenExt-contains$f.Extension.ToLowerInvariant()){Fail('Potential private/binary file: '+$rel)}
    if($f.Extension-ieq'.zip'){Fail('ZIP archive must not be committed: '+$rel)}
    if($f.Length-le8MB-and$f.Extension.ToLowerInvariant()-in@('.md','.txt','.json','.ps1','.cmd','.yml','.yaml','.gitignore','.gitattributes')){
        $text=[System.IO.File]::ReadAllText($f.FullName,[System.Text.Encoding]::UTF8)
        foreach($pattern in @('(?i)[A-Z]:\\Users\\[^\\\s]+','(?i)/(?:home|Users)/[^/\s]+','(?i)BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY','(?i)appr-r\d{4}-[0-9a-f]{12}','(?i)cand-r\d{4}-[0-9a-f]{12}')){
            if($text-match$pattern){Fail('Potential instance/local leakage in '+$rel+'; pattern='+$pattern)}
        }
        if($text.IndexOf($maintainerPath,[System.StringComparison]::OrdinalIgnoreCase)-ge0){
            if($rel-eq'manager/product/docs/TESTING.md'-or$rel-eq'tests/framework/manager-gate/README.md'){
                $warnings += ('Nonportable maintainer-path example retained in exact qualified source: '+$rel)
            }else{
                Fail('Unexpected maintainer-local path in public tree: '+$rel)
            }
        }
    }
}

Write-Host('Public repository verification PASS. Manager '+$version+'; managed='+$expected.Count+'; framework=r'+$fr) -ForegroundColor Green
foreach($w in $warnings){Write-Warning $w}
