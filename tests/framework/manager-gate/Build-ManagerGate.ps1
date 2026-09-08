[CmdletBinding(DefaultParameterSetName='Root')]
param(
    [Parameter(Mandatory=$true,ParameterSetName='Root')][string]$SourceRoot,
    [Parameter(Mandatory=$true,ParameterSetName='Zip')][string]$SourceZip,
    [Parameter(Mandatory=$true)][string]$BaselineVersion,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [int]$GateRevision=1,
    [switch]$Force
)

$ErrorActionPreference='Stop'
if($PSVersionTable.PSVersion.Major-lt5){throw 'Build-ManagerGate requires PowerShell 5 or newer.'}
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$sourceZipSafetyPath=Join-Path $PSScriptRoot 'SourceZipSafety.ps1'
if(-not(Test-Path -LiteralPath $sourceZipSafetyPath -PathType Leaf)){throw('Framework SourceZip safety helper missing: '+$sourceZipSafetyPath)}
. $sourceZipSafetyPath

function Sha([string]$Path){return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function TextSha([string]$Text){
    $enc=New-Object System.Text.UTF8Encoding($false);$sha=[System.Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($sha.ComputeHash($enc.GetBytes($Text))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
}
function Write-Utf8NoBom([string]$Path,[string]$Text){
    $parent=Split-Path -Parent $Path;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    [System.IO.File]::WriteAllText($Path,$Text,(New-Object System.Text.UTF8Encoding($false)))
}
function Assert-VersionText([string]$Text,[string]$Name){if($Text-notmatch'^[0-9]+\.[0-9]+\.[0-9]+$'){throw($Name+' must be x.y.z: '+$Text)}}
function Get-OrdinalUniqueStrings([object[]]$Values){
    $list=New-Object 'System.Collections.Generic.List[string]'
    foreach($raw in @($Values)){if($null-ne$raw){[void]$list.Add([string]$raw)}}
    $list.Sort([System.StringComparer]::Ordinal)
    $out=New-Object System.Collections.ArrayList
    $haveLast=$false;$last=''
    foreach($item in $list){
        if ((-not $haveLast) -or (-not [string]::Equals($last,$item,[System.StringComparison]::Ordinal))) {
            [void]$out.Add($item);$last=$item;$haveLast=$true
        }
    }
    return @($out)
}
function GateSpecManagedDigest([string]$Root,$Manifest){
    $managed=New-Object 'System.Collections.Generic.List[string]'
    foreach($raw in @($Manifest.managed_files)){[void]$managed.Add(([string]$raw).Replace('\','/'))}
    $managed.Sort([System.StringComparer]::Ordinal)
    $rows=New-Object System.Collections.ArrayList
    foreach($raw in $managed){
        $p=Join-Path $Root $raw.Replace('/','\');if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Managed source file missing: '+$raw)}
        [void]$rows.Add($raw+"`0"+(Sha $p))
    }
    return TextSha([string]::Join("`n",@($rows)))
}
function Copy-DeclaredFiles([string]$Root,$Manifest,[string]$Destination){
    foreach($raw in @($Manifest.managed_files)){
        $rel=([string]$raw).Replace('/','\');$src=Join-Path $Root $rel
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)){throw('Managed source file missing: '+$rel)}
        $item=Get-Item -LiteralPath $src -Force;if(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw('Managed source reparse point refused: '+$rel)}
        $dst=Join-Path $Destination $rel;$parent=Split-Path -Parent $dst;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null};Copy-Item -LiteralPath $src -Destination $dst -Force
    }
}
function Write-DeterministicZip([string]$Source,[string]$ZipPath,[string]$RootName){
    $tmp=$ZipPath+'.tmp-'+[guid]::NewGuid().ToString('N');$stream=$null;$archive=$null
    try{
        $stream=[System.IO.File]::Open($tmp,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::ReadWrite,[System.IO.FileShare]::None)
        $archive=New-Object System.IO.Compression.ZipArchive($stream,[System.IO.Compression.ZipArchiveMode]::Create,$false)
        $root=(Get-Item -LiteralPath $Source -Force).FullName.TrimEnd('\')
        $filePaths=New-Object 'System.Collections.Generic.List[string]'
        foreach($f in @(Get-ChildItem -LiteralPath $Source -File -Recurse -Force)){[void]$filePaths.Add([string]$f.FullName)}
        $filePaths.Sort([System.StringComparer]::Ordinal)
        foreach($filePath in $filePaths){
            $f=Get-Item -LiteralPath $filePath -Force
            if(($f.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw('Gate package reparse point refused: '+$f.FullName)}
            $rel=$f.FullName.Substring($root.Length).TrimStart('\').Replace('\','/')
            $entry=$archive.CreateEntry($RootName.TrimEnd('/')+'/'+$rel,[System.IO.Compression.CompressionLevel]::Optimal);$entry.LastWriteTime=[datetimeoffset]'2000-01-01T00:00:00Z'
            $input=[System.IO.File]::OpenRead($f.FullName);$output=$entry.Open();try{$input.CopyTo($output)}finally{$output.Dispose();$input.Dispose()}
        }
        $archive.Dispose();$archive=$null;$stream.Dispose();$stream=$null
        if(Test-Path -LiteralPath $ZipPath){if(-not$Force){throw('Output already exists; use -Force: '+$ZipPath)};Remove-Item -LiteralPath $ZipPath -Force}
        Move-Item -LiteralPath $tmp -Destination $ZipPath
    }finally{if($archive){$archive.Dispose()};if($stream){$stream.Dispose()};if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}}
}

Assert-VersionText $BaselineVersion 'BaselineVersion'
if($GateRevision-lt1){throw 'GateRevision must be >= 1.'}
$frameworkRoot=$PSScriptRoot;$templates=Join-Path $frameworkRoot 'templates'
$frameworkRevisionPath=Join-Path $frameworkRoot 'FRAMEWORK_REVISION.txt'
if(-not(Test-Path -LiteralPath $frameworkRevisionPath -PathType Leaf)){throw('Framework revision marker missing: '+$frameworkRevisionPath)}
$frameworkRevision=0
if(-not[int]::TryParse((Get-Content -LiteralPath $frameworkRevisionPath -Raw -Encoding UTF8).Trim(),[ref]$frameworkRevision)-or$frameworkRevision-lt1){throw 'Framework revision marker is invalid.'}
foreach($required in @('Invoke-KeelarynGateChild.ps1','Publish-KeelarynTestedArtifacts.ps1','Run-KeelarynManagerFullGate.ps1','Run-KeelarynManagerSourceGate.ps1','RUN_FULL_GATE.cmd.template')){if(-not(Test-Path -LiteralPath (Join-Path $templates $required) -PathType Leaf)){throw('Framework template missing: '+$required)}}

$tempRoot=Join-Path ([System.IO.Path]::GetTempPath()) ('keelaryn_gate_build_'+[guid]::NewGuid().ToString('N'))
try{
    New-Item -ItemType Directory -Force -Path $tempRoot|Out-Null
    if($PSCmdlet.ParameterSetName-eq'Zip'){
        $SourceZip=[System.IO.Path]::GetFullPath($SourceZip);if(-not(Test-Path -LiteralPath $SourceZip -PathType Leaf)){throw('SOURCE ZIP missing: '+$SourceZip)}
        $expanded=Join-Path $tempRoot 'source-expanded'
        $SourceRoot=Expand-KeelarynSourceZipSafely -ZipPath $SourceZip -Destination $expanded -RequiredRoot 'keelaryn'
    }
    $SourceRoot=[System.IO.Path]::GetFullPath($SourceRoot).TrimEnd('\');if(-not(Test-Path -LiteralPath $SourceRoot -PathType Container)){throw('Manager source root missing: '+$SourceRoot)}
    $installPath=Join-Path $SourceRoot 'product\install\INSTALLATION.json';if(-not(Test-Path -LiteralPath $installPath -PathType Leaf)){throw('INSTALLATION.json missing: '+$installPath)}
    $install=(Get-Content -LiteralPath $installPath -Raw -Encoding UTF8)|ConvertFrom-Json
    if([string]$install.schema-ne'keelaryn.manager.installation.v2'){throw('Unsupported installation schema: '+[string]$install.schema)}
    $version=[string]$install.manager_version;Assert-VersionText $version 'candidate manager_version'
    if([version]$version-le[version]$BaselineVersion){throw('Candidate version must be newer than baseline: '+$BaselineVersion+' -> '+$version)}
    $finalPaths=@(Get-OrdinalUniqueStrings @($install.managed_files|ForEach-Object{([string]$_).Replace('\','/')}));if($finalPaths.Count-lt1-or$finalPaths.Count-ne@($install.managed_files).Count){throw 'INSTALLATION managed_files is empty or contains duplicates.'}
    $managedDigest=GateSpecManagedDigest $SourceRoot $install;$installSha=Sha $installPath

    $stage=Join-Path $tempRoot ('manager-'+$version);New-Item -ItemType Directory -Force -Path $stage|Out-Null;Copy-DeclaredFiles $SourceRoot $install $stage
    $bootstrap='$ManagerVersion = "'+$version+'"'+"`r`n"+'$runtime = Join-Path $PSScriptRoot ''product\runtime\Keelaryn__Manager.ps1'''+"`r`n"+'if (-not (Test-Path -LiteralPath $runtime -PathType Leaf)) {'+"`r`n"+'    [Console]::Error.WriteLine(''Keelaryn Manager runtime is missing: ''+$runtime)'+"`r`n"+'    exit 1'+"`r`n"+'}'+"`r`n"+'& (Join-Path $PSHOME ''powershell.exe'') -NoProfile -ExecutionPolicy Bypass -File $runtime @args'+"`r`n"+'exit $LASTEXITCODE'+"`r`n"
    Write-Utf8NoBom (Join-Path $stage 'Keelaryn__Manager.ps1') $bootstrap;Write-Utf8NoBom (Join-Path $stage '_manager_version.txt') ($version+"`n")
    $transition=@(Get-OrdinalUniqueStrings @($finalPaths+@('Keelaryn__Manager.ps1','_manager_manifest.json','_manager_version.txt')))
    $transitionDoc=[ordered]@{schema='keelaryn.manager.installation.v1';manager_version=$version;managed_files=$transition};Write-Utf8NoBom (Join-Path $stage '_manager_manifest.json') ((($transitionDoc|ConvertTo-Json -Depth 10).Replace("`r`n","`n"))+"`n")

    $gateDir=Join-Path $stage 'gate';New-Item -ItemType Directory -Force -Path $gateDir|Out-Null
    foreach($name in @('Invoke-KeelarynGateChild.ps1','Publish-KeelarynTestedArtifacts.ps1','Run-KeelarynManagerFullGate.ps1','Run-KeelarynManagerSourceGate.ps1')){Copy-Item -LiteralPath (Join-Path $templates $name) -Destination (Join-Path $gateDir $name) -Force}
    $spec=[ordered]@{schema='keelaryn.manager-gate-spec.v1';framework_version='2.0';framework_revision=$frameworkRevision;candidate_version=$version;baseline_manager_version=$BaselineVersion;gate_revision=$GateRevision;candidate_installation_sha256=$installSha;candidate_managed_content_sha256=$managedDigest;final_managed_count=$finalPaths.Count}
    Write-Utf8NoBom (Join-Path $gateDir 'GATE_SPEC.json') ((($spec|ConvertTo-Json -Depth 8).Replace("`r`n","`n"))+"`n");Write-Utf8NoBom (Join-Path $gateDir 'GATE_REVISION.txt') ([string]$GateRevision+"`n");Write-Utf8NoBom (Join-Path $gateDir 'FRAMEWORK_REVISION.txt') ([string]$frameworkRevision+"`n")
    $runTemplate=[System.IO.File]::ReadAllText((Join-Path $templates 'RUN_FULL_GATE.cmd.template'),[System.Text.Encoding]::ASCII);$digits=$version.Replace('.','');$run=$runTemplate.Replace('{{VERSION}}',$version).Replace('{{VERSION_DIGITS}}',$digits).Replace('{{GATE_REVISION}}',[string]$GateRevision);$run=$run.Replace("`r`n","`n").Replace("`n","`r`n");Write-Utf8NoBom (Join-Path $stage ('RUN_'+$digits+'_FULL_GATE.cmd')) $run

    foreach($f in @(Get-ChildItem -LiteralPath $stage -File -Recurse -Force|Where-Object{$_.Extension-in@('.ps1','.cmd')})){
        $bytes=[System.IO.File]::ReadAllBytes($f.FullName);foreach($b in $bytes){if($b-gt127){throw('Non-ASCII executable source in gate package: '+$f.FullName)}}
    }
    foreach($f in @(Get-ChildItem -LiteralPath $stage -File -Recurse -Force -Filter '*.ps1')){
        $tokens=$null;$errors=$null;$ast=[System.Management.Automation.Language.Parser]::ParseFile($f.FullName,[ref]$tokens,[ref]$errors)
        if(@($errors).Count-ne0){throw('PowerShell parser rejected generated gate package file: '+$f.FullName+'; '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
        $defs=@{}
        foreach($fn in @($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]},$true))){
            $a=$fn.Parent;$nested=$false;while($null-ne$a){if($a -is [System.Management.Automation.Language.FunctionDefinitionAst]){$nested=$true;break};$a=$a.Parent}
            if(-not$nested){$defs[[string]$fn.Name]=[int]$fn.Extent.StartOffset}
        }
        foreach($c in @($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst]},$true))){
            $a=$c.Parent;$inside=$false;while($null-ne$a){if($a -is [System.Management.Automation.Language.FunctionDefinitionAst]){$inside=$true;break};$a=$a.Parent};if($inside){continue}
            $n=$c.GetCommandName();if($n-and$defs.ContainsKey([string]$n)-and[int]$c.Extent.StartOffset-lt[int]$defs[[string]$n]){throw('Generated gate invokes custom helper before definition: '+$f.FullName+'; helper='+$n)}
        }
    }
    foreach($gatePs in @(Get-ChildItem -LiteralPath $gateDir -File -Filter '*.ps1')){
        $gateText=[System.IO.File]::ReadAllText($gatePs.FullName,[System.Text.Encoding]::ASCII)
        if($gateText.Contains(".Replace('\\'")){throw('Gate path normalization contains C-style double-backslash literal: '+$gatePs.FullName)}
    }
    # PowerShell treats ',' and '+' with precedence that can silently concatenate multiple intended array elements.
    # Reject unparenthesized dynamic string concatenation in array literals at framework build time.
    foreach($gatePs in @(Get-ChildItem -LiteralPath $gateDir -File -Filter '*.ps1')){
        $gateText=[System.IO.File]::ReadAllText($gatePs.FullName,[System.Text.Encoding]::ASCII)
        if([regex]::IsMatch($gateText,'(?:@\(|,)\s*''[^''\r\n]*''\s*\+\s*\$[A-Za-z_][A-Za-z0-9_]*\s*,')){
            throw('Ambiguous unparenthesized dynamic array element in gate template: '+$gatePs.FullName)
        }
    }

    # Ordering safety is contract-specific. Do not globally reject historical Windows ordering:
    # rollback/update fixtures and same-run diagnostic snapshots intentionally retain the Windows-proven contract.
    $allowedFullNameSortFunctions=@('TreeDigest','PortableHubDigest','PortableHubSnapshot','Write-DirectoryZip')
    $allowedUniqueSortFunctions=@('Compare-PortableHubSnapshots')
    foreach($gatePs in @(Get-ChildItem -LiteralPath $gateDir -File -Filter '*.ps1')){
        $gateText=[System.IO.File]::ReadAllText($gatePs.FullName,[System.Text.Encoding]::ASCII)
        if($gateText -match '\.WaitForExit\(\)'){
            throw('Unbounded process wait is forbidden in gate template: '+$gatePs.FullName)
        }

        $sortTokens=$null
        $sortErrors=$null
        $sortAst=[System.Management.Automation.Language.Parser]::ParseFile(
            $gatePs.FullName,
            [ref]$sortTokens,
            [ref]$sortErrors
        )
        if(@($sortErrors).Count -ne 0){
            throw('PowerShell parser rejected gate ordering audit target: '+$gatePs.FullName)
        }

        $sortCommands=@(
            $sortAst.FindAll(
                {
                    param($node)
                    ($node -is [System.Management.Automation.Language.CommandAst]) -and
                    ($node.GetCommandName() -ieq 'Sort-Object')
                },
                $true
            )
        )
        foreach($cmd in $sortCommands){
            $fn=$cmd.Parent
            while(($null -ne $fn) -and (-not($fn -is [System.Management.Automation.Language.FunctionDefinitionAst]))){
                $fn=$fn.Parent
            }
            $fnName=''
            if($null -ne $fn){$fnName=[string]$fn.Name}
            $cmdText=[string]$cmd.Extent.Text

            $usesFullName=($cmdText -match '(?i)(?:^|\s|\|)Sort-Object\s+FullName(?:\s|$)')
            if($usesFullName -and ($allowedFullNameSortFunctions -notcontains $fnName)){
                throw('Culture-sensitive FullName ordering is forbidden in this gate context: '+$gatePs.FullName+'; function='+$fnName)
            }

            $usesUnique=($cmdText -match '(?i)(?:^|\s)-Unique(?:\s|$)')
            if($usesUnique -and ($allowedUniqueSortFunctions -notcontains $fnName)){
                throw('Culture-sensitive path uniqueness is forbidden in this gate context: '+$gatePs.FullName+'; function='+$fnName)
            }
        }

        if($gatePs.Name -eq 'Run-KeelarynManagerFullGate.ps1'){
            foreach($token in @(
                'function Test-IsTransientFileLockException',
                'function Open-ZipUpdateWithSharingRetry',
                'function Test-ZipUpdateSharingRetrySelfTest',
                '$za=Open-ZipUpdateWithSharingRetry $stateCurrent'
            )){
                if(-not$gateText.Contains($token)){throw('Framework r12 FullGate sharing-retry contract missing token: '+$token)}
            }
            if($gateText.Contains('$za=[System.IO.Compression.ZipFile]::Open($stateCurrent')){
                throw 'Framework r12 forbids direct single-attempt CURRENT ZipFile.Open(Update) in Full Gate E4.'
            }
            $gateDigestFns=@(
                $sortAst.FindAll(
                    {
                        param($node)
                        ($node -is [System.Management.Automation.Language.FunctionDefinitionAst]) -and
                        ($node.Name -eq 'GateSpecManagedDigest')
                    },
                    $true
                )
            )
            if($gateDigestFns.Count -ne 1){
                throw('GateSpecManagedDigest definition count mismatch in FullGate template: '+$gatePs.FullName)
            }
            $gateDigestText=[string]$gateDigestFns[0].Extent.Text
            if(
                ($gateDigestText -notmatch '\[System\.StringComparer\]::Ordinal') -or
                ($gateDigestText -match '(?i)Sort-Object')
            ){
                throw('GateSpecManagedDigest must use explicit ordinal ordering and no Sort-Object: '+$gatePs.FullName)
            }
        }
    }

    $OutputPath=[System.IO.Path]::GetFullPath($OutputPath);if((Split-Path $OutputPath -Leaf)-cne('manager-'+$version+'.zip')){throw('Output ZIP must be named exactly manager-'+$version+'.zip: '+$OutputPath)};$parent=Split-Path -Parent $OutputPath;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    Write-DeterministicZip $stage $OutputPath ('manager-'+$version)
    Write-Host ('Manager gate built: '+$OutputPath)
    Write-Host ('Candidate: '+$version+'; baseline: '+$BaselineVersion+'; gate revision: '+$GateRevision+'; framework revision: '+$frameworkRevision)
    Write-Host ('Managed content: '+$managedDigest)
    Write-Host ('ZIP SHA256: '+(Sha $OutputPath))
}finally{if(Test-Path -LiteralPath $tempRoot){Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue}}
