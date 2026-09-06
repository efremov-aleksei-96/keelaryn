from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'manager/product/docs/TESTING.md'
text = path.read_text(encoding='utf-8-sig')
old = r'D:\0\0__Core\keelaryn\tests\UNPACK_MANAGER_GATE.cmd'
new = r'tests\UNPACK_MANAGER_GATE.cmd'
count = text.count(old)
if count != 1:
    raise RuntimeError(f'Expected exactly one maintainer-local gate entrypoint in staged TESTING.md, found {count}')
text = text.replace(old, new, 1)
if r'D:\0\0__Core\keelaryn' in text:
    raise RuntimeError('Maintainer-local Keelaryn root remains in staged Manager TESTING.md.')
path.write_text(text, encoding='utf-8', newline='\n')
print('LIFECYCLE_PORTABLE_TESTING_DOC_FIX=PASS')
