# Keelaryn Manager 4.13.0

Manager 4.13.0 is the grouped post-4.12 development cycle for supported ChatGPT exchange/onboarding and development-workspace hygiene. It preserves Hub schemas, native update compatibility, rollback semantics, deterministic release construction and fail-closed validation boundaries unless a separately qualified change explicitly says otherwise.

The immutable development baseline is Manager 4.12.0. Gate Framework 2.0 r11 remains the reusable framework for this candidate unless reusable framework source actually changes.

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

## Development workspace hygiene

The intended tests lifecycle distinguishes current reusable framework source, disposable work, active/current expanded results and frozen archives. Disposable `tests/work` cleanup is explicit, dry-run first, reparse-safe and file-granular so temporary Windows directory locks do not become data-integrity failures.

`manager/state/history` remains protected from generic cleanup. Existing release-bundle retention already validates and archives reproducible Manager release bundles; 4.13 does not introduce a second competing release-retention policy.

## Update compatibility

Manager 4.13.0 preserves the native update compatibility floor in `product/manager_release.json`. UPDATE artifacts retain the established transition envelope used by supported older Manager validators.

Manager-only update commands clearly distinguish "no newer valid package" from failure and do not silently process Hub updates.

## User interface compatibility

Use `keelaryn\Keelaryn.cmd` or `manager\KEELARYN.cmd`.

The existing numeric main-menu contract is preserved to avoid breaking established Windows gate orchestration. ChatGPT is added as a separate lettered entry. Existing first-run Create, Connect and Main-menu choices keep their numeric meaning; ChatGPT setup is an additional optional path and remains reopenable later.

## Release gate

This source is not production-approved merely because it carries version 4.13.0. Production approval still requires the applicable Windows PowerShell 5.1 parser/static checks, Manager and frontend SelfTests, deterministic release/package checks, CURRENT-backed disposable 4.12.0 -> 4.13.0 native update, rollback/fault injection, migrations, Doctor, production immutability, UI regression coverage, public PR CI, exact tested/PR/post-merge/release artifact identity and gated publication.
