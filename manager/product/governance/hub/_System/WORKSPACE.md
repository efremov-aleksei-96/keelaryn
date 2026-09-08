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

Checkout/return packets are context-transfer objects, not canonical artifacts and never belong in Local Manager `state/inbox`.

## Canonical entity and chat-title invariant

When checkout scope maps to exactly one canonical Hub project, the checkout must identify that entity and derive its recommended detached-chat title from the canonical project Markdown.

Canonical authority order:

1. use `_System/ROUTER.json` or other derived metadata only as a locator when useful;
2. open the located canonical project Markdown;
3. read `id` and the Markdown H1 from that canonical file;
4. use the canonical H1 as `source_entity_title` and the default `suggested_chat_title`.

A filename, user alias/shortened phrase or ROUTER title must not override the canonical Markdown H1. If ROUTER and canonical Markdown disagree, canonical Markdown wins and the derived mismatch may be reported for later repair.

For a deliberately narrower workstream, an explicit suffix may be used:

```text
<canonical project title> — <subscope>
```

The unsuffixed canonical title is the default.

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

When scope maps to one canonical entity, also include:

```text
source_entity_id: <canonical entity id>
source_entity_title: <canonical Markdown H1>
suggested_chat_title: <canonical title or canonical title + explicit subscope suffix>
```

These fields are informational context-transfer metadata within `keelaryn.workspace.v1`; they do not create a new packet schema. Legacy `keelaryn.workspace.v1` checkout packets without the three fields remain readable. If any of the three fields is emitted, all three must be emitted together.

Include all task-relevant authoritative state, constraints, relevant history/negative knowledge, open items, uncertainty, provenance and workbench instructions. Exclude unrelated Hub state.

## User-facing handoff

After producing the checkout artifact, Workspace must surface the recommended title without requiring a separate question:

```text
Chat title:
<suggested_chat_title>
```

If checkout scope does not map unambiguously to one canonical entity, do not invent entity metadata or a canonical title. Resolve the ambiguity before claiming an entity-bound title.

## Detached workbench

The workbench may research, reason, draft and create ordinary artifacts from the checkout plus new evidence. It must not claim that Keelaryn__Hub itself was persisted or checkpointed.

## RETURN PACKET

Use the same baseline identity fields and return only durable delta: new facts/evidence, decisions, completed actions, supersessions, explicit deletion requests, artifacts/references and unresolved conflicts.

A Hub-aware worker ingests the packet against its **current approved** checkpoint. If canonical state advanced, reconcile/rebase the delta; never restore the old checkout snapshot wholesale. Any persistent result still uses the normal CANDIDATE -> APPROVED -> CURRENT chain.
