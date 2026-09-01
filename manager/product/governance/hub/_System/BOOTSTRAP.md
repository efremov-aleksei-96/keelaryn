---
id: system.bootstrap
type: system
status: active
updated: {{DATE}}
---

# Keelaryn__Hub Fast Bootstrap

Minimal operating contract for ordinary Hub-aware worker chats. Full governance is in [[_System/PROTOCOL]].

## Authority

For factual conflicts use this order:

1. explicit current user correction;
2. fresh primary evidence supplied by the user;
3. current canonical Markdown;
4. recent durable Records/evidence;
5. historical/superseded material;
6. derived metadata;
7. model memory or old chat context.

Never silently resolve a material conflict. Preserve uncertainty explicitly. Never delete, discard or irreversibly replace canonical information without explicit user authorization.

Secrets such as passwords, private keys, recovery codes, seed phrases and TOTP secrets do not belong in Keelaryn__Hub.

## Fast read path

1. `_System/ARTIFACT.json`;
2. `_System/STATE.md`;
3. `_System/ROUTER.json`;
4. `_System/VALIDATION.json` when present;
5. only the canonical Markdown needed for the concrete task.

For a bare launch, use `Projects/QUEUE.md` and project metadata to offer actionable work. Do not preload the whole vault.

Use `_System/INDEX.json` for graph-wide discovery, ambiguity resolution or audits. Use `_System/PROTOCOL.md` for architecture, migration, deletion, conflicts, artifact semantics or Manager work.

## Canonical refresh

A valid newer APPROVED/CURRENT attachment is a hard rebase event. It becomes the worker's new canonical baseline. A CANDIDATE never becomes canonical merely by being attached.

When canonical state advances, preserve still-unpersisted user evidence deliberately and reapply or flag it against the new base rather than silently carrying an obsolete file tree forward.

## Persistent writes

After material persistent work, update only relevant canonical files, rebuild derived metadata, and emit a complete CANDIDATE from the exact currently approved base. CANDIDATEs are non-canonical until reconciled by Chat Manager.

For sustained topic work outside the Hub-aware chat, use [[_System/WORKSPACE]].
