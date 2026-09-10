[CmdletBinding()]
param(
    [ValidateSet(
        'Menu','Status','OpenHub','Doctor','UpdateAll','UpdateManager','UpdateHub',
        'InstanceInfo','ImportPackage','PrepareTests','UnpackTest','RunFullGate','BuildAIContext',
        'BuildRelease','BuildDistribution','BuildCandidateTransport','RestoreCandidateTransport',
        'RepairCurrentTransport','CheckMigrations','ApplyMigrations','BindInstance','InitializeInstanceRegistry','ListInstances','SwitchInstance','RegisterInstance','Genesis',
        'MigrateInstanceIdentity','MigrateLegacyNamespace','MigrateLayout','FinalizeLayout','FinalizeFilesystemLayout',
        'PrepareWorkspaceSession','PrepareChatManagerSession','OpenChatGPTExchange','OpenChatGPTGuide','ImportLegacyExchange',
        'StorageReport','CleanTestsWork','CompactQualificationEvidence',
        'OpenInbox','OpenLogs','OpenReleases','OpenTestsWork','OpenTestsResults','OpenCompatCommands','OpenKeelarynRoot',
        'EnsureRootLauncher','RenderMain'
    )]
    [string]$Action='Menu',
    [string]$Path,
    [string]$InstanceName,
    [switch]$Replace,
    [switch]$ConfirmChanges,
    [switch]$NoAutoRun,
    [switch]$NoRootLauncher,
    [switch]$SelfTest
)

$ErrorActionPreference='Stop'
$script:FrontendScriptPath=[string]$MyInvocation.MyCommand.Path

function Fail([string]$Message) { throw $Message }

function Write-UiLine {
    [CmdletBinding()]
    param(
        [AllowNull()][object]$Object='',
        [System.ConsoleColor]$ForegroundColor=[System.ConsoleColor]::Gray
    )
    $text=if($null-eq$Object){''}else{[string]$Object}
    try{
        $restore=$false
        $old=[System.ConsoleColor]::Gray
        try{
            if(-not[Console]::IsOutputRedirected){
                $old=[Console]::ForegroundColor
                [Console]::ForegroundColor=$ForegroundColor
                $restore=$true
            }
        }catch{}
        [Console]::WriteLine($text)
        if($restore){try{[Console]::ForegroundColor=$old}catch{}}
    }
    catch{
        Microsoft.PowerShell.Utility\Write-Host $text
    }
}

function Write-UiText {
    [CmdletBinding()]
    param(
        [AllowNull()][object]$Object='',
        [System.ConsoleColor]$ForegroundColor=[System.ConsoleColor]::Gray
    )
    $text=if($null-eq$Object){''}else{[string]$Object}
    try{
        $restore=$false
        $old=[System.ConsoleColor]::Gray
        try{
            if(-not[Console]::IsOutputRedirected){
                $old=[Console]::ForegroundColor
                [Console]::ForegroundColor=$ForegroundColor
                $restore=$true
            }
        }catch{}
        [Console]::Write($text)
        if($restore){try{[Console]::ForegroundColor=$old}catch{}}
    }
    catch{
        Microsoft.PowerShell.Utility\Write-Host -NoNewline $text
    }
}

function Write-UiHost {
    [CmdletBinding()]
    param(
        [Parameter(Position=0)][AllowNull()][object]$Object='',
        [System.ConsoleColor]$ForegroundColor=[System.ConsoleColor]::Gray,
        [switch]$NoNewline
    )
    if($NoNewline){Write-UiText $Object -ForegroundColor $ForegroundColor}
    else{Write-UiLine $Object -ForegroundColor $ForegroundColor}
}

function Read-UiInput([string]$Prompt) {
    $prefix=if([string]::IsNullOrEmpty($Prompt)){''}else{$Prompt+': '}
    try{
        [Console]::Write($prefix)
        $line=[Console]::ReadLine()
        if($null-eq$line){return ''}
        return [string]$line
    }
    catch{
        return [string](Microsoft.PowerShell.Utility\Read-Host $Prompt)
    }
}

function Clear-Ui {
    try{
        if(-not[Console]::IsOutputRedirected){[Console]::Clear()}
    }catch{}
}

function Set-UiTitle([string]$Title) {
    try{if(-not[Console]::IsOutputRedirected){[Console]::Title=$Title}}catch{}
}

function Get-MainMenuContractLines {
    return @(
        'Keelaryn',
        'Everyday',
        '  [1] Open Hub',
        '  [2] Doctor',
        '  [3] Install update package...',
        '  [4] Install pending updates',
        '  [5] Installation info',
        '  [6] Maintenance',
        '  [7] Development',
        '  [8] Advanced',
        '  [9] Open Keelaryn folder',
        '  [C] ChatGPT',
        '  [0] Exit'
    )
}


function Get-ManagerRoot {
    $product=Split-Path $PSScriptRoot -Parent
    return [System.IO.Path]::GetFullPath((Split-Path $product -Parent)).TrimEnd('\')
}

$ManagerRoot=Get-ManagerRoot
$LayoutRoot=[System.IO.Path]::GetFullPath((Split-Path $ManagerRoot -Parent)).TrimEnd('\')
$ManagerScript=Join-Path $ManagerRoot 'product\runtime\Keelaryn__Manager.ps1'
$ManagerInstallManifest=Join-Path $ManagerRoot 'product\install\INSTALLATION.json'
$StateRoot=Join-Path $ManagerRoot 'state'
$StateLayoutReceipt=Join-Path $StateRoot 'layout.json'
$CanonicalLayout=((Split-Path $ManagerRoot -Leaf) -ieq 'manager')
$HubRoot=Join-Path $LayoutRoot 'hub'
$TestsRoot=Join-Path $LayoutRoot 'tests'
$CompatCommands=Join-Path $ManagerRoot 'compat\commands'
$ExchangeParent=Join-Path $LayoutRoot 'exchange'
$ExchangeRoot=Join-Path $ExchangeParent 'chatgpt'
$LegacyExchangeRoot=Join-Path $LayoutRoot 'Inputs_outputs'
$ChatGPTDocsRoot=Join-Path $ManagerRoot 'product\docs\chatgpt-projects'
$QualificationCompactionTool=Join-Path $PSScriptRoot 'Compact-KeelarynQualificationEvidence.ps1'

function Refresh-FrontendOperationalPaths {
    $script:StateLayoutActive=Test-Path -LiteralPath $StateLayoutReceipt -PathType Leaf
    $script:Inbox=if($script:StateLayoutActive){Join-Path $StateRoot 'inbox'}else{Join-Path $ManagerRoot '_inbox'}
    $script:Logs=if($script:StateLayoutActive){Join-Path $StateRoot 'logs'}else{Join-Path $ManagerRoot '_logs'}
    $script:Releases=if($script:StateLayoutActive){Join-Path $StateRoot 'releases'}else{Join-Path $ManagerRoot '_releases'}
}
Refresh-FrontendOperationalPaths

function Get-FrontendInstanceContext {
    $legacyCurrent=if($StateLayoutActive){Join-Path $StateRoot 'baseline\Keelaryn__Hub_CURRENT.zip'}else{Join-Path $ManagerRoot 'Keelaryn__Hub_CURRENT.zip'}
    $legacy=[pscustomobject]@{
        RegistryActive=$false;InstanceId=$null;Name=$null;HubPath=$HubRoot
        HubInbox=$Inbox;CurrentZip=$legacyCurrent
        ExchangeRoot=(Join-Path $ExchangeParent 'chatgpt')
    }
    if(-not$StateLayoutActive){return $legacy}
    $registryPath=Join-Path $StateRoot 'instances.json'
    $activePath=Join-Path $StateRoot 'active_instance.json'
    if(-not(Test-Path -LiteralPath $registryPath -PathType Leaf)){return $legacy}
    try{
        $ri=Get-Item -LiteralPath $registryPath -Force -ErrorAction Stop
        $ai=Get-Item -LiteralPath $activePath -Force -ErrorAction Stop
        if(($ri.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0-or($ai.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0-or$ri.Length-gt1MB-or$ai.Length-gt64KB){throw 'unsafe registry metadata'}
        $registry=Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8|ConvertFrom-Json
        $active=Get-Content -LiteralPath $activePath -Raw -Encoding UTF8|ConvertFrom-Json
        if([string]$registry.schema-ne'keelaryn.manager.instances.v1'-or[string]$active.schema-ne'keelaryn.manager.active-instance.v1'){throw 'unsupported registry schema'}
        $id=([string]$active.instance_id).Trim().ToLowerInvariant()
        $rows=@($registry.instances|Where-Object{([string]$_.instance_id).Trim().ToLowerInvariant()-eq$id})
        if($rows.Count-ne1){throw 'active instance does not resolve'}
        $row=$rows[0]
        $state=Join-Path $StateRoot ('instances\'+$id)
        return [pscustomobject]@{
            RegistryActive=$true;InstanceId=$id;Name=[string]$row.name;HubPath=[System.IO.Path]::GetFullPath([string]$row.vault_path)
            HubInbox=Join-Path $state 'inbox';CurrentZip=Join-Path $state 'baseline\Keelaryn__Hub_CURRENT.zip'
            ExchangeRoot=Join-Path $ExchangeParent ('instances\'+$id+'\chatgpt')
        }
    }catch{
        return [pscustomobject]@{
            RegistryActive=$true;InstanceId=$null;Name='<registry error>';HubPath=$HubRoot
            HubInbox=$Inbox;CurrentZip=$legacyCurrent;ExchangeRoot=(Join-Path $ExchangeParent 'chatgpt')
        }
    }
}

function Refresh-FrontendInstanceContext {
    $ctx=Get-FrontendInstanceContext
    $script:ExchangeRoot=[string]$ctx.ExchangeRoot
    return $ctx
}

function Get-RequiredFrontendInstanceContext {
    $ctx=Refresh-FrontendInstanceContext
    if($ctx.RegistryActive-and-not$ctx.InstanceId){
        Fail 'Multi-Hub registry exists but the active instance cannot be resolved. ChatGPT exchange action refused.'
    }
    return $ctx
}
function Get-ChatGPTExchangeDirectoryNames {
    return @('workspace-input','workspace-checkouts','chat-returns','chat-manager-input','chat-manager-results','development')
}

function Ensure-ChatGPTExchangeLayout {
    $null=Get-RequiredFrontendInstanceContext
    Ensure-DirectorySafe $ExchangeParent 'Keelaryn exchange root'
    Ensure-DirectorySafe $ExchangeRoot 'ChatGPT exchange root'
    foreach($name in @(Get-ChatGPTExchangeDirectoryNames)){
        Ensure-DirectorySafe (Join-Path $ExchangeRoot $name) ('ChatGPT exchange '+$name)
    }
}

function Get-CurrentHubTransportPath {
    $path=[string](Get-FrontendInstanceContext).CurrentZip
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){return $null}
    $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('CURRENT transport must not be a reparse point: '+$path)}
    if($item.Length-gt1GB){Fail('CURRENT transport exceeds the 1 GiB safety limit: '+$path)}
    return $path
}

function Copy-CurrentForChatGPT([string]$DestinationDirectory) {
    Ensure-ChatGPTExchangeLayout
    Ensure-DirectorySafe $DestinationDirectory 'ChatGPT CURRENT destination'
    $source=Get-CurrentHubTransportPath
    if([string]::IsNullOrWhiteSpace($source)){
        Write-UiHost 'No Manager CURRENT transport is available. Run Doctor and explicit CURRENT repair first.' -ForegroundColor Yellow
        Set-ActionSemantic 'failed'
        return 1
    }
    $target=Join-Path $DestinationDirectory 'Keelaryn__Hub_CURRENT.zip'
    if(Test-Path -LiteralPath $target){
        $item=Get-Item -LiteralPath $target -Force -ErrorAction Stop
        if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Unsafe ChatGPT CURRENT destination: '+$target)}
    }
    $tmp=$target+'.tmp-'+[guid]::NewGuid().ToString('N')
    try{
        Copy-Item -LiteralPath $source -Destination $tmp -Force -ErrorAction Stop
        if((Get-FileSha256Hex $source)-cne(Get-FileSha256Hex $tmp)){Fail('Prepared CURRENT failed SHA-256 verification.')}
        if(Test-Path -LiteralPath $target -PathType Leaf){Remove-Item -LiteralPath $target -Force -ErrorAction Stop}
        Move-Item -LiteralPath $tmp -Destination $target -ErrorAction Stop
        Write-UiHost ('Prepared CURRENT: '+$target) -ForegroundColor Green
        return 0
    }finally{if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}}
}

function Get-SafeTreeInventory([string]$Directory) {
    if(-not(Test-Path -LiteralPath $Directory -PathType Container)){return @()}
    Ensure-DirectorySafe $Directory 'Inventory root'
    $rows=New-Object System.Collections.ArrayList
    $stack=New-Object 'System.Collections.Generic.Stack[string]'
    $stack.Push([System.IO.Path]::GetFullPath($Directory))
    while($stack.Count-gt0){
        $dir=$stack.Pop()
        foreach($item in @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction Stop)){
            $isReparse=(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0)
            [void]$rows.Add([pscustomobject]@{Path=$item.FullName;IsDirectory=[bool]$item.PSIsContainer;IsReparse=[bool]$isReparse;Length=$(if($item.PSIsContainer){[int64]0}else{[int64]$item.Length})})
            if($item.PSIsContainer -and -not $isReparse){$stack.Push($item.FullName)}
        }
    }
    return @($rows)
}

function Get-StorageStats([string]$Path) {
    if(-not(Test-Path -LiteralPath $Path)){return [pscustomobject]@{Path=$Path;Files=0;Directories=0;Bytes=[int64]0;Reparse=0;Exists=$false}}
    $inv=@(Get-SafeTreeInventory $Path)
    [int64]$bytes=0
    foreach($row in @($inv|Where-Object{-not$_.IsDirectory})){$bytes+=[int64]$row.Length}
    return [pscustomobject]@{Path=$Path;Files=@($inv|Where-Object{-not$_.IsDirectory}).Count;Directories=@($inv|Where-Object{$_.IsDirectory}).Count;Bytes=$bytes;Reparse=@($inv|Where-Object{$_.IsReparse}).Count;Exists=$true}
}

function Format-ByteCount([int64]$Bytes) {
    if($Bytes-ge1GB){return ('{0:N2} GiB' -f ($Bytes/1GB))}
    if($Bytes-ge1MB){return ('{0:N2} MiB' -f ($Bytes/1MB))}
    if($Bytes-ge1KB){return ('{0:N2} KiB' -f ($Bytes/1KB))}
    return ($Bytes.ToString()+' B')
}

function Show-StorageReport {
    Ensure-ChatGPTExchangeLayout
    Write-UiHost 'Keelaryn storage report' -ForegroundColor Cyan
    $targets=@(
        [pscustomobject]@{Name='tests\framework';Path=(Join-Path $TestsRoot 'framework');Policy='current reusable test framework source'},
        [pscustomobject]@{Name='tests\work';Path=(Join-Path $TestsRoot 'work');Policy='DISPOSABLE; explicit cleanup allowed'},
        [pscustomobject]@{Name='tests\results';Path=(Join-Path $TestsRoot 'results');Policy='active/current expanded evidence and concise results'},
        [pscustomobject]@{Name='tests\archives';Path=(Join-Path $TestsRoot 'archives');Policy='frozen verified historical evidence'},
        [pscustomobject]@{Name='manager\state\releases';Path=$Releases;Policy='validated automatic Manager release-bundle retention'},
        [pscustomobject]@{Name='manager\state\history';Path=(Join-Path $StateRoot 'history');Policy='PROTECTED; never generic-clean'},
        [pscustomobject]@{Name='exchange\chatgpt';Path=$ExchangeRoot;Policy='user-facing ChatGPT exchange'},
        [pscustomobject]@{Name='Inputs_outputs';Path=$LegacyExchangeRoot;Policy='legacy exception; copy-only migration source'}
    )
    foreach($target in $targets){
        $s=Get-StorageStats $target.Path
        Write-UiHost ('{0,-28} files={1,6} dirs={2,6} bytes={3,12} reparse={4,4}' -f $target.Name,$s.Files,$s.Directories,(Format-ByteCount $s.Bytes),$s.Reparse)
        Write-UiHost ('  '+$target.Path) -ForegroundColor DarkGray
        Write-UiHost ('  policy: '+$target.Policy) -ForegroundColor DarkGray
    }
    Write-UiHost 'Release ZIP retention is already enforced by validated BuildRelease logic; this report does not create a second cleanup policy.' -ForegroundColor DarkGray
    return 0
}

function Remove-FileWithRetry([string]$FilePath) {
    for($i=0;$i-lt5;$i++){
        try{if(Test-Path -LiteralPath $FilePath -PathType Leaf){Remove-Item -LiteralPath $FilePath -Force -ErrorAction Stop};return $true}
        catch{if($i-ge4){return $false};Start-Sleep -Milliseconds (150*($i+1))}
    }
    return $false
}

function Remove-EmptyDirectoryWithRetry([string]$Directory) {
    for($i=0;$i-lt5;$i++){
        try{if(Test-Path -LiteralPath $Directory -PathType Container){Remove-Item -LiteralPath $Directory -Force -ErrorAction Stop};return $true}
        catch{if($i-ge4){return $false};Start-Sleep -Milliseconds (150*($i+1))}
    }
    return $false
}

function Invoke-CleanTestsWork([switch]$Apply) {
    $root=Join-Path $TestsRoot 'work'
    Ensure-DirectorySafe $root 'tests work'
    $rootFull=[System.IO.Path]::GetFullPath($root).TrimEnd('\')
    $managerFull=[System.IO.Path]::GetFullPath($ManagerRoot).TrimEnd('\')
    if($managerFull.StartsWith(($rootFull+'\'),[System.StringComparison]::OrdinalIgnoreCase)){
        Write-UiHost 'Cleanup refused: this Manager instance is running from inside tests\work.' -ForegroundColor Yellow
        Write-UiHost ('Protected running candidate: '+$ManagerRoot)
        return 2
    }
    $inv=@(Get-SafeTreeInventory $root)
    $reparse=@($inv|Where-Object{$_.IsReparse})
    $files=@($inv|Where-Object{-not$_.IsDirectory})
    $dirs=@($inv|Where-Object{$_.IsDirectory})
    [int64]$bytes=0;foreach($f in $files){$bytes+=[int64]$f.Length}
    Write-UiHost 'Disposable test-work cleanup' -ForegroundColor Cyan
    Write-UiHost ('Target: '+$root)
    Write-UiHost ('Files: '+$files.Count+' | Directories: '+$dirs.Count+' | Bytes: '+(Format-ByteCount $bytes))
    if($reparse.Count-ne0){
        Write-UiHost ('Cleanup rejected: reparse entries='+$reparse.Count) -ForegroundColor Yellow
        foreach($r in $reparse){Write-UiHost ('  '+$r.Path)}
        return 1
    }
    foreach($item in @(Get-ChildItem -LiteralPath $root -Force -ErrorAction Stop)){Write-UiHost ('  '+$item.FullName)}
    if(-not$Apply){Write-UiHost 'DRY RUN ONLY. Nothing was deleted.' -ForegroundColor DarkGray;return 0}
    $failedFiles=New-Object System.Collections.ArrayList
    foreach($f in $files){if(-not(Remove-FileWithRetry $f.Path)){[void]$failedFiles.Add($f.Path)}}
    if($failedFiles.Count-ne0){Write-UiHost 'FAILED: one or more files remain locked/undeletable.' -ForegroundColor Red;foreach($p in $failedFiles){Write-UiHost ('  '+$p)};return 1}
    $pending=New-Object System.Collections.ArrayList
    foreach($d in @($dirs|Sort-Object {$_.Path.Length} -Descending)){
        if(Test-Path -LiteralPath $d.Path -PathType Container){
            $children=@(Get-ChildItem -LiteralPath $d.Path -Force -ErrorAction SilentlyContinue)
            if($children.Count-eq0){if(-not(Remove-EmptyDirectoryWithRetry $d.Path)){[void]$pending.Add($d.Path)}}else{[void]$pending.Add($d.Path)}
        }
    }
    $nonEmpty=@()
    foreach($p in $pending){if((Test-Path -LiteralPath $p -PathType Container)-and@(Get-ChildItem -LiteralPath $p -Force -ErrorAction SilentlyContinue).Count-ne0){$nonEmpty+=,$p}}
    if($nonEmpty.Count-ne0){Write-UiHost 'FAILED: non-empty paths remain after file cleanup.' -ForegroundColor Red;foreach($p in $nonEmpty){Write-UiHost ('  '+$p)};return 1}
    $stillLocked=@($pending|Where-Object{Test-Path -LiteralPath $_ -PathType Container})
    if($stillLocked.Count-ne0){
        Write-UiHost 'PASS with pending empty-directory cleanup.' -ForegroundColor Yellow
        foreach($p in $stillLocked){Write-UiHost ('  DISPOSABLE + SOURCE EMPTY + DIRECTORY LOCKED: '+$p)}
        return 0
    }
    Write-UiHost 'PASS: tests\work is clean.' -ForegroundColor Green
    return 0
}

function Ensure-SafeSubdirectoryPath([string]$Base,[string]$TargetDirectory) {
    Ensure-DirectorySafe $Base 'Safe destination base'
    $baseFull=[System.IO.Path]::GetFullPath($Base).TrimEnd('\')
    $targetFull=[System.IO.Path]::GetFullPath($TargetDirectory).TrimEnd('\')
    if(-not($targetFull.Equals($baseFull,[System.StringComparison]::OrdinalIgnoreCase)) -and -not ($targetFull.StartsWith(($baseFull+'\'),[System.StringComparison]::OrdinalIgnoreCase))){Fail('Destination escaped its allowed root: '+$targetFull)}
    if($targetFull.Equals($baseFull,[System.StringComparison]::OrdinalIgnoreCase)){return $baseFull}
    $relative=$targetFull.Substring($baseFull.Length).TrimStart('\')
    $current=$baseFull
    foreach($part in @($relative-split'\\')){
        if([string]::IsNullOrWhiteSpace($part)){continue}
        $current=Join-Path $current $part
        if(Test-Path -LiteralPath $current){
            $item=Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if(-not$item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Unsafe destination path component: '+$current)}
        }else{New-Item -ItemType Directory -Path $current -ErrorAction Stop|Out-Null}
    }
    return $targetFull
}

function Invoke-LegacyExchangeMigration([switch]$Apply) {
    Ensure-ChatGPTExchangeLayout
    if(-not(Test-Path -LiteralPath $LegacyExchangeRoot -PathType Container)){Write-UiHost 'No legacy Inputs_outputs directory exists. No changes required.';Set-ActionSemantic 'no_changes';return 0}
    Ensure-DirectorySafe $LegacyExchangeRoot 'Legacy Inputs_outputs'
    $inv=@(Get-SafeTreeInventory $LegacyExchangeRoot)
    $reparse=@($inv|Where-Object{$_.IsReparse})
    if($reparse.Count-ne0){Write-UiHost 'Migration rejected: legacy exchange contains reparse points.' -ForegroundColor Yellow;foreach($r in $reparse){Write-UiHost ('  '+$r.Path)};return 1}
    $files=@($inv|Where-Object{-not$_.IsDirectory})
    [int64]$bytes=0;foreach($f in $files){$bytes+=[int64]$f.Length}
    $destRoot=Join-Path $ExchangeRoot 'development\legacy-import'
    Write-UiHost 'Legacy Inputs_outputs migration' -ForegroundColor Cyan
    Write-UiHost ('Source:      '+$LegacyExchangeRoot)
    Write-UiHost ('Destination: '+$destRoot)
    Write-UiHost ('Files: '+$files.Count+' | Bytes: '+(Format-ByteCount $bytes))
    Write-UiHost 'Source deletion: NEVER' -ForegroundColor DarkGray
    if(-not$Apply){Write-UiHost 'DRY RUN ONLY. Nothing was copied.' -ForegroundColor DarkGray;return 0}
    $null=Ensure-SafeSubdirectoryPath (Join-Path $ExchangeRoot 'development') $destRoot
    $sourceBase=[System.IO.Path]::GetFullPath($LegacyExchangeRoot).TrimEnd('\')+'\'
    $copied=0;$same=0
    foreach($f in $files){
        $rel=$f.Path.Substring($sourceBase.Length)
        $target=Join-Path $destRoot $rel
        $targetDir=Split-Path $target -Parent
        $null=Ensure-SafeSubdirectoryPath $destRoot $targetDir
        $sourceHash=Get-FileSha256Hex $f.Path
        if(Test-Path -LiteralPath $target){
            $item=Get-Item -LiteralPath $target -Force -ErrorAction Stop
            if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Unsafe migration destination collision: '+$target)}
            if((Get-FileSha256Hex $target)-ceq$sourceHash){$same++;continue}
            $dir=Split-Path $target -Parent;$stem=[System.IO.Path]::GetFileNameWithoutExtension($target);$ext=[System.IO.Path]::GetExtension($target)
            $target=Join-Path $dir ($stem+'.conflict-'+$sourceHash.Substring(0,8)+$ext)
            if(Test-Path -LiteralPath $target){
                $item=Get-Item -LiteralPath $target -Force -ErrorAction Stop
                if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Unsafe migration conflict destination: '+$target)}
                if((Get-FileSha256Hex $target)-ceq$sourceHash){$same++;continue}
                Fail('Migration conflict destination already exists with different bytes: '+$target)
            }
        }
        Copy-Item -LiteralPath $f.Path -Destination $target -ErrorAction Stop
        if((Get-FileSha256Hex $target)-cne$sourceHash){Fail('Migrated file failed SHA-256 verification: '+$f.Path)}
        $copied++
    }
    Write-UiHost ('PASS: copied='+$copied+' already-identical='+$same+' source-preserved='+$files.Count) -ForegroundColor Green
    return 0
}

function Open-ChatGPTGuide {
    if(-not(Test-Path -LiteralPath $ChatGPTDocsRoot -PathType Container)){Fail('ChatGPT setup docs missing: '+$ChatGPTDocsRoot)}
    return Open-Folder $ChatGPTDocsRoot
}

function Read-ManagerVersion {
    if(-not(Test-Path -LiteralPath $ManagerInstallManifest -PathType Leaf)){return '<missing>'}
    try{return [string]((Get-Content -LiteralPath $ManagerInstallManifest -Raw -Encoding UTF8|ConvertFrom-Json).manager_version)}catch{return '<invalid>'}
}

function Get-FileSha256Hex([string]$FilePath) {
    $stream=[System.IO.File]::OpenRead($FilePath)
    $sha=[System.Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Test-ReparsePoint([string]$ItemPath) {
    if(-not(Test-Path -LiteralPath $ItemPath)){return $false}
    $item=Get-Item -LiteralPath $ItemPath -Force
    return (($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0)
}

function Ensure-DirectorySafe([string]$Directory,[string]$Purpose) {
    if(-not(Test-Path -LiteralPath $Directory)){
        New-Item -ItemType Directory -Force -Path $Directory|Out-Null
    }
    $item=Get-Item -LiteralPath $Directory -Force -ErrorAction Stop
    if(-not$item.PSIsContainer){Fail($Purpose+' is not a directory: '+$Directory)}
    if(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){
        Fail($Purpose+' must not be a reparse point: '+$Directory)
    }
}

function Get-GeneratedRootLauncherText {
    return [string]::Join("`r`n",@(
        '@echo off',
        'call "%~dp0manager\KEELARYN.cmd" %*',
        'exit /b %ERRORLEVEL%',
        ''
    ))
}

function Ensure-RootLauncher([switch]$Quiet) {
    if(-not$CanonicalLayout){return [pscustomobject]@{Status='not_canonical';Path=$null}}
    $target=Join-Path $LayoutRoot 'Keelaryn.cmd'
    $expected=Get-GeneratedRootLauncherText
    if(Test-Path -LiteralPath $target){
        $item=Get-Item -LiteralPath $target -Force
        if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){
            if(-not$Quiet){Write-UiHost('Root launcher collision left untouched: '+$target)-ForegroundColor Yellow}
            return [pscustomobject]@{Status='collision';Path=$target}
        }
        $actual=[System.IO.File]::ReadAllText($target,[System.Text.Encoding]::ASCII)
        if($actual-ceq$expected){
            return [pscustomobject]@{Status='current';Path=$target}
        }
        if(-not$Quiet){
            Write-UiHost('Existing non-Keelaryn root launcher left untouched: '+$target)-ForegroundColor Yellow
        }
        return [pscustomobject]@{Status='custom';Path=$target}
    }
    [System.IO.File]::WriteAllText($target,$expected,[System.Text.Encoding]::ASCII)
    if(-not$Quiet){Write-UiHost('Root launcher created: '+$target)-ForegroundColor Green}
    return [pscustomobject]@{Status='created';Path=$target}
}


function Test-QuickHubCandidate([string]$CandidatePath) {
    if([string]::IsNullOrWhiteSpace($CandidatePath)){return $false}
    try{$full=[System.IO.Path]::GetFullPath($CandidatePath)}catch{return $false}
    if(-not(Test-Path -LiteralPath $full -PathType Container)){return $false}
    foreach($rel in @('_System\STATE.md','_System\INDEX.json','_System\ROUTER.json','_System\VALIDATION.json')){
        if(-not(Test-Path -LiteralPath (Join-Path $full $rel) -PathType Leaf)){return $false}
    }
    return $true
}

function Get-QuickHubBinding {
    $multi=Get-FrontendInstanceContext
    if($multi.RegistryActive-and$multi.InstanceId-and(Test-QuickHubCandidate ([string]$multi.HubPath))){
        return [pscustomobject]@{Path=[string]$multi.HubPath;Source='instance_registry';InstanceId=[string]$multi.InstanceId;Name=[string]$multi.Name}
    }
    $envPath=([string]$env:KEELARYN_HUB_PATH).Trim()
    if($envPath -and (Test-QuickHubCandidate $envPath)){
        return [pscustomobject]@{Path=[System.IO.Path]::GetFullPath($envPath);Source='environment'}
    }
    $legacyPath=([string][Environment]::GetEnvironmentVariable('CORE_HUB_VAULT_PATH')).Trim()
    if($legacyPath -and (Test-QuickHubCandidate $legacyPath)){
        return [pscustomobject]@{Path=[System.IO.Path]::GetFullPath($legacyPath);Source='legacy_environment'}
    }

    $bindingPath=if($StateLayoutActive){Join-Path $StateRoot 'binding.json'}else{Join-Path $ManagerRoot '_instance_binding.json'}
    if(Test-Path -LiteralPath $bindingPath -PathType Leaf){
        try{
            $item=Get-Item -LiteralPath $bindingPath -Force -ErrorAction Stop
            if(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-eq0 -and $item.Length-le4MB){
                $binding=Get-Content -LiteralPath $bindingPath -Raw -Encoding UTF8|ConvertFrom-Json
                if([string]$binding.schema-eq'keelaryn.manager.instance-binding.v2'){
                    $stored=([string]$binding.vault_path).Trim()
                    if($stored -and (Test-QuickHubCandidate $stored)){
                        return [pscustomobject]@{Path=[System.IO.Path]::GetFullPath($stored);Source='binding'}
                    }
                }
            }
        }catch{}
    }

    return [pscustomobject]@{Path=$HubRoot;Source='canonical'}
}

function Resolve-StartupDisposition {
    param(
        [bool]$CanonicalLayoutActive,
        [bool]$HasValidHub,
        [bool]$CanonicalHubPathExists,
        [bool]$HasCurrentBaseline,
        [bool]$HasBindingState,
        [bool]$HasHubEnvironmentOverride
    )
    if(-not$CanonicalLayoutActive){return 'not_applicable'}
    if($HasValidHub){return 'ready'}
    if(-not$CanonicalHubPathExists -and -not$HasCurrentBaseline -and -not$HasBindingState -and -not$HasHubEnvironmentOverride){return 'new_install'}
    return 'attention'
}

function Get-StartupDisposition {
    $binding=Get-QuickHubBinding
    $hasValidHub=Test-QuickHubCandidate ([string]$binding.Path)
    $current=if($StateLayoutActive){Join-Path $StateRoot 'baseline\Keelaryn__Hub_CURRENT.zip'}else{Join-Path $ManagerRoot 'Keelaryn__Hub_CURRENT.zip'}
    $bindingPath=if($StateLayoutActive){Join-Path $StateRoot 'binding.json'}else{Join-Path $ManagerRoot '_instance_binding.json'}
    $hasEnvironment=(-not[string]::IsNullOrWhiteSpace([string]$env:KEELARYN_HUB_PATH))-or(-not[string]::IsNullOrWhiteSpace([string][Environment]::GetEnvironmentVariable('CORE_HUB_VAULT_PATH')))
    return Resolve-StartupDisposition ([bool]$CanonicalLayout) ([bool]$hasValidHub) ([bool](Test-Path -LiteralPath $HubRoot)) ([bool](Test-Path -LiteralPath $current -PathType Leaf)) ([bool](Test-Path -LiteralPath $bindingPath -PathType Leaf)) ([bool]$hasEnvironment)
}

function Get-QuickStatus {
    $version=Read-ManagerVersion
    $hubBinding=Get-QuickHubBinding
    $effectiveHubRoot=[string]$hubBinding.Path
    $hubVersion='<unavailable>'
    $hubRevision='<unavailable>'
    $hubRevisionTime='<unavailable>'
    $artifactId='<unavailable>'
    $artifactPath=Join-Path $effectiveHubRoot '_System\ARTIFACT.json'
    if(Test-Path -LiteralPath $artifactPath -PathType Leaf){
        try{
            $a=Get-Content -LiteralPath $artifactPath -Raw -Encoding UTF8|ConvertFrom-Json
            if($a.system_version){$hubVersion=[string]$a.system_version}
            if($a.data_revision){$hubRevision=[string]$a.data_revision}
            $revisionRaw=if($a.PSObject.Properties['revision_time_utc'] -and $a.revision_time_utc){[string]$a.revision_time_utc}else{[string]$a.created}
            if($revisionRaw){
                try{$hubRevisionTime=([DateTimeOffset]::Parse($revisionRaw)).ToLocalTime().ToString('yyyy-MM-dd HH:mm')}catch{$hubRevisionTime=$revisionRaw}
            }
            if($a.artifact_id){$artifactId=[string]$a.artifact_id}
        }catch{}
    }

    $doctor='never'
    $doctorGenerated=$null
    $doctorPath=Join-Path $Logs 'DOCTOR_REPORT.json'
    if(Test-Path -LiteralPath $doctorPath -PathType Leaf){
        try{
            $r=Get-Content -LiteralPath $doctorPath -Raw -Encoding UTF8|ConvertFrom-Json
            $doctorGenerated=[string]$r.generated
            $sameManager=([string]$r.manager_version-eq$version)
            $sameVault=$false
            if($r.vault){
                try{
                    $sameVault=([System.IO.Path]::GetFullPath([string]$r.vault).TrimEnd('\') -ieq [System.IO.Path]::GetFullPath($effectiveHubRoot).TrimEnd('\'))
                }catch{}
            }
            if($sameManager-and$sameVault){
                if([int]$r.errors-eq0){$doctor='PASS'}else{$doctor='FAIL'}
                if([int]$r.warnings-gt0){$doctor+=' + warnings'}
            }else{
                $doctor='stale'
            }
        }catch{$doctor='unreadable'}
    }

    $managerUpdates=0;$hubApproved=0;$hubCandidate=0;$instanceContext=Get-FrontendInstanceContext;$activeHubInbox=[string]$instanceContext.HubInbox
    if(Test-Path -LiteralPath $Inbox -PathType Container){
        $managerUpdates=@(Get-ChildItem -LiteralPath $Inbox -File -Filter '*.zip' -ErrorAction SilentlyContinue|
            Where-Object{$_.Name-match'(?i)^Keelaryn__Manager_Update_'}).Count
        $hubApproved=if(Test-Path -LiteralPath $activeHubInbox -PathType Container){@(Get-ChildItem -LiteralPath $activeHubInbox -File -Filter '*.zip' -ErrorAction SilentlyContinue|
            Where-Object{$_.Name-match'(?i)^(Keelaryn__Hub|Core__Hub)_APPROVED_'}).Count}else{0}
        $hubCandidate=if(Test-Path -LiteralPath $activeHubInbox -PathType Container){@(Get-ChildItem -LiteralPath $activeHubInbox -File -Filter '*.zip' -ErrorAction SilentlyContinue|
            Where-Object{$_.Name-match'(?i)^(Keelaryn__Hub|Core__Hub)_CANDIDATE_'}).Count}else{0}
    }

    $rootExtras=@()
    if(Test-Path -LiteralPath $LayoutRoot -PathType Container){
        $allowed=@('manager','hub','hubs','tests','exchange','Inputs_outputs','Keelaryn.cmd')
        $rootExtras=@(Get-ChildItem -LiteralPath $LayoutRoot -Force -ErrorAction SilentlyContinue|
            Where-Object{$allowed-notcontains$_.Name}|Sort-Object Name|ForEach-Object{$_.Name})
    }

    $testsExtras=@()
    if(Test-Path -LiteralPath $TestsRoot -PathType Container){
        $allowedTests=@('framework','work','results','archives','legacy-layout-backup','WORKSPACE.json')
        $testsExtras=@(Get-ChildItem -LiteralPath $TestsRoot -Force -ErrorAction SilentlyContinue|
            Where-Object{$allowedTests-notcontains$_.Name}|Sort-Object Name|ForEach-Object{$_.Name})
    }

    return [pscustomobject]@{
        ManagerVersion=$version
        HubVersion=$hubVersion
        HubRevision=$hubRevision
        HubRevisionTime=$hubRevisionTime
        ArtifactId=$artifactId
        HubPath=$effectiveHubRoot
        HubBindingSource=[string]$hubBinding.Source
        InstanceId=[string]$instanceContext.InstanceId
        InstanceName=[string]$instanceContext.Name
        LastDoctor=$doctor
        LastDoctorGenerated=$doctorGenerated
        ManagerUpdates=$managerUpdates
        HubApproved=$hubApproved
        HubCandidate=$hubCandidate
        RootExtras=@($rootExtras)
        TestsExtras=@($testsExtras)
    }
}

function Show-QuickStatus([switch]$DetailedWorkspace) {
    $s=Get-QuickStatus
    Write-UiHost ''
    Write-UiHost ('Keelaryn Manager '+$s.ManagerVersion) -ForegroundColor Cyan
    Write-UiHost ('Hub '+$s.HubVersion+' | '+$s.HubRevisionTime)
    if($s.InstanceId){Write-UiHost ('Instance: '+$s.InstanceName+' | '+$s.InstanceId.Substring(0,8)) -ForegroundColor DarkGray}
    Write-UiHost ('Health: '+$s.LastDoctor)
    $updates=if(($s.ManagerUpdates+$s.HubApproved)-eq0){'none'}else{('Manager='+$s.ManagerUpdates+' | Hub='+$s.HubApproved)}
    Write-UiHost ('Updates: '+$updates)
    if($DetailedWorkspace-and(@($s.RootExtras).Count-gt0-or@($s.TestsExtras).Count-gt0)){
        Write-UiHost ('Workspace diagnostics: root extras='+@($s.RootExtras).Count+' | tests extras='+@($s.TestsExtras).Count) -ForegroundColor Yellow
        foreach($name in @($s.RootExtras|Select-Object -First 8)){Write-UiHost ('  root: '+$name) -ForegroundColor DarkYellow}
        if(@($s.RootExtras).Count-gt8){Write-UiHost ('  root: ... +'+(@($s.RootExtras).Count-8)+' more') -ForegroundColor DarkYellow}
        foreach($name in @($s.TestsExtras|Select-Object -First 8)){Write-UiHost ('  tests: '+$name) -ForegroundColor DarkYellow}
        if(@($s.TestsExtras).Count-gt8){Write-UiHost ('  tests: ... +'+(@($s.TestsExtras).Count-8)+' more') -ForegroundColor DarkYellow}
        Write-UiHost '  Unknown files are diagnostic only and are never moved automatically.' -ForegroundColor DarkGray
    }
    return $s
}

function Invoke-Manager([string[]]$ManagerArgs) {
    if(-not(Test-Path -LiteralPath $ManagerScript -PathType Leaf)){Fail('Manager runtime missing: '+$ManagerScript)}
    & (Join-Path $PSHOME 'powershell.exe') -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $ManagerScript @ManagerArgs 2>&1 | ForEach-Object { Write-UiHost ([string]$_) }
    $rc=[int]$LASTEXITCODE
    Refresh-FrontendOperationalPaths
    return $rc
}

function Open-Folder([string]$FolderPath) {
    if(-not(Test-Path -LiteralPath $FolderPath -PathType Container)){
        Write-UiHost('Folder does not exist: '+$FolderPath)-ForegroundColor Yellow
        return 2
    }
    Start-Process explorer.exe -ArgumentList ('"'+$FolderPath+'"')|Out-Null
    return 0
}

function Resolve-PickerSelection([bool]$GuiAvailable,[bool]$Accepted,[string]$SelectedPath,[string]$ManualPath) {
    if($GuiAvailable){
        if($Accepted){return [string]$SelectedPath}
        return $null
    }
    if([string]::IsNullOrWhiteSpace($ManualPath)){return $null}
    return ([string]$ManualPath).Trim().Trim('"')
}

function Select-File([string]$Title,[string]$Filter,[string]$InitialDirectory) {
    try{
        Add-Type -AssemblyName System.Windows.Forms
        $dialog=New-Object System.Windows.Forms.OpenFileDialog
        try{
            $dialog.Title=$Title
            $dialog.Filter=$Filter
            $dialog.Multiselect=$false
            if($InitialDirectory-and(Test-Path -LiteralPath $InitialDirectory -PathType Container)){$dialog.InitialDirectory=$InitialDirectory}
            $result=$dialog.ShowDialog()
            return Resolve-PickerSelection $true ($result-eq[System.Windows.Forms.DialogResult]::OK) $dialog.FileName $null
        }finally{$dialog.Dispose()}
    }catch{}
    $manual=Read-UiInput ($Title+' - GUI unavailable; enter full path or leave blank to cancel')
    return Resolve-PickerSelection $false $false $null $manual
}

function Select-Folder([string]$Title,[string]$InitialDirectory) {
    try{
        Add-Type -AssemblyName System.Windows.Forms
        $dialog=New-Object System.Windows.Forms.FolderBrowserDialog
        try{
            $dialog.Description=$Title
            if($InitialDirectory-and(Test-Path -LiteralPath $InitialDirectory -PathType Container)){$dialog.SelectedPath=$InitialDirectory}
            $result=$dialog.ShowDialog()
            return Resolve-PickerSelection $true ($result-eq[System.Windows.Forms.DialogResult]::OK) $dialog.SelectedPath $null
        }finally{$dialog.Dispose()}
    }catch{}
    $manual=Read-UiInput ($Title+' - GUI unavailable; enter full path or leave blank to cancel')
    return Resolve-PickerSelection $false $false $null $manual
}

function Confirm([string]$Prompt,[bool]$DefaultNo=$true) {
    $suffix=if($DefaultNo){' [y/N]'}else{' [Y/n]'}
    $answer=Read-UiInput ($Prompt+$suffix)
    if([string]::IsNullOrWhiteSpace($answer)){return -not$DefaultNo}
    return ($answer-match'^(?i)y(es)?$')
}

function Resolve-ExplicitConfirmation([bool]$Explicit,[bool]$Interactive,[bool]$Confirmed) {
    if($Explicit){return $true}
    if(-not$Interactive){return $false}
    return $Confirmed
}

function Request-CommitConfirmation([string]$Prompt,[bool]$Explicit=$false) {
    if($Explicit){return $true}
    if($Action-ne'Menu'){return $false}
    return Resolve-ExplicitConfirmation $false $true (Confirm $Prompt)
}

$script:LastActionSemantic='completed'
function Set-ActionSemantic([ValidateSet('completed','no_changes','cancelled','failed')][string]$Status){$script:LastActionSemantic=$Status}

function Import-Package([string]$PackagePath) {
    if(-not$PackagePath){
        $PackagePath=Select-File 'Select Keelaryn update package' 'Keelaryn ZIP packages (*.zip)|*.zip' (Join-Path $env:USERPROFILE 'Downloads')
        if(-not$PackagePath){Set-ActionSemantic 'cancelled';return 2}
    }
    $PackagePath=[System.IO.Path]::GetFullPath($PackagePath)
    if(-not(Test-Path -LiteralPath $PackagePath -PathType Leaf)){Fail('Selected package does not exist: '+$PackagePath)}
    if(Test-ReparsePoint $PackagePath){Fail('Selected package must not be a reparse point.')}
    $file=Get-Item -LiteralPath $PackagePath -Force
    if($file.Length-gt1GB){Fail('Selected package exceeds the 1 GiB import safety limit.')}
    $name=$file.Name

    $mode=$null
    if($name-match'(?i)^Keelaryn__Manager_Update_.*\.zip$'){$mode='manager'}
    elseif($name-match'(?i)^(Keelaryn__Hub|Core__Hub)_APPROVED_.*\.zip$'){$mode='hub'}
    else{
        Fail('Unsupported install package name. Select a Manager UPDATE or Hub APPROVED ZIP. CANDIDATE ZIPs are never installed.')
    }

    $destinationInbox=$Inbox
    if($mode-eq'hub'){$ctx=Get-FrontendInstanceContext;$destinationInbox=[string]$ctx.HubInbox;if($ctx.RegistryActive-and-not$ctx.InstanceId){Fail('Multi-Hub registry is unresolved; Hub package import refused.')}}
    Ensure-DirectorySafe $destinationInbox $(if($mode-eq'hub'){'Active Hub inbox'}else{'Manager inbox'})
    $dest=Join-Path $destinationInbox $name
    if(Test-Path -LiteralPath $dest){
        $destItem=Get-Item -LiteralPath $dest -Force
        if($destItem.PSIsContainer-or($destItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){
            Fail('Inbox destination collides with an unsafe object: '+$dest)
        }
        if((Get-FileSha256Hex $dest)-eq(Get-FileSha256Hex $PackagePath)){
            Write-UiHost 'Identical package is already present in the Manager inbox.' -ForegroundColor DarkGray
        }else{
            if((-not $Replace) -and (-not (Request-CommitConfirmation 'A different file with this name already exists in the inbox. Replace it?' $false))){
                Write-UiHost 'Cancelled. Existing inbox package left untouched.' -ForegroundColor Yellow
                Set-ActionSemantic 'cancelled';return 3
            }
            Copy-Item -LiteralPath $PackagePath -Destination $dest -Force
        }
    }else{
        Copy-Item -LiteralPath $PackagePath -Destination $dest
    }
    if((Get-FileSha256Hex $dest)-ne(Get-FileSha256Hex $PackagePath)){Fail('Inbox copy hash mismatch.')}

    Write-UiHost ('Imported: '+$dest) -ForegroundColor Green
    if($mode-eq'manager'){
        return Invoke-Manager @('-UpdateManager')
    }
    return Invoke-Manager @('-UpdateHub')
}

function Get-TestArchivePlan([string]$ArchivePath) {
    $tool=Join-Path $PSScriptRoot 'Unpack-KeelarynTestArchive.ps1'
    $args=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$tool,'-ZipPath',$ArchivePath,'-TestsRoot',$TestsRoot,'-PlanOnly','-NonInteractive','-NoAutoRun')
    $lines=@(& (Join-Path $PSHOME 'powershell.exe') @args 2>&1)
    $rc=[int]$LASTEXITCODE
    if($rc-ne0){foreach($line in $lines){Write-UiHost ([string]$line)};return $null}
    foreach($line in $lines){
        $text=[string]$line
        if($text.StartsWith('KEELARYN_PLAN_JSON:',[System.StringComparison]::Ordinal)){
            try{return ($text.Substring(19)|ConvertFrom-Json)}catch{Fail('Test archive plan output is invalid.')}
        }
    }
    Fail('Test archive tool did not return a plan.')
}

function Invoke-TestArchiveTool([string]$ArchivePath,[bool]$ForceNoAutoRun=$false,[bool]$RequireManager=$false) {
    $tool=Join-Path $PSScriptRoot 'Unpack-KeelarynTestArchive.ps1'
    if(-not(Test-Path -LiteralPath $tool -PathType Leaf)){Fail('Test archive tool missing: '+$tool)}
    if(-not$ArchivePath){
        $ArchivePath=Select-File 'Select Keelaryn test/gate archive' 'Keelaryn test archives (*.zip)|*.zip' (Join-Path $env:USERPROFILE 'Downloads')
        if(-not$ArchivePath){Set-ActionSemantic 'cancelled';return 2}
    }
    $ArchivePath=[System.IO.Path]::GetFullPath($ArchivePath)
    $plan=Get-TestArchivePlan $ArchivePath
    if(-not$plan){Set-ActionSemantic 'failed';return 1}
    if($RequireManager-and[string]$plan.kind-ne'manager'){Fail('Full Gate requires manager-<version>.zip.')}
    $replaceNow=[bool]$Replace
    if((Test-Path -LiteralPath ([string]$plan.destination))-and-not$replaceNow){
        if(-not(Request-CommitConfirmation ('Disposable workspace already exists: '+[string]$plan.destination+'. Replace it?') $false)){
            Write-UiHost 'Cancelled. Existing work folder left untouched.' -ForegroundColor Yellow
            Set-ActionSemantic 'cancelled'
            return 3
        }
        $replaceNow=$true
    }
    $args=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$tool,'-ZipPath',$ArchivePath,'-TestsRoot',$TestsRoot,'-NonInteractive')
    if($replaceNow){$args+='-Replace'}
    if($NoAutoRun-or$ForceNoAutoRun){$args+='-NoAutoRun'}
    & (Join-Path $PSHOME 'powershell.exe') @args 2>&1 | ForEach-Object { Write-UiHost ([string]$_) }
    $rc=[int]$LASTEXITCODE
    if($rc-eq0){$script:LastTestArchivePlan=$plan}
    elseif($rc-eq3){Set-ActionSemantic 'cancelled'}
    else{Set-ActionSemantic 'failed'}
    return $rc
}

function Invoke-FullGate([string]$ArchivePath) {
    $rc=Invoke-TestArchiveTool $ArchivePath $true $true
    if($rc-ne0){return $rc}
    $destination=[string]$script:LastTestArchivePlan.destination
    $runner=Join-Path $destination 'gate\Run-KeelarynManagerFullGate.ps1'
    if(-not(Test-Path -LiteralPath $runner -PathType Leaf)){Fail('Full Gate runner is missing: '+$runner)}
    Write-UiHost ''
    Write-UiHost ('Full Gate workspace: '+$destination) -ForegroundColor Cyan
    Write-UiHost 'Production access: READ-ONLY. Destructive development targets: tests only.' -ForegroundColor DarkGray
    $args=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$runner,'-CandidateRoot',$destination,'-ProductionRoot',$LayoutRoot)
    & (Join-Path $PSHOME 'powershell.exe') @args 2>&1 | ForEach-Object { Write-UiHost ([string]$_) }
    $gateRc=[int]$LASTEXITCODE
    if($gateRc-ne0){Set-ActionSemantic 'failed'}
    return $gateRc
}

function Invoke-QualificationCompactor([string]$TargetPath,[bool]$DoApply=$false) {
    if(-not(Test-Path -LiteralPath $QualificationCompactionTool -PathType Leaf)){Fail('Qualification compaction tool missing: '+$QualificationCompactionTool)}
    $target=$TargetPath
    if(-not$target){
        $target=Select-Folder 'Select completed qualification results directory' (Join-Path $TestsRoot 'results')
        if(-not$target){Set-ActionSemantic 'cancelled';return 2}
    }
    $target=[System.IO.Path]::GetFullPath($target).TrimEnd('\')
    $args=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$QualificationCompactionTool,'-ResultsPath',$target,'-TestsRoot',$TestsRoot)
    if($DoApply){$args+='-Apply'}
    & (Join-Path $PSHOME 'powershell.exe') @args 2>&1 | ForEach-Object { Write-UiHost ([string]$_) }
    $rc=[int]$LASTEXITCODE
    if($rc-ne0){Set-ActionSemantic 'failed'}
    return $rc
}

function Invoke-ApplyMigrationsUi {
    $rc=Invoke-Manager @('-CheckMigrations')
    if($rc-ne0){Set-ActionSemantic 'failed';return $rc}
    $planPath=Join-Path $Logs 'MIGRATION_PLAN.json'
    if(-not(Test-Path -LiteralPath $planPath -PathType Leaf)){Fail('Migration plan was not produced: '+$planPath)}
    $plan=Get-Content -LiteralPath $planPath -Raw -Encoding UTF8|ConvertFrom-Json
    $status=[string]$plan.status
    if($status-eq'up_to_date'){
        Write-UiHost 'No migrations required.' -ForegroundColor Green
        Set-ActionSemantic 'no_changes'
        return 0
    }
    if($status-ne'ready'){
        Write-UiHost ('Migration cannot be applied automatically: '+[string]$plan.reason) -ForegroundColor Yellow
        Set-ActionSemantic 'failed'
        return 2
    }
    $steps=@($plan.chain)
    Write-UiHost ('Pending migrations: '+$steps.Count)
    foreach($step in $steps){Write-UiHost ('  '+[string]$step.id+': '+[string]$step.from_system_version+' -> '+[string]$step.to_system_version)}
    if(-not(Request-CommitConfirmation 'Apply these migrations?' ([bool]$ConfirmChanges))){
        if($Action-ne'Menu' -and -not$ConfirmChanges){Write-UiHost 'Explicit confirmation is required for direct migration apply.' -ForegroundColor DarkGray}
        Write-UiHost 'Cancelled. No changes made.' -ForegroundColor Yellow
        Set-ActionSemantic 'cancelled'
        return 2
    }
    return Invoke-Manager @('-ApplyMigrations')
}

function Invoke-BindInstanceUi([string]$TargetPath) {
    $target=$TargetPath
    if(-not$target){$target=Select-Folder 'Select existing Keelaryn Hub directory' $LayoutRoot}
    if(-not$target){Set-ActionSemantic 'cancelled';return 2}
    $target=[System.IO.Path]::GetFullPath($target).TrimEnd('\')
    $current=Get-QuickHubBinding
    Write-UiHost ('Current Hub: '+[string]$current.Path)
    Write-UiHost ('New Hub:     '+$target)
    if(-not(Request-CommitConfirmation 'Change the Manager binding to this Hub?' ([bool]$ConfirmChanges))){
        if($Action-ne'Menu' -and -not$ConfirmChanges){Write-UiHost 'Explicit confirmation is required for direct binding changes.' -ForegroundColor DarkGray}
        Write-UiHost 'Cancelled. Binding unchanged.' -ForegroundColor Yellow
        Set-ActionSemantic 'cancelled'
        return 2
    }
    return Invoke-Manager @('-BindInstancePath',$target)
}

function Invoke-GenesisUi([string]$ConfigPath,[string]$NewInstancePath=$null,[string]$NewInstanceName=$null) {
    $binding=Get-QuickHubBinding
    $target=if($NewInstancePath){[System.IO.Path]::GetFullPath($NewInstancePath).TrimEnd('\')}else{[string]$binding.Path}
    $current=if($NewInstancePath){'<per-instance CURRENT assigned after Genesis>'}else{[string](Get-FrontendInstanceContext).CurrentZip}
    Write-UiHost ('Target Hub: '+$target)
    Write-UiHost ('CURRENT transport: '+$current)

    if($ConfigPath){
        $full=[System.IO.Path]::GetFullPath($ConfigPath)
        if(-not(Test-Path -LiteralPath $full -PathType Leaf)){Fail('Genesis config file does not exist: '+$full)}
        if(-not$ConfirmChanges){
            Write-UiHost 'Explicit confirmation is required for direct Genesis.' -ForegroundColor DarkGray
            Write-UiHost 'Cancelled. No changes made.' -ForegroundColor Yellow
            Set-ActionSemantic 'cancelled'
            return 2
        }
        if($NewInstancePath){
            $args=@('-GenesisInstancePath',$target,'-GenesisConfigPath',$full,'-GenesisConfirmed')
            if($NewInstanceName){$args+=@('-GenesisInstanceName',$NewInstanceName)}
            return Invoke-Manager $args
        }
        return Invoke-Manager @('-Genesis','-GenesisConfigPath',$full,'-GenesisConfirmed')
    }

    if($Action-ne'Menu'){
        Write-UiHost 'Direct Genesis requires -Path <config.json> and -ConfirmChanges.' -ForegroundColor Yellow
        Set-ActionSemantic 'cancelled'
        return 2
    }
    if((Test-Path -LiteralPath $target) -or ((-not$NewInstancePath)-and(Test-Path -LiteralPath $current))){
        Write-UiHost 'Genesis target or CURRENT transport already exists.' -ForegroundColor Yellow
        Set-ActionSemantic 'failed'
        return 1
    }

    $language=(Read-UiInput 'Canonical language [en]').Trim();if(-not$language){$language='en'}
    $purpose=(Read-UiInput 'Purpose: personal / professional / mixed [mixed]').Trim().ToLowerInvariant();if(-not$purpose){$purpose='mixed'}
    if(@('personal','professional','mixed')-notcontains$purpose){Write-UiHost 'Purpose must be personal, professional or mixed.' -ForegroundColor Yellow;Set-ActionSemantic 'failed';return 1}
    $timezone=(Read-UiInput 'Timezone [local]').Trim();if(-not$timezone){$timezone=[System.TimeZoneInfo]::Local.Id}
    $areasRaw=Read-UiInput 'Areas, comma-separated (optional)'
    $projectsRaw=Read-UiInput 'Live projects, comma-separated (optional)'
    $areas=@($areasRaw-split','|ForEach-Object{$_.Trim()}|Where-Object{$_}|Select-Object -Unique)
    $projects=@($projectsRaw-split','|ForEach-Object{$_.Trim()}|Where-Object{$_}|Select-Object -Unique)
    if($areas.Count-gt8){Write-UiHost 'Genesis supports at most 8 initial Areas.' -ForegroundColor Yellow;Set-ActionSemantic 'failed';return 1}
    if($projects.Count-gt12){Write-UiHost 'Genesis supports at most 12 initial Projects.' -ForegroundColor Yellow;Set-ActionSemantic 'failed';return 1}
    Write-UiHost ('Areas: '+$(if($areas.Count){$areas-join', '}else{'none'}))
    Write-UiHost ('Projects: '+$(if($projects.Count){$projects-join', '}else{'none'}))
    if(-not(Confirm 'Create the canonical initial Hub revision?')){
        Write-UiHost 'Cancelled. No changes made.' -ForegroundColor Yellow
        Set-ActionSemantic 'cancelled'
        return 2
    }

    $tmp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_genesis_'+[guid]::NewGuid().ToString('N')+'.json')
    $doc=[ordered]@{schema='keelaryn.genesis-input.v1';language=$language;purpose=$purpose;timezone=$timezone;areas=@($areas);projects=@($projects)}
    try{
        [System.IO.File]::WriteAllText($tmp,(($doc|ConvertTo-Json -Depth 6)+"`n"),(New-Object System.Text.UTF8Encoding($false)))
        if($NewInstancePath){
            $args=@('-GenesisInstancePath',$target,'-GenesisConfigPath',$tmp,'-GenesisConfirmed')
            if($NewInstanceName){$args+=@('-GenesisInstanceName',$NewInstanceName)}
            return Invoke-Manager $args
        }
        return Invoke-Manager @('-Genesis','-GenesisConfigPath',$tmp,'-GenesisConfirmed')
    }finally{Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}
}

function Invoke-Action([string]$Name,[string]$ActionPath) {
    switch($Name){
        'Status' { $null=Show-QuickStatus -DetailedWorkspace; return 0 }
        'OpenHub' { return Invoke-Manager @('-OpenOnly') }
        'Doctor' { return Invoke-Manager @('-Doctor') }
        'UpdateAll' { $q=Get-QuickStatus;if(($q.ManagerUpdates+$q.HubApproved)-eq0){Write-UiHost 'Manager: no pending update.';Write-UiHost 'Hub: no APPROVED update.';Set-ActionSemantic 'no_changes';return 0};return Invoke-Manager @('-UpdateAll') }
        'UpdateManager' { return Invoke-Manager @('-UpdateManager') }
        'UpdateHub' { return Invoke-Manager @('-UpdateHub') }
        'InstanceInfo' { return Invoke-Manager @('-InstanceInfo') }
        'ImportPackage' { return Import-Package $ActionPath }
        'PrepareTests' { return Invoke-Manager @('-PrepareTests') }
        'UnpackTest' { return Invoke-TestArchiveTool $ActionPath }
        'RunFullGate' { return Invoke-FullGate $ActionPath }
        'BuildAIContext' { return Invoke-Manager @('-BuildAIContext') }
        'BuildRelease' { return Invoke-Manager @('-BuildRelease') }
        'BuildDistribution' { return Invoke-Manager @('-BuildDistribution') }
        'BuildCandidateTransport' { $q=Get-QuickStatus;if($q.HubCandidate-eq0){Write-UiHost 'No Hub CANDIDATE is available. Nothing to build.';Set-ActionSemantic 'no_changes';return 0};return Invoke-Manager @('-BuildCandidateTransport') }
        'RestoreCandidateTransport' { $hubInbox=[string](Get-FrontendInstanceContext).HubInbox;$count=if(Test-Path -LiteralPath $hubInbox -PathType Container){@(Get-ChildItem -LiteralPath $hubInbox -File -Filter 'Keelaryn__Hub_CANDIDATE_TRANSPORT_*.json' -ErrorAction SilentlyContinue).Count}else{0};if($count-eq0){Write-UiHost 'No Hub CANDIDATE transport is available. Nothing to restore.';Set-ActionSemantic 'no_changes';return 0};return Invoke-Manager @('-RestoreCandidateTransport') }
        'PrepareWorkspaceSession' { $ctx=Get-RequiredFrontendInstanceContext; return Copy-CurrentForChatGPT (Join-Path ([string]$ctx.ExchangeRoot) 'workspace-input') }
        'PrepareChatManagerSession' { $ctx=Get-RequiredFrontendInstanceContext; return Copy-CurrentForChatGPT (Join-Path ([string]$ctx.ExchangeRoot) 'chat-manager-input') }
        'OpenChatGPTExchange' { $ctx=Get-RequiredFrontendInstanceContext; Ensure-ChatGPTExchangeLayout; return Open-Folder ([string]$ctx.ExchangeRoot) }
        'OpenChatGPTGuide' { return Open-ChatGPTGuide }
        'ImportLegacyExchange' { return Invoke-LegacyExchangeMigration -Apply:$ConfirmChanges }
        'StorageReport' { return Show-StorageReport }
        'CleanTestsWork' { return Invoke-CleanTestsWork -Apply:$ConfirmChanges }
        'CompactQualificationEvidence' { return Invoke-QualificationCompactor $ActionPath ([bool]$ConfirmChanges) }
        'RepairCurrentTransport' { return Invoke-Manager @('-RepairCurrentTransport') }
        'CheckMigrations' { return Invoke-Manager @('-CheckMigrations') }
        'ApplyMigrations' { return Invoke-ApplyMigrationsUi }
        'BindInstance' { return Invoke-BindInstanceUi $ActionPath }
        'InitializeInstanceRegistry' { $args=@('-InitializeInstanceRegistry');if($InstanceName){$args+=@('-RegisterInstanceName',$InstanceName)};return Invoke-Manager $args }
        'ListInstances' { return Invoke-Manager @('-ListInstances') }
        'SwitchInstance' { if(-not$ActionPath){Fail('SwitchInstance requires -Path <instance_id>.')};return Invoke-Manager @('-SwitchInstanceId',$ActionPath) }
        'RegisterInstance' { if(-not$ActionPath){Fail('RegisterInstance requires -Path <Hub directory>.')};$args=@('-RegisterInstancePath',$ActionPath);if($InstanceName){$args+=@('-RegisterInstanceName',$InstanceName)};return Invoke-Manager $args }
        'Genesis' { return Invoke-GenesisUi $ActionPath }
        'MigrateInstanceIdentity' { return Invoke-Manager @('-AdoptInstanceIdentity') }
        'MigrateLegacyNamespace' { return Invoke-Manager @('-MigrateLegacyNamespace') }
        'MigrateLayout' { return Invoke-Manager @('-MigrateLayout') }
        'FinalizeLayout' { return Invoke-Manager @('-FinalizeLayout') }
        'FinalizeFilesystemLayout' { return Invoke-Manager @('-FinalizeFilesystemLayout') }
        'OpenInbox' { Ensure-DirectorySafe $Inbox 'Manager inbox'; return Open-Folder $Inbox }
        'OpenLogs' { Ensure-DirectorySafe $Logs 'Manager logs'; return Open-Folder $Logs }
        'OpenReleases' { Ensure-DirectorySafe $Releases 'Manager releases'; return Open-Folder $Releases }
        'OpenTestsWork' { Ensure-DirectorySafe (Join-Path $TestsRoot 'work') 'Tests work'; return Open-Folder (Join-Path $TestsRoot 'work') }
        'OpenTestsResults' { Ensure-DirectorySafe (Join-Path $TestsRoot 'results') 'Tests results'; return Open-Folder (Join-Path $TestsRoot 'results') }
        'OpenCompatCommands' { $rc=Invoke-Manager @('-InitializePresentation'); if($rc-ne0){return $rc}; return Open-Folder $CompatCommands }
        'OpenKeelarynRoot' { return Open-Folder $LayoutRoot }
        'EnsureRootLauncher' { $null=Ensure-RootLauncher; return 0 }
        'RenderMain' { Show-MainMenuScreen; return 0 }
        default { Fail('Unsupported frontend action: '+$Name) }
    }
}

function Invoke-MenuAction([string]$Name,[string]$ActionPath,[string]$Label) {
    if([string]::IsNullOrWhiteSpace($Label)){$Label=$Name}
    $script:LastActionSemantic='completed'
    Write-UiHost ''
    Write-UiHost ('--- '+$Label+' ---') -ForegroundColor Cyan
    try{$rc=[int](Invoke-Action $Name $ActionPath)}catch{
        $script:LastActionSemantic='failed'
        Write-UiHost ('FAILED: '+$Label) -ForegroundColor Red
        Write-UiHost $_.Exception.Message -ForegroundColor Red
        return 1
    }
    Write-UiHost ''
    switch($script:LastActionSemantic){
        'no_changes' {Write-UiHost 'NO CHANGES REQUIRED' -ForegroundColor Green}
        'cancelled' {Write-UiHost 'CANCELLED. No changes made.' -ForegroundColor Yellow}
        'failed' {Write-UiHost ('FAILED: '+$Label+' (ExitCode '+$rc+')') -ForegroundColor Red}
        default {
            if($rc-eq0){Write-UiHost 'COMPLETED' -ForegroundColor Green}
            elseif($Name-eq'Doctor'-and$rc-eq2){Write-UiHost 'COMPLETED WITH WARNINGS' -ForegroundColor Yellow}
            elseif($rc-eq2-or$rc-eq3){Write-UiHost ('FAILED: '+$Label+' (ExitCode '+$rc+')') -ForegroundColor Yellow}
            else{Write-UiHost ('FAILED: '+$Label+' (ExitCode '+$rc+')') -ForegroundColor Red}
        }
    }
    return $rc
}

function Pause-Menu {
    Write-UiHost ''
    Write-UiText '[Enter] Back' -ForegroundColor DarkGray
    try{[void][Console]::ReadLine()}catch{[void](Microsoft.PowerShell.Utility\Read-Host)}
}

function Show-ChatGPTSetupMenu {
    while($true){
        Clear-Ui
        Write-UiHost 'Set up ChatGPT for Keelaryn' -ForegroundColor Cyan
        Write-UiHost '  [1] Standard setup (recommended)'
        Write-UiHost '  [2] Developer / Contributor setup'
        Write-UiHost '  [3] Skip / back'
        $choice=(Read-UiInput 'Select').Trim()
        switch($choice){
            '1' {
                Ensure-ChatGPTExchangeLayout
                Write-UiHost 'Create these ChatGPT Projects:' -ForegroundColor Green
                Write-UiHost '  Keelaryn - Workspace'
                Write-UiHost '  Keelaryn - Chats'
                Write-UiHost '  Keelaryn - Chat Manager'
                Write-UiHost ('Copy the matching Project instructions from: '+$ChatGPTDocsRoot)
                $null=Open-ChatGPTGuide
                Pause-Menu
            }
            '2' {
                Ensure-ChatGPTExchangeLayout
                Write-UiHost 'Create the Standard three Projects plus:' -ForegroundColor Green
                Write-UiHost '  Keelaryn - Manager Development'
                Write-UiHost ('Copy the matching Project instructions from: '+$ChatGPTDocsRoot)
                $null=Open-ChatGPTGuide
                Pause-Menu
            }
            '3' {return}
            default {Write-UiHost 'Unknown selection.' -ForegroundColor Yellow;Pause-Menu}
        }
    }
}

function Show-ChatGPTMenu {
    while($true){
        Clear-Ui
        $null=Show-QuickStatus
        Write-UiHost ''
        Write-UiHost 'ChatGPT' -ForegroundColor Cyan
        Write-UiHost '  [1] Prepare Workspace session'
        Write-UiHost '  [2] Prepare Chat Manager session'
        Write-UiHost '  [3] Open exchange folder'
        Write-UiHost '  [4] Setup guide / Project templates'
        Write-UiHost '  [5] Import legacy Inputs_outputs (copy only)...'
        Write-UiHost '  [0] Back'
        $choice=(Read-UiInput 'Select').Trim()
        switch($choice){
            '1' {$null=Invoke-MenuAction 'PrepareWorkspaceSession' $null 'Prepare Workspace session';Pause-Menu}
            '2' {$null=Invoke-MenuAction 'PrepareChatManagerSession' $null 'Prepare Chat Manager session';Pause-Menu}
            '3' {$null=Invoke-MenuAction 'OpenChatGPTExchange' $null 'Open ChatGPT exchange'}
            '4' {Show-ChatGPTSetupMenu}
            '5' {
                $null=Invoke-LegacyExchangeMigration
                if(Confirm 'Copy and SHA-256 verify legacy Inputs_outputs now?'){$null=Invoke-LegacyExchangeMigration -Apply}
                Pause-Menu
            }
            '0' {return}
            default {Write-UiHost 'Unknown selection.' -ForegroundColor Yellow;Pause-Menu}
        }
    }
}

function Invoke-NewRegisteredHubGenesisUi {
    $ctx=Get-FrontendInstanceContext
    if(-not$ctx.RegistryActive-or-not$ctx.InstanceId){
        Write-UiHost 'Multi-Hub registry must be valid before creating another Hub.' -ForegroundColor Yellow
        Set-ActionSemantic 'failed'
        return 1
    }
    $name=(Read-UiInput 'Display name for new Hub').Trim()
    if(-not$name){Write-UiHost 'Display name is required.' -ForegroundColor Yellow;Set-ActionSemantic 'cancelled';return 2}
    $folder=(Read-UiInput 'Folder name under keelaryn\hubs (for example: vova)').Trim()
    if(-not$folder){Write-UiHost 'Folder name is required.' -ForegroundColor Yellow;Set-ActionSemantic 'cancelled';return 2}
    if($folder.Length-gt64-or$folder.EndsWith(' ')-or$folder.EndsWith('.')-or$folder-match'[<>:"/\\|?*\x00-\x1F]'){
        Write-UiHost 'Folder name is not Win32-safe.' -ForegroundColor Yellow;Set-ActionSemantic 'failed';return 1
    }
    $target=Join-Path (Join-Path $LayoutRoot 'hubs') $folder
    Write-UiHost ('New Hub path: '+$target)
    $rc=Invoke-GenesisUi $null $target $name
    if($rc-ne0){return $rc}
    $registry=Get-Content -LiteralPath (Join-Path $StateRoot 'instances.json') -Raw -Encoding UTF8|ConvertFrom-Json
    $targetFull=[System.IO.Path]::GetFullPath($target).TrimEnd('\')
    $row=@($registry.instances|Where-Object{[System.IO.Path]::GetFullPath([string]$_.vault_path).TrimEnd('\')-ceq$targetFull})
    if($row.Count-ne1){Fail('Newly created Hub did not resolve to exactly one registry row.')}
    if(Confirm ('Switch active Hub to '+$name+' now?')){
        return Invoke-Manager @('-SwitchInstanceId',[string]$row[0].instance_id)
    }
    return 0
}
function Get-FrontendRegistryRows {
    $ctx=Get-FrontendInstanceContext
    if(-not$ctx.RegistryActive-or-not$ctx.InstanceId){return @()}
    $registryPath=Join-Path $StateRoot 'instances.json'
    $registry=Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8|ConvertFrom-Json
    return @($registry.instances|Sort-Object name,instance_id)
}

function Show-HubManagementMenu {
    while($true){
        Clear-Ui
        $ctx=Get-FrontendInstanceContext
        Write-UiHost 'Manage Hubs' -ForegroundColor Cyan
        if(-not$ctx.RegistryActive){
            Write-UiHost 'Multi-Hub registry is not initialized. Current installation remains in single-Hub compatibility mode.' -ForegroundColor DarkGray
            Write-UiHost '  [1] Enable multi-Hub for the current Hub'
            Write-UiHost '  [0] Back'
            $choice=(Read-UiInput 'Select').Trim()
            if($choice-eq'1'){
                $name=(Read-UiInput 'Display name for current Hub [Primary]').Trim();if(-not$name){$name='Primary'}
                if(Confirm 'Initialize multi-Hub registry without changing Hub content?'){
                    $rc=Invoke-Manager @('-InitializeInstanceRegistry','-RegisterInstanceName',$name)
                    if($rc-ne0){Pause-Menu}else{Write-UiHost 'Registry initialized.' -ForegroundColor Green;Pause-Menu}
                }
            }elseif($choice-eq'0'){return}else{Write-UiHost 'Unknown selection.' -ForegroundColor Yellow;Pause-Menu}
            continue
        }
        if(-not$ctx.InstanceId){
            Write-UiHost 'Registry exists but is invalid/unresolved. Run Doctor; switching is disabled.' -ForegroundColor Red
            Write-UiHost '  [0] Back'
            if((Read-UiInput 'Select').Trim()-eq'0'){return}
            continue
        }
        Write-UiHost ('Active: '+$ctx.Name+' | '+$ctx.InstanceId) -ForegroundColor Green
        Write-UiHost ''
        Write-UiHost '  [1] List registered Hubs'
        Write-UiHost '  [2] Switch active Hub'
        Write-UiHost '  [3] Create new Hub'
        Write-UiHost '  [4] Connect existing Hub'
        Write-UiHost '  [5] Active Hub info'
        Write-UiHost '  [0] Back'
        $choice=(Read-UiInput 'Select').Trim()
        switch($choice){
            '1' {$null=Invoke-Manager @('-ListInstances');Pause-Menu}
            '2' {
                $rows=@(Get-FrontendRegistryRows)
                for($i=0;$i-lt$rows.Count;$i++){
                    $mark=if([string]$rows[$i].instance_id-eq[string]$ctx.InstanceId){'*'}else{' '}
                    Write-UiHost ('  [{0}] {1} {2} | {3}' -f ($i+1),$mark,[string]$rows[$i].name,([string]$rows[$i].instance_id).Substring(0,8))
                }
                $raw=(Read-UiInput 'Select Hub number').Trim();$n=0
                if([int]::TryParse($raw,[ref]$n)-and$n-ge1-and$n-le$rows.Count){
                    $target=$rows[$n-1]
                    if([string]$target.instance_id-eq[string]$ctx.InstanceId){Write-UiHost 'Already active.' -ForegroundColor DarkGray;Pause-Menu}
                    elseif(Confirm ('Switch active Hub to '+[string]$target.name+'?')){
                        $null=Invoke-Manager @('-SwitchInstanceId',[string]$target.instance_id);Pause-Menu
                    }
                }else{Write-UiHost 'Invalid selection.' -ForegroundColor Yellow;Pause-Menu}
            }
            '3' {
                $null=Invoke-NewRegisteredHubGenesisUi
                Pause-Menu
            }
            '4' {
                $target=Select-Folder 'Select existing Keelaryn Hub directory' $LayoutRoot
                if($target){
                    $name=(Read-UiInput ('Display name ['+(Split-Path $target -Leaf)+']')).Trim();if(-not$name){$name=Split-Path $target -Leaf}
                    if(Confirm ('Register this Hub without copying or modifying its content? '+$target)){
                        $null=Invoke-Manager @('-RegisterInstancePath',$target,'-RegisterInstanceName',$name);Pause-Menu
                    }
                }
            }
            '5' {$null=Invoke-Manager @('-InstanceInfo');Pause-Menu}
            '0' {return}
            default {Write-UiHost 'Unknown selection.' -ForegroundColor Yellow;Pause-Menu}
        }
    }
}
function Show-MaintenanceMenu {
    while($true){
        Clear-Ui
        $null=Show-QuickStatus
        Write-UiHost ''
        Write-UiHost 'Maintenance' -ForegroundColor Cyan
        Write-UiHost '  [1] Repair Hub CURRENT'
        Write-UiHost '  [2] Check migrations'
        Write-UiHost '  [3] Apply pending migrations'
        Write-UiHost '  [4] Manage Hubs...'
        Write-UiHost '  [5] Open update inbox'
        Write-UiHost '  [6] Open logs'
        Write-UiHost '  [7] Storage report'
        Write-UiHost '  [8] Clean disposable test work...'
        Write-UiHost '  [9] Compact completed qualification evidence...'
        Write-UiHost '  [0] Back'
        $choice=(Read-UiInput 'Select').Trim()
        switch -Regex($choice){
            '^1$' {if(Confirm 'Run explicit CURRENT transport repair?'){$null=Invoke-MenuAction 'RepairCurrentTransport' $null 'Repair Hub CURRENT';Pause-Menu}}
            '^2$' {$null=Invoke-MenuAction 'CheckMigrations' $null 'Check migrations';Pause-Menu}
            '^3$' {$null=Invoke-MenuAction 'ApplyMigrations' $null 'Apply pending migrations';Pause-Menu}
            '^4$' {Show-HubManagementMenu}
            '^5$' {$null=Invoke-MenuAction 'OpenInbox' $null 'Open update inbox'}
            '^6$' {$null=Invoke-MenuAction 'OpenLogs' $null 'Open logs'}
            '^7$' {$null=Invoke-MenuAction 'StorageReport' $null 'Storage report';Pause-Menu}
            '^8$' {
                $null=Invoke-CleanTestsWork
                if(Confirm 'Delete the listed disposable tests\work contents?'){$null=Invoke-CleanTestsWork -Apply}
                Pause-Menu
            }
            '^9$' {
                $target=Select-Folder 'Select completed qualification results directory' (Join-Path $TestsRoot 'results')
                if($target){
                    $rc=Invoke-QualificationCompactor $target $false
                    if($rc-eq0-and(Confirm 'Archive, SHA-256 verify and compact this completed qualification evidence?')){$null=Invoke-QualificationCompactor $target $true}
                }
                Pause-Menu
            }
            '^0$' {return}
            default {Write-UiHost 'Unknown selection.' -ForegroundColor Yellow;Pause-Menu}
        }
    }
}

function Show-DevelopmentMenu {
    while($true){
        Clear-Ui
        $null=Show-QuickStatus
        Write-UiHost ''
        Write-UiHost 'Development' -ForegroundColor Cyan
        Write-UiHost 'Validation' -ForegroundColor DarkCyan
        Write-UiHost '  [1] Run Full Gate...'
        Write-UiHost '  [2] Run test package...'
        Write-UiHost 'Build' -ForegroundColor DarkCyan
        Write-UiHost '  [3] Build AI_CONTEXT'
        Write-UiHost '  [4] Build release'
        Write-UiHost '  [5] Build distribution'
        Write-UiHost 'Hub candidate transport' -ForegroundColor DarkCyan
        Write-UiHost '  [6] Export transport for Hub CANDIDATE'
        Write-UiHost '  [7] Restore Hub CANDIDATE transport'
        Write-UiHost 'Results' -ForegroundColor DarkCyan
        Write-UiHost '  [8] Open test workspace'
        Write-UiHost '  [9] Open test results'
        Write-UiHost '  [R] Open releases'
        Write-UiHost '  [0] Back'
        $choice=(Read-UiInput 'Select').Trim()
        switch -Regex($choice){
            '^1$' {$null=Invoke-MenuAction 'RunFullGate' $null 'Run Full Gate';Pause-Menu}
            '^2$' {$null=Invoke-MenuAction 'UnpackTest' $null 'Run test package';Pause-Menu}
            '^3$' {$null=Invoke-MenuAction 'BuildAIContext' $null 'Build AI_CONTEXT';Pause-Menu}
            '^4$' {$null=Invoke-MenuAction 'BuildRelease' $null 'Build release';Pause-Menu}
            '^5$' {$null=Invoke-MenuAction 'BuildDistribution' $null 'Build distribution';Pause-Menu}
            '^6$' {$null=Invoke-MenuAction 'BuildCandidateTransport' $null 'Export Hub CANDIDATE transport';Pause-Menu}
            '^7$' {$null=Invoke-MenuAction 'RestoreCandidateTransport' $null 'Restore Hub CANDIDATE transport';Pause-Menu}
            '^8$' {$null=Invoke-MenuAction 'OpenTestsWork' $null 'Open test workspace'}
            '^9$' {$null=Invoke-MenuAction 'OpenTestsResults' $null 'Open test results'}
            '^(?i)r$' {$null=Invoke-MenuAction 'OpenReleases' $null 'Open releases'}
            '^0$' {return}
            default {Write-UiHost 'Unknown selection.' -ForegroundColor Yellow;Pause-Menu}
        }
    }
}

function Show-LegacyToolsMenu {
    while($true){
        Clear-Ui
        Write-UiHost 'Legacy migration tools' -ForegroundColor Cyan
        Write-UiHost '  [1] Adopt instance identity'
        Write-UiHost '  [2] Migrate legacy namespace'
        Write-UiHost '  [3] Migrate canonical layout'
        Write-UiHost '  [4] Finalize legacy layout'
        Write-UiHost '  [5] Finalize Manager filesystem layout'
        Write-UiHost '  [0] Back'
        $choice=(Read-UiInput 'Select').Trim()
        switch($choice){
            '1' {if(Confirm 'Run explicit instance identity adoption?'){$null=Invoke-MenuAction 'MigrateInstanceIdentity' $null 'Adopt instance identity';Pause-Menu}}
            '2' {if(Confirm 'Run legacy namespace migration?'){$null=Invoke-MenuAction 'MigrateLegacyNamespace' $null 'Migrate legacy namespace';Pause-Menu}}
            '3' {if(Confirm 'Run canonical layout migration?'){$null=Invoke-MenuAction 'MigrateLayout' $null 'Migrate canonical layout';Pause-Menu}}
            '4' {if(Confirm 'Finalize legacy layout after migration?'){$null=Invoke-MenuAction 'FinalizeLayout' $null 'Finalize legacy layout';Pause-Menu}}
            '5' {if(Confirm 'Finalize Manager filesystem layout?'){$null=Invoke-MenuAction 'FinalizeFilesystemLayout' $null 'Finalize Manager filesystem layout';Pause-Menu}}
            '0' {return}
            default {Write-UiHost 'Unknown selection.' -ForegroundColor Yellow;Pause-Menu}
        }
    }
}

function Show-CompatibilityMenu {
    while($true){
        Clear-Ui
        Write-UiHost 'Compatibility / legacy migration' -ForegroundColor Cyan
        Write-UiHost '  [1] Check compatibility / migrations'
        Write-UiHost '  [2] Apply required migrations'
        Write-UiHost '  [3] Legacy migration tools...'
        Write-UiHost '  [0] Back'
        $choice=(Read-UiInput 'Select').Trim()
        switch($choice){
            '1' {$null=Invoke-MenuAction 'CheckMigrations' $null 'Check compatibility / migrations';Pause-Menu}
            '2' {$null=Invoke-MenuAction 'ApplyMigrations' $null 'Apply required migrations';Pause-Menu}
            '3' {Show-LegacyToolsMenu}
            '0' {return}
            default {Write-UiHost 'Unknown selection.' -ForegroundColor Yellow;Pause-Menu}
        }
    }
}

function Show-AdvancedMenu {
    while($true){
        Clear-Ui
        $null=Show-QuickStatus
        Write-UiHost ''
        Write-UiHost 'Advanced' -ForegroundColor Cyan
        Write-UiHost '  [1] Genesis new Hub...'
        Write-UiHost '  [2] Compatibility / legacy migration...'
        Write-UiHost '  [3] Repair root launcher'
        Write-UiHost '  [4] Open compatibility commands'
        Write-UiHost '  [0] Back'
        $choice=(Read-UiInput 'Select').Trim()
        switch($choice){
            '1' {$null=Invoke-MenuAction 'Genesis' $null 'Genesis new Hub';Pause-Menu}
            '2' {Show-CompatibilityMenu}
            '3' {$null=Invoke-MenuAction 'EnsureRootLauncher' $null 'Repair root launcher';Pause-Menu}
            '4' {$null=Invoke-MenuAction 'OpenCompatCommands' $null 'Open compatibility commands'}
            '0' {return}
            default {Write-UiHost 'Unknown selection.' -ForegroundColor Yellow;Pause-Menu}
        }
    }
}

function Show-SetupCompletion {
    $doctorRc=[int](Invoke-MenuAction 'Doctor' $null 'Initial Doctor')
    Write-UiHost ''
    if($doctorRc-eq0){
        Write-UiHost 'Keelaryn setup is ready.' -ForegroundColor Green
        Write-UiHost '  [1] Open Hub'
        Write-UiHost '  [2] Main menu'
        Write-UiHost '  [3] Set up ChatGPT...'
        $choice=(Read-UiInput 'Select').Trim()
        if($choice-eq'1'){$null=Invoke-Action 'OpenHub' $null}
        elseif($choice-eq'3'){Show-ChatGPTSetupMenu}
        return
    }
    Write-UiHost 'Setup completed, but Doctor requires attention.' -ForegroundColor Yellow
    Pause-Menu
}

function Show-FirstRunWizard {
    while($true){
        $disposition=Get-StartupDisposition
        if($disposition-eq'ready' -or $disposition-eq'not_applicable'){return $true}
        Clear-Ui
        Set-UiTitle ('Keelaryn Manager '+(Read-ManagerVersion))
        Write-UiHost '============================================================' -ForegroundColor DarkCyan
        Write-UiHost ' Welcome to Keelaryn' -ForegroundColor Cyan
        Write-UiHost '============================================================' -ForegroundColor DarkCyan
        Write-UiHost ''

        if($disposition-eq'new_install'){
            Write-UiHost 'No Hub is configured yet.'
            Write-UiHost 'Create a new Hub or connect an existing one.' -ForegroundColor DarkGray
            Write-UiHost ''
            Write-UiHost '  [1] Create a new Hub'
            Write-UiHost '  [2] Connect an existing Hub'
            Write-UiHost '  [3] Main menu for now'
            Write-UiHost '  [0] Exit'
            $choice=(Read-UiInput 'Select').Trim()
            switch($choice){
                '1' {
                    $rc=[int](Invoke-MenuAction 'Genesis' $null 'Create new Hub')
                    if($rc-eq0){Show-SetupCompletion;return $true}
                    Pause-Menu
                }
                '2' {
                    $rc=[int](Invoke-MenuAction 'BindInstance' $null 'Connect existing Hub')
                    if($rc-eq0){Show-SetupCompletion;return $true}
                    Pause-Menu
                }
                '3' {return $true}
                '0' {return $false}
                default {Write-UiHost 'Unknown selection.' -ForegroundColor Yellow;Pause-Menu}
            }
            continue
        }

        Write-UiHost 'No valid Hub is currently available, but this is not an empty first-run state.' -ForegroundColor Yellow
        if(Test-Path -LiteralPath $HubRoot){
            Write-UiHost ('Canonical Hub path already exists: '+$HubRoot)
            Write-UiHost 'Genesis will not overwrite it. A source checkout is not a clean runtime installation.' -ForegroundColor DarkGray
        }
        Write-UiHost ''
        Write-UiHost '  [1] Run Doctor'
        Write-UiHost '  [2] Connect an existing Hub'
        Write-UiHost '  [3] Main menu'
        Write-UiHost '  [0] Exit'
        $choice=(Read-UiInput 'Select').Trim()
        switch($choice){
            '1' {$null=Invoke-MenuAction 'Doctor' $null 'Doctor';Pause-Menu}
            '2' {
                $rc=[int](Invoke-MenuAction 'BindInstance' $null 'Connect existing Hub')
                if($rc-eq0){Show-SetupCompletion;return $true}
                Pause-Menu
            }
            '3' {return $true}
            '0' {return $false}
            default {Write-UiHost 'Unknown selection.' -ForegroundColor Yellow;Pause-Menu}
        }
    }
}

function Show-MainMenuScreen {
    Clear-Ui
    $version=Read-ManagerVersion
    Set-UiTitle ('Keelaryn Manager '+$version)
    Write-UiHost '============================================================' -ForegroundColor DarkCyan
    Write-UiHost ' Keelaryn' -ForegroundColor Cyan
    Write-UiHost '============================================================' -ForegroundColor DarkCyan
    $null=Show-QuickStatus
    Write-UiHost ''
    Write-UiHost 'Everyday' -ForegroundColor Cyan
    foreach($line in @((Get-MainMenuContractLines)|Select-Object -Skip 2)){
        Write-UiHost $line
        if($line-eq'  [5] Show instance info'){Write-UiHost ''}
    }
    Write-UiHost ''
}

function Show-MainMenu {
    if(-not$NoRootLauncher){$null=Ensure-RootLauncher -Quiet}
    $presentationRc=Invoke-Manager @('-InitializePresentation')
    if($presentationRc-ne0){Write-UiHost('Presentation initialization returned '+$presentationRc+'. Core actions remain available.')-ForegroundColor Yellow}
    if(-not(Show-FirstRunWizard)){return 0}
    while($true){
        Show-MainMenuScreen
        $choice=(Read-UiInput 'Select').Trim()
        switch($choice){
            '1' {$null=Invoke-MenuAction 'OpenHub' $null 'Open Hub'}
            '2' {$null=Invoke-MenuAction 'Doctor' $null 'Doctor';Pause-Menu}
            '3' {$null=Invoke-MenuAction 'ImportPackage' $null 'Install update package';Pause-Menu}
            '4' {$null=Invoke-MenuAction 'UpdateAll' $null 'Install pending updates';Pause-Menu}
            '5' {$null=Invoke-MenuAction 'InstanceInfo' $null 'Installation info';Pause-Menu}
            '6' {Show-MaintenanceMenu}
            '7' {Show-DevelopmentMenu}
            '8' {Show-AdvancedMenu}
            '9' {$null=Invoke-MenuAction 'OpenKeelarynRoot' $null 'Open Keelaryn folder'}
            {$_-match'^(?i)c$'} {Show-ChatGPTMenu}
            '0' {return 0}
            default {Write-UiHost 'Unknown selection.' -ForegroundColor Yellow;Pause-Menu}
        }
    }
}

$script:FrontendSelfTestReason=''
function Test-FrontendSelf {
    try{
        if(-not(Test-Path -LiteralPath $ManagerScript -PathType Leaf)){
            $script:FrontendSelfTestReason='Manager runtime missing.'
            return $false
        }
        $v=Read-ManagerVersion
        $parsed=[version]'0.0'
        if(-not[version]::TryParse($v,[ref]$parsed)){
            $script:FrontendSelfTestReason='Manager version is not parseable: '+$v
            return $false
        }
        $empty=[System.IO.Path]::GetTempFileName()
        try{
            [System.IO.File]::WriteAllBytes($empty,[byte[]]@())
            if((Get-FileSha256Hex $empty)-cne'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'){
                $script:FrontendSelfTestReason='SHA-256 helper fixed vector mismatch.'
                return $false
            }
        }finally{Remove-Item -LiteralPath $empty -Force -ErrorAction SilentlyContinue}
        if((Resolve-PickerSelection $true $true 'C:\picked.zip' 'C:\manual.zip')-cne'C:\picked.zip'){
            $script:FrontendSelfTestReason='Picker GUI-success state-machine failed.'
            return $false
        }
        if($null-ne(Resolve-PickerSelection $true $false $null 'C:\manual-must-not-run.zip')){
            $script:FrontendSelfTestReason='Picker GUI-Cancel incorrectly fell through to manual selection.'
            return $false
        }
        if((Resolve-PickerSelection $false $false $null '  "C:\manual.zip"  ')-cne'C:\manual.zip'){
            $script:FrontendSelfTestReason='Picker GUI-unavailable manual fallback failed.'
            return $false
        }
        if(-not(Resolve-ExplicitConfirmation $true $false $false)){
            $script:FrontendSelfTestReason='Explicit confirmation policy failed.'
            return $false
        }
        if(Resolve-ExplicitConfirmation $false $false $true){
            $script:FrontendSelfTestReason='Direct non-interactive confirmation policy incorrectly approved.'
            return $false
        }
        if(-not(Resolve-ExplicitConfirmation $false $true $true)){
            $script:FrontendSelfTestReason='Interactive confirmation policy failed.'
            return $false
        }
        if(Resolve-ExplicitConfirmation $false $true $false){
            $script:FrontendSelfTestReason='Interactive decline policy failed.'
            return $false
        }
        if((Resolve-StartupDisposition $true $true $false $false $false $false)-cne'ready'){
            $script:FrontendSelfTestReason='First-run ready-state classification failed.'
            return $false
        }
        if((Resolve-StartupDisposition $true $false $false $false $false $false)-cne'new_install'){
            $script:FrontendSelfTestReason='First-run new-install classification failed.'
            return $false
        }
        if((Resolve-StartupDisposition $true $false $true $false $false $false)-cne'attention'){
            $script:FrontendSelfTestReason='First-run collision classification failed.'
            return $false
        }
        if((Resolve-StartupDisposition $true $false $false $true $false $false)-cne'attention'){
            $script:FrontendSelfTestReason='First-run existing-state classification failed.'
            return $false
        }
        if((Resolve-StartupDisposition $false $false $false $false $false $false)-cne'not_applicable'){
            $script:FrontendSelfTestReason='First-run non-canonical classification failed.'
            return $false
        }
        $status=Get-QuickStatus
        if(-not$status.ManagerVersion){
            $script:FrontendSelfTestReason='Quick status did not report ManagerVersion.'
            return $false
        }
        if((Get-GeneratedRootLauncherText)-notmatch'(?i)manager\\KEELARYN\.cmd'){
            $script:FrontendSelfTestReason='Generated root launcher text is invalid.'
            return $false
        }
        $tool=Join-Path $PSScriptRoot 'Unpack-KeelarynTestArchive.ps1'
        if(-not(Test-Path -LiteralPath $tool -PathType Leaf)){
            $script:FrontendSelfTestReason='Integrated test archive tool is missing.'
            return $false
        }
        $contract=[string]::Join("`n",@(Get-MainMenuContractLines))
        if([string]::IsNullOrWhiteSpace($script:FrontendScriptPath) -or -not (Test-Path -LiteralPath $script:FrontendScriptPath -PathType Leaf)){
            $script:FrontendSelfTestReason='Frontend script path is unavailable for source-contract validation.'
            return $false
        }
        $frontendSource=[System.IO.File]::ReadAllText($script:FrontendScriptPath,[System.Text.Encoding]::UTF8)
        foreach($uiToken in @('function Invoke-MenuAction','function Invoke-FullGate','function Invoke-GenesisUi','function Show-FirstRunWizard','function Resolve-StartupDisposition','function Refresh-FrontendOperationalPaths','function Show-ChatGPTMenu','function Ensure-ChatGPTExchangeLayout','function Invoke-LegacyExchangeMigration','function Invoke-CleanTestsWork','function Invoke-QualificationCompactor','Show-SetupCompletion','GenesisConfigPath','GenesisConfirmed','-NonInteractive','[Enter] Back','COMPLETED WITH WARNINGS','elseif($Name-eq''Doctor''-and$rc-eq2)','product\runtime\Keelaryn__Manager.ps1')){
            if(-not$frontendSource.Contains($uiToken)){
                $script:FrontendSelfTestReason='Visible action-output contract missing token: '+$uiToken
                return $false
            }
        }
        if($frontendSource-match'(?m)^\s*\$null\s*=\s*Invoke-Action\b'){
            $script:FrontendSelfTestReason='Interactive menu still suppresses Invoke-Action output.'
            return $false
        }
        foreach($token in @('Keelaryn','Everyday','[2] Doctor','[5] Installation info','[7] Development','[C] ChatGPT','[0] Exit')){
            if($contract-notmatch[regex]::Escape($token)){
                $script:FrontendSelfTestReason='Main menu render contract omitted token: '+$token
                return $false
            }
        }
        $script:FrontendSelfTestReason=''
        return $true
    }
    catch{
        $script:FrontendSelfTestReason=$_.Exception.Message
        return $false
    }
}

try{
    if($SelfTest){
        if(Test-FrontendSelf){
            Write-UiHost 'Keelaryn frontend self-test PASS.' -ForegroundColor Green
            exit 0
        }
        Write-UiHost ('Keelaryn frontend self-test FAIL: '+[string]$script:FrontendSelfTestReason) -ForegroundColor Red
        exit 1
    }

    if($Action-eq'Menu'){
        exit (Show-MainMenu)
    }
    exit (Invoke-Action $Action $Path)
}
catch{
    Write-UiHost ''
    Write-UiHost ('Keelaryn frontend error: '+$_.Exception.Message) -ForegroundColor Red
    exit 1
}
