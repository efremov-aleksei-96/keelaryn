# Security model

Keelaryn is not a sandbox for hostile code. Its security model protects local state and prevents unsafe filesystem/package behavior in a trusted-user automation environment.

## Assets

- canonical Hub data/checkpoint identity;
- Manager managed source/runtime;
- rollback/history snapshots;
- release artifacts/manifests;
- instance-specific candidate/current transport.

## Controls

- path traversal, reserved-name, Unicode/case collision and reparse-point checks;
- ZIP-envelope validation before package interpretation;
- exact declared managed-set updates;
- rollback snapshots and post-install validation;
- bounded file-lock retry with read-only Restart Manager diagnostics;
- explicit CURRENT/CANDIDATE/APPROVED roles;
- managed allowlists for generic release construction;
- personal Hub and Manager state excluded from public source;
- fresh validation at transaction/commit boundaries.

The reusable Gate Framework is qualified independently because test infrastructure is itself part of the release trust boundary.

## Secrets / disclosure

Passwords, private keys, recovery codes, seed phrases and TOTP secrets do not belong in the portable Hub or public repository. Use GitHub Private Vulnerability Reporting when available and never attach real Hub/private transport data to public issues.
