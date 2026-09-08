# Release engineering

Keelaryn treats a release as a chain of identities and gates rather than as a ZIP file copied from a development folder.

The release question is not only **“did the build succeed?”** It is:

> Can the repository prove that the bytes published to users are the same candidate bytes that passed the required Windows qualification, and can that result be reproduced without hidden local state?

## Release artifacts

A Manager release produces four primary artifacts plus a manifest:

| Artifact | Purpose |
|---|---|
| **SOURCE** | Canonical managed product source snapshot. |
| **DISTRIBUTION** | Clean-install package for a new Keelaryn installation. |
| **UPDATE** | Transition package for an existing Manager installation. |
| **AI_CONTEXT** | Generated task-routed development context bound to exact managed source/runtime identity. |
| **Release manifest** | Artifact names, sizes, hashes and release identity used for validation/handoff. |

The builder snapshots managed source, constructs the artifacts from that snapshot, validates the generated bundle, publishes it atomically, publishes the manifest last and then revalidates the published result before retention is applied.

## Identity discipline

Keelaryn keeps several identities separate because they answer different questions:

- **Manager version** — which product implementation is this?
- **managed-content digest** — are these exact managed source bytes the expected candidate?
- **gate revision** — which qualification execution/spec revision produced this evidence?
- **Gate Framework revision** — which reusable test-harness source was trusted?
- **UPDATE SHA-256** — which exact installable artifact passed the release boundary?
- **Git commit / release tag** — which public source and publication record correspond to the release?

An issued candidate is immutable. Product-byte defects require a new Manager candidate/version. Gate-only corrections may advance gate revision only when cryptographic candidate identity proves that product bytes did not change. Reusable Gate Framework changes have their own framework revision and qualification cycle.

Current identities are machine-readable in [`PUBLIC_PROVENANCE.json`](../PUBLIC_PROVENANCE.json) and [`PUBLIC_FILE_MANIFEST.json`](../PUBLIC_FILE_MANIFEST.json); this document intentionally does not duplicate the current version/revision numbers.

## Qualification layers

```mermaid
flowchart LR
    C[Manager candidate] --> S[SourceGate]
    S --> D[Hosted disposable Full Gate]
    D --> P[Production Full Gate]
    P --> H[Tested-artifact handoff]
    H --> PR[Public-source PR]
    PR --> R[Required repository checks]
    R --> PUB[Immutable GitHub Release]

    D -. prequalification only .-> P
```

### 1. SourceGate

SourceGate is the deterministic source/release layer. It checks, as applicable:

- PowerShell parser and executable-source constraints;
- exact managed-file set;
- Manager/frontend/archive SelfTests;
- non-interactive UI contracts;
- AI_CONTEXT construction and reconstruction constraints;
- isolated deterministic `BUILD_RELEASE` runs;
- SOURCE / DISTRIBUTION / UPDATE boundary contracts;
- release handoff metadata.

Two release builds use isolated roots so one build cannot accidentally make the next one appear deterministic through shared output or cached state.

### 2. Hosted disposable Full Gate

A GitHub-hosted Windows runner can execute the deep disposable suite against a synthetic canonical Hub. This catches update, rollback, migration, UI and packaging defects without requiring access to personal data or a maintainer workstation.

Its evidence is explicitly classified as **synthetic prequalification only**. It cannot satisfy final production approval by itself.

See [Remote qualification](REMOTE_QUALIFICATION.md).

### 3. Production Full Gate

Before production approval, the applicable real production boundary is checked. Mutable work still occurs on disposable targets; production Manager/Hub/CURRENT state is used only under the gate's read-only contract.

The Full Gate exercises, as applicable:

- production read-only preflight;
- SOURCE / SelfTest / AI_CONTEXT / deterministic release checks;
- CURRENT-backed disposable baseline creation;
- rollback fault injection;
- native disposable Manager update;
- post-update Doctor and migrations;
- UI and submenu orchestration;
- archive and hostile-path regression;
- candidate transport build/reconstruction;
- CURRENT repair;
- AI_CONTEXT performance control;
- installed release and Generic DISTRIBUTION behavior;
- Genesis and recovery-related contracts;
- final production immutability.

A PASS publishes the exact tested Manager UPDATE and the tested-artifact handoff used for the production install/release cycle.

### 4. Public-source PR gates

The public repository protects `main` with required status checks. The source state proposed for merge is validated through:

- `source-gate`;
- `repository-governance`;
- `release-policy`.

For release-critical diffs, `release-policy` additionally requires the expensive `distribution-gate` to succeed on the exact current PR head SHA. This keeps a universal cheap required check while still enforcing release-specific validation where needed.

Repository governance also validates:

- full-SHA-pinned GitHub Actions;
- approved runner OS families;
- public source boundaries;
- deterministic public file manifest generation;
- presentation/current-state drift controls;
- artifact upload/download SHA-256 roundtrip.

### 5. Publication

For an applicable new release, the public release workflow consumes already-qualified source/provenance and then:

1. rebuilds/validates the public release bundle;
2. creates the GitHub Release as a draft;
3. attaches the complete asset set before publication;
4. publishes it;
5. requires native release immutability;
6. verifies release and asset attestations;
7. re-downloads assets and requires byte identity with the gated build.

The workflow fails closed if a newly published release does not satisfy the configured immutability policy.

## Why the production Hub is not a mutable test target

A real Hub is valuable for compatibility evidence but unacceptable as a mutation fixture. Qualification therefore separates:

- **production observation** — read-only identity/compatibility checks where required;
- **disposable execution** — updates, migrations, failure injection, archive tests and other mutable operations under `tests` roots or synthetic hosted installations.

The final immutability phase verifies that qualification itself did not alter the protected production state.

## Candidate and gate failures

A failed candidate is evidence, not something to erase. The release process therefore avoids:

- silently replacing already-issued candidate bytes;
- changing Gate Framework source without a new framework identity;
- retroactively rewriting old qualification provenance using a newer framework;
- promoting disposable hosted evidence to production qualification;
- rebuilding an UPDATE and assuming it is the tested artifact without checking exact identity.

This discipline keeps historical PASS/FAIL statements referentially stable.

## Reproducibility controls

Release reproducibility is enforced at several layers:

- exact managed-file allowlist;
- managed-content SHA-256 identity;
- isolated deterministic release builds;
- deterministic public source manifest generation;
- exact tested UPDATE hash in provenance;
- source checkout attributes for authoritative byte preservation;
- artifact transport roundtrip validation in GitHub Actions;
- immutable release publication for applicable new releases.

## Current release evidence

Do not infer the current release from prose in this document. Use the authoritative surfaces:

- [Latest GitHub Release](https://github.com/efremov-aleksei-96/keelaryn/releases/latest)
- [`PUBLIC_PROVENANCE.json`](../PUBLIC_PROVENANCE.json)
- [`PUBLIC_FILE_MANIFEST.json`](../PUBLIC_FILE_MANIFEST.json)
- [`REPOSITORY_GOVERNANCE.json`](../REPOSITORY_GOVERNANCE.json)

That separation is deliberate: volatile release identity belongs in generated/machine-readable metadata, while this document describes the stable engineering model.
