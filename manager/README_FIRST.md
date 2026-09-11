# Keelaryn Manager 4.17.5
Manager 4.17.4 is the corrective successor to rejected candidate 4.17.3. It generalizes fail-if-exists directory publication to per-instance state creation, performs fresh published-baseline validation immediately before registry commits, and preserves/reports durable or ambiguous registered-Genesis commit outcomes without destructive rollback.

## 4.17.3 context
Manager 4.17.3 is the corrective successor to the production-qualified but public-release-rejected 4.17.2. It binds ChatGPT CURRENT source/destination to one captured Hub instance and makes registered Genesis directory publication fail closed if a destination becomes occupied at the commit boundary.

## 4.17.2 context
Manager 4.17.2 is the corrective successor to rejected public-release candidate 4.17.1. Final review after successful 4.17.1 g3 and production acceptance found three edge-case defects in newly introduced multi-Hub paths: committed registration state could be deleted after a later activation failure, frontend registry metadata could supply a non-GUID path segment, and interactive registered Genesis cancellation was misclassified as failed staging.

4.17.2 preserves the qualified 4.17.1 product architecture and Framework r24 contracts while correcting those transaction/path/cancellation boundaries. Existing Hub bytes are not migrated or rewritten by this Manager-only correction.

## Earlier release context

Manager 4.16.3 is the corrective successor to rejected candidate 4.16.2. Framework r22 CURRENT-backed Full Gate exposed a runtime-resilience defect: a transient Windows sharing lock on `state/logs/manager.log` held by an external synchronization process could abort a Manager command before its operation/transaction boundary even though the blocked file was diagnostic state rather than canonical Manager or Hub state.

Manager 4.16.3 preserves the 4.16.2 governance, migration, UPDATE compatibility, Doctor-warning UI and data-safety contracts. The correction is intentionally narrow: the primary `manager.log` keeps bounded sharing-lock retries; after a terminal transient sharing violation the diagnostic line is redirected to a unique `manager_fallback_*.log` when possible, and a transient failure of both diagnostic sinks does not block the requested Manager operation. Non-transient logging failures remain hard failures. Log rotation likewise skips only transient sharing locks.

This resilience exception applies only to diagnostics. Manager state mutations, package publication, CURRENT/Hub writes, update/rollback boundaries and Manager locking remain fail-closed. Existing Hubs are never rewritten automatically to clear governance drift. Gate Framework r22 remains unchanged and is the reusable qualification framework for this successor candidate.

## Governance compatibility

`product/release.json` now declares generic governance independently of `system_version`: `keelaryn.hub-governance.v1`, governance revision 1, `keelaryn.workspace.v1`, and Workspace checkout revision 1. The corresponding Hub-side `_System/GOVERNANCE.json` is canonical adoption evidence rather than derived metadata.

The canonical `product/governance/hub` overlay owns both the `_System` governance documents and `Resources/Prompts/Workspace Checkout.md`. `product/starter/hub` remains the minimal Genesis/user-state skeleton. Existing Hubs are not replaced from either tree during a Manager update.

Doctor reports structural migration status and governance compatibility separately. Missing/stale governance or a contract mismatch requires Chat Manager reconciliation; governance newer than the running Manager requires Manager compatibility review and is never downgraded automatically.

## Workspace checkout canonical-title synchronization

The existing Workspace checkout entity/title contract remains `keelaryn.workspace.v1`. For a scope resolving to exactly one project, canonical Markdown supplies the project `id` and H1. ROUTER may locate the file but cannot override the Markdown title. Entity-bound v1 packets carry `source_entity_id`, `source_entity_title`, and `suggested_chat_title`; legacy v1 packets remain readable.

`product/tools/Resolve-KeelarynWorkspaceCheckout.ps1 -SelfTest` continues to exercise filename/H1 divergence, shortened aliases, exact entity IDs, quoted `type`/`id` frontmatter scalars, exact-ID precedence over normalized alias collisions, explicit subscope suffixes, legacy packet compatibility, ROUTER/Markdown disagreement and ambiguous alias rejection. Manager SelfTest invokes the same contract test.

## Canonical installed layout

```text
keelaryn/
├── Keelaryn.cmd
├── manager/
│   ├── KEELARYN.cmd
│   ├── README_FIRST.md
│   ├── product/
│   ├── compat/
│   │   └── commands/
│   └── state/
│       ├── baseline/
│       ├── inbox/
│       ├── logs/
│       ├── history/
│       ├── releases/
│       ├── work/
│       ├── binding.json          (when bound)
│       └── layout.json
├── hub/
├── tests/
└── exchange/
    └── chatgpt/
```

`exchange/chatgpt` is user-facing exchange state, not Manager runtime state and not canonical Hub state.

## ChatGPT architecture

The complete Standard setup for a normal user is:

```text
Keelaryn — Workspace
Keelaryn — Chats
Keelaryn — Chat Manager
```

`Keelaryn — Manager Development` is optional and is only for contributors/system-level Keelaryn development.

Manager ships authoritative copy-ready Project instruction templates under:

```text
manager/product/docs/chatgpt-projects
```

The supported artifact flow is:

```text
CURRENT
  -> Workspace
  -> WORKSPACE_CHECKOUT
  -> Chats
  -> HUB_RETURN / HUB_RETURN_INTERIM
  -> Chat Manager
  -> APPROVED
  -> local Manager
  -> next CURRENT
```

The Manager frontend can prepare CURRENT for Workspace or Chat Manager and opens the supported exchange location. Legacy `Inputs_outputs` migration is copy-only, rejects reparse points, verifies copied bytes with SHA-256 and never deletes the source automatically.

## AI_CONTEXT correctness

AI_CONTEXT preserves complete managed source while exposing the monolithic runtime as exact AST-bound slices. Task routes fail closed when an entry function or related managed file is missing and use the deterministic transitive closure of internal Manager-function dependencies rather than only one direct-call level.

The task router records entry, direct-dependency, transitive-dependency and total recommended-function counts together with the runtime byte budget. The generator validates that every internal call made by the recommended closure remains inside that closure.

AI_CONTEXT also binds the build to a stable managed-source snapshot: source hashes captured before derived output construction must still match fresh source hashes at the end of the build, and every copied non-runtime managed file must match the final context-manifest hash. The canonical runtime SHA used for AST slicing is revalidated at the transaction boundary. Concurrent source mutation therefore fails the build rather than producing a mixed context.

## Development workspace hygiene

The tests workspace contract is explicit: `framework` holds one current reusable framework source, `work` is disposable, `results` holds active/current expanded evidence plus concise qualification indexes, and `archives` holds frozen verified history. Disposable `tests/work` cleanup is explicit, dry-run first, reparse-safe and file-granular. Completed Full Gate evidence can be compacted to a per-entry SHA-256-verified archive before expanded source cleanup; temporary empty-directory locks remain a cleanup state rather than a data-integrity failure.

`manager/state/history` remains protected from generic cleanup. Existing release-bundle retention validates and archives reproducible Manager release bundles.

## Update compatibility

Manager 4.16.3 preserves the native update compatibility floor in `product/manager_release.json`. UPDATE artifacts retain the established transition envelope used by supported older Manager validators. The normal production qualification transition for this candidate is Manager 4.15.1 -> 4.16.3.

Manager-only update commands continue to distinguish "no newer valid package" from failure and do not silently process Hub updates. Installing Manager 4.16.3 alone must not change the personal Hub or its governance receipt.

## User interface compatibility

Use `keelaryn\Keelaryn.cmd` or `manager\KEELARYN.cmd`.

The existing numeric main-menu contract is preserved to avoid breaking established Windows gate orchestration. ChatGPT remains a separate lettered entry. Existing first-run Create, Connect and Main-menu choices keep their numeric meaning; ChatGPT setup remains an additional optional path and is reopenable later.

## Release gate

This source is not production-approved merely because it carries version 4.16.3. Production approval requires the applicable Windows PowerShell 5.1 parser/static checks, Manager and frontend SelfTests, deterministic SOURCE/DISTRIBUTION/UPDATE/AI_CONTEXT checks, disposable 4.15.1 -> 4.16.3 update and rollback/fault-injection coverage, Doctor governance-current/stale/newer cases, Genesis receipt validation, migration regression coverage, production Hub immutability, UI regression coverage, exact tested/public-source/release artifact identity, and gated publication. The consolidated Full Gate must use exact Gate Framework r22 and r22 must complete independent qualification/freeze before final Manager publication.
