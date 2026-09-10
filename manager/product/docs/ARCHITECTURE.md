# Keelaryn architecture

Keelaryn has one product source tree and any number of instance-owned Hubs.

```text
manager/ product source
├── product/governance/hub   canonical generic governance overlay
├── product/starter/hub      minimal Genesis/user-state skeleton
├── product/migrations       explicit structural system transitions
└── product/docs             product documentation

                    manages
                       ↓
              hub instance
```

## Product / instance boundary

Product source contains no user instance state. Runtime files such as CURRENT checkpoints, inbox, history, logs, releases and local binding are not managed product source and cannot become release inputs.

## One governance source

Genesis and legacy namespace migration consume the same `product/governance/hub` overlay. The overlay owns the generic `_System` governance documents, `_System/GOVERNANCE.json`, and the canonical `Resources/Prompts/Workspace Checkout.md` prompt. The starter tree contains only the minimum Genesis/user-state skeleton.

`_System/GOVERNANCE.json` is an instance-side adoption receipt. It records the generic governance revision and contract-specific revisions actually adopted by that Hub. `product/release.json` declares the revisions expected by the running Manager.

`system_version` remains structural migration identity and is deliberately independent from `governance_revision`. This prevents a governance-only change from masquerading as a structural migration while still making drift machine-readable.

Existing Hubs are never overwritten from the generic overlay during a Manager update. Doctor reports missing/stale/newer governance; convergence is performed through Chat Manager and the normal CANDIDATE -> APPROVED -> CURRENT lifecycle.

The starter tree contains only the minimum canonical skeleton needed to instantiate user-owned state. Synthetic sample Hubs are not embedded in the Manager source tree.

## Identity

`instance_id` is stable for the lifetime of a Hub. `artifact_id` identifies a checkpoint. Product `release_id` identifies a generic structural system release. `governance_revision` identifies the adopted generic-governance contract. These identifiers are not interchangeable.

## Runtime binding

Binding v2 records absolute path plus stable instance identity. Paths may change; instance identity does not. Ambiguous discovery is blocked and explicit Maintenance > Bind existing Hub (legacy alias `BIND_INSTANCE.cmd`) is available.

## Portable inventory and lifecycle isolation

Canonical Hub inventory prunes `.git/**`, `.obsidian/**` and shell-local files before recursion, rejects non-local reparse points and detects Windows/Unicode path collisions. Content and payload identities are calculated in one pass per file.

Manager-only modes (`-UpdateManager`, `-SelfTest`, `-BuildDistribution`, `-BuildRelease`, `-BuildAIContext`) are Hub-blind unless explicit binding is requested.

## AI development surface

The managed AI-context generator derives a lossless runtime segment map, call/caller function map, task routes and exact managed-source mirrors. Within one build it reuses the already decoded runtime text for parser and lexical validation rather than reopening the runtime. It is a derived development surface, never a second runtime implementation.

## Performance invariants

Portable Hub analysis is single-pass per explicit snapshot: each portable file is hashed once to derive full content identity, payload identity, and source-manifest identity. Safety-critical commit checks deliberately take a fresh snapshot rather than reusing stale analysis. Manager UPDATE validation opens each package once per validation pass, performs envelope safety checks against that same archive handle, and indexes ZIP entries once instead of reopening or rescanning the archive for every declared file. Fresh staged-package validation remains a separate pass at the install boundary.

Hub ZIP inspection uses short-lived per-operation sessions for read-only validation paths. A session validates the archive envelope once and derives portable content/payload/source-manifest hashes from one entry-hash pass; callers may reuse that immutable snapshot only within the current operation. Transaction and commit boundaries still perform fresh installed-state validation and never rely on a process-global cache.

Doctor's governance compatibility read is bounded to the canonical `_System/GOVERNANCE.json` receipt and does not rewrite the Hub. Structural migration planning remains a separate check.

## Windows lock diagnostics

Sharing/lock failures remain fail-closed. On the terminal Windows sharing/lock violation, Manager queries the Windows Restart Manager API for processes or services that currently use the affected file and adds bounded owner metadata (PID, application/service name, application type and restartability) to the error. The diagnostic path is lazy, read-only, and never calls Restart Manager shutdown or restart operations. Failure of the diagnostic query never changes the underlying transaction decision.

Doctor's healthy-MANIFEST path stops after exact ordered entry equality is proven; expensive missing/extra/changed classification is constructed only on mismatch. `DOCTOR_REPORT.json` also records fine-grained read-only Hub sub-timings so further optimization is measurement-driven rather than cache-driven.

Candidate transport is a secondary, non-canonical resilience channel. `keelaryn.hub.candidate-transport.v1` stores only a bounded deterministic portable-tree delta from an exact CURRENT reconstruction identity to a validated artifact-v3 CANDIDATE. Embedded bytes are Base64 with independent length/SHA-256 checks. Reconstruction revalidates the resulting complete Hub and emits a complete CANDIDATE ZIP; it never bypasses Chat Manager approval or participates in automatic Hub installation.

## User-facing and repository boundaries

The interactive frontend lives under `product/tools` and delegates every operational action back to the single Manager runtime. The optional root `Keelaryn.cmd` is generated local convenience state and is intentionally outside the managed product set.

Installed production state and public repository source are related but not identical views. The repository's managed `manager/` tree is release source; installed Manager adds local runtime state, while the personal Hub remains outside generic source.
