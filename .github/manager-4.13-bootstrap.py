from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
MAIN = HERE / "manager-4.13-bootstrap-main.py"
FIX1 = HERE / "manager-4.13-fix1.py"

for helper in (MAIN, FIX1):
    if not helper.is_file():
        raise RuntimeError(f"Missing 4.13 bootstrap helper: {helper}")

runpy.run_path(str(MAIN), run_name="__main__")
runpy.run_path(str(FIX1), run_name="__main__")

# These files are branch-only bootstrap implementation details. Delete them from
# the working tree before public-source verification and before the validated
# product commit is made.
MAIN.unlink()
FIX1.unlink()
print("MANAGER_4_13_BOOTSTRAP_WRAPPER=PASS")
