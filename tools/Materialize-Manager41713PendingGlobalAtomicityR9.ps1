[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [Parameter(Mandatory=$true)][string]$EvidenceRoot
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$ExpectedBase=$ExpectedBase.Trim().ToLowerInvariant()
$Utf8NoBom=New-Object Text.UTF8Encoding($false)
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null

function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)}
function Write-Json([string]$Path,$Object,[int]$Depth=80){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth $Depth).Replace("`r`n","`n"))+"`n")}
function Read-Json([string]$Path){return Get-Content -LiteralPath $Path -Raw -Encoding UTF8|ConvertFrom-Json}
function Parse-Ast([string]$Path){$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors);if(@($errors).Count-ne0){Fail('Parser failed: '+$Path+' :: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))};return $ast}
function Replace-Once([string]$Text,[string]$Old,[string]$New,[string]$Label){$count=[regex]::Matches($Text,[regex]::Escape($Old)).Count;if($count-ne1){Fail($Label+' count='+$count)};return $Text.Replace($Old,$New)}
function Add-UniqueString($Object,[string]$Property,[string]$Value){$values=@($Object.$Property|ForEach-Object{[string]$_});if($values-cnotcontains$Value){$Object.$Property=@($values)+@($Value)}}
function Set-Property($Object,[string]$Name,$Value){if($null-eq$Object.PSObject.Properties[$Name]){$Object|Add-Member -NotePropertyName $Name -NotePropertyValue $Value}else{$Object.$Name=$Value}}
function Invoke-Child([string]$Script,[string[]]$Arguments,[string]$Purpose,[switch]$AllowFailure){
    $exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    foreach($line in @($out)){Write-Host $line}
    if(-not$AllowFailure-and$code-ne0){Fail($Purpose+' failed; exit='+$code+'; output='+([string]::Join(' | ',@($out))))}
    return [pscustomobject]@{ExitCode=$code;Text=[string]::Join("`n",@($out));Output=@($out)}
}

$head=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($head-cne$ExpectedBase){Fail('Unexpected R9 base HEAD: '+$head+' expected='+$ExpectedBase)}
if(@(& git.exe -C $RepositoryRoot status --porcelain).Count-ne0){Fail 'R9 target checkout is not clean.'}

$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$matrixPath=Join-Path $RepositoryRoot 'tools\Invoke-ManagerEntryReachabilityMatrix.ps1'
$entryValidatorPath=Join-Path $RepositoryRoot 'tools\Test-ManagerEntryReachabilityKnowledge.ps1'
$metadataVerifierPath=Join-Path $RepositoryRoot 'tools\Verify-PublicCandidateMetadata.ps1'
$entryModelPath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability.json'
$machinePath=Join-Path $RepositoryRoot 'tests\knowledge\state-machines\multi-hub.json'
$riskPath=Join-Path $RepositoryRoot 'tests\knowledge\risk-map.json'
$defectPath=Join-Path $RepositoryRoot 'tests\knowledge\defects\manager-4.17.13-prefreeze.json'
$manifestPath=Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json'
$provenancePath=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json'
$statePath=Join-Path $RepositoryRoot 'MANAGER_DEVELOPMENT_STATE.json'
$manifestBuilder=Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1'
foreach($p in @($runtimePath,$matrixPath,$entryValidatorPath,$metadataVerifierPath,$entryModelPath,$machinePath,$riskPath,$defectPath,$manifestPath,$provenancePath,$statePath,$manifestBuilder)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Required R9 path missing: '+$p)}}

# -----------------------------------------------------------------------------
# Product correction: two-phase stranded-global handoff.
# All identity, registration, destination and collision checks complete before the
# first per-instance destination is published. Missing destinations are staged,
# the whole plan is revalidated, then publication begins. A publication failure
# rolls back only exact-hash destinations created by this invocation. Global
# sources are removed only after destination publication has coherently committed.
# -----------------------------------------------------------------------------
$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
$ast=Parse-Ast $runtimePath
$fnRows=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-ceq'Reconcile-StrandedGlobalHubInputsForExistingRegistry'},$true))
if($fnRows.Count-ne1){Fail('Reconcile-StrandedGlobalHubInputsForExistingRegistry function count='+$fnRows.Count)}
$fn=$fnRows[0]
$newFunction=@'
function Reconcile-StrandedGlobalHubInputsForExistingRegistry {
    $inputs=@(Get-GlobalHubOwnedInboxObjects)
    if($inputs.Count-eq0){return 0}
    $registry=Get-ManagerInstanceRegistry
    $plans=New-Object System.Collections.ArrayList

    # Phase 1: preflight every input and every destination before any durable publication.
    foreach($input in $inputs){
        $identity=Get-GlobalHubInputIdentity $input
        $matches=@($registry.instances|Where-Object{[string]$_.instance_id-eq[string]$identity.InstanceId})
        if($matches.Count-ne1){throw('Global Hub input belongs to an unregistered/ambiguous instance_id: '+$identity.InstanceId+' file='+$identity.File.Name)}
        $paths=Get-InstanceStatePaths ([string]$identity.InstanceId)
        if(-not(Test-Path -LiteralPath $paths.Inbox -PathType Container)){throw('Registered instance inbox is missing for stranded input reconciliation: '+$paths.Inbox)}
        $destRoot=Get-Item -LiteralPath $paths.Inbox -Force -ErrorAction Stop
        if(-not$destRoot.PSIsContainer-or($destRoot.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Registered instance inbox is unsafe: '+$paths.Inbox)}
        $source=[string]$identity.File.FullName
        $sourceItem=Get-Item -LiteralPath $source -Force -ErrorAction Stop
        if($sourceItem.PSIsContainer-or($sourceItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Stranded Hub input source is unsafe: '+$source)}
        $sourceHash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
        if($sourceHash-ne[string]$identity.Sha256){throw('Stranded Hub input changed during preflight: '+$source)}
        $destination=Join-Path $destRoot.FullName $identity.File.Name
        $existing=Get-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue
        $alreadyPresent=$false
        if($existing){
            if($existing.PSIsContainer-or($existing.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Stranded Hub input destination collision is unsafe: '+$destination)}
            if((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()-ne[string]$identity.Sha256){throw('Stranded Hub input destination collision has different bytes: '+$destination)}
            $alreadyPresent=$true
        }
        [void]$plans.Add([pscustomobject]@{
            Source=$source;Destination=$destination;Sha256=[string]$identity.Sha256;InstanceId=[string]$identity.InstanceId;Kind=[string]$identity.Kind
            AlreadyPresent=$alreadyPresent;Stage='';PublishedByThisRun=$false
        })
    }

    try{
        # Phase 2: stage every missing destination. Staging is non-authoritative.
        foreach($plan in @($plans)){
            if([bool]$plan.AlreadyPresent){continue}
            $sourceItem=Get-Item -LiteralPath ([string]$plan.Source) -Force -ErrorAction Stop
            if($sourceItem.PSIsContainer-or($sourceItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Stranded Hub input source became unsafe before staging: '+[string]$plan.Source)}
            $before=(Get-FileHash -LiteralPath ([string]$plan.Source) -Algorithm SHA256).Hash.ToLowerInvariant()
            if($before-ne[string]$plan.Sha256){throw('Stranded Hub input changed before staging: '+[string]$plan.Source)}
            $tmp=([string]$plan.Destination)+'.stage.'+[guid]::NewGuid().ToString('N')
            $plan.Stage=$tmp
            Copy-Item -LiteralPath ([string]$plan.Source) -Destination $tmp -Force
            $copied=(Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash.ToLowerInvariant()
            $after=(Get-FileHash -LiteralPath ([string]$plan.Source) -Algorithm SHA256).Hash.ToLowerInvariant()
            if($copied-ne$before-or$after-ne$before){throw('Stranded Hub input changed while it was staged: '+[string]$plan.Source)}
        }

        # Phase 3: revalidate the complete plan immediately before the publication boundary.
        foreach($plan in @($plans)){
            $sourceItem=Get-Item -LiteralPath ([string]$plan.Source) -Force -ErrorAction Stop
            if($sourceItem.PSIsContainer-or($sourceItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Stranded Hub input source became unsafe before handoff commit: '+[string]$plan.Source)}
            if((Get-FileHash -LiteralPath ([string]$plan.Source) -Algorithm SHA256).Hash.ToLowerInvariant()-ne[string]$plan.Sha256){throw('Stranded Hub input changed before handoff commit: '+[string]$plan.Source)}
            if([bool]$plan.AlreadyPresent){
                $destItem=Get-Item -LiteralPath ([string]$plan.Destination) -Force -ErrorAction Stop
                if($destItem.PSIsContainer-or($destItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Existing stranded Hub input destination became unsafe before handoff commit: '+[string]$plan.Destination)}
                if((Get-FileHash -LiteralPath ([string]$plan.Destination) -Algorithm SHA256).Hash.ToLowerInvariant()-ne[string]$plan.Sha256){throw('Existing stranded Hub input destination changed before handoff commit: '+[string]$plan.Destination)}
            }else{
                if(Test-Path -LiteralPath ([string]$plan.Destination)){throw('Stranded Hub input destination became occupied before handoff commit: '+[string]$plan.Destination)}
                $stageItem=Get-Item -LiteralPath ([string]$plan.Stage) -Force -ErrorAction Stop
                if($stageItem.PSIsContainer-or($stageItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Stranded Hub input stage is unsafe before handoff commit: '+[string]$plan.Stage)}
                if((Get-FileHash -LiteralPath ([string]$plan.Stage) -Algorithm SHA256).Hash.ToLowerInvariant()-ne[string]$plan.Sha256){throw('Stranded Hub input stage changed before handoff commit: '+[string]$plan.Stage)}
            }
        }

        # Phase 4: publish missing destinations. If any publication fails, roll back only
        # destinations created by this invocation while all global sources are still intact.
        $published=New-Object System.Collections.ArrayList
        try{
            foreach($plan in @($plans)){
                if([bool]$plan.AlreadyPresent){continue}
                # Fresh per-entry commit-boundary revalidation protects later entries in the batch.
                $sourceItem=Get-Item -LiteralPath ([string]$plan.Source) -Force -ErrorAction Stop
                if($sourceItem.PSIsContainer-or($sourceItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Stranded Hub input source became unsafe at handoff commit: '+[string]$plan.Source)}
                if((Get-FileHash -LiteralPath ([string]$plan.Source) -Algorithm SHA256).Hash.ToLowerInvariant()-ne[string]$plan.Sha256){throw('Stranded Hub input changed at handoff commit: '+[string]$plan.Source)}
                if(Test-Path -LiteralPath ([string]$plan.Destination)){throw('Stranded Hub input destination became occupied at handoff commit: '+[string]$plan.Destination)}
                $stageItem=Get-Item -LiteralPath ([string]$plan.Stage) -Force -ErrorAction Stop
                if($stageItem.PSIsContainer-or($stageItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Stranded Hub input stage became unsafe at handoff commit: '+[string]$plan.Stage)}
                if((Get-FileHash -LiteralPath ([string]$plan.Stage) -Algorithm SHA256).Hash.ToLowerInvariant()-ne[string]$plan.Sha256){throw('Stranded Hub input stage changed at handoff commit: '+[string]$plan.Stage)}
                Publish-CompletedFileAtomically ([string]$plan.Stage) ([string]$plan.Destination)
                $plan.Stage=''
                $destItem=Get-Item -LiteralPath ([string]$plan.Destination) -Force -ErrorAction Stop
                if($destItem.PSIsContainer-or($destItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('Published stranded Hub input destination is unsafe: '+[string]$plan.Destination)}
                if((Get-FileHash -LiteralPath ([string]$plan.Destination) -Algorithm SHA256).Hash.ToLowerInvariant()-ne[string]$plan.Sha256){throw('Published stranded Hub input destination failed hash verification: '+[string]$plan.Destination)}
                $plan.PublishedByThisRun=$true
                [void]$published.Add($plan)
            }
        }catch{
            $publicationError=$_.Exception.Message
            $rollbackFailures=New-Object System.Collections.ArrayList
            for($i=$published.Count-1;$i-ge0;$i--){
                $plan=$published[$i]
                try{
                    if(Test-Path -LiteralPath ([string]$plan.Destination)){
                        $destItem=Get-Item -LiteralPath ([string]$plan.Destination) -Force -ErrorAction Stop
                        if($destItem.PSIsContainer-or($destItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){throw('rollback destination is unsafe: '+[string]$plan.Destination)}
                        $destHash=(Get-FileHash -LiteralPath ([string]$plan.Destination) -Algorithm SHA256).Hash.ToLowerInvariant()
                        if($destHash-ne[string]$plan.Sha256){throw('rollback destination hash is ambiguous: '+[string]$plan.Destination)}
                        Remove-Item -LiteralPath ([string]$plan.Destination) -Force -ErrorAction Stop
                    }
                }catch{[void]$rollbackFailures.Add($_.Exception.Message)}
            }
            if($rollbackFailures.Count-ne0){
                throw('Stranded global Hub input destination publication failed and rollback was incomplete; partial per-instance handoff may be durable. Global sources were preserved. publication_error='+$publicationError+'; rollback_errors='+([string]::Join(' | ',@($rollbackFailures))))
            }
            throw('Stranded global Hub input destination publication failed before handoff commit; all destinations created by this invocation were rolled back and global sources were preserved. publication_error='+$publicationError)
        }
    }finally{
        foreach($plan in @($plans)){
            if(-[string]::IsNullOrWhiteSpace([string]$plan.Stage)-and(Test-Path -LiteralPath ([string]$plan.Stage))){Remove-Item -LiteralPath ([string]$plan.Stage) -Force -ErrorAction SilentlyContinue}
        }
    }

    $handoff=[pscustomobject]@{Entries=@($plans|ForEach-Object{[pscustomobject]@{Source=[string]$_.Source;Destination=[string]$_.Destination;Sha256=[string]$_.Sha256;InstanceId=[string]$_.InstanceId;Kind=[string]$_.Kind}})}
    try{
        return Complete-GlobalHubInputActivationHandoff $handoff
    }catch{
        throw('Stranded global Hub input destinations committed, but global source cleanup failed. Per-instance destination bytes are authoritative for this handoff; preserve remaining global sources and re-run Initialize instance registry for idempotent cleanup. '+$_.Exception.Message)
    }
}
'@
$newRuntime=$runtime.Substring(0,$fn.Extent.StartOffset)+$newFunction.TrimEnd("`r","`n")+$runtime.Substring($fn.Extent.EndOffset)
Write-Utf8 $runtimePath $newRuntime
$null=Parse-Ast $runtimePath

# -----------------------------------------------------------------------------
# State machine + executable entry model: one additional mixed-invalid pending
# state/action pair. This deliberately makes the process-entry contract 102.
# -----------------------------------------------------------------------------
$machine=Read-Json $machinePath
if(@($machine.states|Where-Object{[string]$_.id-ceq'REGISTRY_PENDING_GLOBAL_INVALID'}).Count-ne0){Fail 'R9 state already exists unexpectedly.'}
$machine.states=@($machine.states)+@([pscustomobject][ordered]@{
    id='REGISTRY_PENDING_GLOBAL_INVALID';description='Registry is healthy while the global Manager inbox contains a mixed batch: an earlier valid identity-bound Hub input and a later recognized but invalid Hub input.'
})
if(@($machine.rules|Where-Object{[string]$_.id-ceq'R-REGISTRY-PENDING-GLOBAL-INVALID-INIT'}).Count-ne0){Fail 'R9 state-machine rule already exists unexpectedly.'}
$machine.rules=@($machine.rules)+@([pscustomobject][ordered]@{
    id='R-REGISTRY-PENDING-GLOBAL-INVALID-INIT';states=@('REGISTRY_PENDING_GLOBAL_INVALID');operation='InitializeRegistry';priority=190;outcome='reject_fail_closed';
    invariants=@('MH-INBOX-001','MH-COMMIT-001','MH-LIFECYCLE-001');reason='Existing-registry reconciliation must validate the complete stranded-input batch before publishing any per-instance destination; a later invalid input must leave all global sources and per-instance lifecycle state unchanged.'
})
Write-Json $machinePath $machine 100

$model=Read-Json $entryModelPath
if(@($model.states|Where-Object{[string]$_.id-ceq'REGISTRY_PENDING_GLOBAL_INVALID'}).Count-ne0){Fail 'R9 entry state already exists unexpectedly.'}
$model.states=@($model.states)+@([pscustomobject][ordered]@{
    id='REGISTRY_PENDING_GLOBAL_INVALID';fixture='registry_pending_global_mixed_invalid';description='Registry is healthy while the global Manager inbox contains a valid A input followed by a recognized invalid Z input; initialization must reject without partial per-instance publication.'
})
if(@($model.coverage_requirements|Where-Object{[string]$_.id-ceq'CR-REGISTRY-INIT-PENDING-GLOBAL-MIXED-INVALID'}).Count-ne0){Fail 'R9 entry requirement already exists unexpectedly.'}
$model.coverage_requirements=@($model.coverage_requirements)+@([pscustomobject][ordered]@{
    id='CR-REGISTRY-INIT-PENDING-GLOBAL-MIXED-INVALID';states=@('REGISTRY_PENDING_GLOBAL_INVALID');actions=@('InitializeInstanceRegistry');expected_mode='registry_init_mixed_invalid_rejected_without_partial_handoff'
})
$model.freeze_rule=([string]$model.freeze_rule).TrimEnd()+ ' A mixed valid/invalid pending-global batch must fail before any valid object is published into a per-instance inbox; both global sources must remain and all Hub lifecycle state must remain unchanged.'
Write-Json $entryModelPath $model 80

# -----------------------------------------------------------------------------
# Permanent matrix fixture + oracle for MGR-DEF-0032.
# -----------------------------------------------------------------------------
$matrix=[IO.File]::ReadAllText($matrixPath,[Text.Encoding]::UTF8)
$matrix=Replace-Once $matrix '$script:ScenarioPendingGlobalSource=$null;$script:ScenarioPendingGlobalTarget=$null;$script:ScenarioPendingGlobalSha=$null' '$script:ScenarioPendingGlobalSource=$null;$script:ScenarioPendingGlobalTarget=$null;$script:ScenarioPendingGlobalSha=$null;$script:ScenarioPendingGlobalInvalidSource=$null' 'R9 matrix state variables'
$oldFixture="            'registry_pending_global' {`$name='Keelaryn__Hub_APPROVED_entry-reachability.zip';`$dst=Join-Path `$globalInbox `$name;Copy-Item -LiteralPath `$alphaCurrent -Destination `$dst -Force;`$script:ScenarioPendingGlobalSource=`$dst;`$script:ScenarioPendingGlobalTarget=Join-Path `$alphaInbox `$name;`$script:ScenarioPendingGlobalSha=(Get-FileHash -LiteralPath `$dst -Algorithm SHA256).Hash.ToLowerInvariant()}`r`n            'registry_pending_instance'"
$newFixture="            'registry_pending_global' {`$name='Keelaryn__Hub_APPROVED_entry-reachability.zip';`$dst=Join-Path `$globalInbox `$name;Copy-Item -LiteralPath `$alphaCurrent -Destination `$dst -Force;`$script:ScenarioPendingGlobalSource=`$dst;`$script:ScenarioPendingGlobalTarget=Join-Path `$alphaInbox `$name;`$script:ScenarioPendingGlobalSha=(Get-FileHash -LiteralPath `$dst -Algorithm SHA256).Hash.ToLowerInvariant()}`r`n            'registry_pending_global_mixed_invalid' {`$validName='Keelaryn__Hub_APPROVED_A_entry-reachability.zip';`$invalidName='Keelaryn__Hub_APPROVED_Z_entry-reachability.zip';`$valid=Join-Path `$globalInbox `$validName;`$invalid=Join-Path `$globalInbox `$invalidName;Copy-Item -LiteralPath `$alphaCurrent -Destination `$valid -Force;Write-Utf8 `$invalid 'not-a-valid-hub-zip';`$script:ScenarioPendingGlobalSource=`$valid;`$script:ScenarioPendingGlobalInvalidSource=`$invalid;`$script:ScenarioPendingGlobalTarget=Join-Path `$alphaInbox `$validName;`$script:ScenarioPendingGlobalSha=(Get-FileHash -LiteralPath `$valid -Algorithm SHA256).Hash.ToLowerInvariant()}`r`n            'registry_pending_instance'"
if(-not$matrix.Contains($oldFixture)){# tolerate LF-normalized checkout
    $oldFixture=$oldFixture.Replace("`r`n","`n");$newFixture=$newFixture.Replace("`r`n","`n")
}
$matrix=Replace-Once $matrix $oldFixture $newFixture 'R9 matrix mixed-invalid fixture'
$oldMode="                'registry_init_reconciles_global_input' {`$sourceConsumed=(`$script:ScenarioPendingGlobalSource-and-not(Test-Path -LiteralPath `$script:ScenarioPendingGlobalSource -PathType Leaf));`$targetOk=`$false;if(`$script:ScenarioPendingGlobalTarget-and(Test-Path -LiteralPath `$script:ScenarioPendingGlobalTarget -PathType Leaf)){`$targetOk=((Get-FileHash -LiteralPath `$script:ScenarioPendingGlobalTarget -Algorithm SHA256).Hash.ToLowerInvariant()-ceq[string]`$script:ScenarioPendingGlobalSha)};`$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$controlStateUnchanged-and`$compatBaselineAfter-ceq`$compatBaselineBefore-and`$sourceConsumed-and`$targetOk-and`$r.Text.Contains('Reconciled 1 identity-bound Hub input(s)'));`$detail=if(`$pass){'InitializeInstanceRegistry moved the validated identity-bound global input into the active registered per-instance inbox while preserving registry/active/baseline state'}else{'pending-global Initialize reconciliation proof failed: '+`$r.Text}}`r`n                'fail_closed'"
$newMode="                'registry_init_reconciles_global_input' {`$sourceConsumed=(`$script:ScenarioPendingGlobalSource-and-not(Test-Path -LiteralPath `$script:ScenarioPendingGlobalSource -PathType Leaf));`$targetOk=`$false;if(`$script:ScenarioPendingGlobalTarget-and(Test-Path -LiteralPath `$script:ScenarioPendingGlobalTarget -PathType Leaf)){`$targetOk=((Get-FileHash -LiteralPath `$script:ScenarioPendingGlobalTarget -Algorithm SHA256).Hash.ToLowerInvariant()-ceq[string]`$script:ScenarioPendingGlobalSha)};`$pass=(`$r.ExitCode-eq0-and`$hubsUnchanged-and`$controlStateUnchanged-and`$compatBaselineAfter-ceq`$compatBaselineBefore-and`$sourceConsumed-and`$targetOk-and`$r.Text.Contains('Reconciled 1 identity-bound Hub input(s)'));`$detail=if(`$pass){'InitializeInstanceRegistry moved the validated identity-bound global input into the active registered per-instance inbox while preserving registry/active/baseline state'}else{'pending-global Initialize reconciliation proof failed: '+`$r.Text}}`r`n                'registry_init_mixed_invalid_rejected_without_partial_handoff' {`$validSourceRemains=(`$script:ScenarioPendingGlobalSource-and(Test-Path -LiteralPath `$script:ScenarioPendingGlobalSource -PathType Leaf));`$invalidSourceRemains=(`$script:ScenarioPendingGlobalInvalidSource-and(Test-Path -LiteralPath `$script:ScenarioPendingGlobalInvalidSource -PathType Leaf));`$targetAbsent=(`$script:ScenarioPendingGlobalTarget-and-not(Test-Path -LiteralPath `$script:ScenarioPendingGlobalTarget));`$pass=(`$r.ExitCode-ne0-and`$hubsUnchanged-and`$lifecycleStateUnchanged-and`$validSourceRemains-and`$invalidSourceRemains-and`$targetAbsent);`$detail=if(`$pass){'mixed valid/invalid stranded-input batch failed before any per-instance destination publication and preserved both global sources plus Hub lifecycle state'}else{'mixed pending-global atomicity proof failed: '+`$r.Text}}`r`n                'fail_closed'"
if(-not$matrix.Contains($oldMode)){$oldMode=$oldMode.Replace("`r`n","`n");$newMode=$newMode.Replace("`r`n","`n")}
$matrix=Replace-Once $matrix $oldMode $newMode 'R9 matrix atomicity oracle'
Write-Utf8 $matrixPath $matrix
$null=Parse-Ast $matrixPath

# -----------------------------------------------------------------------------
# Cross-model validator: exact 102 contract and new fail-closed Initialize mode.
# -----------------------------------------------------------------------------
$v=[IO.File]::ReadAllText($entryValidatorPath,[Text.Encoding]::UTF8)
$v=Replace-Once $v "'REGISTRY_PENDING_GLOBAL','REGISTRY_PENDING_INSTANCE','REGISTRY_ACTIVE_METADATA_INVALID'" "'REGISTRY_PENDING_GLOBAL','REGISTRY_PENDING_GLOBAL_INVALID','REGISTRY_PENDING_INSTANCE','REGISTRY_ACTIVE_METADATA_INVALID'" 'R9 validator required state'
$v=Replace-Once $v "'registry_init_reconciles_global_input') -cnotcontains `$reqMode" "'registry_init_reconciles_global_input','registry_init_mixed_invalid_rejected_without_partial_handoff') -cnotcontains `$reqMode" 'R9 validator expected-mode allowlist'
$v=Replace-Once $v "foreach(`$sid in @('REGISTRY_HEALTHY','REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_INSTANCE','REGISTRY_PENDING_GLOBAL')){if(-not`$pairs.Contains(`$sid+'|InitializeInstanceRegistry')){Fail('Existing-registry Initialize coverage omitted '+`$sid)}}" "foreach(`$sid in @('REGISTRY_HEALTHY','REGISTRY_INACTIVE_HUB_MISSING','REGISTRY_INACTIVE_HUB_CORRUPT','REGISTRY_PENDING_INSTANCE','REGISTRY_PENDING_GLOBAL','REGISTRY_PENDING_GLOBAL_INVALID')){if(-not`$pairs.Contains(`$sid+'|InitializeInstanceRegistry')){Fail('Existing-registry Initialize coverage omitted '+`$sid)}}" 'R9 validator Initialize coverage'
$v=Replace-Once $v "if(`$pairs.Count-lt101){Fail('Entry-reachability cross-product is unexpectedly small: '+`$pairs.Count)}" "if(`$pairs.Count-ne102){Fail('Entry-reachability cross-product must be exactly 102 after MGR-DEF-0032 regression; actual='+`$pairs.Count)}" 'R9 validator exact count'
$v=Replace-Once $v "elseif(`$mode-ceq'registry_init_reconciles_global_input'){if(`$outcome-cne'reconcile_identity_bound_global_inputs_then_report_initialized'){Fail('Pending-global Initialize oracle/state-machine mismatch: '+`$outcome)}}`r`n    else" "elseif(`$mode-ceq'registry_init_reconciles_global_input'){if(`$outcome-cne'reconcile_identity_bound_global_inputs_then_report_initialized'){Fail('Pending-global Initialize oracle/state-machine mismatch: '+`$outcome)}}`r`n    elseif(`$mode-ceq'registry_init_mixed_invalid_rejected_without_partial_handoff'){if(`$outcome-cne'reject_fail_closed'){Fail('Mixed-invalid pending-global Initialize oracle/state-machine mismatch: '+`$outcome)}}`r`n    else" 'R9 validator state-machine outcome'
if(-not$v.Contains('mixed valid/invalid pending-global batch')){
    $v=Replace-Once $v "if(-not([string]`$model.freeze_rule).Contains('pending-global must prove identity-bound transfer')){Fail 'Freeze rule must require executable existing-registry Initialize semantics.'}" "if(-not([string]`$model.freeze_rule).Contains('pending-global must prove identity-bound transfer')){Fail 'Freeze rule must require executable existing-registry Initialize semantics.'}`r`nif(-not([string]`$model.freeze_rule).Contains('mixed valid/invalid pending-global batch')){Fail 'Freeze rule must require mixed-invalid pending-global atomicity.'}" 'R9 validator freeze rule'
}
Write-Utf8 $entryValidatorPath $v
$null=Parse-Ast $entryValidatorPath

# -----------------------------------------------------------------------------
# Engineering knowledge: MGR-DEF-0032 and risk mapping.
# -----------------------------------------------------------------------------
$defects=Read-Json $defectPath
if(@($defects.defects|Where-Object{[string]$_.id-ceq'MGR-DEF-0032'}).Count-ne0){Fail 'MGR-DEF-0032 already exists unexpectedly.'}
$defects.defects=@($defects.defects)+@([pscustomobject][ordered]@{
    id='MGR-DEF-0032';title='Existing-registry stranded-input reconciliation publishes an earlier valid destination before a later invalid input is validated';severity='P1';status='fixed';release_blocker=$true;detected_in='4.17.13';detected_stage='prefreeze_adversarial_state_machine_review';
    defect_class='multi-input transaction preflight / partial durable inbox handoff';affected_surfaces=@('S-RUNTIME-INBOX');
    preconditions='A valid multi-Hub registry exists and the global Manager inbox contains at least two recognized Hub-owned objects ordered so that a valid identity-bound input is processed before a later invalid input.';
    bad_behavior='Reconcile-StrandedGlobalHubInputsForExistingRegistry validates and publishes each destination in one loop. A valid first input is copied into the active per-instance inbox before validation of a later invalid input fails, leaving partial durable/discoverable lifecycle mutation while the command reports failure and global sources remain.';
    root_cause='Failure-prone identity, registration, destination and collision validation was interleaved with authoritative per-instance destination publication instead of being completed for the whole batch before the first commit. Single-input ER-101 could not expose this multi-input transaction boundary.';
    root_cause_classes=@('RC-COMMIT-001','RC-PUBLISH-001','RC-REACHABILITY-001');violated_invariants=@('MH-INBOX-001','MH-COMMIT-001','MH-LIFECYCLE-001');related_defects=@('MGR-DEF-0031');
    permanent_regressions=@('tools/Invoke-ManagerEntryReachabilityMatrix.ps1');planned_regressions=@();fixed_in='4.17.13';evidence=@(
        [pscustomobject][ordered]@{type='prefreeze_atomicity_red_run';id='34858872734'},
        [pscustomobject][ordered]@{type='prefreeze_atomicity_red_job';id='104025497974'},
        [pscustomobject][ordered]@{type='prefreeze_atomicity_red_artifact';id='10354056744'},
        [pscustomobject][ordered]@{type='prefreeze_atomicity_red_artifact_sha256';id='6530ae9bbb912bfd8060918b923ff267efe31665c0f5889c2f3a5d87b61c7960'},
        [pscustomobject][ordered]@{type='prefreeze_atomicity_red_summary';id='exact c7cf09d7: valid A destination was published before invalid Z identity validation failed; both global sources remained; harness_error=false'},
        [pscustomobject][ordered]@{type='source_symbol';id='Reconcile-StrandedGlobalHubInputsForExistingRegistry'}
    )
})
Write-Json $defectPath $defects 90

$risk=Read-Json $riskPath
$surface=@($risk.surfaces|Where-Object{[string]$_.id-ceq'S-RUNTIME-INBOX'})
if($surface.Count-ne1){Fail('S-RUNTIME-INBOX count='+$surface.Count)}
Add-UniqueString $surface[0] 'symbols' 'Complete-GlobalHubInputActivationHandoff'
Add-UniqueString $surface[0] 'root_cause_classes' 'RC-COMMIT-001'
Add-UniqueString $surface[0] 'root_cause_classes' 'RC-PUBLISH-001'
Add-UniqueString $surface[0] 'state_machine_rules' 'R-REGISTRY-PENDING-GLOBAL-INVALID-INIT'
Add-UniqueString $surface[0] 'regressions' 'tools/Invoke-ManagerEntryReachabilityMatrix.ps1'
Write-Json $riskPath $risk 100

# -----------------------------------------------------------------------------
# Permanent metadata consistency guard. It already reads development state, but c7
# proved that it did not bind state.materialization identity to manifest/provenance.
# Add the invariant, then deliberately prove RED before synchronizing state.
# -----------------------------------------------------------------------------
$meta=[IO.File]::ReadAllText($metadataVerifierPath,[Text.Encoding]::UTF8)
$oldMeta="    `$expectedBaseline=([string]`$state.lineage.production_manager_version).Trim()`r`n    if(`$baselineVersion-cne`$expectedBaseline){Fail('PUBLIC_PROVENANCE baseline mismatch for active development line: provenance='+`$baselineVersion+' production='+`$expectedBaseline)}"
$newMeta="    `$expectedBaseline=([string]`$state.lineage.production_manager_version).Trim()`r`n    if(`$baselineVersion-cne`$expectedBaseline){Fail('PUBLIC_PROVENANCE baseline mismatch for active development line: provenance='+`$baselineVersion+' production='+`$expectedBaseline)}`r`n    `$stateMaterializationVersion=([string]`$state.materialization.manager_version).Trim()`r`n    if(`$stateMaterializationVersion-cne`$version){Fail('MANAGER_DEVELOPMENT_STATE materialization version mismatch: state='+`$stateMaterializationVersion+' install='+`$version)}`r`n    `$stateInstall=Normalized-Optional `$state.materialization.installation_sha256`r`n    if(`$stateInstall-cne`$manifestInstall){Fail('MANAGER_DEVELOPMENT_STATE installation identity mismatch: state='+`$stateInstall+' manifest='+`$manifestInstall)}`r`n    `$stateManaged=Normalized-Optional `$state.materialization.managed_content_sha256`r`n    if(`$stateManaged-cne`$manifestManaged){Fail('MANAGER_DEVELOPMENT_STATE managed identity mismatch: state='+`$stateManaged+' manifest='+`$manifestManaged)}"
if(-not$meta.Contains($oldMeta)){$oldMeta=$oldMeta.Replace("`r`n","`n");$newMeta=$newMeta.Replace("`r`n","`n")}
$meta=Replace-Once $meta $oldMeta $newMeta 'R9 metadata identity guard'
Write-Utf8 $metadataVerifierPath $meta
$null=Parse-Ast $metadataVerifierPath

# Product bytes changed; regenerate authoritative public identity first.
$null=Invoke-Child $manifestBuilder @('-RepositoryRoot',$RepositoryRoot,'-Write') 'PUBLIC_FILE_MANIFEST regeneration'
$null=Invoke-Child $manifestBuilder @('-RepositoryRoot',$RepositoryRoot,'-Check') 'PUBLIC_FILE_MANIFEST reproducibility'
$manifest=Read-Json $manifestPath
if([string]$manifest.manager.version-cne'4.17.13'){Fail 'R9 manifest Manager version mismatch.'}

# Synchronize provenance first while intentionally keeping MANAGER_DEVELOPMENT_STATE stale
# for one verifier invocation. This is the RED proof for the new cross-file guard.
$provenance=Read-Json $provenancePath
$provenance.source_manager_installation_sha256=[string]$manifest.manager.installation_sha256
$provenance.source_manager_gate_managed_content_sha256=[string]$manifest.manager.gate_managed_content_sha256
$provenance.candidate_identity.validated_development_parent=$ExpectedBase
$dev=$provenance.qualification_evidence.development_4_17_13
$dev.entry_reachability_scenarios=102
Set-Property $dev 'prefreeze_atomicity_fix' ([pscustomobject][ordered]@{
    defect_id='MGR-DEF-0032';status='materialized_unqualified_development';red_run_id=34858872734;red_job_id=104025497974;red_artifact_id=10354056744;
    red_artifact_sha256='6530ae9bbb912bfd8060918b923ff267efe31665c0f5889c2f3a5d87b61c7960';fix='batch-wide preflight + staging + commit-boundary revalidation + rollback of newly published destinations + explicit post-commit source-cleanup outcome';exact_green_requalification='required_before_freeze'
})
Write-Json $provenancePath $provenance 90

$red=Invoke-Child $metadataVerifierPath @('-RepositoryRoot',$RepositoryRoot) 'Metadata identity guard RED proof' -AllowFailure
if($red.ExitCode-eq0){Fail 'Metadata identity guard RED proof unexpectedly passed stale MANAGER_DEVELOPMENT_STATE materialization identity.'}
if(-not$red.Text.Contains('MANAGER_DEVELOPMENT_STATE managed identity mismatch')){Fail('Metadata identity guard RED proof failed for the wrong reason: '+$red.Text)}
Write-Utf8 (Join-Path $EvidenceRoot 'METADATA_IDENTITY_GUARD_RED.txt') ($red.Text+"`n")

# Now synchronize volatile development-state identity to the exact new public manifest.
$state=Read-Json $statePath
$state.materialization.manager_version='4.17.13'
$state.materialization.installation_sha256=[string]$manifest.manager.installation_sha256
$state.materialization.managed_content_sha256=[string]$manifest.manager.gate_managed_content_sha256
$state.materialization.status='materialized_unqualified_development_live_branch'
$succ=$state.qualification.successor_4_17_13
$succ.status='materialized_unqualified_development_prefreeze_atomicity_fix'
$succ.process_entry_green_proof='R9 requires exact 102-scenario process-entry PASS including mixed-invalid pending-global atomicity, 29-mode completeness, state-machine/oracle consistency and complete non-default risk mapping'
$state.next_exact_goal.description='Obtain exact-head Development Validation with 29-mode entry-policy completeness, 102-scenario process-entry PASS including MGR-DEF-0032 atomicity, state-machine/oracle consistency and complete non-default state-machine risk mapping; then full-successor Risk/Defect Gate and clean semantic pre-freeze review.'
$state.next_exact_goal.candidate_freeze_permitted=$false
Write-Json $statePath $state 90

$green=Invoke-Child $metadataVerifierPath @('-RepositoryRoot',$RepositoryRoot) 'Metadata identity guard GREEN proof'
Write-Utf8 (Join-Path $EvidenceRoot 'METADATA_IDENTITY_GUARD_GREEN.txt') ($green.Text+"`n")

# Parse all modified PowerShell and leave a compact materialization receipt.
foreach($p in @($runtimePath,$matrixPath,$entryValidatorPath,$metadataVerifierPath)){$null=Parse-Ast $p}
$receipt=[ordered]@{
    schema='keelaryn.manager-41713-atomicity-r9-materialization.v1';base=$ExpectedBase;manager_version='4.17.13';defect_id='MGR-DEF-0032';
    entry_scenarios=102;installation_sha256=[string]$manifest.manager.installation_sha256;managed_content_sha256=[string]$manifest.manager.gate_managed_content_sha256;
    metadata_guard_red='pass';metadata_guard_green='pass';candidate_issued=$false;completed_utc=[DateTime]::UtcNow.ToString('o')
}
Write-Json (Join-Path $EvidenceRoot 'R9_MATERIALIZATION.json') $receipt 20
Write-Host ('Manager 4.17.13 R9 materialization: PASS; managed='+[string]$manifest.manager.gate_managed_content_sha256) -ForegroundColor Green
