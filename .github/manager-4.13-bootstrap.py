from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
MAIN = HERE / "manager-4.13-bootstrap-main.py"
FIX1 = HERE / "manager-4.13-fix1.py"

for helper in (MAIN, FIX1):
    if not helper.is_file():
        raise RuntimeError(f"Missing 4.13 bootstrap helper: {helper}")

# Load the asserted patcher without invoking its __main__ block, then apply the
# grouped product patch. Keep its identity helpers available so final public
# metadata can be bound only after every byte-level fix has completed.
ns = runpy.run_path(str(MAIN), run_name="keelaryn_manager_4_13_bootstrap_main")
ns["main"]()
runpy.run_path(str(FIX1), run_name="__main__")
ns["verify_ascii_executables"]()
ns["public_metadata_patch"]()

# Branch-only bootstrap implementation details must not survive into the
# validated public source commit.
MAIN.unlink()
FIX1.unlink()
print("MANAGER_4_13_BOOTSTRAP_WRAPPER=PASS")
