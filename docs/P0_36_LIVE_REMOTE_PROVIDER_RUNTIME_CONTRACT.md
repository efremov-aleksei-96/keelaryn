# P0-36 — Live Remote Provider Runtime Contract

Date: 2026-09-30  
Status: **P0-36A QUALIFIED / P0-36B QUALIFIED / P0-36C EXECUTABLE QUALIFIED — LIVE ACCEPTANCE PENDING**
Live provider authorization: **P0-36C READ-ONLY ACCEPTANCE ONLY; EXECUTABLE QUALIFIED, REAL PROVIDER ACCEPTANCE NOT YET QUALIFIED**
Corpus mutation: **FORBIDDEN**

## 1. Goal

P0-36 closes the outstanding P0 gate that deterministic Google Drive / RemoteHistory mechanics have not yet been exercised through a real authenticated user-runtime path.

The target remains corpus-first:

```text
real read-only Google Drive provider
→ exact RemoteHistory/topology publication
→ exact provider metadata snapshot
→ existing ScanSession / Observation / Inventory
→ existing lifetime-aware identity authority
→ existing SAME/NEW acceptance when evidence permits
```

P0-36 MUST reuse the P0-29/P0-30 machinery. It MUST NOT introduce a second remote inventory, a second identity resolver, provider-specific Artifact identity, or a canonical content mirror.

## 2. Boundary-review blocker

### P0_36_B1_PROVIDER_NEUTRAL_OBSERVATION_FACT_AVAILABILITY — RESOLVED BY P0-36A

The canonical architecture says an Observation *may* record size, MIME/type, provider metadata and timestamps where meaningful. Provider metadata is evidence, not unquestioned truth.

The current early-P0 durable model is narrower:

- `ObservationRecordInput.Size` is mandatory `int64`;
- `Mode` is mandatory `uint32`;
- `ModifiedAt` is mandatory;
- SQLite `observations.size/mode/modified_at` are `NOT NULL`;
- `LIGHTWEIGHT_ALL:v1` rejects a snapshot entry unless size, mode and modified time are all present.

That is valid for the currently-qualified LocalFS profile, but it is not provider-neutral enough for live Google Drive.

Official Google Drive v3 evidence:
- `File.size` is populated for blobs and Google Workspace editor files but is not populated for objects that have no size, including folders and shortcuts;
- Drive metadata exposes MIME/type and modified time, but not a POSIX filesystem mode;
- exact requested fields should be selected with the Drive API `fields` mask;
- metadata-only access can use `drive.metadata.readonly`.

Therefore a direct Google live adapter cannot honestly satisfy `LIGHTWEIGHT_ALL:v1` for a normal managed root. Substituting `0` for unknown size or mode would turn absence of provider evidence into fabricated evidence.

## 3. Rejected shortcuts

P0-36 MUST NOT:

1. manufacture `size=0`, `mode=0`, or a fake modified timestamp and treat it as observed provider metadata;
2. omit folders/shortcuts merely to make the required fields fit while still calling the inventory complete;
3. qualify only the already-working history cursor path and claim the provider→Observation runtime is live;
4. download/export content solely to invent metadata that the provider does not expose;
5. add a Google-specific inventory or metadata authority beside Observation;
6. weaken exact-IN, topology, fingerprint, lifetime, source-bound transaction, or replay guards.

## 4. P0-36A — explicit optional observation facts

Before live wiring, the durable Observation boundary must represent **fact unavailable** explicitly.

Required semantics:

- size, mode and modified time are independently available or unavailable;
- unknown is not encoded as a provider fact;
- LocalFS continues to supply all three facts exactly as today;
- existing durable rows remain semantically known;
- identity does not depend on availability of these convenience metadata fields;
- regular-file ContentEvidence may be accepted only when an exact size fact is available and matches it;
- missing size therefore keeps SAME regular-file continuity unresolved rather than manufacturing a Revision;
- current inventory can expose unavailable metadata without pretending it is zero.

### 4.1 Backward-compatible storage direction

The preferred minimal migration is to preserve the existing value columns and add explicit availability authority beside them, rather than rebuilding the heavily-referenced Observation table solely to make three columns nullable.

Conceptually:

```text
size + size_known
mode + mode_known
modified_at + modified_at_known
```

Existing rows migrate as known=true.

For a new unknown fact, the stored compatibility value is an internal sentinel only; the availability bit is authoritative and public Go/JSON APIs MUST expose the fact as unavailable. No identity, inventory, fingerprint, content-evidence or runtime decision may consume the compatibility value when its known bit is false.

The implementation must use compile-time-visible optionality at the public model boundary (for example pointers/explicit optional values), so old consumers cannot silently treat an unknown remote fact as a real zero.

This direction is provisional until the implementation audit verifies every read/write/trigger path. If a clean nullable-table migration is demonstrably safer under the pinned SQLite migration stack, it may replace the compatibility-column direction, but not the explicit optionality semantics.

### 4.2 Snapshot/fingerprint versioning

Historical `keelaryn.remote-metadata-snapshot:v1` + `LIGHTWEIGHT_ALL:v1` remains immutable and replay-verifiable.

P0-36A introduces a new exact semantic pair, expected as:

```text
keelaryn.remote-metadata-snapshot:v2
LIGHTWEIGHT_ALL:v2
```

V2 fingerprints fact presence as well as fact value. Missing and zero are distinct.

The completion transaction must dispatch verification by the source's immutable fingerprint/policy version. V1 scans continue to verify under V1 rules; V2 scans use the V2 optional-fact rules.

## 5. P0-36B — Google live metadata adapter/runtime composition

Only after A qualifies.

The Google client may extend its existing field mask to return the exact provider facts needed by the live metadata mapper:

- id;
- parents;
- driveId;
- trashed;
- shortcut target where applicable;
- mimeType;
- size when supplied;
- modifiedTime when supplied.

Provider mapping:

- ordinary content-bearing Drive items → `REGULAR_FILE`;
- folders and shortcuts → non-regular `OTHER` for P0 unless a stronger cross-provider semantic is deliberately qualified;
- size → present only when Drive supplies it;
- mode → unavailable;
- modified time → present only when a valid provider timestamp is supplied.

No content download/export is required for inventory materialization. Native Google Workspace content may therefore create/retain physical observations and NEW Artifact identity without forcing a Keelaryn Revision; SAME regular-file revision continuity remains unresolved until exact content evidence exists.

Runtime composition must reuse:

- `gdrive.GoogleClient`;
- canonical My Drive/shared-drive scope resolution;
- `TopologyCoordinator`;
- durable RemoteHistory generation/publication;
- Google managed-root membership projection;
- P0-30 materializer;
- existing identity acceptance.

## 6. P0-36C — authenticated executable live acceptance

The final gate requires a real authenticated provider read through a supported executable/runtime surface.

Current checkpoint after exact-head qualification:

- supported command: `keelaryn google-drive-bootstrap`;
- exact-head qualification: `09363714673d3c92fc89f2200d8b9de5ec908545`, CI `36749826725` — validate, Ubuntu 24.04 and Windows 2025 PASS;
- temporary access token is accepted only through an environment variable; a raw token CLI argument is rejected;
- granted scope is validated before protected control-state mutation;
- provider identity is derived read-only from Drive `about.user.permissionId`;
- no Drive write API/scope is present in the qualified runtime surface;
- **real token-backed Google Drive execution is still pending and P0-36C is not yet closed**.

Authorization requirements:

- request the narrowest sufficient Drive scope; P0 inventory/history should use `drive.metadata.readonly`;
- OAuth/service construction stays outside the pure history adapter;
- credentials/tokens are not written to the corpus and are not committed to Git;
- the runtime does not request Drive write scope;
- live provider operations are read-only;
- only Keelaryn control state may be mutated;
- qualification should preferably use disposable protected control state against the real provider so acceptance cannot contaminate production authority.

The user-runtime surface must not require raw database paths and must not expose lower-level provider operations that bypass coordinator/materializer guards.

## 7. Interruption discipline

Every control-state mutation keeps the existing rule:

```text
read durable prestate
→ validate provider/source boundary
→ perform one coherent durable transition
→ verify durable result
```

After timeout/interruption:
- never repeat bootstrap/advance/materialization blindly;
- reconcile generation/sequence/cursor and any matching scan source first;
- existing Coordinator PRESTATE_CHANGED / replay behavior remains authoritative.

Provider reads themselves are non-mutating; a failed provider call must not be reclassified as a history GAP unless the qualified adapter explicitly proves the corresponding provider history condition.

## 8. Qualification order

### P0-36A
- optional-fact durable model;
- v1 backward replay;
- v2 optional-fact fingerprint;
- LocalFS regression;
- remote transaction/fingerprint/direct-SQL guards;
- Ubuntu 24.04 + Windows 2025;
- structural retrospective and risk-driven full audit because this changes a cross-provider durable evidence boundary.

### P0-36B
- Google metadata field mapping;
- deterministic fake-service coverage for folders, shortcuts, blobs and native Workspace files;
- no OAuth;
- no corpus mutation;
- exact-head cross-platform qualification + targeted retrospective.

### P0-36C
- supported authenticated runtime surface;
- real Drive read-only acceptance;
- disposable control preferred for acceptance;
- prove no Drive corpus writes;
- prove exact runtime result against durable authority;
- exact-head qualification and live evidence checkpoint.

Only after C may the P0 closure gate `LIVE_REMOTE_PROVIDER_RUNTIME_QUALIFICATION` be removed.

## 9. Prior-art / reuse decision

Reuse the already-pinned official `google.golang.org/api/drive/v3` client. The repository already transitively carries the Google auth/OAuth stack; do not add a second Drive SDK merely for P0-36.

Do not adopt rclone or another sync engine as an execution dependency: those projects have mature authentication/sync UX but would duplicate the already-qualified RemoteHistory/topology/identity semantics and work against the one-binary/minimal-dependency direction. Their operational ideas may still inform later auth UX.

## 10. External evidence

Google Drive API documentation used for this boundary review:

- File resource: https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- Fields masks: https://developers.google.com/workspace/drive/api/guides/fields-parameter
- Drive OAuth scopes: https://developers.google.com/workspace/drive/api/guides/api-specific-auth

## 11. Current decision

P0-36A and P0-36B are qualified. The provider-neutral optional-fact boundary is durable, and the Google metadata bootstrap is composed through the existing RemoteHistory/topology/materialization/identity authority without provider writes or a second inventory.

P0-36C is now the only remaining P0-36 substage. It may add only the supported authenticated **read-only** executable acceptance path defined above. The `LIVE_REMOTE_PROVIDER_RUNTIME_QUALIFICATION` closure gate remains outstanding until that exact-head live evidence checkpoint passes.
