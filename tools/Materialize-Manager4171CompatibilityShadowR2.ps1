param([Parameter(Mandatory=$true)][string]$RuntimePath)
$ErrorActionPreference='Stop'
function Replace-Exact([string]$Text,[string]$Old,[string]$New,[string]$Label){
    $a=$Text.IndexOf($Old,[System.StringComparison]::Ordinal);if($a-lt0){throw('Missing anchor: '+$Label)}
    $b=$Text.IndexOf($Old,$a+$Old.Length,[System.StringComparison]::Ordinal);if($b-ge0){throw('Non-unique anchor: '+$Label)}
    return $Text.Substring(0,$a)+$New+$Text.Substring($a+$Old.Length)
}
$path=[IO.Path]::GetFullPath($RuntimePath)
$text=[IO.File]::ReadAllText($path,[Text.Encoding]::UTF8).Replace("`r`n","`n")
if($text.Contains('function Get-CompatibilityCheckpointIdentityFast')){Write-Host 'r2 already materialized.';exit 0}
$old=@'
function Get-CompatibilityShadowAssessment($Row) {
    try{
        if($null-eq$Row){throw 'Active registry row is missing.'}
        $paths=Get-InstanceStatePaths ([string]$Row.instance_id)
        if(-not(Test-Path -LiteralPath $paths.Current -PathType Leaf)){throw('Active per-instance CURRENT is missing: '+$paths.Current)}
        if(-not(Test-Path -LiteralPath $script:LegacySingleInstanceCurrentZip -PathType Leaf)){throw('Legacy compatibility CURRENT is missing: '+$script:LegacySingleInstanceCurrentZip)}
        foreach($path in @($paths.Current,$script:LegacySingleInstanceCurrentZip)){
            $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop
            if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw('Compatibility CURRENT path is unsafe: '+$path)}
        }
        $binding=Get-CompatibilityBindingAssessment $Row
        if(-not$binding.Valid){throw $binding.Reason}
        $perHash=(Get-FileHash -LiteralPath $paths.Current -Algorithm SHA256).Hash.ToLowerInvariant()
        $legacyHash=(Get-FileHash -LiteralPath $script:LegacySingleInstanceCurrentZip -Algorithm SHA256).Hash.ToLowerInvariant()
        if($perHash-ne$legacyHash){throw('Legacy compatibility CURRENT bytes differ from active per-instance CURRENT; per='+$perHash.Substring(0,12)+' legacy='+$legacyHash.Substring(0,12)+'.')}
        return [pscustomobject]@{Valid=$true;Reason='Legacy CURRENT + binding coherently shadow the active per-instance CURRENT.';FileSha256=$perHash}
    }catch{return [pscustomobject]@{Valid=$false;Reason=$_.Exception.Message;FileSha256=$null}}
}
'@
$new=@'
function Get-CompatibilityCheckpointIdentityFast([string]$ZipPath) {
    $archive=$null
    try{
        if(-not(Test-Path -LiteralPath $ZipPath -PathType Leaf)){throw('CURRENT is missing: '+$ZipPath)}
        $item=Get-Item -LiteralPath $ZipPath -Force -ErrorAction Stop
        if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0-or[long]$item.Length-gt$MaxHubZipBytes){throw('CURRENT path is unsafe or oversized: '+$ZipPath)}
        $archive=[System.IO.Compression.ZipFile]::OpenRead($item.FullName)
        $root='Keelaryn__Hub/'
        $envelope=Test-ZipEnvelopeArchive $archive ([long]$item.Length) $MaxHubZipBytes $MaxHubExpandedBytes $MaxHubEntries $root
        if(-not$envelope.Valid){
            $root=[string]$LegacyCoreCompat.HubZipRoot
            $envelope=Test-ZipEnvelopeArchive $archive ([long]$item.Length) $MaxHubZipBytes $MaxHubExpandedBytes $MaxHubEntries $root
        }
        if(-not$envelope.Valid){throw('CURRENT ZIP envelope is invalid: '+$envelope.Reason)}
        $stateEntry=$archive.Entries|Where-Object{$_.FullName.Replace('\','/')-eq($root+'_System/STATE.md')}|Select-Object -First 1
        $artifactEntry=$archive.Entries|Where-Object{$_.FullName.Replace('\','/')-eq($root+'_System/ARTIFACT.json')}|Select-Object -First 1
        if(-not$stateEntry-or-not$artifactEntry){throw 'CURRENT STATE/ARTIFACT metadata is missing.'}
        $state=Read-StateText (Read-ZipEntryText $stateEntry)
        $artifact=Parse-ArtifactManifestText (Read-ZipEntryText $artifactEntry)
        if(-not$state-or-not$artifact){throw 'CURRENT STATE/ARTIFACT metadata is invalid.'}
        $instanceId=$null
        if($state.InstanceSchema){
            $instanceEntry=$archive.Entries|Where-Object{$_.FullName.Replace('\','/')-eq($root+'_System/INSTANCE.json')}|Select-Object -First 1
            if(-not$instanceEntry){throw 'CURRENT INSTANCE metadata is missing.'}
            $instance=Parse-InstanceManifestText (Read-ZipEntryText $instanceEntry)
            if(-not$instance-or[string]$instance.Schema-ne[string]$state.InstanceSchema){throw 'CURRENT INSTANCE metadata is invalid.'}
            $instanceId=[string]$instance.InstanceId
        }
        if([string]$artifact.InstanceId-ne[string]$instanceId){throw 'CURRENT STATE/INSTANCE and ARTIFACT instance identities differ.'}
        if([string]$artifact.VersionText-ne[string]$state.VersionText-or[int]$artifact.Revision-ne[int]$state.Revision){throw 'CURRENT STATE and ARTIFACT version/revision identities differ.'}
        return [pscustomobject]@{InstanceId=$instanceId;ArtifactId=[string]$artifact.ArtifactId;ArtifactStatus=[string]$artifact.Status;VersionText=[string]$state.VersionText;Revision=[int]$state.Revision}
    }finally{if($archive){$archive.Dispose()}}
}

function Get-CompatibilityShadowAssessment($Row) {
    try{
        if($null-eq$Row){throw 'Active registry row is missing.'}
        $paths=Get-InstanceStatePaths ([string]$Row.instance_id)
        if(-not(Test-Path -LiteralPath $paths.Current -PathType Leaf)){throw('Active per-instance CURRENT is missing: '+$paths.Current)}
        if(-not(Test-Path -LiteralPath $script:LegacySingleInstanceCurrentZip -PathType Leaf)){throw('Legacy compatibility CURRENT is missing: '+$script:LegacySingleInstanceCurrentZip)}
        foreach($path in @($paths.Current,$script:LegacySingleInstanceCurrentZip)){
            $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop
            if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw('Compatibility CURRENT path is unsafe: '+$path)}
        }
        $binding=Get-CompatibilityBindingAssessment $Row
        if(-not$binding.Valid){throw $binding.Reason}
        $perHash=(Get-FileHash -LiteralPath $paths.Current -Algorithm SHA256).Hash.ToLowerInvariant()
        $legacyHash=(Get-FileHash -LiteralPath $script:LegacySingleInstanceCurrentZip -Algorithm SHA256).Hash.ToLowerInvariant()
        if($perHash-ne$legacyHash){throw('Legacy compatibility CURRENT bytes differ from active per-instance CURRENT; per='+$perHash.Substring(0,12)+' legacy='+$legacyHash.Substring(0,12)+'.')}

        # Fast-path identity proof deliberately reads only archive envelope + STATE/INSTANCE/ARTIFACT.
        # It must not invoke full portable payload/source-manifest hashing on every Manager startup.
        $zipIdentity=Get-CompatibilityCheckpointIdentityFast $paths.Current
        $vaultState=Read-VaultStateCoreAt ([string]$Row.vault_path)
        $vaultArtifact=Read-VaultArtifactManifestAt ([string]$Row.vault_path)
        if(-not$zipIdentity-or-not$vaultState-or-not$vaultArtifact){throw 'Active compatibility checkpoint identity metadata is incomplete.'}
        if([string]$zipIdentity.ArtifactStatus-ne'approved'){throw 'Active compatibility CURRENT is not an approved checkpoint.'}
        if([string]$zipIdentity.InstanceId-ne[string]$Row.instance_id-or[string]$vaultState.InstanceId-ne[string]$Row.instance_id-or[string]$vaultArtifact.InstanceId-ne[string]$Row.instance_id){throw 'Compatibility shadow does not belong to the active instance_id.'}
        if([string]$zipIdentity.ArtifactId-ne[string]$vaultArtifact.ArtifactId){throw 'Compatibility shadow artifact_id differs from the installed active Hub.'}
        if([string]$zipIdentity.VersionText-ne[string]$vaultState.VersionText-or[int]$zipIdentity.Revision-ne[int]$vaultState.Revision){throw 'Compatibility shadow version/revision differs from the installed active Hub.'}
        return [pscustomobject]@{Valid=$true;Reason='Legacy CURRENT + binding coherently shadow the active per-instance CURRENT.';FileSha256=$perHash}
    }catch{return [pscustomobject]@{Valid=$false;Reason=$_.Exception.Message;FileSha256=$null}}
}
'@
$text=Replace-Exact $text $old $new 'compatibility shadow fast path'
$token="foreach(`$token in @('function Get-CompatibilityShadowAssessment'"
$text=Replace-Exact $text $token "foreach(`$token in @('function Get-CompatibilityCheckpointIdentityFast','function Get-CompatibilityShadowAssessment'" 'product source token'
$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
if(@($errors).Count){throw('Parser failure: '+(@($errors|ForEach-Object{$_.Message})-join'; '))}
foreach($required in @('function Get-CompatibilityCheckpointIdentityFast','Compatibility shadow does not belong to the active instance_id.','Fast-path identity proof deliberately reads only archive envelope')){if(-not$text.Contains($required)){throw('Missing r2 token: '+$required)}}
[IO.File]::WriteAllText($path,$text,(New-Object Text.UTF8Encoding($false)))
Write-Host 'Compatibility-shadow r2 materialized: PASS'
