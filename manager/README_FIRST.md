# Keelaryn Manager 4.15.0

Manager 4.15.0 adds deterministic Workspace checkout canonical-title synchronization. Entity-bound checkouts keep `keelaryn.workspace.v1`, derive `source_entity_id` and `source_entity_title` from canonical project Markdown, surface `suggested_chat_title`, preserve legacy v1 packet readability, and provide a Chat Manager convergence path for existing customized Hubs. Gate Framework r12 remains unchanged.

The candidate baseline is the production-qualified Manager 4.14.1. Gate Framework 2.0 r12 remains the frozen reusable framework for this feature candidate; Framework source is unchanged from the independently Windows-qualified r12.


## Workspace checkout canonical-title synchronization

Workspace checkout generation now has an explicit canonical entity/title contract. For a scope resolving to exactly one project, canonical Markdown supplies the project `id` and H1. ROUTER may locate the file but cannot override the Markdown title. New entity-bound v1 packets carry `source_entity_id`, `source_entity_title`, and `suggested_chat_title`; legacy v1 packets remain accepted. Generic Genesis includes the Workspace Checkout prompt, and existing customized Hubs converge through Chat Manager rather than automatic governance overwrite.

`product/tools/Resolve-KeelarynWorkspaceCheckout.ps1 -SelfTest` exercises filename/H1 divergence, shortened aliases, exact entity IDs, explicit subscope suffixes, legacy packet compatibility, ROUTER/Markdown disagreement and ambiguous alias rejection. Manager SelfTest invokes the same contract test.

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

AI_CONTEXT continues to preserve complete managed source while exposing the monolithic runtime as exact AST-bound slices. Manager 4.14.1 makes each configured task route fail closed when an entry function or related managed file is missing and expands runtime recommendations to the deterministic transitive closure of internal Manager-function dependencies rather than only one direct-call level.

The task router records entry, direct-dependency, transitive-dependency and total recommended-function counts together with the runtime byte budget. The generator validates that every internal call made by the recommended closure remains inside that closure.

AI_CONTEXT also binds the build to a stable managed-source snapshot: source hashes captured before derived output construction must still match fresh source hashes at the end of the build, and every copied non-runtime managed file must match the final context-manifest hash. The canonical runtime SHA used for AST slicing is revalidated at the transaction boundary. Concurrent source mutation therefore fails the build rather than producing a mixed context.

## Development workspace hygiene

The tests workspace contract is explicit: `framework` holds one current reusable framework source, `work` is disposable, `results` holds active/current expanded evidence plus concise qualification indexes, and `archives` holds frozen verified history. Disposable `tests/work` cleanup is explicit, dry-run first, reparse-safe and file-granular. Completed Full Gate evidence can be compacted to a per-entry SHA-256-verified archive before expanded source cleanup; temporary empty-directory locks remain a cleanup state rather than a data-integrity failure.

`manager/state/history` remains protected from generic cleanup. Existing release-bundle retention already validates and archives reproducible Manager release bundles; this cycle does not introduce a second competing release-retention policy.

## Update compatibility

Manager 4.15.0 preserves the native update compatibility floor in `product/manager_release.json`. UPDATE artifacts retain the established transition envelope used by supported older Manager validators.

Manager-only update commands clearly distinguish "no newer valid package" from failure and do not silently process Hub updates.

## User interface compatibility

Use `keelaryn\Keelaryn.cmd` or `manager\KEELARYN.cmd`.

The existing numeric main-menu contract is preserved to avoid breaking established Windows gate orchestration. ChatGPT remains a separate lettered entry. Existing first-run Create, Connect and Main-menu choices keep their numeric meaning; ChatGPT setup remains an additional optional path and is reopenable later.

## Release gate

This source is not production-approved merely because it carries version 4.15.0. Production approval still requires the applicable Windows PowerShell 5.1 parser/static checks, Manager and frontend SelfTests, deterministic release/package checks, CURRENT-backed disposable 4.14.1 -> 4.15.0 native update, rollback/fault injection, migrations, Doctor, production immutability, UI regression coverage, public PR CI, exact tested/PR/post-merge/release artifact identity and gated publication.
