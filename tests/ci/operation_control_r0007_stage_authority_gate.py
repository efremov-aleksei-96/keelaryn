from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


authority = _load(
    "keelaryn_stage_authority_gate_contract",
    ROOT / "tools" / "operation_control_r0007_stage_authority.py",
)
issuer = _load(
    "keelaryn_stage_authority_gate_issuer",
    ROOT / "tools" / "operation_control_r0007_stage_authority_issue.py",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="operation-control-r0007-stage-authority-gate"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    value = authority.qualify(render_record=issuer.render_record)
    raw = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(raw, encoding="utf-8", newline="\n")
    print(raw, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
