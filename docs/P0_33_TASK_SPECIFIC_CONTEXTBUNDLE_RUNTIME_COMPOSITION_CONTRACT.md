# P0-33 — Task-specific ContextBundle runtime composition

Date: 2026-09-29
Status: **FIRST PRODUCT SLICE**

## Goal

Compose the qualified P0-32 local executable/search runtime with the already-qualified P0-18 ContextBundle builder:

```text
literal FTS query
→ ordered exact Artifact/Revision hits
→ current Inventory exact-match gate
→ deterministic current read locator
→ bounded ContextBundle extraction
→ exact provenance recheck
→ ephemeral task-specific bundle
```

No durable semantic state, identity rule, protocol server or corpus mutation is introduced.

## Runtime command

```text
keelaryn context-bundle \
  --root <corpus> \
  --state-db <state.db> \
  --search-db <search.db> \
  --query <literal terms> \
  --reason <task reason>
```

Optional `--limit` and `--max-bytes` remain bounded.

## Authority rules

A search hit is not enough to read corpus content.

For every hit:

1. the current COMPLETE local source boundary is replay-proved;
2. current Inventory must contain the exact same ArtifactID + RevisionID;
3. the P0 local extractor identity must match;
4. the first locator in deterministic current Inventory order is selected only as a read locator;
5. ContextBundle extraction revalidates exact Revision ContentEvidence;
6. returned bundle ArtifactID/RevisionID/extractor provenance must equal the search hit;
7. EXTRACTED/OPAQUE outcomes with fresh bytes must also match exact ContentEvidence; qualified bounded outcomes such as LIMIT_EXCEEDED may carry no fresh evidence and no text;
8. STALE_REVISION fails closed as corpus change;
9. the complete local source boundary is replay-proved again after all bundle reads.

If any hit is historical/stale relative to current Inventory, P0-33 fails closed instead of substituting another Revision or silently skipping the hit.

## Multiple current locators

One Artifact/Revision may have multiple current locators, for example hard links.

P0-33 uses the first locator in the already deterministic Inventory order as the read path. This is a runtime read-locator choice only. It does not make path part of Artifact identity and does not merge/split Artifacts.

## Interruption and mutation

The bundle is ephemeral and non-authoritative. P0-33 does not write bundle state.

The runtime requires existing state/search databases before opening the ContextBundle path, preventing a mistyped read command from creating an empty state or search database.

Corpus bytes remain read-only.

## Explicitly out of scope

- durable ContextBundle storage;
- inferred task semantics;
- vector/embedding retrieval;
- post-bootstrap rescan/reconciliation;
- live remote/provider runtime;
- MCP/HTTP/web;
- Android qualification;
- physical corpus mutation.

H3 filesystem protection and H4 Doctor/SelfTest remain production/user-runtime gates.

## Qualification targets

- search hit order is preserved in bundle order;
- every item preserves exact Artifact/Revision/extractor/evidence provenance;
- historical/non-current Revision substitution is forbidden;
- deterministic multiple-locator selection does not redefine identity;
- changed corpus boundary aborts without returning a stale bundle;
- missing read-side state DB is not created;
- one executable exposes the ContextBundle path;
- exact-head Ubuntu 24.04 and Windows 2025 CI pass.


## Pre-qualification bounded-outcome correction

The initial slice compared ContentEvidence for every ContextBundle item. That was too strict for the already-qualified builder contract: `LIMIT_EXCEEDED` and `UNSUPPORTED` deliberately preserve exact Artifact/Revision/extractor provenance without reading bytes and therefore carry no fresh ContentEvidence.

P0-33 now preserves those bounded outcomes instead of misclassifying them as provenance corruption. `STALE_REVISION` remains fail-closed and does not return a stale task bundle.
