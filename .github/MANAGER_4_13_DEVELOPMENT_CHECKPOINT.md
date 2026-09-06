# Manager 4.13.0 development checkpoint

Date: 2026-09-06
Branch: `manager-4.13.0-lifecycle`
Baseline: public/production Manager 4.12.0 commit `576102227e749c3d0d47ae3e43fe3ba02946cfdd`
Gate Framework: r11 unchanged

## Durable state

The branch is the direct continuation of `manager-4.13.0`; no merge is required.

Old push-triggered/self-committing lifecycle workflow variants v1/v2/v3/v5 were retired. The only lifecycle workflow is a read-only Windows preflight with `contents: read` and `cancel-in-progress: true`.

Current staged lifecycle patch pipeline:

1. `.github/manager-4.13-lifecycle-fix1.py`
2. `.github/manager-4.13-lifecycle-fix2.py`
3. `.github/manager-4.13-lifecycle-fix4.py`
4. `.github/manager-4.13-lifecycle-fix5.py`
5. `.github/manager-4.13-lifecycle.py`

These helpers stage product changes only in the CI working tree. Lifecycle product changes are not yet materialized in the Git branch.

## Latest validated lifecycle preflight

Workflow run: `34049698469`
Job: `101530959491`
Validated staged head: `9ddf3f6597c875fc99b5a548229295e9298fe970`
Result: PASS

Staged product identity at that checkpoint:

- Manager version: 4.13.0
- managed files: 67
- INSTALLATION SHA-256: `5cf598b412168bde4f5e543c7a8eceb7f6170b22b7325c9e9b06bea6c316f32d`
- managed-content SHA-256: `de20a5936347758a0af4c7ff3b852ae348fb35c94c151ef4330c64aef90b18a0`

Windows preflight results:

- asserted lifecycle patch: PASS
- PowerShell parser: PASS
- managed executable ASCII policy: PASS
- qualification-compactor SelfTest: PASS
- file-reparse substitution regression: PASS
- unmapped file-reparse rejection: PASS
- reparse-directory rejection: PASS
- Manager SelfTest: PASS
- frontend SelfTest: PASS
- AI_CONTEXT generation: PASS
- public-repository boundary: PASS
- r11 SourceGate: PASS
- deterministic BuildRelease x2: PASS
- SOURCE/DISTRIBUTION/UPDATE transition boundary: PASS

Development-only SourceGate identity:

- gate revision: 9008 (diagnostic only; not a release qualification revision)
- gate ZIP SHA-256: `2517c54e96c8320596d09140d58a8c68c345066d2782803e506dd5084d4cd2c8`

## Reparse evidence contract

The staged compactor implements `keelaryn.reparse-substitution-map.v1`.

Rules validated on Windows:

- reparse-point directories are always rejected and never traversed;
- unknown/unmapped file reparse points fail closed;
- a mapped file reparse point is archived only through an explicitly protected regular non-reparse copy;
- the protected copy is bound by exact size and SHA-256;
- the archive uses the protected bytes under the original evidence relative path;
- original evidence attributes/timestamps plus substitution provenance are recorded in the manifest;
- changed/unused/unsafe bindings fail closed;
- cleanup deletes evidence links/files only after archive verification and never deletes the protected copy;
- Manager state history remains outside compaction cleanup scope.

The regression fixture deliberately uses a symlink target with bytes different from the protected copy and verifies that the protected bytes, not link-target bytes, enter the archive.

## ChatGPT architecture audit

The 4.13 branch satisfies the required normal-user architecture:

- `Keelaryn — Workspace`
- `Keelaryn — Chats`
- `Keelaryn — Chat Manager`

and optional:

- `Keelaryn — Manager Development`

The setup guide and all four project templates contain fresh-chat inputs, minimum launch prompts, role/must-not contracts, output artifacts, save locations and next-project routing. Exchange root is `exchange\chatgpt`.

## Governance findings

Verified current repository state:

- `main` branch protection: disabled (`protected=false`)
- repository rulesets: none
- public release workflow top-level permissions: `contents: read`
- only the `publish` job elevates to `contents: write`
- publication remains fail-closed and existing release assets are verified byte-identical rather than overwritten

Branch protection/ruleset hardening remains an unresolved repository-governance action.

## Exact UPDATE identity hardening

The repository now stages a stricter qualification/publication contract:

- `PUBLIC_PROVENANCE.json` contains `production_validation.tested_update_sha256`;
- an unqualified candidate must keep that value null/blank;
- a Full-Gate-qualified source must bind a valid exact tested UPDATE SHA-256 and gate revision;
- CI BuildRelease verifies its UPDATE SHA-256 against that Full-Gate identity when qualification is asserted;
- publish is permitted only for a push to `main`, not for a feature-branch/manual validation run;
- publish consumes the gated build artifact;
- an existing GitHub Release is accepted only when its relevant assets are byte-identical.

A dedicated read-only Windows self-test exercises exact-match and mismatched-hash paths. This block is awaiting a clean full preflight after the development checkpoint itself was portable-normalized.

## Source-hygiene note

Public verification still reports one Manager-source warning for the maintainer-local example retained in `manager/product/docs/TESTING.md`. Portable-normalize that product-source example before materializing final 4.13 product bytes. Do not modify frozen Gate Framework r11 merely to remove its separate historical documentation warning.

## Update UX / Doctor review

No additional product change is currently justified:

- Manager-only update no-op wording explicitly states that no newer valid Manager was found, the installed Manager remains unchanged, and Hub inbox was not processed;
- Hub update no-op distinguishes missing APPROVED state, pending CANDIDATEs and the reason;
- Doctor already emits machine-readable coded findings, timings and recommended actions;
- drift-related Doctor codes and recommendations are fail-closed and explicitly prohibit regenerating MANIFEST to hide drift.

## Next steps

1. obtain a clean full preflight for the exact UPDATE identity contract;
2. portable-normalize Manager TESTING documentation;
3. complete performance/context review, changing product bytes only where evidence justifies it;
4. materialize the fully validated staged lifecycle product changes in one controlled commit and remove staging helpers/workflow scaffolding;
5. run branch/PR CI and exact identity checks;
6. only then issue one normal Windows `manager-4.13.0.zip` for the consolidated user Full Gate via `UNPACK_MANAGER_GATE.cmd`.

Do not describe 4.13.0 as production-approved at this checkpoint.
