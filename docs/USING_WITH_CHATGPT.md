# Using Keelaryn with ChatGPT

Keelaryn is local-first. ChatGPT does not automatically read or modify your Hub. The supported workflow uses explicit exchange artifacts and three separate ChatGPT Projects so navigation, deep work and canonical reconciliation do not blur together.

## Standard setup

A normal Keelaryn user creates:

```text
Keelaryn — Workspace
Keelaryn — Chats
Keelaryn — Chat Manager
```

This is the complete standard configuration.

`Keelaryn — Manager Development` is optional and is only for contributors, forks, Keelaryn system development and defects that require changes to Manager/protocols/formats/tooling/validation/release behavior.

The generic Manager distribution includes copy-ready Project instruction templates and a setup guide under:

```text
manager\product\docs\chatgpt-projects
```

Manager 4.13 also provides a user-facing exchange root:

```text
exchange\chatgpt
```

Ordinary users do not need to enter `manager\state` to move ChatGPT artifacts around.

## 1. Workspace

Workspace is the Hub navigator and scoped-checkout generator.

Start a fresh Workspace chat with current canonical Hub state. In Manager, use `ChatGPT -> Prepare Workspace session`, then attach:

```text
exchange\chatgpt\workspace-input\Keelaryn__Hub_CURRENT.zip
```

Workspace reads CURRENT, shows the relevant routines/projects/queue, helps choose scope and exports the minimum sufficient canonical context as:

```text
KEELARYN__WORKSPACE_CHECKOUT_<scope>_<date>.md
```

Save it under:

```text
exchange\chatgpt\workspace-checkouts
```

Workspace should not become the deep execution environment and must not claim proposed changes are canonical.

## 2. Chats

Chats is the deep task-execution environment.

Start from the scoped checkout plus only task-specific evidence. Perform the actual research, reasoning, planning, writing or analysis there.

When work should return to Hub, emit one of:

```text
KEELARYN__HUB_RETURN_<scope>_<date>.md
KEELARYN__HUB_RETURN_<scope>_INTERIM_<date>.md
```

Save returns under:

```text
exchange\chatgpt\chat-returns
```

Chats must distinguish canonical facts from new evidence/inference/proposals and must not issue APPROVED.

## 3. Chat Manager

Chat Manager is the controlled reconciliation layer.

In Manager, use `ChatGPT -> Prepare Chat Manager session`, then attach:

```text
exchange\chatgpt\chat-manager-input\Keelaryn__Hub_CURRENT.zip
```

plus the RETURN/CANDIDATE artifacts for one coherent batch.

Chat Manager treats CURRENT as canonical and every RETURN/INTERIM/CANDIDATE as proposed state. It validates ancestry, conflicts and invariants, reconciles supported changes, validates the result, then emits APPROVED or a precise blocker.

Successful output is:

```text
Keelaryn__Hub_APPROVED_*.zip
```

Save it under:

```text
exchange\chatgpt\chat-manager-results
```

Only the local Keelaryn Manager installs validated APPROVED into the next CURRENT.

## 4. End-to-end lifecycle

```text
CURRENT
   ↓
Workspace
   ↓
scoped WORKSPACE_CHECKOUT
   ↓
Chats
   ↓
HUB_RETURN / HUB_RETURN_INTERIM
   ↓
Chat Manager reconciliation
   ↓
APPROVED
   ↓
local Manager validation/install
   ↓
new CURRENT
```

A newer revision number alone never makes a proposal canonical.

## 5. Manager Development

Use the optional Manager Development Project only when the work changes Keelaryn itself: Manager runtime/architecture, protocols/formats, generic UX/tooling, Doctor/SelfTest, update/rollback/migrations, release engineering, public GitHub/CI, supply-chain identity or other system-level behavior.

A continuation chat normally needs the latest Manager Development handoff plus only task-specific engineering context such as AI_CONTEXT, exact source files, a gate/test pack, sanitized diagnostics or release metadata.

Do not use personal Hub content as generic Manager source or fixtures.

## 6. Legacy `Inputs_outputs`

Older local installations may contain a manual `Inputs_outputs` exchange folder. Manager 4.13 treats it as a migration source, not canonical product layout. The supported migration is copy-only and hash-verified; the legacy source is not deleted automatically.

## 7. Security and context efficiency

Prefer the smallest artifact that preserves required invariants. Do not upload credentials, password databases, private keys, recovery material or unrelated personal files.

For Manager development, prefer generated AI_CONTEXT or exact task-specific source routes over repeatedly loading the complete runtime. For Hub work, prefer Workspace-generated scoped checkouts over loading the entire Hub into every task chat.