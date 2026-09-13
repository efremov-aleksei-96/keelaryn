[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Get-Newline([string]$Text){if($Text.Contains("`r`n")){return "`r`n"};return "`n"}
function Normalize-Newlines([string]$Text,[string]$Nl){return ($Text.Replace("`r`n","`n").Replace("`r","`n").Replace("`n",$Nl))}
function Get-FunctionAstFromText([string]$Text,[string]$Name){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseInput($Text,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){Fail('Parser failed while locating '+$Name+': '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $rows=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name})
    if($rows.Count-ne1){Fail('Expected exactly one function '+$Name+'; actual='+$rows.Count)}
    return $rows[0]
}
function Replace-Function([string]$Text,[string]$Name,[string]$Replacement){
    $node=Get-FunctionAstFromText $Text $Name
    $nl=Get-Newline $Text
    $replacementText=Normalize-Newlines $Replacement $nl
    return $Text.Substring(0,[int]$node.Extent.StartOffset)+$replacementText+$Text.Substring([int]$node.Extent.EndOffset)
}
function Insert-FunctionPrologue([string]$Text,[string]$Name,[string]$Code){
    $node=Get-FunctionAstFromText $Text $Name
    $nl=Get-Newline $Text
    $insertAt=[int]$node.Body.Extent.StartOffset+1
    $insert=$nl+(Normalize-Newlines $Code $nl)+$nl
    return $Text.Substring(0,$insertAt)+$insert+$Text.Substring($insertAt)
}
function Replace-ExactOnce([string]$Text,[string]$Old,[string]$New,[string]$Label){
    $first=$Text.IndexOf($Old,[StringComparison]::Ordinal)
    if($first-lt0){Fail($Label+' source text not found.')}
    if($Text.IndexOf($Old,$first+$Old.Length,[StringComparison]::Ordinal)-ge0){Fail($Label+' source text is not unique.')}
    return $Text.Substring(0,$first)+$New+$Text.Substring($first+$Old.Length)
}
function Write-Text([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)}
function Parse-File([string]$Path){
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){Fail('PowerShell parser failed: '+$Path+'; '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
}

$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$installPath=Join-Path $RepositoryRoot 'manager\product\install\INSTALLATION.json'
$policyPath=Join-Path $RepositoryRoot 'manager\product\manager_release.json'
$readmePath=Join-Path $RepositoryRoot 'manager\README_FIRST.md'
$statePath=Join-Path $RepositoryRoot 'MANAGER_DEVELOPMENT_STATE.json'
foreach($path in @($runtimePath,$installPath,$policyPath,$readmePath,$statePath)){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Fail('Required source missing: '+$path)}}

$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
if($runtime.Contains('$ManagerVersion = "4.17.9"')){Fail 'Manager runtime is already 4.17.9; refusing to reapply one-shot transformer.'}
$runtime=Replace-ExactOnce $runtime '$ManagerVersion = "4.17.8"' '$ManagerVersion = "4.17.9"' 'runtime version'
$runtime=Replace-ExactOnce $runtime '$allowRegistryUnresolved=$Doctor-or$SelfTest-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$UpdateManager-or$InitializeInstanceRegistry-or$ListInstances-or$FinalizeFilesystemLayout' '$allowRegistryUnresolved=$Doctor-or$SelfTest-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$UpdateManager-or$InitializeInstanceRegistry-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$FinalizeFilesystemLayout' 'recovery allowlist'

$registryHelpersAndList=@'
function Get-GlobalHubOwnedInboxObjects {
    $rows=New-Object System.Collections.ArrayList
    if(-not(Test-Path -LiteralPath $Inbox -PathType Container)){return @($rows)}
    $root=Get-Item -LiteralPath $Inbox -Force -ErrorAction Stop
    if(-not$root.PSIsContainer-or($root.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Global Manager inbox is unsafe: '+$Inbox)}
    foreach($file in @(Get-ChildItem -LiteralPath $Inbox -File -Force -ErrorAction Stop|Sort-Object Name)){
        if($file.Name.StartsWith('Keelaryn__Manager',[StringComparison]::OrdinalIgnoreCase)){continue} # ManagerGlobal, not Hub-owned.
        $kind=$null
        if($file.Extension -ieq '.zip' -and ($file.Name.StartsWith('Keelaryn__Hub',[StringComparison]::OrdinalIgnoreCase)-or$file.Name.StartsWith([string]$LegacyCoreCompat.HubDirectory,[StringComparison]::OrdinalIgnoreCase))){$kind='hub_zip'}
        elseif($file.Extension -ieq '.json' -and $file.Name.StartsWith('Keelaryn__Hub_CANDIDATE_TRANSPORT_',[StringComparison]::OrdinalIgnoreCase)){$kind='candidate_transport'}
        if($kind){[void]$rows.Add([pscustomobject]@{File=$file;Kind=$kind})}
    }
    return @($rows)
}

function Get-GlobalHubInputIdentity($Input) {
    if($null-eq$Input-or$null-eq$Input.File){throw 'Global Hub input descriptor is invalid.'}
    $file=Get-Item -LiteralPath ([string]$Input.File.FullName) -Force -ErrorAction Stop
    if($file.PSIsContainer-or($file.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Global Hub input is unsafe: '+$file.FullName)}
    $sha=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if([string]$Input.Kind-eq'hub_zip'){
        $candidate=$file.Name.StartsWith('Keelaryn__Hub_CANDIDATE_',[StringComparison]::OrdinalIgnoreCase)-or$file.Name.StartsWith([string]$LegacyCoreCompat.CandidatePrefix,[StringComparison]::OrdinalIgnoreCase)
        $approved=$file.Name.StartsWith('Keelaryn__Hub_APPROVED_',[StringComparison]::OrdinalIgnoreCase)-or$file.Name.StartsWith([string]$LegacyCoreCompat.ApprovedPrefix,[StringComparison]::OrdinalIgnoreCase)
        if(-not$candidate-and-not$approved){throw('Global Hub ZIP has an unsupported pending role and cannot be assigned safely: '+$file.Name)}
        $required=if($candidate){'candidate'}else{'approved'}
        $identity=$null
        try{
            $identity=Get-ValidatedHubTransportIdentity $file.FullName $required
            $id=([string]$identity.Artifact.InstanceId).Trim().ToLowerInvariant()
            $g=[guid]::Empty
            if(-not[guid]::TryParse($id,[ref]$g)-or$g-eq[guid]::Empty){throw('Global Hub ZIP lacks canonical instance_id: '+$file.Name)}
            return [pscustomobject]@{InstanceId=$g.ToString().ToLowerInvariant();Sha256=$sha;Kind='hub_zip';File=$file}
        }finally{if($identity-and$identity.Session){Close-HubZipInspectionSession $identity.Session}}
    }
    if([string]$Input.Kind-eq'candidate_transport'){
        $doc=Read-CandidateTransportDocument $file.FullName
        $id=([string]$doc.candidate.instance_id).Trim().ToLowerInvariant();$g=[guid]::Empty
        if(-not[guid]::TryParse($id,[ref]$g)-or$g-eq[guid]::Empty){throw('Global candidate transport lacks canonical instance_id: '+$file.Name)}
        return [pscustomobject]@{InstanceId=$g.ToString().ToLowerInvariant();Sha256=$sha;Kind='candidate_transport';File=$file}
    }
    throw('Unsupported global Hub input kind: '+[string]$Input.Kind)
}

function Stage-GlobalHubInputsForRegistryActivation([string]$InstanceId,[string]$DestinationInbox) {
    $id=([string]$InstanceId).Trim().ToLowerInvariant()
    $entries=New-Object System.Collections.ArrayList
    $inputs=@(Get-GlobalHubOwnedInboxObjects)
    if($inputs.Count-eq0){return [pscustomobject]@{Entries=@()}}
    if(-not(Test-Path -LiteralPath $DestinationInbox -PathType Container)){throw('Per-instance inbox is missing before registry activation: '+$DestinationInbox)}
    $destRoot=Get-Item -LiteralPath $DestinationInbox -Force -ErrorAction Stop
    if(-not$destRoot.PSIsContainer-or($destRoot.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Per-instance inbox is unsafe before registry activation: '+$DestinationInbox)}
    foreach($input in $inputs){
        $identity=Get-GlobalHubInputIdentity $input
        if([string]$identity.InstanceId-ne$id){throw('Global Hub input instance_id does not match the Hub being activated. input='+$identity.InstanceId+' target='+$id+' file='+$identity.File.Name)}
        $source=[string]$identity.File.FullName
        $destination=Join-Path $destRoot.FullName $identity.File.Name
        $existing=Get-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue
        if($existing){
            if($existing.PSIsContainer-or($existing.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Global Hub input destination collision is unsafe: '+$destination)}
            $existingHash=(Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
            if($existingHash-ne[string]$identity.Sha256){throw('Global Hub input destination collision has different bytes: '+$destination)}
        }else{
            $tmp=$destination+'.stage.'+[guid]::NewGuid().ToString('N')
            try{
                $before=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
                if($before-ne[string]$identity.Sha256){throw('Global Hub input changed before staging: '+$source)}
                Copy-Item -LiteralPath $source -Destination $tmp -Force
                $copied=(Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash.ToLowerInvariant()
                $after=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
                if($copied-ne$before-or$after-ne$before){throw('Global Hub input changed while it was staged: '+$source)}
                Publish-CompletedFileAtomically $tmp $destination
            }finally{if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}}
        }
        [void]$entries.Add([pscustomobject]@{Source=$source;Destination=$destination;Sha256=[string]$identity.Sha256;InstanceId=$id;Kind=[string]$identity.Kind})
    }
    return [pscustomobject]@{Entries=@($entries)}
}

function Assert-GlobalHubInputActivationHandoffPrepared($Handoff) {
    if($null-eq$Handoff){return $true}
    foreach($entry in @($Handoff.Entries)){
        foreach($path in @([string]$entry.Source,[string]$entry.Destination)){
            $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop
            if($item.PSIsContainer-or($item.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Registry-activation Hub input handoff path is unsafe: '+$path)}
            if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()-ne[string]$entry.Sha256){throw('Registry-activation Hub input changed before registry commit: '+$path)}
        }
    }
    return $true
}

function Test-GlobalHubInputActivationHandoffSourcesIntact($Handoff) {
    if($null-eq$Handoff){return $true}
    try{
        foreach($entry in @($Handoff.Entries)){
            if(-not(Test-Path -LiteralPath ([string]$entry.Source) -PathType Leaf)){return $false}
            $item=Get-Item -LiteralPath ([string]$entry.Source) -Force -ErrorAction Stop
            if(($item.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){return $false}
            if((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()-ne[string]$entry.Sha256){return $false}
        }
        return $true
    }catch{return $false}
}

function Complete-GlobalHubInputActivationHandoff($Handoff) {
    if($null-eq$Handoff){return 0}
    $completed=0
    foreach($entry in @($Handoff.Entries)){
        $destination=[string]$entry.Destination
        $destItem=Get-Item -LiteralPath $destination -Force -ErrorAction Stop
        if($destItem.PSIsContainer-or($destItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Committed per-instance Hub input is unsafe: '+$destination)}
        $destHash=(Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
        if($destHash-ne[string]$entry.Sha256){throw('Committed per-instance Hub input hash changed: '+$destination)}
        $source=[string]$entry.Source
        if(Test-Path -LiteralPath $source){
            $srcItem=Get-Item -LiteralPath $source -Force -ErrorAction Stop
            if($srcItem.PSIsContainer-or($srcItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Global Hub input source became unsafe after commit: '+$source)}
            $srcHash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
            if($srcHash-ne[string]$entry.Sha256){throw('Global Hub input changed after commit; preserving both global and instance copies for explicit recovery: '+$source)}
            Remove-Item -LiteralPath $source -Force -ErrorAction Stop
        }
        $completed++
    }
    return $completed
}

function Assert-NoStrandedGlobalHubInputs([string]$Operation='Hub operation') {
    if(-not(Test-Path -LiteralPath $script:InstanceRegistryFile -PathType Leaf)){return}
    $rows=@(Get-GlobalHubOwnedInboxObjects)
    if($rows.Count-ne0){
        throw($Operation+' refused because '+$rows.Count+' Hub-owned object(s) remain in the global Manager inbox and would otherwise be unreachable from per-instance Hub discovery. Run Initialize instance registry to reconcile identity-bound inputs first. Files: '+([string]::Join(', ',@($rows|ForEach-Object{$_.File.Name}))))
    }
}

function Reconcile-StrandedGlobalHubInputsForExistingRegistry {
    $inputs=@(Get-GlobalHubOwnedInboxObjects)
    if($inputs.Count-eq0){return 0}
    $registry=Get-ManagerInstanceRegistry
    $entries=New-Object System.Collections.ArrayList
    foreach($input in $inputs){
        $identity=Get-GlobalHubInputIdentity $input
        $matches=@($registry.instances|Where-Object{[string]$_.instance_id-eq[string]$identity.InstanceId})
        if($matches.Count-ne1){throw('Global Hub input belongs to an unregistered/ambiguous instance_id: '+$identity.InstanceId+' file='+$identity.File.Name)}
        $paths=Get-InstanceStatePaths ([string]$identity.InstanceId)
        if(-not(Test-Path -LiteralPath $paths.Inbox -PathType Container)){throw('Registered instance inbox is missing for stranded input reconciliation: '+$paths.Inbox)}
        $destRoot=Get-Item -LiteralPath $paths.Inbox -Force -ErrorAction Stop
        if(($destRoot.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Registered instance inbox is unsafe: '+$paths.Inbox)}
        $source=[string]$identity.File.FullName;$destination=Join-Path $destRoot.FullName $identity.File.Name
        $existing=Get-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue
        if($existing){
            if($existing.PSIsContainer-or($existing.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Stranded Hub input destination collision is unsafe: '+$destination)}
            if((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()-ne[string]$identity.Sha256){throw('Stranded Hub input destination collision has different bytes: '+$destination)}
        }else{
            $tmp=$destination+'.stage.'+[guid]::NewGuid().ToString('N')
            try{
                $before=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
                Copy-Item -LiteralPath $source -Destination $tmp -Force
                $copied=(Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash.ToLowerInvariant();$after=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
                if($before-ne[string]$identity.Sha256-or$copied-ne$before-or$after-ne$before){throw('Stranded Hub input changed during staging: '+$source)}
                Publish-CompletedFileAtomically $tmp $destination
            }finally{if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}}
        }
        [void]$entries.Add([pscustomobject]@{Source=$source;Destination=$destination;Sha256=[string]$identity.Sha256;InstanceId=[string]$identity.InstanceId;Kind=[string]$identity.Kind})
    }
    return Complete-GlobalHubInputActivationHandoff ([pscustomobject]@{Entries=@($entries)})
}

function Invoke-ListInstances {
    if(-not(Test-Path -LiteralPath $script:InstanceRegistryFile -PathType Leaf)){
        Write-Host 'Multi-Hub registry: not initialized (single-instance compatibility mode).'
        return 0
    }
    $registry=Get-ManagerInstanceRegistry
    $active=$null;$activeError=$null
    try{$active=Read-ActiveInstanceEarly}catch{$activeError=$_.Exception.Message}
    Write-Host ('Registered Hubs: '+@($registry.instances).Count) -ForegroundColor Cyan
    if($activeError){Write-Warning('Active selection metadata is invalid/unresolved: '+$activeError)}
    foreach($row in @($registry.instances|Sort-Object name,instance_id)){
        $mark=if($active-and[string]$row.instance_id-eq[string]$active.instance_id){'*'}else{' '}
        Write-Host ('{0} {1} | {2} | {3}' -f $mark,[string]$row.name,[string]$row.instance_id,[string]$row.vault_path)
    }
    return 0
}
'@
$runtime=Replace-Function $runtime 'Invoke-ListInstances' $registryHelpersAndList

$newSwitch=@'
function Invoke-SwitchRegisteredInstance([string]$InstanceId) {
    $registry=Get-ManagerInstanceRegistry
    $id=([string]$InstanceId).Trim().ToLowerInvariant()
    $matches=@($registry.instances|Where-Object{[string]$_.instance_id-eq$id})
    if($matches.Count-ne1){throw('Unknown registered instance_id: '+$id)}
    $row=$matches[0]

    # Previous selection is diagnostic/rollback context only. Recovery must be driven by
    # the requested target and must not require the old active Hub to be readable.
    $previousSelection=$null;$previousRow=$null
    try{
        $previousSelection=Read-ActiveInstanceEarly
        $previousMatches=@($registry.instances|Where-Object{[string]$_.instance_id-eq[string]$previousSelection.instance_id})
        if($previousMatches.Count-eq1){$previousRow=$previousMatches[0]}
    }catch{}

    if($previousSelection-and[string]$previousSelection.instance_id-eq$id){
        $null=Assert-RegisteredInstanceActivationEligible $row
        $null=Publish-CompatibilityShadowFromRegisteredInstance $row 'multi_hub_switch_same_instance'
        $null=Assert-RegisteredInstanceActivationEligible $row
        $shadow=Get-CompatibilityShadowAssessment $row
        if(-not$shadow.Valid){throw('Active Hub compatibility shadow is not commit-eligible: '+$shadow.Reason)}
        Write-Host ('Active Hub is already: '+[string]$row.name) -ForegroundColor Green
        return 0
    }

    $committed=$false;$writeStarted=$false;$definitePreCommit=$false;$ambiguous=$false
    try{
        $null=Assert-RegisteredInstanceActivationEligible $row
        $null=Publish-CompatibilityShadowFromRegisteredInstance $row 'multi_hub_switch_prepare'
        # Fresh full activation + compatibility predicates immediately before the authoritative marker.
        $null=Assert-RegisteredInstanceActivationEligible $row
        $shadow=Get-CompatibilityShadowAssessment $row
        if(-not$shadow.Valid){throw('Target compatibility shadow changed before active commit: '+$shadow.Reason)}
        $writeStarted=$true
        Write-ManagerActiveInstance $id
        $committed=$true
    }catch{
        $primary=$_.Exception.Message
        if(-not$committed){
            if(-not$writeStarted){$definitePreCommit=$true}
            else{
                try{
                    $activeNow=Read-ActiveInstanceEarly
                    if([string]$activeNow.instance_id-eq$id){$committed=$true}
                    elseif($previousSelection-and[string]$activeNow.instance_id-eq[string]$previousSelection.instance_id){$definitePreCommit=$true}
                    else{$ambiguous=$true}
                }catch{$ambiguous=$true}
            }
        }
        if(-not$committed){
            if($definitePreCommit-and$previousRow){
                try{
                    $null=Assert-RegisteredInstanceActivationEligible $previousRow
                    $null=Publish-CompatibilityShadowFromRegisteredInstance $previousRow 'multi_hub_switch_best_effort_restore'
                }catch{Log('Best-effort previous compatibility-shadow restore skipped/failed after pre-commit switch failure: '+$_.Exception.Message)}
            }
            if($ambiguous){throw('Active Hub switch commit status is ambiguous after active-marker write failure; no destructive rollback was attempted. Target='+$id+'. Primary: '+$primary)}
            throw('Active Hub switch failed before active selection commit; target was not selected. '+$primary)
        }
    }

    try{
        $null=Resolve-RegisteredInstanceContextEarly
        $script:InvocationInstanceId=$id
        $null=Assert-RegisteredInstanceActivationEligible $row
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
$runtime=Replace-Function $runtime 'Invoke-SwitchRegisteredInstance' $newSwitch

$newBind=@'
function Invoke-RebindRegisteredInstance([string]$Path,[string]$Name) {
    $registry=Get-ManagerInstanceRegistry
    $full=Assert-RegisteredVaultStructuralSafetyEarly $Path
    if(-not(& $TestHubCandidate $full)){throw('Rebind target is not a valid Keelaryn Hub: '+$full)}
    $state=Read-VaultMetadataAt $full;$artifact=Read-VaultArtifactManifestAt $full
    if(-not$state-or-not$artifact-or-not$state.InstanceId-or[string]$artifact.InstanceId-ne[string]$state.InstanceId){throw 'Rebind target lacks a consistent canonical instance identity.'}
    $id=[string]$state.InstanceId
    $sameId=@($registry.instances|Where-Object{[string]$_.instance_id-eq$id})
    if($sameId.Count-ne1){throw('Rebind requires exactly one existing registry row with the same immutable instance_id: '+$id)}
    $oldRow=$sameId[0]
    $newKey=Get-KeelarynNormalizedPathKey $full;$oldKey=Get-KeelarynNormalizedPathKey ([string]$oldRow.vault_path)
    $samePath=@($registry.instances|Where-Object{(Get-KeelarynNormalizedPathKey ([string]$_.vault_path))-eq$newKey})
    if($samePath.Count-ne0-and-not($samePath.Count-eq1-and[string]$samePath[0].instance_id-eq$id)){throw 'Rebind target path is already owned by another registered instance.'}
    foreach($other in @($registry.instances|Where-Object{[string]$_.instance_id-ne$id})){
        if(Test-KeelarynPathOverlap $full ([string]$other.vault_path)){throw('Rebind target overlaps registered Hub '+[string]$other.name+': '+[string]$other.vault_path)}
    }
    if($newKey-eq$oldKey){return Invoke-SwitchRegisteredInstance $id}

    $candidateRow=[pscustomobject]@{instance_id=$id;name=[string]$oldRow.name;vault_path=$full;registered_utc=[string]$oldRow.registered_utc}
    $previousSelection=$null;$previousRow=$null
    try{
        $previousSelection=Read-ActiveInstanceEarly
        $p=@($registry.instances|Where-Object{[string]$_.instance_id-eq[string]$previousSelection.instance_id})
        if($p.Count-eq1){$previousRow=$p[0]}
    }catch{}

    # Rebind preserves the existing per-instance state/CURRENT. It never moves or clones Hub bytes.
    $null=Assert-RegisteredInstanceActivationEligible $candidateRow
    $null=Publish-CompatibilityShadowFromRegisteredInstance $candidateRow 'multi_hub_rebind_prepare'
    $null=Assert-RegisteredInstanceActivationEligible $candidateRow
    $shadow=Get-CompatibilityShadowAssessment $candidateRow
    if(-not$shadow.Valid){throw('Rebind compatibility shadow changed before registry commit: '+$shadow.Reason)}

    $newRows=@($registry.instances|ForEach-Object{if([string]$_.instance_id-eq$id){$candidateRow}else{$_}})
    $writeStarted=$false;$registryCommitted=$false;$registryAmbiguous=$false
    try{
        $writeStarted=$true
        Write-ManagerInstanceRegistry ([ordered]@{schema='keelaryn.manager.instances.v1';registry_revision=([int]$registry.registry_revision+1);instances=@($newRows)})
        $registryCommitted=$true
    }catch{
        $primary=$_.Exception.Message
        try{
            $after=Get-ManagerInstanceRegistry
            $newMatches=@($after.instances|Where-Object{[string]$_.instance_id-eq$id-and(Get-KeelarynNormalizedPathKey ([string]$_.vault_path))-eq$newKey})
            $oldMatches=@($after.instances|Where-Object{[string]$_.instance_id-eq$id-and(Get-KeelarynNormalizedPathKey ([string]$_.vault_path))-eq$oldKey})
            if($newMatches.Count-eq1-and$oldMatches.Count-eq0){$registryCommitted=$true}
            elseif($newMatches.Count-eq0-and$oldMatches.Count-eq1){$registryCommitted=$false}
            else{$registryAmbiguous=$true}
        }catch{$registryAmbiguous=$true}
        if(-not$registryCommitted){
            if(-not$registryAmbiguous-and$previousRow){
                try{$null=Assert-RegisteredInstanceActivationEligible $previousRow;$null=Publish-CompatibilityShadowFromRegisteredInstance $previousRow 'multi_hub_rebind_best_effort_restore'}catch{Log('Best-effort compatibility restore skipped/failed after uncommitted rebind: '+$_.Exception.Message)}
            }
            if($registryAmbiguous){throw('Hub rebind registry commit status is ambiguous; registry/Hub bytes were not rolled back. Primary: '+$primary)}
            throw('Hub rebind failed before registry commit; previous registry path remains authoritative. '+$primary)
        }
    }

    try{
        # Registry path commit is durable. Revalidate the exact target before repairing/setting active selection.
        $null=Assert-RegisteredInstanceActivationEligible $candidateRow
        $shadow=Get-CompatibilityShadowAssessment $candidateRow
        if(-not$shadow.Valid){throw('Committed rebind compatibility shadow is not activation-eligible: '+$shadow.Reason)}
        $activeCommitted=$false
        try{Write-ManagerActiveInstance $id;$activeCommitted=$true}catch{
            try{$a=Read-ActiveInstanceEarly;if([string]$a.instance_id-eq$id){$activeCommitted=$true}}catch{}
            if(-not$activeCommitted){throw('Registry path commit is durable, but active selection commit is not confirmed: '+$_.Exception.Message)}
        }
        $null=Resolve-RegisteredInstanceContextEarly
        $script:InvocationInstanceId=$id
        $check=Get-CompatibilityShadowAssessment $candidateRow
        if(-not$check.Valid){throw $check.Reason}
    }catch{
        throw('Hub rebind durable registry commit succeeded, but activation/post-commit verification failed; the new validated registry path was preserved. '+$_.Exception.Message)
    }
    Write-Host ('Rebound registered Hub without moving Hub bytes: '+[string]$oldRow.name) -ForegroundColor Green
    Write-Host ('instance_id: '+$id)
    Write-Host ('path: '+$full)
    return 0
}

function Invoke-BindInstance {
    if (-not $BindInstancePath) { throw 'BindInstancePath is required.' }
    if (Test-Path -LiteralPath $script:InstanceRegistryFile -PathType Leaf) {
        $full=Assert-RegisteredVaultStructuralSafetyEarly $BindInstancePath
        if(-not(& $TestHubCandidate $full)){throw('Bind target is not a valid Hub: '+$full)}
        $state=Read-VaultMetadataAt $full;$artifact=Read-VaultArtifactManifestAt $full
        if(-not$state-or-not$artifact-or-not$state.InstanceId-or[string]$artifact.InstanceId-ne[string]$state.InstanceId){throw 'Bind target lacks a consistent canonical instance identity.'}
        $registry=Get-ManagerInstanceRegistry
        $sameId=@($registry.instances|Where-Object{[string]$_.instance_id-eq[string]$state.InstanceId})
        if($sameId.Count-eq1){return Invoke-RebindRegisteredInstance $full $RegisterInstanceName}
        if($sameId.Count-gt1){throw 'Bind target instance_id is ambiguous in the registry.'}
        return Invoke-RegisterExistingInstance $full $RegisterInstanceName $true
    }
    if (-not (& $TestHubCandidate $Vault)) { throw ('Bind target is not a valid Hub: '+$Vault) }
    $id=& $ReadBoundInstanceId $Vault
    & $WriteBindingV2 $Vault $id 'explicit_bind_command'
    Write-Host ('Bound Keelaryn__Manager to: '+$Vault) -ForegroundColor Green
    if ($id) { Write-Host ('instance_id: '+$id) }
    return 0
}
'@
$runtime=Replace-Function $runtime 'Invoke-BindInstance' $newBind

$newInitialize=@'
function Invoke-InitializeInstanceRegistry {
    if(-not$CanonicalLayoutActive-or-not$StateLayoutActive){throw 'Multi-Hub registry initialization requires finalized canonical Manager layout.'}
    if(Test-ExistingInstanceRegistryForInitialization){
        $migrated=Reconcile-StrandedGlobalHubInputsForExistingRegistry
        Write-Host 'Multi-Hub registry is already initialized and valid.' -ForegroundColor Green
        if($migrated-gt0){Write-Host('Reconciled '+$migrated+' identity-bound Hub input(s) from the global Manager inbox into registered per-instance inboxes.')-ForegroundColor Green}
        return 0
    }
    Assert-InstanceBindingAvailable
    $baseline=Test-CanonicalBaselineConsistent
    if(-not$baseline.State.InstanceId){throw 'Multi-Hub registry requires canonical keelaryn.instance.v1 identity.'}
    $id=[string]$baseline.State.InstanceId
    $name=if($RegisterInstanceName){$RegisterInstanceName}else{'Primary'}
    $registered=(Get-Date).ToUniversalTime().ToString('o')
    $vaultFull=[System.IO.Path]::GetFullPath($Vault).TrimEnd('\')
    $bootstrapRow=[pscustomobject]@{instance_id=$id;name=$name;vault_path=$vaultFull;registered_utc=$registered}
    $paths=$null;$handoff=$null
    $activeWriteStarted=$false;$registryWriteStarted=$false;$registryCommitted=$false
    try{
        $paths=New-RegisteredInstanceStateFromVault $id $Vault
        # Preserve the exact pre-registry CURRENT bytes where possible. This is stronger
        # than relying only on deterministic reconstruction and keeps historical transport identity.
        if(Test-Path -LiteralPath $script:LegacySingleInstanceCurrentZip -PathType Leaf){
            $tmp=$paths.Current+'.legacy-copy'
            Copy-Item -LiteralPath $script:LegacySingleInstanceCurrentZip -Destination $tmp -Force
            $session=Open-HubZipInspectionSession $tmp
            if(-not$session){throw 'Legacy single-instance CURRENT failed validation during registry bootstrap.'}
            try{
                $state=Read-ZipState $tmp $session;$artifact=Read-ZipArtifactManifest $tmp $session;$analysis=Get-PortableVaultAnalysis $Vault;$hash=Get-ZipHashPair $tmp $session
                if(-not$state-or-not$artifact-or[string]$state.InstanceId-ne$id-or[string]$artifact.InstanceId-ne$id-or[string]$hash.ContentHash-ne[string]$analysis.ContentHash){throw 'Legacy CURRENT does not match the active Hub during registry bootstrap.'}
            }finally{Close-HubZipInspectionSession $session}
            Publish-CompletedFileAtomically $tmp $paths.Current
        }
        # Copy only validated, identity-bound Hub inputs. Global sources remain reachable
        # until instances.json is proven durable; unknown files are never bulk-moved.
        $handoff=Stage-GlobalHubInputsForRegistryActivation $id $paths.Inbox
        $registry=[ordered]@{
            schema='keelaryn.manager.instances.v1';registry_revision=1
            instances=@([ordered]@{instance_id=$id;name=$name;vault_path=$vaultFull;registered_utc=$registered})
        }
        $null=Publish-CompatibilityShadowFromRegisteredInstance $bootstrapRow 'multi_hub_registry_bootstrap'
        # Full activation eligibility + compatibility + pending-input reachability are fresh
        # immediately before active selection becomes authoritative.
        $null=Assert-RegisteredInstanceActivationEligible $bootstrapRow
        $null=Assert-GlobalHubInputActivationHandoffPrepared $handoff
        $shadow=Get-CompatibilityShadowAssessment $bootstrapRow
        if(-not$shadow.Valid){throw('Bootstrap compatibility shadow changed before active commit: '+$shadow.Reason)}
        $activeWriteStarted=$true
        Write-ManagerActiveInstance $id
        # instances.json is the registry activation marker. Revalidate the complete resulting
        # state again after active publication and immediately before registry commit.
        $null=Assert-RegisteredInstanceActivationEligible $bootstrapRow
        $null=Assert-GlobalHubInputActivationHandoffPrepared $handoff
        $shadow=Get-CompatibilityShadowAssessment $bootstrapRow
        if(-not$shadow.Valid){throw('Bootstrap compatibility shadow changed before registry commit: '+$shadow.Reason)}
        $registryWriteStarted=$true
        Write-ManagerInstanceRegistry $registry
        $registryCommitted=$true
        $null=Complete-GlobalHubInputActivationHandoff $handoff
        $null=Resolve-RegisteredInstanceContextEarly
        $script:InvocationInstanceId=$id
        Write-Host ('Multi-Hub registry initialized. Active: '+$name+' | '+$id) -ForegroundColor Green
        Write-Host ('Instance CURRENT: '+$paths.Current)
        return 0
    }catch{
        $primary=$_.Exception.Message
        $registryNotCommitted=$false;$verificationFailure=$null
        if(-not$registryCommitted){
            if(-not$registryWriteStarted){$registryNotCommitted=$true}
            elseif(-not(Test-Path -LiteralPath $script:InstanceRegistryFile -PathType Leaf)){$registryNotCommitted=$true}
            else{
                try{
                    $after=Get-ManagerInstanceRegistry
                    $exact=@($after.instances|Where-Object{[string]$_.instance_id-eq$id-and[string]$_.name-ceq$name-and(Get-KeelarynNormalizedPathKey ([string]$_.vault_path))-eq(Get-KeelarynNormalizedPathKey $vaultFull)})
                    if([int]$after.registry_revision-eq1-and@($after.instances).Count-eq1-and$exact.Count-eq1){$registryCommitted=$true}
                    else{$verificationFailure=('Registry verification returned an unexpected bootstrap document: revision={0}; rows={1}; exact={2}.' -f [int]$after.registry_revision,@($after.instances).Count,$exact.Count)}
                }catch{$verificationFailure=$_.Exception.Message}
            }
        }
        if($registryCommitted){throw('Multi-Hub registry durable commit succeeded, but subsequent bootstrap verification/Hub-input handoff failed; registry/active/per-instance state were preserved. '+$primary)}
        if($registryWriteStarted-and-not$registryNotCommitted){
            if([string]::IsNullOrWhiteSpace([string]$verificationFailure)){$verificationFailure='Registry verification could not establish whether the bootstrap write committed.'}
            throw('Multi-Hub registry commit status is ambiguous after a bootstrap write failure; registry/active/per-instance state were preserved. Primary failure: '+$primary+' Commit verification failure: '+$verificationFailure)
        }

        $cleanupErrors=New-Object System.Collections.ArrayList
        if($activeWriteStarted-and(Test-Path -LiteralPath $script:ActiveInstanceFile -PathType Leaf)){
            try{$activeNow=Read-ActiveInstanceEarly;if([string]$activeNow.instance_id-ne$id){throw 'Active marker no longer belongs to the bootstrap instance; cleanup refused.'};Remove-Item -LiteralPath $script:ActiveInstanceFile -Force -ErrorAction Stop}catch{[void]$cleanupErrors.Add('active: '+$_.Exception.Message)}
        }
        $sourcesIntact=Test-GlobalHubInputActivationHandoffSourcesIntact $handoff
        if(-not$sourcesIntact){[void]$cleanupErrors.Add('state: staged Hub input preserved because its original global source disappeared or changed before registry commit; deleting the staged copy could lose data.')}
        elseif($paths-and(Test-Path -LiteralPath $paths.Root -PathType Container)){
            try{$null=Assert-RegisteredInstanceBaseline $bootstrapRow;Remove-Item -LiteralPath $paths.Root -Recurse -Force -ErrorAction Stop}catch{[void]$cleanupErrors.Add('state: '+$_.Exception.Message)}
        }
        if($cleanupErrors.Count-ne0){throw('Multi-Hub registry initialization failed before registry commit and rollback cleanup could not be completed safely. Primary: '+$primary+' Cleanup: '+([string]::Join(' | ',@($cleanupErrors))))}
        throw('Multi-Hub registry initialization failed before registry commit; bootstrap active/state were rolled back while global Hub inputs remained reachable. '+$primary)
    }
}
'@
$runtime=Replace-Function $runtime 'Invoke-InitializeInstanceRegistry' $newInitialize

$runtime=Insert-FunctionPrologue $runtime 'Find-HubUpdateDecision' "    Assert-NoStrandedGlobalHubInputs 'Hub update discovery'"
$runtime=Insert-FunctionPrologue $runtime 'Invoke-BuildCandidateTransport' "    Assert-NoStrandedGlobalHubInputs 'Candidate transport build'"
$runtime=Insert-FunctionPrologue $runtime 'Invoke-RestoreCandidateTransport' "    Assert-NoStrandedGlobalHubInputs 'Candidate transport restore'"
$runtime=Insert-FunctionPrologue $runtime 'Invoke-Doctor' @'
    if(Test-Path -LiteralPath $script:InstanceRegistryFile -PathType Leaf){
        try{
            $globalHubInputs=@(Get-GlobalHubOwnedInboxObjects)
            if($globalHubInputs.Count-gt0){Add-DoctorFinding $rows 'WARN' 'inbox.hub_global_stranded' ($globalHubInputs.Count.ToString()+' Hub-owned object(s) remain in the global Manager inbox and are outside normal per-instance Hub discovery: '+([string]::Join(', ',@($globalHubInputs|ForEach-Object{$_.File.Name}))))}
            else{Add-DoctorFinding $rows 'OK' 'inbox.hub_global' 'No stranded Hub-owned objects in the global Manager inbox.'}
        }catch{Add-DoctorFinding $rows 'WARN' 'inbox.hub_global_scan' $_.Exception.Message}
    }
'@
$runtime=Replace-ExactOnce $runtime "    if (`$warningCodes -contains 'inbox.manager_invalid') { [void]`$actions.Add('Review or remove invalid Manager ZIPs from state/inbox before the next update run.') }" "    if (`$warningCodes -contains 'inbox.manager_invalid') { [void]`$actions.Add('Review or remove invalid Manager ZIPs from state/inbox before the next update run.') }`n    if (`$warningCodes -contains 'inbox.hub_global_stranded') { [void]`$actions.Add('Run Initialize instance registry again to reconcile validated identity-bound global Hub inputs into their registered per-instance inboxes; foreign/ambiguous inputs will fail closed.') }" 'Doctor stranded-input action'

Write-Text $runtimePath $runtime
Parse-File $runtimePath

$install=[IO.File]::ReadAllText($installPath,[Text.Encoding]::UTF8)
$install=Replace-ExactOnce $install '"manager_version": "4.17.8"' '"manager_version": "4.17.9"' 'INSTALLATION manager_version'
Write-Text $installPath $install

$policy=[IO.File]::ReadAllText($policyPath,[Text.Encoding]::UTF8)
$policy=Replace-ExactOnce $policy '"manager_version":  "4.17.8"' '"manager_version":  "4.17.9"' 'manager release policy version'
Write-Text $policyPath $policy

$readme=[IO.File]::ReadAllText($readmePath,[Text.Encoding]::UTF8)
$readme=Replace-ExactOnce $readme '# Keelaryn Manager 4.17.8' '# Keelaryn Manager 4.17.9' 'README heading'
$oldIntro='Manager 4.17.8 is the corrective successor to the production-qualified but public-release-rejected Manager 4.17.7.'
$pos=$readme.IndexOf($oldIntro,[StringComparison]::Ordinal)
if($pos-lt0){Fail 'README 4.17.8 introduction anchor missing.'}
$nl=Get-Newline $readme
$newIntro='Manager 4.17.9 is the multi-Hub convergence successor to the production-qualified but public-release-rejected Manager 4.17.8. It separates registry-document validity from active-selection/active-Hub health for target-driven recovery, adds identity-preserving rebind without moving Hub bytes, keeps Hub-owned global inbox objects reachable across registry activation, diagnoses/blocks stranded global Hub inputs in registered mode, and revalidates full activation plus compatibility predicates at authoritative commit boundaries. Production multi-Hub remains disabled until this successor completes qualification.'+$nl+$nl+'## 4.17.8 context'+$nl+$oldIntro
$readme=$readme.Substring(0,$pos)+$newIntro+$readme.Substring($pos+$oldIntro.Length)
Write-Text $readmePath $readme

$state=Get-Content -LiteralPath $statePath -Raw -Encoding UTF8|ConvertFrom-Json
$state.product_bytes_changed_from_production_provenance=$true
$state.qualification.development_validation.status='current_head_requires_validation'
$state.qualification.development_validation.note='Manager 4.17.9 convergence product bytes are now under active development; exact product head requires fresh hosted validation before blockers can be cleared.'
$state.next_exact_goal.description='Validate the 4.17.9 convergence product changes against permanent A01-A20 executable coverage; diagnose/fix any hosted failures without weakening invariants; only after exact-head PASS mark blockers fixed and require strict Risk/Defect Gate PASS.'
$state|ConvertTo-Json -Depth 30|ForEach-Object{[IO.File]::WriteAllText($statePath,($_.Replace("`r`n","`n")+"`n"),$Utf8NoBom)}

# Final local structural assertions before the mutation workflow is allowed to commit.
$final=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
foreach($token in @('$ManagerVersion = "4.17.9"','function Get-GlobalHubOwnedInboxObjects','function Stage-GlobalHubInputsForRegistryActivation','function Assert-NoStrandedGlobalHubInputs','function Invoke-RebindRegisteredInstance','Assert-RegisteredInstanceActivationEligible $row','inbox.hub_global_stranded')){if(-not$final.Contains($token)){Fail('Expected 4.17.9 runtime token missing: '+$token)}}
Write-Host 'Manager 4.17.9 convergence transformer: PASS' -ForegroundColor Green
