from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'manager/README_FIRST.md'
raw = path.read_bytes()
bom = raw.startswith(b'\xef\xbb\xbf')
text = raw.decode('utf-8-sig')
nl = '\r\n' if text.count('\r\n') > text.count('\n') / 2 else '\n'
text = text.replace('\r\n','\n').replace('\r','\n')
count = text.count('4.13.0')
if count < 1:
    raise RuntimeError('Expected at least one 4.13.0 marker in manager/README_FIRST.md')
text = text.replace('4.13.0','4.13.1')
out = text.replace('\n', nl).encode('utf-8')
if bom:
    out = b'\xef\xbb\xbf' + out
path.write_bytes(out)
print(f'MANAGER_4_13_1_README_VERSION_FIX=PASS replacements={count}')
