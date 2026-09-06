from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'manager/product/tools/Compact-KeelarynQualificationEvidence.ps1'
text = path.read_text(encoding='utf-8-sig')

bad = "'\\\\'"   # PowerShell single-quoted string containing two backslash characters.
good = "'\\'"     # PowerShell single-quoted string containing one backslash character.
count = text.count(bad)
if count < 1:
    raise RuntimeError('Expected staged double-backslash PowerShell literals, found none.')
text = text.replace(bad, good)
if bad in text:
    raise RuntimeError('Double-backslash PowerShell literal normalization was incomplete.')
path.write_text(text, encoding='utf-8', newline='\n')
print(f'LIFECYCLE_POWERSHELL_PATH_LITERAL_FIX=PASS replacements={count}')
