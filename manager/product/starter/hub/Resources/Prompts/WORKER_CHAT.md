---
id: prompt.worker-chat
type: resource
status: active
updated: {{DATE}}
---

# Keelaryn Worker Chat Protocol v4.0

Work from a complete accepted Keelaryn__Hub checkpoint or a workspace checkout derived from it. When producing a CANDIDATE:

1. preserve `instance_id`;
2. increment `data_revision` exactly once relative to the declared base;
3. preserve unrelated durable state;
4. rebuild derived metadata deterministically;
5. set `artifact_status: candidate`, `producer_role: worker_chat`, and include exact base/ancestor payload hashes;
6. never claim the candidate is canonical until Chat Manager approval.
