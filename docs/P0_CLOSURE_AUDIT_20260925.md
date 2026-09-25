# P0 Closure Audit — 2026-09-25

Status: **P0 NOT CLOSED**

Authority: this is an implementation/evidence audit. `KEELARYN_CANONICAL.md` remains the sole product architecture authority.

## Required P0 path

| Canonical capability | Status | Active-line evidence / gap |
|---|---|---|
| one existing corpus root | QUALIFIED | localfs provider snapshots a user-selected root |
| read-only discovery | QUALIFIED | localfs Snapshot; symlinks not followed |
| durable ProviderObject/Locator observations | PARTIAL | append-only occurrences/observations/locators are durable; localfs native identity intentionally remains process-local/unresolved |
| Artifact identity | PARTIAL | explicit first-observation bootstrap creates durable Artifacts; post-bootstrap continuity is not yet durably applied |
| Revision continuity | PARTIAL | Revision semantics and durable history are qualified; no end-to-end post-bootstrap continuity commit path yet |
| inventory | QUALIFIED | latest COMPLETE scan is authoritative; OPEN/ABORTED ignored |
| minimal extraction | QUALIFIED | bounded revision-bound UTF-8 text/Markdown extraction |
| SQLite FTS search | ABSENT | no FTS schema/query implementation in active tree |
| task-specific ContextBundle | QUALIFIED | explicit-selection derived bundle with exact Artifact/Revision/source provenance |
| MCP/HTTP/CLI access | ABSENT as product access surface | active tree has no inventory/search/context API endpoint or usable product CLI surface |

## Canonical P0 proof cases

| Proof | Status | Reason |
|---|---|---|
| unchanged rescan -> same Artifact and Revision | ABSENT end-to-end | candidate/evidence model exists but resolved continuity is not committed to the next observation |
| rename/move with strong evidence -> same Artifact/Revision, new Locator | PARTIAL | in-process native matching can discover an AMBIGUOUS candidate; no conclusive provider path + no commit path |
| content modification -> same Artifact, new Revision | PARTIAL | Revision engine proves A->B semantics, but scan reconciliation cannot yet assign the modified occurrence to the existing Artifact |
| true copy -> new Artifact despite identical bytes | QUALIFIED for adoption semantics | bootstrap identical independent files become distinct Artifacts with identical content evidence |
| ambiguous continuity -> explicit ambiguity, no silent merge | QUALIFIED | candidate set and ingestion remain unresolved without conclusive evidence |
| unsupported content -> valid Artifact + unsupported extraction | QUALIFIED | bootstrap identity exists; extractor returns UNSUPPORTED without reading unsupported type |
| restart -> exact durable identity state resumes | QUALIFIED | SQLite reopen tests preserve Artifact/Revision/Observation/inventory authority |
| derived extraction/index rebuild without identity change | PARTIAL | extraction is rebuildable/non-mutating; FTS index not implemented yet |
| ContextBundle cites exact Revision/source evidence | QUALIFIED | P0-18 |
| corpus bytes unchanged by P0 operations | QUALIFIED for implemented local path | discovery, reconciliation, extraction and context operations are read-only against corpus |

## P0 technology-spike checklist

| Spike item | Status |
|---|---|
| one Go executable direction | PARTIAL — Go cmd exists, but product access surface is not yet useful |
| SQLite state | QUALIFIED |
| local read-only scan | QUALIFIED |
| one rclone-backed remote scan | ABSENT |
| provider/native identity evidence preserved | PARTIAL — process-local localfs evidence only |
| FTS query | ABSENT |
| minimal MCP endpoint | ABSENT |
| embedded minimal web status page | ABSENT |

## Priority decision

Do **not** implement FTS/MCP/remote provider next merely because they are visible missing boxes.

The earliest incomplete correctness edge is:

`resolved continuity -> durable observation assignment -> same/new Revision -> accepted-decision provenance`.

Until that exists, post-bootstrap Artifact identity is not a complete product path.

Therefore the next objective is P0-20: a provider-neutral, fail-closed transaction that accepts only a uniquely `RESOLVED_SAME` candidate set, assigns the current observation to that existing Artifact, reuses or creates its Revision from current content evidence, and durably records the accepted continuity resolution/provenance in the same transaction.

After P0-20, add/prove a conclusive evidence source; then re-audit continuity proofs before FTS/search/access surfaces.
