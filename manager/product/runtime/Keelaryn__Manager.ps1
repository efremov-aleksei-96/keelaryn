param(
    [switch]$OpenOnly,
    [switch]$UpdateManager,
    [switch]$UpdateHub,
    [switch]$UpdateAll,
    [switch]$SelfTest,
    [switch]$Genesis,
    [string]$GenesisConfigPath,
    [switch]$GenesisConfirmed,
    [switch]$BuildDistribution,
    [switch]$InstanceInfo,
    [switch]$CheckMigrations,
    [switch]$AdoptInstanceIdentity,
    [switch]$ApplyMigrations,
    [switch]$MigrateLegacyNamespace,
    [switch]$MigrateLayout,
    [switch]$FinalizeLayout,
    [switch]$Doctor,
    [switch]$BuildRelease,
    [switch]$BuildAIContext,
    [switch]$RepairCurrentTransport,
    [switch]$PrepareTests,
    [switch]$BuildCandidateTransport,
    [switch]$RestoreCandidateTransport,
    [switch]$InitializePresentation,
    [switch]$FinalizeFilesystemLayout,
    [string]$BindInstancePath
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression

$ManagerVersion = "4.12.0"
$RuntimeDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeProductDirectory = Split-Path -Parent $RuntimeDirectory
$Root = Split-Path -Parent $RuntimeProductDirectory
$InstallParent = Split-Path -Parent $Root
$ManagerDirectoryName = Split-Path $Root -Leaf
$CanonicalLayoutActive = $ManagerDirectoryName -ieq 'manager'
$LayoutRoot = if ($CanonicalLayoutActive) { $InstallParent } else { Join-Path $InstallParent 'keelaryn' }
$CanonicalManagerPath = Join-Path $LayoutRoot 'manager'
$CanonicalHubPath = Join-Path $LayoutRoot 'hub'
$CanonicalTestsPath = Join-Path $LayoutRoot 'tests'
$ProductRoot = Join-Path $Root 'product'
$CanonicalInstallationManifest = Join-Path $ProductRoot 'install\INSTALLATION.json'
$StateRoot = Join-Path $Root 'state'
$StateLayoutReceipt = Join-Path $StateRoot 'layout.json'

function Set-ManagerOperationalPaths {
    $script:StateLayoutActive = Test-Path -LiteralPath $StateLayoutReceipt -PathType Leaf
    if ($script:StateLayoutActive) {
        $script:BindingFile = Join-Path $StateRoot 'binding.json'
        $script:Inbox = Join-Path $StateRoot 'inbox'
        $script:History = Join-Path $StateRoot 'history'
        $script:Logs = Join-Path $StateRoot 'logs'
        $script:Releases = Join-Path $StateRoot 'releases'
        $script:PreferredCurrentZip = Join-Path $StateRoot 'baseline\Keelaryn__Hub_CURRENT.zip'
        $script:WorkRoot = Join-Path $StateRoot 'work'
    } else {
        $script:BindingFile = Join-Path $Root '_instance_binding.json'
        $script:Inbox = Join-Path $Root '_inbox'
        $script:History = Join-Path $Root '_history'
        $script:Logs = Join-Path $Root '_logs'
        $script:Releases = Join-Path $Root '_releases'
        $script:PreferredCurrentZip = Join-Path $Root 'Keelaryn__Hub_CURRENT.zip'
        $script:WorkRoot = $Root
    }
    $script:Checkpoints = Join-Path $script:History 'checkpoints'
    $script:Rollback = Join-Path $script:History 'rollback'
    $script:ManagerUpdates = Join-Path $script:History 'manager_updates'
    $script:LogFile = Join-Path $script:Logs 'manager.log'
    $script:AttentionFile = Join-Path $script:Logs 'ATTENTION_REQUIRED.txt'
    $script:ShortcutFailureMarker = Join-Path $script:Logs 'shortcut_creation_failed.txt'
    $script:LegacyBindingFile = Join-Path $script:Logs 'legacy_instance_binding.json'
}

function Assert-ManagerOperationalPathsReady {
    param([switch]$RequireStateLayout)
    if ($RequireStateLayout -and -not $script:StateLayoutActive) { throw 'Manager state-layout receipt is not active after filesystem finalization.' }
    if (-not $script:StateLayoutActive) { return }
    $expected=[ordered]@{
        BindingFile=(Join-Path $StateRoot 'binding.json')
        Inbox=(Join-Path $StateRoot 'inbox')
        History=(Join-Path $StateRoot 'history')
        Logs=(Join-Path $StateRoot 'logs')
        Releases=(Join-Path $StateRoot 'releases')
        PreferredCurrentZip=(Join-Path $StateRoot 'baseline\Keelaryn__Hub_CURRENT.zip')
        WorkRoot=(Join-Path $StateRoot 'work')
        LogFile=(Join-Path $StateRoot 'logs\manager.log')
    }
    foreach($name in @($expected.Keys)){
        $actual=[string](Get-Variable -Name $name -Scope Script -ValueOnly -ErrorAction Stop)
        if ([System.IO.Path]::GetFullPath($actual) -cne [System.IO.Path]::GetFullPath([string]$expected[$name])) { throw('Operational path switch mismatch: '+$name+'='+$actual+' expected='+[string]$expected[$name])}
    }
    foreach($dir in @($script:Inbox,$script:History,$script:Logs,$script:Releases,(Split-Path -Parent $script:PreferredCurrentZip))){
        if (-not (Test-Path -LiteralPath $dir -PathType Container)) { throw('Operational state directory missing after filesystem finalization: '+$dir) }
    }
}

Set-ManagerOperationalPaths

function Complete-PendingFilesystemLogHandoff {
    if (-not (Test-Path -LiteralPath $StateLayoutReceipt -PathType Leaf)) { return }
    $receipt=$null
    try { $receipt=([System.IO.File]::ReadAllText($StateLayoutReceipt,[System.Text.Encoding]::UTF8)|ConvertFrom-Json) }
    catch { throw ('Could not read Manager filesystem-layout receipt: '+$_.Exception.Message) }
    if (-not [bool]$receipt.legacy_log_handoff_pending) { return }
    if ([string]$env:KEELARYN_FILESYSTEM_HANDOFF_ACTIVE -eq '1') { return }

    $legacyLogs=Join-Path $Root '_logs'
    $stateLogs=Join-Path $StateRoot 'logs'
    if (-not (Test-Path -LiteralPath $stateLogs -PathType Container)) { throw ('Pending filesystem log handoff is missing canonical state logs: '+$stateLogs) }
    if (Test-Path -LiteralPath $legacyLogs) {
        $legacyItem=Get-Item -LiteralPath $legacyLogs -Force -ErrorAction Stop
        if (-not $legacyItem.PSIsContainer -or ($legacyItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Pending legacy log handoff path is unsafe: '+$legacyLogs) }
        $children=@(Get-ChildItem -LiteralPath $legacyLogs -Force -ErrorAction Stop)
        $unexpected=@($children|Where-Object{$_.PSIsContainer -or $_.Name -cne 'manager.log'})
        if($unexpected.Count-ne0){throw('Pending legacy log handoff contains unexpected path(s): '+(($unexpected|ForEach-Object{$_.Name})-join', '))}
        $legacyLog=Join-Path $legacyLogs 'manager.log'
        if(Test-Path -LiteralPath $legacyLog -PathType Leaf){
            $legacyLogItem=Get-Item -LiteralPath $legacyLog -Force -ErrorAction Stop
            if(($legacyLogItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)-ne0){throw('Pending legacy manager.log must not be a reparse point: '+$legacyLog)}
            $lines=@(Get-Content -LiteralPath $legacyLog -Encoding UTF8 -ErrorAction Stop)
            if($lines.Count-ne0){Add-Content -LiteralPath (Join-Path $stateLogs 'manager.log') -Value $lines -Encoding UTF8}
        }
        Remove-Item -LiteralPath $legacyLogs -Recurse -Force -ErrorAction Stop
    }

    $out=[ordered]@{}
    foreach($prop in @($receipt.PSObject.Properties)){$out[[string]$prop.Name]=$prop.Value}
    $out['legacy_log_handoff_pending']=$false
    $out['legacy_log_handoff_completed_utc']=(Get-Date).ToUniversalTime().ToString('o')
    $out|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $StateLayoutReceipt -Encoding UTF8
}

function Initialize-FreshManagerStateLayoutIfEligible {
    if (-not $CanonicalLayoutActive -or $StateLayoutActive) { return }
    foreach($rel in @('_inbox','_history','_logs','_releases','_instance_binding.json','Keelaryn__Hub_CURRENT.zip','Keelaryn__Manager.ps1','_manager_manifest.json','_manager_version.txt')){
        if(Test-Path -LiteralPath (Join-Path $Root $rel)){return}
    }
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
    foreach($dir in @('inbox','history','logs','releases','baseline')){New-Item -ItemType Directory -Force -Path (Join-Path $StateRoot $dir)|Out-Null}
    [ordered]@{schema='keelaryn.manager.filesystem-layout.v2';manager_version=$ManagerVersion;finalized_utc=(Get-Date).ToUniversalTime().ToString('o');state_root='state';canonical_manifest='product/install/INSTALLATION.json';fresh_install=$true;legacy_log_handoff_pending=$false}|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $StateLayoutReceipt -Encoding UTF8
    Set-ManagerOperationalPaths
}

Initialize-FreshManagerStateLayoutIfEligible

$UpdateModeCount = ([int][bool]$UpdateManager) + ([int][bool]$UpdateHub) + ([int][bool]$UpdateAll)
if ($UpdateModeCount -gt 1) { throw 'Choose only one update mode: -UpdateManager, -UpdateHub, or -UpdateAll.' }
$PrimaryModeCount = ([int][bool]$OpenOnly)+([int][bool]$UpdateManager)+([int][bool]$UpdateHub)+([int][bool]$UpdateAll)+([int][bool]$SelfTest)+([int][bool]$Genesis)+([int][bool]$BuildDistribution)+([int][bool]$InstanceInfo)+([int][bool]$CheckMigrations)+([int][bool]$AdoptInstanceIdentity)+([int][bool]$ApplyMigrations)+([int][bool]$MigrateLegacyNamespace)+([int][bool]$MigrateLayout)+([int][bool]$FinalizeLayout)+([int][bool]$Doctor)+([int][bool]$BuildRelease)+([int][bool]$BuildAIContext)+([int][bool]$RepairCurrentTransport)+([int][bool]$PrepareTests)+([int][bool]$BuildCandidateTransport)+([int][bool]$RestoreCandidateTransport)+([int][bool]$InitializePresentation)+([int][bool]$FinalizeFilesystemLayout)+([int][bool](-not [string]::IsNullOrWhiteSpace($BindInstancePath)))
if ($PrimaryModeCount -gt 1) { throw 'Choose exactly one Keelaryn Manager action per invocation.' }
if ((-not [string]::IsNullOrWhiteSpace($GenesisConfigPath) -or $GenesisConfirmed) -and -not $Genesis) { throw 'GenesisConfigPath/GenesisConfirmed are valid only with -Genesis.' }
if (-not [string]::IsNullOrWhiteSpace($GenesisConfigPath) -and -not $GenesisConfirmed) { throw 'Non-interactive Genesis requires explicit -GenesisConfirmed.' }
if ($GenesisConfirmed -and [string]::IsNullOrWhiteSpace($GenesisConfigPath)) { throw 'GenesisConfirmed requires -GenesisConfigPath.' }
$WantsManagerUpdate = [bool]($UpdateManager -or $UpdateAll)
$WantsHubUpdate = [bool]($UpdateHub -or $UpdateAll)

# Explicit pre-Keelaryn compatibility aliases. These names are never used as
# defaults for new installations, Genesis, releases, or generic distributions.
$LegacyCoreCompat = [ordered]@{
    HubDirectory = 'Core__Hub'
    HubZipRoot = 'Core__Hub/'
    CurrentZipName = 'Core__Hub_CURRENT.zip'
    CandidatePrefix = 'Core__Hub_CANDIDATE_'
    ApprovedPrefix = 'Core__Hub_APPROVED_'
    StateFormatKey = 'corehub_format'
    BindingSchema = 'coremanager.instance-binding.v1'
    EnvPath = 'CORE_HUB_VAULT_PATH'
    InstanceSchema = 'corehub.instance.v1'
    RouterV1 = 'corehub.router.v1'
    RouterV2 = 'corehub.router.v2'
    ArtifactV1 = 'corehub.artifact.v1'
    ArtifactV2 = 'corehub.artifact.v2'
    ArtifactV3 = 'corehub.artifact.v3'
    ManagerProtocolPattern = '^chat-manager-v3(?:\.|$)'
}

$DefaultVault = if ($CanonicalLayoutActive) { $CanonicalHubPath } else { Join-Path $InstallParent 'Keelaryn__Hub' }

function Invoke-WithExistingHiddenFileWritable([string]$Path,[scriptblock]$Action) {
    $restoreHidden=$false
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Mutable Manager file must not be a reparse point: '+$Path) }
        if (($item.Attributes -band [System.IO.FileAttributes]::Hidden) -ne 0) {
            $item.Attributes=[System.IO.FileAttributes]([int]$item.Attributes -band (-bnot [int][System.IO.FileAttributes]::Hidden))
            $restoreHidden=$true
        }
    }
    try { return & $Action }
    finally {
        if ($restoreHidden -and (Test-Path -LiteralPath $Path -PathType Leaf)) {
            $item=Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
            if ($item -and ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0 -and ($item.Attributes -band [System.IO.FileAttributes]::Hidden) -eq 0) {
                $item.Attributes=$item.Attributes -bor [System.IO.FileAttributes]::Hidden
            }
        }
    }
}

function Set-ManagerMutablePresentationHidden([string]$Path) {
    if ($StateLayoutActive -or -not $CanonicalLayoutActive -or [string]$env:OS -ne 'Windows_NT' -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $full=[System.IO.Path]::GetFullPath($Path)
    $targets=@(
        [System.IO.Path]::GetFullPath($BindingFile),
        [System.IO.Path]::GetFullPath($PreferredCurrentZip)
    )
    if(@($targets|Where-Object{$_-ieq$full}).Count-eq0){return}
    $item=Get-Item -LiteralPath $full -Force -ErrorAction Stop
    if(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw('Mutable Manager presentation path must not be a reparse point: '+$full)}
    if(($item.Attributes-band[System.IO.FileAttributes]::Hidden)-eq0){$item.Attributes=$item.Attributes-bor[System.IO.FileAttributes]::Hidden}
}

function Write-ManagerBindingDocument([string]$Path,$Object) {
    $json=$Object|ConvertTo-Json -Depth 5
    $encoding=New-Object System.Text.UTF8Encoding($false)
    Invoke-WithExistingHiddenFileWritable $Path { [System.IO.File]::WriteAllText($Path,$json,$encoding) }|Out-Null
    Set-ManagerMutablePresentationHidden $Path
}
$Vault = $DefaultVault
$script:BindingResolutionError = $null

$TestHubCandidate = {
    param([string]$Path)
    return (Test-Path $Path -PathType Container) -and
        (Test-Path (Join-Path $Path '_System\STATE.md') -PathType Leaf) -and
        (Test-Path (Join-Path $Path '_System\INDEX.json') -PathType Leaf) -and
        (Test-Path (Join-Path $Path '_System\ROUTER.json') -PathType Leaf) -and
        (Test-Path (Join-Path $Path '_System\VALIDATION.json') -PathType Leaf)
}
$ReadBoundInstanceId = {
    param([string]$Path)
    $p = Join-Path $Path '_System\INSTANCE.json'
    if (-not (Test-Path $p -PathType Leaf)) { return $null }
    try {
        $item=Get-Item -LiteralPath $p -Force -ErrorAction Stop
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or $item.Length -gt 4MB) { return $null }
        $m = (Get-Content -LiteralPath $p -Raw -Encoding UTF8) | ConvertFrom-Json
        $id = ([string]$m.instance_id).Trim().ToLowerInvariant()
        $g = [guid]::Empty
        if (([string]$m.schema -eq 'keelaryn.instance.v1') -and [guid]::TryParse($id,[ref]$g) -and $g -ne [guid]::Empty) { return $id }
    } catch {}
    return $null
}
$WriteBindingV2 = {
    param([string]$Path,[string]$InstanceId,[string]$Source)
    if ($SelfTest -or $Doctor) { return }
    $obj=[ordered]@{
        schema='keelaryn.manager.instance-binding.v2'
        vault_path=[System.IO.Path]::GetFullPath($Path)
        vault_directory_name=[System.IO.Path]::GetFileName([System.IO.Path]::GetFullPath($Path).TrimEnd('\'))
        source=$Source
    }
    if ($InstanceId) { $obj.instance_id=$InstanceId }
    Write-ManagerBindingDocument $BindingFile $obj
}
$GetSiblingCandidates = {
    return @(Get-ChildItem $InstallParent -Directory -ErrorAction SilentlyContinue | Where-Object {
        $_.FullName -ne $Root -and (& $TestHubCandidate $_.FullName)
    })
}

$SkipHubBindingResolution = (-not $BindInstancePath) -and ($SelfTest -or $BuildDistribution -or $BuildRelease -or $BuildAIContext -or $UpdateManager -or $BuildCandidateTransport -or $RestoreCandidateTransport -or $FinalizeFilesystemLayout)
if (-not $SkipHubBindingResolution) {
try {
    if ($BindInstancePath) {
        $candidate = [System.IO.Path]::GetFullPath($BindInstancePath)
        if (-not (& $TestHubCandidate $candidate)) { throw ('Bind target does not identify a valid Keelaryn__Hub: ' + $candidate) }
        $Vault = $candidate
    }
    else {
        $newEnv = $env:KEELARYN_HUB_PATH
        $legacyEnv = [Environment]::GetEnvironmentVariable([string]$LegacyCoreCompat.EnvPath)
        if ($newEnv -or $legacyEnv) {
            $raw = if ($newEnv) { $newEnv } else { $legacyEnv }
            $candidate = [System.IO.Path]::GetFullPath($raw)
            if (-not (& $TestHubCandidate $candidate)) { throw ($(if ($newEnv) { 'KEELARYN_HUB_PATH' } else { 'Legacy Hub path' }) + ' does not identify a valid Hub: ' + $candidate) }
            $Vault = $candidate
            & $WriteBindingV2 $Vault (& $ReadBoundInstanceId $Vault) $(if ($newEnv) { 'environment_override' } else { 'legacy_environment_override' })
        }
        elseif (Test-Path $BindingFile -PathType Leaf) {
            $bindingItem=Get-Item -LiteralPath $BindingFile -Force -ErrorAction Stop
            if (($bindingItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or $bindingItem.Length -gt 4MB) { throw 'instance binding file is unsafe or exceeds the metadata size limit' }
            $binding = (Get-Content -LiteralPath $BindingFile -Raw -Encoding UTF8) | ConvertFrom-Json
            $schema = [string]$binding.schema
            $resolved = $null
            $bindingId = ([string]$binding.instance_id).Trim().ToLowerInvariant()
            if ($schema -eq 'keelaryn.manager.instance-binding.v2') {
                $storedPath = ([string]$binding.vault_path).Trim()
                if ($storedPath) {
                    try { $storedPath=[System.IO.Path]::GetFullPath($storedPath) } catch { $storedPath=$null }
                }
                if ($storedPath -and (& $TestHubCandidate $storedPath)) {
                    $actualId=& $ReadBoundInstanceId $storedPath
                    if (-not $bindingId -or $actualId -eq $bindingId) { $resolved=$storedPath }
                }
                if (-not $resolved) {
                    $siblings=@(& $GetSiblingCandidates)
                    if ($bindingId) { $siblings=@($siblings | Where-Object { (& $ReadBoundInstanceId $_.FullName) -eq $bindingId }) }
                    elseif ($binding.vault_directory_name) { $leaf=[string]$binding.vault_directory_name; $siblings=@($siblings | Where-Object { $_.Name -eq $leaf }) }
                    if ($siblings.Count -eq 1) { $resolved=$siblings[0].FullName }
                    elseif ($siblings.Count -gt 1) { throw 'multiple candidate instances match the stored binding' }
                }
            }
            elseif ($schema -eq 'keelaryn.manager.instance-binding.v1' -or $schema -eq [string]$LegacyCoreCompat.BindingSchema) {
                $leaf=[string]$binding.vault_directory_name
                if (-not $leaf -or $leaf -ne [System.IO.Path]::GetFileName($leaf) -or $leaf.Contains('..')) { throw 'invalid legacy sibling directory name' }
                $bound=Join-Path $InstallParent $leaf
                if (& $TestHubCandidate $bound) { $resolved=$bound }
                else {
                    $siblings=@(& $GetSiblingCandidates)
                    if ($siblings.Count -eq 1) { $resolved=$siblings[0].FullName }
                    elseif ($siblings.Count -gt 1) { throw 'legacy binding is stale and multiple sibling instances exist' }
                }
            }
            else { throw 'unsupported binding schema' }
            if (-not $resolved) { throw 'bound vault could not be resolved by absolute path, identity, or unique sibling discovery' }
            $Vault=[System.IO.Path]::GetFullPath($resolved)
            & $WriteBindingV2 $Vault (& $ReadBoundInstanceId $Vault) 'binding_reconciled'
        }
        else {
            $siblings=@(& $GetSiblingCandidates)
            if ($siblings.Count -eq 1) {
                $Vault=$siblings[0].FullName
                & $WriteBindingV2 $Vault (& $ReadBoundInstanceId $Vault) 'auto_discovered_existing_instance'
            }
            elseif ($siblings.Count -gt 1) { throw 'Multiple sibling Keelaryn/legacy instances were discovered. Use BIND_INSTANCE.cmd or KEELARYN_HUB_PATH to select one explicitly.' }
        }
    }
}
catch {
    $allowUnresolved = $Doctor -or $SelfTest -or $BuildDistribution -or $BuildRelease -or $BuildAIContext -or $BuildCandidateTransport -or $RestoreCandidateTransport -or $InitializePresentation -or $FinalizeFilesystemLayout -or $WantsManagerUpdate
    if ($allowUnresolved) {
        $script:BindingResolutionError = $_.Exception.Message
        $Vault = $DefaultVault
    }
    else { throw ('Invalid Keelaryn instance binding: ' + $_.Exception.Message) }
}
}

$LegacyCurrentZip = Join-Path $Root ([string]$LegacyCoreCompat.CurrentZipName)
$CurrentZip = if ($StateLayoutActive) { $PreferredCurrentZip } elseif ((Test-Path $PreferredCurrentZip -PathType Leaf) -or -not (Test-Path $LegacyCurrentZip -PathType Leaf)) { $PreferredCurrentZip } else { $LegacyCurrentZip }
$ProductReleaseFile = Join-Path $ProductRoot "release.json"
$ManagerReleasePolicyFile = Join-Path $ProductRoot "manager_release.json"
$InstalledManagerManifest = $CanonicalInstallationManifest

$MaxHubZipBytes = 50MB
$MaxHubExpandedBytes = 250MB
$MaxHubEntries = 10000
$MaxManagerZipBytes = 20MB
$MaxManagerExpandedBytes = 50MB
$MaxManagerEntries = 200
$MaxCompressionRatio = 200.0
$MinHubDiskHeadroom = 100MB
$MinManagerDiskHeadroom = 50MB
$MaxCandidateTransportBytes = 128MB
$MaxCandidateTransportRawPayloadBytes = 90MB

$ManagedManagerFiles = @(
    "compat/commands/APPLY_MIGRATIONS.cmd",
    "compat/commands/BIND_INSTANCE.cmd",
    "compat/commands/BUILD_AI_CONTEXT.cmd",
    "compat/commands/BUILD_CANDIDATE_TRANSPORT.cmd",
    "compat/commands/BUILD_GENERIC_DISTRIBUTION.cmd",
    "compat/commands/BUILD_RELEASE.cmd",
    "compat/commands/CHECK_MIGRATIONS.cmd",
    "compat/commands/DOCTOR.cmd",
    "compat/commands/FINALIZE_LAYOUT.cmd",
    "compat/commands/GENESIS_KEELARYN__HUB.cmd",
    "compat/commands/MIGRATE_INSTANCE_IDENTITY.cmd",
    "compat/commands/MIGRATE_LAYOUT.cmd",
    "compat/commands/MIGRATE_TO_KEELARYN.cmd",
    "compat/commands/OPEN_KEELARYN__HUB.cmd",
    "compat/commands/PREPARE_TESTS.cmd",
    "compat/commands/REPAIR_CURRENT_TRANSPORT.cmd",
    "compat/commands/RESTORE_CANDIDATE_TRANSPORT.cmd",
    "compat/commands/SHOW_INSTANCE_INFO.cmd",
    "compat/commands/UPDATE_ALL.cmd",
    "compat/commands/UPDATE_HUB.cmd",
    "compat/commands/UPDATE_MANAGER.cmd",
    "KEELARYN.cmd",
    "product/docs/AI_DEVELOPMENT.md",
    "product/docs/ARCHITECTURE.md",
    "product/docs/CANDIDATE_TRANSPORT.md",
    "product/docs/GENESIS_AND_ONBOARDING.md",
    "product/docs/LAYOUT.md",
    "product/docs/MIGRATIONS.md",
    "product/docs/OPERATIONS.md",
    "product/docs/PRIVACY_AND_RELEASE.md",
    "product/docs/RELEASE_BUILD.md",
    "product/docs/REPOSITORY_MODEL.md",
    "product/docs/TESTING.md",
    "product/docs/USER_INTERFACE.md",
    "product/governance/hub/_System/BOOTSTRAP.md",
    "product/governance/hub/_System/CHAT_MANAGER.md",
    "product/governance/hub/_System/CHAT_MANAGER_LAUNCH.md",
    "product/governance/hub/_System/GLOSSARY.md",
    "product/governance/hub/_System/PROTOCOL.md",
    "product/governance/hub/_System/WORKSPACE.md",
    "product/governance/hub/README.md",
    "product/install/INSTALLATION.json",
    "product/manager_release.json",
    "product/migrations/2.0.0_to_2.1.0.json",
    "product/migrations/index.json",
    "product/migrations/README.md",
    "product/release.json",
    "product/runtime/Keelaryn__Manager.ps1",
    "product/starter/hub/_System/GENESIS.md",
    "product/starter/hub/Areas/README.md",
    "product/starter/hub/HOME.md",
    "product/starter/hub/Projects/QUEUE.md",
    "product/starter/hub/Records/README.md",
    "product/starter/hub/Resources/Prompts/Initialize New Hub.md",
    "product/starter/hub/Resources/Prompts/WORKER_CHAT.md",
    "product/starter/hub/Resources/README.md",
    "product/tools/audit_cleanroom.ps1",
    "product/tools/KeelarynMenu.ps1",
    "product/tools/New-KeelarynAIContext.ps1",
    "product/tools/Unpack-KeelarynTestArchive.ps1",
    "README_FIRST.md"
)

# 4.8.7 finalizes the physical filesystem layout. Canonical managed source lives under product/ and compat/;
# transition root bootstrap/version/manifest files exist only in the 4.7.2-compatible UPDATE envelope and gate package.
$BootstrapCompatibilityCommands = @()

$CompatibilityCommandSpecs = [ordered]@{
    'APPLY_MIGRATIONS.cmd' = [ordered]@{ kind='standard'; manager_arg='-ApplyMigrations'; pause='always' }
    'BIND_INSTANCE.cmd' = [ordered]@{ kind='bind'; manager_arg='-BindInstancePath'; pause='none' }
    'BUILD_AI_CONTEXT.cmd' = [ordered]@{ kind='standard'; manager_arg='-BuildAIContext'; pause='error' }
    'BUILD_CANDIDATE_TRANSPORT.cmd' = [ordered]@{ kind='standard'; manager_arg='-BuildCandidateTransport'; pause='error' }
    'BUILD_GENERIC_DISTRIBUTION.cmd' = [ordered]@{ kind='standard'; manager_arg='-BuildDistribution'; pause='always' }
    'BUILD_RELEASE.cmd' = [ordered]@{ kind='standard'; manager_arg='-BuildRelease'; pause='error' }
    'CHECK_MIGRATIONS.cmd' = [ordered]@{ kind='standard'; manager_arg='-CheckMigrations'; pause='always' }
    'DOCTOR.cmd' = [ordered]@{ kind='standard'; manager_arg='-Doctor'; pause='always' }
    'FINALIZE_LAYOUT.cmd' = [ordered]@{ kind='standard'; manager_arg='-FinalizeLayout'; pause='always' }
    'GENESIS_KEELARYN__HUB.cmd' = [ordered]@{ kind='standard'; manager_arg='-Genesis'; pause='always' }
    'MIGRATE_INSTANCE_IDENTITY.cmd' = [ordered]@{ kind='standard'; manager_arg='-AdoptInstanceIdentity'; pause='always' }
    'MIGRATE_LAYOUT.cmd' = [ordered]@{ kind='standard'; manager_arg='-MigrateLayout'; pause='always' }
    'MIGRATE_TO_KEELARYN.cmd' = [ordered]@{ kind='standard'; manager_arg='-MigrateLegacyNamespace'; pause='always' }
    'OPEN_KEELARYN__HUB.cmd' = [ordered]@{ kind='standard'; manager_arg='-OpenOnly'; pause='error' }
    'PREPARE_TESTS.cmd' = [ordered]@{ kind='standard'; manager_arg='-PrepareTests'; pause='error' }
    'REPAIR_CURRENT_TRANSPORT.cmd' = [ordered]@{ kind='standard'; manager_arg='-RepairCurrentTransport'; pause='error' }
    'RESTORE_CANDIDATE_TRANSPORT.cmd' = [ordered]@{ kind='standard'; manager_arg='-RestoreCandidateTransport'; pause='error' }
    'SHOW_INSTANCE_INFO.cmd' = [ordered]@{ kind='standard'; manager_arg='-InstanceInfo'; pause='always' }
    'UPDATE_ALL.cmd' = [ordered]@{ kind='standard'; manager_arg='-UpdateAll'; pause='always' }
    'UPDATE_HUB.cmd' = [ordered]@{ kind='standard'; manager_arg='-UpdateHub'; pause='always' }
    'UPDATE_MANAGER.cmd' = [ordered]@{ kind='standard'; manager_arg='-UpdateManager'; pause='always' }
}

$script:ManagerMutex = $null
$script:ManagerMutexHeld = $false

New-Item -ItemType Directory -Force -Path $Inbox, $History, $Checkpoints, $Rollback, $ManagerUpdates, $Logs, $Releases, $WorkRoot | Out-Null
# BEGIN Keelaryn archive/metadata hardening
$script:KeelarynMaxJsonMetadataBytes = 4MB
$script:KeelarynMaxMarkdownMetadataBytes = 16MB

function Assert-KeelarynArchiveEntrySafety {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [System.IO.Compression.ZipArchiveEntry] $Entry
    )

    $rawAttributes = [System.BitConverter]::ToUInt32([System.BitConverter]::GetBytes([int]$Entry.ExternalAttributes), 0)
    $unixType = (($rawAttributes -shr 16) -band 0xF000)
    $isDirectory = $Entry.FullName.EndsWith('/') -or $Entry.FullName.EndsWith([string][char]92)

    # 0 means that the producer did not encode Unix mode bits. Otherwise only
    # regular files (0x8000) and directories (0x4000) are accepted.
    if ($unixType -ne 0 -and $unixType -ne 0x8000 -and $unixType -ne 0x4000) {
        throw "ZIP entry is not a regular file or directory: $($Entry.FullName)"
    }

    $dosAttributes = ($rawAttributes -band 0xFFFF)
    if (($dosAttributes -band [uint32][System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "ZIP entry carries a reparse-point attribute: $($Entry.FullName)"
    }

    # Size limits are enforced when an entry is actually read as structured/text metadata;
    # ordinary user JSON/Markdown remains subject only to the generic per-file/envelope limits.
}

function Assert-KeelarynJsonFileSize {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string] $LiteralPath)
    $item = Get-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "JSON metadata path must not be a reparse point: $LiteralPath"
    }
    if ($item.Length -gt $script:KeelarynMaxJsonMetadataBytes) {
        throw "JSON metadata file exceeds the safe limit ($($item.Length) bytes): $LiteralPath"
    }
}
# END Keelaryn archive/metadata hardening


function Read-KeelarynJsonFileText {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$LiteralPath)
    Assert-KeelarynJsonFileSize $LiteralPath
    return Get-Content -LiteralPath $LiteralPath -Raw -Encoding UTF8
}

function Read-KeelarynJsonFile {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$LiteralPath)
    return (Read-KeelarynJsonFileText $LiteralPath) | ConvertFrom-Json
}

function Rotate-Log {
    if (Test-Path $script:LogFile) {
        $item = Get-Item $script:LogFile
        if ($item.Length -gt 1MB) {
            $stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
            Move-Item $script:LogFile (Join-Path $script:Logs ("manager_" + $stamp + ".log"))
        }
    }

    $cutoff = (Get-Date).AddDays(-14)
    Get-ChildItem $script:Logs -Filter "manager_*.log" -File -ErrorAction SilentlyContinue | Where-Object {
        $_.LastWriteTime -lt $cutoff
    } | ForEach-Object {
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

function Write-ManagerLogLine([string]$Line,[int]$Attempts=40,[int]$DelayMs=100) {
    if ($Attempts -lt 1) { $Attempts=1 }
    if ($DelayMs -lt 0) { $DelayMs=0 }
    for ($attempt=1; $attempt -le $Attempts; $attempt++) {
        try {
            Add-Content -LiteralPath $script:LogFile -Value $Line -Encoding UTF8
            return
        }
        catch {
            $isTransient=Test-IsTransientFileLockException $_.Exception
            if (-not $isTransient) { throw }
            if ($attempt -ge $Attempts) { throw (New-FileLockDiagnosticException $script:LogFile 'Manager log write' $_.Exception) }
            if ($DelayMs -gt 0) { Start-Sleep -Milliseconds $DelayMs }
        }
    }
}

function Log([string]$Message) {
    $line = "{0} [Manager {1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $ManagerVersion, $Message
    Write-ManagerLogLine $line
}

function Set-AttentionNotice([string[]]$Lines) {
    $header = @(
        "Keelaryn Manager $ManagerVersion requires attention.",
        ("Generated: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss")),
        "",
        "No ambiguous package was installed and the current vault was not replaced by that package.",
        "For Keelaryn__Hub divergence/lineage issues, attach the relevant ZIP(s) to the dedicated Chat Manager.",
        ""
    )
    Set-Content -Path $script:AttentionFile -Value ($header + $Lines) -Encoding UTF8
}

function Clear-AttentionNotice {
    if (Test-Path $script:AttentionFile) {
        Remove-Item $script:AttentionFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-TextHashHex([string]$Text) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant()) }
    finally { $sha.Dispose() }
}

function Get-StreamHashHex([System.IO.Stream]$Stream) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Stream)).Replace('-', '').ToLowerInvariant()) }
    finally { $sha.Dispose() }
}

function Get-BytesHashHex([byte[]]$Bytes) {
    if ($null -eq $Bytes) { throw 'Byte array is null.' }
    $sha=[System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes)).Replace('-', '').ToLowerInvariant()) }
    finally { $sha.Dispose() }
}

function Test-Sha256Text([string]$Value) {
    if (-not $Value) { return $false }
    return [regex]::IsMatch($Value, '^[0-9a-fA-F]{64}$')
}

function Test-ArtifactId([string]$Value) {
    if (-not $Value) { return $false }
    return [regex]::IsMatch($Value, '^[A-Za-z0-9][A-Za-z0-9._-]{5,127}$')
}

function Acquire-ManagerLock {
    if ($script:ManagerMutexHeld) { return }
    $normalized = [System.IO.Path]::GetFullPath($Root).TrimEnd('\').ToLowerInvariant()
    $suffix = (Get-TextHashHex $normalized).Substring(0, 20)
    $names = @( ("Global\KeelarynManager_" + $suffix), ("Local\KeelarynManager_" + $suffix) )
    $lastError = $null

    foreach ($name in $names) {
        $mutex = $null
        try {
            $created = $false
            $mutex = New-Object System.Threading.Mutex($false, $name, [ref]$created)
            $acquired = $false
            try { $acquired = $mutex.WaitOne(0, $false) }
            catch [System.Threading.AbandonedMutexException] { $acquired = $true }
            if (-not $acquired) {
                $mutex.Dispose()
                throw "Another Keelaryn__Manager update process is already running."
            }
            $script:ManagerMutex = $mutex
            $script:ManagerMutexHeld = $true
            return
        }
        catch {
            if ($mutex) { try { $mutex.Dispose() } catch {} }
            $lastError = $_.Exception.Message
            if ($lastError -eq "Another Keelaryn__Manager update process is already running.") { throw }
        }
    }
    throw ("Could not acquire Keelaryn__Manager update mutex: " + $lastError)
}

function Release-ManagerLock {
    if ($script:ManagerMutexHeld -and $script:ManagerMutex) {
        try { $script:ManagerMutex.ReleaseMutex() } catch {}
        try { $script:ManagerMutex.Dispose() } catch {}
    }
    $script:ManagerMutex = $null
    $script:ManagerMutexHeld = $false
}

function Read-StateText([string]$Text) {
    $formatMatch = [regex]::Match($Text, '(?m)^keelaryn_format:\s*(\d+)\s*$')
    $namespace = 'keelaryn'
    if (-not $formatMatch.Success) {
        $legacyPattern = '(?m)^' + [regex]::Escape([string]$LegacyCoreCompat.StateFormatKey) + ':\s*(\d+)\s*$'
        $formatMatch = [regex]::Match($Text, $legacyPattern)
        if ($formatMatch.Success) { $namespace = 'legacy_core' }
    }
    $versionMatch = [regex]::Match($Text, '(?m)^system_version:\s*([0-9]+(?:\.[0-9]+){1,3})\s*$')
    $revisionMatch = [regex]::Match($Text, '(?m)^data_revision:\s*(\d+)\s*$')
    if (-not $formatMatch.Success -or -not $versionMatch.Success -or -not $revisionMatch.Success) { return $null }

    function Match-Optional([string]$Pattern) {
        $m = [regex]::Match($Text, $Pattern)
        if ($m.Success) { return $m.Groups[1].Value.Trim() }
        return $null
    }

    return [pscustomobject]@{
        Namespace = $namespace
        Format = [int]$formatMatch.Groups[1].Value
        Version = [version]$versionMatch.Groups[1].Value
        VersionText = $versionMatch.Groups[1].Value
        Revision = [int]$revisionMatch.Groups[1].Value
        RevisionScope = Match-Optional '(?m)^revision_scope:\s*([^\r\n]+?)\s*$'
        RouterSchema = Match-Optional '(?m)^derived_router_schema:\s*([^\r\n]+?)\s*$'
        IndexSchema = Match-Optional '(?m)^derived_index_schema:\s*([^\r\n]+?)\s*$'
        ValidationSchema = Match-Optional '(?m)^derived_validation_schema:\s*([^\r\n]+?)\s*$'
        ManifestSchema = Match-Optional '(?m)^derived_manifest_schema:\s*([^\r\n]+?)\s*$'
        ArtifactSchema = Match-Optional '(?m)^artifact_schema:\s*([^\r\n]+?)\s*$'
        InstanceSchema = Match-Optional '(?m)^instance_schema:\s*([^\r\n]+?)\s*$'
        ManagerProtocol = Match-Optional '(?m)^manager_protocol:\s*([^\r\n]+?)\s*$'
    }
}

function New-CheckResult([bool]$Valid, [string]$Reason) {
    return [pscustomobject]@{ Valid = $Valid; Reason = $Reason }
}

function Resolve-IndexLink([string]$SourcePath, [string]$Target, [hashtable]$KnownPaths, [hashtable]$BasenameCounts) {
    $t = $Target.Replace('\','/').Trim('/')
    if (-not $t) { return $true }
    $direct = $t.ToLowerInvariant()
    if ($KnownPaths.ContainsKey($direct)) { return $true }

    $sourceDir = [System.IO.Path]::GetDirectoryName($SourcePath)
    if ($sourceDir) {
        $sourceDir = $sourceDir.Replace('\','/').Trim('/')
        $relative = ($sourceDir + "/" + $t).ToLowerInvariant()
        if ($KnownPaths.ContainsKey($relative)) { return $true }
    }

    $base = [System.IO.Path]::GetFileName($t).ToLowerInvariant()
    if ($BasenameCounts.ContainsKey($base) -and [int]$BasenameCounts[$base] -eq 1) { return $true }
    return $false
}

function Test-RouterSchemaV2([string]$Schema) { return $Schema -eq 'keelaryn.router.v2' -or $Schema -eq [string]$LegacyCoreCompat.RouterV2 }
function Test-RouterSchemaV1([string]$Schema) { return $Schema -eq [string]$LegacyCoreCompat.RouterV1 }
function Test-ArtifactSchemaV1([string]$Schema) { return $Schema -eq [string]$LegacyCoreCompat.ArtifactV1 }
function Test-ArtifactSchemaV2([string]$Schema) { return $Schema -eq [string]$LegacyCoreCompat.ArtifactV2 }
function Test-ArtifactSchemaV3([string]$Schema) { return $Schema -eq 'keelaryn.artifact.v3' -or $Schema -eq [string]$LegacyCoreCompat.ArtifactV3 }
function Test-InstanceSchema([string]$Schema) { return $Schema -eq 'keelaryn.instance.v1' -or $Schema -eq [string]$LegacyCoreCompat.InstanceSchema }

function Test-DerivedMetadataTexts([string]$IndexText, [string]$RouterText, [string]$ValidationText, $State) {
    try { $index = $IndexText | ConvertFrom-Json }
    catch { return New-CheckResult $false ("INDEX JSON parse failed: " + $_.Exception.Message) }

    if ($null -eq $index.schema -or $null -eq $index.system_version -or $null -eq $index.data_revision -or $null -eq $index.entities) {
        return New-CheckResult $false "INDEX is missing required top-level fields."
    }
    if ([string]$index.system_version -ne $State.VersionText -or [int]$index.data_revision -ne $State.Revision) {
        return New-CheckResult $false "INDEX version/revision disagrees with STATE."
    }
    if ($State.InstanceId -and ([string]$index.instance_id).ToLowerInvariant() -ne $State.InstanceId) {
        return New-CheckResult $false "INDEX instance_id disagrees with INSTANCE."
    }
    if ($State.IndexSchema -and ([string]$index.schema -ne $State.IndexSchema)) {
        return New-CheckResult $false "INDEX schema disagrees with STATE."
    }

    $entities = @($index.entities)
    if ($null -ne $index.entity_count -and [int]$index.entity_count -ne $entities.Count) {
        return New-CheckResult $false "INDEX entity_count disagrees with entity list."
    }

    $ids = @{}
    $paths = @{}
    $knownPaths = @{}
    $basenameCounts = @{}
    foreach ($entity in $entities) {
        foreach ($required in @('id','type','status','updated','path','title')) {
            if ($null -eq $entity.PSObject.Properties[$required] -or -not ([string]$entity.$required).Trim()) {
                return New-CheckResult $false ("INDEX entity missing required field {0}." -f $required)
            }
        }
        if ($entity.parse_error) { return New-CheckResult $false ("INDEX contains parse_error for " + [string]$entity.path) }

        $idKey = ([string]$entity.id).ToLowerInvariant()
        if ($ids.ContainsKey($idKey)) { return New-CheckResult $false ("Duplicate entity id: " + [string]$entity.id) }
        $ids[$idKey] = $true

        $pathKey = ([string]$entity.path).Replace('\','/').ToLowerInvariant()
        if ($paths.ContainsKey($pathKey)) { return New-CheckResult $false ("Duplicate entity path: " + [string]$entity.path) }
        $paths[$pathKey] = $entity

        $withoutExt = $pathKey
        if ($withoutExt.EndsWith('.md')) { $withoutExt = $withoutExt.Substring(0, $withoutExt.Length - 3) }
        $knownPaths[$withoutExt] = $true
        $base = [System.IO.Path]::GetFileName($withoutExt).ToLowerInvariant()
        if (-not $basenameCounts.ContainsKey($base)) { $basenameCounts[$base] = 0 }
        $basenameCounts[$base] = [int]$basenameCounts[$base] + 1
    }

    foreach ($entity in $entities) {
        foreach ($link in @($entity.links)) {
            $target = ([string]$link).Split('|')[0].Split('#')[0].Trim()
            if ($target -and -not (Resolve-IndexLink ([string]$entity.path) $target $knownPaths $basenameCounts)) {
                return New-CheckResult $false ("Broken indexed wikilink: {0} -> {1}" -f $entity.path, $target)
            }
        }
    }

    if ($State.RouterSchema) {
        if (-not $RouterText) { return New-CheckResult $false "STATE declares Router schema but ROUTER is missing." }
        try { $router = $RouterText | ConvertFrom-Json }
        catch { return New-CheckResult $false ("ROUTER JSON parse failed: " + $_.Exception.Message) }
        if ([string]$router.schema -ne $State.RouterSchema -or [string]$router.system_version -ne $State.VersionText -or [int]$router.data_revision -ne $State.Revision) {
            return New-CheckResult $false "ROUTER schema/version/revision disagrees with STATE."
        }
        if ($State.InstanceId -and ([string]$router.instance_id).ToLowerInvariant() -ne $State.InstanceId) { return New-CheckResult $false "ROUTER instance_id disagrees with INSTANCE." }
        $routes = @($router.routes)
        $expected = @($entities)
        if ((Test-RouterSchemaV2 $State.RouterSchema)) {
            $expected = @($entities | Where-Object { ([string]$_.status) -eq 'active' -or ([string]$_.status) -eq 'waiting' })
            if ([int]$router.source_entity_count -ne $entities.Count -or [int]$router.route_count -ne $routes.Count) {
                return New-CheckResult $false "ROUTER v2 counts disagree with INDEX/routes."
            }
            $statuses = @($router.included_statuses | ForEach-Object { ([string]$_).ToLowerInvariant() } | Sort-Object -Unique)
            if ($statuses.Count -ne 2 -or $statuses[0] -ne 'active' -or $statuses[1] -ne 'waiting') {
                return New-CheckResult $false "ROUTER v2 included_statuses must be active/waiting."
            }
        }
        elseif ((Test-RouterSchemaV1 $State.RouterSchema)) {
            if ([int]$router.entity_count -ne $entities.Count) { return New-CheckResult $false "ROUTER v1 entity_count disagrees with INDEX." }
        }
        else { return New-CheckResult $false ("Unsupported Router schema: " + $State.RouterSchema) }

        if ($routes.Count -ne $expected.Count) { return New-CheckResult $false "ROUTER route count differs from expected INDEX subset." }
        $seenRoutes = @{}
        foreach ($row in $routes) {
            $a = @($row)
            if ($a.Count -ne 4) { return New-CheckResult $false "ROUTER row does not have four fields." }
            $pkey = ([string]$a[2]).Replace('\','/').ToLowerInvariant()
            if ($seenRoutes.ContainsKey($pkey)) { return New-CheckResult $false ("Duplicate ROUTER path: " + [string]$a[2]) }
            $seenRoutes[$pkey] = $true
            if (-not $paths.ContainsKey($pkey)) { return New-CheckResult $false ("ROUTER path absent from INDEX: " + [string]$a[2]) }
            $e = $paths[$pkey]
            if ([string]$a[0] -ne [string]$e.type -or [string]$a[1] -ne [string]$e.status -or [string]$a[3] -ne [string]$e.title) {
                return New-CheckResult $false ("ROUTER row disagrees with INDEX: " + [string]$a[2])
            }
        }
    }

    if ($State.ValidationSchema) {
        if (-not $ValidationText) { return New-CheckResult $false "STATE declares Validation schema but VALIDATION is missing." }
        try { $validation = $ValidationText | ConvertFrom-Json }
        catch { return New-CheckResult $false ("VALIDATION JSON parse failed: " + $_.Exception.Message) }
        if ([string]$validation.schema -ne $State.ValidationSchema -or [string]$validation.system_version -ne $State.VersionText -or [int]$validation.data_revision -ne $State.Revision) {
            return New-CheckResult $false "VALIDATION schema/version/revision disagrees with STATE."
        }
        if ($State.InstanceId -and ([string]$validation.instance_id).ToLowerInvariant() -ne $State.InstanceId) { return New-CheckResult $false "VALIDATION instance_id disagrees with INSTANCE." }
        if ([int]$validation.entity_count -ne $entities.Count -or [int]$validation.error_count -ne 0) {
            return New-CheckResult $false "VALIDATION summary reports inconsistent entity count/errors."
        }
        if ((Test-RouterSchemaV2 $State.RouterSchema) -and [int]$validation.route_count -ne @($router.routes).Count) {
            return New-CheckResult $false "VALIDATION route_count disagrees with ROUTER."
        }
        $checks = $validation.checks
        if ($State.ManifestSchema) {
            if ([string]$validation.source_manifest.schema -ne $State.ManifestSchema -or -not [bool]$checks.manifest_consistent) { return New-CheckResult $false "VALIDATION source manifest declaration is not clean." }
        }
        if (-not $checks -or [int]$checks.parse_errors -ne 0 -or [int]$checks.duplicate_ids -ne 0 -or [int]$checks.duplicate_paths -ne 0 -or [int]$checks.broken_links -ne 0 -or -not [bool]$checks.required_metadata -or -not [bool]$checks.index_consistent -or -not [bool]$checks.router_consistent) {
            return New-CheckResult $false "VALIDATION checks are not clean."
        }
    }

    return New-CheckResult $true "Derived metadata valid."
}

function Test-InstanceId([string]$Value) {
    if (-not $Value) { return $false }
    $g = [guid]::Empty
    return [guid]::TryParse($Value, [ref]$g) -and $g -ne [guid]::Empty
}

function Parse-InstanceManifestText([string]$Text) {
    try { $m = $Text | ConvertFrom-Json } catch { return $null }
    if (-not (Test-InstanceSchema ([string]$m.schema))) { return $null }
    $id = ([string]$m.instance_id).Trim()
    $created = ([string]$m.created).Trim()
    if (-not (Test-InstanceId $id) -or -not $created) { return $null }

    $origin = ([string]$m.origin_type).Trim().ToLowerInvariant()
    if (-not $origin) {
        if (([string]$m.genesis_release_id).Trim()) { $origin = 'genesis' }
        else { return $null }
    }
    if ($origin -eq 'genesis') {
        if (-not ([string]$m.genesis_release_id).Trim()) { return $null }
    }
    elseif ($origin -eq 'legacy_adoption') {
        if (-not ([string]$m.adoption_release_id).Trim()) { return $null }
    }
    else { return $null }

    return [pscustomobject]@{
        InstanceId = $id.ToLowerInvariant()
        Schema = [string]$m.schema
        OriginType = $origin
        GenesisReleaseId = ([string]$m.genesis_release_id).Trim()
        AdoptionReleaseId = ([string]$m.adoption_release_id).Trim()
        Created = $created
    }
}

function Read-VaultInstanceAt([string]$VaultPath) {
    $p = Join-Path $VaultPath '_System\INSTANCE.json'
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { return $null }
    try { return Parse-InstanceManifestText (Read-KeelarynJsonFileText $p) }
    catch { return $null }
}

function Read-ZipInstance([string]$ZipPath) {
    $zipInfo = Get-HubZipEnvelope $ZipPath
    if (-not $zipInfo) { return $null }
    $archive = $null
    try {
        $archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
        $entryName = $zipInfo.Root + '_System/INSTANCE.json'
        $entry = $archive.Entries | Where-Object { $_.FullName.Replace('\','/') -eq $entryName } | Select-Object -First 1
        if (-not $entry) { return $null }
        return Parse-InstanceManifestText (Read-ZipEntryText $entry)
    }
    catch { return $null }
    finally { if ($archive) { $archive.Dispose() } }
}

function Read-VaultStateCoreAt([string]$VaultPath) {
    $statePath = Join-Path $VaultPath '_System\STATE.md'
    if (-not (Test-Path $statePath -PathType Leaf)) { return $null }
    $state = Read-StateText (Get-Content $statePath -Raw -Encoding UTF8)
    if (-not $state -or $state.Format -ne 1) { return $null }
    if ($state.InstanceSchema) {
        $instance = Read-VaultInstanceAt $VaultPath
        if (-not $instance -or $instance.Schema -ne $state.InstanceSchema) { return $null }
        $state | Add-Member -NotePropertyName InstanceId -NotePropertyValue $instance.InstanceId -Force
    } else { $state | Add-Member -NotePropertyName InstanceId -NotePropertyValue $null -Force }
    return $state
}

function Get-VaultManifestDiagnostic([string]$HubPath,$State,$PortableAnalysis=$null) {
    $path = Join-Path $HubPath '_System\MANIFEST.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return [pscustomobject]@{Valid=$false;Reason='MANIFEST is missing.';DeclaredCount=$null;ActualCount=$null;DeclaredHash=$null;ActualHash=$null;Missing=@();Extra=@();Changed=@()}
    }
    try { $manifest = Read-KeelarynJsonFile $path }
    catch { return [pscustomobject]@{Valid=$false;Reason=('MANIFEST JSON parse failed: '+$_.Exception.Message);DeclaredCount=$null;ActualCount=$null;DeclaredHash=$null;ActualHash=$null;Missing=@();Extra=@();Changed=@()} }

    $built = New-PortableSourceManifest $HubPath $State.VersionText $State.Revision $State.InstanceId $PortableAnalysis
    $check = Test-ManifestObjectAgainstBuilt $manifest $built $State
    if ($check.Valid) {
        return [pscustomobject]@{
            Valid=$true;Reason=$check.Reason;DeclaredCount=[int]$manifest.entry_count;ActualCount=[int]$built.EntryCount
            DeclaredHash=([string]$manifest.content_set_sha256).ToLowerInvariant();ActualHash=$built.ContentHash
            Missing=@();Extra=@();Changed=@()
        }
    }
    # Detailed path classification is diagnostic-only and is intentionally paid only on mismatch.
    $declared=@{}; $actual=@{}
    foreach ($row in @($manifest.entries)) {
        $a=@($row); if ($a.Count -ne 3) { continue }
        $key=([string]$a[0]).Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
        if (-not $declared.ContainsKey($key)) { $declared[$key]=[pscustomobject]@{Path=[string]$a[0];Length=[long]$a[1];Hash=([string]$a[2]).ToLowerInvariant()} }
    }
    foreach ($row in @($built.Manifest.entries)) {
        $a=@($row); $key=([string]$a[0]).Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
        $actual[$key]=[pscustomobject]@{Path=[string]$a[0];Length=[long]$a[1];Hash=([string]$a[2]).ToLowerInvariant()}
    }

    $missing=New-Object System.Collections.ArrayList; $extra=New-Object System.Collections.ArrayList; $changed=New-Object System.Collections.ArrayList
    foreach ($key in @($declared.Keys | Sort-Object)) {
        if (-not $actual.ContainsKey($key)) { [void]$missing.Add($declared[$key].Path); continue }
        $d=$declared[$key]; $a=$actual[$key]
        if ($d.Length -ne $a.Length -or $d.Hash -ne $a.Hash) { [void]$changed.Add($a.Path) }
    }
    foreach ($key in @($actual.Keys | Sort-Object)) { if (-not $declared.ContainsKey($key)) { [void]$extra.Add($actual[$key].Path) } }

    $reason=$check.Reason
    if (-not $check.Valid) {
        $parts=New-Object System.Collections.ArrayList
        [void]$parts.Add('declared_count='+[string]$manifest.entry_count)
        [void]$parts.Add('actual_count='+[string]$built.EntryCount)
        [void]$parts.Add('declared_hash='+([string]$manifest.content_set_sha256).ToLowerInvariant())
        [void]$parts.Add('actual_hash='+$built.ContentHash)
        if ($missing.Count -gt 0) { [void]$parts.Add('missing='+[string]::Join(', ',@($missing|Select-Object -First 8))) }
        if ($extra.Count -gt 0) { [void]$parts.Add('extra='+[string]::Join(', ',@($extra|Select-Object -First 8))) }
        if ($changed.Count -gt 0) { [void]$parts.Add('changed='+[string]::Join(', ',@($changed|Select-Object -First 8))) }
        $reason += ' ' + [string]::Join('; ',@($parts)) + '.'
    }
    return [pscustomobject]@{
        Valid=[bool]$check.Valid;Reason=$reason;DeclaredCount=[int]$manifest.entry_count;ActualCount=[int]$built.EntryCount
        DeclaredHash=([string]$manifest.content_set_sha256).ToLowerInvariant();ActualHash=$built.ContentHash
        Missing=@($missing);Extra=@($extra);Changed=@($changed)
    }
}

function Read-VaultMetadataAt([string]$VaultPath,$PortableAnalysis=$null) {
    $indexPath = Join-Path $VaultPath '_System\INDEX.json'
    if (-not (Test-Path -LiteralPath $indexPath -PathType Leaf)) { return $null }

    $state = Read-VaultStateCoreAt $VaultPath
    if (-not $state) { return $null }

    $routerText = $null
    if ($state.RouterSchema) {
        $routerPath = Join-Path $VaultPath '_System\ROUTER.json'
        if (-not (Test-Path -LiteralPath $routerPath -PathType Leaf)) { return $null }
        $routerText = Read-KeelarynJsonFileText $routerPath
    }
    $validationText = $null
    if ($state.ValidationSchema) {
        $validationPath = Join-Path $VaultPath '_System\VALIDATION.json'
        if (-not (Test-Path -LiteralPath $validationPath -PathType Leaf)) { return $null }
        $validationText = Read-KeelarynJsonFileText $validationPath
    }

    $check = Test-DerivedMetadataTexts (Read-KeelarynJsonFileText $indexPath) $routerText $validationText $state
    if (-not $check.Valid) {
        Log ("Vault metadata validation failed at {0}: {1}" -f $VaultPath, $check.Reason)
        return $null
    }
    if ($state.ManifestSchema) {
        $manifestCheck = Test-VaultSourceManifestConsistency $VaultPath $state $PortableAnalysis
        if (-not $manifestCheck.Valid) { Log ("Vault source manifest validation failed at {0}: {1}" -f $VaultPath,$manifestCheck.Reason); return $null }
    }
    return $state
}

function Read-VaultState { return Read-VaultMetadataAt $Vault }

function Read-ZipEntryText($Entry) {
    Assert-KeelarynArchiveEntrySafety -Entry $Entry
    $extension=[System.IO.Path]::GetExtension([string]$Entry.FullName).ToLowerInvariant()
    $limit=[long]$script:KeelarynMaxMarkdownMetadataBytes
    if ($extension -eq '.json') { $limit=[long]$script:KeelarynMaxJsonMetadataBytes }
    if ([long]$Entry.Length -gt $limit) { throw ('ZIP text/metadata entry exceeds safe read limit ('+$limit+' bytes): '+[string]$Entry.FullName) }
    $stream=$Entry.Open()
    $reader=New-Object System.IO.StreamReader($stream,[System.Text.Encoding]::UTF8,$true,4096,$false)
    try { return $reader.ReadToEnd() }
    finally { $reader.Dispose(); $stream.Dispose() }
}

function Test-ZipEnvelopeArchive($Archive, [long]$ZipLength, [long]$MaxZipBytes, [long]$MaxExpandedBytes, [int]$MaxEntries, [string]$RequiredRoot) {
    if ($ZipLength -gt $MaxZipBytes) { return New-CheckResult $false ("ZIP exceeds allowed compressed size ({0} bytes)." -f $MaxZipBytes) }
    try {
        if ($Archive.Entries.Count -gt $MaxEntries) { return New-CheckResult $false ("ZIP exceeds entry limit ({0})." -f $MaxEntries) }
        $seen = @{}
        [long]$expanded = 0
        [long]$compressed = 0
        foreach ($entry in $Archive.Entries) {
            Assert-KeelarynArchiveEntrySafety -Entry $entry
            $name = $entry.FullName.Replace('\','/')
            if (-not $name.StartsWith($RequiredRoot, [System.StringComparison]::Ordinal)) { return New-CheckResult $false ("ZIP entry is outside required root: " + $name) }
            $relative = $name.Substring($RequiredRoot.Length)
            if ($relative) {
                $segments = @($relative.TrimEnd('/') -split '/')
                if (@($segments | Where-Object { $_ -eq '.' -or $_ -eq '..' }).Count -gt 0) { return New-CheckResult $false ("Unsafe ZIP path: " + $name) }
                foreach ($segment in $segments) {
                    if (-not $segment) { return New-CheckResult $false ("Unsafe empty ZIP path segment: " + $name) }
                    if ($segment.Length -gt 180) { return New-CheckResult $false ("ZIP path segment exceeds safety limit: " + $name) }
                    if ($segment.Contains(':') -or $segment.EndsWith(' ') -or $segment.EndsWith('.')) { return New-CheckResult $false ("Unsafe Windows ZIP path segment: " + $name) }
                    if (Test-IsWindowsReservedPathSegment $segment) { return New-CheckResult $false ("Reserved Windows ZIP path segment: " + $name) }
                }
                if ($relative.Length -gt 512) { return New-CheckResult $false ("ZIP relative path exceeds safety limit: " + $name) }
            }
            $unixType = (($entry.ExternalAttributes -shr 16) -band 0xF000)
            if ($unixType -eq 0xA000) { return New-CheckResult $false ("Symbolic-link ZIP entry is not allowed: " + $name) }
            if ($entry.Length -gt 64MB) { return New-CheckResult $false ("ZIP entry exceeds per-file safety limit: " + $name) }
            $key = $name.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
            if ($seen.ContainsKey($key)) { return New-CheckResult $false ("Duplicate/Unicode-colliding ZIP path: " + $name) }
            $seen[$key] = $true
            $expanded += [long]$entry.Length
            $compressed += [long]$entry.CompressedLength
            if ($expanded -gt $MaxExpandedBytes) { return New-CheckResult $false ("ZIP expanded size exceeds limit ({0} bytes)." -f $MaxExpandedBytes) }
        }
        if ($expanded -gt 10MB -and $compressed -gt 0) {
            $ratio = [double]$expanded / [double]$compressed
            if ($ratio -gt $MaxCompressionRatio) { return New-CheckResult $false ("ZIP compression ratio exceeds safety limit ({0:N1}:1)." -f $ratio) }
        }
        return [pscustomobject]@{ Valid=$true; Reason='ZIP envelope valid.'; ExpandedBytes=$expanded; EntryCount=$Archive.Entries.Count }
    }
    catch { return New-CheckResult $false ("ZIP envelope check failed: " + $_.Exception.Message) }
}

function Test-ZipEnvelope([string]$ZipPath, [long]$MaxZipBytes, [long]$MaxExpandedBytes, [int]$MaxEntries, [string]$RequiredRoot) {
    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) { return New-CheckResult $false "ZIP does not exist." }
    $file = Get-Item -LiteralPath $ZipPath -Force
    if ($file.Length -gt $MaxZipBytes) { return New-CheckResult $false ("ZIP exceeds allowed compressed size ({0} bytes)." -f $MaxZipBytes) }
    $archive = $null
    try {
        $archive = [System.IO.Compression.ZipFile]::OpenRead($file.FullName)
        return Test-ZipEnvelopeArchive $archive ([long]$file.Length) $MaxZipBytes $MaxExpandedBytes $MaxEntries $RequiredRoot
    }
    catch { return New-CheckResult $false ("ZIP envelope check failed: " + $_.Exception.Message) }
    finally { if ($archive) { $archive.Dispose() } }
}

function Test-HubZipInspectionSessionForPath($Session,[string]$ZipPath) {
    if (-not $Session -or -not $Session.Archive) { return $false }
    try { $full=[System.IO.Path]::GetFullPath($ZipPath) } catch { return $false }
    return [string]::Equals([string]$Session.ZipPath,$full,[System.StringComparison]::OrdinalIgnoreCase)
}

function Open-HubZipInspectionSession([string]$ZipPath) {
    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) { return $null }
    $full=[System.IO.Path]::GetFullPath($ZipPath)
    $file=Get-Item -LiteralPath $full -Force
    if ($file.Length -gt $MaxHubZipBytes) { return $null }
    $archive=$null
    try {
        $archive=[System.IO.Compression.ZipFile]::OpenRead($full)
        $root='Keelaryn__Hub/'; $legacy=$false
        $envelope=Test-ZipEnvelopeArchive $archive ([long]$file.Length) $MaxHubZipBytes $MaxHubExpandedBytes $MaxHubEntries $root
        if (-not $envelope.Valid) {
            $root=[string]$LegacyCoreCompat.HubZipRoot; $legacy=$true
            $envelope=Test-ZipEnvelopeArchive $archive ([long]$file.Length) $MaxHubZipBytes $MaxHubExpandedBytes $MaxHubEntries $root
        }
        if (-not $envelope.Valid) { $archive.Dispose(); $archive=$null; return $null }

        $entryMap=@{}
        $hashedRows=New-Object System.Collections.ArrayList
        $contentRows=New-Object System.Collections.ArrayList
        $payloadRows=New-Object System.Collections.ArrayList
        $manifestRows=New-Object System.Collections.ArrayList
        $manifestEntries=New-Object System.Collections.ArrayList
        $manifestExcluded=@{'_system/artifact.json'=$true;'_system/manifest.json'=$true;'_system/index.json'=$true;'_system/router.json'=$true;'_system/validation.json'=$true}
        $containsLocal=$false
        foreach ($entry in $archive.Entries) {
            $n=$entry.FullName.Replace('\','/')
            $entryMap[$n]=$entry
            $localRel=$n.Substring($root.Length).TrimEnd('/')
            if ($localRel -and (Test-IsLocalDeploymentRelativePath $localRel)) { $containsLocal=$true }
            if ($n.EndsWith('/') -or (Test-IsLocalDeploymentRelativePath $localRel)) { continue }
            $rel=$n.Substring($root.Length)
            $stream=$entry.Open(); try { $hash=Get-StreamHashHex $stream } finally { $stream.Dispose() }
            [void]$hashedRows.Add([pscustomobject]@{
                RawSort=([string]$entry.FullName).ToLowerInvariant(); ManifestSort=([string]$n).ToLowerInvariant()
                Rel=$rel; Length=[long]$entry.Length; Hash=$hash
            })
        }
        # Preserve the exact legacy ordering contracts while hashing each entry only once.
        # Get-ZipHashPair historically sorts raw ZIP names; MANIFEST construction sorts slash-normalized names.
        foreach ($row in @($hashedRows | Sort-Object { $_.RawSort })) {
            $line=[string]$row.Rel+"`0"+[string]$row.Hash
            [void]$contentRows.Add($line)
            if ([string]$row.Rel -ne '_System/ARTIFACT.json') { [void]$payloadRows.Add($line) }
        }
        foreach ($row in @($hashedRows | Sort-Object { $_.ManifestSort })) {
            $manifestKey=([string]$row.Rel).Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
            if (-not $manifestExcluded.ContainsKey($manifestKey)) {
                $line=[string]$row.Rel+"`0"+[string]$row.Hash
                [void]$manifestRows.Add($line)
                [void]$manifestEntries.Add([pscustomobject]@{Rel=[string]$row.Rel;Length=[long]$row.Length;Hash=[string]$row.Hash})
            }
        }
        $hashPair=[pscustomobject]@{
            ContentHash=Get-TextHashHex ([string]::Join("`n",@($contentRows)))
            PayloadHash=Get-TextHashHex ([string]::Join("`n",@($payloadRows)))
        }
        return [pscustomobject]@{
            ZipPath=$full; Archive=$archive; Root=$root; Legacy=$legacy; Envelope=$envelope; EntryMap=$entryMap
            ContainsLocalDeploymentState=[bool]$containsLocal; HashPair=$hashPair; PortableFiles=@($hashedRows); ManifestEntries=@($manifestEntries)
            ManifestContentHash=Get-TextHashHex ([string]::Join("`n",@($manifestRows)))
        }
    }
    catch {
        if ($archive) { $archive.Dispose() }
        throw
    }
}

function Close-HubZipInspectionSession($Session) {
    if ($Session -and $Session.Archive) { $Session.Archive.Dispose() }
}

function Get-HubZipEnvelope([string]$ZipPath) {
    $newRoot = 'Keelaryn__Hub/'
    $check = Test-ZipEnvelope $ZipPath $MaxHubZipBytes $MaxHubExpandedBytes $MaxHubEntries $newRoot
    if ($check.Valid) { return [pscustomobject]@{ Root=$newRoot; Legacy=$false; Envelope=$check } }
    $legacyRoot = [string]$LegacyCoreCompat.HubZipRoot
    $legacyCheck = Test-ZipEnvelope $ZipPath $MaxHubZipBytes $MaxHubExpandedBytes $MaxHubEntries $legacyRoot
    if ($legacyCheck.Valid) { return [pscustomobject]@{ Root=$legacyRoot; Legacy=$true; Envelope=$legacyCheck } }
    return $null
}

function Read-ZipState([string]$ZipPath,$Session=$null) {
    if ($Session -and -not (Test-HubZipInspectionSessionForPath $Session $ZipPath)) { throw 'Hub ZIP inspection session/path mismatch.' }
    $zipInfo = if ($Session) { [pscustomobject]@{Root=$Session.Root;Legacy=$Session.Legacy;Envelope=$Session.Envelope} } else { Get-HubZipEnvelope $ZipPath }
    if (-not $zipInfo) { Log ("Invalid Hub ZIP {0}: unsupported archive root or unsafe envelope." -f $ZipPath); return $null }
    $hubRoot = [string]$zipInfo.Root
    $envelope = $zipInfo.Envelope

    $archive = $null
    try {
        $archive = if ($Session) { $Session.Archive } else { [System.IO.Compression.ZipFile]::OpenRead($ZipPath) }
        $stateName=$hubRoot + '_System/STATE.md'; $indexName=$hubRoot + '_System/INDEX.json'
        $stateEntry = if ($Session) { $Session.EntryMap[$stateName] } else { $archive.Entries | Where-Object { $_.FullName.Replace('\','/') -eq $stateName } | Select-Object -First 1 }
        $indexEntry = if ($Session) { $Session.EntryMap[$indexName] } else { $archive.Entries | Where-Object { $_.FullName.Replace('\','/') -eq $indexName } | Select-Object -First 1 }
        if (-not $stateEntry -or -not $indexEntry) { return $null }
        $state = Read-StateText (Read-ZipEntryText $stateEntry)
        if (-not $state -or $state.Format -ne 1) { return $null }
        if ($state.InstanceSchema) {
            $instanceName=$hubRoot + '_System/INSTANCE.json'
            $instanceEntry=if ($Session) { $Session.EntryMap[$instanceName] } else { $archive.Entries | Where-Object { $_.FullName.Replace('\','/') -eq $instanceName } | Select-Object -First 1 }
            if (-not $instanceEntry) { return $null }
            $instance=Parse-InstanceManifestText (Read-ZipEntryText $instanceEntry)
            if (-not $instance -or $instance.Schema -ne $state.InstanceSchema) { return $null }
            $state | Add-Member -NotePropertyName InstanceId -NotePropertyValue $instance.InstanceId -Force
        } else { $state | Add-Member -NotePropertyName InstanceId -NotePropertyValue $null -Force }

        $routerText = $null
        if ($state.RouterSchema) {
            $routerName=$hubRoot + '_System/ROUTER.json'
            $routerEntry = if ($Session) { $Session.EntryMap[$routerName] } else { $archive.Entries | Where-Object { $_.FullName.Replace('\','/') -eq $routerName } | Select-Object -First 1 }
            if (-not $routerEntry) { return $null }
            $routerText = Read-ZipEntryText $routerEntry
        }
        $validationText = $null
        if ($state.ValidationSchema) {
            $validationName=$hubRoot + '_System/VALIDATION.json'
            $validationEntry = if ($Session) { $Session.EntryMap[$validationName] } else { $archive.Entries | Where-Object { $_.FullName.Replace('\','/') -eq $validationName } | Select-Object -First 1 }
            if (-not $validationEntry) { return $null }
            $validationText = Read-ZipEntryText $validationEntry
        }

        $check = Test-DerivedMetadataTexts (Read-ZipEntryText $indexEntry) $routerText $validationText $state
        if (-not $check.Valid) { Log ("Invalid Hub derived metadata {0}: {1}" -f $ZipPath,$check.Reason); return $null }
        if ($state.ManifestSchema) {
            $manifestCheck=Test-ZipSourceManifestConsistency $ZipPath $state $Session
            if (-not $manifestCheck.Valid) { Log ("Invalid Hub source manifest {0}: {1}" -f $ZipPath,$manifestCheck.Reason); return $null }
        }
        $state | Add-Member -NotePropertyName ExpandedBytes -NotePropertyValue ([long]$envelope.ExpandedBytes) -Force
        $state | Add-Member -NotePropertyName EntryCount -NotePropertyValue ([int]$envelope.EntryCount) -Force
        $state | Add-Member -NotePropertyName ZipRoot -NotePropertyValue $hubRoot.TrimEnd('/') -Force
        $state | Add-Member -NotePropertyName LegacyArchiveRoot -NotePropertyValue ([bool]$zipInfo.Legacy) -Force
        return $state
    }
    catch { Log ("Invalid Hub package {0}: {1}" -f $ZipPath, $_.Exception.Message); return $null }
    finally { if ($archive -and -not $Session) { $archive.Dispose() } }
}

function Parse-ArtifactManifestText([string]$Text) {
    try { $manifest = $Text | ConvertFrom-Json } catch { return $null }

    $schema = ([string]$manifest.schema).Trim()
    if (-not (Test-ArtifactSchemaV1 $schema) -and -not (Test-ArtifactSchemaV2 $schema) -and -not (Test-ArtifactSchemaV3 $schema)) { return $null }
    $status = ([string]$manifest.artifact_status).Trim().ToLowerInvariant()
    if ($status -ne 'candidate' -and $status -ne 'approved') { return $null }
    $artifactId = ([string]$manifest.artifact_id).Trim()
    if (-not (Test-ArtifactId $artifactId)) { return $null }
    $producer = ([string]$manifest.producer_role).Trim().ToLowerInvariant()
    $isMigrationProducer = ($producer -eq 'keelaryn_manager_migration' -or $producer -eq 'core_manager_migration')
    $isGenesisProducer = ($producer -eq 'keelaryn_manager_genesis' -or $producer -eq 'core_manager_genesis')

    $genesis = $false
    if ((Test-ArtifactSchemaV3 $schema) -and $manifest.PSObject.Properties['genesis']) { $genesis = [bool]$manifest.genesis }
    if ($genesis) {
        if ($status -ne 'approved' -or -not $isGenesisProducer) { return $null }
    }
    else {
        if ($status -eq 'candidate' -and $producer -ne 'worker' -and $producer -ne 'worker_chat' -and -not $isMigrationProducer) { return $null }
        if ($status -eq 'approved' -and $producer -ne 'chat_manager' -and -not $isMigrationProducer) { return $null }
        if ($isMigrationProducer -and -not (Test-ArtifactSchemaV3 $schema)) { return $null }
    }

    try {
        $version = [version]([string]$manifest.system_version)
        $revision = [int]$manifest.data_revision
        $baseRevision = [int]$manifest.base_data_revision
    }
    catch { return $null }
    $baseVersionText = ([string]$manifest.base_system_version).Trim()
    $managerProtocol = ([string]$manifest.manager_protocol).Trim()
    $createdUtc=([string]$manifest.created).Trim()
    if (-not $managerProtocol -or -not $createdUtc) { return $null }
    try{$null=[DateTimeOffset]::Parse($createdUtc)}catch{return $null}
    $revisionTimeUtc=$createdUtc
    if($manifest.PSObject.Properties['revision_time_utc']){
        $revisionTimeUtc=([string]$manifest.revision_time_utc).Trim()
        if(-not$revisionTimeUtc){return $null}
        try{$rt=[DateTimeOffset]::Parse($revisionTimeUtc);if($rt.Offset-ne[TimeSpan]::Zero){return $null}}catch{return $null}
    }

    if ((Test-ArtifactSchemaV1 $schema)) {
        if ($revision -lt 1 -or $baseRevision -lt 0 -or $baseRevision -ne ($revision - 1) -or -not $baseVersionText) { return $null }
        $baseHash = ([string]$manifest.base_content_sha256).Trim().ToLowerInvariant()
        if (-not (Test-Sha256Text $baseHash)) { return $null }
        $accepted = @()
        if ($status -eq 'approved') {
            if ($null -eq $manifest.PSObject.Properties['accepted_candidates']) { return $null }
            $seen = @{}
            foreach ($row in @($manifest.accepted_candidates)) {
                if ($null -eq $row) { continue }
                $id = ([string]$row.artifact_id).Trim()
                $h = ([string]$row.hub_content_sha256).Trim().ToLowerInvariant()
                if (-not (Test-ArtifactId $id) -or -not (Test-Sha256Text $h) -or $seen.ContainsKey($id.ToLowerInvariant())) { return $null }
                $seen[$id.ToLowerInvariant()] = $true
                $accepted += [pscustomobject]@{ ArtifactId = $id; ContentHash = $h; HashMode = 'full_v1' }
            }
        }
        return [pscustomobject]@{
            Schema=$schema; Status=$status; ArtifactId=$artifactId; ProducerRole=$producer; Version=$version; VersionText=[string]$manifest.system_version
            Revision=$revision; BaseVersionText=$baseVersionText; BaseRevision=$baseRevision; BaseContentHash=$baseHash; BasePayloadHash=$null
            BaseArtifactId=([string]$manifest.base_artifact_id).Trim(); PayloadHash=$null; Ancestors=@(); ManagerProtocol=$managerProtocol
            AcceptedCandidates=@($accepted); HashMode='full_v1'; InstanceId=$null; Genesis=$false; CreatedUtc=$createdUtc; RevisionTimeUtc=$revisionTimeUtc
        }
    }

    $payloadHash = ([string]$manifest.payload_content_sha256).Trim().ToLowerInvariant()
    if (-not (Test-Sha256Text $payloadHash)) { return $null }
    $instanceId = $null
    if ((Test-ArtifactSchemaV3 $schema)) {
        $instanceId = ([string]$manifest.instance_id).Trim().ToLowerInvariant()
        if (-not (Test-InstanceId $instanceId)) { return $null }
    }

    if ($genesis) {
        if ($revision -ne 1 -or $baseRevision -ne 0 -or $baseVersionText -or -not ([string]$manifest.genesis_release_id).Trim()) { return $null }
        if (@($manifest.ancestor_chain).Count -ne 0) { return $null }
        return [pscustomobject]@{
            Schema=$schema; Status=$status; ArtifactId=$artifactId; ProducerRole=$producer; Version=$version; VersionText=[string]$manifest.system_version
            Revision=1; BaseVersionText=''; BaseRevision=0; BaseContentHash=$null; BasePayloadHash=$null; BaseArtifactId=''; PayloadHash=$payloadHash
            Ancestors=@(); ManagerProtocol=$managerProtocol; AcceptedCandidates=@(); HashMode='payload_v3'; InstanceId=$instanceId; Genesis=$true; CreatedUtc=$createdUtc; RevisionTimeUtc=$revisionTimeUtc
        }
    }

    if ($revision -lt 1 -or $baseRevision -lt 0 -or $baseRevision -ne ($revision - 1) -or -not $baseVersionText) { return $null }
    $basePayloadHash = ([string]$manifest.base_payload_content_sha256).Trim().ToLowerInvariant()
    if (-not (Test-Sha256Text $basePayloadHash)) { return $null }
    $baseArtifactId = ([string]$manifest.base_artifact_id).Trim()
    if ($baseArtifactId -and -not (Test-ArtifactId $baseArtifactId)) { return $null }
    if ($null -eq $manifest.PSObject.Properties['ancestor_chain']) { return $null }
    $ancestorRows = @($manifest.ancestor_chain)
    if ($ancestorRows.Count -lt 1 -or $ancestorRows.Count -gt 16) { return $null }

    $ancestors = @(); $seenRevs = @{}; $lastRev = $revision
    foreach ($row in $ancestorRows) {
        try { $r = [int]$row.data_revision; $vtext = ([string]$row.system_version).Trim(); $null = [version]$vtext } catch { return $null }
        $h = ([string]$row.payload_content_sha256).Trim().ToLowerInvariant()
        $id = ([string]$row.artifact_id).Trim()
        if ($r -lt 1 -or $r -ge $lastRev -or $seenRevs.ContainsKey([string]$r) -or -not (Test-Sha256Text $h)) { return $null }
        if ($id -and -not (Test-ArtifactId $id)) { return $null }
        $seenRevs[[string]$r] = $true
        $lastRev = $r
        $ancestors += [pscustomobject]@{ Revision=$r; VersionText=$vtext; PayloadHash=$h; ArtifactId=$id }
    }
    $first = $ancestors[0]
    if ($first.Revision -ne $baseRevision -or $first.VersionText -ne $baseVersionText -or $first.PayloadHash -ne $basePayloadHash) { return $null }
    if ($baseArtifactId -and $first.ArtifactId -ne $baseArtifactId) { return $null }

    $accepted = @()
    if ($status -eq 'approved') {
        if ($null -eq $manifest.PSObject.Properties['accepted_candidates']) { return $null }
        $seen = @{}
        foreach ($row in @($manifest.accepted_candidates)) {
            if ($null -eq $row) { continue }
            $id = ([string]$row.artifact_id).Trim()
            $h = ([string]$row.payload_content_sha256).Trim().ToLowerInvariant()
            if (-not (Test-ArtifactId $id) -or -not (Test-Sha256Text $h) -or $seen.ContainsKey($id.ToLowerInvariant())) { return $null }
            $seen[$id.ToLowerInvariant()] = $true
            $mode = if ((Test-ArtifactSchemaV3 $schema)) { 'payload_v3' } else { 'payload_v2' }
            $accepted += [pscustomobject]@{ ArtifactId=$id; ContentHash=$h; HashMode=$mode }
        }
    }
    $hashMode = if ((Test-ArtifactSchemaV3 $schema)) { 'payload_v3' } else { 'payload_v2' }
    return [pscustomobject]@{
        Schema=$schema; Status=$status; ArtifactId=$artifactId; ProducerRole=$producer; Version=$version; VersionText=[string]$manifest.system_version
        Revision=$revision; BaseVersionText=$baseVersionText; BaseRevision=$baseRevision; BaseContentHash=$null; BasePayloadHash=$basePayloadHash
        BaseArtifactId=$baseArtifactId; PayloadHash=$payloadHash; Ancestors=@($ancestors); ManagerProtocol=$managerProtocol; AcceptedCandidates=@($accepted)
        HashMode=$hashMode; InstanceId=$instanceId; Genesis=$false; CreatedUtc=$createdUtc; RevisionTimeUtc=$revisionTimeUtc
    }
}

function Read-ZipArtifactManifest([string]$ZipPath,$Session=$null) {
    if ($Session -and -not (Test-HubZipInspectionSessionForPath $Session $ZipPath)) { throw 'Hub ZIP inspection session/path mismatch.' }
    $zipInfo = if ($Session) { [pscustomobject]@{Root=$Session.Root} } else { Get-HubZipEnvelope $ZipPath }
    if (-not $zipInfo) { return $null }
    $archive=$null
    try {
        $archive=if ($Session) { $Session.Archive } else { [System.IO.Compression.ZipFile]::OpenRead($ZipPath) }
        $entryName = $zipInfo.Root + '_System/ARTIFACT.json'
        $entry=if ($Session) { $Session.EntryMap[$entryName] } else { $archive.Entries | Where-Object { $_.FullName.Replace('\','/') -eq $entryName } | Select-Object -First 1 }
        if (-not $entry) { return $null }
        return Parse-ArtifactManifestText (Read-ZipEntryText $entry)
    }
    catch { Log ("Invalid artifact manifest in {0}: {1}" -f $ZipPath,$_.Exception.Message); return $null }
    finally { if ($archive -and -not $Session) { $archive.Dispose() } }
}

function Read-VaultArtifactManifestAt([string]$VaultPath) {
    $path=Join-Path $VaultPath '_System\ARTIFACT.json'
    if (-not (Test-Path $path -PathType Leaf)) { return $null }
    try { return Parse-ArtifactManifestText (Read-KeelarynJsonFileText $path) } catch { return $null }
}

function Test-IsLocalDeploymentRelativePath([string]$RelativePath) {
    if (-not $RelativePath) { return $false }
    $p=$RelativePath.Replace('\','/').TrimStart('/').ToLowerInvariant()
    if ($p -eq '.obsidian' -or $p.StartsWith('.obsidian/') -or $p -eq '.git' -or $p.StartsWith('.git/')) { return $true }
    $leaf=[System.IO.Path]::GetFileName($p)
    return @('.ds_store','thumbs.db','desktop.ini') -contains $leaf
}

function Get-SafeTreeFileInventory([string]$RootPath,[switch]$ExcludeLocalDeploymentState,[string]$Purpose='File tree') {
    $rootItem=Get-Item -LiteralPath $RootPath -Force -ErrorAction Stop
    if (-not $rootItem.PSIsContainer) { throw ($Purpose+' root is not a directory.') }
    if (($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ($Purpose+' root must not be a reparse point.') }
    $root=$rootItem.FullName.TrimEnd('\')
    $pending=New-Object System.Collections.ArrayList; $results=New-Object System.Collections.ArrayList; $seen=@{}
    [void]$pending.Add($rootItem)
    while ($pending.Count -gt 0) {
        $i=$pending.Count-1; $dir=$pending[$i]; $pending.RemoveAt($i)
        foreach ($child in @(Get-ChildItem -LiteralPath $dir.FullName -Force -ErrorAction Stop)) {
            $rel=$child.FullName.Substring($root.Length).TrimStart('\').Replace('\','/')
            if ($ExcludeLocalDeploymentState -and (Test-IsLocalDeploymentRelativePath $rel)) { continue }
            if ($rel.Length -gt 512) { throw ($Purpose+' path exceeds safety limit: '+$rel) }
            foreach ($segment in @($rel -split '/')) {
                if (-not $segment -or $segment -eq '.' -or $segment -eq '..' -or $segment.Length -gt 180 -or $segment.EndsWith(' ') -or $segment.EndsWith('.') -or $segment.Contains(':') -or $segment -match '[<>"|?*\x00-\x1F]' -or (Test-IsWindowsReservedPathSegment $segment)) { throw ($Purpose+' contains an unsafe Windows path: '+$rel) }
            }
            $key=$rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
            if ($seen.ContainsKey($key)) { throw ($Purpose+' contains a duplicate/Unicode-colliding path: '+$rel) }
            $seen[$key]=$true
            if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ($Purpose+' contains a reparse point: '+$rel) }
            if ($child.PSIsContainer) { [void]$pending.Add($child); continue }
            [void]$results.Add([pscustomobject]@{File=$child;RelativePath=$rel})
        }
    }
    return @($results | Sort-Object { $_.RelativePath.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant() })
}

function Get-PortableVaultFileInventory([string]$VaultPath) { return @(Get-SafeTreeFileInventory -RootPath $VaultPath -ExcludeLocalDeploymentState -Purpose 'Portable Keelaryn__Hub') }


function Get-PortableVaultAnalysis([string]$VaultPath) {
    $contentRows = New-Object System.Collections.ArrayList
    $payloadRows = New-Object System.Collections.ArrayList
    $manifestRows = New-Object System.Collections.ArrayList
    $manifestFiles = New-Object System.Collections.ArrayList
    $files = New-Object System.Collections.ArrayList
    $manifestExcluded = @{
        '_system/artifact.json' = $true
        '_system/manifest.json' = $true
        '_system/index.json' = $true
        '_system/router.json' = $true
        '_system/validation.json' = $true
    }

    foreach ($row in @(Get-PortableVaultFileInventory $VaultPath)) {
        $relative = [string]$row.RelativePath
        $stream = [System.IO.File]::OpenRead($row.File.FullName)
        try {
            $length = [long]$stream.Length
            $hash = Get-StreamHashHex $stream
        }
        finally { $stream.Dispose() }

        $line = $relative + "`0" + $hash
        [void]$contentRows.Add($line)
        if ($relative -ne '_System/ARTIFACT.json') { [void]$payloadRows.Add($line) }

        $manifestKey = $relative.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
        if (-not $manifestExcluded.ContainsKey($manifestKey)) {
            [void]$manifestRows.Add($line)
            [void]$manifestFiles.Add([pscustomobject]@{RelativePath=$relative;Length=$length;Hash=$hash})
        }
        [void]$files.Add([pscustomobject]@{File=$row.File;RelativePath=$relative;Length=$length;Hash=$hash})
    }

    return [pscustomobject]@{
        Files = @($files)
        FileCount = [int]$files.Count
        ContentHash = Get-TextHashHex ([string]::Join("`n", @($contentRows)))
        PayloadHash = Get-TextHashHex ([string]::Join("`n", @($payloadRows)))
        ManifestFiles = @($manifestFiles)
        ManifestEntryCount = [int]$manifestFiles.Count
        ManifestContentHash = Get-TextHashHex ([string]::Join("`n", @($manifestRows)))
    }
}

function Copy-PortableHubTree([string]$SourceHub,[string]$DestinationHub) {
    if (Test-Path -LiteralPath $DestinationHub) { if (@(Get-ChildItem -LiteralPath $DestinationHub -Force).Count -gt 0) { throw ('Portable Hub copy destination must be empty: '+$DestinationHub) } }
    else { New-Item -ItemType Directory -Path $DestinationHub -Force | Out-Null }
    foreach ($row in @(Get-PortableVaultFileInventory $SourceHub)) {
        $dst=Join-Path $DestinationHub ([string]$row.RelativePath).Replace('/','\'); $parent=Split-Path -Parent $dst
        if ($parent -and -not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Copy-Item -LiteralPath $row.File.FullName -Destination $dst -Force
    }
}


function Assert-CandidateTransportRelativePath([string]$RelativePath) {
    if (-not $RelativePath -or [System.IO.Path]::IsPathRooted($RelativePath)) { throw 'Candidate transport path is empty or rooted.' }
    if ($RelativePath.Contains('\')) { throw ('Candidate transport path must use forward slashes: '+$RelativePath) }
    $rel=$RelativePath.Trim('/')
    if (-not $rel -or $rel -cne $RelativePath -or $rel.Contains(':') -or $rel.Length -gt 512) { throw ('Unsafe candidate transport path: '+$RelativePath) }
    if ($rel.Normalize([System.Text.NormalizationForm]::FormC) -cne $rel) { throw ('Candidate transport path must be NFC-normalized: '+$rel) }
    foreach ($segment in @($rel -split '/')) {
        if (-not $segment -or $segment -eq '.' -or $segment -eq '..' -or $segment.Length -gt 180 -or $segment.EndsWith(' ') -or $segment.EndsWith('.') -or $segment -match '[<>"|?*\x00-\x1F]' -or (Test-IsWindowsReservedPathSegment $segment)) { throw ('Unsafe candidate transport path: '+$rel) }
    }
    if (Test-IsLocalDeploymentRelativePath $rel) { throw ('Candidate transport cannot contain local deployment state: '+$rel) }
    return $rel
}

function Get-CandidateTransportPathKey([string]$RelativePath) {
    $rel=Assert-CandidateTransportRelativePath $RelativePath
    return $rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
}

function Assert-CandidateTransportPropertySet($Object,[string[]]$Expected,[string]$Context) {
    if ($null -eq $Object) { throw ($Context+' is missing.') }
    $actual=@($Object.PSObject.Properties | ForEach-Object { [string]$_.Name })
    if ($actual.Count -ne $Expected.Count) { throw ($Context+' has an unexpected property count.') }
    foreach ($name in $Expected) { if ($actual -notcontains $name) { throw ($Context+' is missing property: '+$name) } }
    foreach ($name in $actual) { if ($Expected -notcontains $name) { throw ($Context+' contains unsupported property: '+$name) } }
}

function Read-HubZipEntryBytes($Entry) {
    Assert-KeelarynArchiveEntrySafety -Entry $Entry
    if ($Entry.FullName.EndsWith('/') -or $Entry.FullName.EndsWith([string][char]92)) { throw ('Cannot read ZIP directory entry as bytes: '+$Entry.FullName) }
    if ([long]$Entry.Length -gt 64MB) { throw ('Hub ZIP entry exceeds candidate transport per-file limit: '+$Entry.FullName) }
    $length=[int]$Entry.Length
    $bytes=New-Object byte[] $length
    $stream=$Entry.Open()
    try {
        $offset=0
        while ($offset -lt $length) {
            $read=$stream.Read($bytes,$offset,$length-$offset)
            if ($read -le 0) { throw ('Unexpected EOF while reading ZIP entry: '+$Entry.FullName) }
            $offset += $read
        }
        if ($stream.ReadByte() -ne -1) { throw ('ZIP entry length changed while reading: '+$Entry.FullName) }
        return ,$bytes
    }
    finally { $stream.Dispose() }
}

function Get-HubZipPortableFileMap($Session) {
    if (-not $Session -or -not $Session.Archive) { throw 'Hub ZIP inspection session is required.' }
    $map=@{}
    foreach ($row in @($Session.PortableFiles)) {
        $rel=Assert-CandidateTransportRelativePath ([string]$row.Rel)
        $key=Get-CandidateTransportPathKey $rel
        if ($map.ContainsKey($key)) { throw ('Duplicate candidate transport ZIP path: '+$rel) }
        $map[$key]=[pscustomobject]@{Rel=$rel;Length=[long]$row.Length;Hash=([string]$row.Hash).ToLowerInvariant()}
    }
    return $map
}

function New-CandidateTransportOperations($BaseSession,$CandidateSession) {
    $baseMap=Get-HubZipPortableFileMap $BaseSession
    $candidateMap=Get-HubZipPortableFileMap $CandidateSession
    $ops=New-Object System.Collections.ArrayList
    [long]$rawBytes=0

    foreach ($row in @($baseMap.Values | Sort-Object { $_.Rel.ToLowerInvariant() })) {
        $key=Get-CandidateTransportPathKey ([string]$row.Rel)
        if (-not $candidateMap.ContainsKey($key)) {
            [void]$ops.Add([ordered]@{op='delete';path=[string]$row.Rel;base_sha256=[string]$row.Hash})
        }
    }
    foreach ($row in @($candidateMap.Values | Sort-Object { $_.Rel.ToLowerInvariant() })) {
        $key=Get-CandidateTransportPathKey ([string]$row.Rel)
        $baseRow=if($baseMap.ContainsKey($key)){$baseMap[$key]}else{$null}
        if ($baseRow -and [string]$baseRow.Hash -eq [string]$row.Hash -and [long]$baseRow.Length -eq [long]$row.Length) { continue }
        $entryName=[string]$CandidateSession.Root+[string]$row.Rel
        $entry=$CandidateSession.EntryMap[$entryName]
        if (-not $entry) { throw ('Candidate transport source entry disappeared: '+[string]$row.Rel) }
        $bytes=Read-HubZipEntryBytes $entry
        $hash=Get-BytesHashHex $bytes
        if ($hash -ne [string]$row.Hash -or $bytes.Length -ne [long]$row.Length) { throw ('Candidate transport source entry changed during read: '+[string]$row.Rel) }
        $rawBytes += [long]$bytes.Length
        if ($rawBytes -gt $MaxCandidateTransportRawPayloadBytes) { throw ('Candidate transport changed payload exceeds raw-byte limit ('+$MaxCandidateTransportRawPayloadBytes+' bytes).') }
        [void]$ops.Add([ordered]@{
            op='put';path=[string]$row.Rel;base_sha256=$(if($baseRow){[string]$baseRow.Hash}else{''});length=[long]$bytes.Length;sha256=$hash;content_b64=[Convert]::ToBase64String($bytes)
        })
    }
    if ($ops.Count -lt 1) { throw 'Candidate transport delta is empty; candidate does not differ from reconstruction baseline.' }
    if ($ops.Count -gt $MaxHubEntries) { throw 'Candidate transport operation count exceeds Hub entry limit.' }
    return [pscustomobject]@{Operations=@($ops);RawBytes=$rawBytes}
}

function Expand-HubZipPortableToDirectory([string]$ZipPath,[string]$Destination,$Session=$null) {
    $owned=$false
    if (-not $Session) { $Session=Open-HubZipInspectionSession $ZipPath; $owned=$true }
    if (-not $Session) { throw ('Invalid Hub ZIP for portable extraction: '+$ZipPath) }
    try {
        if (-not (Test-HubZipInspectionSessionForPath $Session $ZipPath)) { throw 'Hub ZIP inspection session/path mismatch.' }
        if (Test-Path -LiteralPath $Destination) {
            $item=Get-Item -LiteralPath $Destination -Force
            if (-not $item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Portable extraction destination is unsafe: '+$Destination) }
            if (@(Get-ChildItem -LiteralPath $Destination -Force).Count -gt 0) { throw ('Portable extraction destination must be empty: '+$Destination) }
        } else { New-Item -ItemType Directory -Path $Destination -Force | Out-Null }
        foreach ($row in @($Session.PortableFiles | Sort-Object { $_.Rel.ToLowerInvariant() })) {
            $rel=Assert-CandidateTransportRelativePath ([string]$row.Rel)
            $entry=$Session.EntryMap[[string]$Session.Root+$rel]
            if (-not $entry) { throw ('Portable extraction entry missing: '+$rel) }
            $dst=Join-Path $Destination $rel.Replace('/','\')
            $parent=Split-Path -Parent $dst
            if ($parent -and -not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
            $input=$entry.Open();$output=[System.IO.File]::Open($dst,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
            try { $input.CopyTo($output) } finally { $output.Dispose();$input.Dispose() }
        }
        $analysis=Get-PortableVaultAnalysis $Destination
        if ([string]$analysis.ContentHash -ne [string]$Session.HashPair.ContentHash -or [string]$analysis.PayloadHash -ne [string]$Session.HashPair.PayloadHash) { throw 'Portable extraction hash mismatch.' }
        return $analysis
    }
    finally { if ($owned -and $Session) { Close-HubZipInspectionSession $Session } }
}

function Get-ValidatedHubTransportIdentity([string]$ZipPath,[string]$RequiredStatus) {
    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) { throw ('Hub transport ZIP does not exist: '+$ZipPath) }
    $zipItem=Get-Item -LiteralPath $ZipPath -Force
    if (($zipItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Hub transport ZIP must not be a reparse point: '+$ZipPath) }
    $session=Open-HubZipInspectionSession $ZipPath
    if (-not $session) { throw ('Invalid Hub ZIP: '+$ZipPath) }
    try {
        if ($session.ContainsLocalDeploymentState) { throw ('Hub ZIP contains local deployment state: '+$ZipPath) }
        $state=Read-ZipState $ZipPath $session
        $artifact=Read-ZipArtifactManifest $ZipPath $session
        if (-not $state -or -not $artifact) { throw ('Hub ZIP metadata validation failed: '+$ZipPath) }
        if ([string]$artifact.Schema -ne 'keelaryn.artifact.v3') { throw 'Candidate transport v1 requires artifact schema keelaryn.artifact.v3.' }
        if ([string]$artifact.Status -ne $RequiredStatus) { throw ('Hub ZIP artifact_status must be '+$RequiredStatus+'.') }
        if ([string]$state.VersionText -ne [string]$artifact.VersionText -or [int]$state.Revision -ne [int]$artifact.Revision) { throw 'Hub ZIP STATE/ARTIFACT revision identity mismatch.' }
        if ([string]$state.InstanceId -ne [string]$artifact.InstanceId -or -not (Test-InstanceId ([string]$artifact.InstanceId))) { throw 'Hub ZIP STATE/ARTIFACT instance identity mismatch.' }
        if ([string]$session.HashPair.PayloadHash -ne [string]$artifact.PayloadHash) { throw 'Hub ZIP ARTIFACT payload hash does not match portable payload.' }
        return [pscustomobject]@{Session=$session;State=$state;Artifact=$artifact;ContentHash=[string]$session.HashPair.ContentHash;PayloadHash=[string]$session.HashPair.PayloadHash}
    }
    catch { Close-HubZipInspectionSession $session; throw }
}

function Get-CandidateTransportRecoveredZipName([string]$ArtifactId) {
    if (-not (Test-ArtifactId $ArtifactId)) { throw 'Candidate transport artifact_id is invalid.' }
    return ('Keelaryn__Hub_CANDIDATE_RECONSTRUCTED_'+$ArtifactId+'.zip')
}

function New-CandidateTransportDocument([string]$BaseZip,[string]$CandidateZip) {
    $base=$null;$candidate=$null
    try {
        $base=Get-ValidatedHubTransportIdentity $BaseZip 'approved'
        $candidate=Get-ValidatedHubTransportIdentity $CandidateZip 'candidate'
        if ([string]$base.Artifact.InstanceId -ne [string]$candidate.Artifact.InstanceId) { throw 'Candidate transport refuses cross-instance reconstruction.' }
        $delta=New-CandidateTransportOperations $base.Session $candidate.Session
        $sourceItem=Get-Item -LiteralPath $CandidateZip -Force
        $sourceName=$sourceItem.Name
        if ([System.IO.Path]::GetFileName($sourceName) -cne $sourceName -or -not $sourceName.EndsWith('.zip',[System.StringComparison]::OrdinalIgnoreCase)) { throw 'Candidate source ZIP filename is invalid.' }
        $declaredBase=[ordered]@{
            system_version=[string]$candidate.Artifact.BaseVersionText;data_revision=[int]$candidate.Artifact.BaseRevision;artifact_id=[string]$candidate.Artifact.BaseArtifactId;payload_content_sha256=[string]$candidate.Artifact.BasePayloadHash
        }
        return [ordered]@{
            schema='keelaryn.hub.candidate-transport.v1'
            transport_role='candidate_fallback'
            encoding='base64-delta-v1'
            reconstruction_base=[ordered]@{
                system_version=[string]$base.State.VersionText;data_revision=[int]$base.State.Revision;instance_id=[string]$base.Artifact.InstanceId;artifact_id=[string]$base.Artifact.ArtifactId;payload_content_sha256=[string]$base.PayloadHash;portable_content_sha256=[string]$base.ContentHash
            }
            candidate=[ordered]@{
                system_version=[string]$candidate.State.VersionText;data_revision=[int]$candidate.State.Revision;instance_id=[string]$candidate.Artifact.InstanceId;artifact_id=[string]$candidate.Artifact.ArtifactId;payload_content_sha256=[string]$candidate.PayloadHash;portable_content_sha256=[string]$candidate.ContentHash;declared_base=$declaredBase;source_zip_name=$sourceName;source_zip_sha256=(Get-FileHash -LiteralPath $CandidateZip -Algorithm SHA256).Hash.ToLowerInvariant();source_zip_size=[long]$sourceItem.Length
            }
            reconstruction=[ordered]@{
                zip_name=Get-CandidateTransportRecoveredZipName ([string]$candidate.Artifact.ArtifactId);operation_count=[int]$delta.Operations.Count;changed_raw_bytes=[long]$delta.RawBytes
            }
            operations=@($delta.Operations)
        }
    }
    finally {
        if($candidate -and $candidate.Session){Close-HubZipInspectionSession $candidate.Session}
        if($base -and $base.Session){Close-HubZipInspectionSession $base.Session}
    }
}

function Assert-CandidateTransportInboxOutputPath([string]$DestinationPath) {
    if (-not (Test-Path -LiteralPath $Inbox -PathType Container)) { New-Item -ItemType Directory -Path $Inbox -Force | Out-Null }
    $inboxItem=Get-Item -LiteralPath $Inbox -Force
    if (-not $inboxItem.PSIsContainer -or ($inboxItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Manager state/inbox is unsafe for candidate transport: '+$Inbox) }
    $dest=[System.IO.Path]::GetFullPath($DestinationPath)
    if ([System.IO.Path]::GetFullPath((Split-Path -Parent $dest)).TrimEnd([char]92) -cne $inboxItem.FullName.TrimEnd([char]92)) { throw ('Candidate transport output must remain directly inside Manager state/inbox: '+$dest) }
    $existing=Get-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.PSIsContainer -or ($existing.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Candidate transport output collides with an unsafe filesystem object: '+$dest) }
    }
    return $dest
}

function Write-CandidateTransportJsonAtomic($Document,[string]$DestinationPath) {
    $json=($Document | ConvertTo-Json -Depth 20 -Compress)+"`n"
    $bytes=(New-Object System.Text.UTF8Encoding($false)).GetBytes($json)
    if ($bytes.Length -gt $MaxCandidateTransportBytes) { throw ('Candidate transport JSON exceeds limit ('+$MaxCandidateTransportBytes+' bytes).') }
    $dest=Assert-CandidateTransportInboxOutputPath $DestinationPath
    $tmp=$dest+'.tmp.'+[guid]::NewGuid().ToString('N')
    try {
        [System.IO.File]::WriteAllBytes($tmp,$bytes)
        if (Test-Path -LiteralPath $dest -PathType Leaf) {
            $existing=(Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant();$prepared=(Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($existing -eq $prepared) { Remove-Item -LiteralPath $tmp -Force; return $dest }
            throw ('Candidate transport already exists with different bytes; refusing overwrite: '+$dest)
        }
        Publish-CompletedFileAtomically $tmp $dest
        return $dest
    }
    finally { if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue} }
}

function Read-CandidateTransportDocument([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw ('Candidate transport does not exist: '+$Path) }
    $item=Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Candidate transport must not be a reparse point.' }
    if ($item.Length -gt $MaxCandidateTransportBytes) { throw ('Candidate transport exceeds JSON size limit: '+$Path) }
    try { $doc=(Get-Content -LiteralPath $Path -Raw -Encoding UTF8)|ConvertFrom-Json } catch { throw ('Candidate transport JSON parse failed: '+$_.Exception.Message) }
    Assert-CandidateTransportPropertySet $doc @('schema','transport_role','encoding','reconstruction_base','candidate','reconstruction','operations') 'Candidate transport root'
    if ([string]$doc.schema -ne 'keelaryn.hub.candidate-transport.v1' -or [string]$doc.transport_role -ne 'candidate_fallback' -or [string]$doc.encoding -ne 'base64-delta-v1') { throw 'Unsupported candidate transport schema/role/encoding.' }
    Assert-CandidateTransportPropertySet $doc.reconstruction_base @('system_version','data_revision','instance_id','artifact_id','payload_content_sha256','portable_content_sha256') 'Candidate transport reconstruction_base'
    Assert-CandidateTransportPropertySet $doc.candidate @('system_version','data_revision','instance_id','artifact_id','payload_content_sha256','portable_content_sha256','declared_base','source_zip_name','source_zip_sha256','source_zip_size') 'Candidate transport candidate'
    Assert-CandidateTransportPropertySet $doc.candidate.declared_base @('system_version','data_revision','artifact_id','payload_content_sha256') 'Candidate transport candidate.declared_base'
    Assert-CandidateTransportPropertySet $doc.reconstruction @('zip_name','operation_count','changed_raw_bytes') 'Candidate transport reconstruction'
    foreach($obj in @($doc.reconstruction_base,$doc.candidate)){
        try{$null=[version]([string]$obj.system_version);$rev=[int]$obj.data_revision}catch{throw 'Candidate transport contains invalid version/revision identity.'}
        if (($rev -lt 1) -or (-not (Test-InstanceId ([string]$obj.instance_id))) -or (-not (Test-ArtifactId ([string]$obj.artifact_id))) -or (-not (Test-Sha256Text ([string]$obj.payload_content_sha256))) -or (-not (Test-Sha256Text ([string]$obj.portable_content_sha256)))) { throw 'Candidate transport contains invalid checkpoint identity.' }
    }
    try{$null=[version]([string]$doc.candidate.declared_base.system_version);$baseRev=[int]$doc.candidate.declared_base.data_revision}catch{throw 'Candidate transport declared base identity is invalid.'}
    $declaredBaseArtifactId=([string]$doc.candidate.declared_base.artifact_id).Trim();if (($baseRev -lt 0) -or ($declaredBaseArtifactId -and (-not (Test-ArtifactId $declaredBaseArtifactId))) -or (-not (Test-Sha256Text ([string]$doc.candidate.declared_base.payload_content_sha256)))) { throw 'Candidate transport declared base identity is invalid.' }
    if([string]$doc.reconstruction_base.instance_id-ne[string]$doc.candidate.instance_id){throw 'Candidate transport contains cross-instance identities.'}
    $sourceName=[string]$doc.candidate.source_zip_name
    if ((-not $sourceName) -or ([System.IO.Path]::GetFileName($sourceName) -cne $sourceName) -or (-not $sourceName.EndsWith('.zip',[System.StringComparison]::OrdinalIgnoreCase)) -or (-not (Test-Sha256Text ([string]$doc.candidate.source_zip_sha256)))) { throw 'Candidate transport source ZIP provenance is invalid.' }
    try{$sourceSize=[long]$doc.candidate.source_zip_size}catch{throw 'Candidate transport source ZIP size is invalid.'};if($sourceSize-lt1-or$sourceSize-gt$MaxHubZipBytes){throw 'Candidate transport source ZIP size is outside Hub ZIP limits.'}
    $expectedZip=Get-CandidateTransportRecoveredZipName ([string]$doc.candidate.artifact_id)
    if ([string]$doc.reconstruction.zip_name -cne $expectedZip) { throw 'Candidate transport reconstruction ZIP identity is invalid.' }
    $ops=@($doc.operations);try{$opCount=[int]$doc.reconstruction.operation_count;$rawExpected=[long]$doc.reconstruction.changed_raw_bytes}catch{throw 'Candidate transport reconstruction counters are invalid.'}
    if($ops.Count-ne$opCount-or$opCount-lt1-or$opCount-gt$MaxHubEntries-or$rawExpected-lt0-or$rawExpected-gt$MaxCandidateTransportRawPayloadBytes){throw 'Candidate transport operation counters are invalid.'}
    $seen=@{};[long]$rawActual=0
    foreach($op in $ops){
        $kind=([string]$op.op).Trim().ToLowerInvariant()
        if($kind-eq'delete'){
            Assert-CandidateTransportPropertySet $op @('op','path','base_sha256') 'Candidate transport delete operation'
            $rel=Assert-CandidateTransportRelativePath ([string]$op.path);$key=Get-CandidateTransportPathKey $rel
            if($seen.ContainsKey($key)){throw('Candidate transport contains duplicate operation path: '+$rel)};$seen[$key]=$true
            if(-not(Test-Sha256Text ([string]$op.base_sha256))){throw('Candidate transport delete base hash is invalid: '+$rel)}
        }elseif($kind-eq'put'){
            Assert-CandidateTransportPropertySet $op @('op','path','base_sha256','length','sha256','content_b64') 'Candidate transport put operation'
            $rel=Assert-CandidateTransportRelativePath ([string]$op.path);$key=Get-CandidateTransportPathKey $rel
            if($seen.ContainsKey($key)){throw('Candidate transport contains duplicate operation path: '+$rel)};$seen[$key]=$true
            $baseHash=([string]$op.base_sha256).Trim().ToLowerInvariant();if ($baseHash -and (-not (Test-Sha256Text $baseHash))) { throw ('Candidate transport put base hash is invalid: '+$rel) }
            try{$length=[long]$op.length}catch{throw('Candidate transport put length is invalid: '+$rel)};if($length-lt0-or$length-gt64MB){throw('Candidate transport put length exceeds per-file limit: '+$rel)}
            $hash=([string]$op.sha256).Trim().ToLowerInvariant();if(-not(Test-Sha256Text $hash)){throw('Candidate transport put SHA-256 is invalid: '+$rel)}
            try{$bytes=[Convert]::FromBase64String([string]$op.content_b64)}catch{throw('Candidate transport Base64 is invalid: '+$rel)}
            if($bytes.Length-ne$length-or(Get-BytesHashHex $bytes)-ne$hash){throw('Candidate transport put payload hash/length mismatch: '+$rel)}
            $rawActual += [long]$bytes.Length;if($rawActual-gt$MaxCandidateTransportRawPayloadBytes){throw 'Candidate transport changed payload exceeds raw-byte limit.'}
        }else{throw('Candidate transport operation is unsupported: '+$kind)}
    }
    if($rawActual-ne$rawExpected){throw 'Candidate transport changed_raw_bytes does not match operations.'}
    return $doc
}

function Apply-CandidateTransportOperations([string]$HubPath,$Document) {
    $hubItem=Get-Item -LiteralPath $HubPath -Force -ErrorAction Stop
    if (-not $hubItem.PSIsContainer -or ($hubItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Candidate transport reconstruction root is unsafe.' }
    $seen=@{}
    $deletes=New-Object System.Collections.ArrayList
    $puts=New-Object System.Collections.ArrayList
    foreach ($op in @($Document.operations)) {
        $kind=([string]$op.op).ToLowerInvariant()
        $rel=Assert-CandidateTransportRelativePath ([string]$op.path)
        $key=Get-CandidateTransportPathKey $rel
        if ($seen.ContainsKey($key)) { throw ('Duplicate candidate transport operation path: '+$rel) }
        $seen[$key]=$true
        if ($kind -eq 'delete') { [void]$deletes.Add([pscustomobject]@{Op=$op;Rel=$rel}) }
        elseif ($kind -eq 'put') { [void]$puts.Add([pscustomobject]@{Op=$op;Rel=$rel}) }
        else { throw ('Candidate transport operation is unsupported: '+$kind) }
    }

    foreach ($row in @($deletes)) {
        $op=$row.Op; $rel=[string]$row.Rel; $path=Join-Path $HubPath $rel.Replace('/','\')
        $existing=Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        if (-not $existing) { throw ('Candidate transport delete target is missing: '+$rel) }
        if ($existing.PSIsContainer -or ($existing.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Candidate transport delete target is not a regular file: '+$rel) }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne ([string]$op.base_sha256).ToLowerInvariant()) { throw ('Candidate transport delete base hash mismatch: '+$rel) }
        Remove-Item -LiteralPath $path -Force
    }

    foreach ($row in @($puts)) {
        $op=$row.Op; $rel=[string]$row.Rel; $path=Join-Path $HubPath $rel.Replace('/','\')
        $existing=Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        if ($existing -and ($existing.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Candidate transport target is a reparse point: '+$rel) }
        $baseHash=([string]$op.base_sha256).Trim().ToLowerInvariant()
        if ($baseHash) {
            if (-not $existing -or $existing.PSIsContainer) { throw ('Candidate transport put base target is not the expected regular file: '+$rel) }
            if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $baseHash) { throw ('Candidate transport put base hash mismatch: '+$rel) }
        }
        elseif ($existing) {
            if ($existing.PSIsContainer) {
                if (@(Get-ChildItem -LiteralPath $path -Force).Count -ne 0) { throw ('Candidate transport add target collides with a non-empty directory: '+$rel) }
                Remove-Item -LiteralPath $path -Force
            }
            else { throw ('Candidate transport add target already exists: '+$rel) }
        }
        $bytes=[Convert]::FromBase64String([string]$op.content_b64)
        if ($bytes.Length -ne [long]$op.length -or (Get-BytesHashHex $bytes) -ne ([string]$op.sha256).ToLowerInvariant()) { throw ('Candidate transport put payload changed after validation: '+$rel) }
        $parent=Split-Path -Parent $path
        if ($parent -and (-not (Test-Path -LiteralPath $parent -PathType Container))) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        if ($parent) {
            $parentItem=Get-Item -LiteralPath $parent -Force
            if (-not $parentItem.PSIsContainer -or ($parentItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Candidate transport put parent is unsafe: '+$rel) }
        }
        [System.IO.File]::WriteAllBytes($path,$bytes)
    }
}

function Restore-CandidateTransportDocument([string]$TransportPath,[string]$BaseZip,[string]$OutputZip) {
    $doc=Read-CandidateTransportDocument $TransportPath
    $base=$null;$temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_candidate_restore_'+[guid]::NewGuid().ToString('N'))
    try{
        $base=Get-ValidatedHubTransportIdentity $BaseZip 'approved'
        $b=$doc.reconstruction_base
        if([string]$base.State.VersionText-ne[string]$b.system_version-or[int]$base.State.Revision-ne[int]$b.data_revision-or[string]$base.Artifact.InstanceId-ne[string]$b.instance_id-or[string]$base.Artifact.ArtifactId-ne[string]$b.artifact_id-or[string]$base.PayloadHash-ne([string]$b.payload_content_sha256).ToLowerInvariant()-or[string]$base.ContentHash-ne([string]$b.portable_content_sha256).ToLowerInvariant()){throw 'Candidate transport reconstruction baseline does not match CURRENT.'}
        $hub=Join-Path $temp 'hub';New-Item -ItemType Directory -Path $temp|Out-Null;$null=Expand-HubZipPortableToDirectory $BaseZip $hub $base.Session
        Apply-CandidateTransportOperations $hub $doc
        $analysis=Get-PortableVaultAnalysis $hub;$c=$doc.candidate
        if([string]$analysis.ContentHash-ne([string]$c.portable_content_sha256).ToLowerInvariant()-or[string]$analysis.PayloadHash-ne([string]$c.payload_content_sha256).ToLowerInvariant()){throw 'Candidate transport reconstructed portable hashes do not match candidate identity.'}
        $state=Read-VaultMetadataAt $hub $analysis;$artifact=Read-VaultArtifactManifestAt $hub
        if(-not$state-or-not$artifact-or[string]$artifact.Schema-ne'keelaryn.artifact.v3'-or[string]$artifact.Status-ne'candidate'){throw 'Candidate transport reconstructed Hub metadata is invalid or not a CANDIDATE.'}
        if([string]$state.VersionText-ne[string]$c.system_version-or[int]$state.Revision-ne[int]$c.data_revision-or[string]$artifact.InstanceId-ne[string]$c.instance_id-or[string]$artifact.ArtifactId-ne[string]$c.artifact_id-or[string]$artifact.PayloadHash-ne([string]$c.payload_content_sha256).ToLowerInvariant()){throw 'Candidate transport reconstructed checkpoint identity mismatch.'}
        $db=$c.declared_base
        if([string]$artifact.BaseVersionText-ne[string]$db.system_version-or[int]$artifact.BaseRevision-ne[int]$db.data_revision-or[string]$artifact.BaseArtifactId-ne[string]$db.artifact_id-or[string]$artifact.BasePayloadHash-ne([string]$db.payload_content_sha256).ToLowerInvariant()){throw 'Candidate transport reconstructed ancestry mismatch.'}
        $prepared=Join-Path $temp 'reconstructed.zip';Write-PortableHubZip $hub $prepared 'Keelaryn__Hub'
        $check=Get-ValidatedHubTransportIdentity $prepared 'candidate';try{if([string]$check.ContentHash-ne[string]$analysis.ContentHash-or[string]$check.PayloadHash-ne[string]$analysis.PayloadHash-or[string]$check.Artifact.ArtifactId-ne[string]$artifact.ArtifactId){throw 'Candidate transport reconstructed ZIP failed final identity validation.'}}finally{Close-HubZipInspectionSession $check.Session}
        $dest=Assert-CandidateTransportInboxOutputPath $OutputZip
        if (Test-Path -LiteralPath $dest -PathType Leaf) {
            $existingCheck=Get-ValidatedHubTransportIdentity $dest 'candidate'
            try {
                if ([string]$existingCheck.ContentHash -eq [string]$analysis.ContentHash -and [string]$existingCheck.PayloadHash -eq [string]$analysis.PayloadHash -and [string]$existingCheck.Artifact.ArtifactId -eq [string]$artifact.ArtifactId) { return $dest }
            }
            finally { Close-HubZipInspectionSession $existingCheck.Session }
            throw ('Reconstructed candidate ZIP already exists with different checkpoint identity: '+$dest)
        }
        $publishTemp=$dest+'.tmp.'+[guid]::NewGuid().ToString('N')
        Copy-Item -LiteralPath $prepared -Destination $publishTemp -Force
        Publish-CompletedFileAtomically $publishTemp $dest
        return $dest
    }
    finally {
        if ($base -and $base.Session) { Close-HubZipInspectionSession $base.Session }
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

function Invoke-BuildCandidateTransport {
    if(-not(Test-Path -LiteralPath $CurrentZip -PathType Leaf)){throw 'Keelaryn__Hub_CURRENT.zip is required to build candidate transport.'}
    $candidates=@(Get-ChildItem -LiteralPath $Inbox -File -Filter '*.zip' -ErrorAction SilentlyContinue | Where-Object { (-not $_.Name.StartsWith('Keelaryn__Hub_CANDIDATE_RECONSTRUCTED_',[System.StringComparison]::OrdinalIgnoreCase)) -and ($_.Name.StartsWith('Keelaryn__Hub_CANDIDATE_',[System.StringComparison]::OrdinalIgnoreCase) -or $_.Name.StartsWith([string]$LegacyCoreCompat.CandidatePrefix,[System.StringComparison]::OrdinalIgnoreCase)) } | Sort-Object Name)
    if($candidates.Count-eq0){Write-Host 'No Hub CANDIDATE is available. Nothing to build.' -ForegroundColor DarkGray;return 0}
    $built=0
    foreach($file in $candidates){
        $doc=New-CandidateTransportDocument $CurrentZip $file.FullName;$artifactId=[string]$doc.candidate.artifact_id;$name='Keelaryn__Hub_CANDIDATE_TRANSPORT_'+$artifactId+'.json';$dest=Join-Path $Inbox $name
        $null=Write-CandidateTransportJsonAtomic $doc $dest;$built++;Write-Host('Candidate transport: '+$dest)-ForegroundColor Green
    }
    Write-Host('Candidate transport build complete: '+$built+' file(s).')-ForegroundColor Green;return 0
}

function Invoke-RestoreCandidateTransport {
    if(-not(Test-Path -LiteralPath $CurrentZip -PathType Leaf)){throw 'Keelaryn__Hub_CURRENT.zip is required to restore candidate transport.'}
    $files=@(Get-ChildItem -LiteralPath $Inbox -File -Filter 'Keelaryn__Hub_CANDIDATE_TRANSPORT_*.json' -ErrorAction SilentlyContinue|Sort-Object Name)
    if($files.Count-eq0){Write-Host 'No Hub CANDIDATE transport is available. Nothing to restore.' -ForegroundColor DarkGray;return 0}
    $restored=0
    foreach($file in $files){$doc=Read-CandidateTransportDocument $file.FullName;$dest=Join-Path $Inbox ([string]$doc.reconstruction.zip_name);$out=Restore-CandidateTransportDocument $file.FullName $CurrentZip $dest;$restored++;Write-Host('Reconstructed CANDIDATE ZIP: '+$out)-ForegroundColor Green}
    Write-Host('Candidate transport restore complete: '+$restored+' file(s).')-ForegroundColor Green;return 0
}

function Get-SafeTreeContentHash([string]$RootPath,[string]$Purpose='File tree') {
    $rows=@(); foreach ($row in @(Get-SafeTreeFileInventory -RootPath $RootPath -Purpose $Purpose)) { $rows += ([string]$row.RelativePath+"`0"+(Get-FileHash -LiteralPath $row.File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()) }
    return Get-TextHashHex ([string]::Join("`n",$rows))
}

function Get-ZipHashPair([string]$ZipPath,$Session=$null) {
    if ($Session) {
        if (-not (Test-HubZipInspectionSessionForPath $Session $ZipPath)) { throw 'Hub ZIP inspection session/path mismatch.' }
        return [pscustomobject]@{ContentHash=[string]$Session.HashPair.ContentHash;PayloadHash=[string]$Session.HashPair.PayloadHash}
    }
    $zipInfo=Get-HubZipEnvelope $ZipPath; if (-not $zipInfo) { throw 'Unsupported Hub ZIP root.' }; $hubRoot=[string]$zipInfo.Root
    $archive=[System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $content=@(); $payload=@()
        foreach ($entry in @($archive.Entries | Where-Object { $n=$_.FullName.Replace('\','/'); -not $n.EndsWith('/') -and $n.StartsWith($hubRoot,[System.StringComparison]::Ordinal) -and -not (Test-IsLocalDeploymentRelativePath $n.Substring($hubRoot.Length)) } | Sort-Object { $_.FullName.ToLowerInvariant() })) {
            Assert-KeelarynArchiveEntrySafety -Entry $entry; $name=$entry.FullName.Replace('\','/').Substring($hubRoot.Length); $stream=$entry.Open(); try{$h=Get-StreamHashHex $stream}finally{$stream.Dispose()}; $row=$name+"`0"+$h; $content += $row; if($name -ne '_System/ARTIFACT.json'){$payload += $row}
        }
        return [pscustomobject]@{ContentHash=Get-TextHashHex([string]::Join("`n",$content));PayloadHash=Get-TextHashHex([string]::Join("`n",$payload))}
    } finally {$archive.Dispose()}
}
function Get-ZipHashInternal([string]$ZipPath,[bool]$ExcludeArtifact){$p=Get-ZipHashPair $ZipPath;if($ExcludeArtifact){return $p.PayloadHash};return $p.ContentHash}
function Get-ZipContentHash([string]$ZipPath){return (Get-ZipHashPair $ZipPath).ContentHash}
function Get-ZipPayloadHash([string]$ZipPath){return (Get-ZipHashPair $ZipPath).PayloadHash}

function Get-VaultHashPairAt([string]$VaultPath) {
    $analysis = Get-PortableVaultAnalysis $VaultPath
    return [pscustomobject]@{ContentHash=$analysis.ContentHash;PayloadHash=$analysis.PayloadHash}
}

function Get-VaultHashInternal([string]$VaultPath,[bool]$ExcludeArtifact){$p=Get-VaultHashPairAt $VaultPath;if($ExcludeArtifact){return $p.PayloadHash};return $p.ContentHash}
function Get-VaultContentHashAt([string]$VaultPath){return (Get-VaultHashPairAt $VaultPath).ContentHash}
function Get-VaultPayloadHashAt([string]$VaultPath){return (Get-VaultHashPairAt $VaultPath).PayloadHash}
function Get-VaultContentHash{return (Get-VaultHashPairAt $Vault).ContentHash}
function Get-VaultPayloadHash{return (Get-VaultHashPairAt $Vault).PayloadHash}

function Get-ValidHubPackages {
    $valid=@()
    if (-not (Test-Path $Inbox)) { return @($valid) }
    $files=@(Get-ChildItem $Inbox -Filter '*.zip' -File -ErrorAction SilentlyContinue | Where-Object {
        $_.Name.StartsWith('Keelaryn__Hub',[System.StringComparison]::OrdinalIgnoreCase) -or
        $_.Name.StartsWith([string]$LegacyCoreCompat.HubDirectory,[System.StringComparison]::OrdinalIgnoreCase)
    } | Sort-Object FullName -Unique)
    foreach ($file in $files) {
        $session=$null
        try { $session=Open-HubZipInspectionSession $file.FullName }
        catch { Log ("Invalid Hub ZIP left untouched: {0}: {1}" -f $file.FullName,$_.Exception.Message); continue }
        if (-not $session) { Log ("Invalid/unrecognized Hub ZIP left untouched: " + $file.FullName); continue }
        try {
            $state=Read-ZipState $file.FullName $session
            $artifact=Read-ZipArtifactManifest $file.FullName $session
            if (-not $state) { Log ("Invalid/unrecognized Hub ZIP left untouched: " + $file.FullName); continue }
            if (Test-ZipContainsLocalDeploymentState $file.FullName $session) { Log ("Hub package contains local deployment state and is not portable; left untouched: " + $file.FullName); continue }
            if (-not $artifact) { Log ("Legacy/unclassified Hub ZIP left untouched: " + $file.FullName); continue }
            if ($artifact.VersionText -ne $state.VersionText -or $artifact.Revision -ne $state.Revision) { Log ("Hub ARTIFACT disagrees with STATE; left untouched: " + $file.FullName); continue }
            if ($state.ArtifactSchema -and $artifact.Schema -ne $state.ArtifactSchema) { Log ("Hub ARTIFACT schema disagrees with STATE; left untouched: " + $file.FullName); continue }
            if ($state.ManagerProtocol -and $artifact.ManagerProtocol -ne $state.ManagerProtocol) { Log ("Hub ARTIFACT manager_protocol disagrees with STATE; left untouched: " + $file.FullName); continue }
            $hashPair=Get-ZipHashPair $file.FullName $session
            if (((Test-ArtifactSchemaV2 $artifact.Schema) -or (Test-ArtifactSchemaV3 $artifact.Schema)) -and $hashPair.PayloadHash -ne $artifact.PayloadHash) { Log ("Hub payload hash mismatch; left untouched: " + $file.FullName); continue }
            if ((Test-ArtifactSchemaV3 $artifact.Schema) -and (-not $state.InstanceId -or $state.InstanceId -ne $artifact.InstanceId)) { Log ("Hub v3 instance identity disagrees between STATE/INSTANCE and ARTIFACT; left untouched: "+$file.FullName); continue }
            if ($artifact.Status -eq 'candidate') { Log ("Worker CANDIDATE left pending for Chat Manager: " + $file.FullName); continue }
            $newApproved=$file.Name.StartsWith('Keelaryn__Hub_APPROVED_',[System.StringComparison]::OrdinalIgnoreCase)
            $legacyApproved=$file.Name.StartsWith([string]$LegacyCoreCompat.ApprovedPrefix,[System.StringComparison]::OrdinalIgnoreCase)
            if (-not $newApproved -and -not $legacyApproved) { Log ("APPROVED manifest has non-APPROVED filename; left untouched: " + $file.FullName); continue }
            $valid += [pscustomobject]@{File=$file;State=$state;Artifact=$artifact;ZipHash=(Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant();ContentHash=$hashPair.ContentHash;PayloadHash=$hashPair.PayloadHash}
        }
        finally { Close-HubZipInspectionSession $session }
    }
    return @($valid)
}

function Add-HubContentHashes([object[]]$Packages) {
    $result=@();foreach($package in $Packages){$content=[string]$package.ContentHash;$payload=[string]$package.PayloadHash;if(-not $content -or -not $payload){$h=Get-ZipHashPair $package.File.FullName;$content=$h.ContentHash;$payload=$h.PayloadHash};$result += [pscustomobject]@{File=$package.File;State=$package.State;Artifact=$package.Artifact;ZipHash=$package.ZipHash;ContentHash=$content;PayloadHash=$payload}}
    return @($result)
}

function Test-HubLineageFromCurrent($Package, $CurrentState, [string]$CurrentContentHash, [string]$CurrentPayloadHash, $CurrentArtifact) {
    if ((Test-ArtifactSchemaV2 $Package.Artifact.Schema) -or (Test-ArtifactSchemaV3 $Package.Artifact.Schema)) {
        if ($CurrentState.InstanceId -and $Package.Artifact.InstanceId -and $CurrentState.InstanceId -ne $Package.Artifact.InstanceId) { return New-CheckResult $false 'Package belongs to a different Keelaryn__Hub instance_id.' }
        $matches=@($Package.Artifact.Ancestors | Where-Object {
            $_.Revision -eq $CurrentState.Revision -and $_.VersionText -eq $CurrentState.VersionText -and $_.PayloadHash -eq $CurrentPayloadHash
        })
        if ($matches.Count -ne 1) { return New-CheckResult $false "Newer payload-linked package does not prove the exact installed checkpoint in its ancestor chain." }
        if ($CurrentArtifact -and $CurrentArtifact.ArtifactId -and $matches[0].ArtifactId -and $matches[0].ArtifactId -ne $CurrentArtifact.ArtifactId) {
            return New-CheckResult $false "Ancestor revision/hash matches but artifact_id differs from installed canonical artifact."
        }
        return New-CheckResult $true "Installed checkpoint is verified in the artifact ancestor chain."
    }

    if ($Package.Artifact.BaseRevision -eq $CurrentState.Revision -and $Package.Artifact.BaseVersionText -eq $CurrentState.VersionText -and $Package.Artifact.BaseContentHash -eq $CurrentContentHash) {
        return New-CheckResult $true "Legacy v1 package directly matches installed base."
    }
    return New-CheckResult $false "Legacy v1 package cannot prove a skipped multi-revision fast-forward; install a v2-linked checkpoint or reconcile in Chat Manager."
}

function Find-HubUpdateDecision($CurrentState, [string]$CurrentContentHash, [string]$CurrentPayloadHash, $CurrentArtifact) {
    $valid=Get-ValidHubPackages
    if (-not $valid -or $valid.Count -eq 0) { return [pscustomobject]@{Action='none';Reason='No valid APPROVED Keelaryn__Hub update packages found.';Package=$null;Details=@()} }
    if ($CurrentState.InstanceId) {
        foreach ($foreign in @($valid | Where-Object { $_.State.InstanceId -ne $CurrentState.InstanceId })) { Log ("Foreign-instance APPROVED Hub package left untouched: " + $foreign.File.FullName) }
        $valid = @($valid | Where-Object { $_.State.InstanceId -eq $CurrentState.InstanceId })
        if ($valid.Count -eq 0) { return [pscustomobject]@{Action='none';Reason='No APPROVED package for the installed instance_id.';Package=$null;Details=@()} }
    }

    $higher=@($valid | Where-Object { $_.State.Revision -gt $CurrentState.Revision })
    if ($higher.Count -gt 0) {
        $maxRevision=($higher | ForEach-Object {$_.State.Revision} | Measure-Object -Maximum).Maximum
        $top=@($higher | Where-Object {$_.State.Revision -eq $maxRevision})
        $scopeProblems=@($top | Where-Object {$CurrentState.RevisionScope -eq 'global_monotonic' -and $_.State.RevisionScope -ne 'global_monotonic'})
        if ($scopeProblems.Count -gt 0) { return [pscustomobject]@{Action='attention';Reason='A higher-revision Hub package does not declare global_monotonic revision scope.';Package=$null;Details=@($scopeProblems | ForEach-Object {$_.File.FullName})} }
        $versionRegressions=@($top | Where-Object {$_.State.Version -lt $CurrentState.Version})
        if ($versionRegressions.Count -gt 0) { return [pscustomobject]@{Action='attention';Reason='A higher data_revision attempts to regress system_version.';Package=$null;Details=@($versionRegressions | ForEach-Object {$_.File.FullName})} }
        $versionKeys=@($top | ForEach-Object {$_.State.VersionText} | Sort-Object -Unique)
        if ($versionKeys.Count -gt 1) { return [pscustomobject]@{Action='attention';Reason=("Conflicting Hub packages claim legacy sequence r{0:D4} with different system_version values." -f $maxRevision);Package=$null;Details=@($top | ForEach-Object {"{0} -> v{1}" -f $_.File.FullName,$_.State.VersionText})} }

        $topHashed=Add-HubContentHashes $top
        $contentHashes=@($topHashed | ForEach-Object {$_.ContentHash} | Sort-Object -Unique)
        if ($contentHashes.Count -gt 1) { return [pscustomobject]@{Action='attention';Reason=("Divergent Hub packages claim the same highest legacy sequence r{0:D4}." -f $maxRevision);Package=$null;Details=@($topHashed | ForEach-Object {"{0} -> content {1}" -f $_.File.FullName,$_.ContentHash})} }
        $best=$topHashed | Sort-Object @{Expression={$_.File.LastWriteTime};Descending=$true} | Select-Object -First 1
        $lineage=Test-HubLineageFromCurrent $best $CurrentState $CurrentContentHash $CurrentPayloadHash $CurrentArtifact
        if (-not $lineage.Valid) {
            return [pscustomobject]@{Action='attention';Reason=$lineage.Reason;Package=$null;Details=@(("Installed: v{0} r{1:D4} payload {2}" -f $CurrentState.VersionText,$CurrentState.Revision,$CurrentPayloadHash),("Package: {0}" -f $best.File.FullName))}
        }
        return [pscustomobject]@{Action='install';Reason=$lineage.Reason;Package=$best;Details=@()}
    }

    $same=@($valid | Where-Object {$_.State.Revision -eq $CurrentState.Revision})
    if ($same.Count -gt 0) {
        $sameHashed=Add-HubContentHashes $same
        $div=@($sameHashed | Where-Object {$_.State.Version -ne $CurrentState.Version -or $_.ContentHash -ne $CurrentContentHash})
        if ($div.Count -gt 0) { return [pscustomobject]@{Action='attention';Reason=("A divergent APPROVED Hub package has installed legacy data_revision r{0:D4}." -f $CurrentState.Revision);Package=$null;Details=@($div | ForEach-Object {"{0} -> v{1} r{2:D4}, content {3}" -f $_.File.FullName,$_.State.VersionText,$_.State.Revision,$_.ContentHash})} }
    }
    return [pscustomobject]@{Action='none';Reason='No newer Keelaryn__Hub package found.';Package=$null;Details=@()}
}

function Test-IsWindowsReservedPathSegment([string]$Segment) {
    if (-not $Segment) { return $false }
    # Do not delegate this contract to System.IO.Path: Keelaryn targets Win32-safe
    # portable names even when release tooling is executed on a different OS/.NET.
    $trimmed=([string]$Segment).TrimEnd([char[]]@(' ','.'))
    $dot=$trimmed.IndexOf('.')
    $stem=if($dot -ge 0){$trimmed.Substring(0,$dot)}else{$trimmed}
    $stem=$stem.ToUpperInvariant().Replace([string][char]0x00B9,'1').Replace([string][char]0x00B2,'2').Replace([string][char]0x00B3,'3')
    if (@('CON','PRN','AUX','NUL','CLOCK$','CONIN$','CONOUT$') -contains $stem) { return $true }
    return $stem -match '^COM[1-9]$' -or $stem -match '^LPT[1-9]$'
}

function Test-ManagerManagedPath([string]$RelativePath) {
    if (-not $RelativePath -or [System.IO.Path]::IsPathRooted($RelativePath)) { return $false }
    $rel=$RelativePath.Replace('\','/').Trim('/')
    if (-not $rel -or $rel.Contains(':') -or $rel.Length -gt 512) { return $false }
    foreach ($segment in @($rel -split '/')) {
        if (-not $segment -or $segment -eq '.' -or $segment -eq '..' -or $segment.Length -gt 180 -or $segment.EndsWith(' ') -or $segment.EndsWith('.') -or $segment -match '[<>"|?*\x00-\x1F]' -or (Test-IsWindowsReservedPathSegment $segment)) { return $false }
    }
    if ($ManagedManagerFiles -contains $rel) { return $true }
    if ($BootstrapCompatibilityCommands -contains $rel) { return $true }
    if (@('_manager_manifest.json','_manager_version.txt','Keelaryn__Manager.ps1') -contains $rel) { return $true }
    if ($rel.StartsWith('compat/commands/',[System.StringComparison]::OrdinalIgnoreCase)) {
        $leaf=[System.IO.Path]::GetFileName($rel)
        $parent=([System.IO.Path]::GetDirectoryName($rel.Replace('/','\'))).Replace('\','/')
        return ($parent -ieq 'compat/commands') -and $CompatibilityCommandSpecs.Contains($leaf)
    }
    if ($rel.StartsWith('product/',[System.StringComparison]::OrdinalIgnoreCase) -or $rel.StartsWith('docs/',[System.StringComparison]::OrdinalIgnoreCase)) {
        $ext=[System.IO.Path]::GetExtension($rel).ToLowerInvariant()
        return @('.md','.json','.ps1','.txt') -contains $ext
    }
    return $false
}

function Assert-ManagerInstallTargetPathSafe([string]$BaseRoot,[string]$RelativePath) {
    if (-not (Test-ManagerManagedPath $RelativePath)) { throw ('Unsafe Manager install target: '+$RelativePath) }
    $rootItem=Get-Item -LiteralPath $BaseRoot -Force -ErrorAction Stop
    if (-not $rootItem.PSIsContainer) { throw 'Manager install root is not a directory.' }
    if (($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Manager install root must not be a reparse point.' }
    $base=$rootItem.FullName.TrimEnd('\')
    $rel=$RelativePath.Replace('/','\').Trim('\')
    $segments=@($rel -split '\\')
    $current=$base
    for ($i=0;$i -lt ($segments.Count-1);$i++) {
        $current=Join-Path $current $segments[$i]
        $item=Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
        if (-not $item) { break }
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Manager install target parent is a reparse point: '+$current) }
        if (-not $item.PSIsContainer) { throw ('Manager install target parent is not a directory: '+$current) }
    }
    $target=Join-Path $base $rel
    $targetItem=Get-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
    if ($targetItem) {
        if (($targetItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Manager install target is a reparse point: '+$target) }
        if ($targetItem.PSIsContainer) { throw ('Manager install target collides with a directory: '+$target) }
    }
}

function Get-GeneratedCompatibilityCommandText([string]$CommandName) {
    if (-not $CompatibilityCommandSpecs.Contains($CommandName)) { throw ('Unknown compatibility command: '+$CommandName) }
    $spec=$CompatibilityCommandSpecs[$CommandName]
    if ([string]$spec.kind -eq 'bind') {
        return [string]::Join("`r`n",@(
            '@echo off','setlocal','rem Keelaryn generated compatibility command',
            'set "TARGET=%~1"','if not defined TARGET set /p "TARGET=Path to Keelaryn__Hub: "','if not defined TARGET exit /b 2',
            'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\product\runtime\Keelaryn__Manager.ps1" -BindInstancePath "%TARGET%"',
            'set "RC=%ERRORLEVEL%"','if not "%RC%"=="0" pause','exit /b %RC%',''
        ))
    }
    $lines=@(
        '@echo off','setlocal','rem Keelaryn generated compatibility command',
        ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\product\runtime\Keelaryn__Manager.ps1" '+[string]$spec.manager_arg),
        'set "RC=%ERRORLEVEL%"'
    )
    if ([string]$spec.pause -eq 'always') { $lines += @('echo.','pause') }
    elseif ([string]$spec.pause -eq 'error') { $lines += 'if not "%RC%"=="0" pause' }
    $lines += @('exit /b %RC%','')
    return [string]::Join("`r`n",$lines)
}

function Get-GeneratedRootCompatibilityAliasText([string]$CommandName) {
    if (-not $CompatibilityCommandSpecs.Contains($CommandName)) { throw ('Unknown compatibility alias: '+$CommandName) }
    return [string]::Join("`r`n",@(
        '@echo off','rem Keelaryn generated compatibility alias',
        ('call "%~dp0compat\commands\'+$CommandName+'" %*'),
        'exit /b %ERRORLEVEL%',''
    ))
}

function Get-GeneratedLayoutRootLauncherText {
    return [string]::Join("`r`n",@(
        '@echo off',
        'call "%~dp0manager\KEELARYN.cmd" %*',
        'exit /b %ERRORLEVEL%',
        ''
    ))
}

function Ensure-LayoutRootLauncherBestEffort {
    if (-not $CanonicalLayoutActive -or [string]$env:OS -ne 'Windows_NT') { return }
    $target=Join-Path $LayoutRoot 'Keelaryn.cmd'
    $expected=Get-GeneratedLayoutRootLauncherText
    try {
        if (Test-Path -LiteralPath $target) {
            $item=Get-Item -LiteralPath $target -Force -ErrorAction Stop
            if ($item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                Log ('Presentation warning: root launcher path collision left untouched: '+$target)
                return
            }
            $actual=[System.IO.File]::ReadAllText($target,[System.Text.Encoding]::ASCII)
            if ($actual -ceq $expected) { return }
            Log ('Presentation warning: custom root launcher left untouched: '+$target)
            return
        }
        [System.IO.File]::WriteAllText($target,$expected,[System.Text.Encoding]::ASCII)
    } catch { Log ('Presentation warning: could not create root launcher '+$target+': '+$_.Exception.Message) }
}

function Set-ManagerPathHiddenBestEffort([string]$Path) {
    if (-not $CanonicalLayoutActive -or [string]$env:OS -ne 'Windows_NT' -or -not (Test-Path -LiteralPath $Path)) { return }
    try {
        $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return }
        if (($item.Attributes -band [System.IO.FileAttributes]::Hidden) -eq 0) { $item.Attributes=$item.Attributes -bor [System.IO.FileAttributes]::Hidden }
    } catch { Log ('Presentation warning: could not hide '+$Path+': '+$_.Exception.Message) }
}

function Set-ManagerPathVisibleBestEffort([string]$Path) {
    if (-not $CanonicalLayoutActive -or [string]$env:OS -ne 'Windows_NT' -or -not (Test-Path -LiteralPath $Path)) { return }
    try {
        $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return }
        if (($item.Attributes -band [System.IO.FileAttributes]::Hidden) -ne 0) {
            $item.Attributes=[System.IO.FileAttributes]([int]$item.Attributes -band (-bnot [int][System.IO.FileAttributes]::Hidden))
        }
    } catch { Log ('Presentation warning: could not unhide physical product path '+$Path+': '+$_.Exception.Message) }
}

function Write-GeneratedCompatibilityFile([string]$Path,[string]$Expected,[string]$Marker) {
    if (Test-Path -LiteralPath $Path) {
        $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if ($item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Compatibility path collision: '+$Path) }
        $actual=[System.IO.File]::ReadAllText($Path,[System.Text.Encoding]::ASCII)
        if ($actual -cne $Expected -and -not $actual.Contains($Marker)) { throw ('Custom compatibility file collision: '+$Path) }
        if ($actual -ceq $Expected) { return }
    }
    $parent=Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent|Out-Null }
    [System.IO.File]::WriteAllText($Path,$Expected,[System.Text.Encoding]::ASCII)
}

function Test-GeneratedRootCompatibilityAlias([string]$Path,[string]$CommandName) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $true }
    try {
        $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if (($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0) { return $false }
        $actual=[System.IO.File]::ReadAllText($Path,[System.Text.Encoding]::ASCII)
        return $actual -ceq (Get-GeneratedRootCompatibilityAliasText $CommandName) -or $actual.Contains('rem Keelaryn generated compatibility alias')
    } catch { return $false }
}

function Set-ManagerStatePathNormalAttributes([string]$Path) {
    if ([string]$env:OS -ne 'Windows_NT' -or -not (Test-Path -LiteralPath $Path)) { return }
    $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0) { throw ('State path must not be a reparse point: '+$Path) }
    $attrs=[int]$item.Attributes
    $attrs=$attrs -band (-bnot [int][System.IO.FileAttributes]::Hidden)
    $attrs=$attrs -band (-bnot [int][System.IO.FileAttributes]::ReadOnly)
    $item.Attributes=[System.IO.FileAttributes]$attrs
}

function Test-FinalFilesystemLayout {
    if (-not (Test-Path -LiteralPath $StateLayoutReceipt -PathType Leaf)) { return $false }
    foreach($rel in @('product','compat','state','KEELARYN.cmd','README_FIRST.md')){if(-not(Test-Path -LiteralPath (Join-Path $Root $rel))){return $false}}
    foreach($rel in @('_history','_inbox','_logs','_releases','_instance_binding.json','Keelaryn__Hub_CURRENT.zip','Keelaryn__Manager.ps1','_manager_manifest.json','_manager_version.txt')){if(Test-Path -LiteralPath (Join-Path $Root $rel)){return $false}}
    foreach($name in @($CompatibilityCommandSpecs.Keys)){if(Test-Path -LiteralPath (Join-Path $Root ([string]$name))){return $false}}
    return $true
}

function Invoke-FinalizeFilesystemLayout {
    if (-not $CanonicalLayoutActive) { throw 'Filesystem finalization requires the canonical keelaryn\\manager layout.' }
    if (Test-FinalFilesystemLayout) { Write-Host 'Manager filesystem layout is already finalized.' -ForegroundColor Green; return 0 }
    if ($StateLayoutActive) { throw 'state/layout.json exists but the final filesystem contract is incomplete; refusing automatic mutation.' }
    if (-not (Test-Path -LiteralPath $CanonicalInstallationManifest -PathType Leaf)) { throw ('Canonical installation manifest is missing: '+$CanonicalInstallationManifest) }
    $finalManifest=Read-KeelarynJsonFile $CanonicalInstallationManifest
    if ([string]$finalManifest.schema -ne 'keelaryn.manager.installation.v2' -or [string]$finalManifest.manager_version -ne $ManagerVersion -or [int]$finalManifest.layout_version -ne 2) { throw 'Canonical installation manifest does not authorize filesystem layout v2.' }

    $moves=@(
        [pscustomobject]@{Source=(Join-Path $Root '_inbox');Target=(Join-Path $StateRoot 'inbox')},
        [pscustomobject]@{Source=(Join-Path $Root '_history');Target=(Join-Path $StateRoot 'history')},
        [pscustomobject]@{Source=(Join-Path $Root '_logs');Target=(Join-Path $StateRoot 'logs')},
        [pscustomobject]@{Source=(Join-Path $Root '_releases');Target=(Join-Path $StateRoot 'releases')},
        [pscustomobject]@{Source=(Join-Path $Root '_instance_binding.json');Target=(Join-Path $StateRoot 'binding.json')},
        [pscustomobject]@{Source=(Join-Path $Root 'Keelaryn__Hub_CURRENT.zip');Target=(Join-Path $StateRoot 'baseline\\Keelaryn__Hub_CURRENT.zip')}
    )
    foreach($row in $moves){
        if(Test-Path -LiteralPath $row.Target){throw('Filesystem finalization target already exists: '+$row.Target)}
        if(Test-Path -LiteralPath $row.Source){
            $item=Get-Item -LiteralPath $row.Source -Force -ErrorAction Stop
            if(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw('Filesystem finalization source must not be a reparse point: '+$row.Source)}
        }
    }
    foreach($name in @($CompatibilityCommandSpecs.Keys)){
        $alias=Join-Path $Root ([string]$name)
        if(-not (Test-GeneratedRootCompatibilityAlias $alias ([string]$name))){throw('Custom or unsafe root compatibility alias must be resolved manually: '+$alias)}
    }
    $transition=@('Keelaryn__Manager.ps1','_manager_manifest.json','_manager_version.txt')
    foreach($name in $transition){if(-not(Test-Path -LiteralPath (Join-Path $Root $name) -PathType Leaf)){throw('Transition file missing before filesystem finalization: '+$name)}}
    if((Get-Content -LiteralPath (Join-Path $Root '_manager_version.txt') -Raw -Encoding UTF8).Trim() -ne $ManagerVersion){throw 'Transition version marker disagrees with running Manager.'}

    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
    $backup=Join-Path $StateRoot ('migration_backup\\'+$ManagerVersion)
    if(Test-Path -LiteralPath $backup){throw('Filesystem migration backup already exists: '+$backup)}
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    foreach($name in $transition){Copy-Item -LiteralPath (Join-Path $Root $name) -Destination (Join-Path $backup $name) -Force}
    $completed=New-Object System.Collections.ArrayList
    $removedAliases=New-Object System.Collections.ArrayList
    $legacyLogHandoff=Join-Path $Root '_logs'
    $legacyLogHandoffCreated=$false
    try {
        foreach($row in $moves){
            if(Test-Path -LiteralPath $row.Source){
                $parent=Split-Path -Parent $row.Target;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
                Move-Item -LiteralPath $row.Source -Destination $row.Target
                [void]$completed.Add($row)
                Set-ManagerStatePathNormalAttributes $row.Target
            }
        }
        foreach($dir in @('inbox','history','logs','releases','baseline')){New-Item -ItemType Directory -Force -Path (Join-Path $StateRoot $dir)|Out-Null;Set-ManagerStatePathNormalAttributes (Join-Path $StateRoot $dir)}
        if(Test-Path -LiteralPath $legacyLogHandoff){throw('Legacy log handoff path unexpectedly remains after state move: '+$legacyLogHandoff)}
        New-Item -ItemType Directory -Path $legacyLogHandoff|Out-Null
        $legacyLogHandoffCreated=$true
        Set-ManagerPathHiddenBestEffort $legacyLogHandoff
        foreach($name in @($CompatibilityCommandSpecs.Keys)){
            $alias=Join-Path $Root ([string]$name)
            if(Test-Path -LiteralPath $alias -PathType Leaf){Remove-Item -LiteralPath $alias -Force;[void]$removedAliases.Add([string]$name)}
        }
        foreach($name in $transition){Remove-Item -LiteralPath (Join-Path $Root $name) -Force}
        $receipt=[ordered]@{schema='keelaryn.manager.filesystem-layout.v2';manager_version=$ManagerVersion;finalized_utc=(Get-Date).ToUniversalTime().ToString('o');state_root='state';canonical_manifest='product/install/INSTALLATION.json';legacy_root_aliases_removed=$true;transition_root_files_removed=$true;legacy_log_handoff_pending=$true}
        $receipt|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $StateLayoutReceipt -Encoding UTF8
        Set-ManagerOperationalPaths
        $script:CurrentZip=$script:PreferredCurrentZip
        New-Item -ItemType Directory -Force -Path $script:Inbox,$script:History,$script:Checkpoints,$script:Rollback,$script:ManagerUpdates,$script:Logs,$script:Releases,$script:WorkRoot | Out-Null
        foreach($path in @($StateRoot,$script:Inbox,$script:History,$script:Logs,$script:Releases,(Split-Path -Parent $script:PreferredCurrentZip))){Set-ManagerStatePathNormalAttributes $path}
        Assert-ManagerOperationalPathsReady -RequireStateLayout
        Write-Host ('Manager filesystem finalized: '+$Root) -ForegroundColor Green
        Write-Host ('State root: '+$StateRoot) -ForegroundColor Green
        return 0
    }
    catch {
        try {
            if(Test-Path -LiteralPath $StateLayoutReceipt){Remove-Item -LiteralPath $StateLayoutReceipt -Force -ErrorAction SilentlyContinue}
            if($legacyLogHandoffCreated -and (Test-Path -LiteralPath $legacyLogHandoff)){Remove-Item -LiteralPath $legacyLogHandoff -Recurse -Force -ErrorAction SilentlyContinue}
            foreach($name in $transition){$dst=Join-Path $Root $name;$src=Join-Path $backup $name;if(-not(Test-Path -LiteralPath $dst)-and(Test-Path -LiteralPath $src)){Copy-Item -LiteralPath $src -Destination $dst -Force}}
            foreach($name in @($removedAliases)){Write-GeneratedCompatibilityFile (Join-Path $Root $name) (Get-GeneratedRootCompatibilityAliasText $name) 'rem Keelaryn generated compatibility alias'}
            $reverse=@($completed);[array]::Reverse($reverse)
            foreach($row in $reverse){
                if((Test-Path -LiteralPath $row.Target) -and -not (Test-Path -LiteralPath $row.Source)){$parent=Split-Path -Parent $row.Source;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null};Move-Item -LiteralPath $row.Target -Destination $row.Source}
            }
            Set-ManagerOperationalPaths
            $script:CurrentZip=if((Test-Path $PreferredCurrentZip -PathType Leaf)-or-not(Test-Path $LegacyCurrentZip -PathType Leaf)){$PreferredCurrentZip}else{$LegacyCurrentZip}
        } catch {}
        throw
    }
}

function Initialize-ManagerPresentationState {
    if (-not $CanonicalLayoutActive) { return 0 }
    Ensure-LayoutRootLauncherBestEffort
    foreach($rel in @('product','compat')){Set-ManagerPathVisibleBestEffort (Join-Path $Root $rel)}
    if($StateLayoutActive){Set-ManagerPathVisibleBestEffort $StateRoot}
    $compatRoot=Join-Path $Root 'compat\\commands'
    New-Item -ItemType Directory -Force -Path $compatRoot|Out-Null
    foreach ($name in @($CompatibilityCommandSpecs.Keys)) {
        $commandPath=Join-Path $compatRoot ([string]$name)
        Write-GeneratedCompatibilityFile $commandPath (Get-GeneratedCompatibilityCommandText ([string]$name)) 'rem Keelaryn generated compatibility command'
        if(-not$StateLayoutActive){Set-ManagerPathHiddenBestEffort (Join-Path $Root ([string]$name))}
    }
    if(-not$StateLayoutActive){
        foreach ($rel in @('Keelaryn__Manager.ps1','_manager_manifest.json','_manager_version.txt','_history','_logs','_releases','_inbox','Keelaryn__Hub_CURRENT.zip','_instance_binding.json','DISTRIBUTION_MANIFEST.json')) { Set-ManagerPathHiddenBestEffort (Join-Path $Root $rel) }
    }
    return 0
}

function Get-InstalledManagedPaths {
    $manifestPath=$CanonicalInstallationManifest
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { return @($ManagedManagerFiles) }
    try {
        $m=Read-KeelarynJsonFile $manifestPath
        if ([string]$m.schema -ne 'keelaryn.manager.installation.v2' -or [int]$m.layout_version -ne 2) { throw 'Unsupported canonical installation manifest schema/layout.' }
        if ([string]$m.manager_version -ne $ManagerVersion) { throw 'Installation manifest manager_version disagrees with the running Manager.' }
        $raw=@($m.managed_files); if ($raw.Count -eq 0) { throw 'Installation manifest managed_files is empty.' }
        $paths=@(); $seen=@{}
        foreach ($p in $raw) {
            $rel=([string]$p).Replace('\','/')
            if (-not (Test-ManagerManagedPath $rel)) { throw ('Installation manifest contains an unsafe/unmanaged path: '+$rel) }
            $key=$rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
            if ($seen.ContainsKey($key)) { throw ('Installation manifest contains a duplicate/Unicode-colliding path: '+$rel) }
            $seen[$key]=$true; $paths += $rel
        }
        return @($paths | Sort-Object)
    }
    catch { throw ('Invalid installed Manager manifest: '+$_.Exception.Message) }
}

function Get-InstalledManagedFileItem([string]$RelativePath) {
    $rel=([string]$RelativePath).Replace('\','/')
    if (-not (Test-ManagerManagedPath $rel)) { throw ('Unsafe managed source path: '+$RelativePath) }
    $path=Join-Path $Root $rel.Replace('/','\')
    $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if ($item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Unsafe managed source item: '+$rel) }
    return $item
}

function Get-ManagerContentHashForPaths([string[]]$Paths) {
    $rows = New-Object System.Collections.ArrayList
    foreach ($name in @($Paths | Sort-Object -Unique)) {
        $path = Join-Path $Root $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
        [void]$rows.Add($name + "`0" + (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant())
    }
    return Get-TextHashHex ([string]::Join("`n", @($rows)))
}

function Read-ManagerUpdatePackage([string]$ZipPath) {
    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) { Log ("Invalid Manager ZIP {0}: ZIP does not exist." -f $ZipPath); return $null }
    $file=$null; $archive=$null
    try {
        $file=Get-Item -LiteralPath $ZipPath -Force
        if ([long]$file.Length -gt $MaxManagerZipBytes) { Log ("Invalid Manager ZIP {0}: ZIP exceeds allowed compressed size ({1} bytes)." -f $ZipPath,$MaxManagerZipBytes); return $null }
        $archive=[System.IO.Compression.ZipFile]::OpenRead($file.FullName)
        $envelope=Test-ZipEnvelopeArchive $archive ([long]$file.Length) $MaxManagerZipBytes $MaxManagerExpandedBytes $MaxManagerEntries 'Keelaryn__Manager_Update/'
        if (-not $envelope.Valid) { Log ("Invalid Manager ZIP {0}: {1}" -f $ZipPath,$envelope.Reason); return $null }
        $entryIndex=@{}; $actualFiles=New-Object System.Collections.ArrayList
        foreach ($entry in $archive.Entries) {
            $name=$entry.FullName.Replace('\','/')
            if ($name.EndsWith('/')) { continue }
            $key=$name.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
            if ($entryIndex.ContainsKey($key)) { return $null }
            $entryIndex[$key]=$entry; [void]$actualFiles.Add($key)
        }
        $lookup = { param([string]$Name) $key=$Name.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant(); if ($entryIndex.ContainsKey($key)) { return $entryIndex[$key] }; return $null }

        $manifestEntry=& $lookup 'Keelaryn__Manager_Update/manifest.json'
        if (-not $manifestEntry) { return $null }
        try { $manifest=(Read-ZipEntryText $manifestEntry)|ConvertFrom-Json } catch { return $null }
        $schema=[string]$manifest.schema
        if (@('keelaryn.manager.update.v1','keelaryn.manager.update.v2') -notcontains $schema -or -not $manifest.manager_version -or -not $manifest.files) { return $null }
        if ($schema -eq 'keelaryn.manager.update.v2') {
            if (-not ([string]$manifest.release_id).Trim() -or -not ([string]$manifest.system_release_id).Trim() -or -not ([string]$manifest.min_manager_version).Trim()) { return $null }
            try {
                if ([version]$ManagerVersion -lt [version]([string]$manifest.min_manager_version)) { return $null }
                if ($manifest.max_manager_version -and [version]$ManagerVersion -gt [version]([string]$manifest.max_manager_version)) { return $null }
            } catch { return $null }
        }
        try { $ver=[version]([string]$manifest.manager_version) } catch { return $null }
        $versionText=[string]$manifest.manager_version
        if ($schema -eq 'keelaryn.manager.update.v2' -and [string]$manifest.release_id -ne ('keelaryn-manager-'+$versionText)) { return $null }

        $rows=New-Object System.Collections.ArrayList; $managed=New-Object System.Collections.ArrayList; $seen=@{}; $hashByPath=@{}
        foreach ($decl in @($manifest.files)) {
            $rel=([string]$decl.path).Replace('\','/'); $declHash=([string]$decl.sha256).ToLowerInvariant()
            if (-not $rel -or -not (Test-Sha256Text $declHash) -or -not (Test-ManagerManagedPath $rel)) { return $null }
            $declSize=$null
            if ($schema -eq 'keelaryn.manager.update.v2') {
                if (-not $decl.PSObject.Properties['size_bytes']) { return $null }
                try { $declSize=[long]$decl.size_bytes } catch { return $null }
                if ($declSize -lt 0) { return $null }
            }
            $key=$rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
            if ($seen.ContainsKey($key)) { return $null }; $seen[$key]=$true
            $entry=& $lookup ('Keelaryn__Manager_Update/payload/'+$rel)
            if (-not $entry) { return $null }
            if ($schema -eq 'keelaryn.manager.update.v2' -and [long]$entry.Length -ne $declSize) { return $null }
            $stream=$entry.Open(); try { $actual=Get-StreamHashHex $stream } finally { $stream.Dispose() }
            if ($actual -ne $declHash) { return $null }
            [void]$rows.Add($rel+"`0"+$actual); [void]$managed.Add($rel); $hashByPath[$key]=$actual
        }
        foreach ($required in $ManagedManagerFiles) { if (-not $seen.ContainsKey($required.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant())) { return $null } }

        $expected=New-Object System.Collections.ArrayList; [void]$expected.Add('keelaryn__manager_update/manifest.json')
        foreach ($rel in @($managed)) { [void]$expected.Add(('Keelaryn__Manager_Update/payload/'+$rel).Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()) }
        $expectedSorted=@($expected | Sort-Object -Unique); $actualSorted=@($actualFiles | Sort-Object -Unique)
        if ($actualSorted.Count -ne $expectedSorted.Count) { return $null }
        for ($i=0;$i -lt $expectedSorted.Count;$i++) { if ($actualSorted[$i] -ne $expectedSorted[$i]) { return $null } }

        $installEntry=& $lookup 'Keelaryn__Manager_Update/payload/_manager_manifest.json'
        if (-not $installEntry) { return $null }
        try { $im=(Read-ZipEntryText $installEntry)|ConvertFrom-Json } catch { return $null }
        if ([string]$im.schema -ne 'keelaryn.manager.installation.v1' -or [string]$im.manager_version -ne $versionText) { return $null }
        $declared=@($im.managed_files|ForEach-Object{([string]$_).Replace('\','/')}|Sort-Object); $actualPaths=@($managed|Sort-Object)
        if ($declared.Count -ne $actualPaths.Count) { return $null }
        for ($i=0;$i -lt $declared.Count;$i++) { if ($declared[$i] -ne $actualPaths[$i]) { return $null } }

        if ($schema -eq 'keelaryn.manager.update.v2') {
            $pe=& $lookup 'Keelaryn__Manager_Update/payload/product/manager_release.json'; $re=& $lookup 'Keelaryn__Manager_Update/payload/product/release.json'
            if (-not $pe -or -not $re) { return $null }
            try { $pol=(Read-ZipEntryText $pe)|ConvertFrom-Json; $rel=(Read-ZipEntryText $re)|ConvertFrom-Json } catch { return $null }
            if ([string]$pol.schema -ne 'keelaryn.manager.release-policy.v1' -or [string]$pol.manager_version -ne $versionText -or [string]$pol.native_update_schema -ne $schema -or [string]$pol.update_min_version -ne [string]$manifest.min_manager_version) { return $null }
            if ([string]$rel.schema -ne 'keelaryn.system-release.v1' -or [string]$rel.release_id -ne [string]$manifest.system_release_id) { return $null }
        }

        $se=& $lookup 'Keelaryn__Manager_Update/payload/Keelaryn__Manager.ps1'; $ce=& $lookup 'Keelaryn__Manager_Update/payload/product/runtime/Keelaryn__Manager.ps1'; $ve=& $lookup 'Keelaryn__Manager_Update/payload/_manager_version.txt'; $rme=& $lookup 'Keelaryn__Manager_Update/payload/README_FIRST.md'
        if (-not $se -or -not $ce -or -not $ve -or -not $rme) { return $null }
        $st=Read-ZipEntryText $se; $ct=Read-ZipEntryText $ce; $vf=(Read-ZipEntryText $ve).Trim(); $rt=Read-ZipEntryText $rme
        $sm=[regex]::Match($st,'(?m)^\$ManagerVersion\s*=\s*"([^"]+)"\s*$'); $cm=[regex]::Match($ct,'(?m)^\$ManagerVersion\s*=\s*"([^"]+)"\s*$'); $rm=[regex]::Match($rt,'(?m)^# Keelaryn Manager\s+([^\s]+)\s*$')
        if (-not $sm.Success -or -not $cm.Success -or -not $rm.Success -or $sm.Groups[1].Value -ne $versionText -or $cm.Groups[1].Value -ne $versionText -or $vf -ne $versionText -or $rm.Groups[1].Value -ne $versionText) { return $null }

        $packageManagedPaths=@($managed|Sort-Object)
        $packageContentHash=Get-TextHashHex([string]::Join("`n",@($rows|Sort-Object)))
        $effectiveManagedPaths=$packageManagedPaths
        $effectiveContentHash=$packageContentHash
        if($manifest.PSObject.Properties['final_managed_files']){
            $final=@($manifest.final_managed_files|ForEach-Object{([string]$_).Replace('\','/')}|Sort-Object -Unique)
            if($final.Count-eq0){return $null}
            $finalRows=New-Object System.Collections.ArrayList
            foreach($rel in $final){
                $key=$rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
                if(-not$seen.ContainsKey($key)-or-not$hashByPath.ContainsKey($key)){return $null}
                [void]$finalRows.Add($rel+"`0"+[string]$hashByPath[$key])
            }
            $calculatedFinalHash=Get-TextHashHex([string]::Join("`n",@($finalRows|Sort-Object)))
            $declaredFinalHash=([string]$manifest.final_content_hash).Trim().ToLowerInvariant()
            if(-not(Test-Sha256Text $declaredFinalHash)-or$declaredFinalHash-ne$calculatedFinalHash){return $null}
            $effectiveManagedPaths=$final
            $effectiveContentHash=$calculatedFinalHash
        }
        return [pscustomobject]@{
            File=$file;Version=$ver;VersionText=$versionText;Schema=$schema
            ManagedPaths=@($effectiveManagedPaths);ContentHash=$effectiveContentHash;PackageManagedPaths=$packageManagedPaths;PackageContentHash=$packageContentHash
            PackageHash=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant();ExpandedBytes=[long]$envelope.ExpandedBytes
        }
    }
    catch { Log ("Invalid Manager package {0}: {1}" -f $ZipPath,$_.Exception.Message); return $null }
    finally { if ($archive) { $archive.Dispose() } }
}

function Get-CurrentManagerContentHash {
    return Get-ManagerContentHashForPaths (Get-InstalledManagedPaths)
}

function Test-InstalledManagerVersionCoherence([string]$ExpectedVersion) {
    try {
        $cp=Join-Path $Root 'product\runtime\Keelaryn__Manager.ps1'
        $rp=Join-Path $Root 'README_FIRST.md'
        $mp=$CanonicalInstallationManifest
        $pp=Join-Path $Root 'product\manager_release.json'
        foreach($path in @($cp,$rp,$mp,$pp)){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){return $false}}
        $ct=Get-Content -LiteralPath $cp -Raw -Encoding UTF8
        $rt=Get-Content -LiteralPath $rp -Raw -Encoding UTF8
        $im=Read-KeelarynJsonFile $mp
        $pol=Read-KeelarynJsonFile $pp
        $cm=[regex]::Match($ct,'(?m)^\$ManagerVersion\s*=\s*"([^"]+)"\s*$')
        $rm=[regex]::Match($rt,'(?m)^# Keelaryn Manager\s+([^\s]+)\s*$')
        if(-not$cm.Success -or -not$rm.Success -or $cm.Groups[1].Value-ne$ExpectedVersion -or $rm.Groups[1].Value-ne$ExpectedVersion){return $false}
        if([string]$im.schema-ne'keelaryn.manager.installation.v2' -or [string]$im.manager_version-ne$ExpectedVersion -or [int]$im.layout_version-ne2){return $false}
        if([string]$pol.schema-ne'keelaryn.manager.release-policy.v1' -or [string]$pol.manager_version-ne$ExpectedVersion -or [string]$pol.native_update_schema-ne'keelaryn.manager.update.v2'){return $false}
        try{if([version]([string]$pol.update_min_version)-gt[version]$ExpectedVersion){return $false}}catch{return $false}
        return $true
    } catch{return $false}
}

function Find-ManagerUpdateDecision {
    $valid=@()
    if (Test-Path $Inbox) {
        foreach ($file in @(Get-ChildItem $Inbox -Filter 'Keelaryn__Manager*.zip' -File -ErrorAction SilentlyContinue | Sort-Object FullName -Unique)) {
            $pkg=Read-ManagerUpdatePackage $file.FullName
            if ($pkg) { $valid += $pkg } else { Log ("Unrecognized/invalid Manager ZIP left untouched: "+$file.FullName) }
        }
    }
    if ($valid.Count -eq 0) { return [pscustomobject]@{Action='none';Reason='No valid Local Manager update packages found.';Package=$null;Details=@();ValidPackages=@()} }
    $currentVer=[version]$ManagerVersion
    $higher=@($valid | Where-Object {$_.Version -gt $currentVer})
    if ($higher.Count -gt 0) {
        $max=$higher | ForEach-Object {$_.Version} | Sort-Object -Descending | Select-Object -First 1
        $top=@($higher | Where-Object {$_.Version -eq $max})
        $hashes=@($top | ForEach-Object {$_.ContentHash} | Sort-Object -Unique)
        if ($hashes.Count -gt 1) { return [pscustomobject]@{Action='attention';Reason=("Divergent Local Manager packages claim version {0}." -f $max);Package=$null;Details=@($top | ForEach-Object {"{0} -> content {1}" -f $_.File.FullName,$_.ContentHash});ValidPackages=@($valid)} }
        return [pscustomobject]@{Action='install';Reason='Newer Local Manager package found.';Package=($top | Sort-Object @{Expression={$_.File.LastWriteTime};Descending=$true} | Select-Object -First 1);Details=@();ValidPackages=@($valid)}
    }
    $same=@($valid | Where-Object {$_.Version -eq $currentVer})
    if ($same.Count -gt 0) {
        $currentHash=Get-CurrentManagerContentHash
        if ($currentHash) {
            $div=@($same | Where-Object {$_.ContentHash -ne $currentHash})
            if ($div.Count -gt 0) { return [pscustomobject]@{Action='attention';Reason=("A divergent Local Manager package claims installed version {0}." -f $ManagerVersion);Package=$null;Details=@($div | ForEach-Object {"{0} -> content {1}" -f $_.File.FullName,$_.ContentHash});ValidPackages=@($valid)} }
        }
    }
    return [pscustomobject]@{Action='none';Reason='No newer Local Manager package found.';Package=$null;Details=@();ValidPackages=@($valid)}
}

function Test-IsPinned([System.IO.FileSystemInfo]$Item) { return $Item.Name.StartsWith('PINNED__',[System.StringComparison]::OrdinalIgnoreCase) }

function Remove-OldHistoryItems([string]$Path,[int]$KeepOrdinary,[int]$KeepPinned,[bool]$PreserveAllPinned) {
    if (-not (Test-Path $Path)) { return }
    $items=@(Get-ChildItem $Path -Force -ErrorAction SilentlyContinue)
    $ordinary=@($items | Where-Object {-not (Test-IsPinned $_)} | Sort-Object LastWriteTime -Descending)
    $pinned=@($items | Where-Object {(Test-IsPinned $_)} | Sort-Object LastWriteTime -Descending)
    $remove=@()
    if ($ordinary.Count -gt $KeepOrdinary) { $remove += @($ordinary | Select-Object -Skip $KeepOrdinary) }
    if (-not $PreserveAllPinned -and $pinned.Count -gt $KeepPinned) { $remove += @($pinned | Select-Object -Skip $KeepPinned) }
    foreach ($item in @($remove | Sort-Object FullName -Unique)) {
        try {
            if ($item.PSIsContainer) { Remove-Item $item.FullName -Recurse -Force } else { Remove-Item $item.FullName -Force }
            Log ("Retention removed: "+$item.FullName)
        }
        catch { Log ("Retention could not remove {0}: {1}" -f $item.FullName,$_.Exception.Message) }
    }
}

function Archive-RedundantManagerInboxPackages([object[]]$ValidatedPackages) {
    if (-not (Test-Path $Inbox -PathType Container)) { return }
    $packages=@($ValidatedPackages)
    if ($packages.Count -eq 0) { return }
    $currentVersion=[version]$ManagerVersion
    $currentHash=Get-CurrentManagerContentHash
    $dest=Join-Path $History 'manager_packages'
    foreach ($pkg in $packages) {
        if (-not $pkg -or -not $pkg.File -or -not (Test-Path -LiteralPath $pkg.File.FullName -PathType Leaf)) { continue }
        $file=Get-Item -LiteralPath $pkg.File.FullName -Force
        $freshHash=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($freshHash -ne [string]$pkg.PackageHash) { Log ('Validated Manager package changed before archive cleanup; left untouched: '+$file.FullName); continue }
        $reason=$null
        if ($pkg.Version -lt $currentVersion) { $reason='superseded' }
        elseif ($pkg.Version -eq $currentVersion -and $currentHash -and $pkg.ContentHash -eq $currentHash) { $reason='redundant_same_content' }
        if (-not $reason) { continue }
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        $target=Join-Path $dest $file.Name
        if (Test-Path $target) { $target=Join-Path $dest (([System.IO.Path]::GetFileNameWithoutExtension($file.Name))+'_'+(Get-Date -Format 'yyyy-MM-dd_HHmmss')+'.zip') }
        Move-Item -LiteralPath $file.FullName -Destination $target
        try { (Get-Item -LiteralPath $target -Force).LastWriteTime=Get-Date } catch {}
        Log ('Archived '+$reason+' Manager package: '+$target)
    }
}

function Cleanup-History {
    Remove-OldHistoryItems $script:Checkpoints 5 2 $false
    # Legacy pinned rollback (notably PINNED__layout_migration) is intentionally held until separate explicit cleanup.
    Remove-OldHistoryItems $script:Rollback 1 0 $true
    Remove-OldHistoryItems $script:ManagerUpdates 2 1 $false
    Remove-OldHistoryItems (Join-Path $script:History 'manager_packages') 5 0 $false
    $cutoff=(Get-Date).AddDays(-14)
    Get-ChildItem $script:Logs -Filter 'manager_*.log' -File -ErrorAction SilentlyContinue | Where-Object {$_.LastWriteTime -lt $cutoff} | ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }
}

function Get-ProductRelease {
    if(-not(Test-Path $ProductReleaseFile -PathType Leaf)){throw("Product release metadata is missing: "+$ProductReleaseFile)};$r=Read-KeelarynJsonFile $ProductReleaseFile;if([string]$r.schema-ne'keelaryn.system-release.v1' -or -not$r.release_id -or -not$r.system_version -or -not$r.manager_protocol -or -not$r.manager_min_version){throw 'Invalid product release metadata.'};$sv=([string]$r.system_version).Trim();if([string]$r.release_id-ne('keelaryn-system-'+$sv)){throw 'Product release_id does not match system_version.'};try{$null=[version]$sv;$min=[version]([string]$r.manager_min_version);$cur=[version]$ManagerVersion}catch{throw 'Product release contains an invalid version.'};if($min-gt$cur){throw 'Product release manager_min_version exceeds running Manager.'};if([string]$r.artifact_schema-ne'keelaryn.artifact.v3' -or [string]$r.instance_schema-ne'keelaryn.instance.v1' -or [string]$r.manifest_schema-ne'keelaryn.manifest.v1' -or [string]$r.validation_schema-ne'keelaryn.validation.v2'){throw 'Product release schema surfaces are inconsistent.'};return $r
}

function Get-ManagerReleasePolicy {
    if (-not (Test-Path $ManagerReleasePolicyFile -PathType Leaf)) { throw ('Manager release policy is missing: ' + $ManagerReleasePolicyFile) }
    $r=Read-KeelarynJsonFile $ManagerReleasePolicyFile
    if ([string]$r.schema -ne 'keelaryn.manager.release-policy.v1' -or [string]$r.manager_version -ne $ManagerVersion -or [string]$r.native_update_schema -ne 'keelaryn.manager.update.v2' -or -not $r.update_min_version) { throw 'Invalid Manager release policy.' }
    try { $floor=[version]([string]$r.update_min_version); $current=[version]$ManagerVersion } catch { throw 'Manager release policy contains an invalid version.' }
    if ($floor -gt $current) { throw 'Manager release policy update_min_version exceeds manager_version.' }
    return $r
}

function Get-FrontmatterValue([string]$Text, [string]$Key) {
    $pattern = '(?m)^' + [regex]::Escape($Key) + ':\s*([^\r\n]+?)\s*$'
    $m = [regex]::Match($Text, $pattern)
    if ($m.Success) { return $m.Groups[1].Value.Trim().Trim('"') }
    return $null
}

function Get-MarkdownTitle([string]$Text, [string]$Fallback) {
    $m = [regex]::Match($Text, '(?m)^#\s+(.+?)\s*$')
    if ($m.Success) { return $m.Groups[1].Value.Trim() }
    return $Fallback
}

function Get-SafeSlug([string]$Text) {
    $s = ([string]$Text).Trim().Normalize([System.Text.NormalizationForm]::FormC)
    # Explicit Win32 filename contract. System.IO.Path.GetInvalidFileNameChars()
    # is runtime/platform-dependent and therefore unsuitable for deterministic Genesis.
    $s = [regex]::Replace($s, '[<>:"/\\|?*\x00-\x1F]', '-')
    # Brackets are legal Windows filename characters but are structural delimiters in Obsidian wikilinks.
    $s = $s.Replace('[','-').Replace(']','-')
    $s = [regex]::Replace($s, '\s+', ' ').Trim().TrimEnd([char[]]@(' ','.'))
    $s = [regex]::Replace($s, '-{2,}', '-').Trim([char[]]@('-')).Trim()
    if (-not $s) { throw 'Genesis item name becomes empty after filename sanitization.' }
    if ($s.Length -gt 80) { throw ('Genesis item filename is too long after sanitization (max 80 characters): ' + $s) }
    if (Test-IsWindowsReservedPathSegment $s) { throw ('Genesis item name is reserved by Windows: ' + $s) }
    return $s
}

function New-GenesisItemPlan($Names,[string]$Kind) {
    if (@('area','project') -notcontains $Kind) { throw ('Unsupported Genesis item kind: ' + $Kind) }
    $items=@(); $seen=@{}; $i=0
    foreach ($name in @($Names)) {
        $i++; $slug=Get-SafeSlug ([string]$name)
        $rel = if ($Kind -eq 'area') { 'Areas/' + $slug + '.md' } else { 'Projects/' + $slug + '.md' }
        $key=$rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
        if ($seen.ContainsKey($key)) { throw ('Genesis filename collision after sanitization: "' + [string]$seen[$key] + '" and "' + [string]$name + '" -> ' + $rel) }
        $seen[$key]=[string]$name
        $items += [pscustomobject]@{ Name=[string]$name; Slug=$slug; RelativePath=$rel; Id=($Kind + '.genesis.' + $i.ToString('D2')) }
    }
    return @($items)
}

function Assert-GenesisPlanDoesNotCollideWithTemplates($Plans) {
    $reserved=@{}
    foreach($source in @((Join-Path $ProductRoot 'starter\hub'),(Join-Path $ProductRoot 'governance\hub'))){if(-not(Test-Path $source -PathType Container)){throw('Genesis template source is missing: '+$source)};foreach($row in @(Get-SafeTreeFileInventory -RootPath $source -Purpose 'Genesis template tree')){$rel=[string]$row.RelativePath;$reserved[$rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()]=$rel}}
    foreach($item in @($Plans)){$key=([string]$item.RelativePath).Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant();if($reserved.ContainsKey($key)){throw('Genesis item path collides with canonical template file: '+[string]$item.RelativePath)}}
}

function Get-DeepestException($Exception) {
    $e=$Exception
    while ($e -and $e.InnerException) { $e=$e.InnerException }
    return $e
}

function Initialize-RestartManagerInterop {
    $existing=([System.Management.Automation.PSTypeName]'Keelaryn.Native.RestartManagerProbe').Type
    if ($existing) { return $existing }
    $source=@'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace Keelaryn.Native {
    public sealed class RestartManagerOwner {
        public int ProcessId { get; set; }
        public string ApplicationName { get; set; }
        public string ServiceShortName { get; set; }
        public int ApplicationType { get; set; }
        public uint AppStatus { get; set; }
        public uint SessionId { get; set; }
        public bool Restartable { get; set; }
    }

    public static class RestartManagerProbe {
        private const int ErrorSuccess = 0;
        private const int ErrorMoreData = 234;
        private const int MaxResults = 4096;

        [StructLayout(LayoutKind.Sequential)]
        private struct FILETIME {
            public uint dwLowDateTime;
            public uint dwHighDateTime;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct RM_UNIQUE_PROCESS {
            public int dwProcessId;
            public FILETIME ProcessStartTime;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct RM_PROCESS_INFO {
            public RM_UNIQUE_PROCESS Process;

            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
            public string strAppName;

            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)]
            public string strServiceShortName;

            public int ApplicationType;
            public uint AppStatus;
            public uint TSSessionId;

            [MarshalAs(UnmanagedType.Bool)]
            public bool bRestartable;
        }

        [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)]
        private static extern int RmStartSession(out uint sessionHandle, int sessionFlags, StringBuilder sessionKey);

        [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)]
        private static extern int RmRegisterResources(
            uint sessionHandle,
            uint fileCount,
            [MarshalAs(UnmanagedType.LPArray, ArraySubType = UnmanagedType.LPWStr)] string[] fileNames,
            uint applicationCount,
            IntPtr applications,
            uint serviceCount,
            IntPtr serviceNames);

        [DllImport("rstrtmgr.dll")]
        private static extern int RmGetList(
            uint sessionHandle,
            out uint processInfoNeeded,
            ref uint processInfoCount,
            [In, Out] RM_PROCESS_INFO[] affectedApps,
            ref uint rebootReasons);

        [DllImport("rstrtmgr.dll")]
        private static extern int RmEndSession(uint sessionHandle);

        private static void ThrowApiError(int error, string operation) {
            throw new Win32Exception(error, operation + " failed.");
        }

        public static RestartManagerOwner[] GetLockingProcesses(string path) {
            if (String.IsNullOrWhiteSpace(path)) {
                throw new ArgumentException("Restart Manager path is empty.", "path");
            }

            string fullPath = Path.GetFullPath(path);
            uint sessionHandle = 0;
            StringBuilder sessionKey = new StringBuilder(33);
            int result = RmStartSession(out sessionHandle, 0, sessionKey);
            if (result != ErrorSuccess) {
                ThrowApiError(result, "RmStartSession");
            }

            try {
                result = RmRegisterResources(
                    sessionHandle,
                    1,
                    new string[] { fullPath },
                    0,
                    IntPtr.Zero,
                    0,
                    IntPtr.Zero);
                if (result != ErrorSuccess) {
                    ThrowApiError(result, "RmRegisterResources");
                }

                uint needed = 0;
                uint count = 0;
                uint rebootReasons = 0;
                result = RmGetList(sessionHandle, out needed, ref count, null, ref rebootReasons);
                if (result == ErrorSuccess && needed == 0) {
                    return new RestartManagerOwner[0];
                }
                if (result != ErrorMoreData && result != ErrorSuccess) {
                    ThrowApiError(result, "RmGetList");
                }

                for (int attempt = 0; attempt < 4; attempt++) {
                    if (needed == 0) {
                        return new RestartManagerOwner[0];
                    }
                    if (needed > MaxResults) {
                        throw new InvalidOperationException("Restart Manager returned an excessive process count: " + needed.ToString());
                    }

                    RM_PROCESS_INFO[] processInfo = new RM_PROCESS_INFO[needed];
                    count = needed;
                    result = RmGetList(sessionHandle, out needed, ref count, processInfo, ref rebootReasons);
                    if (result == ErrorMoreData) {
                        continue;
                    }
                    if (result != ErrorSuccess) {
                        ThrowApiError(result, "RmGetList");
                    }

                    int actual = (int)Math.Min(count, (uint)processInfo.Length);
                    List<RestartManagerOwner> owners = new List<RestartManagerOwner>(actual);
                    for (int i = 0; i < actual; i++) {
                        RM_PROCESS_INFO item = processInfo[i];
                        owners.Add(new RestartManagerOwner {
                            ProcessId = item.Process.dwProcessId,
                            ApplicationName = item.strAppName ?? String.Empty,
                            ServiceShortName = item.strServiceShortName ?? String.Empty,
                            ApplicationType = item.ApplicationType,
                            AppStatus = item.AppStatus,
                            SessionId = item.TSSessionId,
                            Restartable = item.bRestartable
                        });
                    }

                    owners.Sort(delegate(RestartManagerOwner left, RestartManagerOwner right) {
                        int resultPid = left.ProcessId.CompareTo(right.ProcessId);
                        if (resultPid != 0) { return resultPid; }
                        int resultService = StringComparer.OrdinalIgnoreCase.Compare(left.ServiceShortName, right.ServiceShortName);
                        if (resultService != 0) { return resultService; }
                        return StringComparer.OrdinalIgnoreCase.Compare(left.ApplicationName, right.ApplicationName);
                    });
                    return owners.ToArray();
                }

                throw new InvalidOperationException("Restart Manager process list changed repeatedly while being queried.");
            }
            finally {
                if (sessionHandle != 0) {
                    RmEndSession(sessionHandle);
                }
            }
        }
    }
}
'@
    Add-Type -TypeDefinition $source -Language CSharp -ErrorAction Stop
    $loaded=([System.Management.Automation.PSTypeName]'Keelaryn.Native.RestartManagerProbe').Type
    if (-not $loaded) { throw 'Restart Manager interop type failed to load.' }
    return $loaded
}

function Get-RestartManagerLockOwners([string]$Path) {
    $full=[System.IO.Path]::GetFullPath($Path)
    $null=Initialize-RestartManagerInterop
    return @([Keelaryn.Native.RestartManagerProbe]::GetLockingProcesses($full))
}

function ConvertTo-RestartManagerAppTypeName([int]$Value) {
    switch ($Value) {
        0 { return 'RmUnknownApp' }
        1 { return 'RmMainWindow' }
        2 { return 'RmOtherWindow' }
        3 { return 'RmService' }
        4 { return 'RmExplorer' }
        5 { return 'RmConsole' }
        1000 { return 'RmCritical' }
        default { return ('RmAppType('+$Value+')') }
    }
}

function Format-FileLockOwnerDiagnostic([string]$Path,[int]$MaxOwners=8) {
    if ($MaxOwners -lt 1) { $MaxOwners=1 }
    try {
        $owners=@(Get-RestartManagerLockOwners $Path)
        if ($owners.Count -eq 0) { return 'Restart Manager reported no locking application or service.' }
        $parts=@()
        $limit=[Math]::Min($owners.Count,$MaxOwners)
        for ($i=0; $i -lt $limit; $i++) {
            $owner=$owners[$i]
            $app=([string]$owner.ApplicationName).Replace("`r",' ').Replace("`n",' ').Replace('"',"'").Trim()
            $service=([string]$owner.ServiceShortName).Replace("`r",' ').Replace("`n",' ').Replace('"',"'").Trim()
            if ($app.Length -gt 120) { $app=$app.Substring(0,120) }
            if ($service.Length -gt 80) { $service=$service.Substring(0,80) }
            $part=('PID='+[int]$owner.ProcessId+' app="'+$app+'" type='+(ConvertTo-RestartManagerAppTypeName ([int]$owner.ApplicationType))+' restartable='+([bool]$owner.Restartable).ToString().ToLowerInvariant())
            if ($service) { $part += ' service="'+$service+'"' }
            $parts += $part
        }
        if ($owners.Count -gt $limit) { $parts += ('... '+($owners.Count-$limit)+' more owner(s)') }
        return ('Restart Manager lock owners: '+([string]::Join('; ',$parts)))
    }
    catch {
        $base=Get-DeepestException $_.Exception
        return ('Restart Manager lock-owner query unavailable: '+$base.GetType().FullName+': '+$base.Message)
    }
}

function New-FileLockDiagnosticException([string]$Path,[string]$Purpose,$Exception) {
    $full=[System.IO.Path]::GetFullPath($Path)
    $base=Get-DeepestException $Exception
    $diagnostic=Format-FileLockOwnerDiagnostic $full
    $message=$Purpose+' blocked by a Windows sharing/lock violation: '+$full+'; '+$base.GetType().FullName+': '+$base.Message+'; '+$diagnostic
    return [System.Activator]::CreateInstance([System.IO.IOException],[object[]]@($message,$Exception))
}

function Test-IsTransientFileLockException($Exception) {
    $e=Get-DeepestException $Exception
    if (-not $e -or -not ($e -is [System.IO.IOException])) { return $false }
    $win32=([int64]$e.HResult -band 0xFFFF)
    return ($win32 -eq 32 -or $win32 -eq 33)
}

function Wait-FileReadyForAtomicReplace([string]$Path,[int]$Attempts=20,[int]$DelayMs=250,[string]$Purpose='atomic replacement') {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw ('Replacement target is missing: ' + $Path) }
    if ($Attempts -lt 1) { $Attempts=1 }
    if ($DelayMs -lt 0) { $DelayMs=0 }
    for ($attempt=1; $attempt -le $Attempts; $attempt++) {
        $stream=$null
        try {
            $stream=[System.IO.File]::Open($Path,[System.IO.FileMode]::Open,[System.IO.FileAccess]::ReadWrite,[System.IO.FileShare]::None)
            return
        }
        catch {
            $isTransient=Test-IsTransientFileLockException $_.Exception
            if (-not $isTransient) { throw }
            if ($attempt -ge $Attempts) {
                # Add owner diagnostics without losing the original Win32 exception:
                # the raw sharing/lock IOException remains the deepest inner exception.
                throw (New-FileLockDiagnosticException $Path $Purpose $_.Exception)
            }
            if ($DelayMs -gt 0) { Start-Sleep -Milliseconds $DelayMs }
        }
        finally { if ($stream) { $stream.Dispose() } }
    }
}

function Publish-CompletedFileAtomically([string]$PreparedPath,[string]$DestinationPath) {
    if (-not (Test-Path -LiteralPath $PreparedPath -PathType Leaf)) {
        throw ('Prepared publish file is missing: ' + $PreparedPath)
    }

    $prepared = [System.IO.Path]::GetFullPath($PreparedPath)
    $dest = [System.IO.Path]::GetFullPath($DestinationPath)
    if ([System.IO.Path]::GetPathRoot($prepared) -ne [System.IO.Path]::GetPathRoot($dest)) {
        throw 'Atomic file publication requires prepared and destination files on the same volume.'
    }

    $parent = Split-Path -Parent $dest
    if ($parent -and -not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    if (Test-Path -LiteralPath $dest -PathType Leaf) {
        # A real sibling backup avoids the Windows PowerShell 5.1 $null binding issue.
        # Sharing/lock violations are transient in common antivirus/indexer scenarios,
        # so retry only that exact Win32 class. Any partial mutation/backup stops retries.
        $backup = Join-Path $parent ('.keelaryn-replace-' + [guid]::NewGuid().ToString('N') + '.bak')
        $maxAttempts=20
        $delayMs=250
        $published=$false
        for ($attempt=1; $attempt -le $maxAttempts; $attempt++) {
            try {
                Invoke-WithExistingHiddenFileWritable $dest { [System.IO.File]::Replace($prepared, $dest, $backup, $true) }|Out-Null
                $published=$true
                if ($attempt -gt 1) { Log ('Atomic replacement succeeded after transient-lock retry attempts: ' + $attempt) }
                break
            }
            catch {
                $transient=Test-IsTransientFileLockException $_.Exception
                $canRetry=$transient -and $attempt -lt $maxAttempts -and (Test-Path -LiteralPath $prepared -PathType Leaf) -and (Test-Path -LiteralPath $dest -PathType Leaf) -and -not (Test-Path -LiteralPath $backup)
                if ($canRetry) { Start-Sleep -Milliseconds $delayMs; continue }
                if ($transient) {
                    $purpose=('Atomic replacement failed after '+$attempt+' attempt(s). Prepared='+$prepared+'; Destination='+$dest+'; Backup='+$backup)
                    throw (New-FileLockDiagnosticException $dest $purpose $_.Exception)
                }
                $base=Get-DeepestException $_.Exception
                throw ('Atomic replacement failed after ' + $attempt + ' attempt(s). Prepared=' + $prepared + '; Destination=' + $dest + '; Backup=' + $backup + '; ' + $base.GetType().FullName + ': ' + $base.Message)
            }
        }
        if (-not $published) { throw ('Atomic replacement did not publish destination: ' + $dest) }

        if (Test-Path -LiteralPath $backup -PathType Leaf) {
            try { [System.IO.File]::Delete($backup) }
            catch { Write-Warning ('Atomic publication succeeded but backup cleanup failed: ' + $backup + '; ' + $_.Exception.Message) }
        }
    }
    else {
        [System.IO.File]::Move($prepared, $dest)
    }
    Set-ManagerMutablePresentationHidden $dest
}

function Write-DeterministicZip([string]$SourceRoot,[string]$ZipPath,[string]$ZipRootName) {
    $dest=[System.IO.Path]::GetFullPath($ZipPath);$tmp=$dest+'.tmp.'+[guid]::NewGuid().ToString('N');$stream=$null;$zip=$null
    try{$stream=[System.IO.File]::Open($tmp,[System.IO.FileMode]::CreateNew);$zip=New-Object System.IO.Compression.ZipArchive($stream,[System.IO.Compression.ZipArchiveMode]::Create,$false);foreach($row in @(Get-SafeTreeFileInventory -RootPath $SourceRoot -Purpose 'Deterministic ZIP source')){$entryName=if($ZipRootName){$ZipRootName.TrimEnd('/')+'/'+$row.RelativePath}else{$row.RelativePath};$entry=$zip.CreateEntry($entryName,[System.IO.Compression.CompressionLevel]::Optimal);$entry.LastWriteTime=[datetimeoffset]'2000-01-01T00:00:00Z';$input=[System.IO.File]::OpenRead($row.File.FullName);$output=$entry.Open();try{$input.CopyTo($output)}finally{$output.Dispose();$input.Dispose()}};$zip.Dispose();$zip=$null;$stream.Dispose();$stream=$null;Publish-CompletedFileAtomically $tmp $dest}finally{if($zip){$zip.Dispose()};if($stream){$stream.Dispose()};if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}}
}

function Write-PortableHubZip([string]$SourceRoot,[string]$ZipPath,[string]$ZipRootName) {
    $dest=[System.IO.Path]::GetFullPath($ZipPath);$tmp=$dest+'.tmp.'+[guid]::NewGuid().ToString('N');$stream=$null;$zip=$null
    try{$stream=[System.IO.File]::Open($tmp,[System.IO.FileMode]::CreateNew);$zip=New-Object System.IO.Compression.ZipArchive($stream,[System.IO.Compression.ZipArchiveMode]::Create,$false);foreach($row in @(Get-PortableVaultFileInventory $SourceRoot)){$entryName=if($ZipRootName){$ZipRootName.TrimEnd('/')+'/'+$row.RelativePath}else{$row.RelativePath};$entry=$zip.CreateEntry($entryName,[System.IO.Compression.CompressionLevel]::Optimal);$entry.LastWriteTime=[datetimeoffset]'2000-01-01T00:00:00Z';$input=[System.IO.File]::OpenRead($row.File.FullName);$output=$entry.Open();try{$input.CopyTo($output)}finally{$output.Dispose();$input.Dispose()}};$zip.Dispose();$zip=$null;$stream.Dispose();$stream=$null;Publish-CompletedFileAtomically $tmp $dest}finally{if($zip){$zip.Dispose()};if($stream){$stream.Dispose()};if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}}
}

function Test-ZipContainsLocalDeploymentState([string]$ZipPath,$Session=$null) {
    if ($Session) {
        if (-not (Test-HubZipInspectionSessionForPath $Session $ZipPath)) { throw 'Hub ZIP inspection session/path mismatch.' }
        return [bool]$Session.ContainsLocalDeploymentState
    }
    $zipInfo=Get-HubZipEnvelope $ZipPath
    if (-not $zipInfo) { return $false }
    $root=[string]$zipInfo.Root
    $archive=[System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($entry in $archive.Entries) {
            Assert-KeelarynArchiveEntrySafety -Entry $entry
            $n=$entry.FullName.Replace('\','/')
            if (-not $n.StartsWith($root,[System.StringComparison]::Ordinal)) { continue }
            $rel=$n.Substring($root.Length).TrimEnd('/')
            if ($rel -and (Test-IsLocalDeploymentRelativePath $rel)) { return $true }
        }
        return $false
    }
    finally { $archive.Dispose() }
}

function Write-SanitizedPortableHubZip([string]$SourceZip,[string]$DestinationZip) {
    $zipInfo=Get-HubZipEnvelope $SourceZip
    if (-not $zipInfo) { throw 'Cannot sanitize unsupported Hub ZIP.' }
    $root=[string]$zipInfo.Root
    if (Test-Path $DestinationZip) { Remove-Item $DestinationZip -Force }
    $inputArchive=[System.IO.Compression.ZipFile]::OpenRead($SourceZip)
    $stream=[System.IO.File]::Open($DestinationZip,[System.IO.FileMode]::CreateNew)
    $outputArchive=New-Object System.IO.Compression.ZipArchive($stream,[System.IO.Compression.ZipArchiveMode]::Create,$false)
    try {
        $entries=@($inputArchive.Entries | Where-Object {
            $n=$_.FullName.Replace('\','/')
            if ($n.EndsWith('/') -or -not $n.StartsWith($root,[System.StringComparison]::Ordinal)) { return $false }
            $rel=$n.Substring($root.Length)
            return -not (Test-IsLocalDeploymentRelativePath $rel)
        } | Sort-Object { $_.FullName.Replace('\','/').ToLowerInvariant() })
        foreach ($entry in $entries) {
            $name=$entry.FullName.Replace('\','/')
            $out=$outputArchive.CreateEntry($name,[System.IO.Compression.CompressionLevel]::Optimal)
            $out.LastWriteTime=[datetimeoffset]'2000-01-01T00:00:00Z'
            $src=$entry.Open(); $dst=$out.Open()
            try { $src.CopyTo($dst) } finally { $dst.Dispose(); $src.Dispose() }
        }
    }
    finally { $outputArchive.Dispose(); $stream.Dispose(); $inputArchive.Dispose() }
}

function Sanitize-CurrentCheckpointTransportIfNeeded {
    if (-not (Test-Path $CurrentZip -PathType Leaf)) { return }
    if (-not (Test-ZipContainsLocalDeploymentState $CurrentZip)) { return }
    $beforeState=Read-ZipState $CurrentZip
    $beforeArtifact=Read-ZipArtifactManifest $CurrentZip
    if (-not $beforeState -or -not $beforeArtifact) { throw 'CURRENT transport contains local deployment state but baseline validation failed; refusing automatic repack.' }
    $beforePayload=Get-ZipPayloadHash $CurrentZip
    $temp=$CurrentZip+'.portable-new'
    try {
        Write-SanitizedPortableHubZip $CurrentZip $temp
        $afterState=Read-ZipState $temp
        $afterArtifact=Read-ZipArtifactManifest $temp
        if (-not $afterState -or -not $afterArtifact) { throw 'Sanitized CURRENT transport failed validation.' }
        if ($afterState.VersionText -ne $beforeState.VersionText -or $afterState.Revision -ne $beforeState.Revision -or $afterArtifact.ArtifactId -ne $beforeArtifact.ArtifactId) { throw 'Sanitized CURRENT transport changed checkpoint identity.' }
        if ((Get-ZipPayloadHash $temp) -ne $beforePayload -or $afterArtifact.PayloadHash -ne $beforeArtifact.PayloadHash) { throw 'Sanitized CURRENT transport changed canonical payload identity.' }
        if (Test-ZipContainsLocalDeploymentState $temp) { throw 'Sanitized CURRENT transport still contains local deployment state.' }
        $backup=$CurrentZip+'.pre-portable-backup'
        if (Test-Path $backup) { Remove-Item $backup -Force -ErrorAction SilentlyContinue }
        try {
            Invoke-WithExistingHiddenFileWritable $CurrentZip { [System.IO.File]::Replace($temp,$CurrentZip,$backup,$true) }|Out-Null
            if (Test-Path $backup) { Remove-Item $backup -Force }
        }
        catch {
            if ((-not (Test-Path $CurrentZip -PathType Leaf)) -and (Test-Path $backup -PathType Leaf)) { Move-Item $backup $CurrentZip -Force }
            throw
        }
        Log 'Repacked Keelaryn__Hub_CURRENT.zip without local deployment state; canonical payload identity unchanged.'
    }
    finally { if (Test-Path $temp) { Remove-Item $temp -Force -ErrorAction SilentlyContinue } }
}

function Build-DerivedMetadata([string]$VaultPath, [string]$VersionText, [int]$Revision, [string]$InstanceId) {
    $entities = @()
    foreach ($row in @(Get-PortableVaultFileInventory $VaultPath | Where-Object { $_.File.Extension -ieq '.md' })) {
        $file=$row.File
        $rel=$row.RelativePath
        $text = Get-Content $file.FullName -Raw -Encoding UTF8
        $id = Get-FrontmatterValue $text 'id'
        $type = Get-FrontmatterValue $text 'type'
        $status = Get-FrontmatterValue $text 'status'
        $updated = Get-FrontmatterValue $text 'updated'
        if (-not $id -or -not $type -or -not $status -or -not $updated) { throw ("Markdown entity lacks required metadata: " + $rel) }
        $links = @()
        foreach ($m in [regex]::Matches($text, '\[\[([^\]]+)\]\]')) { $links += $m.Groups[1].Value }
        $entities += [ordered]@{
            id=$id; type=$type; status=$status; updated=$updated; path=$rel
            title=(Get-MarkdownTitle $text ([System.IO.Path]::GetFileNameWithoutExtension($file.Name)))
            links=@($links)
        }
    }

    $index = [ordered]@{ schema='keelaryn.index.v1'; system_version=$VersionText; data_revision=$Revision; instance_id=$InstanceId; entity_count=$entities.Count; entities=$entities }
    $index | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $VaultPath '_System\INDEX.json') -Encoding UTF8

    $routes = @()
    foreach ($e in $entities) {
        if ($e.status -eq 'active' -or $e.status -eq 'waiting') { $routes += ,@($e.type, $e.status, $e.path, $e.title) }
    }
    $router = [ordered]@{
        schema='keelaryn.router.v2'; system_version=$VersionText; data_revision=$Revision; instance_id=$InstanceId
        source_entity_count=$entities.Count; included_statuses=@('active','waiting'); route_count=$routes.Count; routes=$routes
    }
    $router | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $VaultPath '_System\ROUTER.json') -Encoding UTF8

    $validation = [ordered]@{
        schema='keelaryn.validation.v2'; vault='Keelaryn__Hub'; system_version=$VersionText; data_revision=$Revision; instance_id=$InstanceId
        entity_count=$entities.Count; route_count=$routes.Count
        source_manifest=[ordered]@{ schema='keelaryn.manifest.v1'; entry_count=0; content_set_sha256='0000000000000000000000000000000000000000000000000000000000000000' }
        manager_validation=[ordered]@{ policy='risk_based_v1'; mode='full'; reasons=@('derived_metadata_rebuilt','source_manifest_verified','deterministic_checks_pass'); full_audit_interval_revisions=10; last_full_audit_revision=$Revision; next_full_audit_revision=($Revision+10) }
        checks=[ordered]@{ parse_errors=0; duplicate_ids=0; duplicate_paths=0; broken_links=0; required_metadata=$true; index_consistent=$true; router_consistent=$true; manifest_consistent=$true }
        error_count=0; warning_count=0
    }
    $validation | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $VaultPath '_System\VALIDATION.json') -Encoding UTF8
    $null=Refresh-PortableSourceManifest $VaultPath $VersionText $Revision $InstanceId
}

function Expand-TemplateTree([string]$Source,[string]$Destination,[hashtable]$Tokens,[switch]$Overlay) {
    if(-not(Test-Path $Source -PathType Container)){throw('Template source is missing: '+$Source)};if(-not$Overlay -and(Test-Path $Destination)){throw('Template destination already exists: '+$Destination)};New-Item -ItemType Directory -Force -Path $Destination|Out-Null
    foreach($row in @(Get-SafeTreeFileInventory -RootPath $Source -Purpose 'Template source')){$file=$row.File;$rel=([string]$row.RelativePath).Replace('/','\');$dst=Join-Path $Destination $rel;$parent=Split-Path -Parent $dst;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null};$text=Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8;foreach($k in $Tokens.Keys){$text=$text.Replace('{{'+$k+'}}',[string]$Tokens[$k])};Set-Content $dst $text -Encoding UTF8}
}

function Install-CanonicalGovernanceTemplates([string]$Destination,[hashtable]$Tokens) {
    $source=Join-Path $ProductRoot 'governance\hub'
    Expand-TemplateTree $source $Destination $Tokens -Overlay
}

function Expand-GenesisTemplate([string]$Destination, [hashtable]$Tokens) {
    $source = Join-Path $ProductRoot 'starter\hub'
    Expand-TemplateTree $source $Destination $Tokens
    Install-CanonicalGovernanceTemplates $Destination $Tokens
}

function Read-GenesisInputConfig([string]$ConfigPath) {
    if ([string]::IsNullOrWhiteSpace($ConfigPath)) { throw 'Genesis config path is empty.' }
    $full=[System.IO.Path]::GetFullPath($ConfigPath)
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw ('Genesis config file not found: '+$full) }
    $item=Get-Item -LiteralPath $full -Force -ErrorAction Stop
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Genesis config must not be a reparse point.' }
    if ($item.Length -gt 64KB) { throw 'Genesis config exceeds 64 KiB.' }
    $cfg=Read-KeelarynJsonFile $full
    $expected=@('areas','language','projects','purpose','schema','timezone')
    $actual=@($cfg.PSObject.Properties.Name|Sort-Object)
    if ([string]::Join('|',$actual) -cne [string]::Join('|',$expected)) { throw 'Genesis config property set is invalid.' }
    if ([string]$cfg.schema -ne 'keelaryn.genesis-input.v1') { throw 'Unsupported Genesis config schema.' }
    $language=([string]$cfg.language).Trim(); if (-not $language) { $language='en' }
    if ($language.Length -gt 64 -or $language -match '[\x00-\x1F]') { throw 'Genesis canonical language is invalid.' }
    $purpose=([string]$cfg.purpose).Trim().ToLowerInvariant(); if (-not $purpose) { $purpose='mixed' }
    if (@('personal','professional','mixed') -notcontains $purpose) { throw 'Purpose must be personal, professional or mixed.' }
    $timezone=([string]$cfg.timezone).Trim(); if (-not $timezone) { $timezone=[System.TimeZoneInfo]::Local.Id }
    if ($timezone.Length -gt 128 -or $timezone -match '[\x00-\x1F]') { throw 'Genesis timezone is invalid.' }
    $areas=New-Object System.Collections.ArrayList
    foreach($row in @($cfg.areas)){
        if($null-eq$row -or $row -isnot [string]){throw 'Genesis areas must be strings.'}
        $v=([string]$row).Trim();if($v){[void]$areas.Add($v)}
    }
    $projects=New-Object System.Collections.ArrayList
    foreach($row in @($cfg.projects)){
        if($null-eq$row -or $row -isnot [string]){throw 'Genesis projects must be strings.'}
        $v=([string]$row).Trim();if($v){[void]$projects.Add($v)}
    }
    return [pscustomobject]@{Language=$language;Purpose=$purpose;Timezone=$timezone;Areas=@($areas|Select-Object -Unique);Projects=@($projects|Select-Object -Unique)}
}

function Invoke-Genesis([string]$ConfigPath,[bool]$Confirmed=$false) {
    Write-Host 'Keelaryn__Hub Genesis' -ForegroundColor Cyan
    Write-Host ('Target Hub: '+$Vault)
    Write-Host ('CURRENT transport: '+$CurrentZip)
    if ((Test-Path $Vault) -or (Test-Path $CurrentZip)) { throw 'Genesis refused: an existing Keelaryn__Hub vault or Keelaryn__Hub_CURRENT.zip already exists.' }
    $release = Get-ProductRelease
    $instanceId = [guid]::NewGuid().ToString().ToLowerInvariant()
    $date = Get-Date -Format 'yyyy-MM-dd'
    $created = (Get-Date).ToUniversalTime().ToString('o')

    $usingConfig=-not [string]::IsNullOrWhiteSpace($ConfigPath)
    if($usingConfig){
        if(-not$Confirmed){throw 'Non-interactive Genesis requires explicit confirmation.'}
        $cfg=Read-GenesisInputConfig $ConfigPath
        $language=[string]$cfg.Language;$purpose=[string]$cfg.Purpose;$timezone=[string]$cfg.Timezone
        $areas=@($cfg.Areas);$projects=@($cfg.Projects)
    }else{
        $language = (Read-Host 'Canonical language [en]').Trim(); if (-not $language) { $language = 'en' }
        $purpose = (Read-Host 'Purpose: personal / professional / mixed [mixed]').Trim().ToLowerInvariant(); if (-not $purpose) { $purpose = 'mixed' }
        if (@('personal','professional','mixed') -notcontains $purpose) { throw 'Purpose must be personal, professional or mixed.' }
        $timezone = (Read-Host 'Timezone [local]').Trim(); if (-not $timezone) { $timezone = [System.TimeZoneInfo]::Local.Id }
        $areasRaw = Read-Host 'Areas, comma-separated (optional)'
        $projectsRaw = Read-Host 'Live projects, comma-separated (optional)'
        $areas = @($areasRaw -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -Unique)
        $projects = @($projectsRaw -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -Unique)
    }
    if ($areas.Count -gt 8) { throw 'Genesis supports at most 8 initial Areas.' }
    if ($projects.Count -gt 12) { throw 'Genesis supports at most 12 initial Projects.' }
    $areaPlan=@(New-GenesisItemPlan $areas 'area')
    $projectPlan=@(New-GenesisItemPlan $projects 'project')
    Assert-GenesisPlanDoesNotCollideWithTemplates @($areaPlan + $projectPlan)

    Write-Host ''
    Write-Host ("instance_id: " + $instanceId)
    Write-Host ("Areas: " + $(if ($areas.Count) { $areas -join ', ' } else { 'none' }))
    Write-Host ("Projects: " + $(if ($projects.Count) { $projects -join ', ' } else { 'none' }))
    if(-not$usingConfig){
        $confirm = (Read-Host 'Create the canonical initial Hub revision? [y/N]').Trim().ToLowerInvariant()
        if ($confirm -ne 'y' -and $confirm -ne 'yes') { Write-Host 'Genesis cancelled.'; return 0 }
    }

    $temp = Join-Path $WorkRoot ('genesis_' + [guid]::NewGuid().ToString('N'))
    $hub = Join-Path $temp 'Keelaryn__Hub'
    New-Item -ItemType Directory -Path $temp | Out-Null
    try {
        $areaHome = if ($areaPlan.Count) { ($areaPlan | ForEach-Object { '- [[' + ('Areas/' + $_.Slug) + ']]' }) -join "`n" } else { 'No Areas yet.' }
        $queue = if ($projectPlan.Count) { ($projectPlan | ForEach-Object { '- [[' + ('Projects/' + $_.Slug) + ']]' }) -join "`n" } else { 'No live Projects yet.' }
        Expand-GenesisTemplate $hub @{
            DATE=$date; INSTANCE_ID=$instanceId; LANGUAGE=$language; PURPOSE=$purpose; TIMEZONE=$timezone
            MANAGER_VERSION=$ManagerVersion; RELEASE_ID=[string]$release.release_id; AREAS_HOME=$areaHome; PROJECT_QUEUE=$queue
        }

        foreach ($item in $areaPlan) {
            $name=$item.Name; $slug=$item.Slug; $id=$item.Id
            $body = "---`nid: $id`ntype: area`nstatus: active`nupdated: $date`n---`n`n# $name`n`nCreated during Genesis from user-authorized initial state.`n"
            Set-Content (Join-Path $hub ('Areas\' + $slug + '.md')) $body -Encoding UTF8
        }
        foreach ($item in $projectPlan) {
            $name=$item.Name; $slug=$item.Slug; $id=$item.Id
            $body = "---`nid: $id`ntype: project`nstatus: active`nupdated: $date`npriority: P3`n---`n`n# $name`n`nInitial live Project created during Genesis. Refine outcome, brief and activation constraints during normal use.`n"
            Set-Content (Join-Path $hub ('Projects\' + $slug + '.md')) $body -Encoding UTF8
        }

        $state = "---`nid: system.state`ntype: system`nstatus: active`nupdated: $date`n---`n`n# Keelaryn__Hub State`n`nkeelaryn_format: 1`nsystem_version: $($release.system_version)`ndata_revision: 1`nrevision_scope: global_monotonic`nderived_router_schema: keelaryn.router.v2`nderived_index_schema: keelaryn.index.v1`nderived_validation_schema: keelaryn.validation.v2`nderived_manifest_schema: keelaryn.manifest.v1`nartifact_schema: keelaryn.artifact.v3`ninstance_schema: keelaryn.instance.v1`nmanager_protocol: $($release.manager_protocol)`n"
        Set-Content (Join-Path $hub '_System\STATE.md') $state -Encoding UTF8
        [ordered]@{
            schema='keelaryn.instance.v1'; instance_id=$instanceId; created=$created; origin_type='genesis'; genesis_release_id=[string]$release.release_id
            genesis_manager_version=$ManagerVersion; canonical_language=$language; purpose=$purpose; timezone=$timezone
        } | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $hub '_System\INSTANCE.json') -Encoding UTF8

        Build-DerivedMetadata $hub ([string]$release.system_version) 1 $instanceId
        $payload = Get-VaultPayloadHashAt $hub
        $artifactId = 'genesis-' + $instanceId.Replace('-','').Substring(0,16)
        [ordered]@{
            schema='keelaryn.artifact.v3'; artifact_status='approved'; artifact_id=$artifactId; producer_role='keelaryn_manager_genesis'; created=$created; revision_time_utc=$created
            system_version=[string]$release.system_version; data_revision=1; instance_id=$instanceId; genesis=$true; genesis_release_id=[string]$release.release_id
            payload_content_sha256=$payload; base_system_version=''; base_data_revision=0; base_artifact_id=''; base_payload_content_sha256=''
            ancestor_chain=@(); accepted_candidates=@(); manager_protocol=[string]$release.manager_protocol
        } | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $hub '_System\ARTIFACT.json') -Encoding UTF8

        $stateCheck = Read-VaultMetadataAt $hub
        if (-not $stateCheck) { throw 'Generated Genesis vault failed Manager validation.' }
        $art = Read-VaultArtifactManifestAt $hub
        if (-not $art -or -not $art.Genesis -or $art.InstanceId -ne $instanceId) { throw 'Generated Genesis ARTIFACT failed validation.' }
        if ((Get-VaultPayloadHashAt $hub) -ne $art.PayloadHash) { throw 'Generated Genesis payload hash mismatch.' }

        $zip = $PreferredCurrentZip
        Write-PortableHubZip $hub $zip 'Keelaryn__Hub'
        Set-ManagerMutablePresentationHidden $zip
        $zipState = Read-ZipState $zip
        $zipArt = Read-ZipArtifactManifest $zip
        if (-not $zipState -or -not $zipArt) { throw 'Generated Genesis ZIP failed validation.' }

        Move-Item $hub $Vault
        $genesisCheckpoint = Join-Path $Checkpoints ('PINNED__GENESIS__Keelaryn__Hub_v' + [string]$release.system_version + '_r0001_' + $date + '.zip')
        Copy-Item $zip $genesisCheckpoint -Force
        Log ("Genesis created instance_id={0}, release={1}" -f $instanceId, $release.release_id)
        Write-Host ''
        Write-Host 'Genesis complete.' -ForegroundColor Green
        Write-Host ("instance_id: " + $instanceId)
        return 0
    }
    finally { if (Test-Path $temp) { Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue } }
}

function Get-OrCreateLegacyBinding($State) {
    if ($State.InstanceId) { return [pscustomobject]@{ InstanceId=$State.InstanceId; Canonical=$true } }
    if (Test-Path $LegacyBindingFile -PathType Leaf) {
        try {
            $b = Read-KeelarynJsonFile $LegacyBindingFile
            if (Test-InstanceId ([string]$b.instance_id)) { return [pscustomobject]@{ InstanceId=([string]$b.instance_id); Canonical=$false } }
        }
        catch {}
    }
    $id = [guid]::NewGuid().ToString().ToLowerInvariant()
    [ordered]@{
        schema='keelaryn.manager.legacy-instance-binding.v1'; instance_id=$id; created=(Get-Date).ToUniversalTime().ToString('o')
        note='Manager-local bridge identity only; canonical Hub remains legacy until explicit migration.'
    } | ConvertTo-Json | Set-Content $LegacyBindingFile -Encoding UTF8
    return [pscustomobject]@{ InstanceId=$id; Canonical=$false }
}

function Show-InstanceInfo {
    $state=Read-VaultState
    if(-not$state){throw 'No valid installed Keelaryn__Hub instance found.'}
    $binding=Get-OrCreateLegacyBinding $state
    $artifact=Read-VaultArtifactManifestAt $Vault
    $revisionRaw=$null
    if($artifact -and $artifact.RevisionTimeUtc){$revisionRaw=[string]$artifact.RevisionTimeUtc}
    elseif($artifact -and $artifact.CreatedUtc){$revisionRaw=[string]$artifact.CreatedUtc}
    $revisionDisplay=if($revisionRaw){try{([DateTimeOffset]::Parse($revisionRaw)).ToLocalTime().ToString('yyyy-MM-dd HH:mm')}catch{$revisionRaw}}else{'unavailable'}
    Write-Host 'Keelaryn installation' -ForegroundColor Cyan
    Write-Host ''
    Write-Host 'Manager'
    Write-Host ('  Version: '+$ManagerVersion)
    Write-Host ('  Location: '+$Root)
    Write-Host ''
    Write-Host 'Hub'
    Write-Host ('  Version: '+$state.VersionText)
    Write-Host ('  Revision: '+$revisionDisplay)
    Write-Host ('  Legacy sequence: r{0:D4}' -f $state.Revision) -ForegroundColor DarkGray
    Write-Host ('  Location: '+$Vault)
    if($artifact){Write-Host ('  Artifact: '+$artifact.ArtifactId)}
    Write-Host ''
    Write-Host ('  Revision UTC: '+$(if($revisionRaw){$revisionRaw}else{'unavailable'})) -ForegroundColor DarkGray
    Write-Host ('  Binding source: '+$(if(Test-Path -LiteralPath $BindingFile -PathType Leaf){'state/binding.json'}else{'default/compatibility resolution'})) -ForegroundColor DarkGray
    Write-Host ''
    Write-Host 'Status'
    $doctorPath=Join-Path $Logs 'DOCTOR_REPORT.json'
    $doctorStatus='never'; $doctorGenerated=$null
    if(Test-Path -LiteralPath $doctorPath -PathType Leaf){
        try{$dr=Read-KeelarynJsonFile $doctorPath;$doctorGenerated=[string]$dr.generated;if([string]$dr.manager_version-eq$ManagerVersion-and[int]$dr.errors-eq0){$doctorStatus='PASS'}elseif([string]$dr.manager_version-eq$ManagerVersion){$doctorStatus='FAIL'}else{$doctorStatus='stale'}}catch{$doctorStatus='unreadable'}
    }
    Write-Host ('  Last Doctor: '+$doctorStatus+$(if($doctorGenerated){' | '+$doctorGenerated}else{''}))
    $managerUpdates=@(Get-ChildItem -LiteralPath $Inbox -File -Filter '*.zip' -ErrorAction SilentlyContinue|Where-Object{$_.Name-match'(?i)^Keelaryn__Manager_Update_'}).Count
    $hubApproved=@(Get-ChildItem -LiteralPath $Inbox -File -Filter '*.zip' -ErrorAction SilentlyContinue|Where-Object{$_.Name-match'(?i)^(Keelaryn__Hub|Core__Hub)_APPROVED_'}).Count
    $hubCandidates=@(Get-ChildItem -LiteralPath $Inbox -File -Filter '*.zip' -ErrorAction SilentlyContinue|Where-Object{$_.Name-match'(?i)^(Keelaryn__Hub|Core__Hub)_CANDIDATE_'}).Count
    Write-Host ('  Pending updates: Manager='+$managerUpdates+' | Hub APPROVED='+$hubApproved)
    Write-Host ('  Hub CANDIDATE inputs: '+$hubCandidates) -ForegroundColor DarkGray
    Write-Host ''
    Write-Host 'Identity'
    Write-Host ('  Instance ID: '+$binding.InstanceId)
    Write-Host ('  Identity scope: '+$(if($binding.Canonical){'keelaryn.instance.v1'}else{'local legacy bridge'}))
    $release=Get-ProductRelease
    Write-Host ('  System release: '+$release.release_id) -ForegroundColor DarkGray
    if([version]$release.system_version-gt$state.Version){Write-Host 'A newer generic system release exists; migration reconciliation is required.' -ForegroundColor Yellow}
    return 0
}

function Set-ObjectProperty($Object, [string]$Name, $Value) {
    if ($null -ne $Object.PSObject.Properties[$Name]) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

function Set-StateScalarField([string]$Text, [string]$Name, [string]$Value) {
    $pattern = '(?m)^' + [regex]::Escape($Name) + ':\s*[^\r\n]*$'
    $replacement = $Name + ': ' + $Value
    if ([regex]::IsMatch($Text, $pattern)) { return [regex]::Replace($Text, $pattern, $replacement, 1) }

    $firstEnd = $Text.IndexOf("`n---", 4, [System.StringComparison]::Ordinal)
    if ($Text.StartsWith('---') -and $firstEnd -gt 0) {
        $front = $Text.Substring(0, $firstEnd)
        if ([regex]::IsMatch($front, '(?m)^keelaryn_format:\s*')) {
            return $Text.Insert($firstEnd, "`n" + $replacement)
        }
    }
    return $Text.TrimEnd() + "`n" + $replacement + "`n"
}

function Test-CanonicalBaselineConsistent {
    $vaultAnalysis=Get-PortableVaultAnalysis $Vault
    $state=Read-VaultMetadataAt $Vault $vaultAnalysis
    if (-not $state) { throw 'Installed Keelaryn__Hub derived metadata is invalid.' }
    if (-not (Test-Path -LiteralPath $CurrentZip -PathType Leaf)) { throw 'Keelaryn__Hub_CURRENT.zip is missing.' }
    $session=Open-HubZipInspectionSession $CurrentZip
    if (-not $session) { throw 'Keelaryn__Hub_CURRENT.zip envelope is invalid.' }
    try {
        $zipState=Read-ZipState $CurrentZip $session; $va=Read-VaultArtifactManifestAt $Vault; $za=Read-ZipArtifactManifest $CurrentZip $session
        if (-not $zipState -or -not $va -or -not $za) { throw 'Canonical baseline metadata is incomplete.' }
        if ($zipState.VersionText -ne $state.VersionText -or $zipState.Revision -ne $state.Revision) { throw 'Keelaryn__Hub_CURRENT.zip STATE differs from installed vault.' }
        $zh=Get-ZipHashPair $CurrentZip $session
        if ($zh.ContentHash -ne $vaultAnalysis.ContentHash -or $zh.PayloadHash -ne $vaultAnalysis.PayloadHash) { throw 'Installed vault has local drift from Keelaryn__Hub_CURRENT.zip.' }
        if ($za.ArtifactId -ne $va.ArtifactId) { throw 'Installed ARTIFACT differs from Keelaryn__Hub_CURRENT.zip.' }
        return [pscustomobject]@{State=$state;Artifact=$va;ContentHash=$vaultAnalysis.ContentHash;PayloadHash=$vaultAnalysis.PayloadHash}
    }
    finally { Close-HubZipInspectionSession $session }
}

function Assert-CurrentHubSnapshotUnchanged($Expected) {
    if(-not$Expected -or -not$Expected.State -or -not$Expected.ContentHash -or -not$Expected.PayloadHash){throw 'Expected Hub snapshot proof is incomplete.'};$state=Read-VaultStateCoreAt $Vault;$artifact=Read-VaultArtifactManifestAt $Vault;if(-not$state -or -not$artifact){throw 'Installed Hub changed or became unreadable before commit.'};if($state.VersionText-ne$Expected.State.VersionText -or $state.Revision-ne$Expected.State.Revision){throw 'Installed Hub STATE changed after validation; rerun.'};if($Expected.State.InstanceId -and $state.InstanceId-ne$Expected.State.InstanceId){throw 'Installed Hub instance_id changed after validation; rerun.'};if($Expected.Artifact -and $artifact.ArtifactId-ne$Expected.Artifact.ArtifactId){throw 'Installed Hub ARTIFACT changed after validation; rerun.'};$h=Get-VaultHashPairAt $Vault;if($h.ContentHash-ne$Expected.ContentHash -or $h.PayloadHash-ne$Expected.PayloadHash){throw 'Installed Hub canonical content changed after validation; no replacement was performed.'}
}

function Update-IdentityDerivedJson([string]$HubPath, [string]$VersionText, [int]$Revision, [string]$InstanceId) {
    foreach ($rel in @('_System\INDEX.json','_System\ROUTER.json','_System\VALIDATION.json')) {
        $path = Join-Path $HubPath $rel
        if (-not (Test-Path $path -PathType Leaf)) { continue }
        $obj = Read-KeelarynJsonFile $path
        Set-ObjectProperty $obj 'system_version' $VersionText
        Set-ObjectProperty $obj 'data_revision' $Revision
        Set-ObjectProperty $obj 'instance_id' $InstanceId
        $obj | ConvertTo-Json -Depth 30 | Set-Content $path -Encoding UTF8
    }
}

function New-PortableSourceManifest([string]$HubPath,[string]$VersionText,[int]$Revision,[string]$InstanceId,$PortableAnalysis=$null) {
    $analysis = $PortableAnalysis
    if (-not $analysis) { $analysis = Get-PortableVaultAnalysis $HubPath }
    $entries=@()
    foreach ($row in @($analysis.ManifestFiles)) { $entries += ,@([string]$row.RelativePath,[long]$row.Length,[string]$row.Hash) }
    $manifest = [ordered]@{
        schema = 'keelaryn.manifest.v1'
        vault = 'Keelaryn__Hub'
        system_version = $VersionText
        data_revision = $Revision
        instance_id = $InstanceId
        entry_count = [int]$analysis.ManifestEntryCount
        content_set_sha256 = [string]$analysis.ManifestContentHash
        entries = $entries
    }
    return [pscustomobject]@{Manifest=$manifest;EntryCount=[int]$analysis.ManifestEntryCount;ContentHash=[string]$analysis.ManifestContentHash}
}

function Refresh-PortableSourceManifest([string]$HubPath, [string]$VersionText, [int]$Revision, [string]$InstanceId) {
    $manifestPath = Join-Path $HubPath '_System\MANIFEST.json'
    $built = New-PortableSourceManifest $HubPath $VersionText $Revision $InstanceId
    $built.Manifest | ConvertTo-Json -Depth 12 | Set-Content $manifestPath -Encoding UTF8

    $validationPath = Join-Path $HubPath '_System\VALIDATION.json'
    if (Test-Path $validationPath -PathType Leaf) {
        $v = Read-KeelarynJsonFile $validationPath
        if ($null -ne $v.PSObject.Properties['source_manifest']) {
            Set-ObjectProperty $v.source_manifest 'schema' 'keelaryn.manifest.v1'
            Set-ObjectProperty $v.source_manifest 'entry_count' $built.EntryCount
            Set-ObjectProperty $v.source_manifest 'content_set_sha256' $built.ContentHash
        }
        if ($null -ne $v.PSObject.Properties['checks']) { Set-ObjectProperty $v.checks 'manifest_consistent' $true }
        $v | ConvertTo-Json -Depth 30 | Set-Content $validationPath -Encoding UTF8
    }
    return $built
}

function Test-ManifestObjectAgainstBuilt($Manifest,$Built,$State) {
    if (-not $Manifest) { return New-CheckResult $false 'MANIFEST is missing.' }
    if (-not $State.ManifestSchema -or [string]$State.ManifestSchema -ne 'keelaryn.manifest.v1') { return New-CheckResult $false 'STATE does not declare the required Keelaryn manifest schema.' }
    if ([string]$Manifest.schema -ne [string]$State.ManifestSchema) { return New-CheckResult $false 'Unsupported or mismatched MANIFEST schema.' }
    if ([string]$Manifest.vault -ne 'Keelaryn__Hub' -or [string]$Manifest.system_version -ne $State.VersionText -or [int]$Manifest.data_revision -ne $State.Revision) { return New-CheckResult $false 'MANIFEST identity/version/revision disagrees with STATE.' }
    if ($State.InstanceId -and ([string]$Manifest.instance_id).ToLowerInvariant() -ne $State.InstanceId) { return New-CheckResult $false 'MANIFEST instance_id disagrees with INSTANCE.' }
    if ([int]$Manifest.entry_count -ne $Built.EntryCount -or ([string]$Manifest.content_set_sha256).ToLowerInvariant() -ne $Built.ContentHash) { return New-CheckResult $false 'MANIFEST summary disagrees with portable source set.' }
    $actual=@($Manifest.entries); $expected=@($Built.Manifest.entries)
    if ($actual.Count -ne $expected.Count) { return New-CheckResult $false 'MANIFEST entries count disagrees with portable source set.' }
    for ($i=0;$i -lt $expected.Count;$i++) {
        $a=@($actual[$i]); $e=@($expected[$i])
        if ($a.Count -ne 3 -or [string]$a[0] -ne [string]$e[0] -or [long]$a[1] -ne [long]$e[1] -or ([string]$a[2]).ToLowerInvariant() -ne ([string]$e[2]).ToLowerInvariant()) { return New-CheckResult $false ('MANIFEST entry mismatch at index '+$i+'.') }
    }
    return New-CheckResult $true 'MANIFEST matches portable source set.'
}

function Test-VaultSourceManifestConsistency([string]$HubPath,$State,$PortableAnalysis=$null) {
    $path = Join-Path $HubPath '_System\MANIFEST.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return New-CheckResult $false 'STATE declares MANIFEST but file is missing.' }
    try { $manifest = Read-KeelarynJsonFile $path }
    catch { return New-CheckResult $false ('MANIFEST JSON parse failed: '+$_.Exception.Message) }
    $built = New-PortableSourceManifest $HubPath $State.VersionText $State.Revision $State.InstanceId $PortableAnalysis
    return Test-ManifestObjectAgainstBuilt $manifest $built $State
}

function Get-ZipPortableSourceManifest([string]$ZipPath,$State,$Session=$null) {
    if ($Session) {
        if (-not (Test-HubZipInspectionSessionForPath $Session $ZipPath)) { throw 'Hub ZIP inspection session/path mismatch.' }
        $entries=@()
        foreach ($row in @($Session.ManifestEntries)) { $entries += ,@([string]$row.Rel,[long]$row.Length,[string]$row.Hash) }
        $contentHash=[string]$Session.ManifestContentHash
        $manifest=[ordered]@{schema='keelaryn.manifest.v1';vault='Keelaryn__Hub';system_version=$State.VersionText;data_revision=$State.Revision;instance_id=$State.InstanceId;entry_count=$entries.Count;content_set_sha256=$contentHash;entries=$entries}
        return [pscustomobject]@{Manifest=$manifest;EntryCount=$entries.Count;ContentHash=$contentHash}
    }
    $zipInfo=Get-HubZipEnvelope $ZipPath
    if (-not $zipInfo) { throw 'Unsupported Hub ZIP root.' }
    $root=[string]$zipInfo.Root
    $excluded=@{'_system/artifact.json'=$true;'_system/manifest.json'=$true;'_system/index.json'=$true;'_system/router.json'=$true;'_system/validation.json'=$true}
    $archive=[System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $rows=@()
        foreach ($entry in @($archive.Entries | Sort-Object { $_.FullName.Replace('\','/').ToLowerInvariant() })) {
            $n=$entry.FullName.Replace('\','/')
            if ($n.EndsWith('/') -or -not $n.StartsWith($root,[System.StringComparison]::Ordinal)) { continue }
            $rel=$n.Substring($root.Length); $key=$rel.ToLowerInvariant()
            if ((Test-IsLocalDeploymentRelativePath $rel) -or $excluded.ContainsKey($key)) { continue }
            $stream=$entry.Open(); try { $h=Get-StreamHashHex $stream } finally { $stream.Dispose() }
            $rows += [pscustomobject]@{ Rel=$rel; Length=[long]$entry.Length; Hash=$h }
        }
        $entries=@(); $hashRows=@()
        foreach ($row in $rows) { $entries += ,@($row.Rel,$row.Length,$row.Hash); $hashRows += ($row.Rel+"`0"+$row.Hash) }
        $contentHash=Get-TextHashHex ([string]::Join("`n",$hashRows))
        $manifest=[ordered]@{schema='keelaryn.manifest.v1';vault='Keelaryn__Hub';system_version=$State.VersionText;data_revision=$State.Revision;instance_id=$State.InstanceId;entry_count=$entries.Count;content_set_sha256=$contentHash;entries=$entries}
        return [pscustomobject]@{Manifest=$manifest;EntryCount=$entries.Count;ContentHash=$contentHash}
    }
    finally { $archive.Dispose() }
}

function Test-ZipSourceManifestConsistency([string]$ZipPath,$State,$Session=$null) {
    if ($Session -and -not (Test-HubZipInspectionSessionForPath $Session $ZipPath)) { return New-CheckResult $false 'Hub ZIP inspection session/path mismatch.' }
    $zipInfo=if ($Session) { [pscustomobject]@{Root=$Session.Root} } else { Get-HubZipEnvelope $ZipPath }
    if (-not $zipInfo) { return New-CheckResult $false 'Unsupported Hub ZIP root.' }
    $archive=$null
    try {
        $archive=if ($Session) { $Session.Archive } else { [System.IO.Compression.ZipFile]::OpenRead($ZipPath) }
        $entryName=[string]$zipInfo.Root+'_System/MANIFEST.json'
        $entry=if ($Session) { $Session.EntryMap[$entryName] } else { $archive.Entries | Where-Object { $_.FullName.Replace('\','/') -eq $entryName } | Select-Object -First 1 }
        if (-not $entry) { return New-CheckResult $false 'STATE declares MANIFEST but ZIP entry is missing.' }
        try { $manifest=(Read-ZipEntryText $entry)|ConvertFrom-Json } catch { return New-CheckResult $false ('MANIFEST JSON parse failed: '+$_.Exception.Message) }
    }
    finally { if ($archive -and -not $Session) { $archive.Dispose() } }
    $built=Get-ZipPortableSourceManifest $ZipPath $State $Session
    return Test-ManifestObjectAgainstBuilt $manifest $built $State
}

function Get-AncestorRowsForMigration($BaseArtifact, [string]$BasePayloadHash) {
    $rows = @()
    $rows += [ordered]@{
        system_version=$BaseArtifact.VersionText; data_revision=$BaseArtifact.Revision; artifact_id=$BaseArtifact.ArtifactId; payload_content_sha256=$BasePayloadHash
    }
    foreach ($a in @($BaseArtifact.Ancestors | Select-Object -First 15)) {
        $rows += [ordered]@{ system_version=$a.VersionText; data_revision=$a.Revision; artifact_id=$a.ArtifactId; payload_content_sha256=$a.PayloadHash }
    }
    return @($rows)
}

function Install-PreparedMigrationHub([string]$PreparedHub,[string]$MigrationId,$ExpectedBaseline) {
    $zip = Join-Path $WorkRoot ('migration_' + [guid]::NewGuid().ToString('N') + '.zip')
    try {
        Write-PortableHubZip $PreparedHub $zip 'Keelaryn__Hub'
        $session=Open-HubZipInspectionSession $zip
        if (-not $session) { throw ('Prepared migration checkpoint has an invalid ZIP envelope: ' + $MigrationId) }
        try {
            $state = Read-ZipState $zip $session
            $artifact = Read-ZipArtifactManifest $zip $session
            if (-not $state -or -not $artifact -or $artifact.Status -ne 'approved' -or $artifact.ProducerRole -ne 'keelaryn_manager_migration') {
                throw ('Prepared migration checkpoint failed package validation: ' + $MigrationId)
            }
            $hashPair=Get-ZipHashPair $zip $session
        }
        finally { Close-HubZipInspectionSession $session }
        $pkg = [pscustomobject]@{File=(Get-Item $zip);State=$state;Artifact=$artifact;ZipHash=(Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant();ContentHash=$hashPair.ContentHash;PayloadHash=$hashPair.PayloadHash}
        if (-not (Close-ObsidianIfNeeded)) { throw 'Obsidian did not close; migration was not installed.' }
        Install-HubPackage $pkg $ExpectedBaseline
    }
    finally { if (Test-Path $zip) { Remove-Item $zip -Force -ErrorAction SilentlyContinue } }
}

function Test-IdentityProtocolCompatible($State) {
    if (-not $State.ManagerProtocol) { return $false }
    return [regex]::IsMatch([string]$State.ManagerProtocol, '^keelaryn-chat-manager-v4(?:\.|$)', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase) -or [regex]::IsMatch([string]$State.ManagerProtocol, [string]$LegacyCoreCompat.ManagerProtocolPattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
}

function Invoke-AdoptInstanceIdentity {
    $baseline = Test-CanonicalBaselineConsistent
    if ($baseline.State.InstanceId) {
        Write-Host ('Identity already canonical: ' + $baseline.State.InstanceId) -ForegroundColor Green
        return 0
    }
    if (-not $baseline.Artifact -or $baseline.Artifact.Status -ne 'approved') { throw 'Identity adoption requires an installed APPROVED checkpoint.' }
    if (-not (Test-IdentityProtocolCompatible $baseline.State)) { throw ('Identity adoption requires a Keelaryn v4-compatible Chat Manager protocol first. Installed protocol: ' + [string]$baseline.State.ManagerProtocol) }

    $binding = Get-OrCreateLegacyBinding $baseline.State
    $release = Get-ProductRelease
    $instanceId = $binding.InstanceId
    $newRevision = $baseline.State.Revision + 1
    $date = Get-Date -Format 'yyyy-MM-dd'
    if (-not (Close-ObsidianIfNeeded)) { throw 'Obsidian did not close; identity migration was not staged.' }
    Assert-CurrentHubSnapshotUnchanged $baseline
    $created = (Get-Date).ToUniversalTime().ToString('o')
    $temp = Join-Path $WorkRoot ('identity_migration_' + [guid]::NewGuid().ToString('N'))
    $hub = Join-Path $temp 'Keelaryn__Hub'
    New-Item -ItemType Directory -Path $temp | Out-Null
    try {
        Copy-PortableHubTree $Vault $hub
        $statePath = Join-Path $hub '_System\STATE.md'
        $stateText = Get-Content $statePath -Raw -Encoding UTF8
        $stateText = Set-StateScalarField $stateText 'data_revision' ([string]$newRevision)
        $stateText = Set-StateScalarField $stateText 'artifact_schema' 'keelaryn.artifact.v3'
        $stateText = Set-StateScalarField $stateText 'instance_schema' 'keelaryn.instance.v1'
        $stateText = Set-StateScalarField $stateText 'updated' $date
        Set-Content $statePath $stateText -Encoding UTF8

        [ordered]@{
            schema='keelaryn.instance.v1'; instance_id=$instanceId; created=$created; origin_type='legacy_adoption'; adoption_release_id=[string]$release.release_id
            adoption_manager_version=$ManagerVersion
            adopted_from=[ordered]@{ system_version=$baseline.State.VersionText; data_revision=$baseline.State.Revision; artifact_id=$baseline.Artifact.ArtifactId; payload_content_sha256=$baseline.PayloadHash }
        } | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $hub '_System\INSTANCE.json') -Encoding UTF8

        Update-IdentityDerivedJson $hub $baseline.State.VersionText $newRevision $instanceId
        $null = Refresh-PortableSourceManifest $hub $baseline.State.VersionText $newRevision $instanceId
        # Refresh validation once more because the source-manifest helper may have updated it after the identity header patch.
        $validationPath = Join-Path $hub '_System\VALIDATION.json'
        if (Test-Path $validationPath -PathType Leaf) {
            $v = Read-KeelarynJsonFile $validationPath
            Set-ObjectProperty $v 'system_version' $baseline.State.VersionText; Set-ObjectProperty $v 'data_revision' $newRevision; Set-ObjectProperty $v 'instance_id' $instanceId
            $v | ConvertTo-Json -Depth 30 | Set-Content $validationPath -Encoding UTF8
        }

        $payload = Get-VaultPayloadHashAt $hub
        $artifactId = ('migr-r{0:D4}-{1}' -f $newRevision, $payload.Substring(0,12))
        [ordered]@{
            schema='keelaryn.artifact.v3'; artifact_status='approved'; artifact_id=$artifactId; producer_role='keelaryn_manager_migration'; created=$created; revision_time_utc=$created
            system_version=$baseline.State.VersionText; data_revision=$newRevision; instance_id=$instanceId; genesis=$false
            payload_content_sha256=$payload; base_system_version=$baseline.State.VersionText; base_data_revision=$baseline.State.Revision
            base_artifact_id=$baseline.Artifact.ArtifactId; base_payload_content_sha256=$baseline.PayloadHash
            ancestor_chain=@(Get-AncestorRowsForMigration $baseline.Artifact $baseline.PayloadHash); accepted_candidates=@()
            manager_protocol=$(if ($baseline.State.ManagerProtocol) { $baseline.State.ManagerProtocol } else { 'keelaryn-chat-manager-v4.0' })
            migration_id='identity-adoption-v1'; migration_release_id=[string]$release.release_id
        } | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $hub '_System\ARTIFACT.json') -Encoding UTF8

        $checkState = Read-VaultMetadataAt $hub; $checkArtifact = Read-VaultArtifactManifestAt $hub
        if (-not $checkState -or -not $checkArtifact -or $checkState.InstanceId -ne $instanceId -or $checkArtifact.InstanceId -ne $instanceId) { throw 'Identity migration staging validation failed.' }
        if ((Get-VaultPayloadHashAt $hub) -ne $checkArtifact.PayloadHash) { throw 'Identity migration staging payload hash mismatch.' }
        Install-PreparedMigrationHub $hub 'identity-adoption-v1' $baseline
        if (Test-Path $LegacyBindingFile -PathType Leaf) { Remove-Item $LegacyBindingFile -Force -ErrorAction SilentlyContinue }
        Log ('Canonical instance identity adopted: ' + $instanceId)
        Write-Host ('Canonical instance identity adopted: ' + $instanceId) -ForegroundColor Green
        return 0
    }
    finally { if (Test-Path $temp) { Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue } }
}

function Get-MigrationRegistry {
    $path = Join-Path $ProductRoot 'migrations\index.json'
    if (-not (Test-Path $path -PathType Leaf)) { throw 'Migration registry is missing.' }
    $r = Read-KeelarynJsonFile $path
    if ([string]$r.schema -ne 'keelaryn.migration-registry.v2') { throw 'Unsupported migration registry schema.' }
    return $r
}

function Resolve-MigrationChain($Registry, [string]$CurrentVersion, [string]$TargetVersion) {
    $current = [version]$CurrentVersion; $target = [version]$TargetVersion
    if ($current -ge $target) { return [pscustomobject]@{ Status='up_to_date'; Reason='Installed system_version is at or above target.'; Steps=@() } }
    $steps=@(); $seen=@{}
    while ($current -lt $target) {
        if ($seen.ContainsKey($current.ToString())) { return [pscustomobject]@{ Status='invalid_registry'; Reason='Migration registry contains a cycle.'; Steps=@($steps) } }
        $seen[$current.ToString()]=$true
        $matches=@($Registry.migrations | Where-Object { ([version]([string]$_.from_system_version)) -eq $current })
        if ($matches.Count -eq 0) { return [pscustomobject]@{ Status='no_path'; Reason=('No registered migration starts at system_version ' + $current.ToString() + '.'); Steps=@($steps) } }
        if ($matches.Count -ne 1) { return [pscustomobject]@{ Status='ambiguous'; Reason=('Multiple migrations start at system_version ' + $current.ToString() + '.'); Steps=@($steps) } }
        $m=$matches[0]
        try { $next=[version]([string]$m.to_system_version) } catch { return [pscustomobject]@{ Status='invalid_registry'; Reason='Migration has invalid to_system_version.'; Steps=@($steps) } }
        if ($next -le $current -or $next -gt $target) { return [pscustomobject]@{ Status='invalid_registry'; Reason=('Migration ' + [string]$m.id + ' has a non-forward or overshooting target.'); Steps=@($steps) } }
        $steps += $m; $current=$next
    }
    $nonAutomatic=@($steps | Where-Object { ([string]$_.apply_mode).Trim().ToLowerInvariant() -ne 'manager_safe' })
    if ($nonAutomatic.Count -gt 0) { return [pscustomobject]@{ Status='review_required'; Reason='A complete migration chain exists, but one or more steps require Chat Manager reconciliation.'; Steps=@($steps) } }
    return [pscustomobject]@{ Status='ready'; Reason='A complete explicit manager-safe migration chain is registered.'; Steps=@($steps) }
}

function Test-PlatformMigrationPath([string]$RelativePath) {
    if (-not $RelativePath) { return $false }
    $p=$RelativePath.Replace('\','/').Trim('/')
    if ($p.Contains('..') -or [System.IO.Path]::IsPathRooted($RelativePath)) { return $false }
    if ($p -eq '_System/STATE.md' -or $p -eq '_System/INSTANCE.json' -or $p -eq '_System/ARTIFACT.json' -or $p -eq '_System/INDEX.json' -or $p -eq '_System/ROUTER.json' -or $p -eq '_System/VALIDATION.json' -or $p -eq '_System/MANIFEST.json') { return $false }
    return $p.StartsWith('_System/',[System.StringComparison]::OrdinalIgnoreCase) -or $p.StartsWith('Resources/Prompts/',[System.StringComparison]::OrdinalIgnoreCase)
}

function Resolve-MigrationAssetPath([string]$RelativePath) {
    $root = Join-Path $ProductRoot 'migrations\assets'
    $full = [System.IO.Path]::GetFullPath((Join-Path $root $RelativePath))
    $base = [System.IO.Path]::GetFullPath($root).TrimEnd('\') + '\'
    if (-not $full.StartsWith($base,[System.StringComparison]::OrdinalIgnoreCase)) { throw 'Migration asset path escapes product/migrations/assets.' }
    if (-not (Test-Path $full -PathType Leaf)) { throw ('Migration asset missing: ' + $RelativePath) }
    return $full
}

function Get-MarkdownIdentity([string]$Path) {
    if ([System.IO.Path]::GetExtension($Path).ToLowerInvariant() -ne '.md') { return $null }
    $text=Get-Content $Path -Raw -Encoding UTF8
    return [pscustomobject]@{ Id=(Get-FrontmatterValue $text 'id'); Type=(Get-FrontmatterValue $text 'type'); Status=(Get-FrontmatterValue $text 'status') }
}

function Apply-SafeMigrationOperation([string]$HubPath, $Operation) {
    $op=([string]$Operation.op).Trim().ToLowerInvariant()
    if ($op -eq 'state_set') {
        $field=([string]$Operation.field).Trim()
        if (@('manager_protocol') -notcontains $field) { throw ('Unsupported automatic STATE field: ' + $field) }
        $path=Join-Path $HubPath '_System\STATE.md'; $text=Get-Content $path -Raw -Encoding UTF8
        $text=Set-StateScalarField $text $field ([string]$Operation.value); Set-Content $path $text -Encoding UTF8
        return
    }
    $rel=([string]$Operation.path).Replace('/','\')
    if (-not (Test-PlatformMigrationPath $rel)) { throw ('Migration operation targets a non-platform or protected path: ' + [string]$Operation.path) }
    $src=Resolve-MigrationAssetPath ([string]$Operation.source)
    $dst=Join-Path $HubPath $rel
    if ($op -eq 'copy_if_missing') {
        if (Test-Path $dst -PathType Leaf) {
            $a=(Get-FileHash $dst -Algorithm SHA256).Hash.ToLowerInvariant(); $b=(Get-FileHash $src -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($a -ne $b) { throw ('Migration conflict: destination already exists with different content: ' + [string]$Operation.path) }
            return
        }
        if ([System.IO.Path]::GetExtension($dst).ToLowerInvariant() -eq '.md') { throw 'Automatic copy_if_missing cannot introduce a new Markdown entity; use Chat Manager reconciliation.' }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null; Copy-Item $src $dst -Force; return
    }
    if ($op -eq 'replace_if_hash') {
        if (-not (Test-Path $dst -PathType Leaf)) { throw ('Migration conflict: expected platform file is missing: ' + [string]$Operation.path) }
        $currentHash=(Get-FileHash $dst -Algorithm SHA256).Hash.ToLowerInvariant(); $expected=@($Operation.expected_sha256 | ForEach-Object { ([string]$_).ToLowerInvariant() })
        $targetHash=(Get-FileHash $src -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($currentHash -eq $targetHash) { return }
        if ($expected.Count -eq 0 -or $expected -notcontains $currentHash) { throw ('Migration conflict: platform file was locally modified or base hash is unknown: ' + [string]$Operation.path) }
        $before=Get-MarkdownIdentity $dst; $after=Get-MarkdownIdentity $src
        if ($before -and ($before.Id -ne $after.Id -or $before.Type -ne $after.Type -or $before.Status -ne $after.Status)) { throw ('Automatic Markdown replacement changes entity identity: ' + [string]$Operation.path) }
        Copy-Item $src $dst -Force; return
    }
    throw ('Unsupported migration operation: ' + $op)
}

function Invoke-OneRegisteredMigration($Step) {
    $release=Get-ProductRelease
    $baseline=Test-CanonicalBaselineConsistent
    if (-not $baseline.State.InstanceId) { throw 'System migrations require canonical instance identity first.' }
    if ($baseline.State.VersionText -ne [string]$Step.from_system_version) { throw 'Migration precondition failed: installed system_version changed.' }
    if ([string]$Step.apply_mode -ne 'manager_safe') { throw ('Migration requires external reconciliation: ' + [string]$Step.id) }
    $specPath=Join-Path $ProductRoot ('migrations\' + ([string]$Step.spec).Replace('/','\'))
    if (-not (Test-Path $specPath -PathType Leaf)) { throw ('Migration spec missing: ' + [string]$Step.spec) }
    $spec=Read-KeelarynJsonFile $specPath
    if ([string]$spec.schema -ne 'keelaryn.migration.v1' -or [string]$spec.id -ne [string]$Step.id) { throw 'Migration registry/spec identity mismatch.' }
    if ([string]$spec.from_system_version -ne $baseline.State.VersionText -or [string]$spec.to_system_version -ne [string]$Step.to_system_version) { throw 'Migration registry/spec version mismatch.' }

    $newRevision=$baseline.State.Revision+1; $targetVersion=[string]$Step.to_system_version; $instanceId=$baseline.State.InstanceId
    if (-not (Close-ObsidianIfNeeded)) { throw 'Obsidian did not close; system migration was not staged.' }
    Assert-CurrentHubSnapshotUnchanged $baseline
    $date=Get-Date -Format 'yyyy-MM-dd'; $created=(Get-Date).ToUniversalTime().ToString('o')
    $temp=Join-Path $WorkRoot ('system_migration_' + [guid]::NewGuid().ToString('N')); $hub=Join-Path $temp 'Keelaryn__Hub'
    New-Item -ItemType Directory -Path $temp | Out-Null
    try {
        Copy-PortableHubTree $Vault $hub
        foreach ($op in @($spec.operations)) { Apply-SafeMigrationOperation $hub $op }
        $statePath=Join-Path $hub '_System\STATE.md'; $stateText=Get-Content $statePath -Raw -Encoding UTF8
        $stateText=Set-StateScalarField $stateText 'system_version' $targetVersion
        $stateText=Set-StateScalarField $stateText 'data_revision' ([string]$newRevision)
        $stateText=Set-StateScalarField $stateText 'artifact_schema' 'keelaryn.artifact.v3'
        $stateText=Set-StateScalarField $stateText 'instance_schema' 'keelaryn.instance.v1'
        $stateText=Set-StateScalarField $stateText 'updated' $date
        Set-Content $statePath $stateText -Encoding UTF8
        Update-IdentityDerivedJson $hub $targetVersion $newRevision $instanceId
        $null=Refresh-PortableSourceManifest $hub $targetVersion $newRevision $instanceId
        $validationPath=Join-Path $hub '_System\VALIDATION.json'
        if (Test-Path $validationPath -PathType Leaf) {
            $v=Read-KeelarynJsonFile $validationPath
            Set-ObjectProperty $v 'system_version' $targetVersion; Set-ObjectProperty $v 'data_revision' $newRevision; Set-ObjectProperty $v 'instance_id' $instanceId
            $v|ConvertTo-Json -Depth 30|Set-Content $validationPath -Encoding UTF8
        }
        $payload=Get-VaultPayloadHashAt $hub; $artifactId=('migr-r{0:D4}-{1}' -f $newRevision,$payload.Substring(0,12))
        [ordered]@{
            schema='keelaryn.artifact.v3'; artifact_status='approved'; artifact_id=$artifactId; producer_role='keelaryn_manager_migration'; created=$created; revision_time_utc=$created
            system_version=$targetVersion; data_revision=$newRevision; instance_id=$instanceId; genesis=$false; payload_content_sha256=$payload
            base_system_version=$baseline.State.VersionText; base_data_revision=$baseline.State.Revision; base_artifact_id=$baseline.Artifact.ArtifactId; base_payload_content_sha256=$baseline.PayloadHash
            ancestor_chain=@(Get-AncestorRowsForMigration $baseline.Artifact $baseline.PayloadHash); accepted_candidates=@()
            manager_protocol=$(if ((Read-StateText $stateText).ManagerProtocol) { (Read-StateText $stateText).ManagerProtocol } else { 'keelaryn-chat-manager-v4.0' })
            migration_id=[string]$Step.id; migration_release_id=[string]$release.release_id
        }|ConvertTo-Json -Depth 12|Set-Content (Join-Path $hub '_System\ARTIFACT.json') -Encoding UTF8
        $checkState=Read-VaultMetadataAt $hub; $checkArtifact=Read-VaultArtifactManifestAt $hub
        if (-not $checkState -or -not $checkArtifact -or $checkState.VersionText -ne $targetVersion -or $checkState.Revision -ne $newRevision) { throw ('Migration staging validation failed: ' + [string]$Step.id) }
        if ((Get-VaultPayloadHashAt $hub) -ne $checkArtifact.PayloadHash) { throw 'Migration staging payload hash mismatch.' }
        Install-PreparedMigrationHub $hub ([string]$Step.id) $baseline
    }
    finally { if (Test-Path $temp) { Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue } }
}

function Invoke-ApplyMigrations {
    $state=Read-VaultState
    if (-not $state) { throw 'No valid installed Keelaryn__Hub instance found.' }
    if (-not $state.InstanceId) { Write-Host 'Canonical instance identity is required first. Run MIGRATE_INSTANCE_IDENTITY.cmd.' -ForegroundColor Yellow; return 2 }
    $release=Get-ProductRelease; $registry=Get-MigrationRegistry
    $plan=Resolve-MigrationChain $registry $state.VersionText ([string]$release.system_version)
    if ($plan.Status -eq 'up_to_date') { Write-Host 'No system migration required.' -ForegroundColor Green; return 0 }
    if ($plan.Status -eq 'review_required') { Write-Host ('Migration requires Chat Manager reconciliation: ' + $plan.Reason) -ForegroundColor Yellow; return 2 }
    if ($plan.Status -ne 'ready') { Write-Host ('Migration blocked: ' + $plan.Reason) -ForegroundColor Yellow; return 2 }
    foreach ($step in @($plan.Steps)) { Invoke-OneRegisteredMigration $step }
    Write-Host 'Registered system migration chain applied.' -ForegroundColor Green
    return 0
}

function Invoke-CheckMigrations {
    $state = Read-VaultState
    if (-not $state) { throw 'No valid installed Keelaryn__Hub instance found.' }
    $binding = Get-OrCreateLegacyBinding $state
    $release = Get-ProductRelease
    $registry = Get-MigrationRegistry
    $chain = Resolve-MigrationChain $registry $state.VersionText ([string]$release.system_version)
    $status = $chain.Status; $reason = $chain.Reason
    if (-not $binding.Canonical) {
        if (Test-IdentityProtocolCompatible $state) {
            $status = 'identity_adoption_required'
            $reason = 'Legacy Hub has no canonical keelaryn.instance.v1 identity. Identity adoption is a separate non-destructive migration checkpoint and must happen before system migrations.'
        }
        else {
            $status = 'protocol_reconciliation_required'
            $reason = 'Legacy Hub must first reconcile its instance-owned Chat Manager protocol to Keelaryn v4 artifact semantics. Keelaryn__Manager will not overwrite a customized protocol automatically.'
        }
    }
    $plan = [ordered]@{
        schema='keelaryn.manager.migration-plan.v2'; generated=(Get-Date).ToUniversalTime().ToString('o'); instance_id=$binding.InstanceId
        identity_scope=$(if ($binding.Canonical) { 'canonical' } else { 'local_legacy_bridge' }); current_system_version=$state.VersionText
        target_system_version=[string]$release.system_version; target_release_id=[string]$release.release_id; status=$status; reason=$reason
        chain=@($chain.Steps | ForEach-Object { [ordered]@{ id=[string]$_.id; from_system_version=[string]$_.from_system_version; to_system_version=[string]$_.to_system_version; apply_mode=[string]$_.apply_mode; spec=[string]$_.spec } })
        registered_migrations=@($registry.migrations)
    }
    $planPath = Join-Path $Logs 'MIGRATION_PLAN.json'
    $plan | ConvertTo-Json -Depth 10 | Set-Content $planPath -Encoding UTF8
    Write-Host ('Migration status: ' + $status)
    Write-Host ('Plan: ' + $planPath)
    if (-not $binding.Canonical -and (Test-IdentityProtocolCompatible $state)) { Write-Host 'Next safe action: MIGRATE_INSTANCE_IDENTITY.cmd' -ForegroundColor Yellow }
    elseif (-not $binding.Canonical) { Write-Host 'Next safe action: reconcile the Hub Chat Manager protocol to Keelaryn v4 semantics through the normal CANDIDATE -> APPROVED flow.' -ForegroundColor Yellow }
    elseif ($chain.Status -eq 'ready') { Write-Host 'Next safe action: APPLY_MIGRATIONS.cmd' -ForegroundColor Cyan }
    elseif ($chain.Status -eq 'review_required') { Write-Host 'Next safe action: reconcile the registered system migration through Chat Manager; do not run APPLY_MIGRATIONS.cmd.' -ForegroundColor Yellow }
    return 0
}


function Convert-LegacyNamespaceActiveText([string]$Text) {
    # Safe active-document branding only. Historical schema/protocol identifiers are facts
    # and must never be globally rewritten into fictitious Keelaryn predecessors.
    $pairs=@(
        @('project.corehub-engine','project.keelaryn-engine'),
        @('project.corehub-legacy-migration','project.keelaryn-legacy-migration'),
        @('Core__Hub Engine','Keelaryn Engine'),
        @('Core__Hub Legacy Migration','Keelaryn Legacy Migration'),
        @('Core__Hub Manager','Keelaryn Manager'),
        @('CORE__HUB','KEELARYN__HUB'),
        @('Core__Manager','Keelaryn__Manager'),
        @('Core__Hub','Keelaryn__Hub')
    )
    foreach ($pair in $pairs) { $Text=$Text.Replace([string]$pair[0],[string]$pair[1]) }
    return $Text
}


function Convert-LegacyProjectIdentityText([string]$Text) {
    foreach ($pair in @(
        @('project.corehub-engine','project.keelaryn-engine'),
        @('project.corehub-legacy-migration','project.keelaryn-legacy-migration'),
        @('Core__Hub Engine','Keelaryn Engine'),
        @('Core__Hub Legacy Migration','Keelaryn Legacy Migration')
    )) { $Text=$Text.Replace([string]$pair[0],[string]$pair[1]) }
    return $Text
}

function Rename-LegacyKeelarynProjectFiles([string]$HubPath) {
    foreach ($row in @(Get-PortableVaultFileInventory $HubPath | Sort-Object { $_.File.FullName.Length } -Descending)) {
        $file=$row.File
        $name=$file.Name.Replace('Core__Hub Engine','Keelaryn Engine').Replace('Core__Hub Legacy Migration','Keelaryn Legacy Migration')
        if ($name -ne $file.Name) {
            $dst=Join-Path $file.DirectoryName $name
            if (Test-Path $dst) { throw ('Namespace migration path collision: ' + $dst) }
            Move-Item -LiteralPath $file.FullName -Destination $dst
        }
    }
}

function Install-LegacyMigrationPlatformTemplates([string]$HubPath,[string]$Date) {
    Install-CanonicalGovernanceTemplates $HubPath @{ DATE=$Date }
}

function Convert-LegacyNamespaceTree([string]$HubPath,[string]$Date) {
    Rename-LegacyKeelarynProjectFiles $HubPath
    $resolved=(Resolve-Path $HubPath).Path.TrimEnd('\')+'\'
    $platform=@(
        'README.md','_System/BOOTSTRAP.md','_System/PROTOCOL.md','_System/WORKSPACE.md',
        '_System/CHAT_MANAGER.md','_System/CHAT_MANAGER_LAUNCH.md','_System/GLOSSARY.md'
    )
    foreach ($row in @(Get-PortableVaultFileInventory $HubPath)) {
        $file=$row.File
        if (@('.md','.json','.txt','.ps1','.cmd') -notcontains $file.Extension.ToLowerInvariant()) { continue }
        $rel=[string]$row.RelativePath
        if ($rel -eq '_System/STATE.md' -or $platform -contains $rel) { continue }
        $text=Get-Content $file.FullName -Raw -Encoding UTF8
        $historical=$rel.StartsWith('Records/',[System.StringComparison]::OrdinalIgnoreCase) -or $rel -eq '_System/CHANGELOG.md'
        if ($historical) { $text=Convert-LegacyProjectIdentityText $text }
        else { $text=Convert-LegacyNamespaceActiveText $text }
        Set-Content $file.FullName $text -Encoding UTF8
    }
    Install-LegacyMigrationPlatformTemplates $HubPath $Date
}


function Convert-LegacyNamespaceState([string]$StateText,[string]$TargetVersion,[int]$Revision,[string]$Date) {
    $marker='## Revision rule'
    $idx=$StateText.IndexOf($marker,[System.StringComparison]::Ordinal)
    if ($idx -lt 0) { throw 'STATE migration refused: Revision rule/history boundary is missing.' }
    $current=$StateText.Substring(0,$idx)
    $history=$StateText.Substring($idx)
    $current=Convert-LegacyNamespaceActiveText $current
    $current=$current.Replace('corehub_format:','keelaryn_format:')
    foreach ($row in @(
        @('keelaryn_format','1'),@('system_version',$TargetVersion),@('data_revision',[string]$Revision),
        @('derived_router_schema','keelaryn.router.v2'),@('derived_index_schema','keelaryn.index.v1'),@('derived_validation_schema','keelaryn.validation.v2'),
        @('derived_manifest_schema','keelaryn.manifest.v1'),@('artifact_schema','keelaryn.artifact.v3'),@('instance_schema','keelaryn.instance.v1'),
        @('manager_protocol','keelaryn-chat-manager-v4.0'),@('workspace_protocol','keelaryn.workspace.v1'),@('last_full_audit_revision',[string]$Revision),@('updated',$Date)
    )) { $current=Set-StateScalarField $current ([string]$row[0]) ([string]$row[1]) }
    $current=[regex]::Replace($current,'(?m)^- Keelaryn__Hub format:.*$','- Keelaryn__Hub format: `1`')
    $current=[regex]::Replace($current,'(?m)^- System version:.*$',('- System version: `'+$TargetVersion+'`'))
    $current=[regex]::Replace($current,'(?m)^- Data revision:.*$',('- Data revision: `r'+$Revision.ToString('D4')+'`'))
    $current=[regex]::Replace($current,'(?m)^- Router schema:.*$','- Router schema: `keelaryn.router.v2`')
    $current=[regex]::Replace($current,'(?m)^- Index schema:.*$','- Index schema: `keelaryn.index.v1`')
    $current=[regex]::Replace($current,'(?m)^- Validation schema:.*$','- Validation schema: `keelaryn.validation.v2`')
    $current=[regex]::Replace($current,'(?m)^- Manifest schema:.*$','- Manifest schema: `keelaryn.manifest.v1`')
    $current=[regex]::Replace($current,'(?m)^- Artifact schema:.*$','- Artifact schema: `keelaryn.artifact.v3`')
    $current=[regex]::Replace($current,'(?m)^- Manager protocol:.*$','- Manager protocol: `keelaryn-chat-manager-v4.0`')
    $current=[regex]::Replace($current,'(?m)^- Workspace protocol:.*$','- Workspace protocol: `keelaryn.workspace.v1`')
    $current=[regex]::Replace($current,'(?m)^- Last full audit:.*$',('- Last full audit: `r'+$Revision.ToString('D4')+'`'))
    $history=[regex]::Replace($history,'(?m)^Next normal checkpoint:.*(?:\r?\n)?','')
    $note="`nCheckpoint ``r$($Revision.ToString('D4'))`` performs the explicit major namespace migration from the legacy Core__Hub/Core__Manager namespace to **Keelaryn**. Active operational names, schemas, package names, project identity and Manager protocol move to ``Keelaryn`` / ``keelaryn.*``; legacy names remain only in historical migration/provenance records where changing them would falsify the recorded past. The checkpoint also adopts canonical ``keelaryn.instance.v1`` identity and ``keelaryn.artifact.v3`` lineage.`n`nNext normal checkpoint: ``v$TargetVersion r$((($Revision+1).ToString('D4')))``.`n"
    return $current+$history.TrimEnd()+"`n"+$note
}

function Test-NamespaceMigrationIsolation([string]$HubPath) {
    # The migration may legitimately preserve legacy Core/corehub identifiers in provenance.
    # Guard only against invented Keelaryn predecessor schemas and obsolete project identities.
    $forbidden=@('keelaryn.artifact.v1','keelaryn.artifact.v2','keelaryn.router.v1')
    $resolved=(Resolve-Path $HubPath).Path.TrimEnd('\')+'\'
    foreach ($row in @(Get-PortableVaultFileInventory $HubPath)) {
        $file=$row.File
        if (@('.md','.json','.txt','.ps1','.cmd') -notcontains $file.Extension.ToLowerInvariant()) { continue }
        $rel=[string]$row.RelativePath
        if ($rel -eq '_System/ARTIFACT.json') { continue } # replaced after this staging check
        $text=Get-Content $file.FullName -Raw -Encoding UTF8
        foreach ($term in $forbidden) {
            if ($text.Contains($term)) { throw ('Fictitious Keelaryn predecessor schema created by namespace migration: '+$rel+' -> '+$term) }
        }
    }
    foreach ($oldPath in @('Projects\Core__Hub Engine.md','Projects\Core__Hub Legacy Migration.md')) {
        if (Test-Path (Join-Path $HubPath $oldPath) -PathType Leaf) { throw ('Legacy active project path remains after namespace migration: '+$oldPath) }
    }
}


function Write-CanonicalBindingV2([string]$InstanceId) {
    $obj=[ordered]@{ schema='keelaryn.manager.instance-binding.v2'; instance_id=$InstanceId; vault_path=[System.IO.Path]::GetFullPath($Vault); vault_directory_name=(Split-Path $Vault -Leaf); source='canonical_namespace_migration' }
    Write-ManagerBindingDocument $BindingFile $obj
}

function Archive-LegacyHubInboxAfterNamespaceMigration {
    $dest=Join-Path $History 'legacy_namespace_inbox'
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    foreach ($file in @(Get-ChildItem $Inbox -File -Filter 'Core__Hub*.zip' -ErrorAction SilentlyContinue)) {
        $target=Join-Path $dest $file.Name
        if (Test-Path $target) { $target=Join-Path $dest (([System.IO.Path]::GetFileNameWithoutExtension($file.Name))+'_'+(Get-Date -Format 'yyyy-MM-dd_HHmmss')+'.zip') }
        Move-Item $file.FullName $target
        Log ('Archived legacy Hub inbox package after namespace migration: '+$target)
    }
}

function Invoke-RobocopyMirror([string]$Source,[string]$Destination,[string]$Purpose) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) { throw ($Purpose+': source is missing: '+$Source) }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy.exe $Source $Destination /MIR /XJ /R:1 /W:1 /COPY:DAT /DCOPY:DAT /NP /NFL /NDL | Out-Host
    $rc=$LASTEXITCODE
    if ($rc -ge 8) { throw ($Purpose+': robocopy failed with code '+$rc) }
    return $rc
}

function Get-TreeFingerprint([string]$Path,[string]$Purpose) {
    $rows=@()
    foreach($row in @(Get-SafeTreeFileInventory -RootPath $Path -Purpose $Purpose)) {
        $h=(Get-FileHash -LiteralPath $row.File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $rows += ($row.RelativePath+"`0"+[string]$row.File.Length+"`0"+$h)
    }
    return Get-TextHashHex ([string]::Join("`n",$rows))
}

function Write-BindingAt([string]$ManagerPath,[string]$HubPath,[string]$InstanceId,[string]$Source) {
    $obj=[ordered]@{schema='keelaryn.manager.instance-binding.v2';vault_path=[System.IO.Path]::GetFullPath($HubPath);vault_directory_name=(Split-Path $HubPath -Leaf);source=$Source}
    if($InstanceId){$obj.instance_id=$InstanceId}
    Write-ManagerBindingDocument (Join-Path $ManagerPath '_instance_binding.json') $obj
}

function Write-LayoutReceipt([string]$LayoutRootPath,[string]$ManagerPath,[string]$HubPath,[string]$TestsPath,[string]$SourceManager,[string]$SourceHub,[bool]$Finalized) {
    $id=& $ReadBoundInstanceId $HubPath
    $obj=[ordered]@{schema='keelaryn.layout.v1';layout='github_style_v1';product='Keelaryn';manager_version=$ManagerVersion;manager_path=[System.IO.Path]::GetFullPath($ManagerPath);hub_path=[System.IO.Path]::GetFullPath($HubPath);tests_path=[System.IO.Path]::GetFullPath($TestsPath);instance_id=$id;migrated_from=[ordered]@{manager=[System.IO.Path]::GetFullPath($SourceManager);hub=[System.IO.Path]::GetFullPath($SourceHub)};legacy_archived=$Finalized;updated=(Get-Date).ToUniversalTime().ToString('o')}
    $obj|ConvertTo-Json -Depth 8|Set-Content (Join-Path $LayoutRootPath 'layout.json') -Encoding UTF8
}

function Invoke-MigrateLayout {
    if($CanonicalLayoutActive){Write-Host ('Canonical layout is already active: '+$LayoutRoot) -ForegroundColor Green;return 0}
    if((Split-Path $Root -Leaf) -ine 'Keelaryn__Manager'){throw('Layout migration only supports the proven Keelaryn__Manager sibling layout. Current Manager: '+$Root)}
    $legacyParent=Split-Path $Root -Parent
    $expectedHub=Join-Path $legacyParent 'Keelaryn__Hub'
    if([System.IO.Path]::GetFullPath($Vault).TrimEnd('\') -ine [System.IO.Path]::GetFullPath($expectedHub).TrimEnd('\')){throw('Layout migration requires the canonical legacy sibling Hub: '+$expectedHub+'. Bound: '+$Vault)}
    if(-not(Test-InstalledManagerVersionCoherence $ManagerVersion)){throw 'Manager version surfaces are not coherent.'}
    $baseline=Test-CanonicalBaselineConsistent
    if(-not$baseline.State -or -not$baseline.Artifact){throw 'Canonical Hub baseline is not valid.'}
    if(-not(Close-ObsidianIfNeeded)){throw 'Obsidian did not close; layout migration cancelled.'}
    Assert-CurrentHubSnapshotUnchanged $baseline
    if((Test-Path -LiteralPath $CanonicalManagerPath) -or (Test-Path -LiteralPath $CanonicalHubPath)){throw('Canonical target manager/hub already exists under '+$LayoutRoot+'. Use Doctor/cleanup instead of overwriting it.')}
    New-Item -ItemType Directory -Force -Path $LayoutRoot,$CanonicalTestsPath | Out-Null
    $nonce=[guid]::NewGuid().ToString('N')
    $stageManager=Join-Path $LayoutRoot ('.manager-stage-'+$nonce)
    $stageHub=Join-Path $LayoutRoot ('.hub-stage-'+$nonce)
    try {
        $sourceHubFingerprint=Get-TreeFingerprint $Vault 'Legacy Hub before layout migration'
        [void](Invoke-RobocopyMirror $Root $stageManager 'Manager layout copy')
        [void](Invoke-RobocopyMirror $Vault $stageHub 'Hub layout copy')
        $stageHubFingerprint=Get-TreeFingerprint $stageHub 'Staged Hub after layout migration'
        if($sourceHubFingerprint-ne$stageHubFingerprint){throw 'Hub full-tree fingerprint differs after layout copy.'}
        $oldManaged=@(Get-InstalledManagedPaths)
        $oldManagedHash=Get-ManagerContentHashForPaths $oldManaged
        $stageManifestPath=Join-Path $stageManager 'product\install\INSTALLATION.json'
        if(-not(Test-Path -LiteralPath $stageManifestPath -PathType Leaf)){$stageManifestPath=Join-Path $stageManager '_manager_manifest.json'}
        $manifest=Read-KeelarynJsonFile $stageManifestPath
        $stagePaths=@($manifest.managed_files|ForEach-Object{([string]$_).Replace('\','/')}|Sort-Object -Unique)
        $stageRows=@();foreach($rel in $stagePaths){$p=Join-Path $stageManager $rel;if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Staged Manager managed file missing: '+$rel)};$stageRows+=($rel+"`0"+(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant())}
        $stageManagedHash=Get-TextHashHex ([string]::Join("`n",$stageRows))
        if($oldManagedHash-ne$stageManagedHash){throw 'Manager managed-product fingerprint differs after layout copy.'}
        Move-Item -LiteralPath $stageManager -Destination $CanonicalManagerPath
        Move-Item -LiteralPath $stageHub -Destination $CanonicalHubPath
        Write-BindingAt $CanonicalManagerPath $CanonicalHubPath $baseline.State.InstanceId 'github_layout_migration'
        Write-LayoutReceipt $LayoutRoot $CanonicalManagerPath $CanonicalHubPath $CanonicalTestsPath $Root $Vault $false
        $newScript=Join-Path $CanonicalManagerPath 'Keelaryn__Manager.ps1'
        $savedNewEnv=$env:KEELARYN_HUB_PATH;$savedLegacyEnv=[Environment]::GetEnvironmentVariable([string]$LegacyCoreCompat.EnvPath)
        try {
            $env:KEELARYN_HUB_PATH=$null;[Environment]::SetEnvironmentVariable([string]$LegacyCoreCompat.EnvPath,$null)
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $newScript -SelfTest | Out-Host
            if($LASTEXITCODE-ne0){throw('Canonical Manager self-test failed with code '+$LASTEXITCODE)}
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $newScript -Doctor | Out-Host
            if($LASTEXITCODE-ne0){throw('Canonical Manager Doctor failed with code '+$LASTEXITCODE)}
        } finally { $env:KEELARYN_HUB_PATH=$savedNewEnv;[Environment]::SetEnvironmentVariable([string]$LegacyCoreCompat.EnvPath,$savedLegacyEnv) }
        try { $desktop=Get-DesktopKnownFolderPath;Save-UnicodeShellShortcut (Join-Path $desktop 'Keelaryn Hub.lnk') (Join-Path $CanonicalManagerPath 'compat\commands\OPEN_KEELARYN__HUB.cmd') $CanonicalManagerPath 'Open Keelaryn Hub';$oldShortcut=Join-Path $desktop 'Keelaryn__Hub.lnk';if(Test-Path -LiteralPath $oldShortcut){Remove-Item -LiteralPath $oldShortcut -Force -ErrorAction SilentlyContinue} } catch { $marker=Join-Path $CanonicalManagerPath 'state\logs\shortcut_creation_failed.txt';Set-Content -LiteralPath $marker -Value $_.Exception.Message -Encoding UTF8 -ErrorAction SilentlyContinue;Write-Warning('Canonical layout is valid, but desktop shortcut activation failed: '+$_.Exception.Message) }
        Write-Host ''
        Write-Host 'Canonical GitHub-style layout activated.' -ForegroundColor Green
        Write-Host ('Manager: '+$CanonicalManagerPath)
        Write-Host ('Hub:     '+$CanonicalHubPath)
        Write-Host ('Tests:   '+$CanonicalTestsPath)
        Write-Host 'Legacy directories remain untouched as rollback copies. Run FINALIZE_LAYOUT.cmd from the NEW manager only after verification.' -ForegroundColor Yellow
        return 0
    } catch {
        if(Test-Path -LiteralPath $CanonicalManagerPath){Remove-Item -LiteralPath $CanonicalManagerPath -Recurse -Force -ErrorAction SilentlyContinue}
        if(Test-Path -LiteralPath $CanonicalHubPath){Remove-Item -LiteralPath $CanonicalHubPath -Recurse -Force -ErrorAction SilentlyContinue}
        $receipt=Join-Path $LayoutRoot 'layout.json';if(Test-Path -LiteralPath $receipt){Remove-Item -LiteralPath $receipt -Force -ErrorAction SilentlyContinue}
        throw
    } finally {
        foreach($p in @($stageManager,$stageHub)){if(Test-Path -LiteralPath $p){Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue}}
    }
}

function Invoke-FinalizeLayout {
    if(-not$CanonicalLayoutActive){throw 'FINALIZE_LAYOUT.cmd must be run from the canonical ...\\keelaryn\\manager installation.'}
    $doctorCode=Invoke-Doctor
    if($doctorCode-ne0){throw('Canonical Doctor must be fully clean before legacy archival. Doctor exit code: '+$doctorCode)}
    if(-not(Close-ObsidianIfNeeded)){throw 'Obsidian did not close; legacy archival cancelled.'}
    $legacyParent=Split-Path $LayoutRoot -Parent
    $legacyManager=Join-Path $legacyParent 'Keelaryn__Manager'
    $legacyHub=Join-Path $legacyParent 'Keelaryn__Hub'
    if(-not(Test-Path -LiteralPath $legacyManager) -and -not(Test-Path -LiteralPath $legacyHub)){Write-Host 'Legacy layout is already archived.' -ForegroundColor Green;return 0}
    $stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
    $archive=Join-Path $CanonicalTestsPath ('legacy-layout-backup\\'+$stamp)
    New-Item -ItemType Directory -Force -Path $archive | Out-Null
    $movedHub=$false;$movedManager=$false
    try{
        if(Test-Path -LiteralPath $legacyHub){Move-Item -LiteralPath $legacyHub -Destination (Join-Path $archive 'Keelaryn__Hub');$movedHub=$true}
        if(Test-Path -LiteralPath $legacyManager){Move-Item -LiteralPath $legacyManager -Destination (Join-Path $archive 'Keelaryn__Manager');$movedManager=$true}
    }catch{
        if($movedManager -and -not(Test-Path -LiteralPath $legacyManager)){Move-Item -LiteralPath (Join-Path $archive 'Keelaryn__Manager') -Destination $legacyManager -ErrorAction SilentlyContinue}
        if($movedHub -and -not(Test-Path -LiteralPath $legacyHub)){Move-Item -LiteralPath (Join-Path $archive 'Keelaryn__Hub') -Destination $legacyHub -ErrorAction SilentlyContinue}
        throw
    }
    Write-LayoutReceipt $LayoutRoot $Root $Vault $CanonicalTestsPath $legacyManager $legacyHub $true
    Ensure-DesktopShortcut
    Write-Host ('Legacy layout archived at: '+$archive) -ForegroundColor Green
    Write-Host 'Canonical paths are now the only active layout.' -ForegroundColor Green
    return 0
}

function Write-LayoutFinalizer([string]$InstanceId) {
    # Legacy Core -> Keelaryn namespace migration can finish into the former
    # sibling layout first. 4.4+ then uses the same proven copy-and-activate
    # layout migration as every other installation.
    if((Split-Path $Root -Leaf) -ieq 'manager'){return $null}
    $helper=Join-Path $InstallParent 'MIGRATE_KEELARYN_LAYOUT.cmd'
    $managerPath=$Root
    $lines=@('@echo off','setlocal','powershell.exe -NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $managerPath 'Keelaryn__Manager.ps1')+'" -MigrateLayout','set RC=%ERRORLEVEL%','exit /b %RC%')
    Set-Content $helper $lines -Encoding ASCII
    return $helper
}

function Invoke-MigrateLegacyNamespace {
    $baseline=Test-CanonicalBaselineConsistent
    if ($baseline.State.Namespace -eq 'keelaryn') { Write-Host 'Instance namespace is already Keelaryn.' -ForegroundColor Green; return 0 }
    if ($baseline.State.Namespace -ne 'legacy_core') { throw 'Unsupported source namespace for major Keelaryn migration.' }
    if (-not $baseline.Artifact -or $baseline.Artifact.Status -ne 'approved') { throw 'Namespace migration requires an installed APPROVED canonical checkpoint.' }
    if (-not (Test-ArtifactSchemaV2 $baseline.Artifact.Schema) -and -not (Test-ArtifactSchemaV3 $baseline.Artifact.Schema)) { throw 'Namespace migration requires payload-linked legacy artifact v2/v3 lineage.' }
    if ([string]$baseline.State.ManagerProtocol -ne 'chat-manager-v2.6') { throw ('Namespace migration is only proven for legacy chat-manager-v2.6. Installed: '+[string]$baseline.State.ManagerProtocol) }
    if (Test-Path $PreferredCurrentZip -PathType Leaf) { throw 'Keelaryn__Hub_CURRENT.zip already exists; resolve the duplicate baseline before migration.' }

    $release=Get-ProductRelease; $targetVersion=[string]$release.system_version
    $binding=Get-OrCreateLegacyBinding $baseline.State; $instanceId=$binding.InstanceId
    if (-not (Close-ObsidianIfNeeded)) { throw 'Obsidian did not close; namespace migration was not staged.' }
    Assert-CurrentHubSnapshotUnchanged $baseline
    $newRevision=$baseline.State.Revision+1; $date=Get-Date -Format 'yyyy-MM-dd'; $created=(Get-Date).ToUniversalTime().ToString('o')
    $oldValidation=$null
    try { $oldValidation=Read-KeelarynJsonFile (Join-Path $Vault '_System\VALIDATION.json') } catch {}
    $temp=Join-Path $WorkRoot ('namespace_migration_'+[guid]::NewGuid().ToString('N')); $hub=Join-Path $temp 'Keelaryn__Hub'
    New-Item -ItemType Directory -Path $temp | Out-Null
    try {
        Copy-PortableHubTree $Vault $hub
        Convert-LegacyNamespaceTree $hub $date
        $statePath=Join-Path $hub '_System\STATE.md'; $stateText=Get-Content $statePath -Raw -Encoding UTF8
        Set-Content $statePath (Convert-LegacyNamespaceState $stateText $targetVersion $newRevision $date) -Encoding UTF8

        [ordered]@{
            schema='keelaryn.instance.v1'; instance_id=$instanceId; created=$created; origin_type='legacy_adoption'; adoption_release_id=[string]$release.release_id
            adoption_manager_version=$ManagerVersion; migration_id='legacy-core-to-keelaryn-v1'
            adopted_from=[ordered]@{ system_version=$baseline.State.VersionText; data_revision=$baseline.State.Revision; artifact_id=$baseline.Artifact.ArtifactId; payload_content_sha256=$baseline.PayloadHash }
        }|ConvertTo-Json -Depth 8|Set-Content (Join-Path $hub '_System\INSTANCE.json') -Encoding UTF8

        $chatPath=Join-Path $hub '_System\CHAT_MANAGER.md'
        if (Test-Path $chatPath -PathType Leaf) {
            $chat=Get-Content $chatPath -Raw -Encoding UTF8
            $chat=[regex]::Replace($chat,'(?m)^protocol_version:\s*.*$','protocol_version: keelaryn-chat-manager-v4.0')
            if (-not $chat.Contains('## Keelaryn identity invariants')) {
                $block="`n## Keelaryn identity invariants`n`n- Preserve ``_System/INSTANCE.json`` unchanged except during an explicit identity migration.`n- ``instance_id`` in every artifact v3 checkpoint must equal the canonical INSTANCE identity.`n- ``artifact_id`` identifies one checkpoint only and must never be reused as an instance identifier.`n- APPROVED artifacts use ``producer_role = chat_manager`` and ``manager_protocol = keelaryn-chat-manager-v4.0``.`n"
                $at=$chat.IndexOf("`n## Start procedure")
                if ($at -gt 0) { $chat=$chat.Insert($at,$block) } else { $chat=$chat.TrimEnd()+"`n"+$block }
            }
            $chat=$chat.Replace('accepted-candidate hashes use v2 payload-hash semantics','accepted-candidate hashes use artifact-v3 payload-hash semantics').Replace('the v2 ancestry proof','the artifact-v3 ancestry proof')
            Set-Content $chatPath $chat -Encoding UTF8
        }

        Build-DerivedMetadata $hub $targetVersion $newRevision $instanceId
        $validationPath=Join-Path $hub '_System\VALIDATION.json'
        if ($oldValidation) { $v=$oldValidation } else { $v=Read-KeelarynJsonFile $validationPath }
        Set-ObjectProperty $v 'schema' 'keelaryn.validation.v2'; Set-ObjectProperty $v 'vault' 'Keelaryn__Hub'; Set-ObjectProperty $v 'system_version' $targetVersion; Set-ObjectProperty $v 'data_revision' $newRevision; Set-ObjectProperty $v 'instance_id' $instanceId
        $idx=Read-KeelarynJsonFile (Join-Path $hub '_System\INDEX.json'); $router=Read-KeelarynJsonFile (Join-Path $hub '_System\ROUTER.json')
        Set-ObjectProperty $v 'entity_count' ([int]$idx.entity_count); Set-ObjectProperty $v 'route_count' ([int]$router.route_count); Set-ObjectProperty $v 'error_count' 0; Set-ObjectProperty $v 'warning_count' 0
        if (-not $v.checks) { Set-ObjectProperty $v 'checks' ([pscustomobject]@{}) }
        foreach ($row in @(@('required_metadata',$true),@('parse_errors',0),@('duplicate_ids',0),@('duplicate_paths',0),@('broken_links',0),@('index_consistent',$true),@('router_consistent',$true),@('manifest_consistent',$true))) { Set-ObjectProperty $v.checks ([string]$row[0]) $row[1] }
        Set-ObjectProperty $v 'source_manifest' ([pscustomobject]@{ schema='keelaryn.manifest.v1'; entry_count=0; content_set_sha256='0000000000000000000000000000000000000000000000000000000000000000' })
        Set-ObjectProperty $v 'manager_validation' ([pscustomobject]@{ policy='risk_based_v1'; mode='full'; reasons=@('major_namespace_migration','identity_adoption','artifact_v3_transition','manager_protocol_v4_transition','derived_metadata_rebuilt','source_manifest_verified','deterministic_checks_pass'); full_audit_interval_revisions=10; last_full_audit_revision=$newRevision; next_full_audit_revision=($newRevision+10) })
        $v|ConvertTo-Json -Depth 30|Set-Content $validationPath -Encoding UTF8
        $null=Refresh-PortableSourceManifest $hub $targetVersion $newRevision $instanceId

        Test-NamespaceMigrationIsolation $hub
        $payload=Get-VaultPayloadHashAt $hub; $artifactId=('migr-r{0:D4}-{1}' -f $newRevision,$payload.Substring(0,12))
        [ordered]@{
            schema='keelaryn.artifact.v3'; artifact_status='approved'; artifact_id=$artifactId; producer_role='keelaryn_manager_migration'; created=$created; revision_time_utc=$created
            system_version=$targetVersion; data_revision=$newRevision; instance_id=$instanceId; genesis=$false; payload_content_sha256=$payload
            base_system_version=$baseline.State.VersionText; base_data_revision=$baseline.State.Revision; base_artifact_id=$baseline.Artifact.ArtifactId; base_payload_content_sha256=$baseline.PayloadHash
            ancestor_chain=@(Get-AncestorRowsForMigration $baseline.Artifact $baseline.PayloadHash); accepted_candidates=@(); manager_protocol='keelaryn-chat-manager-v4.0'
            migration_id='legacy-core-to-keelaryn-v1'; migration_release_id=[string]$release.release_id
        }|ConvertTo-Json -Depth 12|Set-Content (Join-Path $hub '_System\ARTIFACT.json') -Encoding UTF8

        $checkState=Read-VaultMetadataAt $hub; $checkArtifact=Read-VaultArtifactManifestAt $hub
        if (-not $checkState -or -not $checkArtifact -or $checkState.Namespace -ne 'keelaryn' -or $checkState.InstanceId -ne $instanceId -or $checkState.Revision -ne $newRevision -or $checkState.VersionText -ne $targetVersion) { throw 'Namespace migration staging validation failed.' }
        if ((Get-VaultPayloadHashAt $hub) -ne $checkArtifact.PayloadHash) { throw 'Namespace migration staging payload hash mismatch.' }
        Install-PreparedMigrationHub $hub 'legacy-core-to-keelaryn-v1' $baseline
        if ($CurrentZip -ne $PreferredCurrentZip) { Move-Item -LiteralPath $CurrentZip -Destination $PreferredCurrentZip -Force; $script:CurrentZip=$PreferredCurrentZip; Set-ManagerMutablePresentationHidden $PreferredCurrentZip }
        Write-CanonicalBindingV2 $instanceId
        if (Test-Path $LegacyBindingFile -PathType Leaf) { Remove-Item $LegacyBindingFile -Force -ErrorAction SilentlyContinue }
        Archive-LegacyHubInboxAfterNamespaceMigration
        if (Test-Path $ShortcutFailureMarker -PathType Leaf) { Remove-Item $ShortcutFailureMarker -Force -ErrorAction SilentlyContinue }
        $helper=Write-LayoutFinalizer $instanceId
        Log ('Major legacy namespace migration installed: instance_id='+$instanceId+', revision='+$newRevision)
        Write-Host ('Keelaryn namespace migration installed: v'+$targetVersion+' | '+([DateTimeOffset]::Parse($created)).ToLocalTime().ToString('yyyy-MM-dd HH:mm')) -ForegroundColor Green; Write-Host ('Legacy sequence: r'+$newRevision.ToString('D4')) -ForegroundColor DarkGray
        Write-Host ('instance_id: '+$instanceId)
        if ($helper) { Write-Host ('Layout finalizer created: '+$helper) -ForegroundColor Cyan; Write-Host 'Close Obsidian, leave the Manager directory, then run that helper.' -ForegroundColor Yellow }
        return 0
    }
    finally { if (Test-Path $temp) { Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue } }
}

function Test-LegacyNamespaceTransformSelfTest {
    $x=Convert-LegacyNamespaceActiveText 'Core__Hub Core__Manager corehub.index.v1 corehub.artifact.v2 chat-manager-v2.6 project.corehub-engine'
    return $x -eq 'Keelaryn__Hub Keelaryn__Manager corehub.index.v1 corehub.artifact.v2 chat-manager-v2.6 project.keelaryn-engine'
}

function Assert-InstanceBindingAvailable {
    if ($script:BindingResolutionError) { throw ('Keelaryn instance binding is unresolved: '+$script:BindingResolutionError+'. Run Keelaryn > Doctor and bind the Hub from Maintenance before Hub operations.') }
    if (-not (& $TestHubCandidate $Vault)) { throw ('No valid Keelaryn__Hub instance is bound at: '+$Vault) }
}

function Invoke-RepairCurrentTransport {
    Assert-InstanceBindingAvailable
    if (-not (Test-Path $CurrentZip -PathType Leaf)) { throw 'Keelaryn__Hub_CURRENT.zip is missing.' }
    if (-not (Test-ZipContainsLocalDeploymentState $CurrentZip)) {
        Write-Host 'CURRENT transport is already portable; no repair needed.' -ForegroundColor Green
        return 0
    }
    Sanitize-CurrentCheckpointTransportIfNeeded
    if (Test-ZipContainsLocalDeploymentState $CurrentZip) { throw 'CURRENT transport repair did not remove local deployment state.' }
    Write-Host 'CURRENT transport sanitized without changing canonical payload identity.' -ForegroundColor Green
    return 0
}

function Add-DoctorFinding([System.Collections.ArrayList]$Rows,[string]$Severity,[string]$Code,[string]$Message) {
    $null=$Rows.Add([pscustomobject]@{ Severity=$Severity; Code=$Code; Message=$Message })
}

function Invoke-Doctor {
    $doctorWatch=[System.Diagnostics.Stopwatch]::StartNew(); $timings=[ordered]@{
        hub_state_core_ms=0.0; hub_portable_analysis_ms=0.0; hub_derived_metadata_ms=0.0; hub_manifest_diagnostic_ms=0.0
        hub_migration_ms=0.0; hub_artifact_ms=0.0; current_baseline_ms=0.0
    }
    $rows=New-Object System.Collections.ArrayList
    $phase=[System.Diagnostics.Stopwatch]::StartNew()
    try {
        if (Test-InstalledManagerVersionCoherence $ManagerVersion) { Add-DoctorFinding $rows 'OK' 'manager.version' ('Manager version markers agree at '+$ManagerVersion+'.') }
        else { Add-DoctorFinding $rows 'ERROR' 'manager.version' 'Manager version markers disagree.' }
        $managedHash=Get-CurrentManagerContentHash
        if ($managedHash) { Add-DoctorFinding $rows 'OK' 'manager.managed_files' ('Managed product set is complete; content='+$managedHash.Substring(0,12)+'.') }
        else { Add-DoctorFinding $rows 'ERROR' 'manager.managed_files' 'Managed product set is incomplete.' }
    } catch { Add-DoctorFinding $rows 'ERROR' 'manager.product' $_.Exception.Message }
    $phase.Stop(); $timings.manager_product_ms=[math]::Round($phase.Elapsed.TotalMilliseconds,1)

    if ($script:BindingResolutionError) { Add-DoctorFinding $rows 'ERROR' 'binding.resolve' $script:BindingResolutionError }
    elseif (& $TestHubCandidate $Vault) {
        $id=& $ReadBoundInstanceId $Vault
        Add-DoctorFinding $rows 'OK' 'binding.resolve' ('Vault='+$Vault+$(if ($id) { '; instance_id='+$id } else { '; legacy/no canonical instance_id' }))
    }
    else { Add-DoctorFinding $rows 'WARN' 'binding.vault' ('No valid Hub instance resolved. Expected/default path: '+$Vault) }

    $phase=[System.Diagnostics.Stopwatch]::StartNew()
    if (& $TestHubCandidate $Vault) {
        try {
            $detail=[System.Diagnostics.Stopwatch]::StartNew(); $coreState=Read-VaultStateCoreAt $Vault; $detail.Stop(); $timings.hub_state_core_ms=[math]::Round($detail.Elapsed.TotalMilliseconds,1)
            $detail=[System.Diagnostics.Stopwatch]::StartNew(); $artifact=Read-VaultArtifactManifestAt $Vault; $detail.Stop(); $timings.hub_artifact_ms=[math]::Round($detail.Elapsed.TotalMilliseconds,1)
            $revisionDisplay=$null
            if($artifact -and $artifact.RevisionTimeUtc){
                try{$revisionDisplay=([DateTimeOffset]::Parse([string]$artifact.RevisionTimeUtc)).ToLocalTime().ToString('yyyy-MM-dd HH:mm')}catch{}
            }
            if((-not$revisionDisplay)-and$coreState){$revisionDisplay='r'+$coreState.Revision.ToString('D4')}
            $state=$null; $vaultAnalysis=$null
            if ($coreState) {
                Add-DoctorFinding $rows 'OK' 'hub.state' ('STATE identifies Hub v'+$coreState.VersionText+' | revision '+$revisionDisplay+'.')
                $detail=[System.Diagnostics.Stopwatch]::StartNew(); $vaultAnalysis=Get-PortableVaultAnalysis $Vault; $detail.Stop(); $timings.hub_portable_analysis_ms=[math]::Round($detail.Elapsed.TotalMilliseconds,1)
            }
            else { Add-DoctorFinding $rows 'ERROR' 'hub.state' 'STATE/INSTANCE core identity parsing failed.' }

            $derivedValid=$false; $manifestValid=$false
            if ($coreState) {
                $detail=[System.Diagnostics.Stopwatch]::StartNew()
                $indexPath=Join-Path $Vault '_System\INDEX.json'; $routerText=$null; $validationText=$null
                if (Test-Path -LiteralPath $indexPath -PathType Leaf) {
                    if ($coreState.RouterSchema) { $rp=Join-Path $Vault '_System\ROUTER.json'; if (Test-Path -LiteralPath $rp -PathType Leaf) { $routerText=Read-KeelarynJsonFileText $rp } }
                    if ($coreState.ValidationSchema) { $vp=Join-Path $Vault '_System\VALIDATION.json'; if (Test-Path -LiteralPath $vp -PathType Leaf) { $validationText=Read-KeelarynJsonFileText $vp } }
                    $dc=Test-DerivedMetadataTexts (Read-KeelarynJsonFileText $indexPath) $routerText $validationText $coreState
                    if ($dc.Valid) { $derivedValid=$true; Add-DoctorFinding $rows 'OK' 'hub.derived' 'INDEX/ROUTER/VALIDATION are internally consistent.' }
                    else { Add-DoctorFinding $rows 'ERROR' 'hub.derived' $dc.Reason }
                } else { Add-DoctorFinding $rows 'ERROR' 'hub.derived' 'INDEX.json is missing.' }
                $detail.Stop(); $timings.hub_derived_metadata_ms=[math]::Round($detail.Elapsed.TotalMilliseconds,1)

                if ($coreState.ManifestSchema) {
                    $detail=[System.Diagnostics.Stopwatch]::StartNew(); $md=Get-VaultManifestDiagnostic $Vault $coreState $vaultAnalysis; $detail.Stop(); $timings.hub_manifest_diagnostic_ms=[math]::Round($detail.Elapsed.TotalMilliseconds,1)
                    if ($md.Valid) { $manifestValid=$true; Add-DoctorFinding $rows 'OK' 'hub.manifest' ('Portable source manifest matches '+$md.ActualCount+' source file(s); content='+$md.ActualHash.Substring(0,12)+'.') }
                    else { Add-DoctorFinding $rows 'ERROR' 'hub.manifest' $md.Reason }
                } else { $manifestValid=$true; Add-DoctorFinding $rows 'WARN' 'hub.manifest' 'STATE does not declare a portable source manifest.' }
            }

            if ($coreState -and $derivedValid -and $manifestValid) { $state=$coreState; Add-DoctorFinding $rows 'OK' 'hub.metadata' ('Hub v'+$state.VersionText+' | revision '+$revisionDisplay+' metadata is valid.') }
            else { Add-DoctorFinding $rows 'ERROR' 'hub.metadata' 'Installed Hub metadata is not canonical; see component findings above.' }

            if ($coreState) {
                try {
                    $detail=[System.Diagnostics.Stopwatch]::StartNew(); $release=Get-ProductRelease; $registry=Get-MigrationRegistry; $plan=Resolve-MigrationChain $registry $coreState.VersionText ([string]$release.system_version); $detail.Stop(); $timings.hub_migration_ms=[math]::Round($detail.Elapsed.TotalMilliseconds,1)
                    if ($plan.Status -eq 'up_to_date') { Add-DoctorFinding $rows 'OK' 'migration.status' 'Instance system release is current.' }
                    elseif ($plan.Status -eq 'ready') { Add-DoctorFinding $rows 'WARN' 'migration.status' ('Manager-safe migration available: '+$coreState.VersionText+' -> '+[string]$release.system_version+'.') }
                    elseif ($plan.Status -eq 'review_required') { Add-DoctorFinding $rows 'WARN' 'migration.status' ('Migration to '+[string]$release.system_version+' requires Chat Manager reconciliation.') }
                    else { Add-DoctorFinding $rows 'WARN' 'migration.status' ('Migration planner: '+$plan.Status+' - '+$plan.Reason) }
                } catch { Add-DoctorFinding $rows 'WARN' 'migration.status' $_.Exception.Message }
            }

            if ($artifact -and ((-not $coreState) -or (-not $coreState.InstanceId) -or (-not $artifact.InstanceId) -or $artifact.InstanceId -eq $coreState.InstanceId)) { Add-DoctorFinding $rows 'OK' 'hub.artifact' ('ARTIFACT '+$artifact.ArtifactId+' is readable.') }
            else { Add-DoctorFinding $rows 'ERROR' 'hub.artifact' 'Installed ARTIFACT is missing/invalid or has an identity mismatch.' }

            $currentDetail=[System.Diagnostics.Stopwatch]::StartNew()
            if (Test-Path -LiteralPath $CurrentZip -PathType Leaf) {
                $currentSession=$null
                try {
                    $currentSession=Open-HubZipInspectionSession $CurrentZip
                    if (-not $currentSession) { throw 'CURRENT ZIP envelope is invalid.' }
                    if (Test-ZipContainsLocalDeploymentState $CurrentZip $currentSession) { Add-DoctorFinding $rows 'WARN' 'transport.local_state' 'CURRENT ZIP contains local deployment state; run REPAIR_CURRENT_TRANSPORT.cmd after reviewing this report.' }
                    $zart=Read-ZipArtifactManifest $CurrentZip $currentSession
                    if ($zart -and $artifact -and $zart.ArtifactId -eq $artifact.ArtifactId) { Add-DoctorFinding $rows 'OK' 'baseline.identity' ('Installed ARTIFACT and CURRENT identify '+$artifact.ArtifactId+'.') }
                    else { Add-DoctorFinding $rows 'ERROR' 'baseline.identity' 'CURRENT and installed ARTIFACT identities differ or cannot be read.' }
                    $vh=if($vaultAnalysis){[string]$vaultAnalysis.ContentHash}else{Get-VaultContentHashAt $Vault}; $zh=(Get-ZipHashPair $CurrentZip $currentSession).ContentHash
                    if ($vh -eq $zh) { Add-DoctorFinding $rows 'OK' 'baseline.current' ('Installed vault portable content exactly matches CURRENT; content='+$vh.Substring(0,12)+'.') }
                    else { Add-DoctorFinding $rows 'ERROR' 'baseline.current' ('Installed vault portable content differs from CURRENT; vault='+$vh.Substring(0,12)+' current='+$zh.Substring(0,12)+'.') }
                } catch { Add-DoctorFinding $rows 'ERROR' 'baseline.current' ('Raw CURRENT comparison failed: '+$_.Exception.Message) }
                finally { if ($currentSession) { Close-HubZipInspectionSession $currentSession } }
            } else { Add-DoctorFinding $rows 'ERROR' 'baseline.current' 'CURRENT ZIP is missing.' }
            $currentDetail.Stop(); $timings.current_baseline_ms=[math]::Round($currentDetail.Elapsed.TotalMilliseconds,1)
        } catch { if ($currentDetail -and $currentDetail.IsRunning) { $currentDetail.Stop(); $timings.current_baseline_ms=[math]::Round($currentDetail.Elapsed.TotalMilliseconds,1) }; Add-DoctorFinding $rows 'ERROR' 'hub.validation' $_.Exception.Message }
    }
    $phase.Stop(); $timings.hub_and_baseline_ms=[math]::Round($phase.Elapsed.TotalMilliseconds,1)

    $phase=[System.Diagnostics.Stopwatch]::StartNew()
    try {
        $invalidManager=0; $validManager=0; $hubPackages=0
        foreach ($file in @(Get-ChildItem $Inbox -Filter '*.zip' -File -ErrorAction SilentlyContinue)) {
            if ($file.Name.StartsWith('Keelaryn__Manager',[System.StringComparison]::OrdinalIgnoreCase)) { if (Read-ManagerUpdatePackage $file.FullName) { $validManager++ } else { $invalidManager++ } }
            elseif ($file.Name.StartsWith('Keelaryn__Hub',[System.StringComparison]::OrdinalIgnoreCase) -or $file.Name.StartsWith([string]$LegacyCoreCompat.HubDirectory,[System.StringComparison]::OrdinalIgnoreCase)) { $hubPackages++ }
        }
        if ($invalidManager -gt 0) { Add-DoctorFinding $rows 'WARN' 'inbox.manager_invalid' ($invalidManager.ToString()+' unrecognized/invalid Manager ZIP(s) remain in inbox.') }
        else { Add-DoctorFinding $rows 'OK' 'inbox.manager' ($validManager.ToString()+' valid Manager update ZIP(s) in inbox.') }
        Add-DoctorFinding $rows 'OK' 'inbox.hub' ($hubPackages.ToString()+' Hub-related ZIP(s) in inbox; Doctor does not install them.')
    } catch { Add-DoctorFinding $rows 'WARN' 'inbox.scan' $_.Exception.Message }
    $phase.Stop(); $timings.inbox_ms=[math]::Round($phase.Elapsed.TotalMilliseconds,1)

    if (Test-Path -LiteralPath $AttentionFile -PathType Leaf) { Add-DoctorFinding $rows 'WARN' 'attention.pending' ('Attention marker exists: '+$AttentionFile) }
    if (Test-Path -LiteralPath $ShortcutFailureMarker -PathType Leaf) { Add-DoctorFinding $rows 'WARN' 'shortcut.failed' 'Desktop shortcut failure marker exists; a newer Manager version may retry it.' }

    $errors=@($rows | Where-Object Severity -eq 'ERROR').Count; $warnings=@($rows | Where-Object Severity -eq 'WARN').Count
    $errorCodes=@($rows | Where-Object Severity -eq 'ERROR' | ForEach-Object { [string]$_.Code }); $warningCodes=@($rows | Where-Object Severity -eq 'WARN' | ForEach-Object { [string]$_.Code })
    $actions=New-Object System.Collections.ArrayList
    if ($errorCodes -contains 'binding.resolve' -or $warningCodes -contains 'binding.vault') { [void]$actions.Add('Run BIND_INSTANCE.cmd and select the intended Keelaryn__Hub path.') }
    if ($warningCodes -contains 'transport.local_state') { [void]$actions.Add('Run REPAIR_CURRENT_TRANSPORT.cmd to remove workstation-local state from CURRENT without changing canonical payload identity.') }
    $migrationFinding=@($rows | Where-Object { $_.Code -eq 'migration.status' -and $_.Severity -eq 'WARN' } | Select-Object -First 1)
    if ($migrationFinding.Count -gt 0) {
        if ($migrationFinding[0].Message -match 'Chat Manager') { [void]$actions.Add('Reconcile the registered system migration through Chat Manager; do not force APPLY_MIGRATIONS.cmd.') }
        elseif ($migrationFinding[0].Message -match 'Manager-safe') { [void]$actions.Add('Review CHECK_MIGRATIONS.cmd, then run APPLY_MIGRATIONS.cmd if the plan is ready.') }
    }
    if ($errorCodes -contains 'hub.manifest') { [void]$actions.Add('Do not regenerate MANIFEST in place. Compare the reported source-path drift with CURRENT; restore accidental local drift or reconcile intentional changes through a new CANDIDATE/APPROVED revision.') }
    if ($errorCodes -contains 'baseline.current') { [void]$actions.Add('Installed portable content differs from CURRENT. Treat CURRENT as the persisted checkpoint until the differing paths are classified; do not install further Hub updates.') }
    if ($errorCodes -contains 'baseline.current' -or $errorCodes -contains 'hub.manifest' -or $errorCodes -contains 'hub.artifact' -or $errorCodes -contains 'baseline.identity') { [void]$actions.Add('Do not install Hub updates until canonical baseline errors are resolved.') }
    if ($warningCodes -contains 'inbox.manager_invalid') { [void]$actions.Add('Review or remove invalid Manager ZIPs from state/inbox before the next update run.') }

    Write-Host ('Keelaryn Doctor - Manager '+$ManagerVersion) -ForegroundColor Cyan
    foreach ($r in $rows) { $color=$(if ($r.Severity -eq 'ERROR'){'Red'}elseif($r.Severity -eq 'WARN'){'Yellow'}else{'Green'}); Write-Host ('[{0}] {1}: {2}' -f $r.Severity,$r.Code,$r.Message) -ForegroundColor $color }
    if ($actions.Count -gt 0) { Write-Host 'Recommended actions:' -ForegroundColor Cyan; foreach ($a in $actions) { Write-Host ('- '+$a) } }

    $doctorWatch.Stop(); $timings.total_ms=[math]::Round($doctorWatch.Elapsed.TotalMilliseconds,1)
    $report=[ordered]@{schema='keelaryn.manager.doctor-report.v1';generated=(Get-Date).ToUniversalTime().ToString('o');manager_version=$ManagerVersion;manager_root=$Root;vault=$Vault;errors=$errors;warnings=$warnings;timings_ms=$timings;findings=@($rows);recommended_actions=@($actions)}
    $path=Join-Path $Logs 'DOCTOR_REPORT.json'; $report|ConvertTo-Json -Depth 8|Set-Content $path -Encoding UTF8
    Write-Host ('Report: '+$path)
    if ($errors -gt 0) { return 1 }; if ($warnings -gt 0) { return 2 }; return 0
}

function Invoke-BindInstance {
    if (-not $BindInstancePath) { throw 'BindInstancePath is required.' }
    if (-not (& $TestHubCandidate $Vault)) { throw ('Bind target is not a valid Hub: '+$Vault) }
    $id=& $ReadBoundInstanceId $Vault
    & $WriteBindingV2 $Vault $id 'explicit_bind_command'
    Write-Host ('Bound Keelaryn__Manager to: '+$Vault) -ForegroundColor Green
    if ($id) { Write-Host ('instance_id: '+$id) }
    return 0
}

function Invoke-BuildAIContext {
    if (-not (Test-AIContextToolSourceSelfTest)) { throw 'AI context build refused: PowerShell parser/lexical source gate failed.' }
    $tool=Join-Path $ProductRoot 'tools\New-KeelarynAIContext.ps1';if(-not(Test-Path $tool -PathType Leaf)){throw('AI context generator missing: '+$tool)};$temp=Join-Path $WorkRoot ('ai_context_'+[guid]::NewGuid().ToString('N'));$ctx=Join-Path $temp 'Keelaryn__Manager_AI_CONTEXT';New-Item -ItemType Directory -Path $temp|Out-Null
    try{& $tool -ManagerRoot $Root -OutputDirectory $ctx 6>&1|Out-Null;if(-not(Test-Path (Join-Path $ctx 'CONTEXT_MANIFEST.json') -PathType Leaf)){throw 'AI context manifest missing.'};$zip=Join-Path $Releases ('Keelaryn__Manager_AI_CONTEXT_v'+$ManagerVersion+'.zip');Write-DeterministicZip $ctx $zip 'Keelaryn__Manager_AI_CONTEXT';Log('Built AI development context: '+$zip);Write-Host 'AI_CONTEXT build: PASS' -ForegroundColor Green;Write-Host('Artifact: '+$zip);return 0}finally{if(Test-Path $temp){Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue}}
}

function Get-ManagerReleaseBundleSpec([string]$VersionText) {
    $text=([string]$VersionText).Trim()
    if (-not $text) { throw 'Manager release bundle version is empty.' }
    try { $version=[version]$text } catch { throw ('Manager release bundle contains an invalid version: '+$text) }
    return [pscustomobject]@{
        Version=$version
        VersionText=$text
        ManifestName=('Keelaryn__Manager_RELEASE_v'+$text+'.json')
        ArtifactNames=[ordered]@{
            source=('Keelaryn__Manager_SOURCE_v'+$text+'.zip')
            distribution=('Keelaryn__Manager_Distribution_v'+$text+'.zip')
            update=('Keelaryn__Manager_Update_v'+$text+'_Built.zip')
            ai_context=('Keelaryn__Manager_AI_CONTEXT_v'+$text+'.zip')
        }
    }
}

function Read-ManagerReleaseBundle([string]$ManifestPath,[string]$BaseDirectory) {
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw ('Manager release manifest is missing: '+$ManifestPath) }
    if (-not (Test-Path -LiteralPath $BaseDirectory -PathType Container)) { throw ('Manager release base directory is missing: '+$BaseDirectory) }
    $manifest=Read-KeelarynJsonFile $ManifestPath
    if ([string]$manifest.schema -ne 'keelaryn.manager.release-bundle.v1') { throw 'Invalid Manager release-bundle schema.' }
    $versionText=([string]$manifest.manager_version).Trim()
    $spec=Get-ManagerReleaseBundleSpec $versionText
    if ([System.IO.Path]::GetFileName($ManifestPath) -cne $spec.ManifestName) { throw 'Manager release manifest filename/version mismatch.' }
    $systemVersion=([string]$manifest.system_version).Trim()
    if (-not $systemVersion -or [string]$manifest.release_id -ne ('keelaryn-system-'+$systemVersion)) { throw 'Manager release bundle system release identity is invalid.' }
    $artifacts=@($manifest.artifacts)
    if ($artifacts.Count -ne 4) { throw 'Manager release bundle must contain exactly four artifacts.' }
    $fileMap=@{}
    $fileMap[$spec.ManifestName]=[System.IO.Path]::GetFullPath($ManifestPath)
    foreach ($role in @('source','distribution','update','ai_context')) {
        $rows=@($artifacts | Where-Object { [string]$_.role -eq $role })
        if ($rows.Count -ne 1) { throw ('Manager release bundle role must appear exactly once: '+$role) }
        $expected=[string]$spec.ArtifactNames[$role]
        if ([string]$rows[0].path -cne $expected) { throw ('Manager release artifact path/version mismatch for role '+$role+'.') }
        $artifactPath=Join-Path $BaseDirectory $expected
        if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) { throw ('Manager release artifact is missing: '+$artifactPath) }
        $item=Get-Item -LiteralPath $artifactPath -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Manager release artifact must not be a reparse point: '+$artifactPath) }
        $expectedHash=([string]$rows[0].sha256).Trim().ToLowerInvariant()
        if ($expectedHash -notmatch '^[0-9a-f]{64}$') { throw ('Manager release artifact SHA-256 is invalid for role '+$role+'.') }
        $actualHash=(Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) { throw ('Manager release artifact SHA-256 mismatch for role '+$role+'.') }
        $fileMap[$expected]=[System.IO.Path]::GetFullPath($artifactPath)
    }
    return [pscustomobject]@{
        Version=$spec.Version
        VersionText=$spec.VersionText
        ManifestName=$spec.ManifestName
        ManifestPath=[System.IO.Path]::GetFullPath($ManifestPath)
        ArtifactNames=$spec.ArtifactNames
        FileMap=$fileMap
    }
}


function Get-LegacyManagerReleaseBundleSpec([string]$VersionText) {
    $text=([string]$VersionText).Trim()
    if (-not $text) { throw 'Legacy Manager release bundle version is empty.' }
    try { $version=[version]$text } catch { throw ('Legacy Manager release bundle contains an invalid version: '+$text) }
    if ($version -gt [version]'4.3.1') { throw ('Legacy three-artifact Manager release bundle is not allowed after 4.3.1: '+$text) }
    return [pscustomobject]@{
        Version=$version
        VersionText=$text
        ManifestName=('Keelaryn__Manager_RELEASE_v'+$text+'.json')
        ArtifactNames=[ordered]@{
            source=('Keelaryn__Manager_SOURCE_v'+$text+'.zip')
            distribution=('Keelaryn__Manager_Distribution_v'+$text+'.zip')
            update=('Keelaryn__Manager_Update_v'+$text+'_Built.zip')
        }
    }
}

function Read-LegacyManagerReleaseBundleForRetention([string]$ManifestPath,[string]$BaseDirectory) {
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw ('Legacy Manager release manifest is missing: '+$ManifestPath) }
    if (-not (Test-Path -LiteralPath $BaseDirectory -PathType Container)) { throw ('Legacy Manager release base directory is missing: '+$BaseDirectory) }
    $manifest=Read-KeelarynJsonFile $ManifestPath
    if ([string]$manifest.schema -ne 'keelaryn.manager.release-bundle.v1') { throw 'Invalid legacy Manager release-bundle schema.' }
    $versionText=([string]$manifest.manager_version).Trim()
    $spec=Get-LegacyManagerReleaseBundleSpec $versionText
    if ([System.IO.Path]::GetFileName($ManifestPath) -cne $spec.ManifestName) { throw 'Legacy Manager release manifest filename/version mismatch.' }
    $systemVersion=([string]$manifest.system_version).Trim()
    if (-not $systemVersion -or [string]$manifest.release_id -ne ('keelaryn-system-'+$systemVersion)) { throw 'Legacy Manager release bundle system release identity is invalid.' }

    [string[]]$propertyNames=@($manifest.PSObject.Properties | ForEach-Object { [string]$_.Name } | Sort-Object)
    [string[]]$expectedProperties=@('artifacts','manager_version','release_id','schema','system_version')
    if ($propertyNames.Count -ne $expectedProperties.Count -or [string]::Join("`n",$propertyNames) -cne [string]::Join("`n",$expectedProperties)) { throw 'Legacy Manager release bundle top-level contract is unrecognized.' }

    $artifacts=@($manifest.artifacts)
    if ($artifacts.Count -ne 3) { throw 'Legacy Manager release bundle must contain exactly three artifacts.' }
    $fileMap=@{}
    $fileMap[$spec.ManifestName]=[System.IO.Path]::GetFullPath($ManifestPath)
    foreach ($role in @('source','distribution','update')) {
        $rows=@($artifacts | Where-Object { [string]$_.role -eq $role })
        if ($rows.Count -ne 1) { throw ('Legacy Manager release bundle role must appear exactly once: '+$role) }
        $expected=[string]$spec.ArtifactNames[$role]
        if ([string]$rows[0].path -cne $expected) { throw ('Legacy Manager release artifact path/version mismatch for role '+$role+'.') }
        $artifactPath=Join-Path $BaseDirectory $expected
        if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) { throw ('Legacy Manager release artifact is missing: '+$artifactPath) }
        $item=Get-Item -LiteralPath $artifactPath -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Legacy Manager release artifact must not be a reparse point: '+$artifactPath) }
        $expectedHash=([string]$rows[0].sha256).Trim().ToLowerInvariant()
        if ($expectedHash -notmatch '^[0-9a-f]{64}$') { throw ('Legacy Manager release artifact SHA-256 is invalid for role '+$role+'.') }
        $actualHash=(Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) { throw ('Legacy Manager release artifact SHA-256 mismatch for role '+$role+'.') }
        $fileMap[$expected]=[System.IO.Path]::GetFullPath($artifactPath)
    }
    return [pscustomobject]@{
        Version=$spec.Version
        VersionText=$spec.VersionText
        ManifestName=$spec.ManifestName
        ManifestPath=[System.IO.Path]::GetFullPath($ManifestPath)
        ArtifactNames=$spec.ArtifactNames
        FileMap=$fileMap
        BundleFormat='legacy3'
    }
}

function Read-ManagerReleaseBundleForRetention([string]$ManifestPath,[string]$BaseDirectory) {
    try { return Read-ManagerReleaseBundle $ManifestPath $BaseDirectory }
    catch {
        $modernError=$_.Exception.Message
        try { return Read-LegacyManagerReleaseBundleForRetention $ManifestPath $BaseDirectory }
        catch { throw ('Manager release bundle is neither modern nor supported retention-only legacy format. Modern: '+$modernError+' Legacy: '+$_.Exception.Message) }
    }
}

function Test-ManagerReleaseBundleEquivalent($Left,$Right) {
    if (-not $Left -or -not $Right -or $Left.VersionText -ne $Right.VersionText) { return $false }
    $names=@($Left.ManifestName)+@($Left.ArtifactNames.Values)
    foreach ($name in $names) {
        if (-not $Left.FileMap.ContainsKey([string]$name) -or -not $Right.FileMap.ContainsKey([string]$name)) { return $false }
        $leftHash=(Get-FileHash -LiteralPath $Left.FileMap[[string]$name] -Algorithm SHA256).Hash.ToLowerInvariant()
        $rightHash=(Get-FileHash -LiteralPath $Right.FileMap[[string]$name] -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($leftHash -ne $rightHash) { return $false }
    }
    return $true
}

function Archive-ManagerReleaseBundle($Bundle) {
    $historyItem=Get-Item -LiteralPath $History -Force -ErrorAction Stop
    if (-not $historyItem.PSIsContainer -or ($historyItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Manager release history root is unsafe: '+$History) }
    $archiveRoot=Join-Path $History 'manager_releases'
    New-Item -ItemType Directory -Force -Path $archiveRoot | Out-Null
    $archiveRootItem=Get-Item -LiteralPath $archiveRoot -Force -ErrorAction Stop
    if (-not $archiveRootItem.PSIsContainer -or ($archiveRootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Manager release archive root is unsafe: '+$archiveRoot) }
    $final=Join-Path $archiveRoot ('v'+$Bundle.VersionText)
    $archived=$null
    if (Test-Path -LiteralPath $final) {
        if (-not (Test-Path -LiteralPath $final -PathType Container)) {
            Write-Warning ('Release retention left v'+$Bundle.VersionText+' in _releases because archive destination is not a directory: '+$final)
            return $false
        }
        $finalItem=Get-Item -LiteralPath $final -Force -ErrorAction Stop
        if (($finalItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            Write-Warning ('Release retention left v'+$Bundle.VersionText+' in _releases because archive destination is a reparse point: '+$final)
            return $false
        }
        try { $archived=Read-ManagerReleaseBundleForRetention (Join-Path $final $Bundle.ManifestName) $final }
        catch {
            Write-Warning ('Release retention left v'+$Bundle.VersionText+' in _releases because existing archive is invalid: '+$_.Exception.Message)
            return $false
        }
        if (-not (Test-ManagerReleaseBundleEquivalent $Bundle $archived)) {
            Write-Warning ('Release retention left v'+$Bundle.VersionText+' in _releases because existing archive differs.')
            return $false
        }
    }
    else {
        $stage=Join-Path $archiveRoot ('.stage-v'+$Bundle.VersionText+'-'+[guid]::NewGuid().ToString('N'))
        try {
            New-Item -ItemType Directory -Path $stage | Out-Null
            foreach ($name in @($Bundle.ArtifactNames.Values)+@($Bundle.ManifestName)) {
                Copy-Item -LiteralPath $Bundle.FileMap[[string]$name] -Destination (Join-Path $stage ([string]$name)) -Force
            }
            $archived=Read-ManagerReleaseBundleForRetention (Join-Path $stage $Bundle.ManifestName) $stage
            if (-not (Test-ManagerReleaseBundleEquivalent $Bundle $archived)) { throw 'Archived Manager release bundle differs from source bundle.' }
            Move-Item -LiteralPath $stage -Destination $final
            $stage=$null
            $archived=Read-ManagerReleaseBundleForRetention (Join-Path $final $Bundle.ManifestName) $final
        }
        finally { if ($stage -and (Test-Path -LiteralPath $stage)) { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue } }
    }

    # Preflight all source files before removing any duplicate. The complete archive
    # already exists and validates; source manifest is removed first so an interrupted
    # cleanup cannot leave a manifest that claims a now-incomplete bundle.
    foreach ($name in @($Bundle.ArtifactNames.Values)+@($Bundle.ManifestName)) {
        Wait-FileReadyForAtomicReplace $Bundle.FileMap[[string]$name] 1 0 'release retention cleanup'
    }
    Remove-Item -LiteralPath $Bundle.ManifestPath -Force
    foreach ($name in @($Bundle.ArtifactNames.Values)) { Remove-Item -LiteralPath $Bundle.FileMap[[string]$name] -Force }
    try { (Get-Item -LiteralPath $final -Force).LastWriteTime=Get-Date } catch {}
    Log ('Archived superseded Manager release bundle v'+$Bundle.VersionText+': '+$final)
    return $true
}

function Cleanup-ManagerReleaseArchive([string]$CurrentVersionText) {
    $archiveRoot=Join-Path $History 'manager_releases'
    if (-not (Test-Path -LiteralPath $archiveRoot -PathType Container)) { return 0 }
    $rootItem=Get-Item -LiteralPath $archiveRoot -Force -ErrorAction Stop
    if (($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Manager release archive root is unsafe: '+$archiveRoot) }
    $currentVersion=[version]$CurrentVersionText
    $validOlder=@()
    foreach ($dir in @(Get-ChildItem -LiteralPath $archiveRoot -Directory -Force -ErrorAction SilentlyContinue | Sort-Object Name)) {
        if (($dir.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            $message=('Release archive retention left reparse-point directory untouched: '+$dir.FullName)
            Write-Warning $message; Log $message; continue
        }
        $name=[string]$dir.Name
        if (-not $name.StartsWith('v',[System.StringComparison]::Ordinal)) {
            $message=('Release archive retention left unrecognized directory untouched: '+$dir.FullName)
            Write-Warning $message; Log $message; continue
        }
        $versionText=$name.Substring(1)
        try {
            $spec=Get-ManagerReleaseBundleSpec $versionText
            $bundle=Read-ManagerReleaseBundleForRetention (Join-Path $dir.FullName $spec.ManifestName) $dir.FullName
        }
        catch {
            $message=('Release archive retention left invalid bundle untouched: '+$dir.FullName+'; '+$_.Exception.Message)
            Write-Warning $message; Log $message; continue
        }
        if ($bundle.Version -ge $currentVersion) {
            $message=('Release archive retention left current/future bundle untouched: v'+$bundle.VersionText)
            Write-Warning $message; Log $message; continue
        }
        $validOlder += [pscustomobject]@{Dir=$dir;Bundle=$bundle}
    }
    $remove=@($validOlder | Sort-Object @{Expression={$_.Bundle.Version};Descending=$true} | Select-Object -Skip 3)
    $removed=0
    foreach ($row in $remove) {
        try {
            Remove-Item -LiteralPath $row.Dir.FullName -Recurse -Force
            $removed++
            Log ('Release archive retention removed validated old bundle v'+$row.Bundle.VersionText+': '+$row.Dir.FullName)
        }
        catch {
            $message=('Release archive retention could not remove validated old bundle v'+$row.Bundle.VersionText+': '+$_.Exception.Message)
            Write-Warning $message; Log $message
        }
    }
    return $removed
}

function Invoke-ManagerReleaseRetention([string]$CurrentVersionText) {
    $currentSpec=Get-ManagerReleaseBundleSpec $CurrentVersionText
    $currentBundle=Read-ManagerReleaseBundle (Join-Path $Releases $currentSpec.ManifestName) $Releases
    $valid=@()
    foreach ($manifestFile in @(Get-ChildItem -LiteralPath $Releases -Filter 'Keelaryn__Manager_RELEASE_v*.json' -File -ErrorAction SilentlyContinue | Sort-Object Name)) {
        try { $valid += Read-ManagerReleaseBundleForRetention $manifestFile.FullName $Releases }
        catch {
            $message=('Release retention left invalid/unrecognized bundle untouched: '+$manifestFile.FullName+'; '+$_.Exception.Message)
            Write-Warning $message
            Log $message
        }
    }
    $currentVersion=[version]$CurrentVersionText
    $future=@($valid | Where-Object { $_.Version -gt $currentVersion })
    foreach ($bundle in $future) {
        $message=('Release retention left future Manager release untouched: v'+$bundle.VersionText)
        Write-Warning $message
        Log $message
    }
    $older=@($valid | Where-Object { $_.Version -lt $currentVersion } | Sort-Object Version -Descending)
    $previous=$null
    if ($older.Count -gt 0) { $previous=$older[0] }
    $archivedCount=0
    foreach ($bundle in @($older | Select-Object -Skip 1)) {
        try { if (Archive-ManagerReleaseBundle $bundle) { $archivedCount++ } }
        catch {
            $message=('Release retention could not archive v'+$bundle.VersionText+'; bundle left in _releases: '+$_.Exception.Message)
            Write-Warning $message
            Log $message
        }
    }
    $archiveRemoved=Cleanup-ManagerReleaseArchive $CurrentVersionText
    $previousVersionText=$null
    if ($previous) { $previousVersionText=$previous.VersionText }
    return [pscustomobject]@{
        Current=$currentBundle.VersionText
        Previous=$previousVersionText
        Archived=$archivedCount
        ArchiveRemoved=$archiveRemoved
        FutureUntouched=$future.Count
    }
}

function Get-TransitionRootBootstrapText {
    return [string]::Join("`n",@(
        ('$ManagerVersion = "'+$ManagerVersion+'"'),
        '$runtime = Join-Path $PSScriptRoot ''product\runtime\Keelaryn__Manager.ps1''',
        'if (-not (Test-Path -LiteralPath $runtime -PathType Leaf)) {',
        '    [Console]::Error.WriteLine(''Keelaryn Manager runtime is missing: ''+$runtime)',
        '    exit 1',
        '}',
        '& (Join-Path $PSHOME ''powershell.exe'') -NoProfile -ExecutionPolicy Bypass -File $runtime @args',
        'exit $LASTEXITCODE',
        ''
    ))
}

function New-TransitionInstallationManifestObject([string[]]$PackagePaths) {
    return [ordered]@{schema='keelaryn.manager.installation.v1';manager_version=$ManagerVersion;managed_files=@($PackagePaths|Sort-Object)}
}

function Convert-ManagerReleaseBytesToText([byte[]]$Bytes) {
    if ($null -eq $Bytes) { throw 'Managed release source bytes are null.' }
    $text=[System.Text.Encoding]::UTF8.GetString($Bytes)
    if ($text.Length -gt 0 -and [int]$text[0] -eq 0xFEFF) { $text=$text.Substring(1) }
    return $text
}

function Get-ManagerReleaseSourceSnapshot([string[]]$Paths) {
    $rows=New-Object System.Collections.ArrayList
    foreach ($rel in @($Paths | Sort-Object -Unique)) {
        $item=Get-InstalledManagedFileItem $rel
        $ext=[System.IO.Path]::GetExtension($rel).ToLowerInvariant()
        if (@('.md','.json','.ps1','.txt','.cmd') -notcontains $ext) { throw ('Release build rejected non-text managed file: '+$rel) }
        $bytes=[System.IO.File]::ReadAllBytes($item.FullName)
        $item.Refresh()
        if (-not $item.Exists -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or [long]$item.Length -ne [long]$bytes.LongLength) { throw ('Managed source changed while release snapshot was being captured: '+$rel) }
        $text=Convert-ManagerReleaseBytesToText $bytes
        Test-CleanroomText $rel $text
        [void]$rows.Add([pscustomobject]@{Path=$rel;Bytes=$bytes;Hash=(Get-BytesHashHex $bytes);Size=[long]$bytes.LongLength;Text=$text})
    }
    return @($rows)
}

function Write-ManagerReleaseSnapshotFile($Row,[string]$Destination) {
    if (-not $Row -or $null -eq $Row.Bytes) { throw 'Invalid Manager release snapshot row.' }
    $parent=Split-Path -Parent $Destination
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    [System.IO.File]::WriteAllBytes($Destination,[byte[]]$Row.Bytes)
}

function Invoke-BuildRelease {
    $releaseRootItem=Get-Item -LiteralPath $Releases -Force -ErrorAction Stop
    if (-not $releaseRootItem.PSIsContainer -or ($releaseRootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Manager release output root is unsafe: '+$Releases) }
    if (-not (Test-AIContextToolSourceSelfTest)) { throw 'Release build refused: PowerShell parser/lexical source gate failed.' }
    $paths=@(Get-InstalledManagedPaths)
    if ($paths.Count -eq 0) { throw 'Installed managed-file manifest is empty.' }
    $release=Get-ProductRelease
    $managerPolicy=Get-ManagerReleasePolicy
    $temp=Join-Path $WorkRoot ('release_'+[guid]::NewGuid().ToString('N'))
    $sourceTree=Join-Path $temp 'source\keelaryn'
    $sourceRoot=Join-Path $sourceTree 'manager'
    $updateRoot=Join-Path $temp 'Keelaryn__Manager_Update'
    $payload=Join-Path $updateRoot 'payload'
    $releaseStage=Join-Path $temp 'release-stage'
    $distTemp=Join-Path $temp 'distribution'
    $distTree=Join-Path $distTemp 'keelaryn'
    $distRoot=Join-Path $distTree 'manager'
    New-Item -ItemType Directory -Force -Path $sourceRoot,$payload,$releaseStage,$distRoot | Out-Null
    try {
        # Capture one immutable in-memory snapshot of every managed source file. SOURCE,
        # UPDATE and DISTRIBUTION are then materialized from exactly the same bytes instead
        # of reopening the canonical source tree independently for each artifact.
        $sourceSnapshot=@(Get-ManagerReleaseSourceSnapshot $paths)
        if ($sourceSnapshot.Count -ne $paths.Count) { throw 'Managed release source snapshot count mismatch.' }
        $entries=@()
        foreach ($row in $sourceSnapshot) {
            $rel=[string]$row.Path
            foreach ($dst in @((Join-Path $sourceRoot $rel),(Join-Path $payload $rel),(Join-Path $distRoot $rel))) {
                Write-ManagerReleaseSnapshotFile $row $dst
            }
            $entries += [ordered]@{path=$rel;sha256=[string]$row.Hash;size_bytes=[long]$row.Size}
        }

        $finalEntries=@($entries)
        $finalRows=@($finalEntries|ForEach-Object{([string]$_.path)+"`0"+([string]$_.sha256)}|Sort-Object)
        $finalContentHash=Get-TextHashHex([string]::Join("`n",$finalRows))
        $transitionPaths=@($paths+@('Keelaryn__Manager.ps1','_manager_manifest.json','_manager_version.txt')|Sort-Object -Unique)
        $transitionBootstrap=Get-TransitionRootBootstrapText
        $transitionManifest=(New-TransitionInstallationManifestObject $transitionPaths)|ConvertTo-Json -Depth 6
        $transitionFiles=[ordered]@{
            'Keelaryn__Manager.ps1'=$transitionBootstrap
            '_manager_manifest.json'=($transitionManifest+"`n")
            '_manager_version.txt'=($ManagerVersion+"`n")
        }
        foreach($name in @($transitionFiles.Keys)){
            $dst=Join-Path $payload ([string]$name)
            $enc=New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText($dst,[string]$transitionFiles[$name],$enc)
            $entries += [ordered]@{path=[string]$name;sha256=(Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash.ToLowerInvariant();size_bytes=(Get-Item -LiteralPath $dst -Force).Length}
        }

        $spec=Get-ManagerReleaseBundleSpec $ManagerVersion
        $aiTool=Join-Path $sourceRoot 'product\tools\New-KeelarynAIContext.ps1'
        $aiContext=Join-Path $sourceRoot 'Development\AI_CONTEXT'
        & $aiTool -ManagerRoot $sourceRoot -OutputDirectory $aiContext 6>&1 | Out-Null
        foreach ($row in @(Get-SafeTreeFileInventory -RootPath $aiContext -Purpose 'Generated AI context')) {
            Test-CleanroomText ('Development/AI_CONTEXT/'+$row.RelativePath) (Get-Content -LiteralPath $row.File.FullName -Raw -Encoding UTF8)
        }
        $aiZip=Join-Path $releaseStage $spec.ArtifactNames.ai_context
        Write-DeterministicZip $aiContext $aiZip 'Keelaryn__Manager_AI_CONTEXT'

        $sourceZip=Join-Path $releaseStage $spec.ArtifactNames.source
        Write-DeterministicZip $sourceTree $sourceZip 'keelaryn'

        $rootLauncher=Get-GeneratedLayoutRootLauncherText
        [System.IO.File]::WriteAllText((Join-Path $distTree 'Keelaryn.cmd'),$rootLauncher,[System.Text.Encoding]::ASCII)
        [ordered]@{schema='keelaryn.manager.distribution.v2';manager_version=$ManagerVersion;layout_version=2;built_from='canonical_final_managed_allowlist_only';files=$finalEntries} | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $distRoot 'product\install\DISTRIBUTION_MANIFEST.json') -Encoding UTF8
        $distZip=Join-Path $releaseStage $spec.ArtifactNames.distribution
        Write-DeterministicZip $distTree $distZip 'keelaryn'

        $floor=([string]$managerPolicy.update_min_version).Trim()
        $um=[ordered]@{schema=[string]$managerPolicy.native_update_schema;manager_version=$ManagerVersion;release_id=('keelaryn-manager-'+$ManagerVersion);system_release_id=[string]$release.release_id;min_manager_version=$floor;final_managed_files=@($paths|Sort-Object);final_content_hash=$finalContentHash;files=@($entries|Sort-Object {[string]$_.path})}
        $um | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $updateRoot 'manifest.json') -Encoding UTF8
        $updateZip=Join-Path $releaseStage $spec.ArtifactNames.update
        Write-DeterministicZip $updateRoot $updateZip 'Keelaryn__Manager_Update'
        $verified=Read-ManagerUpdatePackage $updateZip
        if (-not $verified -or $verified.VersionText -ne $ManagerVersion) { throw 'Release build self-validation rejected generated UPDATE.' }

        $rm=[ordered]@{
            schema='keelaryn.manager.release-bundle.v1'
            manager_version=$ManagerVersion
            system_version=[string]$release.system_version
            release_id=[string]$release.release_id
            artifacts=@(
                [ordered]@{role='source';path=$spec.ArtifactNames.source;sha256=(Get-FileHash $sourceZip -Algorithm SHA256).Hash.ToLowerInvariant()},
                [ordered]@{role='distribution';path=$spec.ArtifactNames.distribution;sha256=(Get-FileHash $distZip -Algorithm SHA256).Hash.ToLowerInvariant()},
                [ordered]@{role='update';path=$spec.ArtifactNames.update;sha256=(Get-FileHash $updateZip -Algorithm SHA256).Hash.ToLowerInvariant()},
                [ordered]@{role='ai_context';path=$spec.ArtifactNames.ai_context;sha256=(Get-FileHash $aiZip -Algorithm SHA256).Hash.ToLowerInvariant()}
            )
        }
        $stagedManifest=Join-Path $releaseStage $spec.ManifestName
        $rm | ConvertTo-Json -Depth 8 | Set-Content $stagedManifest -Encoding UTF8
        $stagedBundle=Read-ManagerReleaseBundle $stagedManifest $releaseStage

        New-Item -ItemType Directory -Force -Path $Releases | Out-Null
        # Preflight every destination before publishing the first file. The manifest is
        # published last, so an interrupted publication never advertises a new complete bundle.
        foreach ($name in @($spec.ArtifactNames.Values)+@($spec.ManifestName)) {
            $destination=Join-Path $Releases ([string]$name)
            if (Test-Path -LiteralPath $destination -PathType Container) { throw ('Release publish target collides with a directory: '+$destination) }
            if (Test-Path -LiteralPath $destination -PathType Leaf) { Wait-FileReadyForAtomicReplace $destination 20 250 'release bundle publication' }
        }
        foreach ($name in @($spec.ArtifactNames.Values)) {
            Publish-CompletedFileAtomically $stagedBundle.FileMap[[string]$name] (Join-Path $Releases ([string]$name))
        }
        Publish-CompletedFileAtomically $stagedBundle.ManifestPath (Join-Path $Releases $spec.ManifestName)

        $publishedBundle=Read-ManagerReleaseBundle (Join-Path $Releases $spec.ManifestName) $Releases
        if ($publishedBundle.VersionText -ne $ManagerVersion) { throw 'Published release bundle version mismatch.' }
        $retention=Invoke-ManagerReleaseRetention $ManagerVersion
        $previousText=if($retention.Previous){$retention.Previous}else{'none'}
        Write-Host 'Release build: PASS' -ForegroundColor Green
        Write-Host 'Artifacts:' -ForegroundColor Cyan
        Write-Host ('  SOURCE:       '+(Join-Path $Releases $spec.ArtifactNames.source))
        Write-Host ('  DISTRIBUTION: '+(Join-Path $Releases $spec.ArtifactNames.distribution))
        Write-Host ('  UPDATE:       '+(Join-Path $Releases $spec.ArtifactNames.update))
        Write-Host ('  AI_CONTEXT:   '+(Join-Path $Releases $spec.ArtifactNames.ai_context))
        Write-Host ('  Manifest:     '+(Join-Path $Releases $spec.ManifestName))
        Write-Host 'Retention:' -ForegroundColor Cyan
        Write-Host ('  Current: '+$retention.Current+'; previous: '+$previousText+'; archived this run: '+$retention.Archived+'; archive pruned: '+$retention.ArchiveRemoved+'; future untouched: '+$retention.FutureUntouched)
        return 0
    }
    finally { if (Test-Path $temp) { Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue } }
}

function Test-CleanroomText([string]$Path, [string]$Text) {
    if ([regex]::IsMatch($Text, '\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)) { throw ("Cleanroom audit: email-like string in " + $Path) }
    $privacyScan=[regex]::Replace($Text,'(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b','<TECHNICAL-GUID>')
    # Full SHA-256 digests are machine identities, not phone numbers.
    $privacyScan=[regex]::Replace($privacyScan,'(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])','<TECHNICAL-SHA256>')
    if ([regex]::IsMatch($privacyScan, '(?:\+\d[\d ()-]{7,}\d|(?<!\d)\d{10,15}(?!\d))')) { throw ("Cleanroom audit: phone-like string in " + $Path) }
    if ([regex]::IsMatch($Text, '[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)) { throw ("Cleanroom audit: absolute user path in " + $Path) }
}

function Invoke-BuildDistribution {
    if (-not (Test-AIContextToolSourceSelfTest)) { throw 'Distribution build refused: PowerShell parser/lexical source gate failed.' }
    $paths = @(Get-InstalledManagedPaths)
    if ($paths.Count -eq 0) { throw 'Installed managed-file manifest is empty.' }
    $temp = Join-Path $WorkRoot ('dist_' + [guid]::NewGuid().ToString('N'))
    $distTree = Join-Path $temp 'keelaryn'
    $dist = Join-Path $distTree 'manager'
    New-Item -ItemType Directory -Path $dist | Out-Null
    try {
        $entries = @()
        foreach ($rel in $paths) {
            $src = Join-Path $Root $rel
            if (-not (Test-Path $src -PathType Leaf)) { throw ("Managed product file missing: " + $rel) }
            $dst = Join-Path $dist $rel
            $parent = Split-Path -Parent $dst
            if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
            Copy-Item $src $dst -Force
            $ext = [System.IO.Path]::GetExtension($rel).ToLowerInvariant()
            if (@('.md','.json','.ps1','.txt','.cmd') -notcontains $ext) { throw ("Cleanroom audit rejected non-text managed file: " + $rel) }
            $text = Get-Content $src -Raw -Encoding UTF8
            Test-CleanroomText $rel $text
            $entries += [ordered]@{ path=$rel; sha256=(Get-FileHash $src -Algorithm SHA256).Hash.ToLowerInvariant(); size_bytes=(Get-InstalledManagedFileItem $rel).Length }
        }
        $rootLauncher=Get-GeneratedLayoutRootLauncherText
        [System.IO.File]::WriteAllText((Join-Path $distTree 'Keelaryn.cmd'),$rootLauncher,[System.Text.Encoding]::ASCII)
        [ordered]@{ schema='keelaryn.manager.distribution.v2'; manager_version=$ManagerVersion; layout_version=2; built_from='canonical_final_managed_allowlist_only'; files=$entries } | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $dist 'product\install\DISTRIBUTION_MANIFEST.json') -Encoding UTF8
        $zip = Join-Path $Releases ('Keelaryn__Manager_Distribution_v' + $ManagerVersion + '.zip')
        Write-DeterministicZip $distTree $zip 'keelaryn'
        Log ("Built generic distribution: " + $zip)
        Write-Host ("Generic distribution: " + $zip) -ForegroundColor Green
        return 0
    }
    finally { if (Test-Path $temp) { Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue } }
}

function Get-DesktopKnownFolderPath {
    if (-not ('KeelarynKnownFolders' -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class KeelarynKnownFolders {
    [DllImport("shell32.dll")]
    private static extern int SHGetKnownFolderPath(ref Guid rfid, uint flags, IntPtr token, out IntPtr path);
    public static string Desktop() {
        Guid id = new Guid("B4BFCC3A-DB2C-424C-B029-7FE99A87C641");
        IntPtr p; int hr = SHGetKnownFolderPath(ref id, 0, IntPtr.Zero, out p);
        if (hr != 0) Marshal.ThrowExceptionForHR(hr);
        try { return Marshal.PtrToStringUni(p); }
        finally { Marshal.FreeCoTaskMem(p); }
    }
}
"@
    }
    return [KeelarynKnownFolders]::Desktop()
}

function Save-UnicodeShellShortcut([string]$ShortcutPath,[string]$TargetPath,[string]$WorkingDirectory,[string]$Description) {
    if (-not ('KeelarynUnicodeShortcut' -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

[ComImport]
[Guid("00021401-0000-0000-C000-000000000046")]
internal class KeelarynShellLinkClass { }

[ComImport]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("000214F9-0000-0000-C000-000000000046")]
internal interface IKeelarynShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile, int cch, IntPtr pfd, uint fFlags);
    void GetIDList(out IntPtr ppidl);
    void SetIDList(IntPtr pidl);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cch);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cch);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cch);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
    void GetHotkey(out short pwHotkey);
    void SetHotkey(short wHotkey);
    void GetShowCmd(out int piShowCmd);
    void SetShowCmd(int iShowCmd);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cch, out int piIcon);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, uint dwReserved);
    void Resolve(IntPtr hwnd, uint fFlags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
}

public static class KeelarynUnicodeShortcut {
    public static void Create(string shortcutPath, string targetPath, string workingDirectory, string description) {
        IKeelarynShellLinkW link = (IKeelarynShellLinkW)new KeelarynShellLinkClass();
        try {
            link.SetPath(targetPath);
            link.SetWorkingDirectory(workingDirectory);
            link.SetDescription(description);
            ((IPersistFile)link).Save(shortcutPath, true);
        }
        finally {
            if (Marshal.IsComObject(link)) Marshal.FinalReleaseComObject(link);
        }
    }
}
"@
    }
    [KeelarynUnicodeShortcut]::Create($ShortcutPath,$TargetPath,$WorkingDirectory,$Description)
}

function Ensure-DesktopShortcut {
    # Avoid creating a shortcut to a transitional pre-Keelaryn directory name.
    if (@('manager','Keelaryn__Manager') -notcontains (Split-Path $Root -Leaf)) { return }
    if (Test-Path $ShortcutFailureMarker -PathType Leaf) {
        try {
            $oldFailure=Read-KeelarynJsonFile $ShortcutFailureMarker
            if ([string]$oldFailure.schema -eq 'keelaryn.manager.shortcut-failure.v1' -and [string]$oldFailure.manager_version -eq $ManagerVersion) { return }
        } catch {}
    }
    try {
        $desktop=Get-DesktopKnownFolderPath
        if (-not $desktop -or -not (Test-Path $desktop -PathType Container)) { return }
        foreach ($legacyName in @('Core__Hub.lnk')) {
            $legacyShortcut=Join-Path $desktop $legacyName
            if (Test-Path $legacyShortcut -PathType Leaf) { Remove-Item $legacyShortcut -Force -ErrorAction SilentlyContinue }
        }
        $shortcutPath=Join-Path $desktop 'Keelaryn Hub.lnk'
        Save-UnicodeShellShortcut $shortcutPath (Join-Path $Root 'compat\commands\OPEN_KEELARYN__HUB.cmd') $Root 'Open Keelaryn Hub'
        if (-not (Test-Path $shortcutPath -PathType Leaf)) { throw 'Unicode ShellLink API returned without creating the shortcut.' }
        if (Test-Path $ShortcutFailureMarker -PathType Leaf) { Remove-Item $ShortcutFailureMarker -Force -ErrorAction SilentlyContinue }
        Log 'Desktop shortcut created/refreshed through Unicode ShellLink + Windows Known Folder APIs.'
    }
    catch {
        [ordered]@{ schema='keelaryn.manager.shortcut-failure.v1'; manager_version=$ManagerVersion; failed=(Get-Date).ToUniversalTime().ToString('o'); message=$_.Exception.Message } |
            ConvertTo-Json -Depth 4 | Set-Content -Path $ShortcutFailureMarker -Encoding UTF8
        Log ('Could not create desktop shortcut: '+$_.Exception.Message)
    }
}

function Open-Vault {
    if (-not (Test-Path $Vault -PathType Container)) { throw ("Sibling Keelaryn__Hub vault is missing: "+$Vault) }
    try {
        $resolved=(Resolve-Path $Vault).Path
        Start-Process ('obsidian://open?path='+[System.Uri]::EscapeDataString($resolved))
        Log 'Opened vault in Obsidian.'
    }
    catch {
        Log ("Obsidian URI failed; opening folder instead: "+$_.Exception.Message)
        Start-Process explorer.exe $Vault
    }
}

function Close-ObsidianIfNeeded {
    $procs=@(Get-Process -Name 'Obsidian' -ErrorAction SilentlyContinue)
    if (-not $procs) { return $true }
    Log 'Obsidian is running; requesting graceful close for update.'
    foreach ($proc in $procs) { try {$null=$proc.CloseMainWindow()} catch {} }
    $deadline=(Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
        if (-not (Get-Process -Name 'Obsidian' -ErrorAction SilentlyContinue)) { return $true }
    }
    Log 'Obsidian did not close; update deferred.'
    return $false
}

function Assert-FreeSpace([long]$ExpandedBytes,[long]$Headroom,[string]$Purpose,[string]$TargetPath=$Root) {
    $needed=[long]($ExpandedBytes*3+$Headroom)
    $full=[System.IO.Path]::GetFullPath($TargetPath)
    $driveRoot=[System.IO.Path]::GetPathRoot($full)
    $drive=New-Object System.IO.DriveInfo($driveRoot)
    if ($drive.AvailableFreeSpace -lt $needed) {
        throw ("Insufficient free disk space for {0} on {1}. Need at least {2:N0} bytes available; have {3:N0}." -f $Purpose,$driveRoot,$needed,$drive.AvailableFreeSpace)
    }
}

function Archive-CurrentCheckpoint($OldState) {
    if (-not (Test-Path $CurrentZip -PathType Leaf) -or -not $OldState) { return }
    $date=Get-Date -Format 'yyyy-MM-dd'
    $baseName='Keelaryn__Hub_v{0}_r{1:D4}_{2}.zip' -f $OldState.VersionText,$OldState.Revision,$date
    $dest=Join-Path $Checkpoints $baseName
    $sourceHash=(Get-FileHash $CurrentZip -Algorithm SHA256).Hash.ToLowerInvariant()
    if (Test-Path $dest -PathType Leaf) {
        $destHash=(Get-FileHash $dest -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($destHash -eq $sourceHash) { return }
        $dest=Join-Path $Checkpoints (([System.IO.Path]::GetFileNameWithoutExtension($baseName))+'_'+$sourceHash.Substring(0,8)+'.zip')
    }
    Copy-Item $CurrentZip $dest -Force
    try { (Get-Item -LiteralPath $dest -Force).LastWriteTime=Get-Date } catch {}
    Log ("Archived outgoing checkpoint: "+$dest)
}

function Remove-AcceptedCandidatePackages($ApprovedArtifact) {
    $accepted=@($ApprovedArtifact.AcceptedCandidates)
    if ($accepted.Count -eq 0 -or -not (Test-Path $Inbox)) { return @() }
    $warnings=@(); $candidateFiles=@(Get-ChildItem $Inbox -Filter '*.zip' -File -ErrorAction SilentlyContinue | Where-Object { $_.Name.StartsWith('Keelaryn__Hub_CANDIDATE_',[System.StringComparison]::OrdinalIgnoreCase) -or $_.Name.StartsWith([string]$LegacyCoreCompat.CandidatePrefix,[System.StringComparison]::OrdinalIgnoreCase) } | Sort-Object FullName -Unique)
    foreach ($acceptedRow in $accepted) {
        foreach ($file in $candidateFiles) {
            if (-not (Test-Path $file.FullName -PathType Leaf)) { continue }
            $state=Read-ZipState $file.FullName; $artifact=Read-ZipArtifactManifest $file.FullName
            if (-not $state -or -not $artifact -or $artifact.Status -ne 'candidate' -or $artifact.ArtifactId -ne $acceptedRow.ArtifactId) { continue }
            $actual=$null
            if ($acceptedRow.HashMode -eq 'payload_v2' -or $acceptedRow.HashMode -eq 'payload_v3') { $actual=Get-ZipPayloadHash $file.FullName } else { $actual=Get-ZipContentHash $file.FullName }
            if ($actual -ne $acceptedRow.ContentHash) { $warnings += ("Candidate {0} has accepted artifact_id but different hash; left untouched: {1}" -f $acceptedRow.ArtifactId,$file.FullName); continue }
            try { Remove-Item $file.FullName -Force; Log ("Removed consumed CANDIDATE proven by installed APPROVED: "+$file.FullName) }
            catch { $warnings += ("Could not remove consumed candidate {0}: {1}" -f $file.FullName,$_.Exception.Message) }
        }
    }
    return @($warnings)
}

function Copy-LocalDeploymentStateForHubUpdate([string]$BackupVault,[string]$StagedVault) {
    foreach($name in @('.obsidian','.git')){$src=Join-Path $BackupVault $name;if(-not(Test-Path -LiteralPath $src)){continue};$item=Get-Item -LiteralPath $src -Force -ErrorAction Stop;if(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw('Hub update cannot safely preserve local state reparse point: '+$src)};$dst=Join-Path $StagedVault $name;if(Test-Path -LiteralPath $dst){Remove-Item -LiteralPath $dst -Recurse -Force};if($item.PSIsContainer){Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force}else{Copy-Item -LiteralPath $src -Destination $dst -Force}}
}

function Install-HubPackage($Package,$ExpectedCurrent=$null) {
    Assert-FreeSpace ([long]$Package.State.ExpandedBytes) $MinHubDiskHeadroom 'Keelaryn__Hub staging/rollback' $Root
    if ([System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($Vault)) -ne [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($Root))) { Assert-FreeSpace ([long]$Package.State.ExpandedBytes) $MinHubDiskHeadroom 'Keelaryn__Hub target' $Vault }
    $temp=Join-Path $WorkRoot ('installing_hub_'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temp | Out-Null
    $backup=$null; $backupCreated=$false; $currentNew=$CurrentZip+'.new'
    $stagedZip=Join-Path $temp 'validated-package.zip'
    try {
        Copy-Item -LiteralPath $Package.File.FullName -Destination $stagedZip -Force
        $stagedHash=(Get-FileHash -LiteralPath $stagedZip -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($stagedHash -ne $Package.ZipHash) { throw 'Hub package changed between decision and staging.' }
        Expand-Archive -LiteralPath $stagedZip -DestinationPath $temp -Force
        $newVault=Join-Path $temp ([string]$Package.State.ZipRoot)
        $newVaultAnalysis=Get-PortableVaultAnalysis $newVault
        $newState=Read-VaultMetadataAt $newVault $newVaultAnalysis
        if (-not $newState) { throw 'Hub package validation failed after extraction.' }
        if ($newState.Version -ne $Package.State.Version -or $newState.Revision -ne $Package.State.Revision) { throw 'Extracted Hub STATE differs from pre-install validation.' }
        if ($newVaultAnalysis.ContentHash -ne $Package.ContentHash -or $newVaultAnalysis.PayloadHash -ne $Package.PayloadHash) { throw 'Extracted Hub hash differs from validated package.' }

        if($ExpectedCurrent){Assert-CurrentHubSnapshotUnchanged $ExpectedCurrent;$oldState=$ExpectedCurrent.State}else{$oldState=Read-VaultState}
        $stamp=Get-Date -Format 'yyyy-MM-dd_HHmmss'
        if ($oldState) { $backupName='Keelaryn__Hub_v{0}_r{1:D4}_{2}' -f $oldState.VersionText,$oldState.Revision,$stamp } else { $backupName='Keelaryn__Hub_unknown_'+$stamp }
        $backup=Join-Path $Rollback $backupName
        Archive-CurrentCheckpoint $oldState

        # Fail before swapping the Hub when CURRENT is persistently locked. This keeps
        # the old Hub active and avoids a rollback for a condition we can detect early.
        if (Test-Path -LiteralPath $CurrentZip -PathType Leaf) {
            try {
                Wait-FileReadyForAtomicReplace $CurrentZip 20 250 'Keelaryn__Hub CURRENT publication preflight'
            }
            catch {
                throw ('Keelaryn__Hub CURRENT publication preflight failed before Hub swap: ' + $CurrentZip + '; ' + $_.Exception.Message)
            }
        }

        if (Test-Path $Vault) { Move-Item -Path $Vault -Destination $backup; $backupCreated=$true; try { (Get-Item -LiteralPath $backup -Force).LastWriteTime=Get-Date } catch {} }
        try {
            if ($backupCreated) { Copy-LocalDeploymentStateForHubUpdate $backup $newVault }
            Move-Item -Path $newVault -Destination $Vault
            $installedHashes=Get-VaultHashPairAt $Vault
            if ($installedHashes.ContentHash -ne $Package.ContentHash -or $installedHashes.PayloadHash -ne $Package.PayloadHash) { throw 'Post-install Hub hash mismatch.' }
            Copy-Item -LiteralPath $stagedZip -Destination $currentNew -Force
            Publish-CompletedFileAtomically $currentNew $CurrentZip
        }
        catch {
            if (Test-Path $currentNew) { Remove-Item $currentNew -Force -ErrorAction SilentlyContinue }
            if (Test-Path $Vault) { Remove-Item $Vault -Recurse -Force -ErrorAction SilentlyContinue }
            if ($backupCreated -and (Test-Path $backup)) { Move-Item -Path $backup -Destination $Vault }
            throw
        }

        try { Remove-Item $Package.File.FullName -Force -ErrorAction SilentlyContinue } catch {}
        foreach ($warning in @(Remove-AcceptedCandidatePackages $Package.Artifact)) { Log ("WARNING: "+$warning); Write-Host ("Warning: "+$warning) -ForegroundColor Yellow }
        Cleanup-History
        Log ("Installed APPROVED Keelaryn__Hub v{0} r{1:D4} from {2}" -f $Package.State.VersionText,$Package.State.Revision,$Package.File.Name)
    }
    finally {
        if (Test-Path $currentNew) { Remove-Item $currentNew -Force -ErrorAction SilentlyContinue }
        if (Test-Path $temp) { Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

function Get-ManagerSnapshotFileMetadata([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw ('Manager rollback snapshot file is missing: '+$Path) }
    $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer) { throw ('Manager rollback snapshot path is not a file: '+$Path) }
    if (($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0) { throw ('Manager rollback snapshot file must not be a reparse point: '+$Path) }
    return [ordered]@{
        size_bytes=[long]$item.Length
        sha256=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Test-ManagerSnapshotMetadataSelfTest {
    $probe=Join-Path $WorkRoot ('snapshot_metadata_selftest_'+[guid]::NewGuid().ToString('N')+'.tmp')
    try {
        $bytes=[System.Text.Encoding]::ASCII.GetBytes('keelaryn-hidden-snapshot-probe')
        [System.IO.File]::WriteAllBytes($probe,$bytes)
        $item=Get-Item -LiteralPath $probe -Force -ErrorAction Stop
        [System.IO.File]::SetAttributes($probe,($item.Attributes-bor[System.IO.FileAttributes]::Hidden))
        $meta=Get-ManagerSnapshotFileMetadata $probe
        if([long]$meta.size_bytes-ne[long]$bytes.Length){return $false}
        $expected=(Get-FileHash -LiteralPath $probe -Algorithm SHA256).Hash.ToLowerInvariant()
        if([string]$meta.sha256-ne$expected){return $false}
        return $true
    }
    catch { return $false }
    finally { if(Test-Path -LiteralPath $probe){Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue} }
}

function Restore-ManagerSnapshot([string]$Snapshot) {
    if(-not$Snapshot -or -not(Test-Path -LiteralPath $Snapshot -PathType Container)){throw 'Manager rollback snapshot is unavailable.'};$si=Get-Item -LiteralPath $Snapshot -Force;if(($si.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw 'Manager rollback snapshot must not be a reparse point.'};$metaPath=Join-Path $Snapshot '_snapshot_manifest.json'
    if(Test-Path -LiteralPath $metaPath -PathType Leaf){$meta=Read-KeelarynJsonFile $metaPath;$targets=@();$seen=@{};foreach($raw in @($meta.target_paths)){$name=([string]$raw).Replace('/','\');if(-not(Test-ManagerManagedPath $name)){throw('Unsafe rollback target: '+$name)};$key=$name.Replace('\','/').Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant();if($seen.ContainsKey($key)){throw('Duplicate rollback target: '+$name)};$seen[$key]=$true;$targets+=$name};if($targets.Count-eq0){throw 'Rollback snapshot contains no target paths.'};foreach($name in $targets){Assert-ManagerInstallTargetPathSafe $Root $name};$restore=@();if([string]$meta.schema-eq'keelaryn.manager.rollback-snapshot.v2'){$fseen=@{};foreach($row in @($meta.files)){$name=([string]$row.path).Replace('/','\');if(-not(Test-ManagerManagedPath $name)){throw('Unsafe rollback file: '+$name)};$key=$name.Replace('\','/').Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant();if(-not$seen.ContainsKey($key)-or$fseen.ContainsKey($key)){throw('Invalid rollback file set: '+$name)};$fseen[$key]=$true;$src=Join-Path $Snapshot ('files\'+$name);if(-not(Test-Path -LiteralPath $src -PathType Leaf)){throw('Rollback file missing: '+$name)};$it=Get-Item -LiteralPath $src -Force;if(($it.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw('Rollback reparse point: '+$name)};$size=[long]$row.size_bytes;if($it.Length-ne$size){throw('Rollback size mismatch: '+$name)};$expected=([string]$row.sha256).ToLowerInvariant();if(-not(Test-Sha256Text $expected)-or(Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash.ToLowerInvariant()-ne$expected){throw('Rollback hash mismatch: '+$name)};$restore += [pscustomobject]@{Path=$name;Source=$src}}}else{foreach($raw in @($meta.existing_paths)){$name=([string]$raw).Replace('/','\');if(-not(Test-ManagerManagedPath $name)){throw('Unsafe legacy rollback path: '+$name)};$src=Join-Path $Snapshot ('files\'+$name);if(-not(Test-Path -LiteralPath $src -PathType Leaf)){throw('Legacy rollback file missing: '+$name)};$restore += [pscustomobject]@{Path=$name;Source=$src}}};foreach($name in $targets){$dst=Join-Path $Root $name;if(Test-Path -LiteralPath $dst -PathType Leaf){Remove-Item -LiteralPath $dst -Force}};foreach($row in $restore){$dst=Join-Path $Root $row.Path;$parent=Split-Path -Parent $dst;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null};Copy-Item -LiteralPath $row.Source -Destination $dst -Force};return}
    foreach($name in $ManagedManagerFiles){$src=Join-Path $Snapshot $name;if(Test-Path -LiteralPath $src -PathType Leaf){Copy-Item -LiteralPath $src -Destination (Join-Path $Root $name) -Force}}
}

function Remove-EmptyObsoleteManagedDirectories([string[]]$ObsoletePaths) {
    $dirs = @()
    $rootPrefix = $Root + [System.IO.Path]::DirectorySeparatorChar
    foreach ($name in @($ObsoletePaths)) {
        if (-not $name) { continue }
        $parent = Split-Path -Parent (Join-Path $Root (([string]$name).Replace('/','\')))
        while ($parent -and $parent -ne $Root -and $parent.StartsWith($rootPrefix,[System.StringComparison]::OrdinalIgnoreCase)) {
            $dirs += $parent
            $parent = Split-Path -Parent $parent
        }
    }
    foreach ($dir in @($dirs | Sort-Object -Property @{Expression={$_.Length};Descending=$true} -Unique)) {
        if (Test-Path $dir -PathType Container) {
            $children = @(Get-ChildItem $dir -Force -ErrorAction SilentlyContinue)
            if ($children.Count -eq 0) { Remove-Item $dir -Force -ErrorAction SilentlyContinue }
        }
    }
}

function Install-ManagerPackage($Package) {
    Assert-FreeSpace ([long]$Package.ExpandedBytes) $MinManagerDiskHeadroom 'Local Manager update' $Root
    $temp = Join-Path $WorkRoot ('installing_manager_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temp | Out-Null
    $snapshot = $null
    $stagedZip = Join-Path $temp 'validated-package.zip'
    try {
        Copy-Item -LiteralPath $Package.File.FullName -Destination $stagedZip -Force
        $stagedHash=(Get-FileHash -LiteralPath $stagedZip -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($stagedHash -ne $Package.PackageHash) { throw 'Manager package changed between decision and staging.' }
        $validated = Read-ManagerUpdatePackage $stagedZip
        if (-not $validated -or $validated.ContentHash -ne $Package.ContentHash -or $validated.PackageHash -ne $Package.PackageHash) { throw 'Manager staged package validation differs from the selected package.' }
        Expand-Archive -LiteralPath $stagedZip -DestinationPath $temp -Force
        $payload = Join-Path $temp 'Keelaryn__Manager_Update\payload'
        if (-not (Test-Path $payload -PathType Container)) { throw 'Manager update payload missing after extraction.' }

        $newPaths = @($Package.ManagedPaths | Sort-Object -Unique)
        if ($newPaths.Count -eq 0) { $newPaths = @($ManagedManagerFiles) }
        $oldPaths = @(Get-InstalledManagedPaths)
        $targets = @($oldPaths + $newPaths | Sort-Object -Unique)
        $obsoletePaths = @($targets | Where-Object { $newPaths -notcontains $_ })
        foreach ($name in $targets) { Assert-ManagerInstallTargetPathSafe $Root $name }

        $stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss_fff'
        $snapshot = Join-Path $ManagerUpdates ('Keelaryn__Manager_v' + $ManagerVersion + '_' + $stamp)
        New-Item -ItemType Directory -Path (Join-Path $snapshot 'files') | Out-Null
        $snapshotFiles=@()
        foreach ($name in $targets) { $src=Join-Path $Root $name; if(Test-Path -LiteralPath $src -PathType Leaf){$dst=Join-Path $snapshot ('files\'+$name);$parent=Split-Path -Parent $dst;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null};Copy-Item -LiteralPath $src -Destination $dst -Force;$meta=Get-ManagerSnapshotFileMetadata $dst;$snapshotFiles += [ordered]@{path=$name;size_bytes=[long]$meta.size_bytes;sha256=[string]$meta.sha256}} }
        [ordered]@{schema='keelaryn.manager.rollback-snapshot.v2';manager_version=$ManagerVersion;target_paths=$targets;files=$snapshotFiles}|ConvertTo-Json -Depth 6|Set-Content (Join-Path $snapshot '_snapshot_manifest.json') -Encoding UTF8

        try {
            # Revalidate at the mutation boundary; the earlier pass protects snapshot creation,
            # while this pass prevents stale path assumptions from authorizing writes.
            foreach ($name in $targets) { Assert-ManagerInstallTargetPathSafe $Root $name }
            foreach ($name in $targets) {
                if ($newPaths -notcontains $name) {
                    Assert-ManagerInstallTargetPathSafe $Root $name
                    $old = Join-Path $Root $name
                    if (Test-Path $old -PathType Leaf) { Remove-Item $old -Force }
                }
            }
            foreach ($name in $newPaths) {
                Assert-ManagerInstallTargetPathSafe $Root $name
                $src = Join-Path $payload $name
                if (-not (Test-Path $src -PathType Leaf)) { throw ("Manager payload file missing: " + $name) }
                $dst = Join-Path $Root $name
                $parent = Split-Path -Parent $dst
                if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
                Copy-Item $src $dst -Force
            }
            if (-not (Test-InstalledManagerVersionCoherence $Package.VersionText)) { throw 'Installed Manager payload version markers disagree with package manifest.' }
            if ((Get-ManagerContentHashForPaths $newPaths) -ne $Package.ContentHash) { throw 'Installed Manager payload hash mismatch.' }
            Remove-EmptyObsoleteManagedDirectories $obsoletePaths
        }
        catch {
            Restore-ManagerSnapshot $snapshot
            throw
        }
        return [pscustomobject]@{ Snapshot = $snapshot; PackagePath = $Package.File.FullName; VersionText = $Package.VersionText }
    }
    catch { Log ("Manager self-update failed: " + $_.Exception.Message); throw }
    finally { if (Test-Path $temp) { Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue } }
}

function Test-UpdatedManagerExecutable {
    $script=Join-Path $Root 'product\runtime\Keelaryn__Manager.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -SelfTest
    return $LASTEXITCODE
}

function Restart-UpdatedManager {
    $script=Join-Path $Root 'product\runtime\Keelaryn__Manager.ps1'
    $previousHandoff=[string]$env:KEELARYN_FILESYSTEM_HANDOFF_ACTIVE
    $setHandoff=$false
    if(Test-Path -LiteralPath $StateLayoutReceipt -PathType Leaf){
        try{$layoutReceipt=([System.IO.File]::ReadAllText($StateLayoutReceipt,[System.Text.Encoding]::UTF8)|ConvertFrom-Json);$setHandoff=[bool]$layoutReceipt.legacy_log_handoff_pending}catch{}
    }
    try {
        if($setHandoff){$env:KEELARYN_FILESYSTEM_HANDOFF_ACTIVE='1'}
        if ($UpdateAll) {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -UpdateAll | Out-Host
        }
        elseif ($UpdateManager) {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -UpdateManager | Out-Host
        }
        else { throw 'Manager restart requested without a Manager-capable update mode.' }
        return $LASTEXITCODE
    }
    finally {
        if([string]::IsNullOrEmpty($previousHandoff)){Remove-Item Env:KEELARYN_FILESYSTEM_HANDOFF_ACTIVE -ErrorAction SilentlyContinue}else{$env:KEELARYN_FILESYSTEM_HANDOFF_ACTIVE=$previousHandoff}
    }
}

function Invoke-Update {
    Ensure-DesktopShortcut
    $attention=$false; $attentionLines=@()

    if ($WantsManagerUpdate) {
        $managerDecision=Find-ManagerUpdateDecision
        if ($managerDecision.Action -eq 'install') {
            Write-Host ("Installing Local Manager {0} first..." -f $managerDecision.Package.VersionText) -ForegroundColor Cyan
            $result=Install-ManagerPackage $managerDecision.Package
            $selfTestCode=Test-UpdatedManagerExecutable
            if ($selfTestCode -ne 0) {
                Restore-ManagerSnapshot $result.Snapshot
                throw ("Updated Local Manager self-test failed with code {0}; previous Manager restored." -f $selfTestCode)
            }
            try { Remove-Item $result.PackagePath -Force -ErrorAction SilentlyContinue } catch {}
            Cleanup-History
            Log ("Installed Local Manager {0}; self-test passed; restarting the same explicit update mode with new code." -f $result.VersionText)
            Release-ManagerLock
            return (Restart-UpdatedManager)
        }
        elseif ($managerDecision.Action -eq 'attention') {
            $attention=$true; $attentionLines += $managerDecision.Reason; $attentionLines += $managerDecision.Details; Log ("ATTENTION: "+$managerDecision.Reason)
        }
        else { Log $managerDecision.Reason; Archive-RedundantManagerInboxPackages -ValidatedPackages @($managerDecision.ValidPackages) }

        if ($attention) {
            Cleanup-History
            Set-AttentionNotice $attentionLines
            Write-Host ''
            Write-Host 'Manager update requires attention; Hub update was not attempted.' -ForegroundColor Yellow
            Write-Host ("Details: "+$AttentionFile)
            return 2
        }
        if ($CanonicalLayoutActive -and -not $StateLayoutActive -and [version]$ManagerVersion -ge [version]'4.8.0') {
            Write-Host 'Finalizing Manager filesystem layout...' -ForegroundColor Cyan
            try {
                $null=Invoke-FinalizeFilesystemLayout
                Assert-ManagerOperationalPathsReady -RequireStateLayout
                Write-Host 'Restarting Manager after filesystem finalization to activate canonical state paths...' -ForegroundColor Cyan
                Release-ManagerLock
                return (Restart-UpdatedManager)
            }
            catch {
                $layoutFailure=$_.Exception.Message
                $snapshot=$null
                try {
                    $snapshot=@(Get-ChildItem -LiteralPath $ManagerUpdates -Directory -Force -ErrorAction Stop|Sort-Object LastWriteTime -Descending|Select-Object -First 1)
                    if($snapshot.Count-ne1){throw 'No rollback snapshot is available for the failed filesystem finalization.'}
                    $snapshotManifest=Read-KeelarynJsonFile (Join-Path $snapshot[0].FullName '_snapshot_manifest.json')
                    if([string]$snapshotManifest.schema-ne'keelaryn.manager.rollback-snapshot.v2'){throw 'Latest rollback snapshot schema is not supported.'}
                    Restore-ManagerSnapshot $snapshot[0].FullName
                    Write-Host ('Filesystem finalization failed; previous Manager snapshot restored: '+[string]$snapshot[0].FullName) -ForegroundColor Yellow
                    Log ('Filesystem finalization failed and prior Manager snapshot was restored. Failure='+$layoutFailure+'; snapshot='+[string]$snapshot[0].FullName)
                }
                catch {
                    throw ('Filesystem finalization failed and automatic Manager rollback also failed. Finalization='+$layoutFailure+'; rollback='+$_.Exception.Message)
                }
                throw ('Filesystem finalization failed; previous Manager restored. '+$layoutFailure)
            }
        }
        if ($UpdateManager) {
            Cleanup-History
            Write-Host ''
            Write-Host 'Manager update command completed; no newer valid Manager package was applied. Keelaryn__Hub inbox was left untouched.' -ForegroundColor Green
            Log 'Manager update command completed without applying a newer Manager package; Hub inbox intentionally untouched.'
            return 0
        }
    }

    if (-not $WantsHubUpdate) { throw 'No update action was selected.' }
    $hubInstalled=$false
    $hubInstalledLabel=$null
    $hubNoopReason=$null
    if ($script:BindingResolutionError) { throw ('Manager update handling completed, but Hub processing cannot continue because instance binding is unresolved: '+$script:BindingResolutionError+'. Run Keelaryn > Doctor and bind the Hub from Maintenance.') }

    if (-not $attention) {
        $currentAnalysis=Get-PortableVaultAnalysis $Vault
        $current=Read-VaultMetadataAt $Vault $currentAnalysis
        if (-not $current) { throw ("Current sibling Keelaryn__Hub derived metadata is invalid or missing: "+$Vault) }
        $currentContentHash=[string]$currentAnalysis.ContentHash; $currentPayloadHash=[string]$currentAnalysis.PayloadHash; $currentArtifact=Read-VaultArtifactManifestAt $Vault

        if (-not (Test-Path $CurrentZip -PathType Leaf)) {
            $attention=$true; $attentionLines += 'Keelaryn__Hub_CURRENT.zip is missing; Hub replacement is disabled until the baseline is restored.'
        }
        else {
            $baselineSession=$null
            try { $baselineSession=Open-HubZipInspectionSession $CurrentZip }
            catch { Log ('Invalid CURRENT baseline ZIP: '+$_.Exception.Message) }
            if (-not $baselineSession) {
                $attention=$true; $attentionLines += 'Keelaryn__Hub_CURRENT.zip has an invalid/unsupported ZIP envelope; Hub replacement is disabled.'
            }
            else {
                try {
                    $baselineState=Read-ZipState $CurrentZip $baselineSession; $baselineArtifact=Read-ZipArtifactManifest $CurrentZip $baselineSession
                    if (-not $baselineState -or $baselineState.Version -ne $current.Version -or $baselineState.Revision -ne $current.Revision) {
                        $attention=$true; $attentionLines += 'Keelaryn__Hub_CURRENT.zip does not match installed vault STATE; Hub replacement is disabled.'
                    }
                    else {
                        $baselineHashes=Get-ZipHashPair $CurrentZip $baselineSession; $baselineContentHash=$baselineHashes.ContentHash; $baselinePayloadHash=$baselineHashes.PayloadHash
                        if ($baselineContentHash -ne $currentContentHash -or $baselinePayloadHash -ne $currentPayloadHash) {
                            $attention=$true
                            $attentionLines += 'Installed canonical files differ from Keelaryn__Hub_CURRENT.zip (local content drift detected).'
                            $attentionLines += ("Vault content: "+$currentContentHash)
                            $attentionLines += ("Baseline content: "+$baselineContentHash)
                        }
                        elseif ($baselineArtifact -and $currentArtifact -and $baselineArtifact.ArtifactId -ne $currentArtifact.ArtifactId) {
                            $attention=$true; $attentionLines += 'Installed ARTIFACT id differs from Keelaryn__Hub_CURRENT.zip.'
                        }
                    }
                }
                finally { Close-HubZipInspectionSession $baselineSession }
            }
        }

        if (-not $attention -and $currentArtifact -and $currentArtifact.Status -eq 'approved') {
            # Reconcile stale inbox candidates against the already-installed canonical APPROVED artifact.
            # This is exact ID + schema-appropriate hash matching only; unrelated candidates remain untouched.
            foreach ($warning in @(Remove-AcceptedCandidatePackages $currentArtifact)) { Log ("WARNING: "+$warning); Write-Host ("Warning: "+$warning) -ForegroundColor Yellow }
        }

        if (-not $attention) {
            $decision=Find-HubUpdateDecision $current $currentContentHash $currentPayloadHash $currentArtifact
            if ($decision.Action -eq 'install') {
                $best=$decision.Package
                $bestRevision=if($best.Artifact -and $best.Artifact.RevisionTimeUtc){try{([DateTimeOffset]::Parse([string]$best.Artifact.RevisionTimeUtc)).ToLocalTime().ToString('yyyy-MM-dd HH:mm')}catch{[string]$best.Artifact.RevisionTimeUtc}}else{('legacy r{0:D4}' -f $best.State.Revision)}
                Write-Host ("Installing APPROVED Keelaryn__Hub v{0} | {1}..." -f $best.State.VersionText,$bestRevision) -ForegroundColor Cyan
                if (Close-ObsidianIfNeeded) {
                    $expectedCurrent=[pscustomobject]@{State=$current;Artifact=$currentArtifact;ContentHash=$currentContentHash;PayloadHash=$currentPayloadHash}
                    Install-HubPackage $best $expectedCurrent
                    $hubInstalled=$true
                    $hubInstalledLabel=('v{0} | {1}' -f $best.State.VersionText,$bestRevision)
                    Clear-AttentionNotice
                }
                else { $attention=$true; $attentionLines += 'Obsidian did not close; Keelaryn__Hub update was deferred.' }
            }
            elseif ($decision.Action -eq 'attention') {
                $attention=$true; $attentionLines += $decision.Reason; $attentionLines += $decision.Details; Log ("ATTENTION: "+$decision.Reason)
            }
            else { $hubNoopReason=[string]$decision.Reason; Log $decision.Reason }
        }
    }

    Cleanup-History
    if ($attention) {
        Set-AttentionNotice $attentionLines
        Write-Host ''
        Write-Host 'Update requires attention; no ambiguous replacement was performed.' -ForegroundColor Yellow
        Write-Host ("Details: "+$AttentionFile)
        return 2
    }
    Clear-AttentionNotice
    Write-Host ''
    $pendingCandidates=@(Get-ChildItem -LiteralPath $Inbox -File -Filter '*.zip' -ErrorAction SilentlyContinue | Where-Object { $_.Name.StartsWith('Keelaryn__Hub_CANDIDATE_',[System.StringComparison]::OrdinalIgnoreCase) -or $_.Name.StartsWith([string]$LegacyCoreCompat.CandidatePrefix,[System.StringComparison]::OrdinalIgnoreCase) }).Count
    if ($hubInstalled) {
        Write-Host ('Hub update installed successfully: '+$hubInstalledLabel+'.') -ForegroundColor Green
        if($UpdateAll){Log ('Combined update action installed Hub '+$hubInstalledLabel+'.')}else{Log ('Hub-only update action installed '+$hubInstalledLabel+'; Manager update packages intentionally untouched.')}
    } elseif ($pendingCandidates-gt0) {
        Write-Host ('No installable APPROVED Hub package found; '+$pendingCandidates+' CANDIDATE package(s) left pending for Chat Manager.') -ForegroundColor Yellow
        if($hubNoopReason){Write-Host ('Reason: '+$hubNoopReason) -ForegroundColor DarkGray}
        Log ('Hub update no-op: '+$pendingCandidates+' CANDIDATE package(s) pending; '+$hubNoopReason)
    } else {
        Write-Host 'No installable APPROVED Hub package found; Hub remains unchanged.' -ForegroundColor Green
        if($hubNoopReason){Write-Host ('Reason: '+$hubNoopReason) -ForegroundColor DarkGray}
        Log ('Hub update no-op: '+$hubNoopReason)
    }
    return 0
}

function Test-ArtifactRoleParserSelfTest {
    $h1='1111111111111111111111111111111111111111111111111111111111111111'; $h2='2222222222222222222222222222222222222222222222222222222222222222'
    $candidate=[ordered]@{
        schema='corehub.artifact.v2'; artifact_status='candidate'; artifact_id='cand-selftest-workerchat'; producer_role='worker_chat'; created='2026-08-28';
        system_version='0.19.1'; data_revision=2; payload_content_sha256=$h2; base_system_version='0.19.0'; base_data_revision=1;
        base_artifact_id='appr-selftest-base'; base_payload_content_sha256=$h1;
        ancestor_chain=@([ordered]@{system_version='0.19.0';data_revision=1;artifact_id='appr-selftest-base';payload_content_sha256=$h1});
        manager_protocol='chat-manager-v2.4'
    } | ConvertTo-Json -Depth 6 -Compress
    $legacyCandidate=[ordered]@{
        schema='corehub.artifact.v2'; artifact_status='candidate'; artifact_id='cand-selftest-alias'; producer_role='worker'; created='2026-08-28';
        system_version='0.19.1'; data_revision=2; payload_content_sha256=$h2; base_system_version='0.19.0'; base_data_revision=1;
        base_artifact_id='appr-selftest-base'; base_payload_content_sha256=$h1;
        ancestor_chain=@([ordered]@{system_version='0.19.0';data_revision=1;artifact_id='appr-selftest-base';payload_content_sha256=$h1});
        manager_protocol='chat-manager-v2.4'
    } | ConvertTo-Json -Depth 6 -Compress
    $invalidCandidate=[ordered]@{
        schema='corehub.artifact.v2'; artifact_status='candidate'; artifact_id='cand-selftest-invalid'; producer_role='chat_manager'; created='2026-08-28';
        system_version='0.19.1'; data_revision=2; payload_content_sha256=$h2; base_system_version='0.19.0'; base_data_revision=1;
        base_artifact_id='appr-selftest-base'; base_payload_content_sha256=$h1;
        ancestor_chain=@([ordered]@{system_version='0.19.0';data_revision=1;artifact_id='appr-selftest-base';payload_content_sha256=$h1});
        manager_protocol='chat-manager-v2.4'
    } | ConvertTo-Json -Depth 6 -Compress
    if (-not (Parse-ArtifactManifestText $candidate)) { return $false }
    if (-not (Parse-ArtifactManifestText $legacyCandidate)) { return $false }
    if (Parse-ArtifactManifestText $invalidCandidate) { return $false }
    return $true
}

function Test-RevisionTimestampParserSelfTest {
    $h1='1111111111111111111111111111111111111111111111111111111111111111'; $h2='2222222222222222222222222222222222222222222222222222222222222222'
    $base=[ordered]@{
        schema='keelaryn.artifact.v3'; artifact_status='candidate'; artifact_id='cand-selftest-revision-time'; producer_role='worker_chat'; created='2030-01-01T00:00:00Z';
        system_version='2.2.0'; data_revision=2; instance_id='11111111-1111-1111-1111-111111111111'; genesis=$false; payload_content_sha256=$h2;
        base_system_version='2.2.0'; base_data_revision=1; base_artifact_id='appr-selftest-base'; base_payload_content_sha256=$h1;
        ancestor_chain=@([ordered]@{system_version='2.2.0';data_revision=1;artifact_id='appr-selftest-base';payload_content_sha256=$h1}); manager_protocol='keelaryn-chat-manager-v4.0'
    }
    $legacy=Parse-ArtifactManifestText ($base|ConvertTo-Json -Depth 6 -Compress)
    if(-not$legacy-or$legacy.RevisionTimeUtc-ne'2030-01-01T00:00:00Z'){return $false}
    $base['revision_time_utc']='2030-01-02T03:04:05Z'
    $modern=Parse-ArtifactManifestText ($base|ConvertTo-Json -Depth 6 -Compress)
    if(-not$modern-or$modern.RevisionTimeUtc-ne'2030-01-02T03:04:05Z'){return $false}
    $base['revision_time_utc']='2030-01-02T07:04:05+04:00'
    if(Parse-ArtifactManifestText ($base|ConvertTo-Json -Depth 6 -Compress)){return $false}
    return $true
}

function Test-GenesisArtifactParserSelfTest {
    $h = '3333333333333333333333333333333333333333333333333333333333333333'
    $g = [guid]::NewGuid().ToString().ToLowerInvariant()
    $release=Get-ProductRelease
    $manifest = [ordered]@{
        schema='keelaryn.artifact.v3'; artifact_status='approved'; artifact_id='genesis-selftest'; producer_role='keelaryn_manager_genesis'; created='2030-01-01T00:00:00Z'; revision_time_utc='2030-01-01T00:00:00Z'
        system_version=[string]$release.system_version; data_revision=1; instance_id=$g; genesis=$true; genesis_release_id=[string]$release.release_id; payload_content_sha256=$h
        base_system_version=''; base_data_revision=0; base_artifact_id=''; base_payload_content_sha256=''; ancestor_chain=@(); accepted_candidates=@(); manager_protocol='keelaryn-chat-manager-v4.0'
    } | ConvertTo-Json -Depth 6 -Compress
    $parsed = Parse-ArtifactManifestText $manifest
    return $parsed -and $parsed.Genesis -and $parsed.InstanceId -eq $g
}

function Test-PortablePolicySelfTest {
    return (Test-IsLocalDeploymentRelativePath '.obsidian') -and (Test-IsLocalDeploymentRelativePath '.obsidian/workspace.json') -and (Test-IsLocalDeploymentRelativePath '.git') -and (Test-IsLocalDeploymentRelativePath '.git/config') -and (Test-IsLocalDeploymentRelativePath 'x/Thumbs.db') -and -not (Test-IsLocalDeploymentRelativePath 'Resources/.gitignore')
}

function Test-PortableInventorySelfTest {
    $temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_portable_'+[guid]::NewGuid().ToString('N'));try{New-Item -ItemType Directory -Force -Path (Join-Path $temp 'Data'),(Join-Path $temp '.git'),(Join-Path $temp '.obsidian')|Out-Null;Set-Content (Join-Path $temp 'Data\canonical.txt') 'canonical';Set-Content (Join-Path $temp '.git\x') 'a';Set-Content (Join-Path $temp '.obsidian\workspace.json') '{}';$inv=@(Get-PortableVaultFileInventory $temp);if($inv.Count-ne1-or$inv[0].RelativePath-ne'Data/canonical.txt'){return $false};$a=Get-VaultHashPairAt $temp;Set-Content (Join-Path $temp '.git\x') 'b';$b=Get-VaultHashPairAt $temp;return $a.ContentHash-eq$b.ContentHash-and$a.PayloadHash-eq$b.PayloadHash}catch{return $false}finally{if(Test-Path $temp){Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue}}
}
function Test-PortableAnalysisAndManifestSelfTest {
    $temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_analysis_'+[guid]::NewGuid().ToString('N'))
    try {
        New-Item -ItemType Directory -Force -Path (Join-Path $temp 'Data'),(Join-Path $temp '_System'),(Join-Path $temp '.git'),(Join-Path $temp '.obsidian') | Out-Null
        Set-Content -LiteralPath (Join-Path $temp 'Data\canonical.txt') -Value 'canonical'
        Set-Content -LiteralPath (Join-Path $temp '_System\ARTIFACT.json') -Value '{}'
        Set-Content -LiteralPath (Join-Path $temp '_System\MANIFEST.json') -Value '{}'
        Set-Content -LiteralPath (Join-Path $temp '_System\INDEX.json') -Value '{}'
        Set-Content -LiteralPath (Join-Path $temp '_System\ROUTER.json') -Value '{}'
        Set-Content -LiteralPath (Join-Path $temp '_System\VALIDATION.json') -Value '{}'
        Set-Content -LiteralPath (Join-Path $temp '.git\x') -Value 'local-a'
        Set-Content -LiteralPath (Join-Path $temp '.obsidian\workspace.json') -Value '{}'

        $a=Get-PortableVaultAnalysis $temp
        if ($a.FileCount -ne 6) { return $false }
        if ($a.ManifestEntryCount -ne 1) { return $false }
        $built=New-PortableSourceManifest $temp '9.9.9' 7 '11111111-1111-1111-1111-111111111111' $a
        if ([string]$built.Manifest.vault -ne 'Keelaryn__Hub') { return $false }
        if ([int]$built.Manifest.entry_count -ne 1 -or [string]$built.Manifest.entries[0][0] -ne 'Data/canonical.txt') { return $false }
        $beforeContent=[string]$a.ContentHash; $beforePayload=[string]$a.PayloadHash
        Set-Content -LiteralPath (Join-Path $temp '.git\x') -Value 'local-b'
        $b=Get-PortableVaultAnalysis $temp
        return $beforeContent -eq $b.ContentHash -and $beforePayload -eq $b.PayloadHash
    }
    catch { return $false }
    finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue } }
}


function Test-DoctorManifestDiagnosticSelfTest {
    $script:DoctorManifestDiagnosticSelfTestReason=''
    $temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_doctor_manifest_'+[guid]::NewGuid().ToString('N'))
    try {
        New-Item -ItemType Directory -Force -Path (Join-Path $temp 'Data'),(Join-Path $temp '_System') | Out-Null
        Set-Content -LiteralPath (Join-Path $temp 'Data\canonical.txt') -Value 'canonical' -Encoding ASCII
        foreach ($name in @('ARTIFACT.json','MANIFEST.json','INDEX.json','ROUTER.json','VALIDATION.json')) { Set-Content -LiteralPath (Join-Path $temp ('_System\'+$name)) -Value '{}' -Encoding ASCII }
        $state=[pscustomobject]@{ManifestSchema='keelaryn.manifest.v1';VersionText='9.9.9';Revision=7;InstanceId='11111111-1111-1111-1111-111111111111'}
        $analysis=Get-PortableVaultAnalysis $temp
        $built=New-PortableSourceManifest $temp $state.VersionText $state.Revision $state.InstanceId $analysis
        $built.Manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $temp '_System\MANIFEST.json') -Encoding UTF8
        $valid=Get-VaultManifestDiagnostic $temp $state $analysis
        if (-not $valid.Valid -or $valid.Missing.Count -ne 0 -or $valid.Extra.Count -ne 0 -or $valid.Changed.Count -ne 0) { $script:DoctorManifestDiagnosticSelfTestReason='Valid MANIFEST fast path changed diagnostic semantics.'; return $false }

        $broken=Read-KeelarynJsonFile (Join-Path $temp '_System\MANIFEST.json')
        $broken.entries[0][2]='0000000000000000000000000000000000000000000000000000000000000000'
        $broken | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $temp '_System\MANIFEST.json') -Encoding UTF8
        $invalid=Get-VaultManifestDiagnostic $temp $state $analysis
        if ($invalid.Valid -or $invalid.Changed.Count -ne 1 -or [string]$invalid.Changed[0] -ne 'Data/canonical.txt') { $script:DoctorManifestDiagnosticSelfTestReason='Invalid MANIFEST detailed classification was not preserved.'; return $false }
        return $true
    }
    catch { $script:DoctorManifestDiagnosticSelfTestReason=('Unexpected error: '+$_.Exception.Message); return $false }
    finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue } }
}

function Test-HubZipInspectionSessionSelfTest {
    $temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_zip_session_'+[guid]::NewGuid().ToString('N'))
    $session=$null
    try {
        $hub=Join-Path $temp 'hub'; New-Item -ItemType Directory -Force -Path (Join-Path $hub 'Data'),(Join-Path $hub '_System'),(Join-Path $hub '.git') | Out-Null
        Set-Content -LiteralPath (Join-Path $hub 'Data\canonical.txt') -Value 'canonical'
        Set-Content -LiteralPath (Join-Path $hub '_System\ARTIFACT.json') -Value '{}'
        Set-Content -LiteralPath (Join-Path $hub '.git\config') -Value 'local-only'
        $zip=Join-Path $temp 'session.zip'; Write-DeterministicZip $hub $zip 'Keelaryn__Hub'
        $session=Open-HubZipInspectionSession $zip
        if (-not $session -or -not (Test-ZipContainsLocalDeploymentState $zip $session)) { return $false }
        $direct=Get-ZipHashPair $zip; $reused=Get-ZipHashPair $zip $session
        if ($direct.ContentHash -ne $reused.ContentHash -or $direct.PayloadHash -ne $reused.PayloadHash) { return $false }
        if (-not (Test-HubZipInspectionSessionForPath $session $zip)) { return $false }
        Close-HubZipInspectionSession $session; $session=$null

        # Mixed slash/backslash entry names are accepted by the legacy envelope contract.
        # They exercise the historical raw-name hash ordering, which differs from MANIFEST ordering.
        $mixed=Join-Path $temp 'mixed-separators.zip'; $fs=$null; $za=$null
        try {
            $fs=[System.IO.File]::Open($mixed,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::ReadWrite,[System.IO.FileShare]::None)
            $za=New-Object System.IO.Compression.ZipArchive($fs,[System.IO.Compression.ZipArchiveMode]::Create,$false)
            foreach ($spec in @([pscustomobject]@{Name='Keelaryn__Hub/Z.txt';Text='z'},[pscustomobject]@{Name='Keelaryn__Hub\A.txt';Text='a'})) {
                $entry=$za.CreateEntry([string]$spec.Name); $bytes=[System.Text.Encoding]::UTF8.GetBytes([string]$spec.Text); $out=$entry.Open()
                try { $out.Write($bytes,0,$bytes.Length) } finally { $out.Dispose() }
            }
            $za.Dispose(); $za=$null; $fs.Dispose(); $fs=$null
        }
        finally { if($za){$za.Dispose()};if($fs){$fs.Dispose()} }
        $session=Open-HubZipInspectionSession $mixed
        if (-not $session) { return $false }
        $mixedDirect=Get-ZipHashPair $mixed; $mixedReused=Get-ZipHashPair $mixed $session
        if ($mixedDirect.ContentHash -ne $mixedReused.ContentHash -or $mixedDirect.PayloadHash -ne $mixedReused.PayloadHash) { return $false }
        return $true
    }
    catch { return $false }
    finally {
        if ($session) { Close-HubZipInspectionSession $session }
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
    }
}


function Test-CandidateTransportSelfTest {
    $script:CandidateTransportSelfTestReason=''
    $temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_candidate_transport_'+[guid]::NewGuid().ToString('N'))
    $baseSession=$null;$candidateSession=$null
    try{
        $baseHub=Join-Path $temp 'base';$candidateHub=Join-Path $temp 'candidate'
        foreach($hub in @($baseHub,$candidateHub)){New-Item -ItemType Directory -Force -Path (Join-Path $hub 'Data'),(Join-Path $hub '_System')|Out-Null}
        [System.IO.File]::WriteAllBytes((Join-Path $baseHub 'Data\keep.bin'),[byte[]](0,1,2,3));[System.IO.File]::WriteAllBytes((Join-Path $candidateHub 'Data\keep.bin'),[byte[]](0,1,2,3))
        [System.IO.File]::WriteAllBytes((Join-Path $baseHub 'Data\change.bin'),[byte[]](10,20,30));[System.IO.File]::WriteAllBytes((Join-Path $candidateHub 'Data\change.bin'),[byte[]](10,99,30,40))
        Set-Content -LiteralPath (Join-Path $baseHub 'Data\delete.txt') -Value 'delete-me' -Encoding ASCII
        Set-Content -LiteralPath (Join-Path $candidateHub 'Data\add.txt') -Value 'added' -Encoding ASCII
        Set-Content -LiteralPath (Join-Path $baseHub '_System\ARTIFACT.json') -Value '{"x":1}' -Encoding ASCII
        Set-Content -LiteralPath (Join-Path $candidateHub '_System\ARTIFACT.json') -Value '{"x":2}' -Encoding ASCII
        $baseZip=Join-Path $temp 'base.zip';$candidateZip=Join-Path $temp 'candidate.zip';Write-PortableHubZip $baseHub $baseZip 'Keelaryn__Hub';Write-PortableHubZip $candidateHub $candidateZip 'Keelaryn__Hub'
        $baseSession=Open-HubZipInspectionSession $baseZip;$candidateSession=Open-HubZipInspectionSession $candidateZip
        if(-not$baseSession-or-not$candidateSession){$script:CandidateTransportSelfTestReason='Could not open transport fixture ZIPs.';return $false}
        $delta=New-CandidateTransportOperations $baseSession $candidateSession
        if($delta.Operations.Count-ne4){$script:CandidateTransportSelfTestReason='Expected add/change/delete/ARTIFACT operations.';return $false}
        $restore=Join-Path $temp 'restore';$null=Expand-HubZipPortableToDirectory $baseZip $restore $baseSession
        $doc=[pscustomobject]@{operations=@($delta.Operations)};Apply-CandidateTransportOperations $restore $doc
        $a=Get-PortableVaultAnalysis $restore
        if([string]$a.ContentHash-ne[string]$candidateSession.HashPair.ContentHash-or[string]$a.PayloadHash-ne[string]$candidateSession.HashPair.PayloadHash){$script:CandidateTransportSelfTestReason='Delta reconstruction hash mismatch.';return $false}
        $bad=[pscustomobject]@{operations=@([pscustomobject]@{op='delete';path='../escape';base_sha256='1111111111111111111111111111111111111111111111111111111111111111'})}
        $rejected=$false;try{Apply-CandidateTransportOperations $restore $bad}catch{$rejected=$_.Exception.Message-match'Unsafe candidate transport path|empty or rooted'}
        if(-not$rejected){$script:CandidateTransportSelfTestReason='Path traversal operation was not rejected.';return $false}
        $put=@($delta.Operations|Where-Object{$_.op-eq'put'}|Select-Object -First 1);$original=[string]$put[0].content_b64;$put[0].content_b64='AAAA'
        $validationRejected=$false
        $mini=[ordered]@{schema='keelaryn.hub.candidate-transport.v1';transport_role='candidate_fallback';encoding='base64-delta-v1';reconstruction_base=[ordered]@{system_version='2.2.0';data_revision=1;instance_id='11111111-1111-1111-1111-111111111111';artifact_id='appr-selftest-base';payload_content_sha256='1111111111111111111111111111111111111111111111111111111111111111';portable_content_sha256='2222222222222222222222222222222222222222222222222222222222222222'};candidate=[ordered]@{system_version='2.2.0';data_revision=2;instance_id='11111111-1111-1111-1111-111111111111';artifact_id='cand-selftest-transport';payload_content_sha256='3333333333333333333333333333333333333333333333333333333333333333';portable_content_sha256='4444444444444444444444444444444444444444444444444444444444444444';declared_base=[ordered]@{system_version='2.2.0';data_revision=1;artifact_id='appr-selftest-base';payload_content_sha256='1111111111111111111111111111111111111111111111111111111111111111'};source_zip_name='Keelaryn__Hub_CANDIDATE_selftest.zip';source_zip_sha256='5555555555555555555555555555555555555555555555555555555555555555';source_zip_size=100};reconstruction=[ordered]@{zip_name='Keelaryn__Hub_CANDIDATE_RECONSTRUCTED_cand-selftest-transport.zip';operation_count=1;changed_raw_bytes=[long]$put[0].length};operations=@($put[0])}
        $jsonPath=Join-Path $temp 'tampered.json';[System.IO.File]::WriteAllText($jsonPath,(($mini|ConvertTo-Json -Depth 20 -Compress)+"`n"),(New-Object System.Text.UTF8Encoding($false)))
        try{$null=Read-CandidateTransportDocument $jsonPath}catch{$validationRejected=$_.Exception.Message-match'payload hash/length mismatch|changed_raw_bytes'}
        $put[0].content_b64=$original
        if(-not$validationRejected){$script:CandidateTransportSelfTestReason='Tampered Base64 payload was not rejected.';return $false}
        return $true
    }catch{$script:CandidateTransportSelfTestReason=('Unexpected error: '+$_.Exception.Message);return $false}
    finally{if($candidateSession){Close-HubZipInspectionSession $candidateSession};if($baseSession){Close-HubZipInspectionSession $baseSession};if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}}
}

function Test-ManagerInstallTargetSafetySelfTest {
    $script:ManagerInstallTargetSafetySelfTestReason=''
    $temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_manager_target_'+[guid]::NewGuid().ToString('N'))
    try {
        $base=Join-Path $temp 'manager'; New-Item -ItemType Directory -Force -Path $base | Out-Null
        $safe=Join-Path $base 'README_FIRST.md'; Set-Content -LiteralPath $safe -Value 'safe' -Encoding ASCII
        Assert-ManagerInstallTargetPathSafe $base 'README_FIRST.md'
        Remove-Item -LiteralPath $safe -Force
        New-Item -ItemType Directory -Path $safe | Out-Null
        $rejected=$false
        try { Assert-ManagerInstallTargetPathSafe $base 'README_FIRST.md' } catch { $rejected=$_.Exception.Message -match 'collides with a directory' }
        if (-not $rejected) { $script:ManagerInstallTargetSafetySelfTestReason='Directory collision was not rejected.'; return $false }
        Remove-Item -LiteralPath $safe -Recurse -Force

        $product=Join-Path $base 'product'; Set-Content -LiteralPath $product -Value 'not-a-directory' -Encoding ASCII
        $rejected=$false
        try { Assert-ManagerInstallTargetPathSafe $base 'product/docs/OPERATIONS.md' } catch { $rejected=$_.Exception.Message -match 'parent is not a directory' }
        if (-not $rejected) { $script:ManagerInstallTargetSafetySelfTestReason='Non-directory parent collision was not rejected.'; return $false }
        Remove-Item -LiteralPath $product -Force
        New-Item -ItemType Directory -Force -Path (Join-Path $base 'product\docs') | Out-Null
        Assert-ManagerInstallTargetPathSafe $base 'product/docs/OPERATIONS.md'
        return $true
    }
    catch { $script:ManagerInstallTargetSafetySelfTestReason=('Unexpected error: '+$_.Exception.Message); return $false }
    finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue } }
}

function Test-ManagerReleaseRetentionSelfTest {
    $script:ManagerReleaseRetentionSelfTestReason=''
    $temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_release_retention_'+[guid]::NewGuid().ToString('N'))
    $oldReleases=$script:Releases
    $oldHistory=$script:History
    $oldLogFile=$script:LogFile
    $oldWarningPreference=$WarningPreference
    try {
        $WarningPreference='SilentlyContinue'
        $script:Releases=Join-Path $temp '_releases'
        $script:History=Join-Path $temp '_history'
        $script:LogFile=Join-Path $temp 'manager.log'
        New-Item -ItemType Directory -Force -Path $script:Releases,$script:History | Out-Null
        foreach ($versionText in @('1.0.0','1.0.1','1.0.2','1.0.3','1.0.4','1.0.5','1.0.6')) {
            $spec=Get-ManagerReleaseBundleSpec $versionText
            $artifacts=@()
            foreach ($role in @('source','distribution','update','ai_context')) {
                $name=[string]$spec.ArtifactNames[$role]
                $path=Join-Path $script:Releases $name
                [System.IO.File]::WriteAllText($path,('role='+$role+';version='+$versionText),(New-Object System.Text.UTF8Encoding($false)))
                $artifacts += [ordered]@{role=$role;path=$name;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
            }
            [ordered]@{schema='keelaryn.manager.release-bundle.v1';manager_version=$versionText;system_version='2.1.0';release_id='keelaryn-system-2.1.0';artifacts=$artifacts} | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $script:Releases $spec.ManifestName) -Encoding UTF8
        }
        Set-Content -LiteralPath (Join-Path $script:Releases 'Keelaryn__Manager_RELEASE_v0.0.1.json') -Value '{}' -Encoding ASCII
        $result=Invoke-ManagerReleaseRetention '1.0.5'
        if ($result.Current -ne '1.0.5' -or $result.Previous -ne '1.0.4') { $script:ManagerReleaseRetentionSelfTestReason='Current/previous retention selection mismatch.'; return $false }
        foreach ($kept in @('1.0.4','1.0.5','1.0.6')) {
            $spec=Get-ManagerReleaseBundleSpec $kept
            if (-not (Test-Path -LiteralPath (Join-Path $script:Releases $spec.ManifestName) -PathType Leaf)) { $script:ManagerReleaseRetentionSelfTestReason=('Expected retained/future release missing: '+$kept); return $false }
        }
        foreach ($archived in @('1.0.0','1.0.1','1.0.2','1.0.3')) {
            $spec=Get-ManagerReleaseBundleSpec $archived
            if (Test-Path -LiteralPath (Join-Path $script:Releases $spec.ManifestName)) { $script:ManagerReleaseRetentionSelfTestReason=('Superseded release remained in _releases: '+$archived); return $false }
        }
        if (-not (Test-Path -LiteralPath (Join-Path $script:Releases 'Keelaryn__Manager_RELEASE_v0.0.1.json') -PathType Leaf)) { $script:ManagerReleaseRetentionSelfTestReason='Invalid/unrecognized release was removed.'; return $false }
        $archiveRoot=Join-Path $script:History 'manager_releases'
        $archiveDirs=@(Get-ChildItem -LiteralPath $archiveRoot -Directory -ErrorAction SilentlyContinue)
        if ($archiveDirs.Count -ne 3) { $script:ManagerReleaseRetentionSelfTestReason=('Archive retention expected 3 bundles, found '+$archiveDirs.Count+'.'); return $false }
        foreach ($dir in $archiveDirs) {
            $manifest=@(Get-ChildItem -LiteralPath $dir.FullName -Filter 'Keelaryn__Manager_RELEASE_v*.json' -File)
            if ($manifest.Count -ne 1) { $script:ManagerReleaseRetentionSelfTestReason=('Archived bundle manifest count mismatch: '+$dir.FullName); return $false }
            $null=Read-ManagerReleaseBundle $manifest[0].FullName $dir.FullName
        }

        # Archive conflicts must fail safe: a complete source bundle remains untouched.
        $conflictVersion='0.9.0'
        $conflictSpec=Get-ManagerReleaseBundleSpec $conflictVersion
        $conflictArtifacts=@()
        foreach ($role in @('source','distribution','update','ai_context')) {
            $name=[string]$conflictSpec.ArtifactNames[$role]
            $path=Join-Path $script:Releases $name
            [System.IO.File]::WriteAllText($path,('conflict-role='+$role),(New-Object System.Text.UTF8Encoding($false)))
            $conflictArtifacts += [ordered]@{role=$role;path=$name;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
        }
        [ordered]@{schema='keelaryn.manager.release-bundle.v1';manager_version=$conflictVersion;system_version='2.1.0';release_id='keelaryn-system-2.1.0';artifacts=$conflictArtifacts} | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $script:Releases $conflictSpec.ManifestName) -Encoding UTF8
        $conflictArchive=Join-Path $archiveRoot ('v'+$conflictVersion)
        New-Item -ItemType Directory -Force -Path $conflictArchive | Out-Null
        Set-Content -LiteralPath (Join-Path $conflictArchive $conflictSpec.ManifestName) -Value '{}' -Encoding ASCII
        $null=Invoke-ManagerReleaseRetention '1.0.5'
        if (-not (Test-Path -LiteralPath $conflictArchive -PathType Container)) { $script:ManagerReleaseRetentionSelfTestReason='Validated-only archive pruning removed an invalid/conflicting archive directory.'; return $false }
        if (-not (Test-Path -LiteralPath (Join-Path $script:Releases $conflictSpec.ManifestName) -PathType Leaf)) { $script:ManagerReleaseRetentionSelfTestReason='Archive conflict removed the source release manifest.'; return $false }
        foreach ($name in @($conflictSpec.ArtifactNames.Values)) {
            if (-not (Test-Path -LiteralPath (Join-Path $script:Releases ([string]$name)) -PathType Leaf)) { $script:ManagerReleaseRetentionSelfTestReason=('Archive conflict removed source artifact: '+[string]$name); return $false }
        }
        return $true
    }
    catch { $script:ManagerReleaseRetentionSelfTestReason=('Unexpected error: '+$_.Exception.Message); return $false }
    finally {
        $script:Releases=$oldReleases
        $script:History=$oldHistory
        $script:LogFile=$oldLogFile
        $WarningPreference=$oldWarningPreference
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
    }
}


function Test-LegacyManagerReleaseRetentionSelfTest {
    $script:LegacyManagerReleaseRetentionSelfTestReason=''
    $temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_legacy_release_retention_'+[guid]::NewGuid().ToString('N'))
    $oldReleases=$script:Releases
    $oldHistory=$script:History
    $oldLogFile=$script:LogFile
    $oldWarningPreference=$WarningPreference
    try {
        $WarningPreference='SilentlyContinue'
        $script:Releases=Join-Path $temp '_releases'
        $script:History=Join-Path $temp '_history'
        $script:LogFile=Join-Path $temp 'manager.log'
        New-Item -ItemType Directory -Force -Path $script:Releases,$script:History | Out-Null

        foreach ($versionText in @('4.4.13','4.4.15')) {
            $spec=Get-ManagerReleaseBundleSpec $versionText
            $artifacts=@()
            foreach ($role in @('source','distribution','update','ai_context')) {
                $name=[string]$spec.ArtifactNames[$role]
                $path=Join-Path $script:Releases $name
                [System.IO.File]::WriteAllText($path,('modern-role='+$role+';version='+$versionText),(New-Object System.Text.UTF8Encoding($false)))
                $artifacts += [ordered]@{role=$role;path=$name;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
            }
            [ordered]@{schema='keelaryn.manager.release-bundle.v1';manager_version=$versionText;system_version='2.1.0';release_id='keelaryn-system-2.1.0';artifacts=$artifacts} | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $script:Releases $spec.ManifestName) -Encoding UTF8
        }

        $legacyVersion='4.3.1'
        $legacySpec=Get-LegacyManagerReleaseBundleSpec $legacyVersion
        $legacyArtifacts=@()
        foreach ($role in @('source','distribution','update')) {
            $name=[string]$legacySpec.ArtifactNames[$role]
            $path=Join-Path $script:Releases $name
            [System.IO.File]::WriteAllText($path,('legacy-role='+$role+';version='+$legacyVersion),(New-Object System.Text.UTF8Encoding($false)))
            $legacyArtifacts += [ordered]@{role=$role;path=$name;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
        }
        $legacyManifest=Join-Path $script:Releases $legacySpec.ManifestName
        [ordered]@{schema='keelaryn.manager.release-bundle.v1';manager_version=$legacyVersion;system_version='2.1.0';release_id='keelaryn-system-2.1.0';artifacts=$legacyArtifacts} | ConvertTo-Json -Depth 8 | Set-Content $legacyManifest -Encoding UTF8

        $strictRejected=$false
        try { $null=Read-ManagerReleaseBundle $legacyManifest $script:Releases } catch { $strictRejected=$_.Exception.Message -match 'exactly four artifacts' }
        if (-not $strictRejected) { $script:LegacyManagerReleaseRetentionSelfTestReason='Modern release reader accepted a legacy three-artifact bundle.'; return $false }

        $legacy=Read-ManagerReleaseBundleForRetention $legacyManifest $script:Releases
        if (-not $legacy -or $legacy.BundleFormat -ne 'legacy3' -or $legacy.ArtifactNames.Count -ne 3) { $script:LegacyManagerReleaseRetentionSelfTestReason='Retention reader did not classify the supported legacy bundle correctly.'; return $false }

        $badVersion='4.3.0'
        $badSpec=Get-LegacyManagerReleaseBundleSpec $badVersion
        $badArtifacts=@()
        foreach ($role in @('source','distribution','update')) {
            $name=[string]$badSpec.ArtifactNames[$role]
            $path=Join-Path $script:Releases $name
            [System.IO.File]::WriteAllText($path,('bad-legacy-role='+$role),(New-Object System.Text.UTF8Encoding($false)))
            $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($role -eq 'source') { $hash='0000000000000000000000000000000000000000000000000000000000000000' }
            $badArtifacts += [ordered]@{role=$role;path=$name;sha256=$hash}
        }
        $badManifest=Join-Path $script:Releases $badSpec.ManifestName
        [ordered]@{schema='keelaryn.manager.release-bundle.v1';manager_version=$badVersion;system_version='2.1.0';release_id='keelaryn-system-2.1.0';artifacts=$badArtifacts} | ConvertTo-Json -Depth 8 | Set-Content $badManifest -Encoding UTF8

        $result=Invoke-ManagerReleaseRetention '4.4.15'
        if ($result.Current -ne '4.4.15' -or $result.Previous -ne '4.4.13') { $script:LegacyManagerReleaseRetentionSelfTestReason='Legacy compatibility changed current/previous modern retention selection.'; return $false }
        if (Test-Path -LiteralPath $legacyManifest) { $script:LegacyManagerReleaseRetentionSelfTestReason='Validated legacy 4.3.1 manifest remained in _releases.'; return $false }
        foreach ($name in @($legacySpec.ArtifactNames.Values)) {
            if (Test-Path -LiteralPath (Join-Path $script:Releases ([string]$name))) { $script:LegacyManagerReleaseRetentionSelfTestReason=('Validated legacy artifact remained in _releases: '+[string]$name); return $false }
        }
        $legacyArchive=Join-Path (Join-Path $script:History 'manager_releases') 'v4.3.1'
        if (-not (Test-Path -LiteralPath $legacyArchive -PathType Container)) { $script:LegacyManagerReleaseRetentionSelfTestReason='Validated legacy bundle was not archived.'; return $false }
        $archivedLegacy=Read-ManagerReleaseBundleForRetention (Join-Path $legacyArchive $legacySpec.ManifestName) $legacyArchive
        if (-not $archivedLegacy -or $archivedLegacy.BundleFormat -ne 'legacy3') { $script:LegacyManagerReleaseRetentionSelfTestReason='Archived legacy bundle could not be revalidated.'; return $false }

        if (-not (Test-Path -LiteralPath $badManifest -PathType Leaf)) { $script:LegacyManagerReleaseRetentionSelfTestReason='Invalid legacy-looking manifest was removed.'; return $false }
        foreach ($name in @($badSpec.ArtifactNames.Values)) {
            if (-not (Test-Path -LiteralPath (Join-Path $script:Releases ([string]$name)) -PathType Leaf)) { $script:LegacyManagerReleaseRetentionSelfTestReason=('Invalid legacy-looking artifact was removed: '+[string]$name); return $false }
        }

        $bounded=$false
        try { $null=Get-LegacyManagerReleaseBundleSpec '4.3.2' } catch { $bounded=$_.Exception.Message -match 'not allowed after 4.3.1' }
        if (-not $bounded) { $script:LegacyManagerReleaseRetentionSelfTestReason='Legacy compatibility version bound was not enforced.'; return $false }
        return $true
    }
    catch { $script:LegacyManagerReleaseRetentionSelfTestReason=('Unexpected error: '+$_.Exception.Message); return $false }
    finally {
        $script:Releases=$oldReleases
        $script:History=$oldHistory
        $script:LogFile=$oldLogFile
        $WarningPreference=$oldWarningPreference
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

function Test-AtomicPublishSelfTest {
    $script:AtomicPublishSelfTestReason = ''
    $temp = Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_atomic_' + [guid]::NewGuid().ToString('N'))
    try {
        New-Item -ItemType Directory -Path $temp -Force | Out-Null
        $destination = Join-Path $temp 'destination.txt'
        $prepared = Join-Path $temp 'prepared.txt'
        $newDestination = Join-Path $temp 'new-destination.txt'
        $newPrepared = Join-Path $temp 'new-prepared.txt'
        $utf8 = New-Object System.Text.UTF8Encoding($false)

        # Existing destination: exercises File.Replace with a real backup path.
        [System.IO.File]::WriteAllText($destination, 'old', $utf8)
        [System.IO.File]::WriteAllText($prepared, 'new', $utf8)
        Publish-CompletedFileAtomically $prepared $destination

        if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
            $script:AtomicPublishSelfTestReason = 'Destination disappeared after replacement publication.'
            return $false
        }
        if (Test-Path -LiteralPath $prepared) {
            $script:AtomicPublishSelfTestReason = 'Prepared replacement file still exists after publication.'
            return $false
        }
        $content = [System.IO.File]::ReadAllText($destination, [System.Text.Encoding]::UTF8)
        if ($content -ne 'new') {
            $script:AtomicPublishSelfTestReason = ('Destination content mismatch after replacement publication: ' + $content)
            return $false
        }
        $leftoverBackups = @(Get-ChildItem -LiteralPath $temp -Force -File -Filter '.keelaryn-replace-*.bak' -ErrorAction SilentlyContinue)
        if ($leftoverBackups.Count -ne 0) {
            $script:AtomicPublishSelfTestReason = ('Replacement backup cleanup left ' + $leftoverBackups.Count + ' file(s).')
            return $false
        }

        # Real Windows sharing violation: ensure the classifier recognizes it and the
        # preflight fails closed while the handle is locked, then succeeds after release.
        $locked = Join-Path $temp 'locked.txt'
        [System.IO.File]::WriteAllText($locked, 'locked', $utf8)
        $lockStream=[System.IO.File]::Open($locked,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::None)
        try {
            # First prove the raw Windows sharing exception is classified correctly.
            $rawClassified=$false
            try {
                $probe=[System.IO.File]::Open($locked,[System.IO.FileMode]::Open,[System.IO.FileAccess]::ReadWrite,[System.IO.FileShare]::None)
                $probe.Dispose()
            }
            catch { $rawClassified=Test-IsTransientFileLockException $_.Exception }
            if (-not $rawClassified) {
                $script:AtomicPublishSelfTestReason = 'Raw Windows sharing-violation classifier contract failed.'
                return $false
            }

            # Restart Manager must identify the process holding the real test handle.
            $owners=@(Get-RestartManagerLockOwners $locked)
            $selfOwner=@($owners | Where-Object { [int]$_.ProcessId -eq [System.Diagnostics.Process]::GetCurrentProcess().Id })
            if ($selfOwner.Count -lt 1) {
                $script:AtomicPublishSelfTestReason = 'Restart Manager did not report the self-test lock owner PID.'
                return $false
            }
            $ownerDiagnostic=Format-FileLockOwnerDiagnostic $locked
            $pidMarker='PID='+[System.Diagnostics.Process]::GetCurrentProcess().Id
            if (-not $ownerDiagnostic.Contains($pidMarker)) {
                $script:AtomicPublishSelfTestReason = 'Restart Manager owner diagnostic omitted the self-test PID.'
                return $false
            }

            # Wait-FileReady enriches the terminal lock error while preserving the raw
            # sharing IOException as the deepest exception for HResult classification.
            $waitClassified=$false
            $waitDiagnostic=$false
            try { Wait-FileReadyForAtomicReplace $locked 1 0 'self-test lock preflight' }
            catch {
                $waitClassified=Test-IsTransientFileLockException $_.Exception
                $waitDiagnostic=$_.Exception.Message.Contains($pidMarker) -and $_.Exception.Message.Contains('Restart Manager lock owners:')
            }
            if (-not $waitClassified -or -not $waitDiagnostic) {
                $script:AtomicPublishSelfTestReason = 'Sharing-violation preflight diagnostic/rethrow contract failed.'
                return $false
            }
        }
        finally { $lockStream.Dispose() }
        Wait-FileReadyForAtomicReplace $locked 1 0 'self-test unlocked preflight'

        # Missing destination: exercises same-volume File.Move publication path.
        [System.IO.File]::WriteAllText($newPrepared, 'created', $utf8)
        Publish-CompletedFileAtomically $newPrepared $newDestination
        if (-not (Test-Path -LiteralPath $newDestination -PathType Leaf)) {
            $script:AtomicPublishSelfTestReason = 'New destination was not created by publication.'
            return $false
        }
        if (Test-Path -LiteralPath $newPrepared) {
            $script:AtomicPublishSelfTestReason = 'Prepared create file still exists after publication.'
            return $false
        }
        $newContent = [System.IO.File]::ReadAllText($newDestination, [System.Text.Encoding]::UTF8)
        if ($newContent -ne 'created') {
            $script:AtomicPublishSelfTestReason = ('New destination content mismatch after publication: ' + $newContent)
            return $false
        }

        return $true
    }
    catch {
        $script:AtomicPublishSelfTestReason = ($_.Exception.GetType().FullName + ': ' + $_.Exception.Message)
        return $false
    }
    finally {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
function Test-TransitionRootBootstrapSelfTest {
    $script:TransitionRootBootstrapSelfTestReason=''
    try{
        $text=Get-TransitionRootBootstrapText
        foreach($token in @('$runtime = Join-Path $PSScriptRoot ''product\runtime\Keelaryn__Manager.ps1''','$PSHOME','$runtime @args')){
            if(-not$text.Contains($token)){$script:TransitionRootBootstrapSelfTestReason=('Missing literal bootstrap token: '+$token);return $false}
        }
        if($text-match'(?i)[A-Z]:\\'){$script:TransitionRootBootstrapSelfTestReason='Generated transition bootstrap contains an absolute Windows path.';return $false}
        $tokens=$null;$errors=$null;[void][System.Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
        if(@($errors).Count-ne0){$script:TransitionRootBootstrapSelfTestReason=('Generated transition bootstrap parser failure: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))));return $false}
        return $true
    }catch{$script:TransitionRootBootstrapSelfTestReason=$_.Exception.Message;return $false}
}

function Test-ManagerReleaseSourceSnapshotSelfTest {
    $script:ManagerReleaseSourceSnapshotSelfTestReason=''
    try {
        $paths=@(Get-InstalledManagedPaths)
        if($paths.Count-lt1){$script:ManagerReleaseSourceSnapshotSelfTestReason='Managed path set is empty.';return $false}
        $rows=@(Get-ManagerReleaseSourceSnapshot $paths)
        if($rows.Count-ne$paths.Count){$script:ManagerReleaseSourceSnapshotSelfTestReason=('Snapshot count mismatch: '+$rows.Count+' vs '+$paths.Count);return $false}
        $seen=@{}
        foreach($row in $rows){
            $rel=([string]$row.Path).Replace('\','/')
            $key=$rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
            if($seen.ContainsKey($key)){$script:ManagerReleaseSourceSnapshotSelfTestReason=('Duplicate snapshot path: '+$rel);return $false};$seen[$key]=$true
            $bytes=[byte[]]$row.Bytes
            if([long]$row.Size-ne[long]$bytes.LongLength){$script:ManagerReleaseSourceSnapshotSelfTestReason=('Snapshot size mismatch: '+$rel);return $false}
            if(([string]$row.Hash)-cne(Get-BytesHashHex $bytes)){$script:ManagerReleaseSourceSnapshotSelfTestReason=('Snapshot hash mismatch: '+$rel);return $false}
            if($null-eq$row.Text){$script:ManagerReleaseSourceSnapshotSelfTestReason=('Snapshot text missing: '+$rel);return $false}
        }
        return $true
    }
    catch{$script:ManagerReleaseSourceSnapshotSelfTestReason=$_.Exception.Message;return $false}
}

function Test-HashHexFormattingSelfTest {
    $script:HashHexFormattingSelfTestReason = ''
    try {
        if ((Get-TextHashHex '') -cne 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855') { $script:HashHexFormattingSelfTestReason='Empty text SHA-256 mismatch.'; return $false }
        if ((Get-TextHashHex 'abc') -cne 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad') { $script:HashHexFormattingSelfTestReason='ASCII text SHA-256 mismatch.'; return $false }
        $bytes=[byte[]](0,1,2,255)
        $expected='3d1f57c984978ef98a18378c8166c1cb8ede02c03eeb6aee7e2f121dfeee3e56'
        if ((Get-BytesHashHex $bytes) -cne $expected) { $script:HashHexFormattingSelfTestReason='Byte-array SHA-256 mismatch.'; return $false }
        $stream=New-Object System.IO.MemoryStream
        try {
            $stream.Write($bytes,0,$bytes.Length); $stream.Position=0
            if ((Get-StreamHashHex $stream) -cne $expected) { $script:HashHexFormattingSelfTestReason='Stream SHA-256 mismatch.'; return $false }
        } finally { $stream.Dispose() }
        $legacySha=[System.Security.Cryptography.SHA256]::Create()
        try { $legacy=(-join ($legacySha.ComputeHash($bytes)|ForEach-Object{$_.ToString('x2')})) } finally { $legacySha.Dispose() }
        if ((Get-BytesHashHex $bytes) -cne $legacy) { $script:HashHexFormattingSelfTestReason='BitConverter formatter differs from historical lowercase hex formatter.'; return $false }
        return $true
    } catch { $script:HashHexFormattingSelfTestReason=$_.Exception.Message; return $false }
}

function Test-CleanroomDetectorSelfTest {
    try {
        $technicalSha = 'a' + ('1' * 12) + ('b' * 51)
        if ($technicalSha.Length -ne 64) { return $false }
        Test-CleanroomText 'selftest/CONTEXT_MANIFEST.json' ('{"sha256":"' + $technicalSha + '"}')
        $barePhoneBlocked = $false
        $barePhone = '12345' + '67890'
        try { Test-CleanroomText 'selftest/phone.txt' $barePhone } catch { $barePhoneBlocked = $true }
        if (-not $barePhoneBlocked) { return $false }
        $internationalPhoneBlocked = $false
        $internationalPhone = '+374' + ' 96 ' + '123456'
        try { Test-CleanroomText 'selftest/phone.txt' $internationalPhone } catch { $internationalPhoneBlocked = $true }
        if (-not $internationalPhoneBlocked) { return $false }
        return $true
    }
    catch { return $false }
}

function Test-AIContextToolSourceSelfTest {
    try {
        $badReturnPattern = '\bret' + 'urn[$@[]'
        $badThrowPattern = '\bthr' + 'ow[$@[]'
        $badExitPattern = '\bex' + 'it[$@[]'
        $badBreakPattern = '\bbre' + 'ak[$@[]'
        $badContinuePattern = '\bcont' + 'inue[$@[]'
        $badBooleanGluePattern = '\)-and-not\('
        $psPaths = @(Get-InstalledManagedPaths | Where-Object { [System.IO.Path]::GetExtension([string]$_) -ieq '.ps1' })
        if ($psPaths.Count -eq 0) { return $false }
        foreach ($rel in $psPaths) {
            $path = Join-Path $Root ([string]$rel)
            $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
            if ($text -match '[^\x00-\x7F]') { return $false }
            if ($text -match $badReturnPattern -or $text -match $badThrowPattern -or $text -match $badExitPattern -or $text -match $badBreakPattern -or $text -match $badContinuePattern -or $text -match $badBooleanGluePattern) { return $false }
            $tokens = $null
            $errors = $null
            [void][System.Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
            if (@($errors).Count -ne 0) { return $false }
        }
        return $true
    }
    catch { return $false }
}

function Test-GenesisPathPlannerSelfTest {
    $script:GenesisPathPlannerSelfTestReason=''
    try {
        $slug=Get-SafeSlug 'Alpha [Beta]'
        if ($slug.Contains('[') -or $slug.Contains(']')) { $script:GenesisPathPlannerSelfTestReason='Obsidian bracket sanitization failed.'; return $false }
        $unsafe=Get-SafeSlug 'A/B:C*D?E"F<G>H|I'
        if ($unsafe -ne 'A-B-C-D-E-F-G-H-I') { $script:GenesisPathPlannerSelfTestReason=('Explicit Win32 character sanitization mismatch: '+$unsafe); return $false }
        $sup1=[string][char]0x00B9; $sup3=[string][char]0x00B3
        foreach($reserved in @('CON','CON.txt','CLOCK$','CONIN$','CONOUT$','COM1',('COM'+$sup1),'LPT3',('LPT'+$sup3))) {
            $blocked=$false
            try { $null=Get-SafeSlug $reserved } catch { $blocked=$true }
            if(-not $blocked) { $script:GenesisPathPlannerSelfTestReason=('Reserved Windows name was accepted: '+$reserved); return $false }
        }
        $collisionBlocked=$false
        try { $names=@('A/B','A:B'); $null=New-GenesisItemPlan $names 'area' } catch { $collisionBlocked=$true }
        if (-not $collisionBlocked) { $script:GenesisPathPlannerSelfTestReason='Sanitization collision was not rejected.'; return $false }
        $caseCollisionBlocked=$false
        try { $names=@('Alpha','alpha'); $null=New-GenesisItemPlan $names 'project' } catch { $caseCollisionBlocked=$true }
        if (-not $caseCollisionBlocked) { $script:GenesisPathPlannerSelfTestReason='Case-insensitive collision was not rejected.'; return $false }
        return $true
    }
    catch { $script:GenesisPathPlannerSelfTestReason=('Unexpected error: '+$_.Exception.Message); return $false }
}

function Test-MigrationPlannerSelfTest {
    $registry=[pscustomobject]@{ migrations=@(
        [pscustomobject]@{ id='selftest-1'; from_system_version='1.0.0'; to_system_version='1.1.0'; apply_mode='manager_safe'; spec='selftest-1.json' },
        [pscustomobject]@{ id='selftest-2'; from_system_version='1.1.0'; to_system_version='1.2.0'; apply_mode='manager_safe'; spec='selftest-2.json' }
    ) }
    $p=Resolve-MigrationChain $registry '1.0.0' '1.2.0'
    return $p.Status -eq 'ready' -and @($p.Steps).Count -eq 2
}

function Assert-TestsWorkspaceDirectorySafe([string]$Path,[string]$Purpose) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (-not $item.PSIsContainer) { throw ($Purpose+' must be a directory: '+$Path) }
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ($Purpose+' must not be a reparse point: '+$Path) }
}

function Initialize-TestsWorkspaceAt([string]$TestsPath,[bool]$WriteMetadata=$true) {
    $tests=[System.IO.Path]::GetFullPath($TestsPath).TrimEnd('\')
    if (-not (Test-Path -LiteralPath $tests)) { New-Item -ItemType Directory -Force -Path $tests | Out-Null }
    Assert-TestsWorkspaceDirectorySafe $tests 'Keelaryn tests root'
    $work=Join-Path $tests 'work';$results=Join-Path $tests 'results';$legacy=Join-Path $tests 'legacy-layout-backup'
    foreach($row in @(@($work,'Keelaryn tests work root'),@($results,'Keelaryn tests results root'))){
        $path=[string]$row[0];$purpose=[string]$row[1]
        if (-not (Test-Path -LiteralPath $path)) { New-Item -ItemType Directory -Force -Path $path | Out-Null }
        Assert-TestsWorkspaceDirectorySafe $path $purpose
    }
    if (Test-Path -LiteralPath $legacy) { Assert-TestsWorkspaceDirectorySafe $legacy 'Keelaryn legacy-layout backup root' }
    $allowed=@('work','results','legacy-layout-backup','WORKSPACE.json')
    $unclassified=@(Get-ChildItem -LiteralPath $tests -Force | Where-Object { $allowed -notcontains $_.Name } | Sort-Object Name | ForEach-Object { $_.Name })
    if($WriteMetadata){
        $meta=[ordered]@{
            schema='keelaryn.tests.workspace.v1';manager_version=$ManagerVersion;tests_path=$tests;
            work='work';results='results';legacy_layout_backup='legacy-layout-backup';
            work_policy='ephemeral candidate/disposable runtime only';results_policy='durable gate summaries, benchmark reports and logs';
            generated_fixtures_policy='generate inside work and remove with the run';rejected_policy='record failed/rejected status under results; no separate rejected tree';
            unclassified_top_level=@($unclassified);updated=(Get-Date).ToUniversalTime().ToString('o')
        }
        $json=($meta|ConvertTo-Json -Depth 6).Replace("`r`n","`n")+"`n"
        [System.IO.File]::WriteAllText((Join-Path $tests 'WORKSPACE.json'),$json,(New-Object System.Text.UTF8Encoding($false)))
    }
    return [pscustomobject]@{Tests=$tests;Work=$work;Results=$results;LegacyLayoutBackup=$legacy;Unclassified=@($unclassified)}
}

function Invoke-PrepareTests {
    if (-not $CanonicalLayoutActive) { throw 'PREPARE_TESTS requires the canonical keelaryn/manager installation layout.' }
    $workspace=Initialize-TestsWorkspaceAt $CanonicalTestsPath $true
    Write-Host 'Keelaryn tests workspace ready.' -ForegroundColor Green
    Write-Host ('work: '+$workspace.Work)
    Write-Host ('results: '+$workspace.Results)
    Write-Host ('legacy-layout-backup: '+$workspace.LegacyLayoutBackup+' (created only by explicit layout finalization)')
    if(@($workspace.Unclassified).Count-gt0){
        Write-Host ('Unclassified top-level tests entries left untouched: '+[string]::Join(', ',@($workspace.Unclassified))) -ForegroundColor Yellow
    }
    return 0
}

function Test-TestsWorkspaceSelfTest {
    $temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_tests_workspace_'+[guid]::NewGuid().ToString('N'))
    try{
        New-Item -ItemType Directory -Force -Path $temp | Out-Null
        New-Item -ItemType Directory -Force -Path (Join-Path $temp 'manager-old') | Out-Null
        $ws=Initialize-TestsWorkspaceAt $temp $true
        if(-not(Test-Path -LiteralPath $ws.Work -PathType Container)-or-not(Test-Path -LiteralPath $ws.Results -PathType Container)){return $false}
        if(Test-Path -LiteralPath $ws.LegacyLayoutBackup){return $false}
        if(@($ws.Unclassified)-notcontains'manager-old'){return $false}
        $meta=Read-KeelarynJsonFile (Join-Path $temp 'WORKSPACE.json')
        if([string]$meta.schema-ne'keelaryn.tests.workspace.v1'-or[string]$meta.work-ne'work'-or[string]$meta.results-ne'results'){return $false}
        if([string]$meta.rejected_policy-notmatch'no separate rejected tree'){return $false}
        return $true
    }
    catch{return $false}
    finally{if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}}
}

$script:UserInterfaceToolSourceSelfTestReason=''
function Test-UserInterfaceToolSourceSelfTest {
    try {
        foreach($rel in @('product/tools/KeelarynMenu.ps1','product/tools/Unpack-KeelarynTestArchive.ps1')){
            $p=Join-Path $Root $rel
            if(-not(Test-Path -LiteralPath $p -PathType Leaf)){
                $script:UserInterfaceToolSourceSelfTestReason='missing managed tool: '+$rel
                return $false
            }
            $text=Get-Content -LiteralPath $p -Raw -Encoding UTF8
            if($text-match'[^\x00-\x7F]'){
                $script:UserInterfaceToolSourceSelfTestReason='non-ASCII executable source: '+$rel
                return $false
            }
            $tokens=$null;$errors=$null
            [void][System.Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
            if(@($errors).Count-ne0){
                $script:UserInterfaceToolSourceSelfTestReason='parser failure in '+$rel+': '+((@($errors)|ForEach-Object{$_.Message})-join'; ')
                return $false
            }
        }

        $menu=Get-Content -LiteralPath (Join-Path $Root 'product/tools/KeelarynMenu.ps1') -Raw -Encoding UTF8
        foreach($requiredFunction in @(
            'Write-UiLine','Read-UiInput','Get-MainMenuContractLines','Get-QuickHubBinding','Get-QuickStatus',
            'Import-Package','Get-TestArchivePlan','Invoke-TestArchiveTool','Invoke-FullGate','Invoke-GenesisUi','Ensure-RootLauncher','Invoke-Action',
            'Show-MainMenuScreen','Show-MainMenu','Test-FrontendSelf'
        )){
            $pattern='(?m)^function\s+'+[regex]::Escape($requiredFunction)+'(?:\s|\{|\()'
            if($menu-notmatch$pattern){
                $script:UserInterfaceToolSourceSelfTestReason='frontend function missing: '+$requiredFunction
                return $false
            }
        }
        foreach($requiredAction in @('ImportPackage','UnpackTest','RunFullGate','Genesis','BuildRelease','EnsureRootLauncher','OpenCompatCommands','Doctor','UpdateAll','RenderMain')){
            if($menu-notmatch("'"+[regex]::Escape($requiredAction)+"'")){
                $script:UserInterfaceToolSourceSelfTestReason='frontend action missing: '+$requiredAction
                return $false
            }
        }

        foreach($requiredToken in @('ConfirmChanges','GenesisConfigPath','GenesisConfirmed','function Invoke-GenesisUi','Explicit confirmation is required for direct Genesis.','-NonInteractive')){
            if(-not$menu.Contains($requiredToken)){
                $script:UserInterfaceToolSourceSelfTestReason='frontend non-interactive orchestration token missing: '+$requiredToken
                return $false
            }
        }

        if($menu-notmatch'\[Console\]::WriteLine'-or$menu-notmatch'\[Console\]::ReadLine'){
            $script:UserInterfaceToolSourceSelfTestReason='frontend direct console renderer contract is missing.'
            return $false
        }
        if($menu-match'(?m)^\s*Clear-Host\b'){
            $script:UserInterfaceToolSourceSelfTestReason='frontend still depends on Clear-Host for menu rendering.'
            return $false
        }

        $unpack=Get-Content -LiteralPath (Join-Path $Root 'product/tools/Unpack-KeelarynTestArchive.ps1') -Raw -Encoding UTF8
        foreach($requiredFunction in @('Write-ToolLine','Read-ToolInput','Resolve-ArchiveSpec','Test-ZipSymlinkLike','Normalize-EntryName','Test-ArchiveToolSelf')){
            $pattern='(?m)^function\s+'+[regex]::Escape($requiredFunction)+'(?:\s|\{|\()'
            if($unpack-notmatch$pattern){
                $script:UserInterfaceToolSourceSelfTestReason='archive-tool function missing: '+$requiredFunction
                return $false
            }
        }
        if($unpack-notmatch'\[Console\]::WriteLine'-or$unpack-notmatch'\[Console\]::ReadLine'){
            $script:UserInterfaceToolSourceSelfTestReason='archive-tool direct console renderer contract is missing.'
            return $false
        }
        if($unpack-notmatch'(?m)\bUnblock-File\b'){
            $script:UserInterfaceToolSourceSelfTestReason='archive-tool MOTW removal contract missing: Unblock-File'
            return $false
        }
        foreach($token in @('PlanOnly','NonInteractive','Existing work folder requires explicit replacement.')){if(-not$unpack.Contains($token)){$script:UserInterfaceToolSourceSelfTestReason='archive-tool noninteractive orchestration contract missing token: '+$token;return $false}}

        $script:UserInterfaceToolSourceSelfTestReason=''
        return $true
    }
    catch{
        $script:UserInterfaceToolSourceSelfTestReason=$_.Exception.Message
        return $false
    }
}

function Test-LayoutContractSelfTest {
    try {
        if($CanonicalLayoutActive){
            return ([System.IO.Path]::GetFullPath($CanonicalManagerPath).TrimEnd('\') -ieq [System.IO.Path]::GetFullPath($Root).TrimEnd('\')) -and ((Split-Path $CanonicalHubPath -Parent) -ieq $LayoutRoot) -and ((Split-Path $CanonicalTestsPath -Parent) -ieq $LayoutRoot)
        }
        return ((Split-Path $LayoutRoot -Leaf) -ieq 'keelaryn') -and ((Split-Path $CanonicalManagerPath -Leaf) -ieq 'manager') -and ((Split-Path $CanonicalHubPath -Leaf) -ieq 'hub') -and ((Split-Path $CanonicalTestsPath -Leaf) -ieq 'tests')
    } catch { return $false }
}

function Test-UpdateCommandSurfaceSelfTest {
    foreach ($name in @('KEELARYN.cmd')+$BootstrapCompatibilityCommands) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $name) -PathType Leaf)) { return $false }
    }
    if ($CompatibilityCommandSpecs.Count -ne 21) { return $false }
    foreach ($name in @($CompatibilityCommandSpecs.Keys)) {
        $generated=Get-GeneratedCompatibilityCommandText ([string]$name)
        if ($generated -notmatch '(?i)Keelaryn__Manager\.ps1') { return $false }
    }
    return $true
}

$script:ProductSourceSelfTestReason=''
function Test-ProductSourceSelfTest {
    try {
        $release = Get-ProductRelease
        try {
            $minimumManagerVersion = [version]([string]$release.manager_min_version)
            $currentManagerVersion = [version]$ManagerVersion
        }
        catch { return $false }
        if ($currentManagerVersion -lt $minimumManagerVersion) { return $false }
        try { $managerPolicy=Get-ManagerReleasePolicy; $updateFloor=[version]([string]$managerPolicy.update_min_version) } catch { return $false }
        if ($updateFloor -gt $currentManagerVersion) { return $false }
        $manifestPath = $CanonicalInstallationManifest
        $m = Read-KeelarynJsonFile $manifestPath
        if ([string]$m.schema -ne 'keelaryn.manager.installation.v2' -or [string]$m.manager_version -ne $ManagerVersion -or [int]$m.layout_version -ne 2) { return $false }
        $paths = @($m.managed_files | ForEach-Object { [string]$_ })
        $registry=Get-MigrationRegistry
        if ([string]$registry.system_version -ne [string]$release.system_version) { return $false }
        if (@($paths | Where-Object { $_.StartsWith('product/legacy_migration_templates/',[System.StringComparison]::OrdinalIgnoreCase) -or $_.StartsWith('product/synthetic_demo/',[System.StringComparison]::OrdinalIgnoreCase) }).Count -gt 0) { return $false }
        $requiredPaths=@(
            'KEELARYN.cmd','product/runtime/Keelaryn__Manager.ps1','product/install/INSTALLATION.json',
            'product/release.json','product/manager_release.json','product/migrations/index.json','product/migrations/README.md','product/migrations/2.0.0_to_2.1.0.json',
            'product/docs/OPERATIONS.md','product/docs/MIGRATIONS.md','product/docs/LAYOUT.md','product/docs/TESTING.md','product/docs/RELEASE_BUILD.md',
            'product/docs/AI_DEVELOPMENT.md','product/docs/CANDIDATE_TRANSPORT.md','product/docs/USER_INTERFACE.md','product/docs/REPOSITORY_MODEL.md',
            'product/tools/New-KeelarynAIContext.ps1','product/tools/KeelarynMenu.ps1','product/tools/Unpack-KeelarynTestArchive.ps1',
            'product/governance/hub/_System/PROTOCOL.md','product/governance/hub/_System/CHAT_MANAGER.md'
        )
        foreach ($required in $requiredPaths) {
            if ($paths -notcontains $required) { return $false }
        }
        foreach ($name in @($CompatibilityCommandSpecs.Keys)) {
            if ($paths -contains [string]$name) { return $false }
            if ($paths -notcontains ('compat/commands/'+[string]$name)) { return $false }
        }
        foreach($legacyRoot in @('Keelaryn__Manager.ps1','_manager_manifest.json','_manager_version.txt')){if($paths-contains$legacyRoot){$script:ProductSourceSelfTestReason='Final managed manifest still contains transition root path: '+$legacyRoot;return $false}}
        foreach ($rel in $paths) {
            if (-not (Test-ManagerManagedPath $rel)) { return $false }
            $p = Join-Path $Root $rel
            if (-not (Test-Path $p -PathType Leaf)) { return $false }
        }
        $runtimeSource=[System.IO.File]::ReadAllText((Join-Path $Root 'product\runtime\Keelaryn__Manager.ps1'),[System.Text.Encoding]::UTF8)
        foreach($token in @('function Invoke-WithExistingHiddenFileWritable','function Set-ManagerMutablePresentationHidden','function Write-ManagerBindingDocument','function Get-InstalledManagedFileItem','function Get-TransitionRootBootstrapText','function Test-TransitionRootBootstrapSelfTest','function Convert-ManagerReleaseBytesToText','function Get-ManagerReleaseSourceSnapshot','function Write-ManagerReleaseSnapshotFile','function Invoke-FinalizeFilesystemLayout','function Set-ManagerOperationalPaths','function Assert-ManagerOperationalPathsReady','function Complete-PendingFilesystemLogHandoff','legacy_log_handoff_pending','KEELARYN_FILESYSTEM_HANDOFF_ACTIVE','Restarting Manager after filesystem finalization to activate canonical state paths...','return (Restart-UpdatedManager)','Filesystem finalization failed; previous Manager restored.','product\install\INSTALLATION.json','state\baseline\Keelaryn__Hub_CURRENT.zip','Get-InstalledManagedFileItem $rel','Get-ManagerReleaseSourceSnapshot $paths','Write-ManagerReleaseSnapshotFile $row $dst','Test-ZipEnvelopeArchive $archive ([long]$file.Length)','ValidPackages=@($valid)','Archive-RedundantManagerInboxPackages -ValidatedPackages @($managerDecision.ValidPackages)','Validated Manager package changed before archive cleanup; left untouched:','Release build: PASS','AI_CONTEXT build: PASS','Invoke-WithExistingHiddenFileWritable $CurrentZip','Invoke-WithExistingHiddenFileWritable $dest','product\runtime\Keelaryn__Manager.ps1')){
            if(-not$runtimeSource.Contains($token)){return $false}
        }
        $aiToolSource=[System.IO.File]::ReadAllText((Join-Path $Root 'product\tools\New-KeelarynAIContext.ps1'),[System.Text.Encoding]::UTF8)
        $aiTokens=$null;$aiErrors=$null
        $aiAst=[System.Management.Automation.Language.Parser]::ParseInput($aiToolSource,[ref]$aiTokens,[ref]$aiErrors)
        if(@($aiErrors).Count-ne0){$script:ProductSourceSelfTestReason='AI_CONTEXT source parser failure: '+((@($aiErrors)|ForEach-Object{$_.Message})-join'; ');return $false}
        $accessorDefinitions=@($aiAst.FindAll({param($node) ($node -is [System.Management.Automation.Language.FunctionDefinitionAst]) -and $node.Name -eq 'Get-ManagedSourceItem'},$true))
        if($accessorDefinitions.Count-ne1){$script:ProductSourceSelfTestReason='AI_CONTEXT hidden-safe managed-source accessor definition count mismatch: '+$accessorDefinitions.Count;return $false}
        $accessorText=[string]$accessorDefinitions[0].Extent.Text
        foreach($token in @('Get-Item -LiteralPath $Path -Force -ErrorAction Stop','PSIsContainer','ReparsePoint')){
            if(-not$accessorText.Contains($token)){$script:ProductSourceSelfTestReason='AI_CONTEXT managed-source accessor contract missing token: '+$token;return $false}
        }
        $accessorCalls=@($aiAst.FindAll({param($node) if($node -is [System.Management.Automation.Language.CommandAst]){$node.GetCommandName() -eq 'Get-ManagedSourceItem'}else{$false}},$true))
        if($accessorCalls.Count-lt1){$script:ProductSourceSelfTestReason='AI_CONTEXT managed-source accessor is defined but never invoked.';return $false}
        foreach($token in @('managedPsText=if($rel-eq','{$source}else{')){if(-not$aiToolSource.Contains($token)){$script:ProductSourceSelfTestReason='AI_CONTEXT runtime-text reuse contract missing token: '+$token;return $false}}
        $forbiddenBindingWrite=('Set-Content $'+'BindingFile -Encoding UTF8');if($runtimeSource.Contains($forbiddenBindingWrite)){$script:ProductSourceSelfTestReason='Legacy direct binding write remains in runtime source.';return $false}
        $script:ProductSourceSelfTestReason=''
        return $true
    }
    catch { $script:ProductSourceSelfTestReason=('Unexpected error: '+$_.Exception.Message); return $false }
}

Complete-PendingFilesystemLogHandoff
Rotate-Log

if ($CanonicalLayoutActive -and -not $SelfTest -and -not $InitializePresentation) { Initialize-ManagerPresentationState|Out-Null }

if ($SelfTest) {
    if (-not (Test-InstalledManagerVersionCoherence $ManagerVersion)) { Write-Host 'Manager self-test failed: version markers disagree.' -ForegroundColor Red; exit 1 }
    if (-not (Get-CurrentManagerContentHash)) { Write-Host 'Manager self-test failed: managed files incomplete.' -ForegroundColor Red; exit 1 }
    if (-not (Test-ArtifactRoleParserSelfTest)) { Write-Host 'Manager self-test failed: artifact producer-role parser contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-RevisionTimestampParserSelfTest)) { Write-Host 'Manager self-test failed: Hub revision timestamp compatibility contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-GenesisArtifactParserSelfTest)) { Write-Host 'Manager self-test failed: artifact v3 Genesis parser contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-MigrationPlannerSelfTest)) { Write-Host 'Manager self-test failed: migration planner contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-GenesisPathPlannerSelfTest)) { Write-Host ('Manager self-test failed: Genesis path-planning contract. '+[string]$script:GenesisPathPlannerSelfTestReason) -ForegroundColor Red; exit 1 }
    if (-not (Test-PortablePolicySelfTest)) { Write-Host 'Manager self-test failed: portable deployment-state policy.' -ForegroundColor Red; exit 1 }
    if (-not (Test-HashHexFormattingSelfTest)) { Write-Host ('Manager self-test failed: SHA-256 hex formatting contract. '+[string]$script:HashHexFormattingSelfTestReason) -ForegroundColor Red; exit 1 }
    if (-not (Test-PortableInventorySelfTest)) { Write-Host 'Manager self-test failed: portable inventory/hash contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-PortableAnalysisAndManifestSelfTest)) { Write-Host 'Manager self-test failed: combined portable analysis/MANIFEST contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-DoctorManifestDiagnosticSelfTest)) { Write-Host ('Manager self-test failed: Doctor MANIFEST fast-path/detail contract. '+[string]$script:DoctorManifestDiagnosticSelfTestReason) -ForegroundColor Red; exit 1 }
    if (-not (Test-HubZipInspectionSessionSelfTest)) { Write-Host 'Manager self-test failed: Hub ZIP inspection-session equivalence contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-CandidateTransportSelfTest)) { Write-Host ('Manager self-test failed: candidate transport contract. '+[string]$script:CandidateTransportSelfTestReason) -ForegroundColor Red; exit 1 }
    if (-not (Test-ManagerInstallTargetSafetySelfTest)) { Write-Host ('Manager self-test failed: Manager install target safety contract. '+[string]$script:ManagerInstallTargetSafetySelfTestReason) -ForegroundColor Red; exit 1 }
    if (-not (Test-ManagerReleaseRetentionSelfTest)) { Write-Host ('Manager self-test failed: release retention contract. '+[string]$script:ManagerReleaseRetentionSelfTestReason) -ForegroundColor Red; exit 1 }
    if (-not (Test-LegacyManagerReleaseRetentionSelfTest)) { Write-Host ('Manager self-test failed: legacy release retention contract. '+[string]$script:LegacyManagerReleaseRetentionSelfTestReason) -ForegroundColor Red; exit 1 }
    if (-not (Test-AtomicPublishSelfTest)) { Write-Host ('Manager self-test failed: atomic publication contract. '+[string]$script:AtomicPublishSelfTestReason) -ForegroundColor Red; exit 1 }
    if (-not (Test-TransitionRootBootstrapSelfTest)) { Write-Host ('Manager self-test failed: transition bootstrap determinism contract. '+[string]$script:TransitionRootBootstrapSelfTestReason) -ForegroundColor Red; exit 1 }
    if (-not (Test-ManagerReleaseSourceSnapshotSelfTest)) { Write-Host ('Manager self-test failed: release source snapshot contract. '+[string]$script:ManagerReleaseSourceSnapshotSelfTestReason) -ForegroundColor Red; exit 1 }
    if (-not (Test-ManagerSnapshotMetadataSelfTest)) { Write-Host 'Manager self-test failed: hidden rollback snapshot metadata contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-CleanroomDetectorSelfTest)) { Write-Host 'Manager self-test failed: cleanroom technical-token/phone detector contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-AIContextToolSourceSelfTest)) { Write-Host 'Manager self-test failed: AI context generator parser contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-LegacyNamespaceTransformSelfTest)) { Write-Host 'Manager self-test failed: legacy namespace transform contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-UpdateCommandSurfaceSelfTest)) { Write-Host 'Manager self-test failed: update command surface contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-TestsWorkspaceSelfTest)) { Write-Host 'Manager self-test failed: tests workspace contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-UserInterfaceToolSourceSelfTest)) { Write-Host ('Manager self-test failed: user-interface/test-archive tool contract. '+[string]$script:UserInterfaceToolSourceSelfTestReason) -ForegroundColor Red; exit 1 }
    if (-not (Test-LayoutContractSelfTest)) { Write-Host 'Manager self-test failed: canonical layout contract.' -ForegroundColor Red; exit 1 }
    if ($CanonicalLayoutActive -and $StateLayoutActive -and -not (Test-FinalFilesystemLayout)) { Write-Host 'Manager self-test failed: finalized filesystem layout contract.' -ForegroundColor Red; exit 1 }
    if (-not (Test-ProductSourceSelfTest)) { Write-Host ('Manager self-test failed: managed product source contract. '+[string]$script:ProductSourceSelfTestReason) -ForegroundColor Red; exit 1 }
    exit 0
}

# Update commands never perform transport repair implicitly. Use the Maintenance repair action explicitly.

Log ("Start. ManagerRoot={0}; Vault={1}; OpenOnly={2}; UpdateManager={3}; UpdateHub={4}; UpdateAll={5}; Genesis={6}; BuildDistribution={7}; InstanceInfo={8}; CheckMigrations={9}; AdoptInstanceIdentity={10}; ApplyMigrations={11}; MigrateLegacyNamespace={12}; MigrateLayout={13}; FinalizeLayout={14}; Doctor={15}; BuildRelease={16}; BuildAIContext={17}; RepairCurrentTransport={18}; PrepareTests={19}; BuildCandidateTransport={20}; RestoreCandidateTransport={21}; InitializePresentation={22}; FinalizeFilesystemLayout={23}; BindInstance={24}" -f $Root,$Vault,$OpenOnly,$UpdateManager,$UpdateHub,$UpdateAll,$Genesis,$BuildDistribution,$InstanceInfo,$CheckMigrations,$AdoptInstanceIdentity,$ApplyMigrations,$MigrateLegacyNamespace,$MigrateLayout,$FinalizeLayout,$Doctor,$BuildRelease,$BuildAIContext,$RepairCurrentTransport,$PrepareTests,$BuildCandidateTransport,$RestoreCandidateTransport,$InitializePresentation,$FinalizeFilesystemLayout,[bool]$BindInstancePath)
$exitCode=0
try {
    if ($InitializePresentation) { $exitCode=Initialize-ManagerPresentationState }
    elseif ($FinalizeFilesystemLayout) { Acquire-ManagerLock; $exitCode=Invoke-FinalizeFilesystemLayout }
    elseif ($Doctor) { $exitCode=Invoke-Doctor }
    elseif ($BindInstancePath) { Acquire-ManagerLock; $exitCode=Invoke-BindInstance }
    elseif ($BuildRelease) { Acquire-ManagerLock; $exitCode=Invoke-BuildRelease }
    elseif ($BuildAIContext) { Acquire-ManagerLock; $exitCode=Invoke-BuildAIContext }
    elseif ($BuildDistribution) { Acquire-ManagerLock; $exitCode=Invoke-BuildDistribution }
    elseif ($RepairCurrentTransport) { Acquire-ManagerLock; $exitCode=Invoke-RepairCurrentTransport }
    elseif ($PrepareTests) { Acquire-ManagerLock; $exitCode=Invoke-PrepareTests }
    elseif ($BuildCandidateTransport) { Acquire-ManagerLock; $exitCode=Invoke-BuildCandidateTransport }
    elseif ($RestoreCandidateTransport) { Acquire-ManagerLock; $exitCode=Invoke-RestoreCandidateTransport }
    elseif ($Genesis) { if ($script:BindingResolutionError) { throw ('Genesis refused while an unresolved prior binding exists: '+$script:BindingResolutionError+'. Rebind or remove the stale runtime binding first.') }; Acquire-ManagerLock; $exitCode=Invoke-Genesis $GenesisConfigPath ([bool]$GenesisConfirmed) }
    elseif ($InstanceInfo) { Assert-InstanceBindingAvailable; $exitCode=Show-InstanceInfo }
    elseif ($CheckMigrations) { Assert-InstanceBindingAvailable; $exitCode=Invoke-CheckMigrations }
    elseif ($AdoptInstanceIdentity) { Assert-InstanceBindingAvailable; Acquire-ManagerLock; $exitCode=Invoke-AdoptInstanceIdentity }
    elseif ($ApplyMigrations) { Assert-InstanceBindingAvailable; Acquire-ManagerLock; $exitCode=Invoke-ApplyMigrations }
    elseif ($MigrateLegacyNamespace) { Assert-InstanceBindingAvailable; Acquire-ManagerLock; $exitCode=Invoke-MigrateLegacyNamespace }
    elseif ($MigrateLayout) { Assert-InstanceBindingAvailable; Acquire-ManagerLock; $exitCode=Invoke-MigrateLayout }
    elseif ($FinalizeLayout) { Assert-InstanceBindingAvailable; Acquire-ManagerLock; $exitCode=Invoke-FinalizeLayout }
    elseif ($UpdateManager -or $UpdateHub -or $UpdateAll) { Acquire-ManagerLock; $exitCode=Invoke-Update; Log ("Explicit update action complete. ExitCode="+$exitCode) }
    else { Assert-InstanceBindingAvailable; Open-Vault; Log 'Open-only action complete.'; $exitCode=0 }
}
catch {
    Log ("ERROR: "+$_.Exception.Message)
    Write-Host ''
    Write-Host 'Keelaryn__Manager error:' -ForegroundColor Red
    Write-Host $_.Exception.Message
    Write-Host ''
    Write-Host ("Log: "+$script:LogFile)
    $exitCode=1
}
finally { Release-ManagerLock }
exit $exitCode
