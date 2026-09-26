# Project Continuity and Observation Policy

**Status:** architecture policy  
**Authority:** subordinate to `KEELARYN_CANONICAL.md`

## 1. Purpose

This policy generalizes the useful part of Keelaryn Development Level 0 (D0) to arbitrary long-lived managed projects and defines how corpus-wide observations can reduce repeated reads without turning Keelaryn into a second authoritative content store.

## 2. Project Continuity Contract

A project is autonomously resumable only when a fresh AI/client/operator can reconstruct the project's exact actionable state from durable sources without depending on chat history.

For every long-lived **managed** project, maintain a compact project-owned checkpoint physically inside the project boundary.

Default layout:

```text
<ProjectRoot>/
└── .keelaryn/
    └── PROJECT_STATE.json
```

A provider/profile may use a visible equivalent such as `PROJECT_STATE.json` or `__Keelaryn/PROJECT_STATE.json` when a dot-directory is undesirable. The exact chosen locator is part of project configuration.

### 2.1 Minimum state

The project checkpoint should contain, as applicable:

- schema/version;
- stable ProjectID;
- project scope/root(s);
- purpose/current objective;
- status;
- completed durable checkpoints;
- blockers/deferred items;
- exact next resumable action;
- authoritative external sources and their roles;
- mutation/transaction constraints;
- references to durable evidence;
- last verified project checkpoint identity/time;
- resume procedure.

It is a checkpoint/index, not a duplicate journal of the whole project.

### 2.2 Authority

The project-local state is authoritative for **project coordination state** that the project owns.

It does not override external reality. Examples:

- Git remains authority for Git branch/commit/source history;
- provider/corpus observations remain authority for observed physical reality;
- an external service remains authority for its remote state;
- a runtime host must be freshly read when runtime reality matters.

A project checkpoint may bind/reference those authorities but must not pretend that a stale reference proves their current state.

### 2.3 Safety

- no credentials/secrets in ordinary project checkpoint files;
- no blind mutation retry after interruption;
- reconcile external authority before retry;
- one coherent durable mutation per transactional turn where practical;
- immediately verify durable result;
- update the project checkpoint after a material state transition;
- chat/AI memory is never the only copy.

### 2.4 Read-only onboarding boundary

Physical project-local state is a write into the corpus/project. Therefore Keelaryn MUST NOT create it merely because a directory was scanned.

An unmanaged corpus can remain fully read-only.

The checkpoint is created when a project is explicitly adopted as a managed/resumable project, or when the user/project workflow already owns such an artifact.

This requirement is architectural and does not block the current read-only P0.

## 3. Observation coverage

Keelaryn should avoid repeatedly reopening source files just to rediscover facts already observed and still provably current.

### 3.1 Default: LIGHTWEIGHT_ALL

For all in-scope objects, keep durable lightweight Observation evidence available from complete scans/history publications:

- provider and provider-object identity evidence;
- locator(s);
- size/type;
- provider metadata and meaningful timestamps;
- scan/history membership;
- observation time and provenance;
- identity/revision assignment status when accepted.

This is the baseline default.

### 3.2 Optional enrichment profiles

`FINGERPRINT_ON_CHANGE`
: Compute a content fingerprint when an object appears changed and existing provider evidence is insufficient.

`EXTRACT_SUPPORTED_ON_CHANGE`
: Cache extraction for supported exact Revisions when content changes or no exact cached extraction exists.

`DEEP_BACKGROUND`
: Opportunistically enrich the corpus in the background under explicit budgets. It may later include broader hashing, extraction, previews, thumbnails, FTS materialization and other rebuildable indexes.

Profiles are policy, not identity authority.

They can be selected per root/provider/file type and constrained by CPU, storage, battery, thermal state, metered network and foreground activity.

## 4. Cache correctness

A cached derived result is reusable only when it is bound to the exact source state it claims to describe.

At minimum bind derived content to:

- ArtifactID when assigned;
- exact RevisionID/content evidence;
- provider/source locator evidence as required for retrieval;
- extractor/indexer identity and version;
- relevant policy/config identity.

Query behavior:

```text
exact fresh cache available
→ use cache

cache absent/stale/insufficient
→ bounded read from provider/source
→ validate exact source state
→ derive/update cache
```

Never silently treat a stale extraction, fingerprint, preview or index entry as current.

## 5. What observations are not

Observation/cache state is not:

- a mandatory mirror of all corpus bytes;
- Artifact identity by itself;
- proof that unchanged metadata means unchanged content;
- permission to merge duplicates;
- permission to mutate the corpus.

Lightweight Observation history contains non-rebuildable evidentiary value when it participates in accepted identity/history decisions. Heavy extraction/index/cache outputs remain rebuildable unless explicitly promoted into a user artifact.

## 6. Scaling direction

Full scans are the correctness baseline; incremental provider history/watchers are the optimization path.

For large corpora:

```text
initial complete observation
→ incremental change/history feed
→ update affected lightweight observations
→ optional bounded enrichment
→ periodic reconciliation/full scan when needed
```

Background work must be resumable and resource-aware. An interrupted enrichment job does not invalidate the last COMPLETE inventory/history authority.

## 7. Current implementation boundary

Already present:

- durable Observations/Locators/ScanSessions;
- complete-scan inventory authority;
- selective content evidence;
- revision-bound minimal extraction;
- RemoteHistory transport semantics;
- hardened durable SAME/NEW acceptance.

Not yet implemented as a general product facility:

- project-local `PROJECT_STATE.json` lifecycle;
- configurable observation profiles;
- persistent broad extraction/index cache;
- scheduler/resource budgets;
- Android background observation adapter;
- full live-provider history publication.

These are architectural requirements/options, not claims of current implementation.
