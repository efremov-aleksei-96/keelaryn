from pathlib import Path

root = Path(__file__).resolve().parents[1]

# Normalize PowerShell path literals introduced by the staged reparse block.
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

# Portable-normalize the TESTING.md template before the main lifecycle patcher emits it.
patcher = root / '.github/manager-4.13-lifecycle.py'
source = patcher.read_text(encoding='utf-8-sig')
old = r'D:\\0\\0__Core\\keelaryn\\tests\\UNPACK_MANAGER_GATE.cmd'
new = r'tests\\UNPACK_MANAGER_GATE.cmd'
found = source.count(old)
if found != 1:
    raise RuntimeError(f'Expected exactly one maintainer-local gate entrypoint template, found {found}')
source = source.replace(old, new, 1)
if r'D:\\0\\0__Core\\keelaryn' in source:
    raise RuntimeError('Maintainer-local Keelaryn root remains in lifecycle product documentation template.')
patcher.write_text(source, encoding='utf-8', newline='\n')

print(f'LIFECYCLE_POWERSHELL_PATH_LITERAL_FIX=PASS replacements={count}')
print('LIFECYCLE_PORTABLE_TESTING_TEMPLATE_FIX=PASS')
