# Security model

Keelaryn is not a sandbox for hostile code. Its security model focuses on protecting local state and preventing unsafe filesystem/package behavior in a trusted-user automation environment.

## Assets

- canonical Hub data and checkpoint identity;
- Manager managed source and installed runtime;
- rollback/history snapshots;
- release artifacts and their manifests;
- instance-specific CANDIDATE/CURRENT transport packages.

## Relevant threats

### Path confusion and traversal

Package and generated paths are normalized and checked for traversal, Windows reserved names, Unicode/case collisions and invalid path forms.

### Reparse points / junction redirection

Managed update targets and important roots are checked for reparse points so writes cannot silently escape the intended tree.

### Partial or inconsistent updates

Manager updates validate declared file hashes and sizes, snapshot the old managed product, apply the exact declared set, and validate the installed result. Release publication validates staged artifacts before the release manifest is published.

### File-sharing races

Transient log sharing violations use bounded retries. Terminal sharing/lock failures remain fatal. Restart Manager diagnostics can report lock owners but never terminate or restart them.

### Corrupt or ambiguous archives

ZIP envelopes are validated before interpretation. Hub package paths and identities are checked, and current/candidate/approved roles remain explicit.

### Instance data leaking into generic releases

Generic builds operate from a managed allowlist. Instance-specific transport data may contain exact changed Hub bytes and is excluded from generic SOURCE/DISTRIBUTION/UPDATE/AI_CONTEXT artifacts.

## Secrets

Keelaryn governance explicitly says that passwords, private keys, recovery codes, seed phrases and TOTP secrets do not belong in the portable Hub. This public repository contains no real Hub instance.

## Responsible disclosure

When this repository is published, enable GitHub Private Vulnerability Reporting if available. Do not attach real Hub data, credentials or private transport artifacts to public issues.
