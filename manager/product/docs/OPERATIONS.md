# Operations

Keelaryn Manager separates diagnostics, explicit binding, Manager product updates, Hub instance updates, transport repair and release construction.

## Preflight

Run Doctor (menu; compatibility command `compat/commands/DOCTOR.cmd`) before major migrations, after moving Manager/Hub folders, or when an update is rejected. Doctor is read-only with respect to canonical Hub state and writes `state/logs/DOCTOR_REPORT.json`.

Exit codes:

- `0` — no findings requiring attention;
- `2` — warnings exist, but no integrity error was detected;
- `1` — one or more integrity/binding errors were detected.

## Binding

`BIND_INSTANCE.cmd <path>` explicitly binds one Manager runtime to one existing Hub. Binding v2 stores both absolute path and, when available, `instance_id`. If a stored path becomes stale after a move, Manager may recover by matching the stable `instance_id` among sibling Hub instances; ambiguous discovery is refused.

## Manager updates

Use Maintenance > Update Manager (legacy alias `UPDATE_MANAGER.cmd`). It scans and installs only Manager product packages. Hub CANDIDATE/APPROVED packages are not evaluated or changed. A Manager self-update restarts into the same explicit Manager-only mode until no newer compatible Manager package remains.

Before snapshot or mutation, every managed destination is checked against the live filesystem. Existing managed targets must be regular non-reparse files, existing parents must be real directories, and reparse-point/directory collisions are rejected before update writes begin. The same target-safety check is repeated at the mutation and rollback boundaries.

## Hub updates

Use Maintenance > Update Hub (legacy alias `UPDATE_HUB.cmd`). It does not scan or install Manager packages. Worker CANDIDATEs remain pending for Chat Manager; only validated APPROVED artifacts can replace the canonical Hub.

## Combined updates

Use Maintenance > Update Manager + Hub (legacy alias `UPDATE_ALL.cmd`) only when both layers are intentionally being serviced. Manager packages are resolved first. After the Manager chain is current, the newly installed Manager evaluates Hub APPROVED packages. A Manager conflict or failed self-test blocks the Hub phase.

This explicit three-command contract prevents a generic “inbox” action from silently changing a different lifecycle layer.

## Portable checkpoints

`.obsidian/**`, `.git/**`, `desktop.ini`, `Thumbs.db`, and `.DS_Store` are local deployment state. They are excluded from portable hashes and packages. `.gitignore` is not excluded merely because its name begins with `.git`.

Incoming Hub ZIPs containing local deployment state are rejected. Update commands never sanitize CURRENT transport implicitly.

## Transport repair

Maintenance > Repair CURRENT transport (compatibility command `compat/commands/REPAIR_CURRENT_TRANSPORT.cmd`) is the explicit maintenance action for older CURRENT ZIPs that accidentally captured local deployment state. It validates STATE, ARTIFACT and payload identity before and after rewriting the ZIP. Product updates, Hub updates and Doctor (menu; compatibility command `compat/commands/DOCTOR.cmd`) never perform this repair as a startup side effect.

Doctor emits ordered `recommended_actions` in the JSON report for actionable findings such as stale binding, non-portable CURRENT transport, registered migrations, baseline divergence, or invalid Manager packages. Recommendations never mutate the Hub automatically.

After Manager update selection, valid Manager packages that are older than the installed version, or exact same-content copies of the installed version, are moved from `state/inbox` to `state/history/manager_packages/`. Cleanup reuses the package objects already validated during update decision-making instead of reopening those ZIPs. Divergent same-version packages and invalid/unrecognized ZIPs are never silently removed.

## AI development context

Run Development > Build AI_CONTEXT (legacy alias `BUILD_AI_CONTEXT.cmd`) to build a compact development handoff. Manager-only build/update/self-test commands are Hub-blind, so a missing or broken Hub cannot block them.

## Locked-file diagnostics

Manager retries only Windows sharing/lock violations in the operations that explicitly permit bounded retry. If the final retry is still blocked, it queries Windows Restart Manager and reports the detected lock owners with PID and application/service identity when available. This is diagnostic only: Keelaryn never terminates, shuts down or restarts the reported process automatically. The original sharing/lock IOException remains in the exception chain so error classification stays fail-closed.

`manager.log` is diagnostic state, not a transaction boundary. Its primary append path keeps bounded sharing-lock retry; if an external process still holds only a transient sharing lock after that budget, Manager writes the diagnostic line to a unique `manager_fallback_*.log` when possible and continues the requested operation. A transient lock also defers log rotation rather than blocking startup. Non-transient log filesystem failures still fail hard. This relaxation applies only to diagnostic logging; Manager locks, update/rollback state, packages, CURRENT and Hub writes retain their existing fail-closed behavior.

Doctor timing telemetry includes `hub_state_core_ms`, `hub_portable_analysis_ms`, `hub_derived_metadata_ms`, `hub_manifest_diagnostic_ms`, `hub_migration_ms`, `hub_artifact_ms`, and `current_baseline_ms` in addition to the existing phase totals. These values are diagnostic-only and do not relax fresh Hub/CURRENT validation.

## Development test workspace

Run Development > Prepare tests workspace (legacy alias `PREPARE_TESTS.cmd`) on the canonical installation before Manager development gates. It creates and validates `tests/work` and `tests/results`, writes `tests/WORKSPACE.json`, and reports legacy/unclassified top-level entries without moving or deleting them. Candidate packs and disposable fixtures go under `work`; gate summaries, transcripts and raw benchmark reports go under `results`. `legacy-layout-backup` remains reserved for explicit layout finalization.
## Hub candidate transport fallback

Development > Build CANDIDATE transport (legacy alias `BUILD_CANDIDATE_TRANSPORT.cmd`) and Development > Restore CANDIDATE transport (legacy alias `RESTORE_CANDIDATE_TRANSPORT.cmd`) are explicit non-installing transport-resilience actions. ZIP remains the primary CANDIDATE checkpoint. The JSON fallback is a deterministic Base64 delta against an exact CURRENT identity and may only reconstruct a CANDIDATE ZIP after path, byte, hash, ancestry and full Hub metadata validation. Neither command modifies Hub, CURRENT or APPROVED state. See `CANDIDATE_TRANSPORT.md`.

## Interactive frontend

Prefer `KEELARYN.cmd` for human-operated workflows. The frontend only orchestrates existing explicit Manager modes and does not bypass update/package validation. Its package picker copies a selected Manager UPDATE or Hub APPROVED ZIP into `state/inbox`, verifies the copied bytes by SHA-256, and then invokes the corresponding canonical update action.

The menu quick-status header is not a health assertion. Use Doctor for authoritative diagnostics.

### Filesystem-finalization handoff

During the one-time 4.7.2 -> 4.8.7 transition, a hidden root `_logs` directory may exist briefly after the update subprocess returns. It is a compatibility handoff for the still-running 4.7.2 parent, not canonical state. The next 4.8.7 Manager invocation completes the handoff, merges any final legacy-parent log line into `state/logs/manager.log`, removes root `_logs`, and records completion in `state/layout.json`.

<!-- multi-hub-operations-v1 -->
## Multi-Hub operations

Enable multi-Hub once from the existing canonical Hub. Initialization creates an instance-owned CURRENT without changing Hub portable content.

Use **Manage Hubs** to list, switch, create or connect Hubs. Creating a Hub uses Genesis in a staging transaction and registers it only after Hub/CURRENT identity validation succeeds. Creation does not switch the active Hub automatically.

Never copy a Hub directory to create another instance. A new Hub must receive a new Genesis `instance_id`. A connected existing Hub must already contain a consistent canonical identity.

<!-- diagnostic-log-append-resilience-v1 -->
### Diagnostic log append resilience

Manager diagnostic logging uses an explicit .NET file append primitive rather than the PowerShell `Add-Content` cmdlet. Ordinary readers may coexist with the log writer; competing/exclusive write locks remain subject to bounded retry and fallback-log handling. Diagnostic sink failures must not weaken transaction locks or package/Hub validation.
