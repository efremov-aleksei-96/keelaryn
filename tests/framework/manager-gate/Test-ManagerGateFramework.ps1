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
if($revision-cne'20'){throw('Framework qualification expected revision 20, got '+$revision)}

foreach($ps in @(Get-ChildItem -LiteralPath $frameworkRoot -File -Recurse -Filter '*.ps1')){
    $tokens=$null;$errors=$null
    [void][System.Management.Automation.Language.Parser]::ParseFile($ps.FullName,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne0){throw('PowerShell parser rejected framework file '+$ps.FullName+': '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
}
$builderText=[System.IO.File]::ReadAllText($builderPath,[System.Text.Encoding]::UTF8)
if($builderText.IndexOf('Expand-Archive',[System.StringComparison]::OrdinalIgnoreCase)-ge0){throw 'Framework r20 builder must not use Expand-Archive for SourceZip.'}
foreach($token in @('SourceZipSafety.ps1','Expand-KeelarynSourceZipSafely')){if(-not$builderText.Contains($token)){throw('Framework r20 builder safety binding missing token: '+$token)}}

$script:tempRoot=Join-Path ([System.IO.Path]::GetTempPath()) ('keelaryn_framework_r20_selftest_'+[guid]::NewGuid().ToString('N'))
try{
    New-Item -ItemType Directory -Force -Path $script:tempRoot|Out-Null
    $valid=Get-ValidEntries

    Write-Host '[1/14] Valid SourceZip extraction...'
    $validZip=Join-Path $script:tempRoot 'valid-source.zip';New-TestZip $validZip $valid
    $validOut=Join-Path $script:tempRoot 'valid-out'
    $managerRoot=Expand-KeelarynSourceZipSafely -ZipPath $validZip -Destination $validOut -RequiredRoot 'keelaryn'
    if(-not(Test-Path -LiteralPath (Join-Path $managerRoot 'product\install\INSTALLATION.json') -PathType Leaf)){throw 'Valid SourceZip extraction lost INSTALLATION.json.'}

    Write-Host '[2/14] Builder SourceZip integration...'
    $gateOut=Join-Path $script:tempRoot 'manager-9.9.9.zip'
    & (Join-Path $PSHOME 'powershell.exe') -NoProfile -ExecutionPolicy Bypass -File $builderPath -SourceZip $validZip -BaselineVersion '9.9.8' -GateRevision 1 -OutputPath $gateOut
    if($LASTEXITCODE-ne0-or-not(Test-Path -LiteralPath $gateOut -PathType Leaf)){throw 'Builder SourceZip integration failed.'}

    Write-Host '[3/14] Zip Slip / dot-segment rejection...'
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/../escape.txt';Text='x';Bytes=$null;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'zip-slip' $rows
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/./dot.txt';Text='x';Bytes=$null;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'dot-segment' $rows

    Write-Host '[4/14] Windows reserved-name rejection...'
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/CON.txt';Text='x';Bytes=$null;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'reserved-name' $rows

    Write-Host '[5/14] Case-alias rejection...'
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/Case.txt';Text='a';Bytes=$null;Compression='Optimal';ExternalAttributes=0};$rows+=,[pscustomobject]@{Name='keelaryn/manager/case.txt';Text='b';Bytes=$null;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'case-alias' $rows

    Write-Host '[6/14] Unicode-normalization alias rejection...'
    $composed='caf'+[char]0x00E9+'.txt';$decomposed='cafe'+[char]0x0301+'.txt'
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name=('keelaryn/manager/'+$composed);Text='a';Bytes=$null;Compression='Optimal';ExternalAttributes=0};$rows+=,[pscustomobject]@{Name=('keelaryn/manager/'+$decomposed);Text='b';Bytes=$null;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'unicode-alias' $rows

    Write-Host '[7/14] Symlink metadata rejection...'
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/link';Text='target';Bytes=$null;Compression='Optimal';ExternalAttributes=-1577123840};Assert-Rejected 'symlink-metadata' $rows

    Write-Host '[8/14] Windows reparse metadata rejection...'
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/reparse';Text='x';Bytes=$null;Compression='Optimal';ExternalAttributes=1024};Assert-Rejected 'reparse-metadata' $rows

    Write-Host '[9/14] Compression-ratio rejection...'
    $bomb=New-Object byte[] (2MB);for($i=0;$i-lt$bomb.Length;$i++){$bomb[$i]=65}
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/ratio-bomb.bin';Text=$null;Bytes=$bomb;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'compression-ratio' $rows

    Write-Host '[10/14] Expanded-size limit rejection...'
    $limits=Get-KeelarynSourceZipLimits;$limits.MaxExpandedBytes=[long]1024;$limits.MaxEntryBytes=[long]1024
    $large=New-Object byte[] 2048
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/large.bin';Text=$null;Bytes=$large;Compression='NoCompression';ExternalAttributes=0};Assert-Rejected 'expanded-size' $rows $limits

    Write-Host '[11/14] Entry-count limit rejection...'
    $limits=Get-KeelarynSourceZipLimits;$limits.MaxEntries=2
    $rows=Clone-Entries $valid;$rows+=,[pscustomobject]@{Name='keelaryn/manager/third.txt';Text='x';Bytes=$null;Compression='Optimal';ExternalAttributes=0};Assert-Rejected 'entry-count' $rows $limits


    Write-Host '[12/14] Transition UPDATE compatibility-alias contract...'
    $sourceGateTemplate=Join-Path $frameworkRoot 'templates\Run-KeelarynManagerSourceGate.ps1'
    $tokens=$null;$errors=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile($sourceGateTemplate,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne0){throw('SourceGate template parser failure before alias-contract extraction: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $functions=@($ast.FindAll({param($node)$node-is[System.Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Get-UpdateTransportCompatibilityContract'},$true))
    if($functions.Count-ne1){throw('Expected exactly one Get-UpdateTransportCompatibilityContract function in SourceGate template; actual='+$functions.Count)}
    Invoke-Expression ([string]$functions[0].Extent.Text)
    $manifestContractFunctions=@($ast.FindAll({param($node)$node-is[System.Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Assert-TransitionInstallationManifestMatchesUpdateTransport'},$true))
    if($manifestContractFunctions.Count-ne1){throw('Expected exactly one Assert-TransitionInstallationManifestMatchesUpdateTransport function in SourceGate template; actual='+$manifestContractFunctions.Count)}
    Invoke-Expression ([string]$manifestContractFunctions[0].Extent.Text)
    foreach($helperName in @('Get-ZipEntryIdentityKey','Get-UniqueZipEntryIndex','Get-ZipEntryDigest','Assert-TransitionAliasPayloadBinding')){
        $helperFunctions=@($ast.FindAll({param($node)$node-is[System.Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq$helperName},$true))
        if($helperFunctions.Count-ne1){throw('Expected exactly one '+$helperName+' function in SourceGate template; actual='+$helperFunctions.Count)}
        Invoke-Expression ([string]$helperFunctions[0].Extent.Text)
    }

    $final=@('product/a.txt','product/b.txt')
    $transition=@('Keelaryn__Manager.ps1','_manager_manifest.json','_manager_version.txt')
    $zero=Get-UpdateTransportCompatibilityContract -FinalPaths $final -TransitionOnly $transition -ReleasePolicy ([pscustomobject]@{})
    if(@($zero.ExpectedPackagePaths).Count-ne5-or@($zero.Aliases).Count-ne0){throw 'Zero-alias UPDATE transport contract mismatch.'}

    $validPolicy=[pscustomobject]@{transition_compatibility_aliases=@([pscustomobject]@{path='legacy/a.txt';source_path='product/a.txt'})}
    $validContract=Get-UpdateTransportCompatibilityContract -FinalPaths $final -TransitionOnly $transition -ReleasePolicy $validPolicy
    if(@($validContract.ExpectedPackagePaths).Count-ne6-or@($validContract.Aliases).Count-ne1-or[string]$validContract.Aliases[0].SourcePath-cne'product/a.txt'){throw 'Valid transition alias contract mismatch.'}

    $validTransitionManifest=@($validContract.ExpectedPackagePaths)
    Assert-TransitionInstallationManifestMatchesUpdateTransport -TransitionPaths $validTransitionManifest -ExpectedPackagePaths @($validContract.ExpectedPackagePaths)

    $missingAliasTransition=@($validTransitionManifest|Where-Object{$_-cne'legacy/a.txt'})
    $missingAliasRejected=$false
    try{
        Assert-TransitionInstallationManifestMatchesUpdateTransport -TransitionPaths $missingAliasTransition -ExpectedPackagePaths @($validContract.ExpectedPackagePaths)
    }catch{
        $missingAliasRejected=$true
        Write-Host('  PASS reject update-transition-manifest-missing-alias: '+$_.Exception.Message)
    }
    if(-not$missingAliasRejected){throw 'UPDATE transition installation manifest without the declared alias was accepted.'}

    $extraTransition=@($validTransitionManifest)+@('legacy/extra.txt')
    $extraTransitionRejected=$false
    try{
        Assert-TransitionInstallationManifestMatchesUpdateTransport -TransitionPaths $extraTransition -ExpectedPackagePaths @($validContract.ExpectedPackagePaths)
    }catch{
        $extraTransitionRejected=$true
        Write-Host('  PASS reject update-transition-manifest-extra-path: '+$_.Exception.Message)
    }
    if(-not$extraTransitionRejected){throw 'UPDATE transition installation manifest with an extra path was accepted.'}

    $duplicateTransition=@($validTransitionManifest)+@($validTransitionManifest[0])
    $duplicateTransitionRejected=$false
    try{
        Assert-TransitionInstallationManifestMatchesUpdateTransport -TransitionPaths $duplicateTransition -ExpectedPackagePaths @($validContract.ExpectedPackagePaths)
    }catch{
        $duplicateTransitionRejected=$true
        Write-Host('  PASS reject update-transition-manifest-duplicate-path: '+$_.Exception.Message)
    }
    if(-not$duplicateTransitionRejected){throw 'UPDATE transition installation manifest duplicate path was silently accepted.'}

    $aliasZip=Join-Path $script:tempRoot 'alias-binding.zip'
    $aliasArchive=[System.IO.Compression.ZipFile]::Open($aliasZip,[System.IO.Compression.ZipArchiveMode]::Create)
    try{
        $srcEntry=$aliasArchive.CreateEntry('source.txt',[System.IO.Compression.CompressionLevel]::NoCompression)
        $writer=New-Object System.IO.StreamWriter($srcEntry.Open(),(New-Object System.Text.UTF8Encoding($false)))
        try{$writer.Write('canonical bytes')}finally{$writer.Dispose()}
        $aliasEntry=$aliasArchive.CreateEntry('alias.txt',[System.IO.Compression.CompressionLevel]::NoCompression)
        $writer=New-Object System.IO.StreamWriter($aliasEntry.Open(),(New-Object System.Text.UTF8Encoding($false)))
        try{$writer.Write('canonical bytes')}finally{$writer.Dispose()}
    }finally{$aliasArchive.Dispose()}

    $aliasArchive=[System.IO.Compression.ZipFile]::OpenRead($aliasZip)
    try{
        $srcEntry=@($aliasArchive.Entries|Where-Object{$_.FullName-eq'source.txt'})[0]
        $aliasEntry=@($aliasArchive.Entries|Where-Object{$_.FullName-eq'alias.txt'})[0]
        $srcDigest=Get-ZipEntryDigest $srcEntry
        $row=[pscustomobject]@{sha256=$srcDigest.Sha256;size_bytes=$srcDigest.Size}
        Assert-TransitionAliasPayloadBinding -AliasRow $row -SourceRow $row -AliasEntry $aliasEntry -SourceEntry $srcEntry -AliasPath 'legacy/a.txt' -SourcePath 'product/a.txt'
    }finally{$aliasArchive.Dispose()}

    $badAliasZip=Join-Path $script:tempRoot 'alias-binding-corrupt.zip'
    $badArchive=[System.IO.Compression.ZipFile]::Open($badAliasZip,[System.IO.Compression.ZipArchiveMode]::Create)
    try{
        $srcEntry=$badArchive.CreateEntry('source.txt',[System.IO.Compression.CompressionLevel]::NoCompression)
        $writer=New-Object System.IO.StreamWriter($srcEntry.Open(),(New-Object System.Text.UTF8Encoding($false)))
        try{$writer.Write('canonical bytes')}finally{$writer.Dispose()}
        $aliasEntry=$badArchive.CreateEntry('alias.txt',[System.IO.Compression.CompressionLevel]::NoCompression)
        $writer=New-Object System.IO.StreamWriter($aliasEntry.Open(),(New-Object System.Text.UTF8Encoding($false)))
        try{$writer.Write('corrupted bytes')}finally{$writer.Dispose()}
    }finally{$badArchive.Dispose()}

    $badArchive=[System.IO.Compression.ZipFile]::OpenRead($badAliasZip)
    try{
        $srcEntry=@($badArchive.Entries|Where-Object{$_.FullName-eq'source.txt'})[0]
        $aliasEntry=@($badArchive.Entries|Where-Object{$_.FullName-eq'alias.txt'})[0]
        $srcDigest=Get-ZipEntryDigest $srcEntry
        $copiedRow=[pscustomobject]@{sha256=$srcDigest.Sha256;size_bytes=$srcDigest.Size}
        $corruptRejected=$false
        try{
            Assert-TransitionAliasPayloadBinding -AliasRow $copiedRow -SourceRow $copiedRow -AliasEntry $aliasEntry -SourceEntry $srcEntry -AliasPath 'legacy/a.txt' -SourcePath 'product/a.txt'
        }catch{
            $corruptRejected=$true
            Write-Host('  PASS reject corrupted-alias-payload-bytes: '+$_.Exception.Message)
        }
        if(-not$corruptRejected){throw 'Corrupted alias payload bytes were accepted from copied manifest metadata.'}
    }finally{$badArchive.Dispose()}

    $caseDuplicateZip=Join-Path $script:tempRoot 'update-duplicate-case-key.zip'
    $caseArchive=[System.IO.Compression.ZipFile]::Open($caseDuplicateZip,[System.IO.Compression.ZipArchiveMode]::Create)
    try{
        foreach($name in @(
            'Keelaryn__Manager_Update/payload/legacy/A.txt',
            'Keelaryn__Manager_Update/payload/LEGACY/a.TXT'
        )){
            $entry=$caseArchive.CreateEntry($name,[System.IO.Compression.CompressionLevel]::NoCompression)
            $writer=New-Object System.IO.StreamWriter($entry.Open(),(New-Object System.Text.UTF8Encoding($false)))
            try{$writer.Write($name)}finally{$writer.Dispose()}
        }
    }finally{$caseArchive.Dispose()}
    $caseArchive=[System.IO.Compression.ZipFile]::OpenRead($caseDuplicateZip)
    try{
        $caseRejected=$false
        try{$null=Get-UniqueZipEntryIndex $caseArchive}catch{
            $caseRejected=$true
            Write-Host('  PASS reject update-zip-case-duplicate-key: '+$_.Exception.Message)
        }
        if(-not$caseRejected){throw 'UPDATE ZIP case-equivalent duplicate entry keys were accepted.'}
    }finally{$caseArchive.Dispose()}

    $unicodeDuplicateZip=Join-Path $script:tempRoot 'update-duplicate-unicode-key.zip'
    $unicodeArchive=[System.IO.Compression.ZipFile]::Open($unicodeDuplicateZip,[System.IO.Compression.ZipArchiveMode]::Create)
    try{
        $composed='Keelaryn__Manager_Update/payload/caf'+[char]0x00E9+'.txt'
        $decomposed='Keelaryn__Manager_Update/payload/cafe'+[char]0x0301+'.txt'
        foreach($name in @($composed,$decomposed)){
            $entry=$unicodeArchive.CreateEntry($name,[System.IO.Compression.CompressionLevel]::NoCompression)
            $writer=New-Object System.IO.StreamWriter($entry.Open(),(New-Object System.Text.UTF8Encoding($false)))
            try{$writer.Write($name)}finally{$writer.Dispose()}
        }
    }finally{$unicodeArchive.Dispose()}
    $unicodeArchive=[System.IO.Compression.ZipFile]::OpenRead($unicodeDuplicateZip)
    try{
        $unicodeRejected=$false
        try{$null=Get-UniqueZipEntryIndex $unicodeArchive}catch{
            $unicodeRejected=$true
            Write-Host('  PASS reject update-zip-unicode-duplicate-key: '+$_.Exception.Message)
        }
        if(-not$unicodeRejected){throw 'UPDATE ZIP Unicode-normalization-equivalent duplicate entry keys were accepted.'}
    }finally{$unicodeArchive.Dispose()}

    $directoryDuplicateCases=@(
        [pscustomobject]@{
            Label='update-zip-directory-exact-duplicate-key'
            Names=@(
                'Keelaryn__Manager_Update/payload/legacy/',
                'Keelaryn__Manager_Update/payload/legacy/'
            )
        },
        [pscustomobject]@{
            Label='update-zip-directory-case-duplicate-key'
            Names=@(
                'Keelaryn__Manager_Update/payload/Legacy/',
                'Keelaryn__Manager_Update/payload/LEGACY/'
            )
        },
        [pscustomobject]@{
            Label='update-zip-directory-unicode-duplicate-key'
            Names=@(
                ('Keelaryn__Manager_Update/payload/caf'+[char]0x00E9+'/'),
                ('Keelaryn__Manager_Update/payload/cafe'+[char]0x0301+'/')
            )
        }
    )

    foreach($case in $directoryDuplicateCases){
        $zipPath=Join-Path $script:tempRoot ($case.Label+'.zip')
        $archive=[System.IO.Compression.ZipFile]::Open($zipPath,[System.IO.Compression.ZipArchiveMode]::Create)
        try{
            foreach($name in @($case.Names)){
                $null=$archive.CreateEntry([string]$name,[System.IO.Compression.CompressionLevel]::NoCompression)
            }
        }finally{$archive.Dispose()}
        $archive=[System.IO.Compression.ZipFile]::OpenRead($zipPath)
        try{
            $rejected=$false
            try{$null=Get-UniqueZipEntryIndex $archive}catch{
                $rejected=$true
                Write-Host('  PASS reject '+$case.Label+': '+$_.Exception.Message)
            }
            if(-not$rejected){throw('Duplicate explicit directory UPDATE ZIP keys were accepted: '+$case.Label)}
        }finally{$archive.Dispose()}
    }

    $rejectContract={
        param($Policy,[string]$Label)
        $rejected=$false
        try{$null=Get-UpdateTransportCompatibilityContract -FinalPaths $final -TransitionOnly $transition -ReleasePolicy $Policy}catch{$rejected=$true;Write-Host('  PASS reject '+$Label+': '+$_.Exception.Message)}
        if(-not$rejected){throw('Unsafe transition alias contract was accepted: '+$Label)}
    }
    &$rejectContract ([pscustomobject]@{transition_compatibility_aliases=@([pscustomobject]@{path='product/a.txt';source_path='product/b.txt'})}) 'final-path-collision'
    &$rejectContract ([pscustomobject]@{transition_compatibility_aliases=@([pscustomobject]@{path='legacy/a.txt';source_path='product/missing.txt'})}) 'missing-source'
    &$rejectContract ([pscustomobject]@{transition_compatibility_aliases=@([pscustomobject]@{path='legacy/a.txt';source_path='product/a.txt'},[pscustomobject]@{path='LEGACY/A.TXT';source_path='product/b.txt'})}) 'case-alias-duplicate'
    &$rejectContract ([pscustomobject]@{transition_compatibility_aliases=@([pscustomobject]@{path='../escape.txt';source_path='product/a.txt'})}) 'unsafe-path'

    Write-Host '[13/14] Full Gate Doctor transition-WARN contract...'
    $fullGateTemplate=Join-Path $frameworkRoot 'templates\Run-KeelarynManagerFullGate.ps1'
    $tokens=$null;$errors=$null
    $fullAst=[System.Management.Automation.Language.Parser]::ParseFile($fullGateTemplate,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne0){throw('FullGate template parser failure before Doctor-contract extraction: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    foreach($helperName in @('Test-IsPermittedTransitionDoctorWarning','Assert-DoctorGateResult','Normalize-DoctorFindingMessage','FindingSignature')){
        $helper=@($fullAst.FindAll({param($node)$node-is[System.Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq$helperName},$true))
        if($helper.Count-ne1){throw('Expected exactly one '+$helperName+' function in FullGate template; actual='+$helper.Count)}
        Invoke-Expression ([string]$helper[0].Extent.Text)
    }

    function New-DoctorFinding([string]$Severity,[string]$Code,[string]$Message){
        return [pscustomobject]@{Severity=$Severity;Code=$Code;Message=$Message}
    }
    function New-DoctorReportForTest([object[]]$Findings){
        $rows=@($Findings)
        return [pscustomobject]@{
            errors=@($rows|Where-Object{[string]$_.Severity-ceq'ERROR'}).Count
            warnings=@($rows|Where-Object{[string]$_.Severity-ceq'WARN'}).Count
            findings=$rows
        }
    }
    function Assert-DoctorContractRejected([string]$Label,[int]$ExitCode,$Report){
        $rejected=$false
        try{[void](Assert-DoctorGateResult ([pscustomobject]@{ExitCode=$ExitCode}) $Report)}
        catch{$rejected=$true;Write-Host('  PASS reject '+$Label+': '+$_.Exception.Message)}
        if(-not$rejected){throw('Doctor gate contract accepted unsafe case: '+$Label)}
    }

    $healthy=New-DoctorReportForTest @(
        (New-DoctorFinding 'OK' 'hub.state' 'healthy')
    )
    if([bool](Assert-DoctorGateResult ([pscustomobject]@{ExitCode=0}) $healthy)){throw 'Healthy Doctor was classified as transition warning.'}

    $missing=New-DoctorReportForTest @(
        (New-DoctorFinding 'OK' 'hub.state' 'healthy'),
        (New-DoctorFinding 'WARN' 'governance.status' 'Hub governance receipt is missing. Chat Manager reconciliation required; Manager will not overwrite Hub governance automatically.')
    )
    if(-not[bool](Assert-DoctorGateResult ([pscustomobject]@{ExitCode=2}) $missing)){throw 'Missing governance receipt transition WARN was not accepted.'}

    $stale=New-DoctorReportForTest @(
        (New-DoctorFinding 'WARN' 'governance.status' 'Hub governance r1 is older than Manager r2. Chat Manager reconciliation required; Manager will not overwrite Hub governance automatically.')
    )
    if(-not[bool](Assert-DoctorGateResult ([pscustomobject]@{ExitCode=2}) $stale)){throw 'Stale governance transition WARN was not accepted.'}

    Assert-DoctorContractRejected 'governance-newer' 2 (New-DoctorReportForTest @(
        (New-DoctorFinding 'WARN' 'governance.status' 'Hub governance r3 is newer than Manager r2. Update/review Manager compatibility before reconciliation; Manager will not downgrade Hub governance.')
    ))
    Assert-DoctorContractRejected 'governance-contract-mismatch' 2 (New-DoctorReportForTest @(
        (New-DoctorFinding 'WARN' 'governance.status' 'Hub governance revision matches Manager but the adopted Workspace/managed-path contract differs. Chat Manager reconciliation required; Manager will not overwrite Hub governance automatically.')
    ))
    Assert-DoctorContractRejected 'governance-invalid' 2 (New-DoctorReportForTest @(
        (New-DoctorFinding 'WARN' 'governance.status' 'Hub governance receipt is unsafe. Chat Manager reconciliation required; Manager will not overwrite Hub governance automatically.')
    ))
    Assert-DoctorContractRejected 'unrelated-warning' 2 (New-DoctorReportForTest @(
        (New-DoctorFinding 'WARN' 'inbox.manager_invalid' 'invalid update package')
    ))
    Assert-DoctorContractRejected 'doctor-error' 1 (New-DoctorReportForTest @(
        (New-DoctorFinding 'ERROR' 'hub.manifest' 'drift')
    ))
    Assert-DoctorContractRejected 'exit-zero-with-warning' 0 $missing

    $baselineSigReport=New-DoctorReportForTest @(
        (New-DoctorFinding 'OK' 'hub.state' 'same')
    )
    $candidateSigReport=New-DoctorReportForTest @(
        (New-DoctorFinding 'OK' 'hub.state' 'same'),
        (New-DoctorFinding 'WARN' 'governance.status' 'Hub governance receipt is missing. Chat Manager reconciliation required; Manager will not overwrite Hub governance automatically.')
    )
    if((FindingSignature $baselineSigReport)-ceq(FindingSignature $candidateSigReport)){throw 'Raw Doctor signature unexpectedly ignored governance.status.'}
    if((FindingSignature $baselineSigReport -IgnoreGovernanceStatus)-cne(FindingSignature $candidateSigReport -IgnoreGovernanceStatus)){throw 'Governance-aware cross-version Doctor signature still differs.'}
    Write-Host '  PASS targeted Doctor transition-WARN and cross-version signature contract'

    Write-Host '[14/14] Full Gate transient CURRENT ZIP sharing-retry contract...'
    $fullGateTemplate=Join-Path $frameworkRoot 'templates\Run-KeelarynManagerFullGate.ps1'
    $fullGateText=[System.IO.File]::ReadAllText($fullGateTemplate,[System.Text.Encoding]::UTF8)
    foreach($token in @(
        'function Open-ZipWithSharingRetry',
        'function Open-ZipReadWithSharingRetry',
        'keelaryn_framework_r20_zip_retry_',
        'Start-Job -ScriptBlock',
        'Open-ZipUpdateWithSharingRetry $stateCurrent 120 250',
        'Open-ZipReadWithSharingRetry $stateCurrent 120 250',
        'Gate Framework r20 ZIP delayed-sharing-retry self-test: PASS'
    )){
        if(-not$fullGateText.Contains($token)){throw('Framework r20 Full Gate sharing-retry binding missing token: '+$token)}
    }
    Write-Host '  PASS delayed-unlock retry + E4 bounded read/write retry binding'

    Write-Host 'FRAMEWORK r20 SELFTEST: PASS' -ForegroundColor Green
}finally{if(Test-Path -LiteralPath $script:tempRoot){Remove-Item -LiteralPath $script:tempRoot -Recurse -Force -ErrorAction SilentlyContinue}}
