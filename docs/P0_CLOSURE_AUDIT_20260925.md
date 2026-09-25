# P0 Closure Re-audit — 2026-09-25

Status: **P0 NOT CLOSED**

Authority: this document is an implementation/evidence audit. `KEELARYN_CANONICAL.md` remains the sole product architecture authority.

Evidence basis:
- authoritative branch: `dev/corpus-first-p0`;
- audited head: `77dc552482b79260fa8a5ad462dc42732c506f75`;
- exact-head CI: `36107693557` — validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS;
- P0-20 through P0-24 are now qualified and supersede the earlier audit's continuity/history gaps.

## Required P0 path

| Canonical capability | Current status | Active-line evidence / remaining gap |
|---|---|---|
| one existing corpus root | QUALIFIED | localfs provider can read a user-selected existing root without reorganizing it |
| read-only discovery | QUALIFIED | localfs Snapshot; corpus bytes are not mutated |
| durable ProviderObject/Locator observations | QUALIFIED FOR LOCAL INGEST | append-only occurrences, observations and locators are durable; localfs native object identity remains intentionally unresolved across durable gaps |
| Artifact identity | PARTIAL END-TO-END | bootstrap adoption is qualified; `RESOLVED_SAME` acceptance is qualified; there is still no safe post-bootstrap path that creates a new Artifact for a newly appearing/distinct occurrence |
| Revision continuity | PARTIAL END-TO-END | P0-20 atomically reuses/creates Revision once continuity is `RESOLVED_SAME`; provider evidence is not yet wired into a complete scan/reconcile/accept loop |
| inventory | QUALIFIED | latest COMPLETE scan is authoritative; OPEN/ABORTED scans are excluded |
| minimal extraction | QUALIFIED | bounded revision-bound UTF-8 text/Markdown extraction |
| SQLite FTS search | ABSENT | no FTS5 schema/query implementation in the active tree |
| task-specific ContextBundle | QUALIFIED | explicit-selection bundle with exact Artifact/Revision/source provenance |
| MCP/HTTP/CLI product access | PARTIAL | a minimal `scan` CLI exists, but there is no usable inventory/search/context product API surface yet |

## Provider/continuity state

### Local filesystem

Qualified:
- read-only discovery and durable complete-scan ingestion;
- first-observation Artifact adoption;
- candidate generation;
- selective content evidence;
- in-process native `os.SameFile` evidence;
- explicit ambiguity;
- atomic `RESOLVED_SAME` acceptance.

Important limitation:
- path, content equality and current local native evidence are intentionally not treated as durable conclusive identity across an observation gap;
- therefore local post-bootstrap continuity remains fail-closed when no stronger evidence exists.

### Google Drive / RemoteHistory

Qualified components:
- provider-native identity semantics for Drive file IDs;
- provider-neutral RemoteHistory contract;
- Google Drive fence -> enumerate -> catch-up -> terminal-cursor semantics;
- official `google.golang.org/api/drive/v3` binding;
- My Drive/shared-drive query binding;
- shortcut resource identity preservation;
- terminal cursor discipline;
- Ubuntu + Windows cross-platform qualification.

Still absent:
- a real remote discovery/ingest path that turns Drive objects/history into durable Keelaryn scan observations and reconciliation inputs;
- live OAuth/provider qualification;
- any Google Drive corpus mutation (correctly out of scope).

## Canonical P0 proof cases

| Proof | Current status | Reason |
|---|---|---|
| unchanged object rescanned -> same Artifact and Revision | PARTIAL COMPONENTS | same-continuity transaction exists, and Drive can supply conclusive continuity under continuous history, but no complete provider->reconcile->accept product loop is wired |
| rename/move with strong evidence -> same Artifact/Revision, new Locator | PARTIAL COMPONENTS | acceptance semantics are qualified; conclusive provider evidence and durable scan wiring are not yet connected end-to-end |
| content modification -> same Artifact, new Revision | PARTIAL COMPONENTS | P0-20 proves the atomic changed-content behavior after `RESOLVED_SAME`; end-to-end evidence/wiring remains |
| true copy -> new Artifact despite identical bytes | PARTIAL | first bootstrap preserves distinct copies, but a copy/new occurrence appearing after bootstrap cannot yet be safely admitted as a new Artifact |
| ambiguous continuity -> explicit ambiguity, no silent merge | QUALIFIED | supporting evidence alone cannot authorize identity mutation |
| unsupported content -> valid Artifact + unsupported extraction | QUALIFIED | identity survives unsupported extraction |
| restart -> exact durable identity state resumes | QUALIFIED | SQLite authority survives reopen and qualified migrations |
| derived extraction/index rebuild without identity change | PARTIAL | extraction is derived/rebuildable; FTS is not implemented |
| ContextBundle cites exact Revision/source evidence | QUALIFIED | P0-18 |
| corpus bytes unchanged by P0 operations | QUALIFIED FOR IMPLEMENTED PATHS | active discovery/reconciliation/extraction/history work is read-only against corpus; no live Drive mutation has occurred |

## Technology-spike checklist

| Spike item | Status |
|---|---|
| one Go executable direction | PARTIAL — executable exists; product access surface is still too narrow |
| SQLite state | QUALIFIED |
| local read-only scan | QUALIFIED |
| one real remote scan | ABSENT — Drive history adapter is qualified but not yet wired as a durable remote scan/provider path |
| provider/native identity evidence preserved | PARTIAL END-TO-END — Drive contract/history is qualified; local durable conclusive identity remains intentionally unavailable |
| FTS query | ABSENT |
| minimal MCP endpoint | ABSENT |
| embedded minimal web status page | ABSENT |

## Earliest remaining correctness gap

The previous audit identified `RESOLVED_SAME -> durable acceptance`; P0-20 closed that gap.

The next earlier correctness edge is now **post-bootstrap new-Artifact admission**.

Current asymmetry:
- `StartBootstrapScan + AdoptObservationInScan` may create Artifacts only when the provider/root has no prior observation history;
- `AcceptResolvedObservationInScan` may mutate identity only for a uniquely `RESOLVED_SAME` result;
- the candidate-set model has no accepted `RESOLVED_NEW` / first-known-object state;
- therefore a genuinely new file, a proven copy, or another newly appearing distinct provider object after bootstrap remains unresolved indefinitely.

This is a correctness gap before search/UI ergonomics. Implementing FTS/MCP first would make an incomplete identity lifecycle easier to query without completing it.

## Next objective

Define the smallest provider-neutral contract for **safe post-bootstrap new Artifact admission** before implementing it.

The contract must:
- never equate "no path candidate" with "new Artifact";
- require explicit evidence that the current occurrence has no accepted predecessor under the qualified scope/provider-history policy;
- preserve ambiguity when that proof is unavailable;
- create Artifact + initial Revision (when content evidence exists) + assigned Observation + non-rebuildable acceptance provenance atomically;
- distinguish "new Keelaryn Artifact because this is first known occurrence" from claims about physical creation time;
- preserve true-copy semantics: identical bytes do not imply same Artifact;
- remain compatible with later cross-root/cross-provider reconciliation.

After that contract and transaction are qualified, wire one conclusive provider path end-to-end (Google Drive is the current first candidate), then re-audit before FTS/search/access work.
