---
id: prompt.workspace-checkout
type: resource
status: active
updated: {{DATE}}
---

# Workspace Checkout

Create the minimum sufficient `KEELARYN__HUB WORKSPACE CHECKOUT` for a detached Keelaryn — Chats workstream from canonical CURRENT.

Follow `_System/WORKSPACE.md` and preserve `schema: keelaryn.workspace.v1`.

When scope maps to exactly one canonical project:

1. use ROUTER only as a locator if useful;
2. open the canonical project Markdown;
3. read its canonical `id` and Markdown H1;
4. emit:

```text
source_entity_id: <canonical entity id>
source_entity_title: <canonical Markdown H1>
suggested_chat_title: <canonical Markdown H1>
```

Canonical Markdown wins over filename, user alias/shortened wording and derived ROUTER title. If ROUTER and Markdown disagree, keep the Markdown title.

Only when the user explicitly requests a narrower workstream may the recommended title become:

```text
<canonical project title> — <explicit subscope>
```

Do not invent entity metadata when scope is ambiguous.

After producing the checkout artifact, always surface the recommendation directly:

```text
Chat title:
<suggested_chat_title>
```

Legacy `keelaryn.workspace.v1` packets without entity/title metadata remain readable; new entity-bound checkouts must emit all three metadata fields together.
