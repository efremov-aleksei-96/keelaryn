# Using Keelaryn with ChatGPT

Keelaryn is local-first. ChatGPT does not automatically read or modify your Hub. You explicitly choose what checkpoint, project handoff or candidate package to attach.

There are two different AI workflows. Keeping them separate protects the canonical Hub.

## 1. Normal project / worker chat

Use a worker chat when you want to work on one concrete project or task.

A good starting point is to attach the current Hub checkpoint or only the relevant project material, then tell ChatGPT which project you want to work on. The Hub contains `Resources/Prompts/WORKER_CHAT.md`, which defines the intended bounded worker-chat behavior.

A simple first-session prompt is:

```text
I use Keelaryn. Read the attached Hub material and the Keelaryn worker-chat instructions before doing project work.

First, summarize only the active project I name and the minimum context needed for it. Do not treat proposed edits as canonical Hub state. When we finish, produce a clear return/handoff package or candidate change set that can be reconciled later.
```

For a new Hub, start with one project rather than loading every long-lived area into the conversation.

## 2. Chat Manager / reconciliation

Chat Manager is the stricter workflow used to reconcile proposed changes back into canonical Hub state.

Use it when you have:

- the current approved `Keelaryn__Hub_CURRENT.zip` (or equivalent current checkpoint);
- one or more pending `Keelaryn__Hub_CANDIDATE_*.zip` packages or return packages;
- a need to decide what becomes the next approved Hub state.

The Hub contains:

```text
_System\CHAT_MANAGER.md
_System\CHAT_MANAGER_LAUNCH.md
_System\PROTOCOL.md
```

A suitable launch instruction is:

```text
Operate as Keelaryn Chat Manager. Read _System/CHAT_MANAGER.md, _System/CHAT_MANAGER_LAUNCH.md and _System/PROTOCOL.md from the attached current Hub before reconciling anything.

Treat CURRENT as canonical. Treat every CANDIDATE or return package as proposed state only. Preserve instance identity and lineage. If the inputs are ambiguous or conflicting, report the blocker instead of inventing canonical state.
```

Do not use Chat Manager merely as a general brainstorming chat. Its job is controlled reconciliation.

## 3. What to upload

Prefer the smallest artifact that still preserves the required invariants:

- one project handoff for ordinary focused work;
- current Hub checkpoint when broad Hub context is genuinely needed;
- CURRENT + pending CANDIDATEs for reconciliation.

Avoid uploading credentials, password databases, private keys, recovery material or unrelated personal files.

## 4. Returning changes to Keelaryn

The safe lifecycle is:

```text
CURRENT
   ↓
worker/project work
   ↓
return package / CANDIDATE
   ↓
Chat Manager reconciliation
   ↓
APPROVED
   ↓
Manager installs validated APPROVED Hub update
   ↓
new CURRENT
```

A newer revision number alone does not make a candidate canonical. Reconciliation and Manager validation remain separate gates.

## 5. Context efficiency

For Manager development, prefer generated `AI_CONTEXT` or task-specific source routes instead of uploading the entire Manager runtime. For personal Hub work, prefer project-specific handoffs over repeatedly loading the entire Hub when the task does not require it.
