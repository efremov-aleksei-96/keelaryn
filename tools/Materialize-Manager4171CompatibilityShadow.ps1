param(
    [Parameter(Mandatory=$true)][string]$RuntimePath
)

$ErrorActionPreference='Stop'

function Replace-Exact([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    $first=$Text.IndexOf($Old,[System.StringComparison]::Ordinal)
    if($first-lt0){throw("Materializer anchor missing: "+$Label)}
    $second=$Text.IndexOf($Old,$first+$Old.Length,[System.StringComparison]::Ordinal)
    if($second-ge0){throw("Materializer anchor is not unique: "+$Label)}
    return $Text.Substring(0,$first)+$New+$Text.Substring($first+$Old.Length)
}

$path=[System.IO.Path]::GetFullPath($RuntimePath)
$text=[System.IO.File]::ReadAllText($path,[System.Text.Encoding]::UTF8).Replace("`r`n","`n")
if($text.Contains('function Invoke-ReconcileActiveCompatibilityShadow')){
    Write-Host 'Compatibility-shadow correction is already materialized.'
    exit 0
}

$oldBinding=@'
function Write-ManagerBindingDocument([string]$Path,$Object) {
    $json=$Object|ConvertTo-Json -Depth 5
    $encoding=New-Object System.Text.UTF8Encoding($false)
    Invoke-WithExistingHiddenFileWritable $Path { [System.IO.File]::WriteAllText($Path,$json,$encoding) }|Out-Null
    Set-ManagerMutablePresentationHidden $Path
}
'@
$newBinding=@'
function Write-ManagerBindingDocument([string]$Path,$Object) {
    $json=$Object|ConvertTo-Json -Depth 5
    $encoding=New-Object System.Text.UTF8Encoding($false)
    $parent=Split-Path -Parent $Path
    if($parent -and -not (Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    $tmp=$Path+'.tmp.'+[guid]::NewGuid().ToString('N')
    $backup=$Path+'.replace-backup.'+[guid]::NewGuid().ToString('N')
    try{
        [System.IO.File]::WriteAllText($tmp,$json,$encoding)
        if(Test-Path -LiteralPath $Path -PathType Leaf){
            Invoke-WithExistingHiddenFileWritable $Path { [System.IO.File]::Replace($tmp,$Path,$backup,$true) }|Out-Null
            if(Test-Path -LiteralPath $backup){Remove-Item -LiteralPath $backup -Force}
        }else{
            [System.IO.File]::Move($tmp,$Path)
        }
        Set-ManagerMutablePresentationHidden $Path
    }catch{
        if((-not(Test-Path -LiteralPath $Path -PathType Leaf))-and(Test-Path -LiteralPath $backup -PathType Leaf)){Move-Item -LiteralPath $backup -Destination $Path -Force}
        throw
    }finally{
        if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}
        if(Test-Path -LiteralPath $backup){Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue}
    }
}
'@
$text=Replace-Exact $text $oldBinding $newBinding 'atomic binding writer'

$helperMarker='function Assert-InstanceBindingAvailable {'
$helpers=@'
function Get-CompatibilityBindingAssessment($Row) {
    try{
        if($null-eq$Row){throw 'Active registry row is missing.'}
        if(-not(Test-Path -LiteralPath $BindingFile -PathType Leaf)){throw 'Compatibility binding is missing.'}
        $item=Get-Item -LiteralPath $BindingFile -Force -ErrorAction Stop
        if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0-or$item.Length-gt4MB){throw 'Compatibility binding is unsafe.'}
        $binding=Read-KeelarynJsonFile $BindingFile
        if([string]$binding.schema-ne'keelaryn.manager.instance-binding.v2'){throw 'Compatibility binding schema is not v2.'}
        $id=([string]$binding.instance_id).Trim().ToLowerInvariant()
        if($id-ne[string]$Row.instance_id){throw('Compatibility binding instance_id differs from active registry instance: '+$id)}
        $stored=([string]$binding.vault_path).Trim()
        if(-not$stored-or-not[System.IO.Path]::IsPathRooted($stored)){throw 'Compatibility binding vault_path is missing or not absolute.'}
        $expected=[System.IO.Path]::GetFullPath([string]$Row.vault_path).TrimEnd('\')
        if((Get-KeelarynNormalizedPathKey $stored)-ne(Get-KeelarynNormalizedPathKey $expected)){throw('Compatibility binding vault_path differs from active registry path: '+$stored)}
        $leaf=([string]$binding.vault_directory_name).Trim()
        if($leaf-ne[System.IO.Path]::GetFileName($expected)){throw 'Compatibility binding vault_directory_name differs from the active registry path.'}
        return [pscustomobject]@{Valid=$true;Reason='Compatibility binding identifies the active registry instance.'}
    }catch{return [pscustomobject]@{Valid=$false;Reason=$_.Exception.Message}}
}

function Get-RegisteredVaultCheckpointIdentity($Row) {
    $path=Assert-RegisteredVaultStructuralSafetyEarly ([string]$Row.vault_path)
    if(-not(& $TestHubCandidate $path)){throw('Registered active Hub is invalid: '+$path)}
    $state=Read-VaultStateCoreAt $path
    $artifact=Read-VaultArtifactManifestAt $path
    if(-not$state-or-not$artifact){throw 'Registered active Hub identity metadata is incomplete.'}
    if([string]$state.InstanceId-ne[string]$Row.instance_id-or[string]$artifact.InstanceId-ne[string]$Row.instance_id){throw 'Registered active Hub instance identity mismatch.'}
    $analysis=Get-PortableVaultAnalysis $path
    if([string]$artifact.PayloadHash-ne[string]$analysis.PayloadHash){throw 'Registered active Hub ARTIFACT payload hash differs from portable payload.'}
    return [pscustomobject]@{
        InstanceId=[string]$Row.instance_id
        ArtifactId=[string]$artifact.ArtifactId
        VersionText=[string]$state.VersionText
        Revision=[int]$state.Revision
        ContentHash=[string]$analysis.ContentHash
        PayloadHash=[string]$analysis.PayloadHash
    }
}

function Get-CurrentCompatibilityAssessment([string]$ZipPath,$Row,$VaultIdentity) {
    $session=$null
    try{
        if(-not(Test-Path -LiteralPath $ZipPath -PathType Leaf)){throw('CURRENT is missing: '+$ZipPath)}
        $item=Get-Item -LiteralPath $ZipPath -Force -ErrorAction Stop
        if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw('CURRENT path is unsafe: '+$ZipPath)}
        $session=Open-HubZipInspectionSession $ZipPath
        if(-not$session){throw('CURRENT ZIP is invalid: '+$ZipPath)}
        if($session.ContainsLocalDeploymentState){throw('CURRENT ZIP contains local deployment state: '+$ZipPath)}
        $state=Read-ZipState $ZipPath $session
        $artifact=Read-ZipArtifactManifest $ZipPath $session
        if(-not$state-or-not$artifact){throw('CURRENT metadata validation failed: '+$ZipPath)}
        if([string]$artifact.Status-ne'approved'){throw('CURRENT ARTIFACT is not approved: '+$ZipPath)}
        if([string]$state.InstanceId-ne[string]$Row.instance_id-or[string]$artifact.InstanceId-ne[string]$Row.instance_id){throw('CURRENT belongs to another instance_id: '+$ZipPath)}
        if([string]$artifact.ArtifactId-ne[string]$VaultIdentity.ArtifactId){throw('CURRENT artifact_id differs from installed active Hub: '+$ZipPath)}
        if([string]$state.VersionText-ne[string]$VaultIdentity.VersionText-or[int]$state.Revision-ne[int]$VaultIdentity.Revision){throw('CURRENT version/revision differs from installed active Hub: '+$ZipPath)}
        $hash=Get-ZipHashPair $ZipPath $session
        if([string]$hash.ContentHash-ne[string]$VaultIdentity.ContentHash-or[string]$hash.PayloadHash-ne[string]$VaultIdentity.PayloadHash){throw('CURRENT portable content differs from installed active Hub: '+$ZipPath)}
        return [pscustomobject]@{Valid=$true;Reason='CURRENT exactly represents the installed active Hub.';FileSha256=(Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()}
    }catch{return [pscustomobject]@{Valid=$false;Reason=$_.Exception.Message;FileSha256=$null}}
    finally{if($session){Close-HubZipInspectionSession $session}}
}

function Publish-ExactManagerStateFile([string]$SourcePath,[string]$DestinationPath,[string]$Purpose) {
    $source=[System.IO.Path]::GetFullPath($SourcePath)
    $destination=[System.IO.Path]::GetFullPath($DestinationPath)
    if($source-eq$destination){return (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()}
    $item=Get-Item -LiteralPath $source -Force -ErrorAction Stop
    if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw($Purpose+': source is unsafe: '+$source)}
    $parent=Split-Path -Parent $destination
    if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    $tmp=$destination+'.tmp.'+[guid]::NewGuid().ToString('N')
    try{
        $before=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
        Copy-Item -LiteralPath $source -Destination $tmp -Force
        $copied=(Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash.ToLowerInvariant()
        $after=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
        if($before-ne$copied-or$before-ne$after){throw($Purpose+': source changed while compatibility bytes were staged.')}
        Publish-CompletedFileAtomically $tmp $destination
        $published=(Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
        if($published-ne$before){throw($Purpose+': published bytes failed SHA-256 verification.')}
        Set-ManagerMutablePresentationHidden $destination
        return $before
    }finally{if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}}
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
        return [pscustomobject]@{Valid=$true;Reason='Legacy CURRENT + binding coherently shadow the active per-instance CURRENT.';FileSha256=$perHash}
    }catch{return [pscustomobject]@{Valid=$false;Reason=$_.Exception.Message;FileSha256=$null}}
}

function Publish-CompatibilityShadowFromRegisteredInstance($Row,[string]$Source) {
    if($null-eq$Row){throw 'Cannot publish compatibility shadow without a registry row.'}
    $null=Assert-RegisteredInstanceBaseline $Row
    $paths=Get-InstanceStatePaths ([string]$Row.instance_id)
    $null=Publish-ExactManagerStateFile $paths.Current $script:LegacySingleInstanceCurrentZip 'Compatibility CURRENT publication'
    & $WriteBindingV2 ([string]$Row.vault_path) ([string]$Row.instance_id) $Source
    $check=Get-CompatibilityShadowAssessment $Row
    if(-not$check.Valid){throw('Compatibility shadow post-publication verification failed: '+$check.Reason)}
    return $check
}

function Invoke-ReconcileActiveCompatibilityShadow {
    if(-not$script:InstanceRegistryActive){return 'single-instance'}
    $row=Get-ManagerActiveInstance
    $fast=Get-CompatibilityShadowAssessment $row
    if($fast.Valid){return 'coherent'}

    $identity=Get-RegisteredVaultCheckpointIdentity $row
    $paths=Get-InstanceStatePaths ([string]$row.instance_id)
    $per=Get-CurrentCompatibilityAssessment $paths.Current $row $identity
    $legacy=Get-CurrentCompatibilityAssessment $script:LegacySingleInstanceCurrentZip $row $identity

    if($per.Valid){
        $null=Publish-ExactManagerStateFile $paths.Current $script:LegacySingleInstanceCurrentZip 'Compatibility shadow reconciliation'
        & $WriteBindingV2 ([string]$row.vault_path) ([string]$row.instance_id) 'multi_hub_shadow_reconciled_from_instance'
        $check=Get-CompatibilityShadowAssessment $row
        if(-not$check.Valid){throw('Compatibility shadow reconciliation verification failed: '+$check.Reason)}
        Log ('Reconciled legacy compatibility shadow from authoritative active per-instance CURRENT; instance_id='+[string]$row.instance_id)
        return 'repaired_from_instance'
    }

    if($legacy.Valid){
        $null=Publish-ExactManagerStateFile $script:LegacySingleInstanceCurrentZip $paths.Current 'Per-instance CURRENT safe adoption'
        $null=Assert-RegisteredInstanceBaseline $row
        & $WriteBindingV2 ([string]$row.vault_path) ([string]$row.instance_id) 'multi_hub_shadow_adopted_to_instance'
        $check=Get-CompatibilityShadowAssessment $row
        if(-not$check.Valid){throw('Safe legacy CURRENT adoption verification failed: '+$check.Reason)}
        Log ('Safely adopted legacy compatibility CURRENT into stale active per-instance CURRENT; instance_id='+[string]$row.instance_id)
        return 'adopted_legacy_to_instance'
    }

    throw('Ambiguous multi-Hub compatibility shadow; refusing reconciliation. Active instance_id='+[string]$row.instance_id+'; per-instance CURRENT: '+$per.Reason+'; legacy CURRENT: '+$legacy.Reason)
}

'@
$text=Replace-Exact $text $helperMarker ($helpers+$helperMarker) 'compatibility-shadow helper insertion'

$oldRegistry=@'
        Write-ManagerInstanceRegistry $registry
        Write-ManagerActiveInstance $id
        & $WriteBindingV2 $Vault $id 'multi_hub_registry_bootstrap'
        $null=Resolve-RegisteredInstanceContextEarly
'@
$newRegistry=@'
        $bootstrapRow=[pscustomobject]@{instance_id=$id;name=$name;vault_path=[System.IO.Path]::GetFullPath($Vault).TrimEnd('\');registered_utc=$registered}
        $null=Publish-CompatibilityShadowFromRegisteredInstance $bootstrapRow 'multi_hub_registry_bootstrap'
        $null=Assert-RegisteredInstanceBaseline $bootstrapRow
        Write-ManagerActiveInstance $id
        # instances.json is the bootstrap activation marker. Before it exists, older/single-instance Managers already see a coherent compatibility pair.
        Write-ManagerInstanceRegistry $registry
        $null=Resolve-RegisteredInstanceContextEarly
'@
$text=Replace-Exact $text $oldRegistry $newRegistry 'registry bootstrap commit order'

$oldSwitch=@'
function Invoke-SwitchRegisteredInstance([string]$InstanceId) {
    $registry=Get-ManagerInstanceRegistry
    $id=([string]$InstanceId).Trim().ToLowerInvariant()
    $matches=@($registry.instances|Where-Object{[string]$_.instance_id-eq$id})
    if($matches.Count-ne1){throw('Unknown registered instance_id: '+$id)}
    $row=$matches[0]
    $null=Assert-RegisteredInstanceBaseline $row
    Write-ManagerActiveInstance $id
    & $WriteBindingV2 ([string]$row.vault_path) $id 'multi_hub_switch'
    $null=Resolve-RegisteredInstanceContextEarly
    $script:InvocationInstanceId=$id
    Write-Host ('Active Hub switched to: '+[string]$row.name) -ForegroundColor Green
    Write-Host ('instance_id: '+$id)
    Write-Host ('path: '+[string]$row.vault_path)
    return 0
}
'@
$newSwitch=@'
function Invoke-SwitchRegisteredInstance([string]$InstanceId) {
    $registry=Get-ManagerInstanceRegistry
    $id=([string]$InstanceId).Trim().ToLowerInvariant()
    $matches=@($registry.instances|Where-Object{[string]$_.instance_id-eq$id})
    if($matches.Count-ne1){throw('Unknown registered instance_id: '+$id)}
    $row=$matches[0]
    $previous=Get-ManagerActiveInstance
    if([string]$previous.instance_id-eq$id){
        $null=Publish-CompatibilityShadowFromRegisteredInstance $row 'multi_hub_switch_same_instance'
        Write-Host ('Active Hub is already: '+[string]$row.name) -ForegroundColor Green
        return 0
    }

    $committed=$false
    try{
        $null=Assert-RegisteredInstanceBaseline $row
        $null=Publish-CompatibilityShadowFromRegisteredInstance $row 'multi_hub_switch_prepare'
        # Fresh transaction-boundary validation immediately before the commit marker.
        $null=Assert-RegisteredInstanceBaseline $row
        Write-ManagerActiveInstance $id
        $committed=$true
    }catch{
        $primary=$_.Exception.Message
        if(-not$committed){
            try{
                $activeNow=Read-ActiveInstanceEarly
                if([string]$activeNow.instance_id-eq[string]$previous.instance_id){$null=Publish-CompatibilityShadowFromRegisteredInstance $previous 'multi_hub_switch_rollback'}
                elseif([string]$activeNow.instance_id-eq$id){$committed=$true}
            }catch{
                throw('Active Hub switch failed before confirmed commit and compatibility rollback also failed. Primary: '+$primary+' Rollback: '+$_.Exception.Message)
            }
        }
        if(-not$committed){throw('Active Hub switch failed before commit; previous active instance remains selected. '+$primary)}
    }

    try{
        $null=Resolve-RegisteredInstanceContextEarly
        $script:InvocationInstanceId=$id
        $check=Get-CompatibilityShadowAssessment $row
        if(-not$check.Valid){throw $check.Reason}
    }catch{
        throw('Active Hub switch durable commit succeeded, but post-commit verification failed: '+$_.Exception.Message)
    }
    Write-Host ('Active Hub switched to: '+[string]$row.name) -ForegroundColor Green
    Write-Host ('instance_id: '+$id)
    Write-Host ('path: '+[string]$row.vault_path)
    return 0
}
'@
$text=Replace-Exact $text $oldSwitch $newSwitch 'crash-safe active instance switch'

$sanitizeAnchor="        Log 'Repacked Keelaryn__Hub_CURRENT.zip without local deployment state; canonical payload identity unchanged.'"
$sanitizeNew=@'
        Log 'Repacked Keelaryn__Hub_CURRENT.zip without local deployment state; canonical payload identity unchanged.'
        if($script:InstanceRegistryActive){
            try{$null=Publish-CompatibilityShadowFromRegisteredInstance (Get-ManagerActiveInstance) 'current_transport_sanitized'}
            catch{throw('CURRENT sanitation durable commit succeeded, but compatibility shadow synchronization failed: '+$_.Exception.Message)}
        }
'@
$text=Replace-Exact $text $sanitizeAnchor $sanitizeNew 'sanitized CURRENT shadow sync'

$installAnchor=@'
        catch {
            if (Test-Path $currentNew) { Remove-Item $currentNew -Force -ErrorAction SilentlyContinue }
            if (Test-Path $Vault) { Remove-Item $Vault -Recurse -Force -ErrorAction SilentlyContinue }
            if ($backupCreated -and (Test-Path $backup)) { Move-Item -Path $backup -Destination $Vault }
            throw
        }

        try { Remove-Item $Package.File.FullName -Force -ErrorAction SilentlyContinue } catch {}
'@
$installNew=@'
        catch {
            if (Test-Path $currentNew) { Remove-Item $currentNew -Force -ErrorAction SilentlyContinue }
            if (Test-Path $Vault) { Remove-Item $Vault -Recurse -Force -ErrorAction SilentlyContinue }
            if ($backupCreated -and (Test-Path $backup)) { Move-Item -Path $backup -Destination $Vault }
            throw
        }

        # Hub + per-instance CURRENT are durably coherent here. Shadow synchronization is post-commit and must never roll that transaction back.
        if($script:InstanceRegistryActive){
            try{$null=Publish-CompatibilityShadowFromRegisteredInstance (Get-ManagerActiveInstance) 'hub_update_post_commit'}
            catch{throw('Hub update durable commit succeeded, but compatibility shadow synchronization failed: '+$_.Exception.Message)}
        }

        try { Remove-Item $Package.File.FullName -Force -ErrorAction SilentlyContinue } catch {}
'@
$text=Replace-Exact $text $installAnchor $installNew 'Hub update post-commit shadow sync'

$doctorAnchor=@'
            Add-DoctorFinding $rows 'OK' 'instances.registry' ('Multi-Hub registry valid; instances='+@($instanceRegistry.instances).Count+'.')
            Add-DoctorFinding $rows 'OK' 'instances.active' ('Active='+[string]$activeInstance.name+'; instance_id='+[string]$activeInstance.instance_id+'.')
'@
$doctorNew=@'
            Add-DoctorFinding $rows 'OK' 'instances.registry' ('Multi-Hub registry valid; instances='+@($instanceRegistry.instances).Count+'.')
            Add-DoctorFinding $rows 'OK' 'instances.active' ('Active='+[string]$activeInstance.name+'; instance_id='+[string]$activeInstance.instance_id+'.')
            $shadow=Get-CompatibilityShadowAssessment $activeInstance
            if($shadow.Valid){Add-DoctorFinding $rows 'OK' 'compatibility.shadow' ('Legacy downgrade compatibility shadow matches active instance; zip='+$shadow.FileSha256.Substring(0,12)+'.')}
            else{Add-DoctorFinding $rows 'ERROR' 'compatibility.shadow' $shadow.Reason}
'@
$text=Replace-Exact $text $doctorAnchor $doctorNew 'Doctor compatibility-shadow invariant'

$productToken="foreach(`$token in @('function Invoke-GenesisRegisteredInstance'"
$productNew="foreach(`$token in @('function Get-CompatibilityShadowAssessment','function Invoke-ReconcileActiveCompatibilityShadow','function Publish-CompatibilityShadowFromRegisteredInstance','function Invoke-GenesisRegisteredInstance'"
$text=Replace-Exact $text $productToken $productNew 'managed product source tokens'

$startupAnchor=@'
# Update commands never perform transport repair implicitly. Use the Maintenance repair action explicitly.

Log ("Start. ManagerRoot={0}; Vault={1}; OpenOnly={2}; UpdateManager={3}; UpdateHub={4}; UpdateAll={5}; Genesis={6}; BuildDistribution={7}; InstanceInfo={8}; CheckMigrations={9}; AdoptInstanceIdentity={10}; ApplyMigrations={11}; MigrateLegacyNamespace={12}; MigrateLayout={13}; FinalizeLayout={14}; Doctor={15}; BuildRelease={16}; BuildAIContext={17}; RepairCurrentTransport={18}; PrepareTests={19}; BuildCandidateTransport={20}; RestoreCandidateTransport={21}; InitializePresentation={22}; FinalizeFilesystemLayout={23}; BindInstance={24}" -f $Root,$Vault,$OpenOnly,$UpdateManager,$UpdateHub,$UpdateAll,$Genesis,$BuildDistribution,$InstanceInfo,$CheckMigrations,$AdoptInstanceIdentity,$ApplyMigrations,$MigrateLegacyNamespace,$MigrateLayout,$FinalizeLayout,$Doctor,$BuildRelease,$BuildAIContext,$RepairCurrentTransport,$PrepareTests,$BuildCandidateTransport,$RestoreCandidateTransport,$InitializePresentation,$FinalizeFilesystemLayout,[bool]$BindInstancePath)
'@
$startupNew=@'
# Update commands never perform transport repair implicitly. Use the Maintenance repair action explicitly.
# Multi-Hub compatibility shadow reconciliation is Manager-state recovery, not a Hub transport repair.
if($script:InstanceRegistryActive -and -not$Doctor){
    Acquire-ManagerLock
    try{$null=Invoke-ReconcileActiveCompatibilityShadow}
    finally{Release-ManagerLock}
}

Log ("Start. ManagerRoot={0}; Vault={1}; OpenOnly={2}; UpdateManager={3}; UpdateHub={4}; UpdateAll={5}; Genesis={6}; BuildDistribution={7}; InstanceInfo={8}; CheckMigrations={9}; AdoptInstanceIdentity={10}; ApplyMigrations={11}; MigrateLegacyNamespace={12}; MigrateLayout={13}; FinalizeLayout={14}; Doctor={15}; BuildRelease={16}; BuildAIContext={17}; RepairCurrentTransport={18}; PrepareTests={19}; BuildCandidateTransport={20}; RestoreCandidateTransport={21}; InitializePresentation={22}; FinalizeFilesystemLayout={23}; BindInstance={24}" -f $Root,$Vault,$OpenOnly,$UpdateManager,$UpdateHub,$UpdateAll,$Genesis,$BuildDistribution,$InstanceInfo,$CheckMigrations,$AdoptInstanceIdentity,$ApplyMigrations,$MigrateLegacyNamespace,$MigrateLayout,$FinalizeLayout,$Doctor,$BuildRelease,$BuildAIContext,$RepairCurrentTransport,$PrepareTests,$BuildCandidateTransport,$RestoreCandidateTransport,$InitializePresentation,$FinalizeFilesystemLayout,[bool]$BindInstancePath)
'@
$text=Replace-Exact $text $startupAnchor $startupNew 'startup compatibility reconciliation'

$tokens=$null;$errors=$null
[void][System.Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
if(@($errors).Count-ne0){throw('Materialized runtime parser failure: '+(@($errors|ForEach-Object{$_.Message})-join'; '))}
foreach($required in @(
    'function Invoke-ReconcileActiveCompatibilityShadow',
    'function Get-CompatibilityShadowAssessment',
    'function Publish-CompatibilityShadowFromRegisteredInstance',
    "'compatibility.shadow'",
    "'multi_hub_switch_prepare'",
    "'multi_hub_shadow_adopted_to_instance'",
    'Hub update durable commit succeeded, but compatibility shadow synchronization failed:'
)){
    if(-not$text.Contains($required)){throw('Materialized runtime missing contract token: '+$required)}
}
$utf8=New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($path,$text,$utf8)
Write-Host 'Compatibility-shadow correction materialized and parser-valid.'
