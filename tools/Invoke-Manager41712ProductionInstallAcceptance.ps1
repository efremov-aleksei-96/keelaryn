[CmdletBinding()]
param([string]$KeelarynRoot = 'D:\0\0__Core\keelaryn')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$expectedBaseline = '4.17.11'
$expectedVersion = '4.17.12'
$expectedGateRevision = 2
$expectedFrameworkRevision = 24
$expectedCandidateInstallationSha256 = 'f66f83aba661868c6ff5007e77f96b3be8be34536000c060cdd0017dcf553b5d'
$expectedCandidateManagedDigest = '5118a866aa54ed916bb087fe41a4ac724bf527181b79b1c34e9b29311bf10fb8'
$expectedBaselineInstallationSha256 = 'cd531baa24836a518afdf582e5313006cdc503fcc212b8b1bcffbb7c55ae2bfc'

$managerRoot = Join-Path $KeelarynRoot 'manager'
$hubRoot = Join-Path $KeelarynRoot 'hub'
$installation = Join-Path $managerRoot 'product\install\INSTALLATION.json'
$runtime = Join-Path $managerRoot 'product\runtime\Keelaryn__Manager.ps1'
$frontend = Join-Path $managerRoot 'product\tools\KeelarynMenu.ps1'
$registry = Join-Path $managerRoot 'state\instances.json'
$currentZip = Join-Path $managerRoot 'state\baseline\Keelaryn__Hub_CURRENT.zip'
$resultsRoot = Join-Path $KeelarynRoot 'tests\results\manager-4.17.12'
$summaryPath = Join-Path $resultsRoot 'GATE_SUMMARY.json'
$sourceGatePath = Join-Path $resultsRoot 'SOURCE_GATE_RESULT.json'
$artifactsRoot = Join-Path $resultsRoot 'artifacts'
$testedReleasePath = Join-Path $artifactsRoot 'TESTED_RELEASE.json'
$installerPs = Join-Path $artifactsRoot 'Install-TestedManagerUpdate.ps1'
$acceptancePath = Join-Path $resultsRoot 'PRODUCTION_ACCEPTANCE.json'

function Sha([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function TextSha([string]$Text) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    $h = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($h.ComputeHash($enc.GetBytes($Text))).Replace('-','').ToLowerInvariant() }
    finally { $h.Dispose() }
}
function Write-Json([string]$Path,$Value) {
    [IO.File]::WriteAllText($Path,(($Value|ConvertTo-Json -Depth 12).Replace("`r`n","`n")+"`n"),(New-Object Text.UTF8Encoding($false)))
}
function Fail([string]$Message) { throw ('Manager 4.17.12 production install acceptance: ' + $Message) }
function ManagedDigest([string]$Root) {
    $manifest = Get-Content -LiteralPath (Join-Path $Root 'product\install\INSTALLATION.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $rels = New-Object 'System.Collections.Generic.List[string]'
    foreach($raw in @($manifest.managed_files)) { [void]$rels.Add(([string]$raw).Replace('\','/')) }
    $rels.Sort([StringComparer]::Ordinal)
    $rows = New-Object System.Collections.ArrayList
    foreach($rel in $rels) {
        $p = Join-Path $Root $rel.Replace('/','\')
        if(-not(Test-Path -LiteralPath $p -PathType Leaf)){ Fail ('managed file missing: '+$rel) }
        [void]$rows.Add($rel+"`0"+(Sha $p))
    }
    return TextSha ([string]::Join("`n",@($rows)))
}
function PortableHubDigest([string]$Root) {
    $full = (Get-Item -LiteralPath $Root -Force).FullName.TrimEnd('\')
    $rows = New-Object System.Collections.ArrayList
    foreach($f in @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force | Sort-Object FullName)) {
        $rel = $f.FullName.Substring($full.Length).TrimStart('\').Replace('\','/')
        $low = $rel.ToLowerInvariant(); $leaf = [IO.Path]::GetFileName($low)
        if($low-eq'.git'-or$low.StartsWith('.git/')-or$low-eq'.obsidian'-or$low.StartsWith('.obsidian/')-or@('.ds_store','thumbs.db','desktop.ini')-contains$leaf){continue}
        [void]$rows.Add($rel+"`0"+(Sha $f.FullName))
    }
    return TextSha ([string]::Join("`n",@($rows)))
}
function Invoke-Checked([string]$Script,[string[]]$Arguments,[string]$Label) {
    $exe=Join-Path $PSHOME 'powershell.exe'
    $old=$ErrorActionPreference
    try { $ErrorActionPreference='Continue'; $out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1); $exit=[int]$LASTEXITCODE }
    finally { $ErrorActionPreference=$old }
    foreach($line in $out){ Write-Host ([string]$line) }
    if($exit-ne0){ Fail ($Label+' failed with exit='+$exit) }
    return @($out|ForEach-Object{[string]$_})
}

Write-Host '=== KEELARYN MANAGER 4.17.12 PRODUCTION INSTALL + ACCEPTANCE ===' -ForegroundColor Cyan
Write-Host 'Transaction: validate exact Full-Gate-tested release -> install 4.17.11 to 4.17.12 -> clean post-install acceptance.'

foreach($p in @($installation,$runtime,$frontend,$currentZip,$summaryPath,$sourceGatePath,$testedReleasePath,$installerPs)) {
    if(-not(Test-Path -LiteralPath $p -PathType Leaf)){ Fail ('required file missing: '+$p) }
}
if(Test-Path -LiteralPath $registry -PathType Leaf){ Fail ('multi-Hub registry must remain inactive: '+$registry) }

$summary=Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8|ConvertFrom-Json
$tested=Get-Content -LiteralPath $testedReleasePath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$summary.status-cne'passed'-or[string]$summary.manager_version-cne$expectedVersion-or[string]$summary.baseline_version-cne$expectedBaseline){ Fail 'Full Gate summary identity/status mismatch.' }
if([int]$summary.gate_revision-ne$expectedGateRevision-or[int]$summary.framework_revision-ne$expectedFrameworkRevision){ Fail 'Full Gate gate/framework revision mismatch.' }
if([string]$summary.candidate_installation_sha256-cne$expectedCandidateInstallationSha256-or[string]$summary.candidate_managed_content_sha256-cne$expectedCandidateManagedDigest){ Fail 'Full Gate candidate identity mismatch.' }
foreach($phase in $summary.phases.PSObject.Properties){ if(-not[bool]$phase.Value){ Fail ('Full Gate phase is not PASS: '+$phase.Name) } }
if([string]$tested.schema-cne'keelaryn.manager-tested-release.v1'-or[string]$tested.status-cne'full_gate_passed'){ Fail 'TESTED_RELEASE is not PASS.' }
if([string]$tested.manager_version-cne$expectedVersion-or[string]$tested.baseline_version-cne$expectedBaseline-or[int]$tested.gate_revision-ne$expectedGateRevision-or[int]$tested.framework_revision-ne$expectedFrameworkRevision){ Fail 'TESTED_RELEASE identity mismatch.' }
if((Sha $sourceGatePath)-cne([string]$tested.source_gate_result_sha256).ToLowerInvariant()){ Fail 'TESTED_RELEASE SourceGate binding mismatch.' }
$testedUpdate=Join-Path $artifactsRoot ([string]$tested.update.file)
if(-not(Test-Path -LiteralPath $testedUpdate -PathType Leaf)){ Fail ('tested UPDATE missing: '+$testedUpdate) }
$testedUpdateSha=Sha $testedUpdate
if($testedUpdateSha-cne([string]$tested.update.sha256).ToLowerInvariant()){ Fail 'tested UPDATE hash mismatch.' }
if([int64](Get-Item -LiteralPath $testedUpdate -Force).Length-ne[int64]$tested.update.bytes){ Fail 'tested UPDATE size mismatch.' }
Write-Host ('Exact tested UPDATE: '+$testedUpdateSha+'; bytes='+[int64]$tested.update.bytes) -ForegroundColor Green

$currentManifest=Get-Content -LiteralPath $installation -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$currentManifest.manager_version-cne$expectedBaseline){ Fail ('production baseline must be '+$expectedBaseline+'; observed '+[string]$currentManifest.manager_version) }
$baselineInstallSha=Sha $installation
if($baselineInstallSha-cne$expectedBaselineInstallationSha256){ Fail ('production baseline INSTALLATION identity mismatch: '+$baselineInstallSha) }
$hubBefore=PortableHubDigest $hubRoot
$currentBefore=Sha $currentZip
Write-Host ('Pre-commit production Hub portable digest: '+$hubBefore)
Write-Host ('Pre-commit CURRENT SHA-256: '+$currentBefore)

$receipt=[ordered]@{
    schema='keelaryn.manager-production-acceptance.v1'; manager_version=$expectedVersion; baseline_version=$expectedBaseline
    gate_revision=$expectedGateRevision; framework_revision=$expectedFrameworkRevision; tested_update_sha256=$testedUpdateSha
    started_utc=[DateTime]::UtcNow.ToString('o'); completed_utc=$null; status='running'; durable_install_committed=$false
    pre=[ordered]@{installation_sha256=$baselineInstallSha;hub_portable_digest=$hubBefore;current_sha256=$currentBefore;multi_hub_registry_active=$false}
    post=$null; failure=$null
}
Write-Json $acceptancePath $receipt

try {
    Write-Host ''
    Write-Host '=== TESTED INSTALLER VALIDATE-ONLY ===' -ForegroundColor Cyan
    [void](Invoke-Checked $installerPs @('-ValidateOnly') 'tested installer ValidateOnly')

    Write-Host ''
    Write-Host '=== PRODUCTION COMMIT 4.17.11 -> 4.17.12 ===' -ForegroundColor Cyan
    [void](Invoke-Checked $installerPs @() 'tested production installer')

    $afterCommit=Get-Content -LiteralPath $installation -Raw -Encoding UTF8|ConvertFrom-Json
    if([string]$afterCommit.manager_version-cne$expectedVersion){ Fail ('installer returned success but installed version is '+[string]$afterCommit.manager_version) }
    $receipt.durable_install_committed=$true
    Write-Json $acceptancePath $receipt
    Write-Host 'DURABLE PRODUCTION COMMIT: Manager 4.17.12 installed.' -ForegroundColor Green

    if((Sha $installation)-cne$expectedCandidateInstallationSha256){ Fail ('installed INSTALLATION SHA mismatch: '+(Sha $installation)) }
    $managed=ManagedDigest $managerRoot
    if($managed-cne$expectedCandidateManagedDigest){ Fail ('installed managed digest mismatch: '+$managed) }
    if(Test-Path -LiteralPath $registry -PathType Leaf){ Fail 'multi-Hub registry became active during Manager installation.' }

    Write-Host ''
    Write-Host '=== PRODUCTION SELFTEST / FRONTEND / UI ===' -ForegroundColor Cyan
    [void](Invoke-Checked $runtime @('-SelfTest') 'Manager SelfTest')
    [void](Invoke-Checked $frontend @('-SelfTest','-NoRootLauncher') 'Frontend SelfTest')
    $render=Invoke-Checked $frontend @('-Action','RenderMain','-NoRootLauncher') 'RenderMain'
    $renderText=[string]::Join("`n",$render)
    foreach($needle in @('Keelaryn','Everyday','[2] Doctor','[5] Installation info')){ if(-not$renderText.Contains($needle)){ Fail ('RenderMain missing contract line: '+$needle) } }
    [void](Invoke-Checked $frontend @('-Action','InstanceInfo','-NoRootLauncher') 'Installation info')

    Write-Host ''
    Write-Host '=== PRODUCTION DOCTOR ===' -ForegroundColor Cyan
    $doctor=Invoke-Checked $runtime @('-Doctor') 'Doctor'
    $doctorText=[string]::Join("`n",$doctor)
    if($doctorText-match'(?m)^\s*\[(WARN|ERROR)\]'){ Fail 'production Doctor produced WARN or ERROR.' }
    foreach($needle in @('[OK] manager.version: Manager version markers agree at 4.17.12.','[OK] instances.registry: Single-instance compatibility mode; multi-Hub registry is not initialized.','[OK] baseline.current: Installed vault portable content exactly matches CURRENT;')){ if(-not$doctorText.Contains($needle)){ Fail ('Doctor missing acceptance line: '+$needle) } }

    $hubAfter=PortableHubDigest $hubRoot
    $currentAfter=Sha $currentZip
    if($hubAfter-cne$hubBefore){ Fail ('production Hub portable content changed; before='+$hubBefore+' after='+$hubAfter) }
    if($currentAfter-cne$currentBefore){ Fail ('production CURRENT changed; before='+$currentBefore+' after='+$currentAfter) }
    if(Test-Path -LiteralPath $registry -PathType Leaf){ Fail 'multi-Hub registry is active after acceptance.' }

    $receipt.status='passed';$receipt.completed_utc=[DateTime]::UtcNow.ToString('o')
    $receipt.post=[ordered]@{installation_sha256=(Sha $installation);managed_digest=$managed;hub_portable_digest=$hubAfter;current_sha256=$currentAfter;doctor_clean=$true;selftest=$true;frontend_selftest=$true;render_main=$true;multi_hub_registry_active=$false}
    Write-Json $acceptancePath $receipt
    Write-Host ''
    Write-Host 'MANAGER 4.17.12 PRODUCTION INSTALL + ACCEPTANCE: PASS' -ForegroundColor Green
    Write-Host ('TESTED_UPDATE_SHA256='+$testedUpdateSha) -ForegroundColor Green
    Write-Host ('PRODUCTION_ACCEPTANCE='+$acceptancePath)
    Write-Host 'Multi-Hub registry remains intentionally inactive. Public release/main merge still requires final publication review.'
}
catch {
    $installedVersion='<unreadable>'
    try { $installedVersion=[string]((Get-Content -LiteralPath $installation -Raw -Encoding UTF8|ConvertFrom-Json).manager_version) } catch {}
    if($installedVersion-ceq$expectedVersion){ $receipt.durable_install_committed=$true; $receipt.status='post_commit_failed' }
    else { $receipt.status='pre_commit_or_install_failed' }
    $receipt.completed_utc=[DateTime]::UtcNow.ToString('o');$receipt.failure=[string]$_.Exception.Message
    try { Write-Json $acceptancePath $receipt } catch {}
    if($receipt.durable_install_committed){
        throw ('Manager 4.17.12 durable production commit succeeded, but post-install acceptance failed. No automatic rollback was attempted. Failure: '+[string]$_.Exception.Message)
    }
    throw
}
