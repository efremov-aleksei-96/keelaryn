from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
TARGET = "4.13.0"
BASELINE = "4.12.0"
NEW_MANAGED_DOCS = [
    "product/docs/chatgpt-projects/CHAT_MANAGER_PROJECT_INSTRUCTIONS.md",
    "product/docs/chatgpt-projects/CHATS_PROJECT_INSTRUCTIONS.md",
    "product/docs/chatgpt-projects/MANAGER_DEVELOPMENT_PROJECT_INSTRUCTIONS.md",
    "product/docs/chatgpt-projects/SETUP_GUIDE.md",
    "product/docs/chatgpt-projects/WORKSPACE_PROJECT_INSTRUCTIONS.md",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_norm(path: Path):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if text.count("\r\n") > text.count("\n") / 2 else "\n"
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    return norm, newline, bom


def write_norm(path: Path, norm: str, newline="\n", bom=False):
    out = norm.replace("\n", newline)
    raw = out.encode("utf-8")
    if bom:
        raw = b"\xef\xbb\xbf" + raw
    path.write_bytes(raw)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one sentinel, found {count}")
    return text.replace(old, new, 1)


def manager_runtime_patch():
    path = ROOT / "manager/product/runtime/Keelaryn__Manager.ps1"
    text, newline, bom = read_norm(path)
    text = replace_once(text, '$ManagerVersion = "4.12.0"', '$ManagerVersion = "4.13.0"', "runtime version")

    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.strip().startswith("$ManagedManagerFiles")]
    if len(starts) != 1:
        raise RuntimeError(f"ManagedManagerFiles: expected one declaration, found {len(starts)}")
    start = starts[0]
    end = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == ")":
            end = i
            break
    if end is None:
        raise RuntimeError("ManagedManagerFiles closing parenthesis not found")
    body = lines[start:end]
    if not all(any(doc.replace("/", "\\") in line or doc in line for line in body) for doc in NEW_MANAGED_DOCS):
        marker_indexes = [i for i in range(start, end) if "product/docs/USER_INTERFACE.md" in lines[i] or "product\\docs\\USER_INTERFACE.md" in lines[i]]
        if len(marker_indexes) != 1:
            raise RuntimeError(f"ManagedManagerFiles USER_INTERFACE marker count={len(marker_indexes)}")
        marker = marker_indexes[0]
        sample = lines[marker]
        indent = sample[: len(sample) - len(sample.lstrip())]
        quote = "'" if "'" in sample else '"'
        sep = "\\" if "product\\docs" in sample else "/"
        inserted = [indent + quote + doc.replace("/", sep) + quote + "," for doc in NEW_MANAGED_DOCS]
        lines[marker + 1:marker + 1] = inserted
        text = "\n".join(lines)

    old_update = "Manager update command completed; no newer valid Manager package was applied. Keelaryn__Hub inbox was left untouched."
    new_update = "Manager update: no newer valid Manager package was found. The installed Manager remains unchanged; the Hub inbox was not processed by this Manager-only command."
    if old_update in text:
        text = replace_once(text, old_update, new_update, "Manager no-newer update wording")

    # Report legacy tests-workspace layout context for follow-up without mutating it blindly.
    for m in re.finditer(r"legacy-layout-backup", text):
        a = max(0, text.rfind("\n", 0, m.start() - 300))
        b = min(len(text), text.find("\n", m.end() + 300))
        print("RUNTIME_LEGACY_TEST_LAYOUT_CONTEXT:")
        print(text[a:b])

    write_norm(path, text, newline, bom)


def installation_patch():
    path = ROOT / "manager/product/install/INSTALLATION.json"
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if obj.get("manager_version") != BASELINE:
        raise RuntimeError(f"INSTALLATION baseline version mismatch: {obj.get('manager_version')}")
    obj["manager_version"] = TARGET
    managed = list(obj.get("managed_files") or [])
    if len(managed) != 61:
        raise RuntimeError(f"Expected 61 baseline managed files, found {len(managed)}")
    for doc in NEW_MANAGED_DOCS:
        if doc not in managed:
            idx = managed.index("product/docs/USER_INTERFACE.md") + 1
            managed.insert(idx, doc)
    if len(managed) != 66 or len(set(x.lower() for x in managed)) != 66:
        raise RuntimeError(f"Expected 66 unique 4.13 managed files, found {len(managed)}")
    obj["managed_files"] = managed
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def manager_release_patch():
    path = ROOT / "manager/product/manager_release.json"
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if obj.get("manager_version") != BASELINE:
        raise RuntimeError(f"manager_release baseline mismatch: {obj.get('manager_version')}")
    obj["manager_version"] = TARGET
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def readme_patch():
    content = """# Keelaryn Manager 4.13.0

Manager 4.13.0 is the grouped post-4.12 development cycle for supported ChatGPT exchange/onboarding and development-workspace hygiene. It preserves Hub schemas, native update compatibility, rollback semantics, deterministic release construction and fail-closed validation boundaries unless a separately qualified change explicitly says otherwise.

The immutable development baseline is Manager 4.12.0. Gate Framework 2.0 r11 remains the reusable framework for this candidate unless reusable framework source actually changes.

## Canonical installed layout

```text
keelaryn/
├── Keelaryn.cmd
├── manager/
│   ├── KEELARYN.cmd
│   ├── README_FIRST.md
│   ├── product/
│   ├── compat/
│   │   └── commands/
│   └── state/
│       ├── baseline/
│       ├── inbox/
│       ├── logs/
│       ├── history/
│       ├── releases/
│       ├── work/
│       ├── binding.json          (when bound)
│       └── layout.json
├── hub/
├── tests/
└── exchange/
    └── chatgpt/
```

`exchange/chatgpt` is user-facing exchange state, not Manager runtime state and not canonical Hub state.

## ChatGPT architecture

The complete Standard setup for a normal user is:

```text
Keelaryn — Workspace
Keelaryn — Chats
Keelaryn — Chat Manager
```

`Keelaryn — Manager Development` is optional and is only for contributors/system-level Keelaryn development.

Manager ships authoritative copy-ready Project instruction templates under:

```text
manager/product/docs/chatgpt-projects
```

The supported artifact flow is:

```text
CURRENT
  -> Workspace
  -> WORKSPACE_CHECKOUT
  -> Chats
  -> HUB_RETURN / HUB_RETURN_INTERIM
  -> Chat Manager
  -> APPROVED
  -> local Manager
  -> next CURRENT
```

The Manager frontend can prepare CURRENT for Workspace or Chat Manager and opens the supported exchange location. Legacy `Inputs_outputs` migration is copy-only, rejects reparse points, verifies copied bytes with SHA-256 and never deletes the source automatically.

## Development workspace hygiene

The intended tests lifecycle distinguishes current reusable framework source, disposable work, active/current expanded results and frozen archives. Disposable `tests/work` cleanup is explicit, dry-run first, reparse-safe and file-granular so temporary Windows directory locks do not become data-integrity failures.

`manager/state/history` remains protected from generic cleanup. Existing release-bundle retention already validates and archives reproducible Manager release bundles; 4.13 does not introduce a second competing release-retention policy.

## Update compatibility

Manager 4.13.0 preserves the native update compatibility floor in `product/manager_release.json`. UPDATE artifacts retain the established transition envelope used by supported older Manager validators.

Manager-only update commands clearly distinguish "no newer valid package" from failure and do not silently process Hub updates.

## User interface compatibility

Use `keelaryn\\Keelaryn.cmd` or `manager\\KEELARYN.cmd`.

The existing numeric main-menu contract is preserved to avoid breaking established Windows gate orchestration. ChatGPT is added as a separate lettered entry. Existing first-run Create, Connect and Main-menu choices keep their numeric meaning; ChatGPT setup is an additional optional path and remains reopenable later.

## Release gate

This source is not production-approved merely because it carries version 4.13.0. Production approval still requires the applicable Windows PowerShell 5.1 parser/static checks, Manager and frontend SelfTests, deterministic release/package checks, CURRENT-backed disposable 4.12.0 -> 4.13.0 native update, rollback/fault injection, migrations, Doctor, production immutability, UI regression coverage, public PR CI, exact tested/PR/post-merge/release artifact identity and gated publication.
"""
    (ROOT / "manager/README_FIRST.md").write_text(content, encoding="utf-8", newline="\n")


def menu_patch():
    path = ROOT / "manager/product/tools/KeelarynMenu.ps1"
    text, newline, bom = read_norm(path)

    text = replace_once(
        text,
        "        'MigrateInstanceIdentity','MigrateLegacyNamespace','MigrateLayout','FinalizeLayout','FinalizeFilesystemLayout',\n        'OpenInbox','OpenLogs','OpenReleases','OpenTestsWork','OpenTestsResults','OpenCompatCommands','OpenKeelarynRoot',",
        "        'MigrateInstanceIdentity','MigrateLegacyNamespace','MigrateLayout','FinalizeLayout','FinalizeFilesystemLayout',\n        'PrepareWorkspaceSession','PrepareChatManagerSession','OpenChatGPTExchange','OpenChatGPTGuide','ImportLegacyExchange',\n        'StorageReport','CleanTestsWork',\n        'OpenInbox','OpenLogs','OpenReleases','OpenTestsWork','OpenTestsResults','OpenCompatCommands','OpenKeelarynRoot',",
        "frontend action ValidateSet",
    )

    text = replace_once(
        text,
        "        '  [8] Advanced',\n        '  [9] Open Keelaryn folder',\n        '  [0] Exit'",
        "        '  [8] Advanced',\n        '  [9] Open Keelaryn folder',\n        '  [C] ChatGPT',\n        '  [0] Exit'",
        "main menu ChatGPT contract",
    )

    text = replace_once(
        text,
        "$TestsRoot=Join-Path $LayoutRoot 'tests'\n$CompatCommands=Join-Path $ManagerRoot 'compat\\commands'",
        "$TestsRoot=Join-Path $LayoutRoot 'tests'\n$CompatCommands=Join-Path $ManagerRoot 'compat\\commands'\n$ExchangeParent=Join-Path $LayoutRoot 'exchange'\n$ExchangeRoot=Join-Path $ExchangeParent 'chatgpt'\n$LegacyExchangeRoot=Join-Path $LayoutRoot 'Inputs_outputs'\n$ChatGPTDocsRoot=Join-Path $ManagerRoot 'product\\docs\\chatgpt-projects'",
        "frontend exchange paths",
    )

    text = replace_once(
        text,
        "$allowed=@('manager','hub','tests','Keelaryn.cmd')",
        "$allowed=@('manager','hub','tests','exchange','Inputs_outputs','Keelaryn.cmd')",
        "root workspace allowlist",
    )
    text = replace_once(
        text,
        "$allowedTests=@('work','results','legacy-layout-backup','WORKSPACE.json')",
        "$allowedTests=@('framework','work','results','archives','legacy-layout-backup','WORKSPACE.json')",
        "tests workspace allowlist",
    )

    helpers = r'''Refresh-FrontendOperationalPaths

function Get-ChatGPTExchangeDirectoryNames {
    return @('workspace-input','workspace-checkouts','chat-returns','chat-manager-input','chat-manager-results','development')
}

function Ensure-ChatGPTExchangeLayout {
    Ensure-DirectorySafe $ExchangeParent 'Keelaryn exchange root'
    Ensure-DirectorySafe $ExchangeRoot 'ChatGPT exchange root'
    foreach($name in @(Get-ChatGPTExchangeDirectoryNames)){
        Ensure-DirectorySafe (Join-Path $ExchangeRoot $name) ('ChatGPT exchange '+$name)
    }
}

function Get-CurrentHubTransportPath {
    $path=if($StateLayoutActive){Join-Path $StateRoot 'baseline\Keelaryn__Hub_CURRENT.zip'}else{Join-Path $ManagerRoot 'Keelaryn__Hub_CURRENT.zip'}
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
    if(-not($targetFull.Equals($baseFull,[System.StringComparison]::OrdinalIgnoreCase))-and-not($targetFull.StartsWith(($baseFull+'\'),[System.StringComparison]::OrdinalIgnoreCase))){Fail('Destination escaped its allowed root: '+$targetFull)}
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

function Read-ManagerVersion'''
    text = replace_once(text, "Refresh-FrontendOperationalPaths\n\nfunction Read-ManagerVersion", helpers, "frontend helper insertion")

    text = replace_once(
        text,
        "        'RestoreCandidateTransport' { $count=if(Test-Path -LiteralPath $Inbox -PathType Container){@(Get-ChildItem -LiteralPath $Inbox -File -Filter 'Keelaryn__Hub_CANDIDATE_TRANSPORT_*.json' -ErrorAction SilentlyContinue).Count}else{0};if($count-eq0){Write-UiHost 'No Hub CANDIDATE transport is available. Nothing to restore.';Set-ActionSemantic 'no_changes';return 0};return Invoke-Manager @('-RestoreCandidateTransport') }\n        'RepairCurrentTransport' { return Invoke-Manager @('-RepairCurrentTransport') }",
        "        'RestoreCandidateTransport' { $count=if(Test-Path -LiteralPath $Inbox -PathType Container){@(Get-ChildItem -LiteralPath $Inbox -File -Filter 'Keelaryn__Hub_CANDIDATE_TRANSPORT_*.json' -ErrorAction SilentlyContinue).Count}else{0};if($count-eq0){Write-UiHost 'No Hub CANDIDATE transport is available. Nothing to restore.';Set-ActionSemantic 'no_changes';return 0};return Invoke-Manager @('-RestoreCandidateTransport') }\n        'PrepareWorkspaceSession' { return Copy-CurrentForChatGPT (Join-Path $ExchangeRoot 'workspace-input') }\n        'PrepareChatManagerSession' { return Copy-CurrentForChatGPT (Join-Path $ExchangeRoot 'chat-manager-input') }\n        'OpenChatGPTExchange' { Ensure-ChatGPTExchangeLayout; return Open-Folder $ExchangeRoot }\n        'OpenChatGPTGuide' { return Open-ChatGPTGuide }\n        'ImportLegacyExchange' { return Invoke-LegacyExchangeMigration -Apply:$ConfirmChanges }\n        'StorageReport' { return Show-StorageReport }\n        'CleanTestsWork' { return Invoke-CleanTestsWork -Apply:$ConfirmChanges }\n        'RepairCurrentTransport' { return Invoke-Manager @('-RepairCurrentTransport') }",
        "frontend ChatGPT/maintenance action routing",
    )

    chat_menus = r'''function Show-ChatGPTSetupMenu {
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

function Show-MaintenanceMenu'''
    text = replace_once(text, "function Show-MaintenanceMenu", chat_menus, "ChatGPT menu insertion")

    text = replace_once(
        text,
        "        Write-UiHost '  [5] Open update inbox'\n        Write-UiHost '  [6] Open logs'\n        Write-UiHost '  [0] Back'",
        "        Write-UiHost '  [5] Open update inbox'\n        Write-UiHost '  [6] Open logs'\n        Write-UiHost '  [7] Storage report'\n        Write-UiHost '  [8] Clean disposable test work...'\n        Write-UiHost '  [0] Back'",
        "maintenance menu additions",
    )
    text = replace_once(
        text,
        "            '^5$' {$null=Invoke-MenuAction 'OpenInbox' $null 'Open update inbox'}\n            '^6$' {$null=Invoke-MenuAction 'OpenLogs' $null 'Open logs'}\n            '^0$' {return}",
        "            '^5$' {$null=Invoke-MenuAction 'OpenInbox' $null 'Open update inbox'}\n            '^6$' {$null=Invoke-MenuAction 'OpenLogs' $null 'Open logs'}\n            '^7$' {$null=Invoke-MenuAction 'StorageReport' $null 'Storage report';Pause-Menu}\n            '^8$' {\n                $null=Invoke-CleanTestsWork\n                if(Confirm 'Delete the listed disposable tests\\work contents?'){$null=Invoke-CleanTestsWork -Apply}\n                Pause-Menu\n            }\n            '^0$' {return}",
        "maintenance routing additions",
    )

    text = replace_once(
        text,
        "        Write-UiHost '  [1] Open Hub'\n        Write-UiHost '  [2] Main menu'\n        $choice=(Read-UiInput 'Select').Trim()\n        if($choice-eq'1'){$null=Invoke-Action 'OpenHub' $null}\n        return",
        "        Write-UiHost '  [1] Open Hub'\n        Write-UiHost '  [2] Main menu'\n        Write-UiHost '  [3] Set up ChatGPT...'\n        $choice=(Read-UiInput 'Select').Trim()\n        if($choice-eq'1'){$null=Invoke-Action 'OpenHub' $null}\n        elseif($choice-eq'3'){Show-ChatGPTSetupMenu}\n        return",
        "first-run optional ChatGPT setup",
    )

    text = replace_once(
        text,
        "            '9' {$null=Invoke-MenuAction 'OpenKeelarynRoot' $null 'Open Keelaryn folder'}\n            '0' {return 0}",
        "            '9' {$null=Invoke-MenuAction 'OpenKeelarynRoot' $null 'Open Keelaryn folder'}\n            {$_-match'^(?i)c$'} {Show-ChatGPTMenu}\n            '0' {return 0}",
        "main menu ChatGPT routing",
    )

    text = replace_once(
        text,
        "foreach($uiToken in @('function Invoke-MenuAction','function Invoke-FullGate','function Invoke-GenesisUi','function Show-FirstRunWizard','function Resolve-StartupDisposition','function Refresh-FrontendOperationalPaths','Show-SetupCompletion','GenesisConfigPath','GenesisConfirmed','-NonInteractive','[Enter] Back','product\\runtime\\Keelaryn__Manager.ps1'))",
        "foreach($uiToken in @('function Invoke-MenuAction','function Invoke-FullGate','function Invoke-GenesisUi','function Show-FirstRunWizard','function Resolve-StartupDisposition','function Refresh-FrontendOperationalPaths','function Show-ChatGPTMenu','function Ensure-ChatGPTExchangeLayout','function Invoke-LegacyExchangeMigration','function Invoke-CleanTestsWork','Show-SetupCompletion','GenesisConfigPath','GenesisConfirmed','-NonInteractive','[Enter] Back','product\\runtime\\Keelaryn__Manager.ps1'))",
        "frontend self-test source tokens",
    )
    text = replace_once(
        text,
        "foreach($token in @('Keelaryn','Everyday','[2] Doctor','[5] Installation info','[7] Development','[0] Exit'))",
        "foreach($token in @('Keelaryn','Everyday','[2] Doctor','[5] Installation info','[7] Development','[C] ChatGPT','[0] Exit'))",
        "frontend self-test menu tokens",
    )

    write_norm(path, text, newline, bom)


def public_metadata_patch():
    install_path = ROOT / "manager/product/install/INSTALLATION.json"
    install = json.loads(install_path.read_text(encoding="utf-8"))
    managed = list(install["managed_files"])
    rows = []
    digest_rows = []
    for rel in sorted(managed):
        p = ROOT / "manager" / rel
        data = p.read_bytes()
        h = sha256_bytes(data)
        rows.append({"path": rel, "size_bytes": len(data), "sha256": h})
        digest_rows.append(rel.replace("\\", "/") + "\x00" + h)
    managed_digest = sha256_bytes("\n".join(digest_rows).encode("utf-8"))
    install_sha = sha256_file(install_path)

    manifest_path = ROOT / "PUBLIC_FILE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["manager"] = {
        "version": TARGET,
        "file_count": len(managed),
        "installation_sha256": install_sha,
        "gate_managed_content_sha256": managed_digest,
        "files": rows,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    prov_path = ROOT / "PUBLIC_PROVENANCE.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8-sig"))
    prov["role"] = "public_source_sync_candidate"
    prov["source_manager_version"] = TARGET
    prov["source_gate_baseline_manager_version"] = BASELINE
    prov["source_manager_installation_sha256"] = install_sha
    prov["source_manager_gate_managed_content_sha256"] = managed_digest
    prov["production_validation"] = {
        "full_gate_pass": False,
        "gate_revision": None,
        "framework_revision": 11,
        "production_doctor_pass": False,
        "production_ux_smoke_pass": False,
        "production_managed_content_prefix": None,
    }
    prov["public_candidate_revision"] = 1
    prov["gate_framework"] = {
        "version": "2.0",
        "revision": 11,
        "windows_qualified": True,
        "frozen_for_manager_candidate": True,
    }
    prov["known_nonsecret_source_hygiene_notes"] = [
        "manager/product/docs/TESTING.md retains a maintainer-local D:\\0\\0__Core example for historical/maintainer testing context; it is not a product installation default."
    ]
    prov["known_nonsecret_hygiene_notes"] = [
        "manager/product/docs/TESTING.md and tests/framework/manager-gate/README.md retain maintainer-local D:\\0\\0__Core examples; they are not product defaults."
    ]
    prov_path.write_text(json.dumps(prov, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    print(f"INSTALLATION_SHA256={install_sha}")
    print(f"MANAGED_CONTENT_SHA256={managed_digest}")
    print(f"MANAGED_FILES={len(managed)}")


def verify_ascii_executables():
    install = json.loads((ROOT / "manager/product/install/INSTALLATION.json").read_text(encoding="utf-8"))
    for rel in install["managed_files"]:
        if Path(rel).suffix.lower() in {".ps1", ".cmd"}:
            data = (ROOT / "manager" / rel).read_bytes()
            if any(b >= 128 for b in data):
                raise RuntimeError(f"Non-ASCII executable source after patch: manager/{rel}")


def main():
    required_docs = [ROOT / "manager" / p for p in NEW_MANAGED_DOCS]
    for p in required_docs:
        if not p.is_file():
            raise RuntimeError(f"Missing new ChatGPT managed doc: {p}")
    installation_patch()
    manager_release_patch()
    manager_runtime_patch()
    readme_patch()
    menu_patch()
    verify_ascii_executables()
    public_metadata_patch()
    print("MANAGER_4_13_BOOTSTRAP_PATCH=PASS")


if __name__ == "__main__":
    main()
