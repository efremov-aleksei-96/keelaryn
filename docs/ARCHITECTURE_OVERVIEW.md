# Architecture overview

Keelaryn separates generic product source from instance-owned state.

```text
repository / product source
manager/
├── compat/commands/
└── product/
    ├── governance/hub/
    ├── starter/hub/
    ├── migrations/
    ├── runtime/
    └── tools/

                 manages
                    ↓
              Hub instance
```

## Product / instance boundary

`manager/product/install/INSTALLATION.json` is the canonical Manager managed-file allowlist. `manager/state/`, the real Hub, CURRENT/inbox/log/history/release output and bindings are runtime state, not repository source.

Generic Hub governance and Genesis starter templates are product source because Manager must be able to create/migrate a Hub without embedding a sample personal instance.

## Identity layers

- `instance_id`: stable Hub instance identity.
- `artifact_id`: one Hub checkpoint identity.
- `revision_time_utc`: immutable human-facing revision time where available.
- `data_revision`: internal monotonic lineage/order sequence retained for compatibility.
- `release_id`: generic Hub/system product release identity.
- Manager version: Manager implementation version, independent of Hub system release.

## Validation model

Read-only operations may reuse immutable per-operation inspection snapshots. Mutation/commit boundaries deliberately perform fresh validation. Manager UPDATE validation opens one ZIP once per validation pass; staged package validation remains a separate fresh pass before installation.

## Release / gate architecture

Manager release construction produces SOURCE, DISTRIBUTION, UPDATE and AI_CONTEXT plus a release manifest. The frozen reusable Gate Framework under `tests/framework/manager-gate` builds versioned Windows gates and binds each gate to the candidate `INSTALLATION.json` and managed-content digest.

SourceGate uses two isolated Manager roots for deterministic release comparison. Full Gate then exercises a CURRENT-backed disposable baseline, rollback, native update, Doctor, UI/archive orchestration, candidate transport, CURRENT repair, Genesis and production immutability.

The personal production Hub is never a mutable test target.

## AI_CONTEXT

AI_CONTEXT is generated from managed Manager source, bound to the exact runtime hash, and exposes task routes plus exact function/source slices. It reduces model context without becoming a second implementation.
