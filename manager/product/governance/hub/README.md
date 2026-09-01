---
id: system.readme
type: system
status: active
updated: {{DATE}}
---

# Keelaryn__Hub

Canonical long-term state managed through Keelaryn's checkpoint workflow.

## Operating model

- Markdown under Areas, Projects, Records and Resources is canonical user-owned state.
- `_System/INSTANCE.json` is the stable instance identity.
- `_System/STATE.md` declares the active system/revision/protocol contract.
- `_System/INDEX.json`, `_System/ROUTER.json`, `_System/MANIFEST.json` and `_System/VALIDATION.json` are deterministic derived metadata.
- `_System/ARTIFACT.json` identifies the current checkpoint and its bounded lineage.

Persistent changes follow:

```text
approved CURRENT -> worker CANDIDATE -> Chat Manager APPROVED -> Local Keelaryn__Manager -> new CURRENT
```

For ordinary navigation open [[HOME]]. For worker startup read [[_System/BOOTSTRAP]]. For governance and revision semantics read [[_System/PROTOCOL]]. For detached topic work use [[_System/WORKSPACE]].

Local deployment state such as `.obsidian/**` is intentionally outside portable checkpoint identity.
