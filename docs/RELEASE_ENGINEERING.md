# Release engineering

Keelaryn release engineering is fail-closed and reproducibility-oriented.

## Release artifacts

A Manager release contains:

- SOURCE;
- DISTRIBUTION;
- UPDATE;
- AI_CONTEXT;
- release manifest with hashes/sizes.

The builder snapshots managed source once, constructs artifacts from that snapshot, validates the generated UPDATE and release bundle, publishes artifacts atomically, publishes the manifest last, revalidates the published bundle and only then performs retention.

## Candidate discipline

An issued candidate is immutable. A product-byte defect requires a new Manager candidate version. A gate-only defect may increment only gate revision when cryptographic candidate binding proves managed bytes are unchanged.

## Gate Framework

Reusable gate source lives at `tests/framework/manager-gate`. The current frozen Windows-qualified baseline is **Framework v2 revision 9**. Framework changes are qualified separately before use with a new Manager candidate.

`GATE_SPEC.json` binds candidate version, expected production baseline, gate/framework revision, canonical installation hash and managed-content digest.

## Windows Full Gate

A production release requires, as applicable:

- parser/static/ASCII checks;
- Manager/frontend/archive SelfTests;
- AI_CONTEXT reconstruction;
- isolated deterministic BUILD_RELEASE x2;
- SOURCE/DISTRIBUTION/UPDATE boundary checks;
- rollback fault injection;
- disposable native Manager update;
- Doctor and migrations;
- UI/archive/candidate-transport regression;
- CURRENT repair;
- performance control;
- distribution/Genesis checks;
- production immutability.

After PASS the gate publishes the exact tested Manager UPDATE and one-click installer under local `tests/results/manager-<version>/artifacts/`.

## GitHub CI

Hosted CI is intentionally Hub-blind. It verifies the public repository boundary and runs the SourceGate layer on Windows PowerShell 5.1. The CURRENT-backed Full Gate remains local release evidence.
