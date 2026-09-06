from pathlib import Path

root=Path(__file__).resolve().parents[1]
p=root/'.github/manager-4.13-lifecycle.py'
s=p.read_text(encoding='utf-8')
old='marker = "    \'product/tools/KeelarynMenu.ps1\',"'
new='marker = \'    "product/tools/KeelarynMenu.ps1",\''
if s.count(old)!=1:
    raise RuntimeError(f'Expected one lifecycle managed-list sentinel definition, found {s.count(old)}')
p.write_text(s.replace(old,new,1),encoding='utf-8',newline='\n')
print('LIFECYCLE_PATCHER_SENTINEL_FIX=PASS')
