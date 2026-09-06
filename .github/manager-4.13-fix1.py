from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "manager/product/tools/KeelarynMenu.ps1"
raw = path.read_bytes()
bom = raw.startswith(b"\xef\xbb\xbf")
text = raw.decode("utf-8-sig")
newline = "\r\n" if text.count("\r\n") > text.count("\n") / 2 else "\n"
norm = text.replace("\r\n", "\n").replace("\r", "\n")
old = ")-and-not("
count = norm.count(old)
if count != 1:
    raise RuntimeError(f"Expected exactly one newly introduced AI_CONTEXT-unsafe boolean glue token, found {count}")
norm = norm.replace(old, ") -and -not (", 1)
out = norm.replace("\n", newline).encode("utf-8")
if bom:
    out = b"\xef\xbb\xbf" + out
path.write_bytes(out)
print("MANAGER_4_13_FIX1_AI_CONTEXT_BOOLEAN_GLUE=PASS")
