---
id: system.glossary
type: system
status: active
updated: {{DATE}}
---

# Keelaryn Glossary

- **Area** — long-lived domain of responsibility or state.
- **Project** — finite outcome or bounded recurring work cycle.
- **Record** — durable evidence, event, decision or snapshot.
- **Resource** — reusable reference material.
- **Canonical checkpoint** — accepted complete state of one Hub instance.
- **CANDIDATE** — non-canonical proposed checkpoint.
- **APPROVED** — checkpoint accepted by Chat Manager or an explicitly authorized Manager migration/Genesis role.
- **CURRENT** — Local Manager's installed alias of the accepted canonical checkpoint.
- **instance_id** — stable UUID of one Hub instance.
- **artifact_id** — identity of one checkpoint artifact.
- **payload hash** — deterministic identity of checkpoint content excluding ARTIFACT transport metadata and local deployment state.
- **source manifest** — deterministic list/hash of portable canonical source files excluding derived metadata.
- **hard rebase** — replacement of a worker's old in-chat canonical baseline by a newer valid APPROVED/CURRENT checkpoint.
- **detached workbench** — ordinary non-canonical chat operating from a scoped checkout packet.
