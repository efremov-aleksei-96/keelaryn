# Production Hub Migration Design

This document defines the zero-based MVP migration boundary for moving the existing production Hub into the zero-based Hub model after the limited-real-Hub-subset pilot has succeeded.

This is a design and qualification contract. It does **not** authorize migration, production mutation, Manager replacement, or cutover merely by existing in the repository.

## 1. Goals

Migration must preserve user data, preserve rollback ability, avoid ambiguous mixed ownership between legacy and zero-based systems, and produce one exact zero-based Hub identity whose initial canonical state is independently verifiable.

Migration must be:

- explicit rather than recursive-by-default;
- deterministic from a frozen migration plan and frozen source bytes;
- restart-safe;
- fail-closed on source drift or ambiguous mapping;
- proven first against a disposable target;
- reversible until final cutover acceptance;
- independent from legacy Manager runtime semantics except where a read-only source extractor deliberately consumes legacy Hub files.

## 2. Non-goals

The MVP migration does not:

- rewrite the existing production Hub in place;
- mutate production Manager 4.x during development or dry-run qualification;
- import every legacy technical artifact automatically;
- preserve legacy Manager control/state files as zero-based canonical data;
- infer new canonical ownership from file names alone;
- introduce multi-Hub runtime support;
- perform semantic deduplication automatically without an explicit reviewed migration mapping;
- publish private Hub bytes to GitHub, CI artifacts, SOURCE, DISTRIBUTION, UPDATE or AI_CONTEXT.

## 3. Migration model

Migration is a **copy-and-cutover** process, never an in-place transformation.

The old production Hub remains intact and read-only throughout source capture, mapping, rehearsal and zero-based target construction.

The migration creates a distinct zero-based target Hub. Legacy and zero-based Hubs may coexist physically during qualification, but only one may be declared the active production Hub after cutover.

The old Hub remains rollback material until post-cutover acceptance explicitly retires that rollback path.

## 4. Source freeze boundary

A production migration candidate begins by defining one exact source capture boundary.

Before source capture:

1. identify the exact production Hub root;
2. verify it is not a symlink/reparse redirect or ambiguous mount;
3. define the explicit source allowlist/mapping policy;
4. require no migration write operation against the source root;
5. fingerprint every selected source file by exact SHA-256 and byte length;
6. record a source manifest using only relative logical paths;
7. re-read every selected source file and verify the same fingerprint after capture.

If source bytes change during capture, the migration candidate is invalid and must be rebuilt from a fresh source observation.

The first implementation may require a short human-declared source quiescence window for the final production capture. Automatic writer coordination is not implied by this design.

## 5. Migration mapping

Migration mapping is semantic authority and must be explicit.

Each selected legacy source item is classified as exactly one of:

- `CANONICAL_IMPORT` — becomes one zero-based canonical file;
- `ROUTER_SOURCE` — contributes to a newly prepared INDEX/router document but is not imported verbatim as canonical truth;
- `PROJECT_WORK_IMPORT` — becomes non-canonical Project work material when deliberately preserved;
- `ARCHIVE_ONLY` — retained outside active zero-based canonical/work authority for historical reference;
- `DROP_TECHNICAL` — legacy technical/runtime artifact intentionally not imported.

Every `PROJECT_WORK_IMPORT` and `ARCHIVE_ONLY` action must additionally bind one exact Hub-relative `destination`. Destination authority is classification-specific:

- `PROJECT_WORK_IMPORT` must be under `work/projects/<project_id>/migration-import/...`, where `<project_id>` is a valid Project identifier;
- `ARCHIVE_ONLY` must be under `archive/migration/<candidate_id>/...` for the same migration candidate;
- all other classifications must omit `destination` entirely;
- no two preservation-classified source items may share one destination.

The preservation namespaces are deliberately outside canonical authority. A file under `work/projects/<project_id>/migration-import/` is preserved Project material, not Project `STATE.md`, not a RESULT and not canonical truth. A file under `archive/migration/<candidate_id>/` is historical migration material outside active work/canonical authority. Ordinary fresh bootstrap does not create either optional namespace.

A migration plan must never silently map one legacy file to multiple canonical owners or multiple legacy truths to one canonical target without an explicitly prepared replacement file.

Canonical target names and contents are frozen in the migration candidate before Core publication.

## 6. Private migration pack

The migration candidate is represented by one immutable private pack stored only in disposable/local private test space.

At minimum the pack binds:

- migration candidate ID;
- source manifest fingerprint;
- exact mapping manifest fingerprint, including preservation destinations;
- every prepared canonical payload by target name, byte length and SHA-256;
- every preserved payload by source classification, exact bytes and the mapping authority that defines its destination;
- prepared root `INDEX.md` bytes when the migration changes routing;
- expected initial canonical inventory;
- total selected/imported byte counts.

The private pack itself must never be committed or uploaded to public development infrastructure.

Sanitized evidence may contain only identities, hashes, counts, outcomes and qualification metadata that do not reveal private payload contents, local paths, Drive IDs or account identities.

## 7. Disposable full rehearsal

Before any production cutover is possible, the exact migration candidate must be rehearsed against a fresh disposable zero-based Hub.

The rehearsal must prove:

1. fresh zero-based Hub bootstrap PASS;
2. exact private migration pack verification PASS;
3. canonical publication through the ordinary Ready Change/Core path;
4. deterministic semantic/postcheck receipt for migration inventory;
5. terminal `COMMITTED`;
6. canonical epoch progression exactly as specified;
7. exact target canonical inventory and hashes;
8. exact materialization and byte verification of every preservation destination;
9. clean READY/SAFE completion;
10. Workspace/Project/Reconciliation structural validity after migration;
11. ordinary consistent-reader protocol can read the migrated canonical set;
12. a subsequent no-op service iteration is IDLE;
13. restart recovery remains valid from the migrated state.

The disposable rehearsal target is destroyed or archived as test evidence according to test policy; it is never promoted by renaming or substituting unqualified bytes after the fact.

### Candidate freeze boundary

After coherent development PASS and before any production-target qualification, the exact private migration candidate must be issued through one explicit freeze operation.

Candidate freeze is an **identity/provenance freeze only**. Its terminal receipt status is exactly `FROZEN_UNQUALIFIED`; creating or verifying that receipt does not claim production qualification, cutover approval, or permission to mutate the production Hub.

The freeze operation must:

- require one exact clean Git worktree root;
- bind the exact source commit and exact source tree;
- freshly verify the complete private migration pack;
- require the private pack to be physically outside the Git worktree even when Git ignore rules would otherwise hide it;
- keep the freeze receipt outside both the Git worktree and the immutable private pack;
- bind the candidate ID, pack digest, source-manifest digest and mapping-manifest digest;
- bind deterministic canonical, Project-initial-state and preservation-destination inventory digests;
- bind the prepared root `INDEX.md` digest when present;
- publish the sanitized receipt atomically and never overwrite a conflicting prior receipt;
- freshly reverify source and pack identity after durable receipt publication.

If the process is lost after durable receipt publication, repeating the same freeze operation must recover idempotently by exact receipt identity. If durable receipt publication succeeded but the post-publication verification fails, evidence must report that distinction explicitly rather than claiming no freeze occurred.

Once a candidate is frozen, any change to source commit/tree, mapping authority, pack manifest, canonical payload, Project initial state, preservation payload/destination or root router bytes invalidates that frozen identity. Do not regenerate replacement bytes under the same frozen receipt; issue a new migration candidate/freeze identity instead.

The private pack remains private after freeze. The sanitized freeze receipt may expose only non-secret identities, hashes, counts and booleans; it must not expose private source paths, canonical target paths, preservation destinations, payload bytes, Drive IDs, account identities or workstation paths.

## 8. Production target construction

Production migration creates a new zero-based Hub target using the same exact qualified Core/product bytes and the exact qualified migration candidate.

The target is distinct from the legacy production Hub and begins as a fresh zero-based Hub at canonical epoch 0.

No canonical payload is written directly. Migration publication must use the ordinary Ready Change/Core transaction path.

Migration-specific topology preparation may create only deterministic empty parent directories required by the frozen canonical target set before Ready Change publication. It must not write canonical payload bytes, must fail closed on ambiguity, and must be independently revalidated before the Core transaction begins.

Preservation materialization is non-canonical and must use only the exact destinations frozen in the verified mapping. Project preservation may be materialized only beneath an explicitly initialized Project. Archive preservation may be materialized only beneath `archive/migration/<candidate_id>/`. Exact bytes and fingerprints must be re-observed after creation; ambiguous or pre-existing conflicting material blocks the migration target.

The migration-specific postcheck must verify the entire expected migrated canonical inventory rather than only changed targets because the new target begins empty.

### Production-target qualification boundary

Production target construction is performed only beneath one deliberately guarded staging root. The gate must never accept an arbitrary existing Hub root as the target of migration writes.

The staging root must have the exact expected name and exact sentinel bytes. Before the target is created, the root may contain only that sentinel. The gate reserves one Drive target ID, durably records that ID in private local authority, and only then creates the fresh target beneath the guarded staging root. On restart, the same reserved ID is authoritative; name-based rediscovery is not a substitute.

Fresh staging validation is required again immediately before a missing reserved target is created. If an unrelated child appears after the private authority was published, creation fails closed rather than assuming the staging root is still safe.

Before target authority/creation and again after construction, the live legacy source bytes must still match the frozen migration source manifest. Source drift invalidates qualification; it must not be silently treated as an acceptable delta.

The production-target gate then runs the same restart-safe migration construction and acceptance proofs used by the disposable full rehearsal. Qualification PASS requires, at minimum:

- exact frozen candidate/pack verification;
- exact live legacy source revalidation;
- exact guarded staging-root verification;
- canonical `COMMITTED` epoch 1;
- exact canonical inventory and bytes;
- exact preservation inventory;
- Workspace/Project/Reconciliation structural validity;
- consistent-reader epoch/inventory verification;
- subsequent Core iteration `IDLE`;
- restart discovery `READY_CLEAN`;
- final fresh pack/freeze/source/staging revalidation.

The private target authority contains the real staging and target Drive IDs and therefore stays private. Sanitized production qualification evidence contains only hashes of those identities. It additionally binds the exact source commit/tree, source-manifest digest, mapping-manifest digest, private-pack digest, frozen canonical/Project/preservation inventory digests, frozen root-router digest when present, observed target inventory digests and terminal outcomes. It must explicitly state `cutover_authorized=false`.

If target construction has durably completed but any later source/freeze/staging revalidation or qualification-evidence publication fails, the failure is classified as **post-construction**. Evidence must not claim that no target exists. The constructed target is preserved for diagnosis and must not become active production merely because construction succeeded.

A production-target qualification PASS proves only that an exact new target has been constructed and accepted. It does not mutate the production selector and does not authorize cutover.

The exact clean Git worktree remains mandatory for candidate freeze and production-target qualification, where source commit/tree authority is established. After qualification PASS, transaction-bound pre-apply and post-cutover runtime verification must not depend on a Git checkout: it revalidates the immutable pack/freeze receipt against the source commit/tree already bound by production qualification and subsequent private cutover receipts.

## 9. Cutover transaction boundary

Cutover is separate from data publication.

The migration publication may complete successfully while the legacy Hub is still the active production Hub. A successful publication therefore means **new target constructed**, not **production switched**.

Cutover may occur only after all production-target acceptance checks PASS and explicit production cutover approval has been given.

The authoritative production selector is `/etc/keelaryn/hub.env`. It contains exactly one canonical `KEELARYN_HUB_ROOT_ID=<exact-root-id>` assignment. Google OAuth credentials remain in `/etc/keelaryn/drive.env`; production Hub selection must not be duplicated there or in another runtime convention.

`hub_cutover.py` owns the durable selector transaction. It shares `/var/lib/keelaryn/deployment/LOCK` and `ACTIVE_TRANSACTION.json` with release switching so source-release and Hub-cutover transactions cannot proceed concurrently. The active cutover record binds exact OLD Hub identity, exact NEW Hub identity, exact qualified source commit and exact cutover-tool bytes.

The production cutover sequence is:

1. confirm production-target qualification PASS and exact qualified runtime/Core/source identity;
2. stop and prove the production writer inactive;
3. `prepare` one Hub-selector transaction while selector is exact OLD; `prepare` must exclusively quiesce the production Drive mutation gate and durably inhibit all gate-participating mutations before active selector authority is published;
4. invoke only the transaction-bound pre-apply finalizer with explicit production-cutover enablement;
5. pre-apply finalization must bind exact PREPARED transaction + inhibit, freshly verify the qualified NEW target, freshly verify OLD legacy Drive bytes against the frozen source, publish/verify a private pre-apply receipt, revalidate transaction/inhibit identity at the commit boundary and only then invoke low-level selector `apply`;
6. require exact durable `APPLIED` / NEW while keeping the mutation inhibit active;
7. run fresh post-cutover read-only acceptance through `tests/live/run_migration_post_cutover_acceptance.py`;
8. require exact private pre-apply provenance, fresh NEW acceptance and a second fresh OLD-source verification before terminal acceptance;
9. publish/verify the private finalization receipt including the exact pre-apply receipt SHA and revalidate transaction/selector identity at the terminal commit boundary;
10. only the finalizer may invoke low-level terminal `accept`; immutable terminal/history authority must prove `ACCEPTED` before the exact mutation inhibit is released;
11. only after inhibit release and finalizer PASS may the NEW writer be started.

Direct manual selector `apply` and terminal `accept` are not accepted production procedures. The public Hub-cutover CLI exposes neither operation. Low-level Python primitives remain available only to transaction-bound finalizers, recovery and disposable qualification after fresh commit-boundary revalidation.

The production mutation gate is a separate root-controlled filesystem boundary. Poller `bootstrap/once/serve`, Workspace `create/update` and production-target qualification hold a shared lock for their entire live mutation lifetime. Hub `prepare` takes the exclusive lock, publishes one canonical sanitized inhibit bound to the exact Hub transaction, and only then publishes active cutover authority. The inhibit remains after low-level `ACCEPTED` settlement until terminal/history recovery has been verified; rollback releases it only after exact OLD plus durable `ROLLED_BACK`. Missing, malformed, mismatched or orphaned inhibit state fails closed.

The active Hub-cutover transaction also binds SHA-256 of the exact pre-apply and post-cutover finalizer bytes from the qualified release. A finalizer must prove its current file identity against that transaction before OAuth/Drive work and again at the relevant selector/terminal commit or recovery boundary. These hashes are transitively covered by the active-transaction SHA used by the mutation inhibit, private receipts and terminal/history authority. Finalizer drift blocks forward acceptance but must not block exact rollback to OLD.

The private pre-apply receipt binds at minimum transaction ID, SHA-256 of exact active transaction bytes, source commit/tree, frozen pack identity, OLD/NEW selector identity hashes, production qualification evidence hash and fresh target-acceptance evidence hash. The private terminal-finalization receipt additionally binds SHA-256 of that exact pre-apply receipt plus fresh post-cutover acceptance evidence. Public output exposes only sanitized hashes/outcomes and must not reveal Hub IDs or private paths.

If process response is lost after durable terminal acceptance, repeating the same finalizer with the same qualified source/runtime and private receipt must recover from immutable terminal/history authority without inventing a new transaction.

If durable selector `apply` succeeds but fresh post-cutover acceptance fails before terminal `ACCEPTED`, evidence must state that the durable cutover occurred. With the NEW writer still stopped, rollback restores the preserved OLD selector identity through the same cutover transaction; the system must not pretend selector mutation never happened.

## 10. Source drift between rehearsal and cutover

The migration rehearsal does not authorize using stale source bytes if the production Hub changes afterward.

Before final production construction/cutover, one of these must be true:

- the production source was intentionally frozen and fingerprints still match the qualified migration candidate; or
- an explicit final-delta migration candidate is built, rehearsed and qualified against the newer source identity.

Silent delta inference is forbidden.

## 11. Rollback

Rollback exists at two layers.

### Publication rollback

Before cutover, any migration publication failure uses the ordinary zero-based Core rollback rules on the new target. The legacy production Hub remains untouched and active.

### Cutover rollback before terminal acceptance

After selector `apply` but before durable terminal `ACCEPTED`, rollback means restoring `/etc/keelaryn/hub.env` to the preserved legacy production Hub identity while the NEW writer is stopped.

Cutover rollback must not copy zero-based target bytes back into the legacy Hub and must not rewrite the legacy Hub to resemble the new structure.

The failed zero-based target, private target authority, qualification evidence and finalization diagnostics are preserved for diagnosis until explicitly cleaned up.

If terminal `ACCEPTED` is already durable, the same cutover transaction cannot later become `ROLLED_BACK`. Any later production reversal requires a new, separately authorized selector transaction and fresh validation of the intended target; it is not recovery of the already accepted transaction.

## 12. Acceptance gates

Production migration is not approved until all applicable gates PASS against exact identities:

- migration plan/schema validation;
- source capture/fingerprint verification;
- private pack deterministic verification;
- disposable full rehearsal;
- exact Core/source commit qualification;
- real Google Drive target construction;
- migrated canonical inventory verification;
- preservation destination inventory verification;
- Workspace/Project/Reconciliation structural verification;
- restart/recovery verification;
- reader SAFE/epoch verification;
- production-target Doctor/SelfTest equivalent appropriate to zero-based architecture;
- cutover-pointer switch/rollback rehearsal on a disposable selector;
- transaction-bound post-cutover finalizer regression, including stale/mismatched evidence rejection and response-loss recovery;
- target-host selector/state filesystem and ownership checks;
- final fresh production-specific read-only acceptance bound to exact active cutover transaction;
- immutable terminal `ACCEPTED` verification before the NEW writer is started.

Development CI and disposable rehearsal are necessary evidence but are not production qualification by themselves.

## 13. Evidence and provenance

Migration evidence must bind at minimum:

- exact zero-based source commit/tree;
- migration candidate ID;
- source-manifest digest;
- mapping-manifest digest;
- private migration-pack digest;
- managed/imported canonical inventory digest;
- preservation destination inventory digest;
- Core/runtime identity;
- disposable rehearsal run identity;
- production construction evidence identity;
- cutover selector identity hash;
- SHA-256 of exact active cutover transaction authority;
- SHA-256 of fresh post-cutover acceptance evidence;
- terminal outcome and canonical epoch.

The private finalization receipt additionally binds real transaction-local authority but remains private on the target host.

Private source paths, payload bytes, Google Drive object IDs, account email addresses, OAuth credentials and local workstation paths are excluded from public repository evidence.

## 14. Cleanup policy

Do not clean migration source captures, private packs, disposable rehearsal evidence or failed targets until the corresponding evidence is durably recorded and the migration candidate is no longer needed for diagnosis or rollback.

After successful production cutover and acceptance, cleanup of disposable migration material is a separate explicit action. The legacy production Hub is retained until rollback retirement is separately approved.

## 15. Implementation order

The migration implementation must proceed in this order:

1. define strict migration source/mapping/pack schemas;
2. implement read-only source capture and deterministic pack builder/verifier;
3. add adversarial filesystem/Windows tests for source drift, reparse points, traversal, duplicates and byte-exactness;
4. implement disposable full-rehearsal orchestration using the existing Drive/Core path;
5. add restart/fault-injection coverage for migration preparation and publication;
6. define the exact production selector/cutover mechanism;
7. rehearse selector switch + rollback against disposable targets;
8. freeze a migration candidate only after coherent development PASS;
9. run production-target qualification;
10. request explicit production cutover approval;
11. perform selector apply and transaction-bound production acceptance;
12. start the NEW writer only after terminal acceptance PASS;
13. retain rollback source until separate retirement approval.

No earlier step implies permission to perform a later production step.
