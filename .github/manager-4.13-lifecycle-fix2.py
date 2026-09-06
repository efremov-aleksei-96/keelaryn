from pathlib import Path
import re

root=Path(__file__).resolve().parents[1]
p=root/'manager/product/tools/Compact-KeelarynQualificationEvidence.ps1'
s=p.read_text(encoding='utf-8-sig')
count=s.count('-or-not')
if count!=2:
    raise RuntimeError(f'Expected exactly two fused -or-not tokens in staging compactor, found {count}')
s=s.replace('-or-not',' -or -not ')
patterns=[
    (r'\)-or\(', ') -or ('),
    (r'\)-and\(', ') -and ('),
    (r'-or\[', ' -or ['),
    (r'-and\[', ' -and ['),
    (r'-or@\(', ' -or @('),
    (r'-and@\(', ' -and @('),
    (r'-or\(', ' -or ('),
    (r'-and\(', ' -and ('),
]
changes=0
for pat,repl in patterns:
    s,n=re.subn(pat,repl,s)
    changes+=n
if changes<1:
    raise RuntimeError('Expected at least one additional fused logical operator to normalize in staging compactor.')
paren_fixes=[
    (
        "if(-not(Test-PublishedArchive $archivePath $manifestPath ([string]$index.archive_sha256) ([string]$index.manifest_sha256)){",
        "if(-not(Test-PublishedArchive $archivePath $manifestPath ([string]$index.archive_sha256) ([string]$index.manifest_sha256))){",
    ),
    (
        "if(-not(Test-PublishedArchive $archive $manifest ([string]$index.archive_sha256) ([string]$index.manifest_sha256)){",
        "if(-not(Test-PublishedArchive $archive $manifest ([string]$index.archive_sha256) ([string]$index.manifest_sha256))){",
    ),
]
paren_changes=0
for old,new in paren_fixes:
    found=s.count(old)
    if found!=1:
        raise RuntimeError(f'Expected exactly one missing-if-parenthesis sentinel, found {found}: {old}')
    s=s.replace(old,new,1)
    paren_changes+=1
p.write_text(s,encoding='utf-8',newline='\n')
print(f'LIFECYCLE_COMPACTOR_BOOLEAN_GLUE_FIX=PASS additional_changes={changes} paren_fixes={paren_changes}')
