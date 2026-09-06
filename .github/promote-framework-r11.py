from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_exact(text: str, old: str, new: str, expected: int, label: str) -> str:
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"{label}: expected {expected} replacement(s), found {count}")
    return text.replace(old, new)


framework = ROOT / "tests" / "framework" / "manager-gate"
full = framework / "templates" / "Run-KeelarynManagerFullGate.ps1"
source = framework / "templates" / "Run-KeelarynManagerSourceGate.ps1"
marker = framework / "FRAMEWORK_REVISION.txt"
framework_readme = framework / "README.md"

if sha256(full) != "c6e1fc79e6ffff15baf69292d782134d3aae25334d7eb1b5a29b143766526d2a":
    raise RuntimeError("Framework r9 FullGate identity mismatch")
if sha256(source) != "a0afd33988451bf6af2460355ca5c8f577b7401a202734bb54dd660edccaf1eb":
    raise RuntimeError("Framework r9 SourceGate identity mismatch")
if marker.read_text(encoding="utf-8").strip() != "9":
    raise RuntimeError("Framework revision base is not r9")

old_prefix = (
    "    $safeLabel=($Label-replace'[^A-Za-z0-9_.-]','_')\r\n"
    "    $prefix=('{0:D3}_{1}'-f$script:CommandSequence,$safeLabel)\r\n"
)
new_prefix = (
    "    $safeLabel=($Label-replace'[^A-Za-z0-9_.-]','_')\r\n"
    "    $labelHash=(TextSha $Label).Substring(0,12)\r\n"
    "    if($safeLabel.Length-gt80){$safeLabel=$safeLabel.Substring(0,80)}\r\n"
    "    $prefix=('{0:D3}_{1}_{2}'-f$script:CommandSequence,$safeLabel,$labelHash)\r\n"
)

full_text = full.read_bytes().decode("ascii")
source_text = source.read_bytes().decode("ascii")
full_text = replace_exact(full_text, old_prefix, new_prefix, 1, "FullGate bounded sidecars")
source_text = replace_exact(source_text, old_prefix, new_prefix, 1, "SourceGate bounded sidecars")
full_text = replace_exact(full_text, "$candA=New-CandidateFixture $stateCurrent", "$candA=New-CandidateFixture $migCurrent", 1, "candidate fixture A lineage")
full_text = replace_exact(full_text, "$candB=New-CandidateFixture $stateCurrent", "$candB=New-CandidateFixture $migCurrent", 1, "candidate fixture B lineage")
full.write_bytes(full_text.encode("ascii"))
source.write_bytes(source_text.encode("ascii"))
marker.write_bytes(b"11\n")

expected_post = {
    full: "2e7ac7f14dc6528da6e1d75dc7c97e6f84839af451b86c572920c9bb8a308fb9",
    source: "fff6dccaea97695a68820fdd64115a4364fdc6248bbaf4a9c91db6926c4ef414",
    marker: "25d4f2a86deb5e2574bb3210b67bb24fcc4afb19f93a7b65a057daa874a9d18e",
}
for path, expected in expected_post.items():
    actual = sha256(path)
    if actual != expected:
        raise RuntimeError(f"Framework r11 exact-byte mismatch: {path}: {actual}")

readme = framework_readme.read_text(encoding="utf-8")
addition = """

## Revision 10 bounded command sidecars

Revision 10 bounds command-log and exit-code sidecar filenames on Windows. The human-visible command label remains complete, while the filesystem prefix uses at most the first 80 sanitized label characters plus a deterministic 12-hex SHA-256 suffix of the complete label. This prevents long command arguments from exceeding Windows path limits without weakening exit-code capture or log-name uniqueness.

## Revision 11 candidate-lineage fixture correction

Revision 11 preserves the revision 10 path-length hardening and corrects the Full Gate candidate-transport fixture source. Candidate fixtures use the valid non-genesis migration CURRENT already produced by the gate instead of the original Genesis CURRENT. This keeps the candidate transport regression on a normal parented lineage even when the disposable production fixture starts at Genesis.

Revision 11 was independently qualified on Windows PowerShell 5.1 while testing unchanged Manager 4.12.0 g1 bytes. Gate Revision 3 passed SourceGate, CURRENT-backed Full Gate, rollback fault injection, native 4.11.0 -> 4.12.0 update, post-update Doctor, UI/archive/migration/candidate-transport/Genesis coverage, AI_CONTEXT performance control and production immutability.
"""
if "## Revision 10 bounded command sidecars" in readme or "## Revision 11 candidate-lineage fixture correction" in readme:
    raise RuntimeError("Framework r10/r11 README notes already exist")
framework_readme.write_text(readme.rstrip() + addition, encoding="utf-8", newline="\n")

manifest_path = ROOT / "PUBLIC_FILE_MANIFEST.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest["gate_framework"].get("revision") != 9:
    raise RuntimeError("Public manifest framework base is not r9")
manifest["gate_framework"]["revision"] = 11
for row in manifest["gate_framework"]["files"]:
    path = framework / row["path"]
    row["size_bytes"] = path.stat().st_size
    row["sha256"] = sha256(path)
manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")

prov_path = ROOT / "PUBLIC_PROVENANCE.json"
prov = json.loads(prov_path.read_text(encoding="utf-8"))
if prov.get("public_candidate_revision") != 8:
    raise RuntimeError("Unexpected provenance public candidate revision before r11 promotion")
if prov["production_validation"].get("framework_revision") != 9:
    raise RuntimeError("Historical Manager 4.11.0 production framework provenance is not r9")
if prov["gate_framework"].get("revision") != 9:
    raise RuntimeError("Current framework provenance base is not r9")
prov["public_candidate_revision"] = 9
prov["gate_framework"]["revision"] = 11
prov["gate_framework"]["windows_qualified"] = True
prov["gate_framework"]["frozen_for_manager_candidate"] = True
# Historical production qualification intentionally remains r9: Manager 4.11.0 was qualified on r9.
prov_path.write_text(json.dumps(prov, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")

verifier = ROOT / "tools" / "Verify-PublicRepository.ps1"
verifier_text = verifier.read_text(encoding="utf-8")
verifier_text = replace_exact(verifier_text, "if($fr-ne'9')", "if($fr-ne'11')", 1, "public verifier framework revision")
verifier.write_text(verifier_text, encoding="utf-8", newline="\n")

root_readme = ROOT / "README.md"
root_text = root_readme.read_text(encoding="utf-8")
old = "The reusable Manager gate harness under `tests/framework/manager-gate/` is frozen **Gate Framework v2 revision 9**, independently qualified on Windows PowerShell 5.1."
new = "The reusable Manager gate harness under `tests/framework/manager-gate/` is frozen **Gate Framework v2 revision 11**, independently qualified on Windows PowerShell 5.1. Manager 4.11.0 itself was production-qualified with historical Framework r9; r11 is the current reusable framework for subsequent candidates."
root_text = replace_exact(root_text, old, new, 1, "root README framework baseline")
root_readme.write_text(root_text, encoding="utf-8", newline="\n")

# Workflow files and this one-shot helper are intentionally left untouched by this commit.
# They are cleaned/renamed through the connected GitHub API after the promoted tree is pushed,
# because GitHub Actions tokens are not granted workflow-file mutation permission.

print("Framework r11 promotion tree prepared")
print("FullGate SHA256:", sha256(full))
print("SourceGate SHA256:", sha256(source))
print("Framework README SHA256:", sha256(framework_readme))
print("Public manifest SHA256:", sha256(manifest_path))
print("Public provenance keeps Manager 4.11 historical framework:", prov["production_validation"]["framework_revision"])
