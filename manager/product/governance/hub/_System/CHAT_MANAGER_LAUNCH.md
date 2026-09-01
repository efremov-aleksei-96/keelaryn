---
id: system.chat-manager-launch
type: system
status: active
updated: {{DATE}}
---

# Keelaryn Chat Manager Launch

Use this file to initialize a dedicated reconciliation chat.

1. Attach the current approved `Keelaryn__Hub_CURRENT.zip` (or equivalent latest APPROVED checkpoint).
2. Attach one or more pending `Keelaryn__Hub_CANDIDATE_*.zip` packages to reconcile.
3. Instruct the chat to operate as **Keelaryn Chat Manager** under `_System/CHAT_MANAGER.md` and `_System/PROTOCOL.md`.
4. The Manager must not treat a CANDIDATE as canonical merely because it is newer or has a higher revision number.
5. Output only a complete APPROVED checkpoint when lineage, semantics, integrity and instance identity are resolved; otherwise report the blocking ambiguity/conflict.
