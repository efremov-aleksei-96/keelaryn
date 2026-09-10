[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..\..'),
    [string]$OutputDirectory=(Join-Path $env:RUNNER_TEMP 'keelaryn-multihub-downgrade'),
    [string]$EvidencePath=''
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$OutputDirectory=[System.IO.Path]::GetFullPath($OutputDirectory).TrimEnd('\')
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
$LegacyVersion='4.16.3'
$LegacyBundleUrl='https://github.com/efremov-aleksei-96/keelaryn/releases/download/v4.16.3/Keelaryn_v4.16.3_Windows.zip'
$LegacyBundleSha256='335d0eaa3302ad7e7bde9a422d56bd3d267bf638023697d355801c3d6db9447c'

function Fail([string]$Message){throw $Message}
function Read-Json([string]$Path){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){Fail('JSON file missing: '+$Path)}
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8|ConvertFrom-Json)
}
function Write-Json([string]$Path,$Object){
    $parent=Split-Path -Parent $Path
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    $text=(($Object|ConvertTo-Json -Depth 30).Replace("`r`n","`n"))+"`n"
    [System.IO.File]::WriteAllText($Path,$text,$Utf8NoBom)
}
function Sha([string]$Path){
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){Fail('Hash target missing: '+$Path)}
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Get-TextSha256([string]$Text){
    $sha=[System.Security.Cryptography.SHA256]::Create()
    try{return ([BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text))).Replace('-','').ToLowerInvariant())}
    finally{$sha.Dispose()}
}
function Get-TreeDigest([string]$Root){
    $item=Get-Item -LiteralPath $Root -Force -ErrorAction Stop
    if(-not$item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Tree root is unsafe: '+$Root)}
    $base=$item.FullName.TrimEnd('\');$rows=New-Object System.Collections.ArrayList
    foreach($file in @(Get-ChildItem -LiteralPath $base -File -Recurse -Force|Sort-Object FullName)){
        if(($file.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Tree contains reparse point: '+$file.FullName)}
        $rel=$file.FullName.Substring($base.Length).TrimStart('\').Replace('\','/')
        [void]$rows.Add($rel+"`0"+[long]$file.Length+"`0"+(Sha $file.FullName))
    }
    return Get-TextSha256 ([string]::Join("`n",@($rows)))
}
function Invoke-Manager([string]$Runtime,[string[]]$Arguments,[int[]]$AllowedCodes=@(0)){
    if($null-eq$Arguments){$Arguments=@()}
    $old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $output=@(& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Runtime @Arguments 2>&1)
        $code=[int]$LASTEXITCODE
    }finally{$ErrorActionPreference=$old}
    foreach($line in @($output)){Write-Host ([string]$line)}
    if($AllowedCodes-notcontains$code){Fail('Manager command failed. exit='+$code+' runtime='+$Runtime+' args='+($Arguments-join' ')+' output='+([string]::Join(' | ',@($output|ForEach-Object{[string]$_}))))}
    return [pscustomobject]@{Code=$code;Output=@($output|ForEach-Object{[string]$_})}
}
function Copy-ManagedManager([string]$Source,[string]$Destination){
    $install=Read-Json (Join-Path $Source 'product\install\INSTALLATION.json')
    if(Test-Path -LiteralPath $Destination){Remove-Item -LiteralPath $Destination -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Destination|Out-Null
    foreach($raw in @($install.managed_files)){
        $rel=([string]$raw).Replace('/','\')
        $src=Join-Path $Source $rel;$dst=Join-Path $Destination $rel
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)){Fail('Managed source missing: '+$rel)}
        $parent=Split-Path -Parent $dst;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
}
function Assert-RelativeManagerPath([string]$ManagerRoot,[string]$Relative){
    $rel=([string]$Relative).Replace('/','\').Trim('\')
    if(-not$rel-or[System.IO.Path]::IsPathRooted($rel)-or$rel.Contains(':')){Fail('Unsafe rollback target: '+$Relative)}
    foreach($segment in @($rel-split'\\')){if(-not$segment-or$segment-eq'.'-or$segment-eq'..'){Fail('Unsafe rollback target: '+$Relative)}}
    $root=[System.IO.Path]::GetFullPath($ManagerRoot).TrimEnd('\')
    $full=[System.IO.Path]::GetFullPath((Join-Path $root $rel))
    if(-not$full.StartsWith($root+'\',[System.StringComparison]::OrdinalIgnoreCase)){Fail('Rollback target escapes Manager root: '+$Relative)}
    return $rel
}
function Restore-ManagerRollbackSnapshotForTest([string]$ManagerRoot,[string]$Snapshot){
    $snap=Get-Item -LiteralPath $Snapshot -Force -ErrorAction Stop
    if(-not$snap.PSIsContainer-or($snap.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Rollback snapshot root is unsafe: '+$Snapshot)}
    $manifestPath=Join-Path $snap.FullName '_snapshot_manifest.json';$manifest=Read-Json $manifestPath
    if([string]$manifest.schema-ne'keelaryn.manager.rollback-snapshot.v2'){Fail('Unsupported rollback snapshot schema.')}
    if([string]$manifest.manager_version-ne$LegacyVersion){Fail('Rollback snapshot is not the expected '+$LegacyVersion+' state.')}
    $targets=@();$seen=@{}
    foreach($raw in @($manifest.target_paths)){
        $rel=Assert-RelativeManagerPath $ManagerRoot ([string]$raw);$key=$rel.ToLowerInvariant()
        if($seen.ContainsKey($key)){Fail('Duplicate rollback target: '+$rel)};$seen[$key]=$true;$targets+=$rel
    }
    if($targets.Count-eq0){Fail('Rollback snapshot contains no targets.')}
    $restore=@();$fileSeen=@{}
    foreach($row in @($manifest.files)){
        $rel=Assert-RelativeManagerPath $ManagerRoot ([string]$row.path);$key=$rel.ToLowerInvariant()
        if(-not$seen.ContainsKey($key)-or$fileSeen.ContainsKey($key)){Fail('Invalid rollback file set: '+$rel)};$fileSeen[$key]=$true
        $src=Join-Path $snap.FullName ('files\'+$rel);$srcItem=Get-Item -LiteralPath $src -Force -ErrorAction Stop
        if($srcItem.PSIsContainer-or($srcItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Rollback source is unsafe: '+$rel)}
        if([long]$srcItem.Length-ne[long]$row.size_bytes-or(Sha $src)-ne([string]$row.sha256).ToLowerInvariant()){Fail('Rollback source metadata mismatch: '+$rel)}
        $restore+=[pscustomobject]@{Path=$rel;Source=$src}
    }
    foreach($rel in $targets){
        $dst=Join-Path $ManagerRoot $rel
        if(Test-Path -LiteralPath $dst){
            $dstItem=Get-Item -LiteralPath $dst -Force -ErrorAction Stop
            if($dstItem.PSIsContainer-or($dstItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Rollback destination is unsafe: '+$rel)}
            Remove-Item -LiteralPath $dst -Force
        }
    }
    foreach($row in $restore){
        $dst=Join-Path $ManagerRoot $row.Path;$parent=Split-Path -Parent $dst
        if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        Copy-Item -LiteralPath $row.Source -Destination $dst -Force
        if((Sha $dst)-ne(Sha $row.Source)){Fail('Rollback publish verification failed: '+$row.Path)}
    }
}
function Get-InstanceId([string]$HubPath){
    $doc=Read-Json (Join-Path $HubPath '_System\INSTANCE.json')
    $id=([string]$doc.instance_id).Trim().ToLowerInvariant()
    $g=[guid]::Empty;if(-not[guid]::TryParse($id,[ref]$g)-or$g-eq[guid]::Empty){Fail('Invalid Hub instance_id at '+$HubPath)}
    return $id
}
function Get-ManagerVersion([string]$ManagerRoot){return ([string](Read-Json (Join-Path $ManagerRoot 'product\install\INSTALLATION.json')).manager_version).Trim()}
function Assert-Shadow([string]$ManagerRoot,[string]$ExpectedId,[string]$ExpectedVault){
    $state=Join-Path $ManagerRoot 'state';$binding=Read-Json (Join-Path $state 'binding.json');$active=Read-Json (Join-Path $state 'active_instance.json');$registry=Read-Json (Join-Path $state 'instances.json')
    if([string]$binding.schema-ne'keelaryn.manager.instance-binding.v2'-or([string]$binding.instance_id).ToLowerInvariant()-ne$ExpectedId){Fail('Compatibility binding does not identify expected active instance.')}
    $actualVault=[System.IO.Path]::GetFullPath([string]$binding.vault_path).TrimEnd('\');$wantedVault=[System.IO.Path]::GetFullPath($ExpectedVault).TrimEnd('\')
    if(-not[string]::Equals($actualVault,$wantedVault,[System.StringComparison]::OrdinalIgnoreCase)){Fail('Compatibility binding vault_path mismatch.')}
    if(([string]$active.instance_id).ToLowerInvariant()-ne$ExpectedId){Fail('active_instance.json mismatch.')}
    $rows=@($registry.instances|Where-Object{([string]$_.instance_id).ToLowerInvariant()-eq$ExpectedId})
    if($rows.Count-ne1){Fail('Registry does not contain exactly one expected active row.')}
    if(-not[string]::Equals([System.IO.Path]::GetFullPath([string]$rows[0].vault_path).TrimEnd('\'),$wantedVault,[System.StringComparison]::OrdinalIgnoreCase)){Fail('Registry active vault_path mismatch.')}
    $global=Join-Path $state 'baseline\Keelaryn__Hub_CURRENT.zip';$per=Join-Path $state ('instances\'+$ExpectedId+'\baseline\Keelaryn__Hub_CURRENT.zip')
    $gh=Sha $global;$ph=Sha $per;if($gh-ne$ph){Fail('Legacy compatibility CURRENT differs from active per-instance CURRENT.')}
    return [pscustomobject]@{Global=$global;Per=$per;Sha256=$gh}
}
function Invoke-DoctorAssert([string]$Runtime,[string]$ManagerRoot,[string]$ExpectedId,[bool]$RequireCompatibilityFinding){
    $result=Invoke-Manager $Runtime @('-Doctor') @(0,2)
    $report=Read-Json (Join-Path $ManagerRoot 'state\logs\DOCTOR_REPORT.json')
    if([int]$report.errors-ne0){Fail('Doctor reported errors under Manager '+[string]$report.manager_version+'.')}
    if($null-ne$report.PSObject.Properties['instance_id']){
        if(([string]$report.instance_id).ToLowerInvariant()-ne$ExpectedId){Fail('Doctor resolved the wrong active instance under Manager '+[string]$report.manager_version+'.')}
    }else{
        # 4.16.3 predates the report-level instance_id field. Its resolved identity is
        # still proven by the same binding document that Doctor reports as binding.resolve.
        $legacyBinding=Read-Json (Join-Path $ManagerRoot 'state\binding.json')
        if(([string]$legacyBinding.instance_id).ToLowerInvariant()-ne$ExpectedId){Fail('Legacy Doctor binding resolved the wrong active instance.')}
    }
    if($RequireCompatibilityFinding){
        $rows=@($report.findings|Where-Object{[string]$_.Code-eq'compatibility.shadow'})
        if($rows.Count-ne1-or[string]$rows[0].Severity-ne'OK'){Fail('Doctor did not prove compatibility.shadow=OK.')}
    }
    return [pscustomobject]@{ExitCode=$result.Code;Warnings=[int]$report.warnings;ManagerVersion=[string]$report.manager_version}
}

$repositoryManager=Join-Path $RepositoryRoot 'manager'
$currentVersion=Get-ManagerVersion $repositoryManager
if([version]$currentVersion-le[version]$LegacyVersion){Fail('Current Manager must be newer than downgrade fixture '+$LegacyVersion+'.')}
if(-not$EvidencePath){$EvidencePath=Join-Path $OutputDirectory 'MULTIHUB_DOWNGRADE_COMPATIBILITY.json'}
$EvidencePath=[System.IO.Path]::GetFullPath($EvidencePath)
if(Test-Path -LiteralPath $OutputDirectory){Remove-Item -LiteralPath $OutputDirectory -Recurse -Force}
New-Item -ItemType Directory -Force -Path $OutputDirectory|Out-Null
$work=Join-Path $OutputDirectory 'work';New-Item -ItemType Directory -Force -Path $work|Out-Null

Write-Host ('Keelaryn multi-Hub downgrade compatibility - current '+$currentVersion+' / fixture '+$LegacyVersion)
Write-Host '[1/10] Acquire exact immutable 4.16.3 Windows distribution...'
[System.Net.ServicePointManager]::SecurityProtocol=[System.Net.SecurityProtocolType]::Tls12
$legacyZip=Join-Path $work 'Keelaryn_v4.16.3_Windows.zip'
Invoke-WebRequest -UseBasicParsing -Uri $LegacyBundleUrl -OutFile $legacyZip
if((Sha $legacyZip)-ne$LegacyBundleSha256){Fail('Immutable 4.16.3 Windows bundle SHA-256 mismatch.')}
$legacyExtract=Join-Path $work 'legacy-extract';Expand-Archive -LiteralPath $legacyZip -DestinationPath $legacyExtract -Force
$layout=Join-Path $legacyExtract 'keelaryn';$manager=Join-Path $layout 'manager';$runtime=Join-Path $manager 'product\runtime\Keelaryn__Manager.ps1'
if(-not(Test-Path -LiteralPath $runtime -PathType Leaf)){Fail('4.16.3 distribution layout is unexpected.')}
if((Get-ManagerVersion $manager)-ne$LegacyVersion){Fail('Downloaded distribution Manager version mismatch.')}
$null=Invoke-Manager $runtime @('-SelfTest')

Write-Host '[2/10] Create Alpha under the real 4.16.3 runtime...'
$config=Join-Path $work 'genesis.json'
Write-Json $config ([ordered]@{schema='keelaryn.genesis-input.v1';language='en';purpose='mixed';timezone='UTC';areas=@();projects=@()})
$null=Invoke-Manager $runtime @('-Genesis','-GenesisConfigPath',$config,'-GenesisConfirmed')
$alpha=Join-Path $layout 'hub';$alphaId=Get-InstanceId $alpha;$alphaDigest=Get-TreeDigest $alpha

Write-Host '[3/10] Build current UPDATE from exact development source and upgrade 4.16.3 -> current...'
$buildLayout=Join-Path $work 'current-build\keelaryn';$buildManager=Join-Path $buildLayout 'manager';New-Item -ItemType Directory -Force -Path $buildLayout|Out-Null
Copy-ManagedManager $repositoryManager $buildManager
$buildRuntime=Join-Path $buildManager 'product\runtime\Keelaryn__Manager.ps1'
$null=Invoke-Manager $buildRuntime @('-BuildRelease')
$updateName='Keelaryn__Manager_Update_v'+$currentVersion+'_Built.zip';$builtUpdate=Join-Path $buildManager ('state\releases\'+$updateName)
if(-not(Test-Path -LiteralPath $builtUpdate -PathType Leaf)){Fail('Current UPDATE artifact was not built.')}
$updateCopy=Join-Path $work $updateName;Copy-Item -LiteralPath $builtUpdate -Destination $updateCopy -Force;$updateSha=Sha $updateCopy
$inbox=Join-Path $manager 'state\inbox';New-Item -ItemType Directory -Force -Path $inbox|Out-Null;Copy-Item -LiteralPath $updateCopy -Destination (Join-Path $inbox $updateName) -Force
$null=Invoke-Manager $runtime @('-UpdateManager')
$runtime=Join-Path $manager 'product\runtime\Keelaryn__Manager.ps1'
if((Get-ManagerVersion $manager)-ne$currentVersion){Fail('Upgrade to current Manager did not commit.')}
$null=Invoke-Manager $runtime @('-SelfTest')
if((Get-TreeDigest $alpha)-ne$alphaDigest){Fail('Alpha Hub changed during Manager upgrade.')}
$snapshots=@(Get-ChildItem -LiteralPath (Join-Path $manager 'state\history\manager_updates') -Directory -Force|Where-Object{try{[string](Read-Json (Join-Path $_.FullName '_snapshot_manifest.json')).manager_version-eq$LegacyVersion}catch{$false}}|Sort-Object LastWriteTime -Descending)
if($snapshots.Count-lt1){Fail('4.16.3 rollback snapshot was not preserved by the real update.')}
$legacySnapshot=$snapshots[0].FullName;$snapshotManifestSha=Sha (Join-Path $legacySnapshot '_snapshot_manifest.json')

Write-Host '[4/10] Initialize registry, create Beta, switch active Hub, and prove compatibility shadow...'
$null=Invoke-Manager $runtime @('-InitializeInstanceRegistry','-RegisterInstanceName','Alpha')
$alphaShadow=Assert-Shadow $manager $alphaId $alpha
$alphaCurrentGood=Join-Path $work 'alpha-current-good.zip';Copy-Item -LiteralPath $alphaShadow.Per -Destination $alphaCurrentGood -Force
$hubsRoot=Join-Path $layout 'hubs';New-Item -ItemType Directory -Force -Path $hubsRoot|Out-Null
$beta=Join-Path $hubsRoot 'beta'
$null=Invoke-Manager $runtime @('-GenesisInstancePath',$beta,'-GenesisInstanceName','Beta','-GenesisConfigPath',$config,'-GenesisConfirmed')
$betaId=Get-InstanceId $beta;$betaDigest=Get-TreeDigest $beta
$null=Invoke-Manager $runtime @('-SwitchInstanceId',$betaId)
$betaShadow=Assert-Shadow $manager $betaId $beta
$betaCurrentGood=Join-Path $work 'beta-current-good.zip';Copy-Item -LiteralPath $betaShadow.Per -Destination $betaCurrentGood -Force
$doctorCurrentBefore=Invoke-DoctorAssert $runtime $manager $betaId $true
if((Get-TreeDigest $alpha)-ne$alphaDigest-or(Get-TreeDigest $beta)-ne$betaDigest){Fail('Hub bytes changed during registry/active switch.')}

Write-Host '[5/10] Downgrade exact Manager product bytes through the real 4.16.3 rollback snapshot...'
Restore-ManagerRollbackSnapshotForTest $manager $legacySnapshot
$runtime=Join-Path $manager 'product\runtime\Keelaryn__Manager.ps1'
if((Get-ManagerVersion $manager)-ne$LegacyVersion){Fail('Rollback did not restore Manager '+$LegacyVersion+'.')}
$null=Invoke-Manager $runtime @('-SelfTest')
$bindingAfterDowngrade=Read-Json (Join-Path $manager 'state\binding.json')
if(([string]$bindingAfterDowngrade.instance_id).ToLowerInvariant()-ne$betaId){Fail('Downgrade lost active Beta compatibility binding.')}
if((Sha (Join-Path $manager 'state\baseline\Keelaryn__Hub_CURRENT.zip'))-ne(Sha $betaCurrentGood)){Fail('Downgrade lost active Beta compatibility CURRENT.')}
$doctorLegacy=Invoke-DoctorAssert $runtime $manager $betaId $false
if((Get-TreeDigest $alpha)-ne$alphaDigest-or(Get-TreeDigest $beta)-ne$betaDigest){Fail('Hub bytes changed during downgrade/legacy Doctor.')}

Write-Host '[6/10] Re-upgrade 4.16.3 -> current and prove Beta recovery...'
Copy-Item -LiteralPath $updateCopy -Destination (Join-Path $manager ('state\inbox\'+$updateName)) -Force
$null=Invoke-Manager $runtime @('-UpdateManager')
$runtime=Join-Path $manager 'product\runtime\Keelaryn__Manager.ps1'
if((Get-ManagerVersion $manager)-ne$currentVersion){Fail('Re-upgrade to current Manager failed.')}
$null=Invoke-Manager $runtime @('-ListInstances')
$betaShadow=Assert-Shadow $manager $betaId $beta
if($betaShadow.Sha256-ne(Sha $betaCurrentGood)){Fail('Re-upgrade did not preserve exact Beta CURRENT bytes.')}
$doctorCurrentAfter=Invoke-DoctorAssert $runtime $manager $betaId $true
if((Get-TreeDigest $alpha)-ne$alphaDigest-or(Get-TreeDigest $beta)-ne$betaDigest){Fail('Hub bytes changed during re-upgrade/recovery.')}

Write-Host '[7/10] Exercise safe adoption: stale per-instance CURRENT + valid active legacy CURRENT...'
$state=Join-Path $manager 'state';$globalCurrent=Join-Path $state 'baseline\Keelaryn__Hub_CURRENT.zip';$betaPer=Join-Path $state ('instances\'+$betaId+'\baseline\Keelaryn__Hub_CURRENT.zip')
Copy-Item -LiteralPath $alphaCurrentGood -Destination $betaPer -Force
if((Sha $betaPer)-eq(Sha $globalCurrent)){Fail('Safe-adoption fixture did not create the intended stale per-instance state.')}
$null=Invoke-Manager $runtime @('-ListInstances')
$adopted=Assert-Shadow $manager $betaId $beta
if($adopted.Sha256-ne(Sha $betaCurrentGood)){Fail('Safe adoption did not recover per-instance CURRENT from valid legacy CURRENT.')}
if((Get-TreeDigest $alpha)-ne$alphaDigest-or(Get-TreeDigest $beta)-ne$betaDigest){Fail('Hub bytes changed during safe adoption.')}

Write-Host '[8/10] Exercise ambiguous fail-closed: active Beta but both CURRENT copies belong to Alpha...'
Copy-Item -LiteralPath $alphaCurrentGood -Destination $betaPer -Force
Copy-Item -LiteralPath $alphaCurrentGood -Destination $globalCurrent -Force
$ambiguousBeforePer=Sha $betaPer;$ambiguousBeforeGlobal=Sha $globalCurrent
$ambiguous=Invoke-Manager $runtime @('-ListInstances') @(1)
if(([string]::Join("`n",@($ambiguous.Output)))-notmatch'Ambiguous multi-Hub compatibility shadow'){Fail('Ambiguous compatibility state failed for an unexpected reason.')}
if((Sha $betaPer)-ne$ambiguousBeforePer-or(Sha $globalCurrent)-ne$ambiguousBeforeGlobal){Fail('Ambiguous fail-closed path mutated CURRENT state.')}
if((Get-TreeDigest $alpha)-ne$alphaDigest-or(Get-TreeDigest $beta)-ne$betaDigest){Fail('Ambiguous fail-closed path mutated Hub bytes.')}

Write-Host '[9/10] Restore coherent Beta shadow externally and run final Manager recovery/Doctor...'
Copy-Item -LiteralPath $betaCurrentGood -Destination $betaPer -Force
Copy-Item -LiteralPath $betaCurrentGood -Destination $globalCurrent -Force
$null=Invoke-Manager $runtime @('-ListInstances')
$finalShadow=Assert-Shadow $manager $betaId $beta
$doctorFinal=Invoke-DoctorAssert $runtime $manager $betaId $true
if((Get-TreeDigest $alpha)-ne$alphaDigest-or(Get-TreeDigest $beta)-ne$betaDigest){Fail('Final recovery changed Hub bytes.')}

Write-Host '[10/10] Write compact qualification evidence and remove disposable work...'
$evidence=[ordered]@{
    schema='keelaryn.manager-multihub-downgrade-compatibility.v1'
    classification='development_only'
    source_sha=$env:GITHUB_SHA
    current_manager_version=$currentVersion
    downgrade_fixture=[ordered]@{manager_version=$LegacyVersion;release_asset='Keelaryn_v4.16.3_Windows.zip';sha256=$LegacyBundleSha256}
    current_update_sha256=$updateSha
    rollback_snapshot_manifest_sha256=$snapshotManifestSha
    alpha_instance_id=$alphaId
    beta_instance_id=$betaId
    alpha_tree_sha256=$alphaDigest
    beta_tree_sha256=$betaDigest
    active_current_sha256=$finalShadow.Sha256
    phases=[ordered]@{
        legacy_genesis_pass=$true
        upgrade_to_current_pass=$true
        registry_and_beta_switch_pass=$true
        downgrade_legacy_doctor_pass=$true
        reupgrade_beta_recovery_pass=$true
        safe_adoption_pass=$true
        ambiguous_fail_closed_pass=$true
        final_doctor_pass=$true
    }
    doctor=[ordered]@{
        current_before=[ordered]@{exit_code=$doctorCurrentBefore.ExitCode;warnings=$doctorCurrentBefore.Warnings}
        legacy_4_16_3=[ordered]@{exit_code=$doctorLegacy.ExitCode;warnings=$doctorLegacy.Warnings}
        current_after_reupgrade=[ordered]@{exit_code=$doctorCurrentAfter.ExitCode;warnings=$doctorCurrentAfter.Warnings}
        final=[ordered]@{exit_code=$doctorFinal.ExitCode;warnings=$doctorFinal.Warnings}
    }
    hubs_byte_immutable=$true
    production_qualified=$false
    candidate_issued=$false
    production_hub_used=$false
    completed_utc=[DateTime]::UtcNow.ToString('o')
}
Write-Json $EvidencePath $evidence
Remove-Item -LiteralPath $work -Recurse -Force
Write-Host ''
Write-Host 'MULTI-HUB DOWNGRADE COMPATIBILITY: PASS' -ForegroundColor Green
Write-Host ('Evidence: '+$EvidencePath)
Write-Host 'Classification: development_only; production_qualified=false; candidate_issued=false'
