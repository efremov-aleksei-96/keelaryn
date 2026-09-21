# Keelaryn Zero-Based Architecture — Corpus-first

Status: **current canonical product architecture**

This document defines the active zero-based architecture for Keelaryn. Earlier Hub-first r2 material remains available through Git history and legacy product/provenance files, but it is not an active architectural authority.

## 1. Fundamental model

Keelaryn is **Corpus-first**.

The durable user corpus consists of the real physical objects that already exist in user-controlled storage and providers: files, directories and provider objects such as PDF, DOCX, XLSX, Google Docs/Sheets, JPG, audio, video, executables, archives, encrypted containers and other real artifacts.

Keelaryn does not require a second complete authoritative content mirror. It manages knowledge about the corpus:

- artifact identity;
- physical locators and provider identity;
- fingerprints and content revisions;
- observations;
- semantic classifications and relations;
- validation;
- transactions and provenance;
- recovery/reconstruction knowledge;
- indexes, views, previews and AI context.

Derived extraction, Markdown, summaries, indexes, previews, semantic views and AI_CONTEXT are rebuildable/non-authoritative unless a user separately creates one as an independent durable artifact.

A PDF remains a PDF, a DOCX remains a DOCX, a JPG remains a JPG. Keelaryn does not make a transformed copy authoritative merely because that copy is easier for software or AI to read.

Physical organization and semantic organization are independent.

## 2. Layered authority model

Corpus-first does **not** mean that physical files are the only authority in the system. Authority is layered by the kind of fact being represented.

### 2.1 Physical corpus object authority

Physical corpus objects are authoritative for:

- object existence;
- the bytes/content actually stored by the provider;
- the physical object that identity refers to;
- the object's current physical locator/provider location.

Keelaryn may maintain durable identity, revision and locator records about those objects, but those records describe the physical corpus and must reconcile to physical evidence.

Path is not artifact identity.

Content hash is not artifact identity.

Provider object ID is not a global Keelaryn identity.

A rename/move with proven continuity preserves the Artifact. A content modification creates a new revision of the same Artifact. A copy creates a new Artifact even when bytes are identical. Identical hashes do not authorize automatic identity merge, deduplication or deletion.

### 2.2 Project/workspace operational-state authority

An explicit project or workspace STATE record remains authoritative for the operational/current state owned by that project or workspace.

Examples include:

- current project phase;
- completed and pending work;
- decisions owned by the project;
- project-local working assumptions;
- next action;
- reconciliation/checkpoint state.

This operational authority does not replace the physical corpus object. A project STATE can say that a document is currently under review; it cannot redefine the document's bytes, erase its physical existence, or make a nonexistent physical mutation true.

Project truth should be referenced, not copied into a competing global canonical record.

### 2.3 LifeOS authority

LifeOS is a separate permanent master/life-orchestration workspace.

LifeOS is authoritative only for its cross-life orchestration semantics, such as relationships among life domains, priorities, cross-project coordination and master-level operational context that LifeOS itself owns.

LifeOS does **not** become part of the Keelaryn engine and does not copy or replace project-owned truth. It references project/workspace state where project truth is needed.

Keelaryn may index, classify, locate and relate LifeOS artifacts like other corpus material, but Keelaryn does not become the owner of LifeOS semantics.

### 2.4 Keelaryn control/semantic-plane authority

Keelaryn's control/semantic plane stores compact system knowledge required to manage and understand the corpus, including:

- inventory/indexes;
- fingerprints;
- Artifact identities and observations;
- revision knowledge;
- current locators;
- relations;
- classifications;
- accepted semantic facts and their provenance;
- ambiguity;
- derived state;
- transaction records;
- validation/reconciliation state;
- rollback and recovery metadata;
- extraction/preview/index metadata;
- task-specific AI context.

This plane is not a second content corpus and must not become a mandatory full mirror of user content.

The control plane can be authoritative for Keelaryn's own transaction/recovery state and accepted metadata, while the underlying physical object remains authoritative for its existence and physical content.

AI inference does not become an accepted durable semantic fact automatically. Ambiguity is a valid first-class state.

### 2.5 Semantics versus physical location

Semantic classification never overrides the underlying physical object.

At the same time, physical location alone does not define the object's complete semantic meaning.

A file can physically live under one directory while participating in multiple semantic dimensions such as People, Organizations, Areas, Events, Facts or Projects. These dimensions are semantic relations/views, not mandatory physical directories.

No rule may infer that moving a file between directories automatically changes every semantic fact about that Artifact.

## 3. Managed corpus physical profile

The initial managed-root profile is:

```text
<Managed Root>/
├── 0__Core/
│   └── __Keelaryn/
├── 1__Inbox/
├── 2__Project/
├── 3__Records/
├── 8__Library/
└── 9__Archive/
```

`0__Core/__Keelaryn` is the small Keelaryn control/semantic state plane. It is not a content Hub and not a full copy of the corpus.

"Core" means machinery/control plane, not "important user files."

Areas, People, Organizations, Events, Facts and similar semantic dimensions are not required top-level directories.

The physical profile is a useful initial convention, not a requirement that arbitrary existing user corpora be destructively normalized before Keelaryn can observe them.

## 4. Legacy Hub boundary

The old production Hub is **legacy runtime state and provenance only**.

Its allowed active role before the r0005 → r0007 control cutover is strictly limited to pre-cutover safety observation of the existing production boundary.

The following legacy facts may be read to prove a safe cutover boundary:

- production `current`;
- `control-current`;
- installed Operation Control release/unit identity;
- writer service state;
- legacy Hub selector;
- legacy Hub PREPARED transaction identity;
- mutation-inhibit identity;
- credential identity/fingerprint where safely observable.

That observation is a **runtime safety check**, not content authority.

The old Hub has no authority over:

- physical corpus object existence/content/identity/location;
- project/workspace operational STATE;
- LifeOS cross-life orchestration semantics;
- the new Keelaryn semantic/control model.

Explicitly forbidden:

- importing old Hub `Areas / Projects / Records / Resources` as the new canonical structure;
- restoring Hub-first architecture;
- reconciling Google Drive corpus semantics/content against the old Hub as authority;
- changing Google Drive corpus because the old Hub says it should look different;
- treating legacy selector/current as the future content model;
- retaining a permanent new-runtime dependency on legacy Hub simply because that dependency existed before cutover.

After a safe r0005 → r0007 cutover, dependency on the legacy Hub must decrease, not become entrenched.

The old Hub-first r2 line is `PROVENANCE_RESEARCH_ONLY`. Frozen old-architecture candidates are not resumed as a product direction.

## 5. Legacy Hub safety observation versus authority

The distinction is normative:

```text
Fresh read-only legacy Hub/VPS reconcile before control cutover
    = ALLOWED SAFETY OBSERVATION

Legacy Hub as canonical content/semantic/project/LifeOS authority
    = FORBIDDEN
```

A successful legacy-runtime reconcile proves only that the control-plane transition can occur safely from the observed predecessor state. It does not validate or adopt legacy Hub semantics into Corpus-first Keelaryn.

## 6. Minimal identity model

Minimum distinct concepts:

```text
Artifact identity
Physical locator / provider identity
Content revision
Observation
```

An observation records what Keelaryn observed about a physical object at a point in time.

A locator says where/how an Artifact is physically accessible; it is not the Artifact itself.

A revision represents observed content state for an Artifact.

Identity continuity must be evidence-based. If continuity cannot be proven, ambiguity is retained instead of silently merging identities.

## 7. Observation and derived state

Read-only discovery precedes mutation.

Discovery may collect:

- locator;
- provider object metadata;
- size;
- timestamps where meaningful;
- fingerprints/hashes;
- MIME/type;
- extraction capability;
- safe structural metadata.

Discovery must not normalize, move, rename, delete, deduplicate, merge identities or accept semantic inference merely to make the corpus look cleaner.

Opaque, encrypted or currently unsupported content is still a valid corpus object. Unsupported extraction is not equivalent to nonexistent content.

Derived state must be rebuildable from the corpus plus accepted durable metadata whenever feasible.

## 8. Safe mutations

Any future physical corpus mutation follows:

```text
capture prestate
→ validate identity
→ validate destination
→ prepare rollback
→ revalidate at mutation boundary
→ mutate
→ verify physical result
→ commit metadata
→ retain provenance
```

Metadata must never claim that a physical mutation completed before the physical result has been verified.

Same-hash objects do not authorize automatic deletion or merge.

No P0 physical normalization, deduplication or destructive migration is required merely to make Keelaryn usable.

## 9. Development Level 0 — autonomous engineering

Before Product P0, D0 establishes autonomous engineering.

A fresh ChatGPT chat must be able to reconstruct exact development state from durable external authority and continue with minimal maintainer involvement.

Authority for development operations:

```text
GitHub
    source code
    branch/HEAD
    architecture/specifications
    CI
    development history

VPS
    controlled runtime/integration state
    production-specific state

Google Drive / other corpus providers
    real corpus
    provider/corpus-specific evidence

ChatGPT
    engineer/orchestrator
    not durable state storage
```

After interruption:

1. resolve GitHub branch/HEAD live;
2. read durable development state;
3. reconcile relevant VPS/provider evidence;
4. determine what completed durably;
5. continue only from the first uncompleted step;
6. never blindly retry a possible durable mutation.

## 10. Product P0

After D0, the minimum useful product path is:

```text
Physical Corpus
↓
read-only discovery
↓
inventory
↓
Artifact identity
↓
current locator
↓
basic observation/revision
↓
minimal extraction
↓
task-specific AI context
```

P0 may explicitly leave difficult reconstruction, metadata-loss recovery, chaotic-corpus adoption, migrations and advanced multi-provider cases unsupported.

Future requirements must remain architecturally possible, but they do not block a minimal coherent happy path unless required for correctness or data safety.

## 11. Build order

Build bottom-up:

1. minimal coherent happy path;
2. reliability;
3. validation;
4. reconciliation;
5. safe mutations;
6. rollback/interruption recovery;
7. metadata-loss recovery;
8. reconstruction;
9. unmanaged/chaotic corpus adoption;
10. normalization/migrations;
11. advanced multi-root/provider support.

Do not front-load a maximal ontology or recovery system into P0.

## 12. GitHub-first qualification discipline

Normal development occurs on `dev/**`.

```text
qualified base
→ dev/**
→ remote development + CI
→ coherent development PASS
→ candidate freeze
→ Source/Full Gate
→ production-specific acceptance
→ main/release
```

A green development CI run is not a candidate. A candidate gate PASS is not production qualification. Production-specific mutation requires fresh production-boundary evidence.

Frozen candidate product bytes are immutable. If product bytes change, issue a new candidate/version. Gate/evidence-only changes use a new gate revision rather than silently changing the frozen candidate.

## 13. Current pre-cutover rule

The current production control successor is r0007. Its frozen product direction is Corpus-first.

Before any r0007 production bootstrap:

1. prove the installed r0005 read-only control channel is alive and source-bound;
2. perform a fresh strictly read-only legacy-runtime reconcile;
3. require the observed predecessor boundary to match the permitted cutover prestate;
4. do not inspect legacy Hub content as semantic authority;
5. do not mutate Google Drive or other corpus content;
6. only a later separately authorized transaction may perform the control-plane cutover.

The purpose of this reconcile is only to make the runtime transition safe.

## 14. Legacy material

Legacy Manager 4.x, Hub 2.x, old Hub-first architecture documents, legacy `hub/` content and old gate/update tooling remain available as provenance/research material unless a specific reusable mechanism is deliberately requalified.

No legacy mechanism or semantic model becomes part of the new architecture merely because it already exists.

Git history is the durable record of superseded architecture; the current canonical architecture does not need to preserve contradictory Hub-first rules inline.
