[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Replace-Function([string]$Source,[string]$Path,[string]$Name,[string]$Replacement){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseInput($Source,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){Fail('Parser failed before replacing '+$Name+': '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $rows=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name})
    if($rows.Count-ne1){Fail('Expected exactly one function '+$Name+' in '+$Path+'; actual='+$rows.Count)}
    $node=$rows[0]
    return $Source.Substring(0,$node.Extent.StartOffset)+$Replacement+$Source.Substring($node.Extent.EndOffset)
}
function Write-Text([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)}

$menuPath=Join-Path $RepositoryRoot 'manager\product\tools\KeelarynMenu.ps1'
$reg3Path=Join-Path $RepositoryRoot 'tools\Invoke-Manager4173ReviewRegression.ps1'
$reg12Path=Join-Path $RepositoryRoot 'tools\Invoke-Manager41712ReviewRegression.ps1'
foreach($p in @($menuPath,$reg3Path,$reg12Path)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Required source missing: '+$p)}}

$menu=[IO.File]::ReadAllText($menuPath,[Text.Encoding]::UTF8)
if(-not$menu.Contains('Add-Type -AssemblyName System.IO.Compression.FileSystem')){
    $anchor="$ErrorActionPreference='Stop'"
    $replacement="$ErrorActionPreference='Stop'`r`nAdd-Type -AssemblyName System.IO.Compression`r`nAdd-Type -AssemblyName System.IO.Compression.FileSystem"
    $first=$menu.IndexOf($anchor,[StringComparison]::Ordinal)
    if($first-lt0-or$menu.IndexOf($anchor,$first+$anchor.Length,[StringComparison]::Ordinal)-ge0){Fail 'Frontend ErrorActionPreference anchor is not uniquely patchable.'}
    $menu=$menu.Substring(0,$first)+$replacement+$menu.Substring($first+$anchor.Length)
}

$newCurrentFunctions=@'
function Read-FrontendZipEntryJson($Entry,[string]$Label) {
    if($null-eq$Entry){Fail($Label+' entry is missing.')}
    if([long]$Entry.Length-lt1-or[long]$Entry.Length-gt4MB){Fail($Label+' entry size is invalid.')}
    $stream=$null;$reader=$null
    try{
        $stream=$Entry.Open()
        $reader=New-Object IO.StreamReader($stream,[Text.Encoding]::UTF8,$true,4096,$false)
        $text=$reader.ReadToEnd()
        if([Text.Encoding]::UTF8.GetByteCount($text)-gt4MB){Fail($Label+' entry exceeds the 4 MiB metadata limit.')}
        try{return ($text|ConvertFrom-Json)}catch{Fail($Label+' JSON is invalid: '+$_.Exception.Message)}
    }finally{
        if($reader){$reader.Dispose()}elseif($stream){$stream.Dispose()}
    }
}

function Assert-FrontendCurrentArchiveBinding($Archive,[string]$ExpectedInstanceId) {
    $expected=ConvertTo-CanonicalFrontendInstanceId $ExpectedInstanceId
    $entries=@($Archive.Entries)
    if($entries.Count-lt1-or$entries.Count-gt10000){Fail('CURRENT archive entry count is outside the 1..10000 safety range.')}
    [long]$expanded=0
    $seen=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $names=New-Object System.Collections.ArrayList
    foreach($entry in $entries){
        $name=([string]$entry.FullName).Replace('\','/')
        if([string]::IsNullOrWhiteSpace($name)-or$name.StartsWith('/')-or$name-match'(^|/)\.\.?(/|$)'-or$name.Contains(':')){Fail('CURRENT archive contains an unsafe path: '+$name)}
        if(-not$seen.Add($name)){Fail('CURRENT archive contains a duplicate path: '+$name)}
        $expanded+=[long]$entry.Length
        if($expanded-gt250MB){Fail 'CURRENT archive expanded-size safety limit exceeded.'}
        if([long]$entry.Length-gt0){
            $compressed=[Math]::Max([long]$entry.CompressedLength,1)
            if(([double]$entry.Length/[double]$compressed)-gt200.0){Fail('CURRENT archive compression-ratio safety limit exceeded: '+$name)}
        }
        [void]$names.Add($name)
    }

    $root=$null
    foreach($candidateRoot in @('Keelaryn__Hub/','Core__Hub/')){
        $outside=@($names|Where-Object{-not([string]$_).StartsWith($candidateRoot,[StringComparison]::OrdinalIgnoreCase)})
        $instance=@($entries|Where-Object{([string]$_.FullName).Replace('\','/').Equals($candidateRoot+'_System/INSTANCE.json',[StringComparison]::OrdinalIgnoreCase)})
        $artifact=@($entries|Where-Object{([string]$_.FullName).Replace('\','/').Equals($candidateRoot+'_System/ARTIFACT.json',[StringComparison]::OrdinalIgnoreCase)})
        if($outside.Count-eq0-and$instance.Count-eq1-and$artifact.Count-eq1){
            if($root){Fail 'CURRENT archive root is ambiguous.'}
            $root=$candidateRoot;$instanceEntry=$instance[0];$artifactEntry=$artifact[0]
        }
    }
    if(-not$root){Fail 'CURRENT archive does not have a supported Hub envelope with INSTANCE/ARTIFACT metadata.'}

    $instance=Read-FrontendZipEntryJson $instanceEntry 'CURRENT INSTANCE'
    $artifact=Read-FrontendZipEntryJson $artifactEntry 'CURRENT ARTIFACT'
    $instanceSchema=([string]$instance.schema).Trim()
    if(@('keelaryn.instance.v1','corehub.instance.v1')-cnotcontains$instanceSchema){Fail('CURRENT INSTANCE schema is unsupported: '+$instanceSchema)}
    $artifactSchema=([string]$artifact.schema).Trim()
    if(@('keelaryn.artifact.v3','corehub.artifact.v3')-cnotcontains$artifactSchema){Fail('CURRENT ARTIFACT schema is unsupported for instance-bound export: '+$artifactSchema)}
    if(([string]$artifact.artifact_status).Trim().ToLowerInvariant()-cne'approved'){Fail 'CURRENT ARTIFACT is not an approved checkpoint.'}
    $instanceId=ConvertTo-CanonicalFrontendInstanceId $instance.instance_id
    $artifactInstanceId=ConvertTo-CanonicalFrontendInstanceId $artifact.instance_id
    if($instanceId-cne$artifactInstanceId){Fail('CURRENT INSTANCE/ARTIFACT identities differ: instance='+$instanceId+' artifact='+$artifactInstanceId)}
    if($instanceId-cne$expected){Fail('CURRENT belongs to a different instance_id. expected='+$expected+' actual='+$instanceId)}
    return [pscustomobject]@{InstanceId=$instanceId;ArtifactId=([string]$artifact.artifact_id).Trim();Status='approved';Root=$root}
}

function Get-CurrentHubTransportPath($Context=$null) {
    $ctx=if($null-eq$Context){Get-RequiredFrontendInstanceContext}else{$Context}
    if($ctx.RegistryActive-and-not$ctx.InstanceId){Fail 'Multi-Hub registry exists but the supplied instance context is unresolved. CURRENT preparation refused.'}
    $path=[string]$ctx.CurrentZip
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){return $null}
    $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('CURRENT transport must not be a reparse point: '+$path)}
    if($item.Length-gt50MB){Fail('CURRENT transport exceeds the 50 MiB Hub transport safety limit: '+$path)}
    return $item.FullName
}
'@.Replace("`n","`r`n")
$menu=Replace-Function $menu $menuPath 'Get-CurrentHubTransportPath' $newCurrentFunctions

$newCopy=@'
function Copy-CurrentForChatGPT($Context,[string]$DestinationName) {
    if($null-eq$Context){Fail 'Captured instance context is required for ChatGPT CURRENT preparation.'}
    if([string]::IsNullOrWhiteSpace($DestinationName)-or$DestinationName.Contains('\')-or$DestinationName.Contains('/')){Fail 'ChatGPT CURRENT destination name is invalid.'}
    $exchangeRoot=[string]$Context.ExchangeRoot
    if([string]::IsNullOrWhiteSpace($exchangeRoot)){Fail 'Captured instance context has no exchange root.'}
    Ensure-ChatGPTExchangeLayout $Context
    $DestinationDirectory=Join-Path $exchangeRoot $DestinationName
    Ensure-DirectorySafe $DestinationDirectory 'ChatGPT CURRENT destination'
    $source=Get-CurrentHubTransportPath $Context
    if([string]::IsNullOrWhiteSpace($source)){
        Write-UiHost 'No Manager CURRENT transport is available. Run Doctor and explicit CURRENT repair first.' -ForegroundColor Yellow
        Set-ActionSemantic 'failed'
        return 1
    }
    $target=Join-Path $DestinationDirectory 'Keelaryn__Hub_CURRENT.zip'
    if(Test-Path -LiteralPath $target){
        $item=Get-Item -LiteralPath $target -Force -ErrorAction Stop
        if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Unsafe ChatGPT CURRENT destination: '+$target)}
    }
    $tmp=$target+'.tmp-'+[guid]::NewGuid().ToString('N')
    $backup=$target+'.replace-backup-'+[guid]::NewGuid().ToString('N')
    $sourceStream=$null;$archive=$null;$targetStream=$null
    try{
        # Hold the exact CURRENT bytes read-locked from identity proof through byte copy.
        # This prevents a switch/repair/external replacement from changing the artifact after validation.
        $sourceStream=New-Object IO.FileStream($source,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
        if([bool]$Context.RegistryActive){
            if([string]::IsNullOrWhiteSpace([string]$Context.InstanceId)){Fail 'Instance-bound CURRENT export requires a captured instance_id.'}
            $archive=New-Object IO.Compression.ZipArchive($sourceStream,[IO.Compression.ZipArchiveMode]::Read,$true)
            $null=Assert-FrontendCurrentArchiveBinding $archive ([string]$Context.InstanceId)
            $archive.Dispose();$archive=$null
        }

        $sourceStream.Position=0
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$sourceHash=([BitConverter]::ToString($sha.ComputeHash($sourceStream))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        $sourceStream.Position=0
        $targetStream=New-Object IO.FileStream($tmp,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        $sourceStream.CopyTo($targetStream)
        $targetStream.Flush($true)
        $targetStream.Dispose();$targetStream=$null
        $tmpHash=Get-FileSha256Hex $tmp
        if($sourceHash-cne$tmpHash){Fail 'Prepared CURRENT failed locked-source SHA-256 verification.'}

        if(Test-Path -LiteralPath $target -PathType Leaf){
            [IO.File]::Replace($tmp,$target,$backup,$true)
            if(Test-Path -LiteralPath $backup){Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue}
        }else{
            [IO.File]::Move($tmp,$target)
        }
        $publishedHash=Get-FileSha256Hex $target
        if($publishedHash-cne$sourceHash){Fail 'Prepared CURRENT durable publication succeeded, but post-publication SHA-256 verification failed.'}
        Write-UiHost ('Prepared CURRENT: '+$target) -ForegroundColor Green
        return 0
    }finally{
        if($archive){$archive.Dispose()}
        if($targetStream){$targetStream.Dispose()}
        if($sourceStream){$sourceStream.Dispose()}
        if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}
        if(Test-Path -LiteralPath $backup){Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue}
    }
}
'@.Replace("`n","`r`n")
$menu=Replace-Function $menu $menuPath 'Copy-CurrentForChatGPT' $newCopy
Write-Text $menuPath $menu

# Strengthen the historical captured-context regression fixture so it is a real identity-bound CURRENT ZIP.
$reg3=[IO.File]::ReadAllText($reg3Path,[Text.Encoding]::UTF8)
if(-not$reg3.Contains('function New-IdentityBoundCurrentZip')){
    $anchor="function Get-Sha256([string]`$Path){return (Get-FileHash -LiteralPath `$Path -Algorithm SHA256).Hash.ToLowerInvariant()}"
    $helper=@'
function New-IdentityBoundCurrentZip([string]$Path,[string]$InstanceId,[string]$ArtifactInstanceId=$null,[string]$Status='approved'){
    if(-not$ArtifactInstanceId){$ArtifactInstanceId=$InstanceId}
    if(Test-Path -LiteralPath $Path){Remove-Item -LiteralPath $Path -Force}
    $parent=Split-Path -Parent $Path;if(-not(Test-Path -LiteralPath $parent)){[void][IO.Directory]::CreateDirectory($parent)}
    $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try{
        $archive=New-Object IO.Compression.ZipArchive($stream,[IO.Compression.ZipArchiveMode]::Create,$true)
        try{
            foreach($row in @(
                [pscustomobject]@{Name='Keelaryn__Hub/_System/INSTANCE.json';Text=(([ordered]@{schema='keelaryn.instance.v1';instance_id=$InstanceId;created='2026-09-14T00:00:00Z'}|ConvertTo-Json -Compress))},
                [pscustomobject]@{Name='Keelaryn__Hub/_System/ARTIFACT.json';Text=(([ordered]@{schema='keelaryn.artifact.v3';artifact_status=$Status;artifact_id='appr-regression-current';instance_id=$ArtifactInstanceId}|ConvertTo-Json -Compress))},
                [pscustomobject]@{Name='Keelaryn__Hub/README.md';Text='identity-bound regression current'}
            )){
                $entry=$archive.CreateEntry($row.Name,[IO.Compression.CompressionLevel]::Optimal)
                $writer=New-Object IO.StreamWriter($entry.Open(),$Utf8NoBom)
                try{$writer.Write([string]$row.Text)}finally{$writer.Dispose()}
            }
        }finally{$archive.Dispose()}
    }finally{$stream.Dispose()}
}
'@
    $replacement=$anchor+"`r`n"+$helper.Replace("`n","`r`n")
    $first=$reg3.IndexOf($anchor,[StringComparison]::Ordinal)
    if($first-lt0-or$reg3.IndexOf($anchor,$first+$anchor.Length,[StringComparison]::Ordinal)-ge0){Fail '4.17.3 regression helper insertion anchor is not unique.'}
    $reg3=$reg3.Substring(0,$first)+$replacement+$reg3.Substring($first+$anchor.Length)
}
$oldImports="Invoke-Expression (Get-FunctionText `$menuPath 'Ensure-ChatGPTExchangeLayout')`r`nInvoke-Expression (Get-FunctionText `$menuPath 'Get-CurrentHubTransportPath')`r`nInvoke-Expression (Get-FunctionText `$menuPath 'Copy-CurrentForChatGPT')"
$newImports="Invoke-Expression (Get-FunctionText `$menuPath 'Ensure-ChatGPTExchangeLayout')`r`nInvoke-Expression (Get-FunctionText `$menuPath 'ConvertTo-CanonicalFrontendInstanceId')`r`nInvoke-Expression (Get-FunctionText `$menuPath 'Read-FrontendZipEntryJson')`r`nInvoke-Expression (Get-FunctionText `$menuPath 'Assert-FrontendCurrentArchiveBinding')`r`nInvoke-Expression (Get-FunctionText `$menuPath 'Get-CurrentHubTransportPath')`r`nInvoke-Expression (Get-FunctionText `$menuPath 'Copy-CurrentForChatGPT')"
if($reg3.Contains($oldImports)){$reg3=$reg3.Replace($oldImports,$newImports)}elseif(-not$reg3.Contains("Get-FunctionText `$menuPath 'Assert-FrontendCurrentArchiveBinding'")){Fail '4.17.3 regression function-import block is not patchable.'}
if(-not$reg3.Contains('function Fail([string]$Message)')){
    $assertAnchor='function Assert([bool]$Condition,[string]$Message){if(-not$Condition){throw $Message}}'
    $reg3=$reg3.Replace($assertAnchor,"function Fail([string]`$Message){throw `$Message}`r`n"+$assertAnchor)
}
$plain="    [IO.File]::WriteAllText(`$aCurrent,'instance-a-current',(New-Object Text.UTF8Encoding(`$false)))"
$zipLine="    New-IdentityBoundCurrentZip `$aCurrent `$aId"
if($reg3.Contains($plain)){$reg3=$reg3.Replace($plain,$zipLine)}elseif(-not$reg3.Contains($zipLine.Trim())){Fail '4.17.3 CURRENT fixture line is not patchable.'}
$successMarker="    Write-Host '  PASS ChatGPT CURRENT source/destination stay on one captured instance context'"
if(-not$reg3.Contains('wrong-instance CURRENT export was not rejected')){
    $negative=@'

    # Regression A2: a captured context must reject a CURRENT whose embedded identity belongs to another instance.
    $preparedHash=Get-Sha256 $prepared
    $bId='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
    New-IdentityBoundCurrentZip $aCurrent $bId
    $blocked=$false
    try{$null=Copy-CurrentForChatGPT $ctxA 'workspace-input'}catch{$blocked=$true}
    Assert $blocked 'Instance A context accepted a CURRENT bound to instance B.'
    Assert ((Get-Sha256 $prepared)-ceq$preparedHash) 'Rejected wrong-instance CURRENT export modified the previously prepared exchange artifact.'

    New-IdentityBoundCurrentZip $aCurrent $aId $bId
    $blocked=$false
    try{$null=Copy-CurrentForChatGPT $ctxA 'workspace-input'}catch{$blocked=$true}
    Assert $blocked 'CURRENT with mismatched INSTANCE/ARTIFACT identities was not rejected.'
    Assert ((Get-Sha256 $prepared)-ceq$preparedHash) 'Rejected mixed-identity CURRENT modified the previously prepared exchange artifact.'

    New-IdentityBoundCurrentZip $aCurrent $aId $aId 'candidate'
    $blocked=$false
    try{$null=Copy-CurrentForChatGPT $ctxA 'workspace-input'}catch{$blocked=$true}
    Assert $blocked 'CANDIDATE CURRENT was accepted for ChatGPT exchange preparation.'
    Assert ((Get-Sha256 $prepared)-ceq$preparedHash) 'Rejected non-approved CURRENT modified the previously prepared exchange artifact.'
    Write-Host '  PASS wrong-instance, mixed-identity and non-approved CURRENT exports fail closed without changing exchange bytes'
'@.Replace("`n","`r`n")
    $reg3=$reg3.Replace($successMarker,$successMarker+$negative)
}
Write-Text $reg3Path $reg3

# Pin the new binding proof in the 4.17.12 review contract.
$reg12=[IO.File]::ReadAllText($reg12Path,[Text.Encoding]::UTF8)
if(-not$reg12.Contains('CURRENT export identity binding')){
    $marker="Write-Host '  PASS SURFACE Manage Hubs recovery is target-driven while unrelated active-context actions stay fail-closed'"
    $insert=@'

$copyCurrentText=Get-FunctionText $menuPath 'Copy-CurrentForChatGPT'
Assert ($copyCurrentText.Contains('Assert-FrontendCurrentArchiveBinding $archive ([string]$Context.InstanceId)')) 'ChatGPT CURRENT export does not validate embedded instance identity against captured context.'
Assert ($copyCurrentText.Contains('[IO.FileShare]::Read')) 'ChatGPT CURRENT export does not hold a read lock from identity validation through byte copy.'
Assert ($menu.Contains('function Assert-FrontendCurrentArchiveBinding')) 'Frontend CURRENT identity-binding validator is missing.'
Assert ($menu.Contains("CURRENT belongs to a different instance_id")) 'Frontend CURRENT wrong-instance failure contract is missing.'
Write-Host '  PASS CURRENT export identity binding is enforced under a locked source artifact'
'@.Replace("`n","`r`n")
    if(-not$reg12.Contains($marker)){Fail '4.17.12 regression surface marker is missing.'}
    $reg12=$reg12.Replace($marker,$marker+$insert)
}
Write-Text $reg12Path $reg12

foreach($path in @($menuPath,$reg3Path,$reg12Path)){
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){Fail('Parser failed after pre-freeze CURRENT binding fix in '+$path+': '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
}

Write-Host 'Manager 4.17.12 pre-freeze CURRENT binding materialization: PASS' -ForegroundColor Green
