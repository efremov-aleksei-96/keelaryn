# Keelaryn — Canonical Product Architecture

**Status:** SOLE CURRENT PRODUCT/ARCHITECTURE AUTHORITY  
**Architecture generation:** Corpus-first clean-slate  
**Adopted:** 2026-09-24  
**Repository:** `efremov-aleksei-96/keelaryn`

## 0. Authority

This file is the single current authority for **what Keelaryn is, what it is not, its data model, product principles, deployment model, build order and reuse policy**.

Operational development state remains separately authoritative in `DEVELOPMENT_STATE.json`, GitHub branch/CI state, and freshly observed runtime/provider evidence. Operational state cannot redefine product architecture.

The following material is superseded as current product architecture and is provenance/research only until physically archived:

- previous Hub-first and Zero-Based architecture documents;
- previous `docs/ROADMAP.md`;
- current Hub-first `spec/**`;
- legacy Manager/Hub product architecture;
- Project → RESULT → Reconciliation → canonical Hub protocols;
- `MASTER.json`, canonical epoch, Ready Change and Hub-selector product models;
- r0001–r0009 operation-control transport architecture except as transition evidence and reusable safety lessons;
- LifeOS-specific rules embedded in Keelaryn architecture.

A future architectural change must modify this file deliberately. New parallel architecture documents MUST NOT silently become competing authority.

---

## 1. Product definition

Keelaryn is an **open-source, provider-neutral corpus identity, revision, provenance and AI-context kernel**.

A user's existing corpus remains the user's corpus. Keelaryn observes and models it without requiring the user to import all content into a proprietary store, reorganize it, convert it to Markdown, or make a Keelaryn-owned mirror authoritative.

Keelaryn exists to provide durable knowledge that ordinary filesystems, cloud drives, sync tools and AI connectors do not reliably provide together:

- stable Artifact identity independent of path and content hash;
- distinction between provider object identity and current locator;
- content revision continuity;
- timestamped observations and evidence;
- ambiguity rather than unsafe guessing;
- provenance of accepted metadata/assertions;
- provider-neutral inventory and context selection;
- rebuildable extraction/search/index state;
- task-specific AI ContextBundles that point back to exact source revisions;
- later, safe corpus mutations with explicit recovery semantics.

Keelaryn is **not** a replacement for a filesystem, cloud drive, sync service, note app, photo manager, document-management system, LLM, or general RAG application.

---

## 2. The user promise

Keelaryn MUST preserve these product promises:

1. **Existing corpus accepted as-is.** No physical normalization is required before use.
2. **Read-only onboarding first.** Initial adoption does not move, rename, delete, deduplicate or rewrite user content.
3. **Files remain files.** PDF remains PDF, DOCX remains DOCX, JPG remains JPG, etc.
4. **No provider lock-in.** Google Drive is one provider, not an architectural dependency.
5. **No AI lock-in.** ChatGPT is one client, not an architectural dependency.
6. **No infrastructure lock-in.** VPS, Gateway, Docker and hosted cloud are optional deployment/operator choices.
7. **Fully open-source operation must remain possible.** A user can run Keelaryn with local/open storage and local/open AI without Google/OpenAI/Gateway.
8. **Ambiguity is valid.** Keelaryn does not invent continuity or semantic truth to make state look complete.
9. **User data ownership.** User-controlled corpus is authoritative for physical content/existence.
10. **Complexity belongs to Keelaryn, not the user.** Ordinary users should not need to understand OAuth internals, systemd, SSH, SQLite, provider IDs or transaction journals.

---

## 3. When Keelaryn is unnecessary

Keelaryn SHOULD NOT try to replace mature specialized software.

If a user's actual need is narrow, the specialized application may be the better product:

- file synchronization only → Syncthing/rclone/Nextcloud/Seafile-class tools;
- scanned-document archive → Paperless-ngx/Mayan/Docspell-class DMS;
- photo/video library → Immich-class media manager;
- local file tagging/organization → TagSpaces-class tools;
- note-centric PKM → Logseq/Trilium/Joplin/Anytype-class tools;
- chat/search over selected documents → Khoj/AnythingLLM/RAG-class tools;
- research datasets under explicit version control → DataLad/git-annex.

Keelaryn is justified when the user needs a **heterogeneous existing corpus to remain in place while gaining durable cross-tool identity, revision/provenance, provider-neutral observation and AI context**.

Keelaryn SHOULD integrate with or sit above specialized applications rather than clone their mature functionality.

---

## 4. Fundamental data model

The minimum durable identity model is:

```text
Corpus
Provider
ProviderObject
Locator
Artifact
Revision
Observation
```

Derived layers:

```text
Extraction
SearchIndex
ContextBundle
```

Later semantic layers, only when justified:

```text
SemanticAssertion
Relation/View
MutationPlan
```

### 4.1 Corpus

A Corpus is the user-selected set of objects Keelaryn manages knowledge about.

A corpus may contain one or many roots/providers. A physical root structure such as:

```text
0__Core/
1__Inbox/
2__Project/
3__Records/
8__Library/
9__Archive/
```

is a useful user profile/template, not a Keelaryn requirement.

### 4.2 Provider

A Provider is an access implementation/source such as:

- local filesystem;
- removable filesystem;
- SFTP;
- WebDAV;
- S3-compatible storage;
- Google Drive;
- OneDrive;
- Dropbox;
- Nextcloud or another service exposed through a suitable adapter.

The Core does not privilege Google Drive.

### 4.3 ProviderObject

A ProviderObject identifies a concrete object inside one provider's own identity domain.

Examples may include a Drive file ID, a filesystem object identity where available, an S3 object/version identity, or another provider-native identifier.

A provider object ID is evidence. It is **not** global Keelaryn Artifact identity.

### 4.4 Locator

A Locator says **where/how an object is currently accessible**.

A locator can be a path, provider parent/name tuple, URI-like provider address, or another access coordinate.

ProviderObject and Locator are separate concepts. One physical/provider object may have multiple locators, and a locator may change without changing Artifact identity.

### 4.5 Artifact

Artifact is Keelaryn's stable logical identity for the user's thing being tracked.

Artifact identity is not:

- a path;
- a content hash;
- a provider object ID;
- a filename;
- an AI-generated classification.

Artifact continuity must be evidence-based.

### 4.6 Revision

A Revision represents a distinct observed content state of one Artifact.

A provider metadata/version counter is evidence but does not automatically equal a Keelaryn content Revision because providers may increment versions for metadata-only changes.

A repeated observation of unchanged content does not create a new Revision.

A content sequence A → B → A produces distinct revisions even if the final bytes/hash match an earlier revision.

### 4.7 Observation

An Observation is immutable evidence of what Keelaryn observed at a point in time.

It may record:

- ProviderObject identity;
- Locator(s);
- size;
- MIME/type;
- provider metadata/revision evidence;
- timestamps where meaningful;
- hashes/fingerprints where available or computed;
- extraction capability/status;
- continuity evidence;
- scan/source identity.

Observation is the basis for later continuity decisions and reconstruction.

---

## 5. Identity invariants

These are mandatory:

- Path != Artifact identity.
- Content hash != Artifact identity.
- ProviderObject != Artifact identity.
- ProviderObject != Locator.
- Same bytes do not prove same Artifact.
- A proven rename/move preserves Artifact.
- A content modification creates a new Revision of the same Artifact.
- A copy creates a new Artifact even when bytes are identical, unless stronger evidence proves the operation was not a copy.
- Hash equality never authorizes automatic deletion/merge.
- Provider metadata is evidence, not unquestioned truth.
- AI inference never becomes accepted durable truth automatically.
- Unknown/ambiguous continuity remains explicitly ambiguous.
- Physical location does not define complete semantic meaning.

---

## 6. Durable state classes

Keelaryn MUST distinguish state that can be rebuilt from state that cannot.

### 6.1 Non-rebuildable / identity authority

Examples:

- Artifact IDs;
- accepted continuity decisions;
- manual ambiguity resolutions;
- accepted semantic assertions;
- provenance of those decisions;
- transaction/recovery authority;
- user-confirmed mappings.

Loss of this state may be impossible to reconstruct exactly from corpus bytes alone.

### 6.2 Rebuildable / derived

Examples:

- extracted text;
- previews;
- thumbnails;
- FTS indexes;
- vector indexes;
- embeddings;
- summaries;
- task-specific AI contexts;
- derived classifications;
- inventory views.

These SHOULD be reproducible from the physical corpus plus surviving accepted durable metadata.

### 6.3 Restore versus reconstruct

`restore` means exact recovery from surviving durable Keelaryn state/checkpoint.

`reconstruct` means best-effort inference from corpus/provider evidence after state loss.

Reconstruction MUST preserve ambiguity and MUST NOT claim to recover original identity decisions when evidence does not prove them.

---

## 7. Runtime architecture: modular monolith

The P0/P1 Core is a **modular monolith**, not a microservice system.

One Go process SHOULD contain:

- identity/revision/observation engine;
- SQLite state store;
- SQLite FTS search;
- provider manager;
- discovery scheduler;
- lightweight extraction routing;
- ContextBundle planner;
- HTTP API;
- MCP server;
- CLI;
- embedded web UI assets.

Why this is preferred initially:

- one transactional state boundary;
- no distributed consistency problem;
- lower latency and IPC overhead;
- simpler recovery and diagnostics;
- simple single-host deployment;
- simple deterministic build/update/rollback;
- one security perimeter for core state;
- substantially lower operational burden.

### 7.1 Not everything must execute in-process

Heavy or high-risk components SHOULD run as supervised workers/processes:

- complex PDF parsing;
- OCR;
- audio/video transcription;
- office rendering/conversion;
- ML/embedding models;
- extractors with large native dependency trees.

A malformed document or extractor crash must not corrupt or terminate the identity Core.

Therefore the target is **one-app**, with a one-binary base, not "every possible dependency in one process forever."

### 7.2 Extension boundary

Core extension points are explicit interfaces/protocols, not hidden internal coupling:

- ProviderAdapter;
- Extractor;
- Context/embedding provider;
- optional operator/administration adapter.

Avoid Go dynamic plugins as a foundational requirement. Optional external workers can use a small versioned stdio/HTTP protocol and can later be sandboxed.

---

## 8. State store and search

### 8.1 SQLite

P0 uses SQLite as the local durable database.

Preferred Go implementation: a mature pure-Go SQLite driver so the base executable does not require a separate database server or CGO runtime dependency.

SQLite stores normalized identity/observation/revision/provenance state.

### 8.2 FTS first

P0 uses SQLite FTS5 for text retrieval.

A separate vector database is explicitly out of scope for P0.

Vector retrieval may be added later only if measured retrieval quality justifies it; an embedded SQLite extension is preferred before adding a separate database/service.

### 8.3 Live DB placement

The live SQLite database MUST NOT be treated as a generic multi-host synchronized file.

It lives on the Keelaryn runtime host/device.

Portable durable checkpoints/exports can be stored separately in user-controlled storage.

---

## 9. Provider architecture

The Core owns a narrow `ProviderAdapter` contract.

The contract exposes raw observations and capabilities. It MUST NOT silently collapse ambiguity.

A provider adapter may expose:

- enumerate/list;
- metadata;
- read content/stream;
- provider-native ID;
- hashes if provider supplies them;
- provider change cursor/feed where available;
- capability flags;
- later, explicit mutation primitives.

### 9.1 Local filesystem is first-class

A completely offline local-filesystem corpus MUST work without any cloud account.

### 9.2 rclone reuse

rclone is the preferred broad provider substrate candidate because it already supports a large set of storage systems and is MIT-licensed.

Keelaryn SHOULD reuse rclone code/backends where practical rather than reimplement provider authentication and byte transport.

Rules:

- rclone remains behind `ProviderAdapter`;
- Keelaryn pins and qualifies the exact rclone version it uses;
- provider IDs/metadata may be evidence;
- rclone path/name normalization or conflict heuristics MUST NOT become Artifact identity logic;
- Keelaryn does not expose powerful rclone remote-control surfaces directly to AI clients;
- native provider adapters may supersede rclone for providers where richer identity/change semantics materially improve correctness.

Because rclone is written in Go and supports out-of-tree composition, a Keelaryn Go build may reuse its packages/backends while still producing a single base executable. Any unstable/internal rclone API remains isolated behind our adapter.

### 9.3 Google Drive

Google Drive is initially important for the maintainer's real corpus but is architecturally only one adapter.

Keelaryn MUST remain usable without Google.

---

## 10. Discovery and change detection

P0:

```text
read-only full scan
→ observations
→ identity/revision reconciliation
```

P1 may add:

- local filesystem watchers;
- provider-native change feeds/cursors;
- scheduled incremental scans;
- scan checkpointing.

Change feeds are optimization/evidence channels, not global identity authority.

Read-only discovery always precedes physical mutation support.

---

## 11. Extraction

Extraction is derived and replaceable.

A particular extractor result is identified by:

- exact Artifact Revision;
- extractor identity/version/config;
- extraction output identity;
- timestamps/provenance.

Changing extractor does not change Artifact or Revision.

### 11.1 Reuse strategy

Candidate extractors:

- Microsoft MarkItDown for lightweight LLM-oriented conversion;
- Docling for high-fidelity structured documents/PDFs and complex layouts;
- Apache Tika as a broad format detector/extraction fallback.

These are optional workers/components, not Core identity dependencies.

Unsupported/encrypted/opaque content remains a valid Artifact with extraction state such as `UNSUPPORTED`, `OPAQUE` or `LOCKED`.

P0 SHOULD support a deliberately small useful format set and return explicit unsupported states rather than attempt universal parsing immediately.

---

## 12. AI and application interoperability

AI is a client of Keelaryn, not its authority.

Primary interoperability protocol: **MCP** using the official maintained Go SDK where practical.

Additional interfaces:

- HTTP API;
- CLI;
- embedded/local web UI.

Initial AI-facing capabilities should be narrow and safe:

- search;
- list/query inventory;
- get Artifact/Revision/Observation metadata;
- retrieve supported content/extractions;
- build ContextBundle;
- status/diagnostics.

Shell/SSH access is not an AI product API.

Physical corpus mutations are not part of P0 AI tools.

---

## 13. ContextBundle

AI_CONTEXT becomes a generated query result, not a second knowledge base.

A ContextBundle binds:

- task/query identity;
- selected Artifact IDs;
- exact Revision IDs;
- selected extraction/excerpt identities;
- provenance/locators;
- reason/ranking for inclusion where useful;
- creation policy/version.

ContextBundles are rebuildable by default and may be cached.

They MUST preserve references back to exact source revisions.

---

## 14. Semantics

P0 does not require a universal ontology, LifeOS, People, Areas, Organizations, Events or Facts.

Keelaryn Core starts ignorant of the user's domain.

LifeOS, FoodOS or any other personal/system ontology is an application/profile layered above Keelaryn.

If durable semantics later become useful, prefer provenance-bearing assertions:

```text
SemanticAssertion
    subject
    predicate
    object/value
    provenance
    status:
        proposed
        accepted
        rejected
        superseded
```

Semantic inference remains separate from physical identity.

---

## 15. Deployment profiles

The same Core/data model supports multiple deployment choices.

### 15.1 Portable/Desktop — default ordinary-user path

```text
download/install
→ choose existing corpus
→ read-only scan
→ use local UI / connect AI
```

No VPS, Docker or external database required.

### 15.2 Local server / NAS

Same Core runs persistently on a home server, NAS or mini-PC.

### 15.3 Self-hosted server/VPS

Advanced users may deploy on their own server.

Installation must be automated; ordinary use must not require hand-written systemd/SSH/OAuth configuration.

### 15.4 Hosted service — optional future product

A hosted Keelaryn may provide zero-admin always-on operation while remaining compatible with the same portable data model and self-host path.

Hosted service MUST NOT become required to access a user's corpus/control data.

### 15.5 Completely FOSS path

Keelaryn MUST be testable in a configuration with:

- local filesystem or open/self-hosted storage;
- no Google account;
- no OpenAI account;
- no Gateway;
- no proprietary cloud;
- optional local/open model through an independent AI client.

---

## 16. User onboarding

The first-run experience should guide a non-technical user:

1. choose where existing data lives;
2. connect/select provider/root;
3. explain read-only scan;
4. scan and summarize corpus;
5. create Keelaryn identity state;
6. show ambiguities and capabilities without demanding ontology design;
7. optionally connect an AI client;
8. optionally enable always-on/runtime mode.

The user should not need to understand Artifact IDs, SQLite, provider IDs, MCP, OAuth internals, systemd or SSH.

Physical reorganization is optional and later.

A managed-folder template may be offered, but "keep my current structure" is always valid.

---

## 17. Reuse-before-build engineering doctrine

**This is mandatory.**

Before designing or coding any non-trivial subsystem, development MUST first survey:

1. open standards;
2. actively maintained open-source projects;
3. reusable libraries;
4. existing protocols/formats;
5. specialized products whose architecture already solves the problem.

For each candidate record:

- functional fit;
- correctness fit with Keelaryn invariants;
- maintenance/activity;
- security history/posture;
- license compatibility;
- platform support;
- binary/runtime cost;
- API stability;
- lock-in risk;
- replacement path.

Preferred order:

```text
reuse exact library/module
→ wrap behind Keelaryn interface
→ use sidecar/subprocess/service
→ fork permissively licensed component when justified
→ contribute upstream
→ reuse protocol/data-model idea
→ implement only the remaining Keelaryn-specific gap
```

"Not directly embeddable" does **not** mean "start from zero."

When code cannot be embedded safely or legally, use its protocol, architecture lessons, test ideas or independently specified behavior where permitted.

Prefer permissive dependencies for the distributable Core (MIT / Apache-2.0 / BSD / public-domain class licenses). Copyleft or source-available projects may still be excellent references/integrations; bundling/linking decisions require explicit license review.

No dependency becomes part of Keelaryn merely because it is popular. The abstraction boundary must allow replacement.

---

## 18. Selected existing work

### 18.1 rclone — REUSE

Role: broad provider/authentication/byte-I/O substrate.

Do not reuse as Artifact identity authority.

### 18.2 SQLite + pure-Go driver — REUSE

Role: embedded durable state and FTS.

### 18.3 official MCP Go SDK — REUSE

Role: AI interoperability.

### 18.4 fsnotify-class watcher — REUSE LATER

Role: local filesystem incremental hints.

### 18.5 MarkItDown — OPTIONAL WORKER/INTEGRATION

Role: lightweight document conversion.

### 18.6 Docling — OPTIONAL WORKER/INTEGRATION

Role: richer PDF/document structure, OCR/layout/chunking.

### 18.7 Apache Tika — OPTIONAL FALLBACK WORKER

Role: broad format detection and text/metadata extraction.

### 18.8 Litestream-class SQLite replication — OPTIONAL SERVER HARDENING

Not P0. Evaluate for self-hosted always-on backup.

### 18.9 sqlite-vec-class embedded vector extension — POSSIBLE LATER

Not P0. Add only after measured need.

### 18.10 Perkeep — MAJOR DESIGN SOURCE, NOT PRODUCT BASE

Perkeep is the closest broad conceptual predecessor found:

- personal data storage "for life";
- open-source;
- stable mutable-object anchors (permanodes);
- immutable/signed claims;
- content/location/search ideas;
- Go implementation.

Do not fork Perkeep as Keelaryn Core because its authoritative design is a content-addressed blob store into which data is represented/imported. Keelaryn's core requirement is instead to overlay identity/revision/provenance on an existing heterogeneous corpus that remains authoritative in place.

Reuse or adapt isolated ideas/code only where they do not import the CAS-authority assumption.

### 18.11 DataLad / git-annex — DESIGN SOURCE / OPTIONAL INTEGRATION

Useful lessons:

- dataset identity distinct from content ID;
- repository/location identity;
- content-location tracking;
- metadata separate from filename;
- explicit version history.

Not the universal Keelaryn base because requiring every ordinary user's corpus to become a Git/git-annex dataset is too invasive and technical, and content keys remain content identities rather than Artifact identities.

### 18.12 TagSpaces — UX/DESIGN SOURCE

Useful lessons:

- existing files remain files;
- offline/local-first;
- optional sidecar metadata;
- tags/views without mandatory proprietary cloud.

Do not make filename/sidecar path the universal Keelaryn identity mechanism.

### 18.13 Specialized systems — INTEGRATE, DO NOT CLONE

Paperless/Mayan/Docspell, Immich, Syncthing/Nextcloud/Seafile, Trilium/Logseq/Joplin/Anytype, Khoj/AnythingLLM/RAG systems solve narrower domains better.

Keelaryn should expose/provider-integrate where useful rather than rebuild all their user-facing capabilities.

---

## 19. Why Keelaryn still exists after this reuse

The remaining proprietary-to-the-project logic is intentionally small and distinctive:

- Artifact identity model;
- ProviderObject versus Locator separation;
- observation model;
- Revision continuity;
- rename/move/copy/modify classification;
- ambiguity representation;
- provenance and accepted continuity decisions;
- cross-provider reconciliation later;
- ContextBundle planning bound to exact revisions;
- safe mutation semantics later.

If these capabilities are not needed for a user, Keelaryn may genuinely be unnecessary for that user. The product should not manufacture a need that a simpler specialized tool already satisfies.

---

## 20. Product P0

P0 is intentionally small and read-only.

### Required P0 path

```text
one existing corpus root
→ read-only discovery
→ durable ProviderObject/Locator observations
→ Artifact identity
→ Revision continuity
→ inventory
→ minimal extraction
→ SQLite FTS search
→ task-specific ContextBundle
→ MCP/HTTP/CLI access
```

### P0 proof cases

At minimum prove:

1. unchanged object rescanned → same Artifact and Revision;
2. rename/move with strong continuity evidence → same Artifact/Revision, new Locator;
3. content modification → same Artifact, new Revision;
4. true copy → new Artifact despite identical bytes;
5. ambiguous continuity → explicit ambiguity, no silent merge;
6. unsupported content → valid Artifact with unsupported extraction;
7. restart → exact durable identity state resumes;
8. derived extraction/index can be rebuilt without changing Artifact identity;
9. AI ContextBundle cites exact Revision/source evidence;
10. user corpus bytes are unchanged by all P0 operations.

### P0 provider strategy

Start with:

- local filesystem;
- one real maintainer-relevant remote/provider path (likely rclone-backed Google Drive for testing).

Google-specific correctness is not the architecture.

---

## 21. P0 technology spike

Before committing to a large implementation, build a very small Go spike proving:

```text
one Go executable
→ SQLite state
→ local read-only scan
→ one rclone-backed remote scan
→ provider/native identity evidence preserved
→ FTS query
→ minimal MCP endpoint
→ embedded minimal web status page
```

The spike is discarded or promoted based on evidence.

Its purpose is to validate Go/rclone/SQLite/MCP composition and binary/deployment ergonomics, not to become an excuse for another infrastructure phase.

---

## 22. Growth order after P0

Only after P0 is useful:

1. reliability and deterministic recovery;
2. incremental local/provider observation;
3. broader extraction;
4. ContextBundle quality;
5. backup/export/restore hardening;
6. semantics/assertions only where recurring value is proven;
7. additional providers;
8. provider-native adapters where generic substrate is insufficient;
9. safe mutation planning;
10. verified physical mutations and rollback/compensation;
11. metadata-loss reconstruction;
12. chaotic-corpus adoption assistance;
13. optional organization/migration suggestions;
14. advanced multi-root/cross-provider identity.

Do not front-load ontology, distributed systems, microservices, vector infrastructure or physical mutation machinery.

---

## 23. Physical mutations — later

Physical mutation is not P0.

Future mutation protocol follows:

```text
capture prestate
→ validate Artifact/ProviderObject/Locator identity
→ validate destination/capabilities
→ establish recovery capability
→ revalidate at mutation boundary
→ mutate
→ re-observe and verify physical result
→ commit metadata
→ retain provenance
```

Provider recovery capability must be explicit:

- EXACT;
- PROVIDER_VERSION_RESTORE;
- TRASH_RESTORE;
- COMPENSATING;
- NONE.

Metadata never claims completion before physical verification.

---

## 24. Security model

Defaults:

- read-only provider scopes where possible;
- least privilege;
- no AI shell access;
- no routine root requirement;
- provider credentials isolated from model-visible content;
- heavy/untrusted parsing isolated from identity Core where practical;
- bounded parsing/time/memory/output;
- exact version pinning/SBOM/license inventory for bundled dependencies;
- immutable release identities/signatures/checksums;
- explicit upgrade/rollback.

AI clients invoke Keelaryn capabilities, not operating-system shell commands.

---

## 25. Development/operator architecture

Development authority:

```text
GitHub
    source / branch / canonical architecture / CI / history

Runtime hosts
    observed integration/runtime state

Corpus providers
    physical corpus and provider-specific evidence

ChatGPT/other AI
    engineer/orchestrator, never durable authority
```

Current Gateway SSH access is a **development OperatorChannel implementation**, not a Keelaryn product dependency.

The product/development model refers generically to `OperatorChannel`. Possible implementations include Gateway, ordinary OpenSSH, local execution, another MCP connector or future automation.

Do not build another general ChatGPT→VPS relay while a suitable operator channel exists.

Preserve transaction/reconcile/no-blind-retry lessons from the old operation runtime; do not preserve transport machinery by inertia.

---

## 26. Clean-slate convergence (C0) — immediate priority

No new Corpus-first product feature development begins until C0 completes. C0 completed on the active Corpus-first line once all correctness/data-safety blockers were removed; explicitly inert tooling-blocked/deferred cleanup may remain under the rule in C0.4.

### C0.1 Freeze the pre-P0 world

Create an immutable Git reference/tag for the current pre-P0 legacy state.

### C0.2 Build exact cleanup manifests

Classify Git and Google Drive development material as:

- KEEP;
- ABSORB;
- ARCHIVE;
- DELETE_CANDIDATE;
- REVIEW.

No Google Drive mutation occurs before the maintainer approves an exact list.

### C0.3 Absorb unique knowledge

Before archiving, ensure unique valid lessons from:

- CorpusBootstrap;
- architecture audits;
- Manager engineering;
- Hub-first Core;
- D0 operation-control incidents;
- real-corpus audits

are represented in this canonical document, current operational state, tests/fixtures where still relevant, or explicit provenance references.

### C0.4 Archive old Google Drive development state

After approval, obsolete Keelaryn/Hub/Manager/CorpusBootstrap development material moves under a clearly historical location such as:

```text
9__Archive/
└── KeelarynLegacy/
    └── 2026-09-24__PreCorpusP0/
```

Real user corpus/projects are not archived merely because Keelaryn development changed.

C0 may close with an explicitly recorded `TOOLING_BLOCKED` or `DEFERRED_CLEANUP` item only when all of the following are true:

- the remaining item is inert and non-authoritative;
- it cannot auto-start or mutate the corpus;
- its exact desired disposition is durably recorded;
- its deferral does not weaken identity/correctness/data-safety guarantees;
- continuing to wait would only block product development on an external tooling limitation or optional historical cleanup.

Such deferral does not reclassify the item as accepted active architecture.

### C0.5 Clean Git active line

Create a clean Corpus-first development line whose working tree contains only current product/development material.

Old implementation remains recoverable from immutable Git history/tag/legacy reference instead of occupying the active product tree.

### C0.6 Collapse CI

Active Corpus-first development should initially have one primary development CI workflow plus only genuinely necessary governance/release workflows.

Candidate identity is data, not a reason to permanently add one workflow file per candidate.

### C0.7 Compact development handoff

Current state must be compact. Historical journals belong in Git/evidence, not an ever-growing "current" handoff.

### C0.8 Close D0

D0 closes once autonomous development can reliably:

- read Git authority;
- use a functioning OperatorChannel;
- run CI;
- observe required runtime/provider state;
- make one qualified mutation;
- verify it;
- checkpoint it.

D0 is not a separate product and must not continue expanding after those conditions are satisfied.

### C0.9 Start P0

The first new product code after C0 implements the minimal data model and read-only observation path.

---

## 27. Archive doctrine

Archive is not authority.

### Git

Prefer immutable Git history/tag/legacy branch to copying the whole old codebase into an `archive/` directory of the active branch.

The active branch must stay small and comprehensible.

### Google Drive

Development artifacts that are unique/private and not otherwise durably represented may be moved to `9__Archive/KeelarynLegacy` after manifest review.

Disposable test outputs with no unique evidentiary value may become delete candidates, but deletion requires separate explicit approval.

### Corpus

Never classify genuine user content as development garbage merely because it was once used by Keelaryn.

---

## 28. Dependency and license policy

For every bundled dependency record:

- project and exact version/commit;
- license;
- source;
- direct/transitive role;
- update policy;
- security advisory source where available;
- whether code is linked, embedded, invoked externally, or optional.

Prefer permissive dependencies for the base distribution.

Source-available/non-OSI or copyleft applications can remain integrations/research references without contaminating the base dependency graph.

---

## 29. Product success criterion

Keelaryn succeeds when a non-technical user can:

1. install or run one app;
2. point it at existing data without reorganizing it;
3. receive a read-only inventory and stable identity model;
4. search/use the corpus locally;
5. connect an AI through an open interface;
6. move between local, self-hosted or hosted operation without losing identity/provenance;
7. stop using Keelaryn and still retain their original files in ordinary usable form.

The best architecture is the smallest architecture that preserves these guarantees.

---

## 30. Non-negotiable final invariants

```text
Corpus-first.
Provider-neutral.
AI-neutral.
Deployment-neutral.
Open-source self-host path.
Read-only adoption first.
Path is not identity.
Hash is not Artifact identity.
ProviderObject is not Locator.
Copy is not move.
Ambiguity is valid state.
Derived data is rebuildable.
Non-rebuildable identity/provenance is explicitly protected.
AI inference is not accepted fact by default.
Physical mutation requires verified transaction semantics.
Reuse before build.
Specialized software is integrated, not needlessly cloned.
D0 enables product development; D0 is not the product.
Build the minimum useful path first.
```

