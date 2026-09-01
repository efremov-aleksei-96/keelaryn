# Release engineering

Keelaryn release engineering is intentionally conservative.

## Release artifacts

A modern Manager release contains four artifacts plus a release manifest:

- SOURCE
- DISTRIBUTION
- UPDATE
- AI_CONTEXT
- release manifest containing SHA-256 for each artifact

The system release version and Manager implementation version are independent.

## Publication sequence

`BUILD_RELEASE.cmd`:

1. reconstructs artifacts from the managed allowlist in temporary same-volume staging;
2. validates the generated UPDATE;
3. validates the complete release-bundle hash set;
4. publishes the four artifacts;
5. publishes the release manifest last;
6. revalidates the published bundle;
7. only then runs release retention.

This prevents an interrupted publication from advertising a complete release that was not fully written.

## Candidate discipline

An issued candidate is immutable as a release-engineering object. If a defect is found, the candidate is rejected and a new version/candidate number is created. Candidates are not described as production-ready until the required Windows gates pass.

## Windows release gates

A typical gate includes:

- PowerShell 5.1 parser validation;
- SelfTest;
- deterministic AI_CONTEXT reconstruction;
- deterministic BUILD_RELEASE;
- disposable native update from the current production baseline;
- Doctor and migration checks;
- rollback snapshot validation;
- Hub/CURRENT immutability;
- targeted fault injection;
- production-tree immutability;
- performance acceptance when the change is performance-sensitive.

## Retention

`_releases` keeps the current and nearest previous valid release. Older validated bundles are moved to bounded history. Invalid, unknown or future bundles are never automatically deleted.
