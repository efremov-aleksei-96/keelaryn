# Keelaryn ChatGPT setup

Keelaryn is local-first. ChatGPT does not automatically read or modify your Hub. Exchange with ChatGPT is explicit and artifact-based.

## Standard setup

A normal Keelaryn user creates exactly these three ChatGPT Projects:

1. `Keelaryn — Workspace`
2. `Keelaryn — Chats`
3. `Keelaryn — Chat Manager`

This is the complete standard setup.

Optional for contributors and Keelaryn system development:

4. `Keelaryn — Manager Development`

Manager Development is not a more advanced normal-user mode. It is for changes to Manager, protocols, formats, generic tooling, validation, release engineering, public distribution, or other system-level behavior.

## Exchange folder

Manager 4.13 uses one user-facing exchange root:

```text
exchange\
└── chatgpt\
    ├── workspace-input\
    ├── workspace-checkouts\
    ├── chat-returns\
    ├── chat-manager-input\
    ├── chat-manager-results\
    └── development\
```

Use the Manager `ChatGPT` menu to prepare CURRENT for Workspace or Chat Manager, open the exchange folder, and reopen this guide.

## Canonical artifact flow

```text
CURRENT
  -> Workspace
  -> WORKSPACE_CHECKOUT
  -> Chats
  -> HUB_RETURN / HUB_RETURN_INTERIM
  -> Chat Manager
  -> APPROVED
  -> local Manager installs APPROVED
  -> next CURRENT
```

Workspace and Chats never make their conclusions canonical. Chat Manager reconciles proposed Hub changes. Only the local Manager installs a validated APPROVED result into CURRENT.

## Project instructions

Copy the complete contents of the matching file into the corresponding ChatGPT Project instructions:

- `WORKSPACE_PROJECT_INSTRUCTIONS.md`
- `CHATS_PROJECT_INSTRUCTIONS.md`
- `CHAT_MANAGER_PROJECT_INSTRUCTIONS.md`
- `MANAGER_DEVELOPMENT_PROJECT_INSTRUCTIONS.md` (optional)

## Start a Workspace chat

First use Manager `ChatGPT -> Prepare Workspace session`.

Attach:

```text
exchange\chatgpt\workspace-input\Keelaryn__Hub_CURRENT.zip
```

Minimum launch prompt:

```text
Initialize this Keelaryn Workspace session from the attached CURRENT. Show the current routines, projects and queue, help me choose a scope, then produce the minimum sufficient scoped checkout.
```

Save the checkout under:

```text
exchange\chatgpt\workspace-checkouts
```

Then continue the task in `Keelaryn — Chats`.

## Start a Chats task

Attach the scoped checkout from:

```text
exchange\chatgpt\workspace-checkouts
```

plus only task-specific evidence.

Minimum launch prompt:

```text
Continue this Keelaryn scoped task from the attached checkout. Treat it as bounded context, not authority to change canonical Hub state. When useful, produce a return artifact for Chat Manager.
```

Save return artifacts under:

```text
exchange\chatgpt\chat-returns
```

## Start a Chat Manager chat

First use Manager `ChatGPT -> Prepare Chat Manager session`.

Attach CURRENT from:

```text
exchange\chatgpt\chat-manager-input\Keelaryn__Hub_CURRENT.zip
```

and the RETURN/CANDIDATE artifacts to reconcile from:

```text
exchange\chatgpt\chat-returns
```

Minimum launch prompt:

```text
Operate as Keelaryn Chat Manager. Treat CURRENT as canonical and every RETURN/CANDIDATE artifact as proposed state. Validate ancestry and conflicts, reconcile only supported changes, validate the result, and emit APPROVED or a precise rejection/blocker.
```

Save successful results under:

```text
exchange\chatgpt\chat-manager-results
```

Then import/install the APPROVED package through Keelaryn Manager.

## Manager Development

For a continuation chat, attach the newest Manager Development handoff plus only the engineering context needed for the current task: AI_CONTEXT, exact source files, a gate/test pack, sanitized diagnostics, or release metadata.

Save development exchange artifacts under:

```text
exchange\chatgpt\development
```

## Legacy `Inputs_outputs`

If an older local installation contains:

```text
Inputs_outputs
```

use the Manager ChatGPT migration action. Migration is copy-only, rejects reparse points, verifies every copied file with SHA-256, and never deletes the legacy source.