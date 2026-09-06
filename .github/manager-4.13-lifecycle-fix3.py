from pathlib import Path
import re

root=Path(__file__).resolve().parents[1]
p=root/'manager/product/tools/Compact-KeelarynQualificationEvidence.ps1'
s=p.read_text(encoding='utf-8-sig')
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
    raise RuntimeError('Expected at least one fused logical operator to normalize in staging compactor.')
p.write_text(s,encoding='utf-8',newline='\n')
print(f'LIFECYCLE_COMPACTOR_LOGICAL_NORMALIZATION=PASS changes={changes}')
