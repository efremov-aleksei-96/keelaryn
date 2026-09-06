from pathlib import Path

root=Path(__file__).resolve().parents[1]
p=root/'manager/product/tools/Compact-KeelarynQualificationEvidence.ps1'
s=p.read_text(encoding='utf-8-sig')
count=s.count('-or-not')
if count!=2:
    raise RuntimeError(f'Expected exactly two fused -or-not tokens in staging compactor, found {count}')
s=s.replace('-or-not',' -or -not ')
p.write_text(s,encoding='utf-8',newline='\n')
print('LIFECYCLE_COMPACTOR_BOOLEAN_GLUE_FIX=PASS')
