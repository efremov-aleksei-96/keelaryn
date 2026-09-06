from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
TOOL_REL = "product/tools/Compact-KeelarynQualificationEvidence.ps1"


def read_norm(path: Path):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    nl = "\r\n" if text.count("\r\n") > text.count("\n") / 2 else "\n"
    return text.replace("\r\n", "\n").replace("\r", "\n"), nl, bom


def write_norm(path: Path, text: str, nl="\n", bom=False):
    raw = text.replace("\n", nl).encode("utf-8")
    if bom:
        raw = b"\xef\xbb\xbf" + raw
    path.write_bytes(raw)


def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one sentinel, found {n}")
    return text.replace(old, new, 1)


def sha_file(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(text: str):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def patch_installation():
    path = ROOT / "manager/product/install/INSTALLATION.json"
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    managed = list(obj["managed_files"])
    if len(managed) != 66:
        raise RuntimeError(f"Expected 66 managed files before lifecycle patch, found {len(managed)}")
    if TOOL_REL not in managed:
        idx = managed.index("product/tools/KeelarynMenu.ps1") + 1
        managed.insert(idx, TOOL_REL)
    if len(managed) != 67 or len({x.lower() for x in managed}) != 67:
        raise RuntimeError("Lifecycle managed-set count/uniqueness mismatch")
    obj["managed_files"] = managed
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def patch_runtime():
    path = ROOT / "manager/product/runtime/Keelaryn__Manager.ps1"
    text, nl, bom = read_norm(path)

    marker = "    'product/tools/KeelarynMenu.ps1',"
    if "Compact-KeelarynQualificationEvidence.ps1" not in text:
        text = replace_once(text, marker, marker + "\n    'product/tools/Compact-KeelarynQualificationEvidence.ps1',", "runtime managed tool")

    start = text.index("function Initialize-TestsWorkspaceAt")
    end = text.index("$script:UserInterfaceToolSourceSelfTestReason=''", start)
    workspace_block = r'''function Initialize-TestsWorkspaceAt([string]$TestsPath,[bool]$WriteMetadata=$true) {
    $tests=[System.IO.Path]::GetFullPath($TestsPath).TrimEnd('\')
    if (-not (Test-Path -LiteralPath $tests)) { New-Item -ItemType Directory -Force -Path $tests | Out-Null }
    Assert-TestsWorkspaceDirectorySafe $tests 'Keelaryn tests root'
    $framework=Join-Path $tests 'framework';$work=Join-Path $tests 'work';$results=Join-Path $tests 'results';$archives=Join-Path $tests 'archives';$legacy=Join-Path $tests 'legacy-layout-backup'
    foreach($row in @(
        @($framework,'Keelaryn tests framework root'),
        @($work,'Keelaryn tests work root'),
        @($results,'Keelaryn tests results root'),
        @($archives,'Keelaryn tests archives root')
    )){
        $path=[string]$row[0];$purpose=[string]$row[1]
        if (-not (Test-Path -LiteralPath $path)) { New-Item -ItemType Directory -Force -Path $path | Out-Null }
        Assert-TestsWorkspaceDirectorySafe $path $purpose
    }
    if (Test-Path -LiteralPath $legacy) { Assert-TestsWorkspaceDirectorySafe $legacy 'Keelaryn legacy-layout backup root' }
    $allowed=@('framework','work','results','archives','legacy-layout-backup','WORKSPACE.json')
    $unclassified=@(Get-ChildItem -LiteralPath $tests -Force | Where-Object { $allowed -notcontains $_.Name } | Sort-Object Name | ForEach-Object { $_.Name })
    if($WriteMetadata){
        $meta=[ordered]@{
            schema='keelaryn.tests.workspace.v2';manager_version=$ManagerVersion;tests_path=$tests;
            framework='framework';work='work';results='results';archives='archives';legacy_layout_backup='legacy-layout-backup';
            framework_policy='one current reusable framework source; never historical qualification expansion';
            work_policy='ephemeral candidate/disposable runtime only; normally empty between cycles';
            results_policy='active/current expanded evidence plus concise qualification indexes; not permanent raw-history storage';
            archives_policy='frozen verified historical evidence bundles with manifests and SHA-256 provenance';
            generated_fixtures_policy='generate inside work and remove with the run';
            rejected_policy='retain concise rejection/root-cause provenance; raw evidence only as a verified archive when durable value exists';
            unclassified_top_level=@($unclassified);updated=(Get-Date).ToUniversalTime().ToString('o')
        }
        $json=($meta|ConvertTo-Json -Depth 6).Replace("`r`n","`n")+"`n"
        [System.IO.File]::WriteAllText((Join-Path $tests 'WORKSPACE.json'),$json,(New-Object System.Text.UTF8Encoding($false)))
    }
    return [pscustomobject]@{Tests=$tests;Framework=$framework;Work=$work;Results=$results;Archives=$archives;LegacyLayoutBackup=$legacy;Unclassified=@($unclassified)}
}

function Invoke-PrepareTests {
    if (-not $CanonicalLayoutActive) { throw 'PREPARE_TESTS requires the canonical keelaryn/manager installation layout.' }
    $workspace=Initialize-TestsWorkspaceAt $CanonicalTestsPath $true
    Write-Host 'Keelaryn tests workspace ready.' -ForegroundColor Green
    Write-Host ('framework: '+$workspace.Framework)
    Write-Host ('work: '+$workspace.Work)
    Write-Host ('results: '+$workspace.Results)
    Write-Host ('archives: '+$workspace.Archives)
    Write-Host ('legacy-layout-backup: '+$workspace.LegacyLayoutBackup+' (created only by explicit legacy layout finalization)')
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
        foreach($dir in @($ws.Framework,$ws.Work,$ws.Results,$ws.Archives)){if(-not(Test-Path -LiteralPath $dir -PathType Container)){return $false}}
        if(Test-Path -LiteralPath $ws.LegacyLayoutBackup){return $false}
        if(@($ws.Unclassified)-notcontains'manager-old'){return $false}
        $meta=Read-KeelarynJsonFile (Join-Path $temp 'WORKSPACE.json')
        if([string]$meta.schema-ne'keelaryn.tests.workspace.v2'-or[string]$meta.framework-ne'framework'-or[string]$meta.work-ne'work'-or[string]$meta.results-ne'results'-or[string]$meta.archives-ne'archives'){return $false}
        if([string]$meta.results_policy-notmatch'not permanent raw-history'-or[string]$meta.archives_policy-notmatch'frozen verified'){return $false}
        return $true
    }
    catch{return $false}
    finally{if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}}
}

function Test-QualificationEvidenceCompactionToolSelfTest {
    try{
        $tool=Join-Path $Root 'product/tools/Compact-KeelarynQualificationEvidence.ps1'
        if(-not(Test-Path -LiteralPath $tool -PathType Leaf)){return $false}
        & (Join-Path $PSHOME 'powershell.exe') -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $tool -SelfTest | Out-Null
        return [int]$LASTEXITCODE -eq 0
    }catch{return $false}
}

'''
    text = text[:start] + workspace_block + text[end:]

    text = replace_once(
        text,
        "foreach($rel in @('product/tools/KeelarynMenu.ps1','product/tools/Unpack-KeelarynTestArchive.ps1'))",
        "foreach($rel in @('product/tools/KeelarynMenu.ps1','product/tools/Unpack-KeelarynTestArchive.ps1','product/tools/Compact-KeelarynQualificationEvidence.ps1'))",
        "runtime UI tool source set",
    )
    text = replace_once(
        text,
        "foreach($requiredAction in @('ImportPackage','UnpackTest','RunFullGate','Genesis','BuildRelease','EnsureRootLauncher','OpenCompatCommands','Doctor','UpdateAll','RenderMain'))",
        "foreach($requiredAction in @('ImportPackage','UnpackTest','RunFullGate','CompactQualificationEvidence','Genesis','BuildRelease','EnsureRootLauncher','OpenCompatCommands','Doctor','UpdateAll','RenderMain'))",
        "runtime required frontend action",
    )
    text = replace_once(
        text,
        "    if (-not (Test-TestsWorkspaceSelfTest)) { Write-Host 'Manager self-test failed: tests workspace contract.' -ForegroundColor Red; exit 1 }\n    if (-not (Test-UserInterfaceToolSourceSelfTest))",
        "    if (-not (Test-TestsWorkspaceSelfTest)) { Write-Host 'Manager self-test failed: tests workspace contract.' -ForegroundColor Red; exit 1 }\n    if (-not (Test-QualificationEvidenceCompactionToolSelfTest)) { Write-Host 'Manager self-test failed: qualification evidence compaction contract.' -ForegroundColor Red; exit 1 }\n    if (-not (Test-UserInterfaceToolSourceSelfTest))",
        "runtime qualification tool SelfTest call",
    )
    write_norm(path, text, nl, bom)


def patch_menu():
    path = ROOT / "manager/product/tools/KeelarynMenu.ps1"
    text, nl, bom = read_norm(path)
    text = replace_once(text, "        'StorageReport','CleanTestsWork',", "        'StorageReport','CleanTestsWork','CompactQualificationEvidence',", "menu ValidateSet")
    text = replace_once(text, "$ChatGPTDocsRoot=Join-Path $ManagerRoot 'product\\docs\\chatgpt-projects'", "$ChatGPTDocsRoot=Join-Path $ManagerRoot 'product\\docs\\chatgpt-projects'\n$QualificationCompactionTool=Join-Path $PSScriptRoot 'Compact-KeelarynQualificationEvidence.ps1'", "menu compaction tool path")

    insert_at = text.index("function Invoke-ApplyMigrationsUi")
    helper = r'''function Invoke-QualificationCompactor([string]$TargetPath,[bool]$DoApply=$false) {
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

'''
    text = text[:insert_at] + helper + text[insert_at:]
    text = replace_once(text, "        'CleanTestsWork' { return Invoke-CleanTestsWork -Apply:$ConfirmChanges }", "        'CleanTestsWork' { return Invoke-CleanTestsWork -Apply:$ConfirmChanges }\n        'CompactQualificationEvidence' { return Invoke-QualificationCompactor $ActionPath ([bool]$ConfirmChanges) }", "menu compaction action")
    text = replace_once(text, "        Write-UiHost '  [8] Clean disposable test work...'\n        Write-UiHost '  [0] Back'", "        Write-UiHost '  [8] Clean disposable test work...'\n        Write-UiHost '  [9] Compact completed qualification evidence...'\n        Write-UiHost '  [0] Back'", "maintenance compaction menu")
    text = replace_once(
        text,
        "            '^8$' {\n                $null=Invoke-CleanTestsWork\n                if(Confirm 'Delete the listed disposable tests\\work contents?'){$null=Invoke-CleanTestsWork -Apply}\n                Pause-Menu\n            }\n            '^0$' {return}",
        "            '^8$' {\n                $null=Invoke-CleanTestsWork\n                if(Confirm 'Delete the listed disposable tests\\work contents?'){$null=Invoke-CleanTestsWork -Apply}\n                Pause-Menu\n            }\n            '^9$' {\n                $target=Select-Folder 'Select completed qualification results directory' (Join-Path $TestsRoot 'results')\n                if($target){\n                    $rc=Invoke-QualificationCompactor $target $false\n                    if($rc-eq0-and(Confirm 'Archive, SHA-256 verify and compact this completed qualification evidence?')){$null=Invoke-QualificationCompactor $target $true}\n                }\n                Pause-Menu\n            }\n            '^0$' {return}",
        "maintenance compaction routing",
    )
    text = replace_once(
        text,
        "'function Invoke-LegacyExchangeMigration','function Invoke-CleanTestsWork','Show-SetupCompletion'",
        "'function Invoke-LegacyExchangeMigration','function Invoke-CleanTestsWork','function Invoke-QualificationCompactor','Show-SetupCompletion'",
        "frontend source tokens",
    )
    write_norm(path, text, nl, bom)


def patch_docs():
    testing = ROOT / "manager/product/docs/TESTING.md"
    testing.write_text("""# Keelaryn development tests workspace

The canonical local development root is `keelaryn/tests`.

```text
tests/
├── framework/
│   └── manager-gate/       # one current reusable framework source
├── work/                    # disposable active candidate/runtime state
├── results/                 # active/current expanded evidence + concise indexes
├── archives/                # frozen verified historical evidence
└── legacy-layout-backup/    # compatibility evidence only when legacy layout finalization requires it
```

`work/` is disposable and should normally be empty between development cycles. Candidate packs, temporary Hub copies, generated fixtures, fault-injection targets and benchmark runtimes belong below it.

`results/` is not permanent raw-history storage. Expanded gate evidence is valid while qualification is active and while a verdict is being investigated. A completed qualification may be compacted to `archives/`, leaving a concise `QUALIFICATION_INDEX.json` under the result root.

`archives/` stores frozen evidence ZIPs plus per-entry manifests. Compaction reopens the archive and verifies every entry by SHA-256 before expanded source evidence is eligible for cleanup. Cleanup is file-granular with bounded retries; a verified archive plus an empty-but-temporarily-locked directory is reported as pending cleanup rather than a data-integrity failure.

Reparse-point directories and file reparse points are rejected by automatic qualification compaction. The tool never follows them. A future substitution mechanism may only use an explicitly protected non-reparse counterpart bound by exact size and SHA-256 and must record substitution provenance.

Unknown or unclassified top-level test entries are never moved or deleted automatically. `manager/state/history` is outside tests compaction scope and remains protected by its rollback/migration retention policy.

## Manager gate archive

Windows Manager gate ZIPs are named exactly:

```text
manager-<version>.zip
```

The external/manual entrypoint remains:

```text
D:\\0\\0__Core\\keelaryn\\tests\\UNPACK_MANAGER_GATE.cmd
```

Manager UI also exposes Development > Run Full Gate. Both workflows use the same `product/tools/Unpack-KeelarynTestArchive.ps1` validation/unpack contract rather than independent extraction implementations.

## Test archive safety

`Unpack-KeelarynTestArchive.ps1` validates archive naming, path traversal, reserved Windows names, case-insensitive collisions, symlink-like entries and size limits. It extracts through staging and publishes atomically into `tests/work/<archive-name>`.

`-PlanOnly` resolves the validated archive kind/version/destination without extraction. `-NonInteractive` prohibits overwrite prompting. If a destination exists and replacement was not explicitly authorized, the non-interactive backend exits without replacing it. This lets Manager UI own the visible confirmation boundary and prevents hidden child prompts behind redirected stdout.

## Full Gate boundary

The Full Gate may read the current production Manager, Hub and CURRENT baseline for preflight/immutability evidence, but it must not execute production Manager/tool paths or use the personal live Hub as a mutable development target.

Mutable test installation, update, migration, rollback, Genesis, candidate-transport and archive fixtures are disposable and remain under `tests`. A CURRENT-backed Hub copy is used when production-compatible Hub behavior must be exercised.

Production approval requires a complete PASS summary. A failed/rejected candidate retains a concise root-cause/provenance record; raw evidence is frozen only when it has durable value.

## Qualification closing

`product/tools/Compact-KeelarynQualificationEvidence.ps1` accepts only a completed `tests/results/.../GATE_SUMMARY.json`. Default execution is a dry run. Commit mode:

1. inventories exact paths/file count/bytes and rejects reparse points;
2. hashes every source file;
3. writes a frozen evidence manifest with original attributes/timestamps;
4. builds the evidence ZIP;
5. reopens the ZIP and verifies every entry by size and SHA-256;
6. publishes archive/manifest identities;
7. writes a concise qualification index;
8. deletes expanded evidence file-by-file with bounded retries;
9. records pending locked files/directories for idempotent retry.

Archive verification precedes any source deletion.

## Gate Framework v2

Repository `tests/framework/manager-gate` owns the reusable Manager gate harness source. A generated gate carries `gate/GATE_SPEC.json` with candidate version, expected production baseline, gate revision, canonical INSTALLATION SHA-256, managed-content digest and managed-file count. Full Gate validates that binding before substantive candidate checks. Gate-only revisions may change harness bytes only when the bound managed-content digest remains unchanged.

Deterministic BUILD_RELEASE validation uses two isolated clean Manager build roots and compares independent release hashes. The second build does not overwrite the first build's release ZIPs, avoiding false failures caused by external indexers or synchronizers briefly locking build-A artifacts.
""", encoding="utf-8", newline="\n")

    ui = ROOT / "manager/product/docs/USER_INTERFACE.md"
    text = ui.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    text = replace_once(text, "Repair Hub CURRENT, check/apply migrations, bind an existing Hub, open update inbox and logs. Ordinary update actions are not duplicated here.", "Repair Hub CURRENT, check/apply migrations, bind an existing Hub, open update inbox/logs, show a storage report, clean disposable test work and compact completed qualification evidence. Ordinary update actions are not duplicated here.", "UI maintenance docs")
    text = replace_once(text, "Zero pending migrations are a no-op and require no confirmation. When an applicable migration exists, the frontend shows the plan before commit. Binding shows both current and proposed Hub paths before confirmation.", "Zero pending migrations are a no-op and require no confirmation. When an applicable migration exists, the frontend shows the plan before commit. Binding shows both current and proposed Hub paths before confirmation. Storage/destructive maintenance actions are dry-run first. Qualification compaction verifies the frozen archive before expanded evidence cleanup and never targets Manager rollback history.", "UI maintenance safety docs")
    ui.write_text(text, encoding="utf-8", newline="\n")

    readme = ROOT / "manager/README_FIRST.md"
    text = readme.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    old = "The intended tests lifecycle distinguishes current reusable framework source, disposable work, active/current expanded results and frozen archives. Disposable `tests/work` cleanup is explicit, dry-run first, reparse-safe and file-granular so temporary Windows directory locks do not become data-integrity failures."
    new = "The tests workspace contract is now explicit: `framework` holds one current reusable framework source, `work` is disposable, `results` holds active/current expanded evidence plus concise qualification indexes, and `archives` holds frozen verified history. Disposable `tests/work` cleanup is explicit, dry-run first, reparse-safe and file-granular. Completed Full Gate evidence can be compacted to a per-entry SHA-256-verified archive before expanded source cleanup; temporary empty-directory locks remain a cleanup state rather than a data-integrity failure."
    text = replace_once(text, old, new, "README tests lifecycle")
    readme.write_text(text, encoding="utf-8", newline="\n")


def update_public_metadata():
    install_path = ROOT / "manager/product/install/INSTALLATION.json"
    install = json.loads(install_path.read_text(encoding="utf-8"))
    managed = list(install["managed_files"])
    rows = []
    digest_rows = []
    for rel in sorted(managed):
        p = ROOT / "manager" / rel
        data = p.read_bytes()
        h = hashlib.sha256(data).hexdigest()
        rows.append({"path": rel, "size_bytes": len(data), "sha256": h})
        digest_rows.append(rel.replace("\\", "/") + "\x00" + h)
    managed_digest = hashlib.sha256("\n".join(digest_rows).encode("utf-8")).hexdigest()
    install_sha = sha_file(install_path)

    manifest_path = ROOT / "PUBLIC_FILE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["manager"] = {"version": "4.13.0", "file_count": len(managed), "installation_sha256": install_sha, "gate_managed_content_sha256": managed_digest, "files": rows}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    prov_path = ROOT / "PUBLIC_PROVENANCE.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8-sig"))
    prov["source_manager_installation_sha256"] = install_sha
    prov["source_manager_gate_managed_content_sha256"] = managed_digest
    prov["public_candidate_revision"] = 2
    prov_path.write_text(json.dumps(prov, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"INSTALLATION_SHA256={install_sha}")
    print(f"MANAGED_CONTENT_SHA256={managed_digest}")
    print(f"MANAGED_FILES={len(managed)}")


def verify_ascii_managed_executables():
    install = json.loads((ROOT / "manager/product/install/INSTALLATION.json").read_text(encoding="utf-8"))
    for rel in install["managed_files"]:
        if Path(rel).suffix.lower() in {".ps1", ".cmd"}:
            data = (ROOT / "manager" / rel).read_bytes()
            if any(b >= 128 for b in data):
                raise RuntimeError(f"Non-ASCII managed executable: {rel}")


def main():
    if not (ROOT / "manager" / TOOL_REL).is_file():
        raise RuntimeError("Qualification compaction tool is missing before lifecycle patch")
    patch_installation()
    patch_runtime()
    patch_menu()
    patch_docs()
    verify_ascii_managed_executables()
    update_public_metadata()
    print("MANAGER_4_13_LIFECYCLE_PATCH=PASS")


if __name__ == "__main__":
    main()
