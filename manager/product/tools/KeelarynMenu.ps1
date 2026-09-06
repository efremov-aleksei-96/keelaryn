[CmdletBinding()]
param(
    [ValidateSet(
        'Menu','Status','OpenHub','Doctor','UpdateAll','UpdateManager','UpdateHub',
        'InstanceInfo','ImportPackage','PrepareTests','UnpackTest','RunFullGate','BuildAIContext',
        'BuildRelease','BuildDistribution','BuildCandidateTransport','RestoreCandidateTransport',
        'RepairCurrentTransport','CheckMigrations','ApplyMigrations','BindInstance','Genesis',
        'MigrateInstanceIdentity','MigrateLegacyNamespace','MigrateLayout','FinalizeLayout','FinalizeFilesystemLayout',
        'OpenInbox','OpenLogs','OpenReleases','OpenTestsWork','OpenTestsResults','OpenCompatCommands','OpenKeelarynRoot',
        'EnsureRootLauncher','RenderMain'
    )]
    [string]$Action='Menu',
    [string]$Path,
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
$StateLayoutActive=Test-Path -LiteralPath $StateLayoutReceipt -PathType Leaf
$CanonicalLayout=((Split-Path $ManagerRoot -Leaf) -ieq 'manager')
$HubRoot=Join-Path $LayoutRoot 'hub'
$TestsRoot=Join-Path $LayoutRoot 'tests'
$Inbox=if($StateLayoutActive){Join-Path $StateRoot 'inbox'}else{Join-Path $ManagerRoot '_inbox'}
$Logs=if($StateLayoutActive){Join-Path $StateRoot 'logs'}else{Join-Path $ManagerRoot '_logs'}
$Releases=if($StateLayoutActive){Join-Path $StateRoot 'releases'}else{Join-Path $ManagerRoot '_releases'}
$CompatCommands=Join-Path $ManagerRoot 'compat\commands'

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

    $managerUpdates=0;$hubApproved=0;$hubCandidate=0
    if(Test-Path -LiteralPath $Inbox -PathType Container){
        $managerUpdates=@(Get-ChildItem -LiteralPath $Inbox -File -Filter '*.zip' -ErrorAction SilentlyContinue|
            Where-Object{$_.Name-match'(?i)^Keelaryn__Manager_Update_'}).Count
        $hubApproved=@(Get-ChildItem -LiteralPath $Inbox -File -Filter '*.zip' -ErrorAction SilentlyContinue|
            Where-Object{$_.Name-match'(?i)^(Keelaryn__Hub|Core__Hub)_APPROVED_'}).Count
        $hubCandidate=@(Get-ChildItem -LiteralPath $Inbox -File -Filter '*.zip' -ErrorAction SilentlyContinue|
            Where-Object{$_.Name-match'(?i)^(Keelaryn__Hub|Core__Hub)_CANDIDATE_'}).Count
    }

    $rootExtras=@()
    if(Test-Path -LiteralPath $LayoutRoot -PathType Container){
        $allowed=@('manager','hub','tests','Keelaryn.cmd')
        $rootExtras=@(Get-ChildItem -LiteralPath $LayoutRoot -Force -ErrorAction SilentlyContinue|
            Where-Object{$allowed-notcontains$_.Name}|Sort-Object Name|ForEach-Object{$_.Name})
    }

    $testsExtras=@()
    if(Test-Path -LiteralPath $TestsRoot -PathType Container){
        $allowedTests=@('work','results','legacy-layout-backup','WORKSPACE.json')
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
    return [int]$LASTEXITCODE
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

    Ensure-DirectorySafe $Inbox 'Manager inbox'
    $dest=Join-Path $Inbox $name
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

function Invoke-GenesisUi([string]$ConfigPath) {
    $binding=Get-QuickHubBinding
    $target=[string]$binding.Path
    $current=if($StateLayoutActive){Join-Path $StateRoot 'baseline\Keelaryn__Hub_CURRENT.zip'}else{Join-Path $ManagerRoot 'Keelaryn__Hub_CURRENT.zip'}
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
        return Invoke-Manager @('-Genesis','-GenesisConfigPath',$full,'-GenesisConfirmed')
    }

    if($Action-ne'Menu'){
        Write-UiHost 'Direct Genesis requires -Path <config.json> and -ConfirmChanges.' -ForegroundColor Yellow
        Set-ActionSemantic 'cancelled'
        return 2
    }
    if((Test-Path -LiteralPath $target) -or (Test-Path -LiteralPath $current)){
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
        'RestoreCandidateTransport' { $count=if(Test-Path -LiteralPath $Inbox -PathType Container){@(Get-ChildItem -LiteralPath $Inbox -File -Filter 'Keelaryn__Hub_CANDIDATE_TRANSPORT_*.json' -ErrorAction SilentlyContinue).Count}else{0};if($count-eq0){Write-UiHost 'No Hub CANDIDATE transport is available. Nothing to restore.';Set-ActionSemantic 'no_changes';return 0};return Invoke-Manager @('-RestoreCandidateTransport') }
        'RepairCurrentTransport' { return Invoke-Manager @('-RepairCurrentTransport') }
        'CheckMigrations' { return Invoke-Manager @('-CheckMigrations') }
        'ApplyMigrations' { return Invoke-ApplyMigrationsUi }
        'BindInstance' { return Invoke-BindInstanceUi $ActionPath }
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

function Show-MaintenanceMenu {
    while($true){
        Clear-Ui
        $null=Show-QuickStatus
        Write-UiHost ''
        Write-UiHost 'Maintenance' -ForegroundColor Cyan
        Write-UiHost '  [1] Repair Hub CURRENT'
        Write-UiHost '  [2] Check migrations'
        Write-UiHost '  [3] Apply pending migrations'
        Write-UiHost '  [4] Bind existing Hub...'
        Write-UiHost '  [5] Open update inbox'
        Write-UiHost '  [6] Open logs'
        Write-UiHost '  [0] Back'
        $choice=(Read-UiInput 'Select').Trim()
        switch -Regex($choice){
            '^1$' {if(Confirm 'Run explicit CURRENT transport repair?'){$null=Invoke-MenuAction 'RepairCurrentTransport' $null 'Repair Hub CURRENT';Pause-Menu}}
            '^2$' {$null=Invoke-MenuAction 'CheckMigrations' $null 'Check migrations';Pause-Menu}
            '^3$' {$null=Invoke-MenuAction 'ApplyMigrations' $null 'Apply pending migrations';Pause-Menu}
            '^4$' {$null=Invoke-MenuAction 'BindInstance' $null 'Bind existing Hub';Pause-Menu}
            '^5$' {$null=Invoke-MenuAction 'OpenInbox' $null 'Open update inbox'}
            '^6$' {$null=Invoke-MenuAction 'OpenLogs' $null 'Open logs'}
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
        foreach($uiToken in @('function Invoke-MenuAction','function Invoke-FullGate','function Invoke-GenesisUi','GenesisConfigPath','GenesisConfirmed','-NonInteractive','[Enter] Back','product\runtime\Keelaryn__Manager.ps1')){
            if(-not$frontendSource.Contains($uiToken)){
                $script:FrontendSelfTestReason='Visible action-output contract missing token: '+$uiToken
                return $false
            }
        }
        if($frontendSource-match'(?m)^\s*\$null\s*=\s*Invoke-Action\b'){
            $script:FrontendSelfTestReason='Interactive menu still suppresses Invoke-Action output.'
            return $false
        }
        foreach($token in @('Keelaryn','Everyday','[2] Doctor','[5] Installation info','[7] Development','[0] Exit')){
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
