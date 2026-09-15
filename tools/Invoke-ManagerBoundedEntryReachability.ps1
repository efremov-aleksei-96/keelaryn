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
function Write-Utf8([string]$Path,[string]$Text){
    $parent=Split-Path -Parent $Path
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    [IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}
function Write-Json([string]$Path,$Object){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth 40).Replace("`r`n","`n"))+"`n")}
function Copy-ManagedManager([string]$SourceManager,[string]$DestinationManager){
    $install=Get-Content -LiteralPath (Join-Path $SourceManager 'product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if([string]$install.schema-cne'keelaryn.manager.installation.v2'){Fail 'Unsupported Manager installation schema.'}
    New-Item -ItemType Directory -Force -Path $DestinationManager|Out-Null
    foreach($raw in @($install.managed_files)){
        $rel=([string]$raw).Replace('/','\');$src=Join-Path $SourceManager $rel;$dst=Join-Path $DestinationManager $rel
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)){Fail('Managed source missing: '+$rel)}
        $parent=Split-Path -Parent $dst
        if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
    return [string]$install.manager_version
}
function Copy-DirectoryExact([string]$Source,[string]$Destination){
    if(-not(Test-Path -LiteralPath $Source -PathType Container)){Fail('Snapshot source directory missing: '+$Source)}
    if(Test-Path -LiteralPath $Destination){Remove-Item -LiteralPath $Destination -Recurse -Force}
    $parent=Split-Path -Parent $Destination
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}
function Invoke-Runtime([string]$Runtime,[string[]]$Arguments){
    if($null-eq$Arguments){$Arguments=@()}
    $exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $output=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Runtime @Arguments 2>&1|ForEach-Object{[string]$_})
        $code=[int]$LASTEXITCODE
    }finally{$ErrorActionPreference=$old}
    return [pscustomobject]@{ExitCode=$code;Output=@($output);Text=[string]::Join("`n",@($output))}
}
function Invoke-Required([string]$Runtime,[string[]]$Arguments,[string]$Purpose){
    $r=Invoke-Runtime $Runtime $Arguments
    foreach($line in @($r.Output)){Write-Host $line}
    if($r.ExitCode-ne0){Fail($Purpose+' failed; exit='+$r.ExitCode+'; output='+$r.Text)}
    return $r
}
function Invoke-RequiredTool([string]$Script,[string[]]$Arguments,[string]$Purpose){
    $r=Invoke-Runtime $Script $Arguments
    foreach($line in @($r.Output)){Write-Host $line}
    if($r.ExitCode-ne0){Fail($Purpose+' failed; exit='+$r.ExitCode+'; output='+$r.Text)}
    return $r
}
function Get-TreeDigest([string]$Root){
    if(-not(Test-Path -LiteralPath $Root -PathType Container)){return 'missing'}
    $rows=New-Object System.Collections.ArrayList
    foreach($f in @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force|Sort-Object FullName)){
        $rel=$f.FullName.Substring($Root.Length).TrimStart('\').Replace('\','/')
        $h=(Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        [void]$rows.Add($rel+'='+$h)
    }
    $sha=[Security.Cryptography.SHA256]::Create()
    try{return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]::Join("`n",@($rows))))).Replace('-','').ToLowerInvariant())}
    finally{$sha.Dispose()}
}
function Read-Registry([string]$ManagerRoot){return Get-Content -LiteralPath (Join-Path $ManagerRoot 'state\instances.json') -Raw -Encoding UTF8|ConvertFrom-Json}
function Read-Active([string]$ManagerRoot){return Get-Content -LiteralPath (Join-Path $ManagerRoot 'state\active_instance.json') -Raw -Encoding UTF8|ConvertFrom-Json}
function Get-PathKey([string]$Path){return [IO.Path]::GetFullPath($Path).TrimEnd('\').ToLowerInvariant()}
function Get-InstalledManagerVersion([string]$ManagerRoot){
    $p=Join-Path $ManagerRoot 'product\install\INSTALLATION.json'
    if(-not(Test-Path -LiteralPath $p -PathType Leaf)){return ''}
    try{return ([string]((Get-Content -LiteralPath $p -Raw -Encoding UTF8|ConvertFrom-Json).manager_version)).Trim()}catch{return ''}
}
function Assert-PowerShellParses([string]$Path,[string]$Purpose){
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){Fail($Purpose+' parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
}
function Set-EntryActionSentinelInstrumentation([string]$Runtime,[string]$Action){
    $text=[IO.File]::ReadAllText($Runtime,[Text.Encoding]::UTF8)
    $probe='if(-not[string]::IsNullOrWhiteSpace([string]$env:KEELARYN_ENTRY_ACTION_SENTINEL)){[IO.File]::WriteAllText([string]$env:KEELARYN_ENTRY_ACTION_SENTINEL,'+[char]39+$Action+[char]39+',[Text.Encoding]::ASCII)}'
    switch($Action){
        'SelfTest' {$anchor='if ($SelfTest) {';$replacement=$anchor+"`r`n    "+$probe}
        'InitializePresentation' {$anchor='if ($InitializePresentation) { $exitCode=Initialize-ManagerPresentationState }';$replacement='if ($InitializePresentation) { '+$probe+'; $exitCode=Initialize-ManagerPresentationState }'}
        default {Fail('Sentinel instrumentation is unsupported for '+$Action)}
    }
    if([regex]::Matches($text,[regex]::Escape($anchor)).Count-ne1){Fail('Sentinel instrumentation anchor count mismatch for '+$Action)}
    Write-Utf8 $Runtime ($text.Replace($anchor,$replacement))
    Assert-PowerShellParses $Runtime ('Sentinel-instrumented '+$Action+' runtime')
}
function Set-SyntheticManagerVersion([string]$ManagerRoot,[string]$FromVersion,[string]$ToVersion){
    $runtimePath=Join-Path $ManagerRoot 'product\runtime\Keelaryn__Manager.ps1'
    $text=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
    $old='$ManagerVersion = "'+$FromVersion+'"';$new='$ManagerVersion = "'+$ToVersion+'"'
    if([regex]::Matches($text,[regex]::Escape($old)).Count-ne1){Fail('Synthetic runtime version marker count mismatch for '+$FromVersion)}
    Write-Utf8 $runtimePath ($text.Replace($old,$new))
    foreach($rel in @('product\install\INSTALLATION.json','product\manager_release.json')){
        $p=Join-Path $ManagerRoot $rel
        $j=Get-Content -LiteralPath $p -Raw -Encoding UTF8|ConvertFrom-Json
        $j.manager_version=$ToVersion
        Write-Json $p $j
    }
    $readme=Join-Path $ManagerRoot 'README_FIRST.md';$rt=[IO.File]::ReadAllText($readme,[Text.Encoding]::UTF8)
    $rx=New-Object Text.RegularExpressions.Regex(('(?m)^# Keelaryn Manager '+[regex]::Escape($FromVersion)+'\r?$'))
    if($rx.Matches($rt).Count-ne1){Fail('Synthetic README version header count mismatch for '+$FromVersion)}
    Write-Utf8 $readme ($rx.Replace($rt,('# Keelaryn Manager '+$ToVersion),1))
}
function New-SyntheticSuccessorUpdate([string]$SourceManager,[string]$TempRoot,[string]$CurrentVersion){
    $v=[version]$CurrentVersion
    if($v.Build-lt0){Fail('Cannot derive synthetic successor from '+$CurrentVersion)}
    $next=('{0}.{1}.{2}' -f $v.Major,$v.Minor,($v.Build+1))
    $builder=Join-Path $TempRoot 'successor-builder\manager'
    $null=Copy-ManagedManager $SourceManager $builder
    Set-SyntheticManagerVersion $builder $CurrentVersion $next
    $builderRuntime=Join-Path $builder 'product\runtime\Keelaryn__Manager.ps1'
    $null=Invoke-Required $builderRuntime @('-InitializePresentation') 'Synthetic successor InitializePresentation'
    $null=Invoke-Required $builderRuntime @('-SelfTest') 'Synthetic successor SelfTest'
    $null=Invoke-Required $builderRuntime @('-BuildRelease') 'Synthetic successor BuildRelease'
    $built=Join-Path $builder ('state\releases\Keelaryn__Manager_Update_v'+$next+'_Built.zip')
    if(-not(Test-Path -LiteralPath $built -PathType Leaf)){Fail('Synthetic successor UPDATE missing: '+$built)}
    $fixtureDir=Join-Path $TempRoot 'fixtures';New-Item -ItemType Directory -Force -Path $fixtureDir|Out-Null
    $fixture=Join-Path $fixtureDir ([IO.Path]::GetFileName($built));Copy-Item -LiteralPath $built -Destination $fixture -Force
    return [pscustomobject]@{Version=$next;Path=$fixture;FileName=[IO.Path]::GetFileName($fixture)}
}
function New-CandidateLikeZip([string]$Path){
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    Add-Type -AssemblyName System.IO.Compression
    if(Test-Path -LiteralPath $Path){Remove-Item -LiteralPath $Path -Force}
    $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try{
        $archive=New-Object IO.Compression.ZipArchive($stream,[IO.Compression.ZipArchiveMode]::Create,$true)
        try{
            $entry=$archive.CreateEntry('regression-marker.txt',[IO.Compression.CompressionLevel]::Optimal)
            $writer=New-Object IO.StreamWriter($entry.Open(),$Utf8NoBom)
            try{$writer.Write('bounded active-instance candidate visibility fixture')}finally{$writer.Dispose()}
        }finally{$archive.Dispose()}
    }finally{$stream.Dispose()}
}

function Get-BoundedReconciliationClaims([string]$ManagerRoot){
    $root=Join-Path $ManagerRoot 'state\reconciliation\hub-inputs'
    $rows=New-Object System.Collections.ArrayList
    if(-not(Test-Path -LiteralPath $root -PathType Container)){return @($rows)}
    $rootItem=Get-Item -LiteralPath $root -Force -ErrorAction Stop
    if(-not$rootItem.PSIsContainer-or($rootItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){Fail('Bounded reconciliation root is unsafe: '+$root)}
    foreach($dir in @(Get-ChildItem -LiteralPath $root -Directory -Force -ErrorAction Stop|Sort-Object Name)){
        if(($dir.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0){Fail('Bounded reconciliation claim is unsafe: '+$dir.FullName)}
        $metaPath=Join-Path $dir.FullName 'claim.json'
        if(-not(Test-Path -LiteralPath $metaPath -PathType Leaf)){Fail('Bounded reconciliation claim metadata missing: '+$metaPath)}
        try{$meta=Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8|ConvertFrom-Json}catch{Fail('Bounded reconciliation claim metadata invalid: '+$metaPath+'; '+$_.Exception.Message)}
        if([string]$meta.schema-cne'keelaryn.manager.hub-input-reconciliation-claim.v1'){Fail('Unexpected bounded reconciliation claim schema: '+[string]$meta.schema)}
        $payload=Join-Path (Join-Path $dir.FullName 'payload') ([string]$meta.original_name)
        [void]$rows.Add([pscustomobject]@{Directory=$dir.FullName;Metadata=$meta;Payload=$payload})
    }
    return @($rows)
}
$planTool=Join-Path $RepositoryRoot 'tools\Build-ManagerEntryReachabilityPlan.ps1'
$oraclePath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability-oracles.json'
foreach($p in @($planTool,$oraclePath)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Bounded Entry dependency missing: '+$p)}}
$planPath=Join-Path ([IO.Path]::GetTempPath()) ('MANAGER_ENTRY_PLAN_BOUNDED_'+[guid]::NewGuid().ToString('N')+'.json')
$null=Invoke-RequiredTool $planTool @('-RepositoryRoot',$RepositoryRoot,'-OutputPath',$planPath) 'Bounded Entry plan derivation'
$plan=Get-Content -LiteralPath $planPath -Raw -Encoding UTF8|ConvertFrom-Json
$oracles=Get-Content -LiteralPath $oraclePath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$plan.schema-cne'keelaryn.manager-entry-plan.v1'){Fail 'Unsupported bounded Entry plan schema.'}
if([string]$oracles.schema-cne'keelaryn.manager-entry-oracles.v2'){Fail 'Unsupported bounded Entry oracle schema.'}
if([bool]$oracles.fallback_oracle_permitted){Fail 'Bounded Entry execution refuses fallback oracles.'}
if([bool]$oracles.transaction_fault_properties_included){Fail 'Transaction fault properties must remain outside bounded Entry execution.'}
$oracleByRule=@{}
foreach($o in @($oracles.rule_oracles)){
    $rid=[string]$o.winning_rule
    if($oracleByRule.ContainsKey($rid)){Fail('Duplicate bounded Entry oracle: '+$rid)}
    $oracleByRule[$rid]=$o
}
$specs=New-Object System.Collections.ArrayList
foreach($edge in @($plan.edges)){
    $rid=[string]$edge.winning_rule
    if(-not$oracleByRule.ContainsKey($rid)){Fail('No explicit oracle for derived edge '+[string]$edge.id+' rule='+$rid)}
    $oracle=$oracleByRule[$rid]
    $allowed=@()
    if($null-ne$oracle.PSObject.Properties['action']){$allowed+=,[string]$oracle.action}
    if($null-ne$oracle.PSObject.Properties['actions']){$allowed+=@($oracle.actions|ForEach-Object{[string]$_})}
    if($allowed -notcontains [string]$edge.action){Fail('Oracle action mismatch for '+[string]$edge.id+' rule='+$rid+' action='+[string]$edge.action)}
    [void]$specs.Add([pscustomobject]@{
        Id=[string]$edge.id;State=[string]$edge.state;Fixture=[string]$edge.fixture;Action=[string]$edge.action
        WinningRule=$rid;Outcome=[string]$edge.outcome;ObservationMode=[string]$oracle.observation_mode;Kind=[string]$edge.kind
    })
}
if($specs.Count-ne[int]$plan.derived_edge_count){Fail('Derived edge materialization mismatch. plan='+[int]$plan.derived_edge_count+' specs='+$specs.Count)}

$sourceManager=Join-Path $RepositoryRoot 'manager'
$tempRoot=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-bounded-entry-'+[guid]::NewGuid().ToString('N'))
$keelarynRoot=Join-Path $tempRoot 'keelaryn';$managerRoot=Join-Path $keelarynRoot 'manager';$configA=Join-Path $tempRoot 'alpha.json';$configB=Join-Path $tempRoot 'beta.json'
$results=New-Object System.Collections.ArrayList;$version='unknown';$harnessError=$null;$successor=$null
if([string]::IsNullOrWhiteSpace($OutputPath)){$OutputPath=Join-Path ([IO.Path]::GetTempPath()) ('BOUNDED_ENTRY_RESULT_'+[guid]::NewGuid().ToString('N')+'.json')}

try{
    New-Item -ItemType Directory -Force -Path $keelarynRoot|Out-Null
    $version=Copy-ManagedManager $sourceManager $managerRoot
    $runtime=Join-Path $managerRoot 'product\runtime\Keelaryn__Manager.ps1'
    foreach($pair in @(@($configA,'Alpha'),@($configB,'Beta'))){
        $cfg=[ordered]@{schema='keelaryn.genesis-input.v1';language='en';purpose='mixed';timezone='UTC';areas=@('Qualification');projects=@('Bounded entry reachability '+[string]$pair[1])}
        Write-Json ([string]$pair[0]) $cfg
    }
    Write-Host ('=== MANAGER BOUNDED ENTRY REACHABILITY / '+$version+' ===')
    $null=Invoke-Required $runtime @('-Genesis','-GenesisConfigPath',$configA,'-GenesisConfirmed') 'Alpha Genesis'
    $null=Invoke-Required $runtime @('-InitializeInstanceRegistry','-RegisterInstanceName','Alpha') 'Registry activation'
    $betaPath=Join-Path $keelarynRoot 'hubs\beta'
    $null=Invoke-Required $runtime @('-GenesisInstancePath',$betaPath,'-GenesisInstanceName','Beta','-GenesisConfigPath',$configB,'-GenesisConfirmed') 'Beta registered Genesis'
    $registry=Read-Registry $managerRoot
    if(@($registry.instances).Count-ne2){Fail('Expected two registered Hubs; actual='+@($registry.instances).Count)}
    $alpha=@($registry.instances|Where-Object{[string]$_.name-ceq'Alpha'});$beta=@($registry.instances|Where-Object{[string]$_.name-ceq'Beta'})
    if($alpha.Count-ne1-or$beta.Count-ne1){Fail 'Could not resolve Alpha/Beta registry rows.'}
    $alpha=$alpha[0];$beta=$beta[0]
    $alphaId=[string]$alpha.instance_id;$betaId=[string]$beta.instance_id;$alphaPath=[string]$alpha.vault_path;$betaPath=[string]$beta.vault_path
    $stateRoot=Join-Path $managerRoot 'state';$alphaCurrent=Join-Path $stateRoot ('instances\'+$alphaId+'\baseline\Keelaryn__Hub_CURRENT.zip');$legacyCurrent=Join-Path $stateRoot 'baseline\Keelaryn__Hub_CURRENT.zip';$activeFile=Join-Path $stateRoot 'active_instance.json';$globalInbox=Join-Path $stateRoot 'inbox';$alphaInbox=Join-Path $stateRoot ('instances\'+$alphaId+'\inbox')
    foreach($p in @($alphaCurrent,$legacyCurrent,$activeFile)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Required initialized state missing: '+$p)}}
    $betaRelocatedPath=Join-Path $keelarynRoot 'hubs\beta-relocated';Copy-DirectoryExact $betaPath $betaRelocatedPath
    $successor=New-SyntheticSuccessorUpdate $sourceManager $tempRoot $version

    $snapRoot=Join-Path $tempRoot 'snapshots';New-Item -ItemType Directory -Force -Path $snapRoot|Out-Null
    $snapManager=Join-Path $snapRoot 'manager';$snapAlpha=Join-Path $snapRoot 'alpha-hub';$snapBeta=Join-Path $snapRoot 'beta-hub';$snapBetaRelocated=Join-Path $snapRoot 'beta-relocated-hub'
    Copy-DirectoryExact $managerRoot $snapManager;Copy-DirectoryExact $alphaPath $snapAlpha;Copy-DirectoryExact $betaPath $snapBeta;Copy-DirectoryExact $betaRelocatedPath $snapBetaRelocated

    function Reset-ScenarioBaseline {
        Copy-DirectoryExact $snapManager $managerRoot;Copy-DirectoryExact $snapAlpha $alphaPath;Copy-DirectoryExact $snapBeta $betaPath;Copy-DirectoryExact $snapBetaRelocated $betaRelocatedPath
    }
    function Apply-DegradedFixture([string]$Fixture){
        $script:ScenarioPendingGlobalSource=$null;$script:ScenarioPendingGlobalTarget=$null;$script:ScenarioPendingGlobalSha=$null;$script:ScenarioPendingGlobalInvalidSource=$null;$script:ScenarioPendingInstancePath=$null
        switch($Fixture){
            'registry_document_invalid' {Write-Utf8 (Join-Path $stateRoot 'instances.json') '{ not-json'}
            'registry_healthy' {}
            'inactive_hub_missing' {Remove-Item -LiteralPath $betaPath -Recurse -Force}
            'inactive_hub_corrupt' {$stateDoc=Join-Path $betaPath '_System\STATE.md';if(Test-Path -LiteralPath $stateDoc){Remove-Item -LiteralPath $stateDoc -Force}else{Fail('Beta structural marker missing before corruption fixture: '+$stateDoc)}}
            'registry_pending_global' {
                $name='Keelaryn__Hub_APPROVED_bounded-entry.zip';$dst=Join-Path $globalInbox $name;Copy-Item -LiteralPath $alphaCurrent -Destination $dst -Force
                $script:ScenarioPendingGlobalSource=$dst;$script:ScenarioPendingGlobalTarget=Join-Path $alphaInbox $name;$script:ScenarioPendingGlobalSha=(Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash.ToLowerInvariant()
            }
            'registry_pending_global_mixed_invalid' {
                $validName='Keelaryn__Hub_APPROVED_A_bounded-entry.zip';$invalidName='Keelaryn__Hub_APPROVED_Z_bounded-entry.zip'
                $valid=Join-Path $globalInbox $validName;$invalid=Join-Path $globalInbox $invalidName;Copy-Item -LiteralPath $alphaCurrent -Destination $valid -Force;Write-Utf8 $invalid 'not-a-valid-hub-zip'
                $script:ScenarioPendingGlobalSource=$valid;$script:ScenarioPendingGlobalInvalidSource=$invalid;$script:ScenarioPendingGlobalTarget=Join-Path $alphaInbox $validName;$script:ScenarioPendingGlobalSha=(Get-FileHash -LiteralPath $valid -Algorithm SHA256).Hash.ToLowerInvariant()
            }
            'registry_pending_instance' {
                $name='Keelaryn__Hub_APPROVED_bounded-entry.zip';$dst=Join-Path $alphaInbox $name;Copy-Item -LiteralPath $alphaCurrent -Destination $dst -Force;$script:ScenarioPendingInstancePath=$dst
            }
            'active_metadata_invalid' {Write-Utf8 $activeFile '{ not-json'}
            'active_hub_missing' {Remove-Item -LiteralPath $alphaPath -Recurse -Force}
            'active_hub_corrupt' {$stateDoc=Join-Path $alphaPath '_System\STATE.md';if(Test-Path -LiteralPath $stateDoc){Remove-Item -LiteralPath $stateDoc -Force}else{Fail('Alpha structural marker missing before corruption fixture: '+$stateDoc)}}
            'active_current_missing' {Remove-Item -LiteralPath $alphaCurrent -Force;Remove-Item -LiteralPath $legacyCurrent -Force}
            'active_current_corrupt' {Write-Utf8 $alphaCurrent 'not-a-zip';Write-Utf8 $legacyCurrent 'not-a-zip'}
            default {Fail('Unknown bounded Entry fixture: '+$Fixture)}
        }
    }
    function Prepare-ActionFixture($Spec){
        if([string]$Spec.State-ceq'REGISTRY_PENDING_INSTANCE'){
            if($script:ScenarioPendingInstancePath-and(Test-Path -LiteralPath $script:ScenarioPendingInstancePath -PathType Leaf)){Remove-Item -LiteralPath $script:ScenarioPendingInstancePath -Force}
            switch([string]$Spec.ObservationMode){
                'active_instance_candidate_visible' {$script:ScenarioPendingInstancePath=Join-Path $alphaInbox 'Keelaryn__Hub_CANDIDATE_bounded-entry.zip';New-CandidateLikeZip $script:ScenarioPendingInstancePath}
                'active_instance_candidate_transport_scope' {$script:ScenarioPendingInstancePath=Join-Path $alphaInbox 'Keelaryn__Hub_CANDIDATE_bounded-entry.zip';Write-Utf8 $script:ScenarioPendingInstancePath 'not-a-valid-hub-zip'}
                'active_instance_candidate_restore_scope' {$script:ScenarioPendingInstancePath=Join-Path $alphaInbox 'Keelaryn__Hub_CANDIDATE_TRANSPORT_bounded-entry.json';Write-Utf8 $script:ScenarioPendingInstancePath '{ not-json'}
            }
        }
    }
    function Get-ActionArguments($Spec){
        switch([string]$Spec.Action){
            'ListInstances' {return @('-ListInstances')}
            'SwitchInstance' {return @('-SwitchInstanceId',$betaId)}
            'BindInstance' {return @('-BindInstancePath',$betaRelocatedPath,'-RegisterInstanceName','Beta')}
            'UpdateManager' {return @('-UpdateManager')}
            'BuildDistribution' {return @('-BuildDistribution')}
            'BuildRelease' {return @('-BuildRelease')}
            'BuildAIContext' {return @('-BuildAIContext')}
            'Doctor' {return @('-Doctor')}
            'SelfTest' {return @('-SelfTest')}
            'PrepareTests' {return @('-PrepareTests')}
            'InitializePresentation' {return @('-InitializePresentation')}
            'FinalizeFilesystemLayout' {return @('-FinalizeFilesystemLayout')}
            'InitializeInstanceRegistry' {return @('-InitializeInstanceRegistry')}
            'UpdateHub' {if([string]$Spec.ObservationMode-ceq'captured_context_required_fail_closed'){return @('-UpdateHub')};return @('-UpdateHub','-ExpectedInstanceId',$alphaId)}
            'UpdateAll' {if([string]$Spec.ObservationMode-ceq'captured_context_required_fail_closed'){return @('-UpdateAll')};return @('-UpdateAll','-ExpectedInstanceId',$alphaId)}
            'RepairCurrent' {return @('-RepairCurrentTransport')}
            'BuildCandidateTransport' {return @('-BuildCandidateTransport')}
            'RestoreCandidateTransport' {return @('-RestoreCandidateTransport')}
            default {Fail('Unknown bounded Entry action: '+[string]$Spec.Action)}
        }
    }

    foreach($spec in @($specs)){
        $classification='product_contract_failure';$detail='';$exitCode=-999;$pass=$false;$oldSentinel=$env:KEELARYN_ENTRY_ACTION_SENTINEL
        try{
            Reset-ScenarioBaseline;Apply-DegradedFixture ([string]$spec.Fixture);Prepare-ActionFixture $spec
            $updateInboxPath=$null;$sentinelPath=$null
            if([string]$spec.Action -ceq 'UpdateManager' -or [string]$spec.ObservationMode -ceq 'updateall_manager_updates_then_hub_fails_closed'){$updateInboxPath=Join-Path $managerRoot ('state\inbox\'+[string]$successor.FileName);Copy-Item -LiteralPath ([string]$successor.Path) -Destination $updateInboxPath -Force}
            if([string]$spec.Action-ceq'PrepareTests'-and(Test-Path -LiteralPath (Join-Path $keelarynRoot 'tests'))){Remove-Item -LiteralPath (Join-Path $keelarynRoot 'tests') -Recurse -Force}
            if([string]$spec.ObservationMode -ceq 'global_success' -and @('SelfTest','InitializePresentation') -ccontains [string]$spec.Action){$sentinelPath=Join-Path $tempRoot ('dispatch-'+[string]$spec.Id+'.txt');if(Test-Path -LiteralPath $sentinelPath){Remove-Item -LiteralPath $sentinelPath -Force};Set-EntryActionSentinelInstrumentation $runtime ([string]$spec.Action);$env:KEELARYN_ENTRY_ACTION_SENTINEL=$sentinelPath}else{$env:KEELARYN_ENTRY_ACTION_SENTINEL=$null}

            $alphaBefore=Get-TreeDigest $alphaPath;$betaBefore=Get-TreeDigest $betaPath;$betaRelocatedBefore=Get-TreeDigest $betaRelocatedPath
            $registryControl=Join-Path $stateRoot 'instances.json';$registryBefore=if(Test-Path -LiteralPath $registryControl -PathType Leaf){(Get-FileHash -LiteralPath $registryControl -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}
            $activeBefore=if(Test-Path -LiteralPath $activeFile -PathType Leaf){(Get-FileHash -LiteralPath $activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}
            $instancesStatePath=Join-Path $stateRoot 'instances';$compatBaselinePath=Join-Path $stateRoot 'baseline';$instancesStateBefore=Get-TreeDigest $instancesStatePath;$compatBaselineBefore=Get-TreeDigest $compatBaselinePath

            $r=Invoke-Runtime $runtime (Get-ActionArguments $spec);$exitCode=$r.ExitCode
            $hubsUnchanged=((Get-TreeDigest $alphaPath)-ceq$alphaBefore-and(Get-TreeDigest $betaPath)-ceq$betaBefore-and(Get-TreeDigest $betaRelocatedPath)-ceq$betaRelocatedBefore)
            $registryAfter=if(Test-Path -LiteralPath $registryControl -PathType Leaf){(Get-FileHash -LiteralPath $registryControl -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}
            $activeAfter=if(Test-Path -LiteralPath $activeFile -PathType Leaf){(Get-FileHash -LiteralPath $activeFile -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}
            $controlStateUnchanged=($registryAfter-ceq$registryBefore-and$activeAfter-ceq$activeBefore)
            $instancesStateAfter=Get-TreeDigest $instancesStatePath;$compatBaselineAfter=Get-TreeDigest $compatBaselinePath
            $lifecycleStateUnchanged=($controlStateUnchanged-and$instancesStateAfter-ceq$instancesStateBefore-and$compatBaselineAfter-ceq$compatBaselineBefore)

            switch([string]$spec.ObservationMode){
                'list_success' {$pass=($r.ExitCode-eq0-and$r.Text.Contains('Registered Hubs:')-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'registry listing reached through real process entry without Hub/lifecycle mutation'}else{'listing proof failed: '+$r.Text}}
                'target_success' {$activeOk=$false;$registryPathOk=$true;if($r.ExitCode-eq0){try{$activeOk=([string](Read-Active $managerRoot).instance_id-ceq$betaId);if([string]$spec.Action-ceq'BindInstance'){$rows=@((Read-Registry $managerRoot).instances|Where-Object{[string]$_.instance_id-ceq$betaId});$registryPathOk=($rows.Count-eq1-and(Get-PathKey ([string]$rows[0].vault_path))-ceq(Get-PathKey $betaRelocatedPath))}}catch{$activeOk=$false;$registryPathOk=$false}};$pass=($r.ExitCode-eq0-and$activeOk-and$registryPathOk-and$hubsUnchanged);$detail=if($pass){'requested target committed with expected identity/path semantics and no Hub byte movement'}else{'target success proof failed: '+$r.Text}}
                'global_success' {
                    if([string]$spec.Action-ceq'UpdateManager'){$installed=Get-InstalledManagerVersion $managerRoot;$restartObserved=$r.Text.Contains('Manager update: no newer valid Manager package was found.');$packageConsumed=(-not(Test-Path -LiteralPath $updateInboxPath -PathType Leaf));$pass=($r.ExitCode-eq0-and$hubsUnchanged-and$lifecycleStateUnchanged-and$installed -ceq [string]$successor.Version-and$restartObserved-and$packageConsumed);$detail=if($pass){'global Manager update installed synthetic successor, restarted, and preserved Hub lifecycle state'}else{'Manager update proof failed; installed='+$installed+' restart='+$restartObserved+' package_consumed='+$packageConsumed+' output='+$r.Text}}
                    elseif([string]$spec.Action-ceq'InitializeInstanceRegistry'){$pass=($r.ExitCode-eq0-and$hubsUnchanged-and$lifecycleStateUnchanged-and$r.Text.Contains('Multi-Hub registry is already initialized and valid.'));$detail=if($pass){'existing valid registry remained reachable/idempotent'}else{'idempotent registry initialization proof failed: '+$r.Text}}
                    else{$evidenceOk=$false;$evidence='';switch([string]$spec.Action){
                        'BuildDistribution' {$artifact=Join-Path $managerRoot ('state\releases\Keelaryn__Manager_Distribution_v'+$version+'.zip');$evidenceOk=($r.Text.Contains('Generic distribution:')-and(Test-Path -LiteralPath $artifact -PathType Leaf));$evidence='distribution marker+artifact'}
                        'BuildRelease' {$releaseRoot=Join-Path $managerRoot 'state\releases';$names=@(('Keelaryn__Manager_SOURCE_v'+$version+'.zip'),('Keelaryn__Manager_Distribution_v'+$version+'.zip'),('Keelaryn__Manager_Update_v'+$version+'_Built.zip'),('Keelaryn__Manager_AI_CONTEXT_v'+$version+'.zip'),('Keelaryn__Manager_RELEASE_v'+$version+'.json'));$missing=@($names|Where-Object{-not(Test-Path -LiteralPath (Join-Path $releaseRoot $_) -PathType Leaf)});$evidenceOk=($r.Text.Contains('Release build: PASS')-and$missing.Count-eq0);$evidence='release PASS marker+five-artifact bundle'}
                        'BuildAIContext' {$artifact=Join-Path $managerRoot ('state\releases\Keelaryn__Manager_AI_CONTEXT_v'+$version+'.zip');$evidenceOk=($r.Text.Contains('AI_CONTEXT build: PASS')-and(Test-Path -LiteralPath $artifact -PathType Leaf));$evidence='AI_CONTEXT marker+artifact'}
                        'SelfTest' {$evidenceOk=($sentinelPath-and(Test-Path -LiteralPath $sentinelPath -PathType Leaf)-and([IO.File]::ReadAllText($sentinelPath,[Text.Encoding]::ASCII)-ceq'SelfTest'));$evidence='exact SelfTest dispatch sentinel'}
                        'PrepareTests' {$receipt=Join-Path $keelarynRoot 'tests\WORKSPACE.json';$evidenceOk=($r.Text.Contains('Keelaryn tests workspace ready.')-and(Test-Path -LiteralPath $receipt -PathType Leaf));$evidence='tests-workspace marker+receipt'}
                        'InitializePresentation' {$evidenceOk=($sentinelPath-and(Test-Path -LiteralPath $sentinelPath -PathType Leaf)-and([IO.File]::ReadAllText($sentinelPath,[Text.Encoding]::ASCII)-ceq'InitializePresentation'));$evidence='exact InitializePresentation dispatch sentinel'}
                        'FinalizeFilesystemLayout' {$layout=Join-Path $managerRoot 'state\layout.json';$evidenceOk=($r.Text.Contains('Manager filesystem layout is already finalized.')-and(Test-Path -LiteralPath $layout -PathType Leaf));$evidence='already-finalized marker+layout receipt'}
                        default {Fail('global_success lacks action-specific bounded oracle for '+[string]$spec.Action)}
                    };$pass=($r.ExitCode-eq0-and$hubsUnchanged-and$lifecycleStateUnchanged-and$evidenceOk);$detail=if($pass){'Manager-global dispatch reached action-specific evidence ('+$evidence+')'}else{'Manager-global action proof failed ('+$evidence+'): '+$r.Text}}
                }
                'diagnostic_reached' {$pass=($r.Text.Contains('Keelaryn Doctor - Manager')-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'Doctor reached diagnostic body read-only; exit='+$r.ExitCode}else{'Doctor diagnostic proof failed: '+$r.Text}}
                'registry_document_rejected_after_dispatch' {$startupBlocked=$r.Text.Contains('Invalid Keelaryn multi-Hub registry:');$operationReached=$r.Text.Contains('Manager instance registry JSON is invalid:');$pass=($r.ExitCode-ne0-and$hubsUnchanged-and$lifecycleStateUnchanged-and-not$startupBlocked-and$operationReached);$detail=if($pass){'invalid registry reached operation-level parser and was rejected without mutation'}else{'registry document rejection proof failed: '+$r.Text}}
                'registry_init_rejected_after_dispatch' {$reached=$r.Text.Contains('Existing multi-Hub registry is invalid:');$pass=($r.ExitCode-ne0-and$hubsUnchanged-and$lifecycleStateUnchanged-and$reached);$detail=if($pass){'registry initialization rejected invalid authoritative state after dispatch'}else{'registry-init rejection proof failed: '+$r.Text}}
                'captured_context_required_fail_closed' {$contextSignal=($r.Text-match'(?i)(captured Hub context|active instance|active Hub|registry|binding)');$pass=($r.ExitCode-ne0-and$hubsUnchanged-and$lifecycleStateUnchanged-and$contextSignal);$detail=if($pass){'missing/unresolvable captured context failed closed without lifecycle mutation'}else{'captured-context rejection proof failed: '+$r.Text}}
                'fail_closed' {$pass=($r.ExitCode-ne0-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'operation failed closed without Hub/lifecycle mutation'}else{'fail-closed proof failed: '+$r.Text}}
                'target_rejected_no_mutation' {$activeStillAlpha=$false;try{$activeStillAlpha=([string](Read-Active $managerRoot).instance_id-ceq$alphaId)}catch{};$pass=($r.ExitCode-ne0-and$activeStillAlpha-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'ineligible/missing requested target was rejected and active selection/lifecycle stayed unchanged'}else{'target rejection proof failed: '+$r.Text}}
                'stranded_global_blocked' {$sourceRemains=($script:ScenarioPendingGlobalSource-and(Test-Path -LiteralPath $script:ScenarioPendingGlobalSource -PathType Leaf));$legacySignal=$r.Text.Contains('remain in the global Manager inbox')-and$r.Text.Contains('reconcile identity-bound inputs first');$claimSignal=$r.Text.Contains('refused because unresolved Hub-input reconciliation state remains')-and$r.Text.Contains('Run Initialize instance registry');$reached=($legacySignal-or$claimSignal);$pass=($r.ExitCode-ne0-and$sourceRemains-and$reached-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'unresolved global Hub input explicitly blocked instance-bound operation without mutation'}else{'stranded-global blocking proof failed: '+$r.Text}}
                'doctor_stranded_global_diagnostic' {$sourceRemains=($script:ScenarioPendingGlobalSource-and(Test-Path -LiteralPath $script:ScenarioPendingGlobalSource -PathType Leaf));$pass=($r.Text.Contains('Keelaryn Doctor - Manager')-and$r.Text.Contains('[WARN] inbox.hub_global_stranded:')-and$sourceRemains-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'Doctor surfaced distinct stranded-global diagnostic without mutation'}else{'stranded-global Doctor proof failed: '+$r.Text}}
                'registry_init_reconciles_global_input' {$sourceConsumed=($script:ScenarioPendingGlobalSource-and-not(Test-Path -LiteralPath $script:ScenarioPendingGlobalSource -PathType Leaf));$targetOk=$false;if($script:ScenarioPendingGlobalTarget-and(Test-Path -LiteralPath $script:ScenarioPendingGlobalTarget -PathType Leaf)){$targetOk=((Get-FileHash -LiteralPath $script:ScenarioPendingGlobalTarget -Algorithm SHA256).Hash.ToLowerInvariant() -ceq [string]$script:ScenarioPendingGlobalSha)};$pass=($r.ExitCode-eq0-and$hubsUnchanged-and$controlStateUnchanged-and$compatBaselineAfter-ceq$compatBaselineBefore-and$sourceConsumed-and$targetOk-and$r.Text.Contains('Reconciled 1 identity-bound Hub input(s)'));$detail=if($pass){'existing-registry initialization reconciled one exact identity-bound global input'}else{'global reconciliation proof failed: '+$r.Text}}
                'registry_init_mixed_invalid_preserves_completed_handoff_and_failed_claim' {$validName=[IO.Path]::GetFileName([string]$script:ScenarioPendingGlobalSource);$invalidName=[IO.Path]::GetFileName([string]$script:ScenarioPendingGlobalInvalidSource);$validConsumed=($script:ScenarioPendingGlobalSource-and-not(Test-Path -LiteralPath $script:ScenarioPendingGlobalSource -PathType Leaf));$invalidConsumed=($script:ScenarioPendingGlobalInvalidSource-and-not(Test-Path -LiteralPath $script:ScenarioPendingGlobalInvalidSource -PathType Leaf));$targetExact=$false;if($script:ScenarioPendingGlobalTarget-and(Test-Path -LiteralPath $script:ScenarioPendingGlobalTarget -PathType Leaf)){$targetExact=((Get-FileHash -LiteralPath $script:ScenarioPendingGlobalTarget -Algorithm SHA256).Hash.ToLowerInvariant()-ceq[string]$script:ScenarioPendingGlobalSha)};$validCopies=@(Get-ChildItem -LiteralPath $instancesStatePath -File -Recurse -Force|Where-Object{$_.Name-ceq$validName});$validScoped=($validCopies.Count-eq1-and[IO.Path]::GetFullPath($validCopies[0].FullName)-ceq[IO.Path]::GetFullPath([string]$script:ScenarioPendingGlobalTarget));$invalidCopies=@(Get-ChildItem -LiteralPath $instancesStatePath -File -Recurse -Force|Where-Object{$_.Name-ceq$invalidName});$claims=@(Get-BoundedReconciliationClaims $managerRoot);$invalidClaims=@($claims|Where-Object{[string]$_.Metadata.original_name-ceq$invalidName});$invalidClaimDurable=($invalidClaims.Count-eq1-and(Test-Path -LiteralPath ([string]$invalidClaims[0].Payload) -PathType Leaf));$pass=($r.ExitCode-ne0-and$validConsumed-and$invalidConsumed-and$targetExact-and$validScoped-and$invalidCopies.Count-eq0-and$invalidClaimDurable-and$claims.Count-eq1-and$hubsUnchanged-and$controlStateUnchanged-and$compatBaselineAfter-ceq$compatBaselineBefore);$detail=if($pass){'per-artifact reconciliation preserved the earlier exact handoff and retained the later invalid artifact as one durable blocking claim'}else{'mixed-invalid claim-aware registry-init proof failed: '+$r.Text}}
                'active_instance_candidate_visible' {$candidateRemains=($script:ScenarioPendingInstancePath-and(Test-Path -LiteralPath $script:ScenarioPendingInstancePath -PathType Leaf));$pass=($r.ExitCode-eq0-and$candidateRemains-and$r.Text.Contains('1 CANDIDATE package(s) left pending for Chat Manager.')-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'UpdateHub surfaced candidate from captured active-instance inbox only'}else{'active-instance candidate visibility proof failed: '+$r.Text}}
                'active_instance_candidate_transport_scope' {$candidateRemains=($script:ScenarioPendingInstancePath-and(Test-Path -LiteralPath $script:ScenarioPendingInstancePath -PathType Leaf));$reached=(-not $r.Text.Contains('No Hub CANDIDATE is available. Nothing to build.'));$pass=($r.ExitCode-ne0-and$candidateRemains-and$reached-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'BuildCandidateTransport consumed active-instance inbox scope and rejected the deliberately invalid candidate'}else{'active-instance transport-build scope proof failed: '+$r.Text}}
                'active_instance_candidate_restore_scope' {$transportRemains=($script:ScenarioPendingInstancePath-and(Test-Path -LiteralPath $script:ScenarioPendingInstancePath -PathType Leaf));$reached=(-not $r.Text.Contains('No Hub CANDIDATE transport is available. Nothing to restore.'));$pass=($r.ExitCode-ne0-and$transportRemains-and$reached-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'RestoreCandidateTransport consumed active-instance inbox scope and rejected deliberately invalid transport JSON'}else{'active-instance transport-restore scope proof failed: '+$r.Text}}
                'updateall_manager_updates_then_hub_fails_closed' {$installed=Get-InstalledManagerVersion $managerRoot;$packageConsumed=(-not(Test-Path -LiteralPath $updateInboxPath -PathType Leaf));$pass=($r.ExitCode-ne0-and$installed -ceq [string]$successor.Version-and$packageConsumed-and$hubsUnchanged-and$lifecycleStateUnchanged);$detail=if($pass){'UpdateAll installed global Manager successor, then failed closed on the captured broken Hub without retargeting'}else{'UpdateAll split-phase proof failed; installed='+$installed+' package_consumed='+$packageConsumed+' output='+$r.Text}}
                default {Fail('Unsupported bounded Entry observation mode: '+[string]$spec.ObservationMode)}
            }
        }catch{$classification='harness_or_fixture_error';$detail=$_.Exception.Message;$pass=$false}
        finally{$env:KEELARYN_ENTRY_ACTION_SENTINEL=$oldSentinel}
        [void]$results.Add([ordered]@{id=[string]$spec.Id;kind=[string]$spec.Kind;state=[string]$spec.State;action=[string]$spec.Action;winning_rule=[string]$spec.WinningRule;outcome=[string]$spec.Outcome;observation_mode=[string]$spec.ObservationMode;pass=$pass;classification=if($pass){'pass'}else{$classification};exit_code=$exitCode;detail=$detail})
        Write-Host ('  '+$(if($pass){'PASS'}else{'FAIL'})+' '+[string]$spec.Id+' '+[string]$spec.State+' x '+[string]$spec.Action+' rule='+[string]$spec.WinningRule+' :: '+$detail) -ForegroundColor $(if($pass){'Green'}else{'Red'})
    }
}catch{$harnessError=$_.Exception.Message;Write-Host ('BOUNDED ENTRY HARNESS ERROR: '+$harnessError) -ForegroundColor Red}
finally{if(Test-Path -LiteralPath $planPath){Remove-Item -LiteralPath $planPath -Force -ErrorAction SilentlyContinue}}

$failed=@($results|Where-Object{-not [bool]$_.pass});$syntheticSuccessorVersion=if($null-ne$successor){[string]$successor.Version}else{''}
$report=[ordered]@{
    schema='keelaryn.manager-bounded-entry-result.v1';manager_version=$version;semantic_owner=[string]$oracles.semantic_owner
    plan_derived_edge_count=[int]$plan.derived_edge_count;executed_count=@($results).Count;fixed_scenario_count_requirement=$false;transaction_fault_injection_included=$false
    oracle_contract_sha256=(Get-FileHash -LiteralPath $oraclePath -Algorithm SHA256).Hash.ToLowerInvariant();plan_control_flow_sha256=[string]$plan.control_flow_sha256;plan_state_machine_sha256=[string]$plan.state_machine_sha256
    pass=($null-eq$harnessError-and$failed.Count-eq0-and@($results).Count-eq[int]$plan.derived_edge_count);harness_error=$harnessError;failures=@($failed|ForEach-Object{[string]$_.id});edges=@($results)
    production_hub_used=$false;scenario_reset='direct_external_full_manager_and_hub_snapshot_restore';synthetic_successor_version=$syntheticSuccessorVersion;completed_utc=[DateTime]::UtcNow.ToString('o')
}
try{Write-Json $OutputPath $report;Write-Host ('Evidence: '+$OutputPath)}catch{Write-Host ('Could not write bounded Entry evidence: '+$_.Exception.Message) -ForegroundColor Red;if(-not$harnessError){$harnessError=$_.Exception.Message}}
try{if(Test-Path -LiteralPath $tempRoot){Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction Stop}}catch{Write-Warning('Disposable cleanup failed: '+$_.Exception.Message)}
if($harnessError-or$failed.Count-ne0-or@($results).Count-ne[int]$plan.derived_edge_count){Write-Host ('MANAGER BOUNDED ENTRY REACHABILITY: FAIL; executed='+@($results).Count+' failures='+$failed.Count+' harness_error='+[bool]$harnessError) -ForegroundColor Red;exit 1}
Write-Host ('MANAGER BOUNDED ENTRY REACHABILITY: PASS; derived_edges='+[int]$plan.derived_edge_count+' executed='+@($results).Count) -ForegroundColor Green
exit 0
