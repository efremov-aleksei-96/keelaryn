[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$runtime=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$Utf8NoBom=New-Object Text.UTF8Encoding($false)
$expectedBaseSha='6011b605e6574f31987f916a6b00b537a7402a1d9b4b5971007bf9f486f89f55'

function Fail([string]$Message){throw $Message}
function Require-One([string]$Text,[string]$Needle,[string]$Label){
    $count=[regex]::Matches($Text,[regex]::Escape($Needle)).Count
    if($count-ne1){Fail($Label+' anchor count='+$count)}
}
function Assert-Parse([string]$Path){
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){Fail('Patched runtime parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
}

if(-not(Test-Path -LiteralPath $runtime -PathType Leaf)){Fail('Runtime missing: '+$runtime)}
$baseSha=(Get-FileHash -LiteralPath $runtime -Algorithm SHA256).Hash.ToLowerInvariant()
if($baseSha-cne$expectedBaseSha){Fail('Unexpected runtime base SHA-256. expected='+$expectedBaseSha+' actual='+$baseSha)}
$text=[IO.File]::ReadAllText($runtime,[Text.Encoding]::UTF8)
if($text.Contains('keelaryn.manager.hub-input-reconciliation-claim.v1')){Fail 'Claim-first reconciliation is already present; proof patch refuses a second application.'}

$rootAnchor="$script:InstancesStateRoot=Join-Path `$StateRoot 'instances'"
Require-One $text $rootAnchor 'claim-root'
$text=$text.Replace($rootAnchor,$rootAnchor+"`r`n`$script:HubInputReconciliationRoot=Join-Path `$StateRoot 'reconciliation\hub-inputs'")

$start='function Assert-NoStrandedGlobalHubInputs([string]$Operation=''Hub operation'') {'
$end='function Invoke-ListInstances {'
$startIndex=$text.IndexOf($start,[StringComparison]::Ordinal)
$endIndex=$text.IndexOf($end,[StringComparison]::Ordinal)
if($startIndex-lt0-or$endIndex-le$startIndex){Fail 'Could not locate stranded-input reconciliation replacement range.'}
if($text.IndexOf($start,$startIndex+1,[StringComparison]::Ordinal)-ge0){Fail 'Stranded-input reconciliation start anchor is duplicated.'}
if($text.IndexOf($end,$endIndex+1,[StringComparison]::Ordinal)-ge0){Fail 'Invoke-ListInstances anchor is duplicated.'}

$newBlock=@'
function Write-HubInputReconciliationClaimMetadata([string]$ClaimDirectory,$Metadata) {
    if([string]::IsNullOrWhiteSpace($ClaimDirectory)-or$null-eq$Metadata){throw 'Hub-input reconciliation claim metadata write is invalid.'}
    if(-not(Test-Path -LiteralPath $ClaimDirectory -PathType Container)){throw('Hub-input reconciliation claim directory is missing: '+$ClaimDirectory)}
    $claimItem=Get-Item -LiteralPath $ClaimDirectory -Force -ErrorAction Stop
    if(-not$claimItem.PSIsContainer-or($claimItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Hub-input reconciliation claim directory is unsafe: '+$ClaimDirectory)}
    $metadataPath=Join-Path $ClaimDirectory 'claim.json'
    $prepared=Join-Path $ClaimDirectory ('claim.json.prepared.'+[guid]::NewGuid().ToString('N'))
    try{
        $json=(($Metadata|ConvertTo-Json -Depth 12).Replace("`r`n","`n"))+"`n"
        [IO.File]::WriteAllText($prepared,$json,(New-Object Text.UTF8Encoding($false)))
        Publish-CompletedFileAtomically $prepared $metadataPath
    }finally{if(Test-Path -LiteralPath $prepared){Remove-Item -LiteralPath $prepared -Force -ErrorAction SilentlyContinue}}
}

function Read-HubInputReconciliationClaim([string]$ClaimDirectory) {
    $claimItem=Get-Item -LiteralPath $ClaimDirectory -Force -ErrorAction Stop
    if(-not$claimItem.PSIsContainer-or($claimItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Hub-input reconciliation claim directory is unsafe: '+$ClaimDirectory)}
    $metadataPath=Join-Path $ClaimDirectory 'claim.json'
    if(-not(Test-Path -LiteralPath $metadataPath -PathType Leaf)){throw('Hub-input reconciliation claim metadata is missing: '+$ClaimDirectory)}
    $metadataItem=Get-Item -LiteralPath $metadataPath -Force -ErrorAction Stop
    if(($metadataItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Hub-input reconciliation claim metadata is unsafe: '+$metadataPath)}
    try{$doc=Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8|ConvertFrom-Json}catch{throw('Hub-input reconciliation claim metadata is invalid: '+$metadataPath+'; '+$_.Exception.Message)}
    if([string]$doc.schema-cne'keelaryn.manager.hub-input-reconciliation-claim.v1'){throw('Unsupported Hub-input reconciliation claim schema: '+[string]$doc.schema)}
    $claimGuid=[guid]::Empty
    if(-not[guid]::TryParse(([string]$doc.claim_id).Trim(),[ref]$claimGuid)-or$claimGuid-eq[guid]::Empty){throw('Hub-input reconciliation claim_id is invalid: '+[string]$doc.claim_id)}
    if($claimGuid.ToString('N')-cne[IO.Path]::GetFileName($ClaimDirectory)){throw('Hub-input reconciliation claim directory/id mismatch: '+$ClaimDirectory)}
    $name=([string]$doc.original_name).Trim()
    if([string]::IsNullOrWhiteSpace($name)-or[IO.Path]::GetFileName($name)-cne$name){throw('Hub-input reconciliation original_name is invalid: '+$name)}
    $kind=([string]$doc.kind).Trim()
    if(@('hub_zip','candidate_transport')-cnotcontains$kind){throw('Hub-input reconciliation kind is invalid: '+$kind)}
    $state=([string]$doc.state).Trim()
    if(@('claiming','claimed','publish_prepared')-cnotcontains$state){throw('Hub-input reconciliation state is invalid: '+$state)}
    $payload=Join-Path (Join-Path $ClaimDirectory 'payload') $name
    return [pscustomobject]@{Directory=$ClaimDirectory;MetadataPath=$metadataPath;Metadata=$doc;Payload=$payload;OriginalName=$name;Kind=$kind}
}

function Get-HubInputReconciliationClaims {
    $rows=New-Object System.Collections.ArrayList
    if(-not(Test-Path -LiteralPath $script:HubInputReconciliationRoot)){return @($rows)}
    $root=Get-Item -LiteralPath $script:HubInputReconciliationRoot -Force -ErrorAction Stop
    if(-not$root.PSIsContainer-or($root.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Hub-input reconciliation root is unsafe: '+$script:HubInputReconciliationRoot)}
    foreach($dir in @(Get-ChildItem -LiteralPath $script:HubInputReconciliationRoot -Directory -Force -ErrorAction Stop|Sort-Object Name)){
        if(($dir.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Hub-input reconciliation claim is a reparse point: '+$dir.FullName)}
        [void]$rows.Add((Read-HubInputReconciliationClaim $dir.FullName))
    }
    return @($rows)
}

function Remove-VerifiedHubInputReconciliationClaim([string]$ClaimDirectory) {
    $full=[IO.Path]::GetFullPath($ClaimDirectory).TrimEnd('\')
    $root=[IO.Path]::GetFullPath($script:HubInputReconciliationRoot).TrimEnd('\')
    if(-not$full.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){throw('Refusing to retire reconciliation claim outside claim root: '+$full)}
    $item=Get-Item -LiteralPath $full -Force -ErrorAction Stop
    if(-not$item.PSIsContainer-or($item.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Refusing to retire unsafe reconciliation claim: '+$full)}
    Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
}

function New-HubInputReconciliationClaim($Descriptor) {
    if($null-eq$Descriptor-or$null-eq$Descriptor.File){throw 'Cannot claim invalid global Hub-input descriptor.'}
    if(-not(Test-Path -LiteralPath $script:HubInputReconciliationRoot -PathType Container)){New-Item -ItemType Directory -Force -Path $script:HubInputReconciliationRoot|Out-Null}
    $root=Get-Item -LiteralPath $script:HubInputReconciliationRoot -Force -ErrorAction Stop
    if(-not$root.PSIsContainer-or($root.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Hub-input reconciliation root is unsafe: '+$script:HubInputReconciliationRoot)}
    $source=[IO.Path]::GetFullPath([string]$Descriptor.File.FullName)
    $sourceItem=Get-Item -LiteralPath $source -Force -ErrorAction Stop
    if($sourceItem.PSIsContainer-or($sourceItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Global Hub input became unsafe before claim: '+$source)}
    $name=[string]$sourceItem.Name;$kind=[string]$Descriptor.Kind
    $id=[guid]::NewGuid().ToString('N');$claimDirectory=Join-Path $script:HubInputReconciliationRoot $id;$payloadDirectory=Join-Path $claimDirectory 'payload';$payload=Join-Path $payloadDirectory $name
    [IO.Directory]::CreateDirectory($payloadDirectory)|Out-Null
    if(([IO.Path]::GetPathRoot($source))-ine([IO.Path]::GetPathRoot($payload))){throw('Hub-input reconciliation claim must remain on the Manager state volume: '+$source+' -> '+$payload)}
    $meta=[ordered]@{schema='keelaryn.manager.hub-input-reconciliation-claim.v1';claim_id=$id;original_name=$name;kind=$kind;state='claiming';source_path=$source;sha256='';instance_id='';destination='';target_vault_path='';created_utc=(Get-Date).ToUniversalTime().ToString('o');updated_utc=(Get-Date).ToUniversalTime().ToString('o')}
    try{
        Write-HubInputReconciliationClaimMetadata $claimDirectory $meta
        if(Test-Path -LiteralPath $payload){throw('Hub-input reconciliation payload destination is unexpectedly occupied: '+$payload)}
        [IO.File]::Move($source,$payload)
    }catch{
        if(-not(Test-Path -LiteralPath $payload)-and(Test-Path -LiteralPath $source -PathType Leaf)){
            Remove-Item -LiteralPath $claimDirectory -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw
    }
    return Read-HubInputReconciliationClaim $claimDirectory
}

function Test-HubInputReconciliationDestinationExact($Claim,[string]$Destination,[string]$Sha256,[string]$InstanceId) {
    if(-not(Test-Path -LiteralPath $Destination -PathType Leaf)){return $false}
    $item=Get-Item -LiteralPath $Destination -Force -ErrorAction Stop
    if($item.PSIsContainer-or($item.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){return $false}
    if((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()-cne$Sha256){return $false}
    try{
        $identity=Get-GlobalHubInputIdentity ([pscustomobject]@{File=$item;Kind=[string]$Claim.Kind})
        return ([string]$identity.InstanceId-ceq$InstanceId-and[string]$identity.Sha256-ceq$Sha256)
    }catch{return $false}
}

function Resolve-HubInputReconciliationClaim($Claim) {
    $meta=$Claim.Metadata;$source=Join-Path $Inbox ([string]$Claim.OriginalName)
    if(-not(Test-Path -LiteralPath ([string]$Claim.Payload) -PathType Leaf)){
        $knownSha=([string]$meta.sha256).Trim().ToLowerInvariant();$knownId=([string]$meta.instance_id).Trim().ToLowerInvariant();$knownDestination=([string]$meta.destination).Trim()
        if($knownSha-and$knownId-and$knownDestination-and(Test-HubInputReconciliationDestinationExact $Claim $knownDestination $knownSha $knownId)){
            Remove-VerifiedHubInputReconciliationClaim ([string]$Claim.Directory)
            return 1
        }
        if([string]$meta.state-ceq'claiming'-and(Test-Path -LiteralPath $source -PathType Leaf)){
            $sourceItem=Get-Item -LiteralPath $source -Force -ErrorAction Stop
            if($sourceItem.PSIsContainer-or($sourceItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Prepared reconciliation claim source is unsafe: '+$source)}
            Remove-VerifiedHubInputReconciliationClaim ([string]$Claim.Directory)
            return 0
        }
        throw('Hub-input reconciliation claim payload is missing and durable outcome is ambiguous: '+[string]$Claim.Directory)
    }

    $payloadItem=Get-Item -LiteralPath ([string]$Claim.Payload) -Force -ErrorAction Stop
    if($payloadItem.PSIsContainer-or($payloadItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Hub-input reconciliation payload is unsafe: '+[string]$Claim.Payload)}
    $identity=Get-GlobalHubInputIdentity ([pscustomobject]@{File=$payloadItem;Kind=[string]$Claim.Kind})
    $meta.sha256=[string]$identity.Sha256;$meta.instance_id=[string]$identity.InstanceId;$meta.state='claimed';$meta.updated_utc=(Get-Date).ToUniversalTime().ToString('o')
    Write-HubInputReconciliationClaimMetadata ([string]$Claim.Directory) $meta

    $registry=Get-ManagerInstanceRegistry
    $matches=@($registry.instances|Where-Object{[string]$_.instance_id-ceq[string]$identity.InstanceId})
    if($matches.Count-ne1){throw('Claimed Hub input belongs to an unregistered/ambiguous instance_id: '+[string]$identity.InstanceId+' claim='+[string]$meta.claim_id)}
    $row=$matches[0]
    $null=Assert-RegisteredInstanceBaseline $row
    $paths=Get-InstanceStatePaths ([string]$identity.InstanceId)
    if(-not(Test-Path -LiteralPath $paths.Inbox -PathType Container)){throw('Registered instance inbox is missing for reconciliation claim: '+$paths.Inbox)}
    $destRoot=Get-Item -LiteralPath $paths.Inbox -Force -ErrorAction Stop
    if(-not$destRoot.PSIsContainer-or($destRoot.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Registered instance inbox is unsafe for reconciliation claim: '+$paths.Inbox)}
    $destination=Join-Path $destRoot.FullName ([string]$Claim.OriginalName)
    $meta.destination=$destination;$meta.target_vault_path=[string]$row.vault_path;$meta.state='publish_prepared';$meta.updated_utc=(Get-Date).ToUniversalTime().ToString('o')
    Write-HubInputReconciliationClaimMetadata ([string]$Claim.Directory) $meta

    if(Test-Path -LiteralPath $destination){
        if(-not(Test-HubInputReconciliationDestinationExact $Claim $destination ([string]$identity.Sha256) ([string]$identity.InstanceId))){throw('Hub-input reconciliation destination collision has different or unverifiable bytes: '+$destination)}
        Remove-VerifiedHubInputReconciliationClaim ([string]$Claim.Directory)
        return 1
    }

    # Fresh commit-boundary validation: authoritative registry row/path, exact claimed payload, and destination vacancy.
    $freshRegistry=Get-ManagerInstanceRegistry;$freshMatches=@($freshRegistry.instances|Where-Object{[string]$_.instance_id-ceq[string]$identity.InstanceId})
    if($freshMatches.Count-ne1){throw('Reconciliation target changed or became ambiguous before publication: '+[string]$identity.InstanceId)}
    $freshRow=$freshMatches[0]
    if([IO.Path]::GetFullPath([string]$freshRow.vault_path).TrimEnd('\')-ine[IO.Path]::GetFullPath([string]$row.vault_path).TrimEnd('\')){throw('Reconciliation target path changed before publication for instance_id '+[string]$identity.InstanceId)}
    $null=Assert-RegisteredInstanceBaseline $freshRow
    $freshPayload=Get-Item -LiteralPath ([string]$Claim.Payload) -Force -ErrorAction Stop
    if($freshPayload.PSIsContainer-or($freshPayload.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Reconciliation claim payload became unsafe at commit boundary: '+[string]$Claim.Payload)}
    $freshIdentity=Get-GlobalHubInputIdentity ([pscustomobject]@{File=$freshPayload;Kind=[string]$Claim.Kind})
    if([string]$freshIdentity.InstanceId-cne[string]$identity.InstanceId-or[string]$freshIdentity.Sha256-cne[string]$identity.Sha256){throw('Reconciliation claim identity changed at commit boundary: '+[string]$Claim.Payload)}
    if(Test-Path -LiteralPath $destination){throw('Hub-input reconciliation destination became occupied at commit boundary: '+$destination)}

    $committed=$false
    try{
        [IO.File]::Move([string]$Claim.Payload,$destination);$committed=$true
        Set-ManagerMutablePresentationHidden $destination
        if(-not(Test-HubInputReconciliationDestinationExact $Claim $destination ([string]$identity.Sha256) ([string]$identity.InstanceId)){throw('final exact destination verification failed: '+$destination)}
    }catch{
        if($committed){throw('Hub-input reconciliation destination committed, but post-commit verification failed; destination and claim metadata are preserved for deterministic recovery. destination='+$destination+'; '+$_.Exception.Message)}
        throw('Hub-input reconciliation failed before destination commit; durable claim is preserved. destination='+$destination+'; '+$_.Exception.Message)
    }
    try{Remove-VerifiedHubInputReconciliationClaim ([string]$Claim.Directory)}catch{throw('Hub-input reconciliation destination is verified and durable, but claim retirement failed; rerun initialization for idempotent recovery. destination='+$destination+'; '+$_.Exception.Message)}
    return 1
}

function Assert-NoStrandedGlobalHubInputs([string]$Operation='Hub operation') {
    if(-not(Test-Path -LiteralPath $script:InstanceRegistryFile -PathType Leaf)){return}
    $rows=@(Get-GlobalHubOwnedInboxObjects);$claims=@(Get-HubInputReconciliationClaims)
    if($rows.Count-ne0-or$claims.Count-ne0){
        $parts=New-Object System.Collections.ArrayList
        if($rows.Count-ne0){[void]$parts.Add($rows.Count.ToString()+' global Hub-owned object(s): '+([string]::Join(', ',@($rows|ForEach-Object{$_.File.Name}))))}
        if($claims.Count-ne0){[void]$parts.Add($claims.Count.ToString()+' durable reconciliation claim(s): '+([string]::Join(', ',@($claims|ForEach-Object{$_.Metadata.claim_id}))))}
        throw($Operation+' refused because unresolved Hub-input reconciliation state remains. Run Initialize instance registry to resume exact identity-bound reconciliation first. '+([string]::Join(' | ',@($parts))))
    }
}

function Reconcile-StrandedGlobalHubInputsForExistingRegistry {
    $completed=0
    foreach($claim in @(Get-HubInputReconciliationClaims)){$completed+=[int](Resolve-HubInputReconciliationClaim $claim)}
    foreach($input in @(Get-GlobalHubOwnedInboxObjects)){
        $claim=New-HubInputReconciliationClaim $input
        $completed+=[int](Resolve-HubInputReconciliationClaim $claim)
    }
    return $completed
}

'@
$text=$text.Substring(0,$startIndex)+$newBlock+$text.Substring($endIndex)

$doctorOld=@'
            $globalHubInputs=@(Get-GlobalHubOwnedInboxObjects)
            if($globalHubInputs.Count-gt0){Add-DoctorFinding $rows 'WARN' 'inbox.hub_global_stranded' ($globalHubInputs.Count.ToString()+' Hub-owned object(s) remain in the global Manager inbox and are outside normal per-instance Hub discovery: '+([string]::Join(', ',@($globalHubInputs|ForEach-Object{$_.File.Name}))))}
            else{Add-DoctorFinding $rows 'OK' 'inbox.hub_global' 'No stranded Hub-owned objects in the global Manager inbox.'}
'@
$doctorNew=@'
            $globalHubInputs=@(Get-GlobalHubOwnedInboxObjects);$reconciliationClaims=@(Get-HubInputReconciliationClaims)
            if($globalHubInputs.Count-gt0){Add-DoctorFinding $rows 'WARN' 'inbox.hub_global_stranded' ($globalHubInputs.Count.ToString()+' Hub-owned object(s) remain in the global Manager inbox and are outside normal per-instance Hub discovery: '+([string]::Join(', ',@($globalHubInputs|ForEach-Object{$_.File.Name}))))}
            else{Add-DoctorFinding $rows 'OK' 'inbox.hub_global' 'No stranded Hub-owned objects in the global Manager inbox.'}
            if($reconciliationClaims.Count-gt0){Add-DoctorFinding $rows 'WARN' 'inbox.hub_reconciliation_claim' ($reconciliationClaims.Count.ToString()+' durable Hub-input reconciliation claim(s) require deterministic resume before ordinary Hub-bound operations: '+([string]::Join(', ',@($reconciliationClaims|ForEach-Object{$_.Metadata.claim_id}))))}
            else{Add-DoctorFinding $rows 'OK' 'inbox.hub_reconciliation_claim' 'No unresolved durable Hub-input reconciliation claims.'}
'@
Require-One $text $doctorOld 'Doctor reconciliation diagnostics'
$text=$text.Replace($doctorOld,$doctorNew)
$actionOld="    if (`$warningCodes -contains 'inbox.hub_global_stranded') { [void]`$actions.Add('Run Initialize instance registry again to reconcile validated identity-bound global Hub inputs into their registered per-instance inboxes; foreign/ambiguous inputs will fail closed.') }"
$actionNew=$actionOld+"`r`n    if (`$warningCodes -contains 'inbox.hub_reconciliation_claim') { [void]`$actions.Add('Run Initialize instance registry again to resume durable Hub-input reconciliation claims; do not delete claim state manually.') }"
Require-One $text $actionOld 'Doctor claim action'
$text=$text.Replace($actionOld,$actionNew)

[IO.File]::WriteAllText($runtime,$text,$Utf8NoBom)
Assert-Parse $runtime
$required=@('keelaryn.manager.hub-input-reconciliation-claim.v1','HubInputReconciliationRoot','New-HubInputReconciliationClaim','Resolve-HubInputReconciliationClaim','inbox.hub_reconciliation_claim','durable claim is preserved','post-commit verification failed')
$patched=[IO.File]::ReadAllText($runtime,[Text.Encoding]::UTF8)
foreach($token in $required){if(-not$patched.Contains($token)){Fail('Patched runtime missing required token: '+$token)}}
foreach($forbidden in @('Phase 2: stage every missing destination','foreach($plan in @($plans))')){if($patched.Contains($forbidden)){Fail('Patched reconciliation still contains old whole-batch token: '+$forbidden)}}
Write-Host 'MGR-DEF-0034 CLAIM-FIRST PROOF PATCH: PASS' -ForegroundColor Green
Write-Host ('base_runtime_sha256='+$baseSha)
Write-Host ('patched_runtime_sha256='+(Get-FileHash -LiteralPath $runtime -Algorithm SHA256).Hash.ToLowerInvariant())
