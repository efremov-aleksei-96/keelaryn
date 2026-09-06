from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


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


def replace_once(text: str, old: str, new: str, label: str):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one sentinel, found {count}")
    return text.replace(old, new, 1)


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def managed_digest(manager: Path, managed):
    rows = []
    for rel in sorted([str(x).replace('\\', '/') for x in managed]):
        rows.append(rel + "\0" + sha(manager / Path(rel)))
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


# Version markers.
runtime = ROOT / "manager/product/runtime/Keelaryn__Manager.ps1"
rt, rt_nl, rt_bom = read_norm(runtime)
rt = replace_once(rt, '$ManagerVersion = "4.13.0"', '$ManagerVersion = "4.13.1"', 'runtime version')

old_fn = """function Test-QualificationEvidenceCompactionToolSelfTest {
    try{
        $tool=Join-Path $Root 'product/tools/Compact-KeelarynQualificationEvidence.ps1'
        if(-not(Test-Path -LiteralPath $tool -PathType Leaf)){return $false}
        & (Join-Path $PSHOME 'powershell.exe') -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $tool -SelfTest | Out-Null
        return [int]$LASTEXITCODE -eq 0
    }catch{return $false}
}"""
new_fn = """$script:QualificationEvidenceCompactionToolSelfTestReason=''
function Test-QualificationEvidenceCompactionToolSelfTest {
    try{
        $tool=Join-Path $Root 'product/tools/Compact-KeelarynQualificationEvidence.ps1'
        if(-not(Test-Path -LiteralPath $tool -PathType Leaf)){$script:QualificationEvidenceCompactionToolSelfTestReason='tool missing: '+$tool;return $false}
        $output=@(& (Join-Path $PSHOME 'powershell.exe') -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $tool -SelfTest 2>&1)
        $code=[int]$LASTEXITCODE
        if($code-ne0){
            $tail=@($output|ForEach-Object{[string]$_}|Select-Object -Last 8)
            $script:QualificationEvidenceCompactionToolSelfTestReason=('exit='+$code+'; '+[string]::Join(' | ',$tail))
            return $false
        }
        return $true
    }catch{$script:QualificationEvidenceCompactionToolSelfTestReason=$_.Exception.Message;return $false}
}"""
rt = replace_once(rt, old_fn, new_fn, 'runtime qualification selftest helper')
rt = replace_once(
    rt,
    "if (-not (Test-QualificationEvidenceCompactionToolSelfTest)) { Write-Host 'Manager self-test failed: qualification evidence compaction contract.' -ForegroundColor Red; exit 1 }",
    "if (-not (Test-QualificationEvidenceCompactionToolSelfTest)) { Write-Host ('Manager self-test failed: qualification evidence compaction contract. '+[string]$script:QualificationEvidenceCompactionToolSelfTestReason) -ForegroundColor Red; exit 1 }",
    'runtime qualification selftest failure detail',
)
write_norm(runtime, rt, rt_nl, rt_bom)

compactor = ROOT / "manager/product/tools/Compact-KeelarynQualificationEvidence.ps1"
ct, ct_nl, ct_bom = read_norm(compactor)
start_marker = "        # File reparse substitution: the link target is intentionally different from the protected bound copy.\n"
end_marker = "        # Reparse-point directories remain unconditionally rejected and are never traversed.\n"
if ct.count(start_marker) != 1 or ct.count(end_marker) != 1:
    raise RuntimeError('compactor reparse selftest block markers are not unique')
start = ct.index(start_marker)
end = ct.index(end_marker, start)
new_block = r'''        # File reparse substitution. Actual file-symlink coverage is used when the host grants
        # symlink creation. Ordinary Windows without Developer Mode / SeCreateSymbolicLinkPrivilege
        # must still be able to run Manager SelfTest, so the protected-copy binding/archive contract
        # also has a privilege-free path that CI exercises explicitly.
        $r2=Join-Path $tests 'results\manager-9.9.10'
        New-Item -ItemType Directory -Force -Path $r2|Out-Null
        $summary2=[ordered]@{schema='keelaryn.manager.windows-gate-summary.v16';manager_version='9.9.10';baseline_version='9.9.9';gate_revision=3;framework_revision=11;status='PASS';completed='2026-01-02T00:00:00Z';candidate_installation_sha256=('c'*64);candidate_managed_content_sha256=('d'*64)}
        Write-Utf8NoBom (Join-Path $r2 'GATE_SUMMARY.json') (($summary2|ConvertTo-Json -Depth 4)+"`n")
        $evil=Join-Path $temp 'evil-target.txt';Write-Utf8NoBom $evil "evil-target-bytes`n"
        $protected=Join-Path $temp 'protected';New-Item -ItemType Directory -Force -Path $protected|Out-Null
        $protectedFile=Join-Path $protected 'copy.bin';Write-Utf8NoBom $protectedFile "protected-archive-bytes`n"
        $link=Join-Path $r2 'linked.txt'
        $forceNoFileSymlink=([string]$env:KEELARYN_SELFTEST_FORCE_NO_FILE_SYMLINK-eq'1')
        $linkCreated=$false;$linkCreationDetail=''
        if(-not$forceNoFileSymlink){
            try{New-Item -ItemType SymbolicLink -Path $link -Target $evil -ErrorAction Stop|Out-Null;$linkCreated=$true}
            catch{$linkCreationDetail=$_.Exception.Message}
        }else{$linkCreationDetail='forced no-file-symlink mode'}
        $mapPath=Join-Path $temp 'reparse-map.json'
        $protectedItem=Get-Item -LiteralPath $protectedFile -Force
        $map=[ordered]@{schema='keelaryn.reparse-substitution-map.v1';protected_root=$protected;entries=@([ordered]@{path='linked.txt';protected_path='copy.bin';size=[int64]$protectedItem.Length;sha256=(Get-Sha256 $protectedFile)})}
        Write-Utf8NoBom $mapPath (($map|ConvertTo-Json -Depth 6)+"`n")
        if($linkCreated){
            $linkItem=Get-Item -LiteralPath $link -Force -ErrorAction Stop
            if(($linkItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-eq0){return $false}
            $unmappedRejected=$false
            try{[void](Invoke-Compaction $r2 $tests $false $null)}catch{$unmappedRejected=$true}
            if(-not$unmappedRejected){return $false}
            if((Invoke-Compaction $r2 $tests $true $mapPath)-ne0){return $false}
            if(-not(Test-Path -LiteralPath $evil -PathType Leaf)-or-not(Test-Path -LiteralPath $protectedFile -PathType Leaf)-or(Test-Path -LiteralPath $link)){return $false}
            $idx2=Read-Json (Join-Path $r2 'QUALIFICATION_INDEX.json')
            $manifest2=Read-Json (Join-Path $tests ([string]$idx2.manifest_path).Replace('/','\'))
            $row2=@($manifest2.entries|Where-Object{[string]$_.path-ceq'linked.txt'})
            if($row2.Count-ne1-or$null-eq$row2[0].substitution){return $false}
            if([string]$row2[0].substitution.schema-ne'keelaryn.reparse-substitution.v1'-or[string]$row2[0].substitution.bound_sha256-cne(Get-Sha256 $protectedFile)){return $false}
            if([string]$row2[0].sha256-cne(Get-Sha256 $protectedFile)-or[string]$row2[0].sha256-ceq(Get-Sha256 $evil)){return $false}
        }else{
            Write-Host ('Qualification compaction self-test: file-symlink fixture unavailable; validating privilege-free substitution binding. '+$linkCreationDetail) -ForegroundColor DarkGray
            $subMap=Read-ReparseSubstitutionMap $mapPath
            $resolved=Resolve-ReparseSubstitution $subMap 'linked.txt'
            if([System.IO.Path]::GetFullPath([string]$resolved.ArchiveSourcePath)-cne[System.IO.Path]::GetFullPath($protectedFile)){return $false}
            if([int64]$resolved.Size-ne[int64]$protectedItem.Length-or[string]$resolved.Sha256-cne(Get-Sha256 $protectedFile)){return $false}
            if([string]$resolved.Substitution.schema-ne'keelaryn.reparse-substitution.v1'-or[string]$resolved.Substitution.bound_sha256-cne(Get-Sha256 $protectedFile)){return $false}
            $syntheticFile=[pscustomobject]@{
                Path=$evil;ArchiveSourcePath=$protectedFile;RelativePath='linked.txt';Size=[int64]$resolved.Size;Sha256=[string]$resolved.Sha256;
                Attributes=[int]$protectedItem.Attributes;CreationTimeUtc=$protectedItem.CreationTimeUtc.ToString('o');LastWriteTimeUtc=$protectedItem.LastWriteTimeUtc.ToString('o');Substitution=$resolved.Substitution
            }
            $syntheticInventory=[pscustomobject]@{Files=@($syntheticFile);Directories=@()}
            $digest2=Get-EvidenceDigest $syntheticInventory.Files
            $manifestObject=Get-FrozenManifest $r2 $summary2 $syntheticInventory $digest2
            $fallbackDir=Join-Path $tests 'archives\manager-9.9.10-fallback';Ensure-SafeDirectory $fallbackDir 'Qualification fallback archive directory'
            $fallbackArchive=Join-Path $fallbackDir 'fallback.zip';$fallbackManifest=Join-Path $fallbackDir 'fallback.manifest.json'
            $verifiedFallback=New-VerifiedArchive $fallbackArchive $fallbackManifest $manifestObject $syntheticInventory
            if(-not(Test-PublishedArchive $fallbackArchive $fallbackManifest ([string]$verifiedFallback.ArchiveSha256) ([string]$verifiedFallback.ManifestSha256))){return $false}
        }

'''
ct = ct[:start] + new_block + ct[end:]
write_norm(compactor, ct, ct_nl, ct_bom)

# Canonical version JSON markers.
install_path = ROOT / "manager/product/install/INSTALLATION.json"
install = json.loads(install_path.read_text(encoding="utf-8-sig"))
if install.get("manager_version") != "4.13.0":
    raise RuntimeError(f"unexpected INSTALLATION baseline version: {install.get('manager_version')}")
install["manager_version"] = "4.13.1"
install_path.write_text(json.dumps(install, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

release_path = ROOT / "manager/product/manager_release.json"
release = json.loads(release_path.read_text(encoding="utf-8-sig"))
if release.get("manager_version") != "4.13.0":
    raise RuntimeError(f"unexpected manager_release baseline version: {release.get('manager_version')}")
release["manager_version"] = "4.13.1"
release_path.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

manager_root = ROOT / "manager"
install_sha = sha(install_path)
digest = managed_digest(manager_root, install["managed_files"])

prov_path = ROOT / "PUBLIC_PROVENANCE.json"
prov = json.loads(prov_path.read_text(encoding="utf-8-sig"))
prov["source_manager_version"] = "4.13.1"
prov["source_manager_installation_sha256"] = install_sha
prov["source_manager_gate_managed_content_sha256"] = digest
pv = prov["production_validation"]
pv["full_gate_pass"] = False
pv["gate_revision"] = None
pv["framework_revision"] = 11
pv["production_doctor_pass"] = False
pv["production_ux_smoke_pass"] = False
pv["production_managed_content_prefix"] = None
pv["tested_update_sha256"] = None
prov["public_candidate_revision"] = int(prov.get("public_candidate_revision", 1)) + 1
prov_path.write_text(json.dumps(prov, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

manifest_path = ROOT / "PUBLIC_FILE_MANIFEST.json"
pm = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
pmgr = pm["manager"]
pmgr["version"] = "4.13.1"
pmgr["file_count"] = len(install["managed_files"])
pmgr["installation_sha256"] = install_sha
pmgr["gate_managed_content_sha256"] = digest
files = []
for rel in sorted([str(x).replace('\\', '/') for x in install["managed_files"]]):
    p = manager_root / Path(rel)
    files.append({"path": rel, "size_bytes": p.stat().st_size, "sha256": sha(p)})
pmgr["files"] = files
manifest_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

# No stale product version string may remain in the Manager authoritative tree.
remaining = []
for p in manager_root.rglob('*'):
    if p.is_file() and p.suffix.lower() in {'.ps1','.cmd','.json','.md','.txt'}:
        try:
            text = p.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            continue
        if '4.13.0' in text:
            remaining.append(str(p.relative_to(ROOT)).replace('\\','/'))
if remaining:
    raise RuntimeError('stale 4.13.0 product references remain: ' + ', '.join(remaining))

print('MANAGER_4_13_1_FIX=PASS')
print('INSTALLATION_SHA256=' + install_sha)
print('MANAGED_CONTENT_SHA256=' + digest)
print('MANAGED_FILES=' + str(len(install['managed_files'])))
