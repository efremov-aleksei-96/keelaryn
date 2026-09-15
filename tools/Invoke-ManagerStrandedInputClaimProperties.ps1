[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [string]$OutputPath=''
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){$parent=Split-Path -Parent $Path;if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null};[IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)}
function Write-Json([string]$Path,$Object){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth 40).Replace("`r`n","`n"))+"`n")}
function Copy-ManagedManager([string]$SourceManager,[string]$DestinationManager){
    $install=Get-Content -LiteralPath (Join-Path $SourceManager 'product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if([string]$install.schema-cne'keelaryn.manager.installation.v2'){Fail 'Unsupported Manager installation schema.'}
    New-Item -ItemType Directory -Force -Path $DestinationManager|Out-Null
    foreach($raw in @($install.managed_files)){$rel=([string]$raw).Replace('/','\');$src=Join-Path $SourceManager $rel;$dst=Join-Path $DestinationManager $rel;if(-not(Test-Path -LiteralPath $src -PathType Leaf)){Fail('Managed source missing: '+$rel)};$parent=Split-Path -Parent $dst;if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null};Copy-Item -LiteralPath $src -Destination $dst -Force}
    return [string]$install.manager_version
}
function Copy-DirectoryExact([string]$Source,[string]$Destination){if(-not(Test-Path -LiteralPath $Source -PathType Container)){Fail('Snapshot source missing: '+$Source)};if(Test-Path -LiteralPath $Destination){Remove-Item -LiteralPath $Destination -Recurse -Force};$parent=Split-Path -Parent $Destination;if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null};Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force}
function Invoke-Runtime([string]$Runtime,[string[]]$Arguments){if($null-eq$Arguments){$Arguments=@()};$exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference;try{$ErrorActionPreference='Continue';$output=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Runtime @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old};return [pscustomobject]@{ExitCode=$code;Output=@($output);Text=[string]::Join("`n",@($output))}}
function Invoke-Required([string]$Runtime,[string[]]$Arguments,[string]$Purpose){$r=Invoke-Runtime $Runtime $Arguments;foreach($line in @($r.Output)){Write-Host $line};if($r.ExitCode-ne0){Fail($Purpose+' failed; exit='+$r.ExitCode+'; output='+$r.Text)};return $r}
function Read-Registry([string]$ManagerRoot){return Get-Content -LiteralPath (Join-Path $ManagerRoot 'state\instances.json') -Raw -Encoding UTF8|ConvertFrom-Json}
function Assert-PowerShellParses([string]$Path,[string]$Purpose){$tokens=$null;$errors=$null;[void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors);if(@($errors).Count){Fail($Purpose+' parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}}
function Get-TreeDigest([string]$Root){if(-not(Test-Path -LiteralPath $Root -PathType Container)){return 'missing'};$rows=New-Object System.Collections.ArrayList;foreach($f in @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force|Sort-Object FullName)){$rel=$f.FullName.Substring($Root.Length).TrimStart('\').Replace('\','/');$h=(Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant();[void]$rows.Add($rel+'='+$h)};$sha=[Security.Cryptography.SHA256]::Create();try{return([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]::Join("`n",@($rows))))).Replace('-','').ToLowerInvariant())}finally{$sha.Dispose()}}
function Test-FileSha([string]$Path,[string]$Sha){return (Test-Path -LiteralPath $Path -PathType Leaf)-and((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()-ceq$Sha)}
function Set-ClaimFaultInstrumentation([string]$Runtime){
    $text=[IO.File]::ReadAllText($Runtime,[Text.Encoding]::UTF8)
    $claimed=@'
    $meta.sha256=[string]$identity.Sha256;$meta.instance_id=[string]$identity.InstanceId;$meta.state='claimed';$meta.updated_utc=(Get-Date).ToUniversalTime().ToString('o')
    Write-HubInputReconciliationClaimMetadata ([string]$Claim.Directory) $meta
'@
    if([regex]::Matches($text,[regex]::Escape($claimed)).Count-ne1){Fail 'Claimed-payload instrumentation anchor mismatch.'}
    $claimedProbe=@'
    $meta.sha256=[string]$identity.Sha256;$meta.instance_id=[string]$identity.InstanceId;$meta.state='claimed';$meta.updated_utc=(Get-Date).ToUniversalTime().ToString('o')
    Write-HubInputReconciliationClaimMetadata ([string]$Claim.Directory) $meta
    if([string]$env:KEELARYN_TRANSACTION_PROPERTY_FAULT-ceq'stop-after-claim'){throw 'TRANSACTION_PROPERTY_STOP_AFTER_CLAIM'}
    if([string]$env:KEELARYN_TRANSACTION_PROPERTY_FAULT-ceq'replace-source-after-claim'){
        $replacement=Join-Path $Inbox ([string]$Claim.OriginalName)
        [IO.File]::WriteAllText($replacement,'transaction-property-foreign-bytes',(New-Object Text.UTF8Encoding($false)))
        throw 'TRANSACTION_PROPERTY_SOURCE_REPLACED_AFTER_CLAIM'
    }
'@
    $text=$text.Replace($claimed,$claimedProbe)
    $commitAnchor='    # Fresh commit-boundary validation: authoritative registry row/path, exact claimed payload, and destination vacancy.'
    if([regex]::Matches($text,[regex]::Escape($commitAnchor)).Count-ne1){Fail 'Commit-boundary instrumentation anchor mismatch.'}
    $commitProbe=@'
    if([string]$env:KEELARYN_TRANSACTION_PROPERTY_FAULT-ceq'drift-registry-before-commit'){
        $faultRegistry=Get-Content -LiteralPath $script:InstanceRegistryFile -Raw -Encoding UTF8|ConvertFrom-Json
        $faultRows=@($faultRegistry.instances|Where-Object{[string]$_.instance_id-ceq[string]$identity.InstanceId})
        if($faultRows.Count-ne1){throw 'TRANSACTION_PROPERTY_REGISTRY_DRIFT_TARGET_MISSING'}
        $faultRows[0].vault_path=[string]$env:KEELARYN_TRANSACTION_PROPERTY_AUX
        [IO.File]::WriteAllText($script:InstanceRegistryFile,(($faultRegistry|ConvertTo-Json -Depth 12).Replace("`r`n","`n")+"`n"),(New-Object Text.UTF8Encoding($false)))
    }
'@
    $text=$text.Replace($commitAnchor,$commitProbe+$commitAnchor)
    $publishAnchor='        [IO.File]::Move([string]$Claim.Payload,$destination);$committed=$true'
    if([regex]::Matches($text,[regex]::Escape($publishAnchor)).Count-ne1){Fail 'Post-commit instrumentation anchor mismatch.'}
    $publishProbe=$publishAnchor+"`r`n        if([string]`$env:KEELARYN_TRANSACTION_PROPERTY_FAULT-ceq'fail-after-destination-commit'){throw 'TRANSACTION_PROPERTY_POSTCOMMIT_FAILURE'}"
    $text=$text.Replace($publishAnchor,$publishProbe)
    Write-Utf8 $Runtime $text;Assert-PowerShellParses $Runtime 'Claim-property instrumented runtime'
}
function Get-TestClaims([string]$ManagerRoot){
    $root=Join-Path $ManagerRoot 'state\reconciliation\hub-inputs';$rows=New-Object System.Collections.ArrayList
    if(-not(Test-Path -LiteralPath $root -PathType Container)){return @($rows)}
    foreach($dir in @(Get-ChildItem -LiteralPath $root -Directory -Force|Sort-Object Name)){
        $metaPath=Join-Path $dir.FullName 'claim.json';if(-not(Test-Path -LiteralPath $metaPath -PathType Leaf)){Fail('Test claim metadata missing: '+$metaPath)}
        $meta=Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8|ConvertFrom-Json;$payload=Join-Path (Join-Path $dir.FullName 'payload') ([string]$meta.original_name)
        [void]$rows.Add([pscustomobject]@{Directory=$dir.FullName;Metadata=$meta;Payload=$payload})
    }
    return @($rows)
}
function New-GlobalInput([string]$Current,[string]$GlobalInbox,[string]$Name){$source=Join-Path $GlobalInbox $Name;Copy-Item -LiteralPath $Current -Destination $source -Force;return[pscustomobject]@{Source=$source;Sha=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()}}

$modelPath=Join-Path $RepositoryRoot 'tests\knowledge\stranded-input-transaction-properties.json'
if(-not(Test-Path -LiteralPath $modelPath -PathType Leaf)){Fail 'Transaction-property model missing.'}
$model=Get-Content -LiteralPath $modelPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$model.schema-cne'keelaryn.manager-stranded-input-transaction-properties.v1'){Fail 'Unexpected transaction-property schema.'}
$modelIds=@($model.properties|ForEach-Object{[string]$_.id}|Sort-Object -Unique);if($modelIds.Count-ne@($model.properties).Count){Fail 'Transaction-property model contains duplicate ids.'}

$sourceManager=Join-Path $RepositoryRoot 'manager';$sourceRuntime=Join-Path $sourceManager 'product\runtime\Keelaryn__Manager.ps1'
if(-not([IO.File]::ReadAllText($sourceRuntime,[Text.Encoding]::UTF8).Contains('keelaryn.manager.hub-input-reconciliation-claim.v1'))){Fail 'Fixed property executor requires claim-first runtime bytes.'}
$tempRoot=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-claim-properties-'+[guid]::NewGuid().ToString('N'));$keelarynRoot=Join-Path $tempRoot 'keelaryn';$managerRoot=Join-Path $keelarynRoot 'manager';$configA=Join-Path $tempRoot 'alpha.json';$configB=Join-Path $tempRoot 'beta.json';$configG=Join-Path $tempRoot 'gamma.json'
if([string]::IsNullOrWhiteSpace($OutputPath)){$OutputPath=Join-Path ([IO.Path]::GetTempPath()) ('STRANDED_INPUT_TRANSACTION_FIXED_'+[guid]::NewGuid().ToString('N')+'.json')}
$results=New-Object System.Collections.ArrayList;$harnessError=$null;$version='unknown';$oldFault=$env:KEELARYN_TRANSACTION_PROPERTY_FAULT;$oldAux=$env:KEELARYN_TRANSACTION_PROPERTY_AUX

try{
    New-Item -ItemType Directory -Force -Path $keelarynRoot|Out-Null;$version=Copy-ManagedManager $sourceManager $managerRoot;$runtime=Join-Path $managerRoot 'product\runtime\Keelaryn__Manager.ps1';Set-ClaimFaultInstrumentation $runtime
    foreach($pair in @(@($configA,'Alpha'),@($configB,'Beta'),@($configG,'Gamma'))){$cfg=[ordered]@{schema='keelaryn.genesis-input.v1';language='en';purpose='mixed';timezone='UTC';areas=@('Qualification');projects=@('Stranded input property '+[string]$pair[1])};Write-Json ([string]$pair[0]) $cfg}
    Write-Host ('=== MANAGER STRANDED INPUT CLAIM PROPERTIES / '+$version+' ===')
    $null=Invoke-Required $runtime @('-Genesis','-GenesisConfigPath',$configA,'-GenesisConfirmed') 'Alpha Genesis';$null=Invoke-Required $runtime @('-InitializeInstanceRegistry','-RegisterInstanceName','Alpha') 'Registry activation'
    $betaPath=Join-Path $keelarynRoot 'hubs\beta';$null=Invoke-Required $runtime @('-GenesisInstancePath',$betaPath,'-GenesisInstanceName','Beta','-GenesisConfigPath',$configB,'-GenesisConfirmed') 'Beta registered Genesis'
    $registry=Read-Registry $managerRoot;$alpha=@($registry.instances|Where-Object{[string]$_.name-ceq'Alpha'});$beta=@($registry.instances|Where-Object{[string]$_.name-ceq'Beta'});if($alpha.Count-ne1-or$beta.Count-ne1){Fail 'Could not resolve Alpha/Beta rows.'};$alpha=$alpha[0];$beta=$beta[0]
    $alphaId=[string]$alpha.instance_id;$betaId=[string]$beta.instance_id;$alphaPath=[string]$alpha.vault_path;$betaPath=[string]$beta.vault_path;$stateRoot=Join-Path $managerRoot 'state';$globalInbox=Join-Path $stateRoot 'inbox';$alphaCurrent=Join-Path $stateRoot ('instances\'+$alphaId+'\baseline\Keelaryn__Hub_CURRENT.zip');$betaCurrent=Join-Path $stateRoot ('instances\'+$betaId+'\baseline\Keelaryn__Hub_CURRENT.zip');$alphaInbox=Join-Path $stateRoot ('instances\'+$alphaId+'\inbox');$betaInbox=Join-Path $stateRoot ('instances\'+$betaId+'\inbox')
    foreach($p in @($alphaCurrent,$betaCurrent,$globalInbox,$alphaInbox,$betaInbox)){if(-not(Test-Path -LiteralPath $p)){Fail('Required fixed-property fixture path missing: '+$p)}}
    $alphaHubDigest=Get-TreeDigest $alphaPath;$betaHubDigest=Get-TreeDigest $betaPath

    $gammaKeelaryn=Join-Path $tempRoot 'gamma\keelaryn';$gammaManager=Join-Path $gammaKeelaryn 'manager';New-Item -ItemType Directory -Force -Path $gammaKeelaryn|Out-Null;$null=Copy-ManagedManager $sourceManager $gammaManager;$gammaRuntime=Join-Path $gammaManager 'product\runtime\Keelaryn__Manager.ps1';$null=Invoke-Required $gammaRuntime @('-Genesis','-GenesisConfigPath',$configG,'-GenesisConfirmed') 'Gamma standalone Genesis';$gammaCurrent=Join-Path $gammaManager 'state\baseline\Keelaryn__Hub_CURRENT.zip';if(-not(Test-Path -LiteralPath $gammaCurrent -PathType Leaf)){Fail 'Gamma unregistered CURRENT fixture missing.'}

    $snapRoot=Join-Path $tempRoot 'snapshot';$snapManager=Join-Path $snapRoot 'manager';$snapAlpha=Join-Path $snapRoot 'alpha';$snapBeta=Join-Path $snapRoot 'beta';Copy-DirectoryExact $managerRoot $snapManager;Copy-DirectoryExact $alphaPath $snapAlpha;Copy-DirectoryExact $betaPath $snapBeta
    function Reset-PropertyBaseline {Copy-DirectoryExact $snapManager $managerRoot;Copy-DirectoryExact $snapAlpha $alphaPath;Copy-DirectoryExact $snapBeta $betaPath;$env:KEELARYN_TRANSACTION_PROPERTY_FAULT=$null;$env:KEELARYN_TRANSACTION_PROPERTY_AUX=$null}
    function Hubs-Unchanged {return ((Get-TreeDigest $alphaPath)-ceq$alphaHubDigest-and(Get-TreeDigest $betaPath)-ceq$betaHubDigest)}
    function Add-Property([string]$Id,[bool]$Pass,[string]$Detail,[int]$ExitCode){[void]$results.Add([ordered]@{id=$Id;pass=$Pass;exit_code=$ExitCode;detail=$Detail});Write-Host ('  '+$(if($Pass){'PASS'}else{'FAIL'})+' '+$Id+' :: '+$Detail) -ForegroundColor $(if($Pass){'Green'}else{'Red'})}

    # SITP-001: source is atomically consumed into a durable claim before target publication.
    Reset-PropertyBaseline;$name='Keelaryn__Hub_APPROVED_SITP001.zip';$g=New-GlobalInput $alphaCurrent $globalInbox $name;$target=Join-Path $alphaInbox $name;$env:KEELARYN_TRANSACTION_PROPERTY_FAULT='stop-after-claim';$r=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$claims=@(Get-TestClaims $managerRoot);$payloadOk=($claims.Count-eq1-and(Test-FileSha $claims[0].Payload $g.Sha));$pass=($r.ExitCode-ne0-and-not(Test-Path -LiteralPath $g.Source)-and-not(Test-Path -LiteralPath $target)-and$payloadOk-and(Hubs-Unchanged));Add-Property 'SITP-001' $pass 'source loss after claim leaves the exact payload durable and discoverable' $r.ExitCode

    # SITP-002: a new occupant at the old source pathname cannot redefine the claimed bytes.
    Reset-PropertyBaseline;$name='Keelaryn__Hub_APPROVED_SITP002.zip';$g=New-GlobalInput $alphaCurrent $globalInbox $name;$target=Join-Path $alphaInbox $name;$env:KEELARYN_TRANSACTION_PROPERTY_FAULT='replace-source-after-claim';$r=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$claims=@(Get-TestClaims $managerRoot);$claimOk=($claims.Count-eq1-and(Test-FileSha $claims[0].Payload $g.Sha));$foreignOk=(Test-Path -LiteralPath $g.Source -PathType Leaf)-and((Get-FileHash -LiteralPath $g.Source -Algorithm SHA256).Hash.ToLowerInvariant()-cne$g.Sha);$pass=($r.ExitCode-ne0-and$claimOk-and$foreignOk-and-not(Test-Path -LiteralPath $target)-and(Hubs-Unchanged));Add-Property 'SITP-002' $pass 'claimed identity remains bound to payload even when the original pathname is reoccupied with different bytes' $r.ExitCode

    # SITP-003: invalid claimed bytes remain durable and never select a target.
    Reset-PropertyBaseline;$name='Keelaryn__Hub_APPROVED_SITP003.zip';$source=Join-Path $globalInbox $name;Write-Utf8 $source 'not-a-valid-hub-zip';$badSha=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant();$r=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$claims=@(Get-TestClaims $managerRoot);$pass=($r.ExitCode-ne0-and-not(Test-Path -LiteralPath $source)-and$claims.Count-eq1-and(Test-FileSha $claims[0].Payload $badSha)-and[string]::IsNullOrWhiteSpace([string]$claims[0].Metadata.instance_id)-and(Hubs-Unchanged));Add-Property 'SITP-003' $pass 'invalid claimed bytes fail closed before target selection and remain durable' $r.ExitCode

    # SITP-004: a valid but unregistered instance identity cannot be routed to an active/friendly target.
    Reset-PropertyBaseline;$name='Keelaryn__Hub_APPROVED_SITP004.zip';$g=New-GlobalInput $gammaCurrent $globalInbox $name;$r=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$claims=@(Get-TestClaims $managerRoot);$pass=($r.ExitCode-ne0-and-not(Test-Path -LiteralPath $g.Source)-and$claims.Count-eq1-and(Test-FileSha $claims[0].Payload $g.Sha)-and-not(Test-Path -LiteralPath (Join-Path $alphaInbox $name))-and-not(Test-Path -LiteralPath (Join-Path $betaInbox $name))-and(Hubs-Unchanged));Add-Property 'SITP-004' $pass 'unregistered canonical instance_id fails closed without cross-instance publication' $r.ExitCode

    # SITP-005: authoritative target path is freshly re-read immediately before publication.
    Reset-PropertyBaseline;$name='Keelaryn__Hub_APPROVED_SITP005.zip';$g=New-GlobalInput $alphaCurrent $globalInbox $name;$target=Join-Path $alphaInbox $name;$drift=Join-Path $keelarynRoot 'hubs\alpha-drift';Copy-DirectoryExact $alphaPath $drift;$env:KEELARYN_TRANSACTION_PROPERTY_AUX=$drift;$env:KEELARYN_TRANSACTION_PROPERTY_FAULT='drift-registry-before-commit';$r=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$claims=@(Get-TestClaims $managerRoot);$pass=($r.ExitCode-ne0-and$claims.Count-eq1-and(Test-FileSha $claims[0].Payload $g.Sha)-and-not(Test-Path -LiteralPath $target)-and$r.Text.Contains('target path changed before publication')-and(Hubs-Unchanged));Add-Property 'SITP-005' $pass 'registry target drift at the commit boundary fails closed and preserves the claim' $r.ExitCode

    # SITP-006: a different occupied destination is never overwritten.
    Reset-PropertyBaseline;$name='Keelaryn__Hub_APPROVED_SITP006.zip';$g=New-GlobalInput $alphaCurrent $globalInbox $name;$target=Join-Path $alphaInbox $name;Write-Utf8 $target 'different-destination-bytes';$collisionSha=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant();$r=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$claims=@(Get-TestClaims $managerRoot);$pass=($r.ExitCode-ne0-and$claims.Count-eq1-and(Test-FileSha $claims[0].Payload $g.Sha)-and(Test-FileSha $target $collisionSha)-and$r.Text.Contains('destination collision')-and(Hubs-Unchanged));Add-Property 'SITP-006' $pass 'different destination collision is preserved and never overwritten' $r.ExitCode

    # SITP-007: an already-present exact destination completes idempotently.
    Reset-PropertyBaseline;$name='Keelaryn__Hub_APPROVED_SITP007.zip';$g=New-GlobalInput $alphaCurrent $globalInbox $name;$target=Join-Path $alphaInbox $name;Copy-Item -LiteralPath $alphaCurrent -Destination $target -Force;$r=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$claims=@(Get-TestClaims $managerRoot);$pass=($r.ExitCode-eq0-and-not(Test-Path -LiteralPath $g.Source)-and(Test-FileSha $target $g.Sha)-and$claims.Count-eq0-and$r.Text.Contains('Reconciled 1 identity-bound Hub input(s)')-and(Hubs-Unchanged));Add-Property 'SITP-007' $pass 'same exact bound destination is verified as idempotent completion before claim retirement' $r.ExitCode

    # SITP-008: failure after durable destination move preserves destination plus recovery metadata.
    Reset-PropertyBaseline;$name='Keelaryn__Hub_APPROVED_SITP008.zip';$g=New-GlobalInput $alphaCurrent $globalInbox $name;$target=Join-Path $alphaInbox $name;$env:KEELARYN_TRANSACTION_PROPERTY_FAULT='fail-after-destination-commit';$r=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$claims=@(Get-TestClaims $managerRoot);$phase1=($r.ExitCode-ne0-and(Test-FileSha $target $g.Sha)-and$claims.Count-eq1-and-not(Test-Path -LiteralPath $claims[0].Payload)-and$r.Text.Contains('destination committed, but post-commit verification failed'));$env:KEELARYN_TRANSACTION_PROPERTY_FAULT=$null;$resume=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$claimsAfter=@(Get-TestClaims $managerRoot);$pass=($phase1-and$resume.ExitCode-eq0-and$claimsAfter.Count-eq0-and(Test-FileSha $target $g.Sha)-and(Hubs-Unchanged));Add-Property 'SITP-008' $pass 'post-commit failure preserves exact destination and claim metadata; retry verifies and retires idempotently' $r.ExitCode

    # SITP-009: later independent failure never rolls back a completed exact handoff.
    Reset-PropertyBaseline;$validName='Keelaryn__Hub_APPROVED_A_SITP009.zip';$invalidName='Keelaryn__Hub_APPROVED_Z_SITP009.zip';$valid=New-GlobalInput $alphaCurrent $globalInbox $validName;$validTarget=Join-Path $alphaInbox $validName;$invalidSource=Join-Path $globalInbox $invalidName;Write-Utf8 $invalidSource 'not-a-valid-hub-zip';$invalidSha=(Get-FileHash -LiteralPath $invalidSource -Algorithm SHA256).Hash.ToLowerInvariant();$r=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$claims=@(Get-TestClaims $managerRoot);$pass=($r.ExitCode-ne0-and(Test-FileSha $validTarget $valid.Sha)-and-not(Test-Path -LiteralPath $valid.Source)-and-not(Test-Path -LiteralPath $invalidSource)-and$claims.Count-eq1-and(Test-FileSha $claims[0].Payload $invalidSha)-and(Hubs-Unchanged));Add-Property 'SITP-009' $pass 'later invalid artifact remains a durable blocking claim while earlier completed exact handoff remains published' $r.ExitCode

    # SITP-010: process restart discovers and resumes a pre-publication durable claim.
    Reset-PropertyBaseline;$name='Keelaryn__Hub_APPROVED_SITP010.zip';$g=New-GlobalInput $betaCurrent $globalInbox $name;$target=Join-Path $betaInbox $name;$env:KEELARYN_TRANSACTION_PROPERTY_FAULT='stop-after-claim';$first=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$claims=@(Get-TestClaims $managerRoot);$phase1=($first.ExitCode-ne0-and$claims.Count-eq1-and(Test-FileSha $claims[0].Payload $g.Sha));$env:KEELARYN_TRANSACTION_PROPERTY_FAULT=$null;$second=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$claimsAfter=@(Get-TestClaims $managerRoot);$pass=($phase1-and$second.ExitCode-eq0-and$claimsAfter.Count-eq0-and(Test-FileSha $target $g.Sha)-and(Hubs-Unchanged));Add-Property 'SITP-010' $pass 'restart deterministically discovers and completes the existing durable claim before clean initialization' $second.ExitCode

    # SITP-011: Doctor surfaces unresolved claims; Hub-bound operations block; Manager-global work remains independent.
    Reset-PropertyBaseline;$name='Keelaryn__Hub_APPROVED_SITP011.zip';$g=New-GlobalInput $alphaCurrent $globalInbox $name;$env:KEELARYN_TRANSACTION_PROPERTY_FAULT='stop-after-claim';$first=Invoke-Runtime $runtime @('-InitializeInstanceRegistry');$env:KEELARYN_TRANSACTION_PROPERTY_FAULT=$null;$claims=@(Get-TestClaims $managerRoot);$doctor=Invoke-Runtime $runtime @('-Doctor');$hubOp=Invoke-Runtime $runtime @('-BuildCandidateTransport');$globalOp=Invoke-Runtime $runtime @('-BuildDistribution');$pass=($first.ExitCode-ne0-and$claims.Count-eq1-and$doctor.Text.Contains('[WARN] inbox.hub_reconciliation_claim:')-and$hubOp.ExitCode-ne0-and$hubOp.Text.Contains('unresolved Hub-input reconciliation state remains')-and$globalOp.ExitCode-eq0-and$globalOp.Text.Contains('Generic distribution:')-and(Hubs-Unchanged));Add-Property 'SITP-011' $pass 'Doctor reports unresolved claim; Hub-bound operation fails closed while Manager-global distribution remains reachable' $hubOp.ExitCode

}catch{$harnessError=$_.Exception.Message;Write-Host ('CLAIM PROPERTY HARNESS ERROR: '+$harnessError) -ForegroundColor Red}
finally{$env:KEELARYN_TRANSACTION_PROPERTY_FAULT=$oldFault;$env:KEELARYN_TRANSACTION_PROPERTY_AUX=$oldAux}

$resultIds=@($results|ForEach-Object{[string]$_.id}|Sort-Object -Unique);$missing=@($modelIds|Where-Object{$resultIds-cnotcontains$_});$extra=@($resultIds|Where-Object{$modelIds-cnotcontains$_});$failed=@($results|Where-Object{-not[bool]$_.pass})
$pass=($null-eq$harnessError-and$missing.Count-eq0-and$extra.Count-eq0-and$failed.Count-eq0-and@($results).Count-eq$modelIds.Count)
$report=[ordered]@{schema='keelaryn.manager-stranded-input-transaction-result.v1';manager_version=$version;expected_state='Fixed';defect='MGR-DEF-0034';semantic_owner=[string]$model.semantic_owner;primary_invariant=[string]$model.primary_invariant;model_property_ids=$modelIds;properties_executed=@($results);missing_properties=$missing;extra_properties=$extra;pass=$pass;harness_error=$harnessError;production_hub_used=$false;disposable_manager_used=$true;completed_utc=[DateTime]::UtcNow.ToString('o')}
try{Write-Json $OutputPath $report;Write-Host ('Evidence: '+$OutputPath)}catch{Write-Host ('Could not write claim-property evidence: '+$_.Exception.Message) -ForegroundColor Red;$pass=$false}
try{if(Test-Path -LiteralPath $tempRoot){Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction Stop}}catch{Write-Warning('Disposable cleanup failed: '+$_.Exception.Message)}
if(-not$pass){Write-Host ('MANAGER STRANDED INPUT CLAIM PROPERTIES: FAIL; executed='+@($results).Count+' failures='+$failed.Count+' missing='+$missing.Count+' harness_error='+[bool]$harnessError) -ForegroundColor Red;exit 1}
Write-Host ('MANAGER STRANDED INPUT CLAIM PROPERTIES: PASS; modeled_properties='+$modelIds.Count+' executed='+@($results).Count) -ForegroundColor Green
exit 0
