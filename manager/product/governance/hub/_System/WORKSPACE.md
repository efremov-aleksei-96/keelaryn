---
id: system.workspace
type: system
status: active
workspace_protocol: keelaryn.workspace.v1
updated: {{DATE}}
---

# Keelaryn Detached Workbench Protocol

Use a detached workbench when sustained topic work benefits from a smaller self-contained context without carrying the whole Hub.

```text
approved Hub -> WORKSPACE CHECKOUT -> detached workbench -> RETURN PACKET -> Hub-aware worker -> CANDIDATE -> Chat Manager -> APPROVED
```

Checkout/return packets are context-transfer objects, not canonical artifacts and never belong in Local Manager `_inbox`.

## WORKSPACE CHECKOUT

Required header:

```text
KEELARYN__HUB WORKSPACE CHECKOUT
schema: keelaryn.workspace.v1
packet_role: checkout
created: YYYY-MM-DD
scope: <topic>
baseline_system_version: <version>
baseline_data_revision: <revision>
baseline_artifact_id: <artifact id>
baseline_payload_content_sha256: <hash>
```

Include all task-relevant authoritative state, constraints, relevant history/negative knowledge, open items, uncertainty, provenance and workbench instructions. Exclude unrelated Hub state.

## Detached workbench

The workbench may research, reason, draft and create ordinary artifacts from the checkout plus new evidence. It must not claim that Keelaryn__Hub itself was persisted or checkpointed.

## RETURN PACKET

Use the same baseline identity fields and return only durable delta: new facts/evidence, decisions, completed actions, supersessions, explicit deletion requests, artifacts/references and unresolved conflicts.

A Hub-aware worker ingests the packet against its **current approved** checkpoint. If canonical state advanced, reconcile/rebase the delta; never restore the old checkout snapshot wholesale. Any persistent result still uses the normal CANDIDATE -> APPROVED -> CURRENT chain.
