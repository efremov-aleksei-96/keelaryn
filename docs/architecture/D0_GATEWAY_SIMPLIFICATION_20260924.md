# D0 Gateway simplification

## Decision

Gateway is now the preferred execution substrate for autonomous Keelaryn development on the VPS.

This changes the D0 architecture boundary:

```text
ChatGPT
  -> GitHub authority
  -> Gateway managed SSH / durable job
  -> VPS
  -> Keelaryn-specific qualified tool
```

Keelaryn must no longer implement a general ChatGPT-to-VPS transport when Gateway already supplies authenticated SSH execution, host-key trust, durable jobs, typed administrative operations, file transfer and audit history.

The simplification does **not** remove Keelaryn-specific correctness. Gateway answers **how an operation is executed**; Keelaryn remains responsible for **what operation is valid, qualified, transactional, recoverable and semantically correct**.

## Retain

The active architecture retains:

- deterministic release build and materialization identity;
- exact candidate qualification and exact-head CI;
- release-switch/update transactions and rollback;
- read-only reconciliation after ambiguity/interruption;
- domain-specific validation and mutation boundaries;
- Corpus-first product layers: discovery, Artifact identity, locators, observations/revisions, semantics, relations, validation, transactions, recovery and AI context.

These are not transport concerns and are not replaced by Gateway.

## Superseded for D0 remote execution

The following are superseded as the **normal ChatGPT-to-VPS execution channel**:

- `core/keelaryn_core/operation_transport.py` GitHub Issues transport;
- the GitHub-Issues queue/status relay architecture;
- the dedicated GitHub operation credential when used only for that relay;
- the requirement that ChatGPT reach VPS work indirectly through that relay.

No deletion occurs in this checkpoint.

## Transition-only components

The following remain installed or retained temporarily until a separately qualified decommission:

- `keelaryn-operation-transport.service`;
- `keelaryn-operation-agent.service`;
- operation-control bootstrap/update/recovery machinery whose purpose is installing/updating those services;
- r0007/r0008/r0009 transition tooling, tests and evidence.

At the live read-only audit on 2026-09-24, operation-agent and operation-transport were both active/running; `keelaryn-drive.service` was inactive/dead; no `keelaryn-*` failed service was present.

They MUST NOT be stopped, disabled or deleted merely because this architectural decision exists. First migrate durable state/CI to the Gateway model, design the restricted operator boundary, and prove safe decommission.

## Review rather than blindly delete

### Operation Runtime

`operation_runtime.py` contains semantics that may remain valuable even with Gateway:

- explicit mutation-boundary progression;
- immutable terminal authority;
- recovery-required classification;
- no-blind-retry rules;
- local durable handoff independent of a network session.

Gateway already provides durable execution jobs, so the runtime should be reduced to domain-specific durable semantics where those semantics are still required. Its old remote-transport roadmap is no longer an architectural requirement.

### Operation Agent

The agent's old role as the remote dispatcher is superseded by Gateway. A smaller local privilege-separation role may still be useful, but only if it is simpler and safer than a dedicated `keelaryn-ops` account plus restricted sudo/operator commands. This must be decided by evidence, not preserved by inertia.

## State-schema debt discovered by this audit

`DEVELOPMENT_STATE.json` validation still hard-codes the older r0005/GitHub-Issues selftest model:

- `production_boundary.installed_operation_control` is bound to the same source as `read_only_selftest`;
- the recorded selftest is the historical GitHub-Issues relay selftest;
- therefore simply changing the state file to r0009/Gateway would currently fail its own validator.

The next coherent development step is a **state-schema/test migration** representing Gateway as the D0 operator channel and separating current VPS control identity from historical relay selftest evidence.

No service decommission is allowed before that migration is green.

## Target D0 architecture

```text
GitHub
  source / branch / CI / specs / checkpoints

Gateway
  authenticated execution transport
  durable SSH jobs
  host-key trust
  bounded administrative operations

VPS
  controlled runtime/integration state

Keelaryn
  qualified domain tools
  validation / transactions / reconcile / rollback

Google Drive
  corpus authority where applicable

ChatGPT
  engineer/orchestrator, never durable authority
```

This architecture removes duplicated transport machinery while preserving Keelaryn's actual product and correctness responsibilities.
